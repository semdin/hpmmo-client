"""Procedural VFX stills that generators draw badly: a perfectly tiling hex
shield lattice, a flat ground scorch decal and a tapered energy streak.

Seeded and deterministic; every output keeps the 4 px zero-alpha gutter and
straight alpha the atlas contract asks for (see pack_flipbook.py).

  python procedural_textures.py <out_dir>
"""
import os, sys
import numpy as np
from PIL import Image

PAD = 4
RNG = np.random.default_rng(20261016)


def save(rgba, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray((np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(path, optimize=True)


def gutter(alpha):
    h, w = alpha.shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    edge = np.minimum(np.minimum(x, w - 1 - x), np.minimum(y, h - 1 - y))
    return alpha * np.clip((edge - PAD) / 6.0, 0.0, 1.0)


def value_noise(size, cells, octaves=4):
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        n = cells * (2 ** o)
        grid = RNG.random((n + 1, n + 1)).astype(np.float32)
        grid[-1, :] = grid[0, :]
        grid[:, -1] = grid[:, 0]
        img = Image.fromarray((grid * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
        out += amp * np.asarray(img).astype(np.float32) / 255.0
        total += amp
        amp *= 0.5
    return out / total


def hex_shield(size=512, cells=6):
    """White hex lattice lines, tileable: `cells` hexes across, and the
    vertical period (cells * sqrt(3) rows) is rounded so the sheet wraps."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    rows = max(1, int(round(cells / np.sqrt(3.0))))
    p = np.dstack([x * cells, y * rows * np.sqrt(3.0)])
    period = np.array([1.0, np.sqrt(3.0)], np.float32)
    a = np.mod(p, period) - period / 2.0
    b = np.mod(p - period / 2.0, period) - period / 2.0
    use_a = (a ** 2).sum(-1) < (b ** 2).sum(-1)
    g = np.where(use_a[..., None], a, b)
    q = np.abs(g)
    # pointy-top hexagon of circumradius 1/sqrt(3) in this lattice
    hd = np.maximum(q[..., 0] * 0.5 + q[..., 1] * (np.sqrt(3.0) / 2.0), q[..., 0])
    edge = 0.5 - hd                     # 0 on the hex border
    line = np.clip(1.0 - edge / 0.03, 0.0, 1.0) ** 1.6
    inner = 0.10 * np.clip(1.0 - edge / 0.5, 0, 1) ** 4
    alpha = np.clip(line + inner, 0, 1)
    return np.dstack([np.ones_like(alpha), np.ones_like(alpha), np.ones_like(alpha), alpha])


def scorch(size=512):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = np.sqrt((x - c) ** 2 + (y - c) ** 2) / (c - PAD - 6)
    n = value_noise(size, 6)
    edge = 0.78 + 0.22 * (n - 0.5) * 2.0
    body = np.clip((edge - r) / 0.35, 0.0, 1.0) ** 0.8
    soot = 0.55 + 0.45 * value_noise(size, 12)
    alpha = gutter(body * soot * 0.92)
    char = 0.06 + 0.10 * value_noise(size, 24)
    ember = np.clip((value_noise(size, 18) - 0.72) * 6.0, 0, 1) * np.clip((r - 0.45) * 3.0, 0, 1) * body
    rgb = np.dstack([char + ember * 0.9, char + ember * 0.35, char + ember * 0.05])
    return np.dstack([rgb, alpha])


def streak(w=1024, h=256):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u = x / (w - 1)
    v = (y - (h - 1) / 2.0) / ((h - 1) / 2.0)
    taper = np.clip(np.sin(np.clip(u, 0, 1) * np.pi), 0.0, 1.0) ** 0.7 * (0.35 + 0.65 * u)   # thicker toward the head
    width = 0.08 + 0.42 * taper
    core = np.exp(-(v / (width * 0.35)) ** 2)
    glow = np.exp(-(v / width) ** 2) * 0.45
    wisp = 0.85 + 0.15 * value_noise(max(w, h), 10)[:h, :w]
    alpha = gutter(np.clip((core + glow) * taper * wisp, 0, 1))
    return np.dstack([np.ones_like(alpha), np.ones_like(alpha), np.ones_like(alpha), alpha])


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    save(hex_shield(), os.path.join(out, "hex_shield_512.png"))
    save(scorch(), os.path.join(out, "scorch_decal_512.png"))
    save(streak(), os.path.join(out, "energy_streak_1024x256.png"))
    print("wrote hex_shield_512.png, scorch_decal_512.png, energy_streak_1024x256.png")


if __name__ == "__main__":
    main()
