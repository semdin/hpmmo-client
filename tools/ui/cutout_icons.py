"""Prepare the fal.ai interface icons for the game.

Two kinds of source art come out of the image model (fal-ai/nano-banana-2.1):

* full-bleed square paintings (the menu buttons) - these are only resized;
* single objects on a flat white ground (the minimap markers and zoom glyphs) -
  the white is removed here. The background is the white region connected to
  the image border (so white highlights inside the object survive), and the
  edge pixels get a soft alpha from how white they are, with the white
  un-mixed from their colour so no pale halo remains. The result is trimmed to
  its visible bounds, padded square and resized.

Usage: python tools/ui/cutout_icons.py <source_dir> [--out assets/ui/icons]
Sources are named menu_<id>.png, mm_<id>.png and item_<item id>.png (an
inventory item on white, cut out like a marker and written as icon_<item id>.png).
"""

import argparse
import glob
import os

import numpy as np
from PIL import Image
from scipy import ndimage

MENU_SIZE = 256
MARKER_SIZE = 128
ITEM_SIZE = 512     # matches the original item icons (icon_broom_*.png)
WHITE_HARD = 238   # min channel above this, connected to the border: background
WHITE_SOFT = 200   # edge band: partially transparent between SOFT and HARD


def cutout(img: Image.Image) -> Image.Image:
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    lo = rgb.min(axis=2)
    near_white = lo >= WHITE_SOFT
    labels, _ = ndimage.label(near_white)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    background = np.isin(labels, list(border))
    # Alpha: 0 for the hard background, a ramp over the soft band, 1 inside.
    ramp = np.clip((255.0 - lo) / (255.0 - WHITE_SOFT), 0.0, 1.0)
    alpha = np.where(background, np.where(lo >= WHITE_HARD, 0.0, ramp), 1.0)
    # Feather one pixel so the cut never stair-steps.
    alpha = np.minimum(alpha, ndimage.uniform_filter(alpha, 3) + 0.35)
    a = np.clip(alpha, 0.0, 1.0)[..., None]
    # Un-mix the white: c = a*f + (1-a)*255  ->  f = (c - (1-a)*255) / a
    fg = np.where(a > 0.01, (rgb - (1.0 - a) * 255.0) / np.maximum(a, 0.01), 0.0)
    out = np.dstack([np.clip(fg, 0, 255), a * 255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def square_trim(img: Image.Image, pad: float = 0.04) -> Image.Image:
    box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        img = img.crop(box)
    side = int(max(img.size) * (1.0 + pad * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "..", "assets", "ui", "icons"))
    args = ap.parse_args()
    for path in sorted(glob.glob(os.path.join(args.source, "*.png"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        img = Image.open(path)
        if stem.startswith("menu_"):
            out = img.convert("RGB").resize((MENU_SIZE, MENU_SIZE), Image.LANCZOS)
            name = "icon_" + stem + ".png"
        elif stem.startswith("mm_"):
            out = square_trim(cutout(img)).resize((MARKER_SIZE, MARKER_SIZE), Image.LANCZOS)
            name = "icon_minimap_" + stem[3:] + ".png"
        elif stem.startswith("item_"):
            out = square_trim(cutout(img)).resize((ITEM_SIZE, ITEM_SIZE), Image.LANCZOS)
            name = "icon_" + stem[5:] + ".png"
        else:
            continue
        out.save(os.path.join(args.out, name))
        print("wrote", name, out.size)


if __name__ == "__main__":
    main()
