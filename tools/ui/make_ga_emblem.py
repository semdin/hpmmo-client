"""Draw the GA (game admin) emblem: gilded "GA" between two swept wings, the
badge shown over a GA's name (player.gd). Pure PIL, no generator.

    python client/tools/ui/make_ga_emblem.py
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.normpath(os.path.join(HERE, "..", ".."))
FONT = os.path.join(CLIENT, "assets", "fonts", "CinzelDecorative-Bold.ttf")
OUT = os.path.join(CLIENT, "assets", "ui", "ga_emblem.png")
W, H = 512, 224
GOLD_TOP = (255, 246, 170)
GOLD_MID = (247, 190, 52)
GOLD_LOW = (176, 98, 18)
EDGE = (58, 28, 6, 255)


def gradient(size, stops):
    w, h = size
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                k = (t - t0) / max(1e-6, t1 - t0)
                c = tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3))
                break
        for x in range(w):
            px[x, y] = c + (255,)
    return img


def wing(draw, cx, cy, side):
    """Five swept feathers fanning out from the letters."""
    for k in range(5):
        ang = math.radians(-28 + k * 15)
        length = 150 - k * 18
        width = 26 - k * 2
        root = (cx + side * (8 + k * 6), cy - 14 + k * 11)
        tip = (root[0] + side * length * math.cos(ang), root[1] + length * math.sin(ang) * 0.55 - 30 + k * 4)
        nx, ny = -(tip[1] - root[1]), tip[0] - root[0]
        norm = math.hypot(nx, ny) or 1.0
        nx, ny = nx / norm * width / 2, ny / norm * width / 2
        mid = ((root[0] + tip[0]) / 2, (root[1] + tip[1]) / 2)
        poly = [(root[0] + nx, root[1] + ny), (mid[0] + nx * 1.1, mid[1] + ny * 1.1), tip,
                (mid[0] - nx * 0.8, mid[1] - ny * 0.8), (root[0] - nx, root[1] - ny)]
        draw.polygon(poly, fill=255)


def main():
    mask_wings = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask_wings)
    wing(d, W / 2 - 92, H / 2 + 6, -1)
    wing(d, W / 2 + 92, H / 2 + 6, 1)
    mask_text = Image.new("L", (W, H), 0)
    font = ImageFont.truetype(FONT, 132)
    td = ImageDraw.Draw(mask_text)
    box = td.textbbox((0, 0), "GA", font=font)
    tx = (W - (box[2] - box[0])) / 2 - box[0]
    ty = (H - (box[3] - box[1])) / 2 - box[1] - 4
    td.text((tx, ty), "GA", font=font, fill=255)

    gold = gradient((W, H), [(0.0, GOLD_TOP), (0.45, GOLD_MID), (1.0, GOLD_LOW)])
    wing_gold = gradient((W, H), [(0.0, GOLD_TOP), (0.6, GOLD_MID), (1.0, GOLD_LOW)])
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # dark outline under both, a soft glow under everything
    both = Image.new("L", (W, H), 0)
    both.paste(255, (0, 0), mask_wings)
    both.paste(255, (0, 0), mask_text)
    glow = both.filter(ImageFilter.GaussianBlur(9))
    out.paste((255, 196, 80, 120), (0, 0), glow)
    edge = both.filter(ImageFilter.MaxFilter(9))
    out.paste(EDGE, (0, 0), edge)
    out.paste(wing_gold, (0, 0), mask_wings)
    # a highlight line through the wings' upper edges
    out.paste(gold, (0, 0), mask_text)
    shine = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shine)
    sd.text((tx, ty - 3), "GA", font=font, fill=110)
    shine = Image.composite(shine, Image.new("L", (W, H), 0), mask_text.point(lambda v: 255 if v > 0 else 0))
    top = Image.new("L", (W, H), 0)
    ImageDraw.Draw(top).rectangle((0, 0, W, int(H * 0.48)), fill=255)
    shine = Image.composite(shine, Image.new("L", (W, H), 0), top)
    out.paste((255, 255, 235, 255), (0, 0), shine)
    out.save(OUT)
    print("GA emblem ->", OUT)


if __name__ == "__main__":
    main()
