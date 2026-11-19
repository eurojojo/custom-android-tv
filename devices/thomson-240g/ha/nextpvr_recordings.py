#!/usr/bin/env python3
"""Haalt de laatste NextPVR-opnames op en schrijft ze als JSON + kaartplaatjes voor de Thomson-app.

Draait op de Home Assistant-Pi (cron, elke 10 minuten, in de HA-container). Leest host + PIN uit
`secrets.json` naast dit script (rechten 600, NIET in de repo):
    {"host": "<nextpvr-host>", "port": 8866, "pin": "<pin>"}
Schrijft in `<HA-config>/www/nextpvr_tv/`:
    recordings.json        lijst van de nieuwste opnames
    cards/<id>.png         16:9-kaart per opname (alleen nieuw gerenderd als hij nog niet bestaat)
HA serveert dat op `http://<ha>:8123/local/nextpvr_tv/...`.

Alleen standaardbibliotheek + Pillow (zit in de HA-container).
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import card_render  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("NEXTPVR_TV_OUT", os.path.join(HERE, "..", "..", "www", "nextpvr_tv"))
CARD_DIR = os.path.join(OUT_DIR, "cards")
OUT_FILE = os.path.join(OUT_DIR, "recordings.json")
MAX_ITEMS = 20
CARD_ITEMS = 12


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def write_atomic(path, data, mode="wb"):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, mode) as f:
        f.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main():
    with open(os.path.join(HERE, "secrets.json"), encoding="utf-8") as f:
        sec = json.load(f)
    base = "http://%s:%s/services/service?" % (sec["host"], sec.get("port", 8866))

    def call(**kw):
        kw["format"] = "json"
        with urllib.request.urlopen(base + urllib.parse.urlencode(kw), timeout=15) as r:
            return json.load(r)

    def get_bytes(**kw):
        try:
            with urllib.request.urlopen(base + urllib.parse.urlencode(kw), timeout=15) as r:
                return r.read()
        except Exception:
            return None

    s = call(method="session.initiate", ver="1.0", device="thomson-tv")
    login = call(method="session.login", sid=s["sid"],
                 md5=md5(":" + md5(sec["pin"]) + ":" + s["salt"]))
    if login.get("stat") != "ok":
        print("login mislukt:", login.get("msg"), file=sys.stderr)
        return 2

    rec = call(method="recording.list", filter="ready", sid=s["sid"])
    items = sorted(rec.get("recordings", []), key=lambda r: int(r.get("startTime", 0)), reverse=True)[:MAX_ITEMS]

    os.makedirs(CARD_DIR, exist_ok=True)
    gewenst = set()
    out_items = []
    for i, r in enumerate(items):
        card = None
        if i < CARD_ITEMS:
            fn = "%s.png" % r["id"]
            gewenst.add(fn)
            path = os.path.join(CARD_DIR, fn)
            if not os.path.exists(path):
                logo = get_bytes(method="channel.icon", channel_id=r.get("channelId"), sid=s["sid"])
                png = card_render.render(r.get("name", ""), r.get("channel", ""), int(r.get("startTime", 0)),
                                         int(r.get("duration", 0)) // 60, logo)
                write_atomic(path, png)
            card = "cards/" + fn
        out_items.append({
            "id": r["id"],
            "title": r.get("name", ""),
            "description": r.get("desc", ""),
            "channel": r.get("channel", ""),
            "start": int(r.get("startTime", 0)),
            "duration": int(r.get("duration", 0)),
            "file": os.path.basename(r.get("file", "")),
            "card": card,
        })
    for fn in os.listdir(CARD_DIR):  # kaarten van verdwenen opnames opruimen
        if fn.endswith(".png") and fn not in gewenst:
            os.remove(os.path.join(CARD_DIR, fn))

    out = {"generated_at": int(time.time()), "source": "nextpvr", "recordings": out_items}
    write_atomic(OUT_FILE, json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    print("%s %d opnames -> %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), len(items), OUT_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
