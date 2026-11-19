"""Rendert 16:9-kaarten (PNG) voor de Watch Next-rij. Alleen Pillow (zit in de HA-container)."""
import colorsys
import hashlib
import io
import time

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _kleur(titel):
    """Vaste, mooie kleur per titel (zelfde titel = zelfde kleur)."""
    h = int(hashlib.md5(titel.encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.55)
    r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.08) % 1, 0.7, 0.18)
    return (int(r * 255), int(g * 255), int(b * 255)), (int(r2 * 255), int(g2 * 255), int(b2 * 255))


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


def datum(ts):
    t = time.localtime(ts)
    return "%s %d %s %02d:%02d" % (DAGEN[t.tm_wday], t.tm_mday, MAANDEN[t.tm_mon - 1], t.tm_hour, t.tm_min)


def render(titel, zender, start, duur_min, logo_bytes=None):
    boven, onder = _kleur(titel)
    strook = Image.new("RGB", (1, H))
    for y in range(H):  # verloop boven -> onder (1 pixel breed, daarna oprekken: snel)
        f = y / (H - 1)
        strook.putpixel((0, y), tuple(int(boven[i] * (1 - f) + onder[i] * f) for i in range(3)))
    img = strook.resize((W, H))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, H - 220, W, H], fill=(0, 0, 0, 120))  # leesbaarheid onderaan
    f_titel = ImageFont.load_default(size=84)
    f_klein = ImageFont.load_default(size=40)
    y = H - 200
    for regel in _wrap(d, titel, f_titel, W - 160, 2):
        d.text((80, y), regel, font=f_titel, fill=(255, 255, 255, 255))
        y += 92
    onderregel = "%s  ·  %s  ·  %d min" % (zender, datum(start), duur_min)
    d.text((80, H - 64), onderregel, font=f_klein, fill=(235, 235, 235, 255))
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
            logo.thumbnail((200, 120))
            plaat = Image.new("RGBA", (logo.width + 40, logo.height + 30), (255, 255, 255, 235))
            img.paste(plaat, (60, 50), plaat)
            img.paste(logo, (80, 65), logo)
        except Exception:
            pass
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
