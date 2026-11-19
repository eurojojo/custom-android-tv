#!/usr/bin/env python3
"""tvfeed: laatste NextPVR-opnames als 16:9-kaarten + lijst (JSON) voor de Thomson-app.

Draait in een Docker-container op de NextPVR-server en doet twee dingen:
  1. elke TVFEED_INTERVAL seconden: opnamelijst ophalen (NextPVR-API, login met PIN uit /secrets.json),
     per opname een plaatje zoeken en er een kaart van maken in /out/cards/<id>.jpg, plus /out/recordings.json;
  2. /out serveren op poort 8871 (alleen lezen).

Plaatje per opname, in volgorde van voorkeur:
  a. een plaatje naast het opnamebestand (zelfde naam, of folder/poster/fanart in dezelfde map);
  b. de artwork-URL ("DeferredArtwork") die NextPVR bij het programma bewaart (uit npvr.db3);
  c. NextPVR's eigen show-artwork (config/media/shows/<Titel>.fanart|landscape|jpg);
  d. een gegenereerde kaart (kleurverloop + zenderlogo).
"""
import base64
import hashlib
import http.server
import json
import os
import re
import socketserver
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request

import card_render

OUT = "/out"
CARDS = os.path.join(OUT, "cards")
ART_CACHE = os.path.join(OUT, "art")
HERO = os.path.join(OUT, "hero")
HOST = os.environ.get("NEXTPVR_HOST", "127.0.0.1")
PORT = os.environ.get("NEXTPVR_PORT", "8866")
INTERVAL = int(os.environ.get("TVFEED_INTERVAL", "600"))
MAX_ITEMS = 40
CARD_ITEMS = 30
CARD_VERSION = "v4"  # ophogen als de kaartjes anders getekend worden: Projectivy cachet plaatjes op URL
BASE = "http://%s:%s/services/service?" % (HOST, PORT)
EXT = (".jpg", ".jpeg", ".png", ".webp")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def call(**kw):
    kw["format"] = "json"
    with urllib.request.urlopen(BASE + urllib.parse.urlencode(kw), timeout=15) as r:
        return json.load(r)


def get_bytes(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "tvfeed/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def read_if(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


# ---------- plaatje zoeken ----------
def real_path(p):
    """NextPVR noemt oudere opnames /recordings/legacy/...; beide wijzen naar dezelfde map, die wij als /recordings/new mounten."""
    return (p or "").replace("/recordings/legacy/", "/recordings/new/", 1)


def sidecar_art(filepath):
    """a. plaatje naast het opnamebestand."""
    filepath = real_path(filepath)
    if not filepath or not os.path.isabs(filepath):
        return None
    base, _ = os.path.splitext(filepath)
    for e in EXT:
        for cand in (base + e, filepath + e):
            data = read_if(cand)
            if data:
                return data
    folder = os.path.dirname(filepath)
    for name in ("fanart", "landscape", "backdrop", "poster", "folder", "cover"):
        for e in EXT:
            data = read_if(os.path.join(folder, name + e))
            if data:
                return data
    return None


def db_art_url(rec_id):
    """b. artwork-URL die NextPVR bij het programma bewaart."""
    try:
        con = sqlite3.connect("file:/npvr.db3?mode=ro", uri=True, timeout=5)
        row = con.execute("select event_details from SCHEDULED_RECORDING where oid=?", (int(rec_id),)).fetchone()
        con.close()
    except Exception as e:
        log("db-fout", e)
        return None
    if not row or not row[0]:
        return None
    m = re.search(r"<DeferredArtwork>(.*?)</DeferredArtwork>", row[0], re.S)
    return m.group(1).replace("&amp;", "&").strip() if m else None


def cached_download(rec_id, url):
    path = os.path.join(ART_CACHE, "%s.img" % rec_id)
    data = read_if(path)
    if data:
        return data
    data = get_bytes(url)
    if data and len(data) > 1000:
        write_atomic(path, data)
        return data
    return None


def show_art(title):
    """c. NextPVR's eigen show-artwork op titel (exact, daarna 'begint met')."""
    base = "/nextpvr-media/shows"
    try:
        names = os.listdir(base)
    except OSError:
        return None
    low = {n.lower(): n for n in names}
    t = title.lower()
    for suf in (".fanart", ".landscape", ""):
        for e in (".jpg", ".png"):
            hit = low.get(t + suf + e)
            if hit:
                return read_if(os.path.join(base, hit))
    for suf in (".fanart", ".landscape", ""):
        for n in sorted(names):
            nl = n.lower()
            if nl.startswith(t + " ") and nl.endswith(suf + ".jpg") and (suf or nl.count(".") == 1):
                return read_if(os.path.join(base, n))
    return None


def find_art(rec):
    data = sidecar_art(rec.get("file", ""))
    if data:
        return data, "sidecar"
    url = db_art_url(rec["id"])
    if url:
        data = cached_download(rec["id"], url)
        if data:
            return data, "epg"
    data = show_art(rec.get("name", ""))
    if data:
        return data, "show"
    return None, "geen"


# ---------- bibliotheek: nieuwe films en afleveringen ----------
LIB_CONFIG = "/library.json"   # niet in de repo; zie library.example.json


def library_cfg():
    """{"roots": [{"mount": "/lib/1", "movies": [mapnamen], "series": [mapnamen]}], "kodi_shares": {sharenaam: mount}}"""
    try:
        return json.load(open(LIB_CONFIG, encoding="utf-8"))
    except Exception:
        return {"roots": [], "kodi_shares": {}}


VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".iso")
LIB_TTL = 3600
N_FILMS, N_EPS = 6, 6
_lib = {"t": 0, "data": {"movies": [], "episodes": []}}


def _titel_jaar(naam):
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", naam)
    return (m.group(1), m.group(2)) if m else (naam, "")


def _nieuwste_video(pad):
    """(mtime, bestandspad) van het nieuwste videobestand direct in of onder pad (max 2 niveaus)."""
    beste = (0, None)
    try:
        for e in os.scandir(pad):
            if e.is_file() and e.name.lower().endswith(VIDEO_EXT):
                mt = e.stat().st_mtime
                if mt > beste[0]:
                    beste = (mt, e.path)
            elif e.is_dir():
                for e2 in os.scandir(e.path):
                    if e2.is_file() and e2.name.lower().endswith(VIDEO_EXT):
                        mt = e2.stat().st_mtime
                        if mt > beste[0]:
                            beste = (mt, e2.path)
    except OSError:
        pass
    return beste


def scan_library():
    films, afl = [], []
    for rootcfg in library_cfg().get("roots", []):
        root = rootcfg["mount"]
        for sub in list(rootcfg.get("movies", [])) + list(rootcfg.get("series", [])):
            is_series = sub in rootcfg.get("series", [])
            base = os.path.join(root, sub)
            if not os.path.isdir(base):
                continue
            try:
                entries = [e for e in os.scandir(base) if e.is_dir()]
            except OSError:
                continue
            for e in entries:
                titel, jaar = _titel_jaar(e.name)
                if is_series:
                    # alleen de nieuwste seizoenmap(pen) bekijken
                    try:
                        seizoenen = sorted((x for x in os.scandir(e.path) if x.is_dir()), key=lambda x: x.stat().st_mtime, reverse=True)[:2]
                    except OSError:
                        continue
                    beste = (0, None)
                    for sz in seizoenen:
                        b = _nieuwste_video(sz.path)
                        if b[0] > beste[0]:
                            beste = b
                    if beste[1]:
                        m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", os.path.basename(beste[1]))
                        sub_t = "S%02dE%02d" % (int(m.group(1)), int(m.group(2))) if m else ""
                        afl.append({"kind": "aflevering", "title": titel, "year": jaar, "sub": sub_t,
                                    "mtime": int(beste[0]), "path": beste[1]})
                else:
                    mt, pad = _nieuwste_video(e.path)
                    if pad:
                        films.append({"kind": "film", "title": titel, "year": jaar, "sub": "",
                                      "mtime": int(mt), "path": pad})
    films.sort(key=lambda r: r["mtime"], reverse=True)
    afl.sort(key=lambda r: r["mtime"], reverse=True)
    for r in films + afl:
        r["id"] = "lib-" + md5(r["path"])[:10]
    return {"movies": films[:N_FILMS], "episodes": afl[:N_EPS]}


def library():
    if time.time() - _lib["t"] > LIB_TTL:
        try:
            _lib["data"] = scan_library()
            _lib["t"] = time.time()
            log("bibliotheek: %d films, %d afleveringen" % (len(_lib["data"]["movies"]), len(_lib["data"]["episodes"])))
        except Exception as e:
            log("bibliotheek-scan mislukt", repr(e))
    return _lib["data"]


def _norm(s):
    s = s.lower().replace("1", "i").replace("0", "o").replace("3", "e").replace("4", "a").replace("5", "s")
    return re.sub(r"[^a-z]+", " ", s).strip()


def _omdb(apikey, **kw):
    kw["apikey"] = apikey
    try:
        with urllib.request.urlopen("https://www.omdbapi.com/?" + urllib.parse.urlencode(kw), timeout=12) as resp:
            return json.load(resp)
    except Exception as e:
        log("omdb-fout", kw.get("t") or kw.get("s"), repr(e))
        return {}


def omdb_poster_url(apikey, r):
    """Zoekt een poster-URL: exacte titel+jaar, dan zonder jaar, dan zoeken met jaar±1 en de beste titelovereenkomst."""
    import difflib
    typ = "movie" if r["kind"] == "film" else "series"
    titel, jaar = r["title"], r["year"]
    nt = _norm(titel)
    kandidaten = []
    for t in dict.fromkeys([titel, re.sub(r"(?<=[A-Za-z])1(?=[A-Za-z])", "i", titel)]):
        for y in ([jaar, None] if jaar else [None]):
            q = {"t": t, "type": typ}
            if y:
                q["y"] = y
            info = _omdb(apikey, **q)
            if info.get("Response") == "True" and info.get("Poster", "N/A") != "N/A":
                return info["Poster"]
    # zoeken: eerst op de hele titel, dan op de eerste drie woorden, met jaar-1/jaar/jaar+1 en zonder jaar
    zoek = [titel, " ".join(titel.split()[:3])]
    jaren = ([str(int(jaar) + d) for d in (0, 1, -1)] if jaar and jaar.isdigit() else []) + [None]
    for zt in dict.fromkeys(zoek):
        for y in jaren:
            q = {"s": zt, "type": typ}
            if y:
                q["y"] = y
            info = _omdb(apikey, **q)
            for x in (info.get("Search") or []) if info.get("Response") == "True" else []:
                if x.get("Poster", "N/A") == "N/A":
                    continue
                kandidaten.append((difflib.SequenceMatcher(None, nt, _norm(x.get("Title", ""))).ratio(), x["Poster"]))
            if kandidaten:
                break
        if kandidaten:
            break
    kandidaten.sort(reverse=True)
    if kandidaten and kandidaten[0][0] >= 0.6:
        return kandidaten[0][1]
    return None


def library_poster(r):
    """OMDb-poster (titel + jaar), eenmalig gedownload en gecachet; geen sleutel of geen treffer -> None."""
    key = md5("%s|%s|%s" % (r["kind"], r["title"], r["year"]))[:12]
    path = os.path.join(ART_CACHE, "lib_%s.img" % key)
    miss = path + ".none"
    data = read_if(path)
    if data:
        return data
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 7 * 86400:
        return None
    try:
        sec = json.load(open("/secrets.json", encoding="utf-8"))
    except Exception:
        sec = {}
    apikey = sec.get("omdb_key")
    if not apikey and not sec.get("tvdb_key"):
        return None
    # TheTVDB eerst: grotere posters (±680x1000, OMDb levert maar 380x562, wat op het grote beeld vaag is) en
    # spelling/aliassen sluiten aan bij de mapnamen. OMDb is de terugval.
    data = None
    for bron in ("tvdb", "omdb"):
        url = tvdb_poster_url(sec, r) if bron == "tvdb" else (omdb_poster_url(apikey, r) if apikey else None)
        data = get_bytes(url) if url and url.startswith("http") else None
        if data and len(data) > 1000:
            break
        data = None
    if data and len(data) > 1000:
        write_atomic(path, data)
        return data
    open(miss, "w").close()
    return None


_tvdb = {"token": None, "t": 0}


def tvdb_poster_url(sec, r):
    """Zoekt in TheTVDB v4 op titel (ook aliassen); nodig: tvdb_key (en evt. tvdb_pin) in secrets.json."""
    key = sec.get("tvdb_key")
    if not key:
        return None
    import difflib
    try:
        if not _tvdb["token"] or time.time() - _tvdb["t"] > 20 * 86400:
            body = {"apikey": key}
            if sec.get("tvdb_pin"):
                body["pin"] = sec["tvdb_pin"]
            req = urllib.request.Request("https://api4.thetvdb.com/v4/login", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                _tvdb["token"] = json.load(resp)["data"]["token"]
                _tvdb["t"] = time.time()
        typ = "movie" if r["kind"] == "film" else "series"
        q = urllib.parse.urlencode({"query": r["title"], "type": typ})
        req = urllib.request.Request("https://api4.thetvdb.com/v4/search?" + q,
                                     headers={"Authorization": "Bearer " + _tvdb["token"]})
        with urllib.request.urlopen(req, timeout=12) as resp:
            res = json.load(resp).get("data") or []
    except Exception as e:
        log("tvdb-fout", r["title"], repr(e))
        return None
    nt = _norm(r["title"])
    beste = (0.0, None)
    for x in res:
        namen = [x.get("name", "")] + list(x.get("aliases") or []) + [x.get("translations", {}).get("nld", "")]
        score = max(difflib.SequenceMatcher(None, nt, _norm(n)).ratio() for n in namen if n)
        if r["year"] and str(x.get("year", "")) == r["year"]:
            score += 0.05
        img = x.get("image_url") or x.get("thumbnail")
        if img and score > beste[0]:
            beste = (score, img)
    return beste[1] if beste[0] >= 0.75 else None


# ---------- kijkvoortgang en volgorde ----------
def playback_positions():
    """{bestandsnaam: (positie_s, duur_s, laatst_bekeken_epoch)} uit NextPVR's PLAYBACK_POSITION."""
    res = {}
    try:
        con = sqlite3.connect("file:/npvr.db3?mode=ro", uri=True, timeout=5)
        for fn, pos, dur, last in con.execute("select filename, position, duration, last_watched from PLAYBACK_POSITION"):
            try:
                ts = int(time.mktime(time.strptime(last, "%Y-%m-%d %H:%M:%S")))
            except Exception:
                ts = 0
            res[fn] = (int(pos or 0), int(dur or 0), ts)
        con.close()
    except Exception as e:
        log("positie-fout", e)
    return res


def volgorde(items, posities):
    """1. bezig met kijken (2-95%), laatst bekeken eerst; 2. nog niet bekeken, nieuwste opname eerst;
    3. uitgekeken (>=95%) of net begonnen en weggeklikt, helemaal achteraan."""
    bezig, nieuw, klaar = [], [], []
    for r in items:
        pos, dur, last = posities.get(os.path.basename(r.get("file", "")), (0, 0, 0))
        dur = dur or int(r.get("duration", 0))
        frac = (pos / dur) if dur else 0
        r["_pos"], r["_dur"], r["_last"] = pos, dur, last
        if frac >= 0.95:
            klaar.append(r)
        elif frac >= 0.02:
            bezig.append(r)
        else:
            nieuw.append(r)
    bezig.sort(key=lambda r: r["_last"], reverse=True)
    nieuw.sort(key=lambda r: int(r.get("startTime", 0)), reverse=True)
    klaar.sort(key=lambda r: r["_last"], reverse=True)
    return bezig + nieuw + klaar


# ---------- Kodi: waar ben je mee bezig (series en films) ----------
KODI_CACHE = os.path.join(OUT, "kodi_state.json")
KODI_MAX_AGE = 240 * 86400   # series waar je langer dan 8 maanden niet naar keek tellen niet meer als "bezig"
_kodi = {"t": 0, "data": {"shows": [], "movies": [], "online": []}}


def _kodi_rpc(box, method, params=None, timeout=6):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    auth = base64.b64encode(("%s:%s" % (box["user"], box["password"])).encode()).decode()
    req = urllib.request.Request("http://%s:8080/jsonrpc" % box["host"], data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("result", {})


def kodi_path(smb):
    """smb://server/<share>/pad/f.mkv -> <mount>/pad/f.mkv, volgens "kodi_shares" in library.json (sharenaam hoofdletterongevoelig)."""
    m = re.match(r"smb://[^/]+/([^/]+)/(.*)$", smb or "")
    if not m:
        return None
    shares = {k.lower(): v for k, v in library_cfg().get("kodi_shares", {}).items()}
    mount = shares.get(m.group(1).lower())
    return "%s/%s" % (mount, urllib.parse.unquote(m.group(2))) if mount else None


def _ts(s):
    try:
        return int(time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S")))
    except Exception:
        return 0


def scan_kodi(box):
    """Alleen-lezen: series in uitvoering (volgende niet geziene aflevering) en films met hervatpunt."""
    shows_out, movies_out = [], []
    res = _kodi_rpc(box, "VideoLibrary.GetTVShows", {
        "properties": ["title", "year", "playcount", "watchedepisodes", "episode", "lastplayed"],
        "sort": {"method": "lastplayed", "order": "descending"}, "limits": {"start": 0, "end": 40}})
    for sh in res.get("tvshows", []):
        last = _ts(sh.get("lastplayed", ""))
        if not last or time.time() - last > KODI_MAX_AGE:
            continue
        if not (0 < sh.get("watchedepisodes", 0) < sh.get("episode", 0)):
            continue  # nog niet begonnen, of helemaal uitgekeken
        eps = _kodi_rpc(box, "VideoLibrary.GetEpisodes", {
            "tvshowid": sh["tvshowid"], "properties": ["season", "episode", "playcount", "file", "resume"],
            "sort": {"method": "episode"}}).get("episodes", [])
        eps.sort(key=lambda e: (e.get("season", 0), e.get("episode", 0)))
        laatste_gezien = max([i for i, e in enumerate(eps) if e.get("playcount", 0) > 0], default=-1)
        volgende = next((e for e in eps[laatste_gezien + 1:] if e.get("playcount", 0) == 0 and e.get("season", 0) > 0), None)
        if not volgende:
            continue
        pad = kodi_path(volgende.get("file"))
        if not pad:
            continue
        smb = volgende.get("file")
        pos = int((volgende.get("resume") or {}).get("position", 0))
        shows_out.append({"title": sh["title"], "year": str(sh.get("year") or ""), "season": volgende["season"],
                          "episode": volgende["episode"], "path": pad, "smb": smb, "last": last, "position": pos,
                          "total": int((volgende.get("resume") or {}).get("total", 0)),
                          "gezien": sh.get("watchedepisodes", 0), "aantal": sh.get("episode", 0)})
    mv = _kodi_rpc(box, "VideoLibrary.GetMovies", {
        "properties": ["title", "year", "file", "resume", "lastplayed"],
        "filter": {"field": "inprogress", "operator": "true", "value": ""},
        "sort": {"method": "lastplayed", "order": "descending"}, "limits": {"start": 0, "end": 10}})
    for m in mv.get("movies", []):
        pad = kodi_path(m.get("file"))
        rs = m.get("resume") or {}
        if pad and rs.get("position", 0) > 0:
            movies_out.append({"title": m["title"], "year": str(m.get("year") or ""), "path": pad, "smb": m.get("file"),
                               "last": _ts(m.get("lastplayed", "")), "position": int(rs["position"]), "total": int(rs.get("total", 0))})
    return shows_out, movies_out


def kodi_state():
    """Elke KODI_TTL s alle bereikbare Kodi's bevragen; een Kodi die uit staat levert de laatst bekende stand (cache)."""
    if time.time() - _kodi["t"] < 240:
        return _kodi["data"]
    try:
        boxes = json.load(open("/secrets.json", encoding="utf-8")).get("kodis", {})
    except Exception:
        boxes = {}
    try:
        cached = json.load(open(KODI_CACHE, encoding="utf-8"))
    except Exception:
        cached = {"boxes": {}}
    online = []
    for naam, box in boxes.items():
        try:
            shows, movies = scan_kodi(box)
            cached["boxes"][naam] = {"shows": shows, "movies": movies, "t": int(time.time())}
            online.append(naam)
        except Exception as e:
            if naam in cached["boxes"]:
                pass  # uit of onbereikbaar: oude stand blijft staan
            else:
                log("kodi", naam, "niet bereikbaar", repr(e)[:80])
    write_atomic(KODI_CACHE, json.dumps(cached).encode("utf-8"))
    shows, movies = {}, {}
    for naam, b in cached["boxes"].items():  # per titel de meest recente
        for x in b.get("shows", []) + b.get("movies", []):
            if x.get("smb"):  # pad opnieuw vertalen: de mounts kunnen veranderd zijn sinds de cache is gemaakt
                x["path"] = kodi_path(x["smb"]) or x["path"]
        for s in b.get("shows", []):
            if s["title"] not in shows or s["last"] > shows[s["title"]]["last"]:
                shows[s["title"]] = s
        for m in b.get("movies", []):
            key = (m["title"], m["year"])
            if key not in movies or m["last"] > movies[key]["last"]:
                movies[key] = m
    data = {"shows": sorted(shows.values(), key=lambda x: x["last"], reverse=True),
            "movies": sorted(movies.values(), key=lambda x: x["last"], reverse=True), "online": online}
    if online:
        log("kodi online:", ",".join(online), "- series bezig:", len(data["shows"]), "films bezig:", len(data["movies"]))
    _kodi["t"], _kodi["data"] = time.time(), data
    return data


# ---------- verversen ----------
def refresh():
    cfg = json.load(open("/secrets.json", encoding="utf-8"))
    s = call(method="session.initiate", ver="1.0", device="tvfeed")
    login = call(method="session.login", sid=s["sid"], md5=md5(":" + md5(cfg["pin"]) + ":" + s["salt"]))
    if login.get("stat") != "ok":
        raise RuntimeError("NextPVR-login mislukt: %s" % login.get("msg"))
    rec = call(method="recording.list", filter="ready", sid=s["sid"])
    items = volgorde(rec.get("recordings", []), playback_positions())[:MAX_ITEMS]

    os.makedirs(CARDS, exist_ok=True)
    os.makedirs(ART_CACHE, exist_ok=True)
    def staat(r):
        f = (r["_pos"] / r["_dur"]) if r["_dur"] else 0
        return "klaar" if f >= 0.95 else "bezig" if f >= 0.02 else "nieuw"

    # volgorde van de rij: bezig -> 4 nieuwste opnames -> nieuwe afleveringen en films (om en om) -> rest
    bezig = [r for r in items if staat(r) == "bezig"]
    nieuw = [r for r in items if staat(r) == "nieuw"]
    lib = library()
    mix = []
    for i in range(max(len(lib["episodes"]), len(lib["movies"]))):
        if i < len(lib["episodes"]):
            mix.append(lib["episodes"][i])
        if i < len(lib["movies"]):
            mix.append(lib["movies"][i])
    # Het kanaal "Nieuwe opnames" is op opnamedatum (ook als je er al aan begonnen bent): de 8 nieuwste
    # niet-uitgekeken opnames. "Verder kijken" = bezig. Dubbelen zijn dus toegestaan.
    nieuwste = sorted(bezig + nieuw, key=lambda r: int(r.get("startTime", 0)), reverse=True)[:8]
    opnames_in_feed = list({str(r["id"]): r for r in (bezig + nieuwste)}.values())
    kodi = kodi_state()
    bezig_titels = {_norm(s["title"]) for s in kodi["shows"]}
    mix = [m for m in mix if not (m["kind"] == "aflevering" and _norm(m["title"]) in bezig_titels)]  # staat al onder Verder kijken
    kodi_items = ([("kodi_serie", s) for s in kodi["shows"]] + [("kodi_film", m) for m in kodi["movies"]])
    volgorde_rij = ([("opname", r) for r in opnames_in_feed] + kodi_items + [("lib", m) for m in mix])[:CARD_ITEMS + 10]
    MEDIA.clear()

    keep, out_items, bronnen = set(), [], {}
    for soort, r in volgorde_rij:
        if soort == "opname":
            iid, titel = str(r["id"]), r.get("name", "")
            MEDIA[iid] = real_path(r.get("file", ""))
            fn = "%s-%s.jpg" % (iid, CARD_VERSION)
            keep.add(fn)
            path = os.path.join(CARDS, fn)
            if not os.path.exists(path):
                art, bron = find_art(r)
                logo = None
                if not art:
                    try:
                        with urllib.request.urlopen(BASE + urllib.parse.urlencode(
                                {"method": "channel.icon", "channel_id": r.get("channelId"), "sid": s["sid"]}), timeout=10) as lr:
                            logo = lr.read()
                    except Exception:
                        logo = None
                write_atomic(path, card_render.render(titel, r.get("channel", ""), int(r.get("startTime", 0)),
                                                      int(r.get("duration", 0)) // 60, art, logo))
                bronnen[iid] = bron
            out_items.append({
                "id": iid, "kind": "opname", "title": titel, "description": r.get("desc", ""),
                "channel": r.get("channel", ""), "start": int(r.get("startTime", 0)),
                "duration": int(r.get("duration", 0)), "file": os.path.basename(r.get("file", "")),
                "card": "cards/" + fn, "position": r["_pos"], "watch_duration": r["_dur"], "state": staat(r),
                "play": "media/" + iid, "last": r["_last"],
            })
        elif soort in ("kodi_serie", "kodi_film"):
            serie = soort == "kodi_serie"
            iid = "kodi-" + md5(r["path"])[:10]
            MEDIA[iid] = r["path"]
            sub = "S%02dE%02d" % (r["season"], r["episode"]) if serie else ""
            fn = "%s-%s.jpg" % (iid, CARD_VERSION)
            keep.add(fn)
            path = os.path.join(CARDS, fn)
            if not os.path.exists(path):
                art = library_poster({"kind": "aflevering" if serie else "film", "title": r["title"], "year": r["year"]})
                label = ("Volgende aflevering " + sub) if serie else "Verder kijken"
                write_atomic(path, card_render.render(r["title"], label, r["last"], 0, art, None,
                                                      datum_tekst="laatst gekeken " + " ".join(card_render.datum(r["last"]).split(" ")[1:3])))
                bronnen[iid] = "kodi"
            bezig_pos = r["position"] if r["position"] > 0 and (r["total"] == 0 or r["position"] / r["total"] < 0.95) else 0
            out_items.append({
                "id": iid, "kind": "aflevering" if serie else "film",
                "title": r["title"] + (" – " + sub if serie else ""),
                "description": r["path"], "channel": ("Volgende aflevering" if serie else "Verder kijken"),
                "start": r["last"], "duration": r["total"], "file": r["path"], "card": "cards/" + fn,
                "position": bezig_pos, "watch_duration": r["total"], "state": "bezig", "play": "media/" + iid,
                "last": r["last"],
            })
        else:
            iid = r["id"]
            MEDIA[iid] = r["path"]
            fn = "%s-%s.jpg" % (iid, CARD_VERSION)
            keep.add(fn)
            path = os.path.join(CARDS, fn)
            if not os.path.exists(path):
                art = library_poster(r)
                label = "Nieuwe film" if r["kind"] == "film" else "Nieuwe aflevering " + r["sub"]
                write_atomic(path, card_render.render(r["title"], label, r["mtime"], 0, art, None,
                                                      datum_tekst="toegevoegd " + card_render.datum(r["mtime"])[3:].split(" ")[0] + " " +
                                                      card_render.datum(r["mtime"]).split(" ")[2]))
                bronnen[iid] = "omdb" if art else "geen"
            out_items.append({
                "id": iid, "kind": r["kind"], "title": r["title"] + (" – " + r["sub"] if r["kind"] == "aflevering" else ""),
                "description": r["path"], "channel": "Nieuwe film" if r["kind"] == "film" else "Nieuwe aflevering",
                "start": r["mtime"], "duration": 0, "file": r["path"], "card": "cards/" + fn,
                "position": 0, "watch_duration": 0, "state": "nieuw", "play": "media/" + iid, "last": r["mtime"],
            })
    for fn in os.listdir(CARDS):
        if fn.endswith(".jpg") and fn not in keep:
            os.remove(os.path.join(CARDS, fn))
    for fn in os.listdir(ART_CACHE):
        if fn.startswith("lib_"):
            continue
        if fn.endswith(".img") and fn[:-4] not in {str(r["id"]) for r in items}:
            os.remove(os.path.join(ART_CACHE, fn))
    # --- "Aanbevolen"-achtergronden: nummer 1 van Nieuwe opnames, Nieuwe series en Nieuwe films ---
    os.makedirs(HERO, exist_ok=True)
    heroes, hero_keep = [], set()
    kandidaten = []
    if nieuwste:
        kandidaten.append(("opname", nieuwste[0]))
    if lib["episodes"]:
        kandidaten.append(("serie", lib["episodes"][0]))
    if lib["movies"]:
        kandidaten.append(("film", lib["movies"][0]))
    for soort, r in kandidaten:
        try:
            if soort == "opname":
                iid, titel, label = str(r["id"]), r.get("name", ""), "Nieuwe opname"
                ondertitel = "%s  ·  %s" % (r.get("channel", ""), card_render.datum(int(r.get("startTime", 0))))
                art, _ = find_art(r)
            else:
                iid, titel = r["id"], r["title"]
                label = "Nieuwe serie" if soort == "serie" else "Nieuwe film"
                ondertitel = ("Aflevering " + r["sub"]) if soort == "serie" and r["sub"] else (("(%s)" % r["year"]) if r["year"] else "")
                art = library_poster(r)
            fn = "%s-%s.jpg" % (soort, md5("%s|%s|%d" % (iid, CARD_VERSION, 1 if art else 0))[:10])
            hero_keep.add(fn)
            path = os.path.join(HERO, fn)
            if not os.path.exists(path):
                write_atomic(path, card_render.render_hero(titel, label, ondertitel, art))
            heroes.append({"uri": "hero/" + fn, "title": titel, "label": label})
        except Exception as e:
            log("hero mislukt", soort, repr(e))
    for fn in os.listdir(HERO):
        if fn.endswith(".jpg") and fn not in hero_keep:
            os.remove(os.path.join(HERO, fn))
    write_atomic(os.path.join(OUT, "hero.json"), json.dumps({"generated_at": int(time.time()), "items": heroes}, ensure_ascii=False).encode("utf-8"))

    doc = {"generated_at": int(time.time()), "source": "nextpvr+bibliotheek", "recordings": out_items}
    write_atomic(os.path.join(OUT, "recordings.json"), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    log("%d kaarten (opnames %d, bibliotheek %d); nieuwe kaarten: %s" % (
        len(out_items), len(bezig) + len(nieuw), len(mix), bronnen or "geen"))


def loop():
    while True:
        try:
            refresh()
        except Exception as e:
            log("verversen mislukt:", repr(e))
        time.sleep(INTERVAL)


MEDIA = {}  # id -> bestandspad; alleen wat nu in de lijst staat wordt geserveerd
MIME = {".ts": "video/mp2t", ".mkv": "video/x-matroska", ".mp4": "video/mp4", ".avi": "video/x-msvideo",
        ".m4v": "video/mp4", ".mov": "video/quicktime", ".iso": "application/octet-stream"}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=OUT, **kw)

    def log_message(self, *a):
        pass

    def _media(self, head_only):
        iid = urllib.parse.unquote(self.path.split("?", 1)[0])[len("/media/"):]
        # de extensie (.ts/.mkv) in de URL is alleen een hint voor de speler (dan kiest VLC meteen de juiste demuxer)
        if os.path.splitext(iid)[1].lower() in MIME:
            iid = os.path.splitext(iid)[0]
        path = MEDIA.get(iid)
        if not path or not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:  # laatste N bytes
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if head_only:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path.startswith("/media/"):
            return self._media(False)
        return super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/media/"):
            return self._media(True)
        return super().do_HEAD()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    threading.Thread(target=loop, daemon=True).start()
    log("tvfeed luistert op :8871")
    Server(("0.0.0.0", 8871), Quiet).serve_forever()
