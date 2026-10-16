"""Pack a generated VFX clip (or a still) into a runtime texture.

Source art for the spell effects is generated on a pure black background
(fal.ai: Wan 3.0 text-to-video for animated elements, Z-Image Turbo for stills;
see art/vfx/README.md). Black is "no effect", so the luminance of each pixel
becomes its coverage (alpha) and the colour is un-premultiplied from it. The
packer then honours the atlas contract the runtime and vfx_regression check:

  * row-major frames, frame 0 top-left, `cols x rows` cells of `cell` px;
  * every cell keeps a `pad` px zero-alpha, zero-colour gutter, and its content
    fades to zero before the gutter (radial + edge falloff), so three mip levels
    never bleed one cell into the next;
  * straight (non-premultiplied) alpha, sRGB colour, linear alpha;
  * one-shot atlases end on an empty frame; a looping atlas crossfades its tail
    into its head so frame N-1 blends into frame 0.

Usage:
  python pack_flipbook.py video <clip.mp4> <out.png> --grid 8 8 --cell 256 [--loop]
         [--start S] [--end E] [--gain G] [--floor F] [--mono]
  python pack_flipbook.py still <image.png> <out.png> --size 512 [--gain G] [--floor F] [--tile]

Prints the metadata entry (JSON) for assets/vfx/metadata.json on stdout's last line.
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image

PAD = 4


def key_black(rgb, floor, gain, mono):
    """rgb float 0..1 -> straight RGBA. Coverage = how far above the black floor
    the brightest channel is; colour is the pixel divided by its coverage."""
    peak = rgb.max(axis=2)
    alpha = np.clip((peak - floor) / max(1e-4, 1.0 - floor) * gain, 0.0, 1.0)
    alpha = alpha ** 0.9
    safe = np.maximum(peak, 1e-4)[..., None]
    colour = np.clip(rgb / safe, 0.0, 1.0)   # hue/saturation at full brightness
    if mono:
        colour = np.ones_like(colour)
    return np.dstack([colour, alpha])


def falloff(size, inner=0.78):
    """1 in the middle, 0 at the cell border: a radial ramp that also hits zero
    a few pixels before every edge (the mip-safe gutter guarantee)."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = np.sqrt((x - c) ** 2 + (y - c) ** 2) / c
    radial = np.clip((1.0 - r) / max(1e-3, 1.0 - inner), 0.0, 1.0)
    edge = np.minimum(np.minimum(x, size - 1 - x), np.minimum(y, size - 1 - y))
    edge = np.clip((edge - 2.0) / 10.0, 0.0, 1.0)
    return np.minimum(radial, edge) ** 1.2


def edge_only(size):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    edge = np.minimum(np.minimum(x, size - 1 - x), np.minimum(y, size - 1 - y))
    return np.clip((edge - 2.0) / 10.0, 0.0, 1.0)


def square_crop(img):
    h, w = img.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    return img[y0:y0 + s, x0:x0 + s]


def resize(img, size):
    pil = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    return np.asarray(pil.resize((size, size), Image.LANCZOS)).astype(np.float32) / 255.0


def read_video(path):
    import cv2
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0)
    cap.release()
    if not frames:
        raise SystemExit("no frames decoded from %s" % path)
    return frames, fps


def pack_video(args):
    frames, fps = read_video(args.src)
    cols, rows = args.grid
    count = cols * rows
    inner = args.cell - 2 * PAD
    lum = [float(f.max(axis=2).mean()) for f in frames]
    # Active span: from the first frame with visible energy to the last one.
    threshold = max(0.004, max(lum) * 0.04)
    active = [i for i, v in enumerate(lum) if v > threshold]
    start = args.start if args.start is not None else (active[0] if active else 0)
    end = args.end if args.end is not None else (active[-1] if active else len(frames) - 1)
    end = max(start + 1, min(end, len(frames) - 1))
    picks = np.linspace(start, end, count)
    mask = falloff(inner, args.inner) if not args.tile else edge_only(inner)
    cells = []
    for k, p in enumerate(picks):
        i0 = int(np.floor(p)); i1 = min(i0 + 1, end); t = p - i0
        rgb = frames[i0] * (1 - t) + frames[i1] * t
        rgba = key_black(resize(square_crop(rgb), inner), args.floor, args.gain, args.mono)
        rgba[..., 3] *= mask
        cells.append(rgba)
    if args.loop:
        # Crossfade the last quarter into the first frames so the sequence is periodic.
        blend = count // 4
        for j in range(blend):
            w = (j + 1) / (blend + 1)
            a = cells[count - blend + j]
            b = cells[j]
            cells[count - blend + j] = a * (1 - w) + b * w
    else:
        # One-shots fade out over their last frames and end empty.
        tail = max(2, count // 10)
        for j in range(tail):
            cells[count - tail + j][..., 3] *= 1.0 - (j + 1) / tail
    sheet = np.zeros((rows * args.cell, cols * args.cell, 4), np.float32)
    for k, cell in enumerate(cells):
        r, c = divmod(k, cols)
        y = r * args.cell + PAD
        x = c * args.cell + PAD
        out = cell.copy()
        out[..., :3] *= (out[..., 3:4] > 0.0)      # zero colour where empty
        sheet[y:y + inner, x:x + inner] = out
    save(sheet, args.out)
    duration = (end - start) / fps
    entry = {
        "cols": cols, "rows": rows, "cell": args.cell, "frames": count,
        "fps": int(round(count / max(0.2, duration))) if not args.fps else args.fps,
        "loop": bool(args.loop), "source_frames": [int(start), int(end)], "source_fps": round(fps, 3),
    }
    return entry


def pack_still(args):
    img = np.asarray(Image.open(args.src).convert("RGB")).astype(np.float32) / 255.0
    size = args.size
    inner = size - 2 * PAD
    rgba = key_black(resize(square_crop(img), inner), args.floor, args.gain, args.mono)
    rgba[..., 3] *= edge_only(inner) if args.tile else falloff(inner, args.inner)
    sheet = np.zeros((size, size, 4), np.float32)
    rgba[..., :3] *= (rgba[..., 3:4] > 0.0)
    sheet[PAD:PAD + inner, PAD:PAD + inner] = rgba
    save(sheet, args.out)
    return {"cols": 1, "rows": 1, "cell": size, "frames": 1, "loop": False}


def save(sheet, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    Image.fromarray((np.clip(sheet, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(out, optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["video", "still"])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--grid", nargs=2, type=int, default=[8, 8])
    ap.add_argument("--cell", type=int, default=256)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--fps", type=int)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--gain", type=float, default=1.25)
    ap.add_argument("--floor", type=float, default=0.06)
    ap.add_argument("--inner", type=float, default=0.72)
    ap.add_argument("--mono", action="store_true", help="white colour, alpha only (tinted at runtime)")
    ap.add_argument("--tile", action="store_true", help="edge gutter only, no radial falloff")
    args = ap.parse_args()
    entry = pack_video(args) if args.mode == "video" else pack_still(args)
    entry.update({"padding_px": PAD, "colour": not args.mono})
    print(json.dumps(entry))


if __name__ == "__main__":
    main()
