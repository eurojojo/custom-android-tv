"""Rendert 16:9-kaarten (JPEG) voor de Watch Next-rij. Alleen Pillow."""
import colorsys
import hashlib
import io
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1280, 720
DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def datum(ts):
    t = time.localtime(ts)
    return "%s %d %s %02d:%02d" % (DAGEN[t.tm_wday], t.tm_mday, MAANDEN[t.tm_mon - 1], t.tm_hour, t.tm_min)


def _verloop(titel):
    h = int(hashlib.md5(titel.encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.55)
    r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.08) % 1, 0.7, 0.18)
    boven, onder = (int(r * 255), int(g * 255), int(b * 255)), (int(r2 * 255), int(g2 * 255), int(b2 * 255))
    strook = Image.new("RGB", (1, H))
    for y in range(H):
        f = y / (H - 1)
        strook.putpixel((0, y), tuple(int(boven[i] * (1 - f) + onder[i] * f) for i in range(3)))
    return strook.resize((W, H))


def _achtergrond(art_bytes, titel):
    """Geeft (16:9 achtergrond, rechterrand van een staande poster of 0)."""
    if not art_bytes:
        return _verloop(titel), 0
    try:
        art = ImageOps.exif_transpose(Image.open(io.BytesIO(art_bytes))).convert("RGB")
    except Exception:
        return _verloop(titel), 0
    if art.width / art.height >= 1.45:  # al (bijna) liggend: bijsnijden tot 16:9
        return ImageOps.fit(art, (W, H), Image.LANCZOS, centering=(0.5, 0.35)), 0
    bg = ImageOps.fit(art, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.55)
    poster = ImageOps.contain(art, (W, int(H * 0.86)), Image.LANCZOS)
    x0 = 70
    bg.paste(poster, (x0, (H - poster.height) // 2))
    return bg, x0 + poster.width


def _wrap(draw, text, font, max_w, max_lines):
    regels, cur = [], ""
    for woord in text.split():
        probe = (cur + " " + woord).strip()
        if draw.textlength(probe, font=font) <= max_w:
            cur = probe
        else:
            if cur:
                regels.append(cur)
            cur = woord
    if cur:
        regels.append(cur)
    if len(regels) > max_lines:
        regels = regels[:max_lines]
        regels[-1] = regels[-1].rstrip(".,; ") + "…"
    return regels


def render(titel, zender, start, duur_min, art_bytes=None, logo_bytes=None, datum_tekst=None):
    img, poster_rand = _achtergrond(art_bytes, titel)
    d = ImageDraw.Draw(img, "RGBA")
    f_titel = ImageFont.load_default(size=78)
    f_klein = ImageFont.load_default(size=38)
    tijd = datum_tekst if datum_tekst is not None else ("%s  ·  %d min" % (datum(start), duur_min))
    onderregel = "%s  ·  %s" % (zender, tijd)
    if poster_rand:
        # staande poster links, tekst rechts ernaast
        x = poster_rand + 60
        regels = _wrap(d, titel, f_titel, W - x - 50, 4)
        blok = 86 * len(regels) + 70
        y = (H - blok) // 2
        for regel in regels:
            d.text((x, y), regel, font=f_titel, fill=(255, 255, 255, 255))
            y += 86
        d.text((x, y + 14), zender, font=f_klein, fill=(235, 235, 235, 255))
        d.text((x, y + 62), tijd, font=f_klein, fill=(210, 210, 210, 255))
    else:
        # liggende afbeelding: tekst onderaan op een donker verloop
        for i in range(260):
            d.line([(0, H - 260 + i), (W, H - 260 + i)], fill=(0, 0, 0, int(215 * (i / 259) ** 1.4)))
        regels = _wrap(d, titel, f_titel, W - 160, 2)
        y = H - 70 - 86 * len(regels) - 20
        for regel in regels:
            d.text((80, y), regel, font=f_titel, fill=(255, 255, 255, 255))
            y += 86
        d.text((80, H - 64), onderregel, font=f_klein, fill=(235, 235, 235, 255))
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
            logo.thumbnail((180, 100))
            plaat = Image.new("RGBA", (logo.width + 36, logo.height + 28), (255, 255, 255, 230))
            img.paste(plaat, (50, 40), plaat)
            img.paste(logo, (68, 54), logo)
        except Exception:
            pass
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


HW, HH = 1920, 1080


def render_hero(titel, label, ondertitel, art_bytes=None):
    """Achtergrond voor het startscherm (16:9, 1920x1080): groot beeld, zonder tekst, donker onderaan voor de rijen."""
    base = None
    poster = None
    if art_bytes:
        try:
            art = ImageOps.exif_transpose(Image.open(io.BytesIO(art_bytes))).convert("RGB")
            if art.width / art.height >= 1.45:
                base = ImageOps.fit(art, (HW, HH), Image.LANCZOS, centering=(0.5, 0.3))
            else:
                base = ImageOps.fit(art, (HW, HH), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
                poster = ImageOps.contain(art, (700, 940), Image.LANCZOS)
        except Exception:
            base = None
    if base is None:
        strook = Image.new("RGB", (1, HH))
        h = int(hashlib.md5(titel.encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF
        r, g, b = colorsys.hsv_to_rgb(h, 0.5, 0.45)
        for y in range(HH):
            f = y / (HH - 1)
            strook.putpixel((0, y), (int(r * 255 * (1 - 0.7 * f)), int(g * 255 * (1 - 0.7 * f)), int(b * 255 * (1 - 0.7 * f))))
        base = strook.resize((HW, HH))
    img = base.copy()
    d = ImageDraw.Draw(img, "RGBA")
    # donker verloop: links (voor de tekst) en onderaan (voor de rijen)
    for x in range(900):
        d.line([(x, 0), (x, HH)], fill=(0, 0, 0, int(190 * (1 - x / 900) ** 1.3)))
    for i in range(620):
        d.line([(0, HH - 620 + i), (HW, HH - 620 + i)], fill=(0, 0, 0, int(230 * (i / 619) ** 1.5)))
    if poster:
        px = HW - poster.width - 150
        img.paste(poster, (px, 70))
        d = ImageDraw.Draw(img, "RGBA")
    # Geen tekst op de achtergrond: de rijen van Projectivy liggen er overheen en tonen zelf de titels.
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()
