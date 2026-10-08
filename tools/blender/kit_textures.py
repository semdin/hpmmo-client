"""Art pass PBR texture generation (project-original art, authored in Blender).

Run headless:
    blender -b --factory-startup --python kit_textures.py -- --out <dir>

Every map is generated deterministically from seeded numpy fields inside
Blender's Python and written as 8-bit PNG. Albedo is encoded sRGB (what a colour
image means); normal/roughness/AO/height are written as raw linear data. Normal
maps are generated from the height field with the OpenGL (+Y up) convention,
which is what Godot assumes by default.

No lighting is baked into any albedo map: the albedo channels contain material
colour and dirt/wear variation only.

Outputs (per set, <set>_<channel>_<res>.png):
    stone_ashlar_01   albedo normal rough ao height   2k, covers 8 m  (256 px/m)
    stone_ashlar_02   albedo normal rough ao height   1k, covers 4 m  (256 px/m)
    floor_flagstone_01 albedo normal rough ao height  2k, covers 8 m  (256 px/m)
    trim_sheet_01     albedo normal rough ao          1k, covers 4 m
    wood_timber_01    albedo normal rough              1k, covers 2 m
    metal_iron_01     albedo normal rough metal        512, covers 1 m
    moss_01           albedo normal rough (albedo RGBA decal) 1k, covers 2 m
    dirt_ground_01    albedo normal rough (albedo RGBA decal) 1k, covers 4 m
    foliage_leafcard_01 albedo normal (RGBA card)     512
    grass_blade_01    albedo (RGBA card)              512
"""

import os
import sys
import zlib
import struct
import argparse

import numpy as np


# --------------------------------------------------------------------- png io

def write_png(path: str, arr: np.ndarray) -> None:
    """Write an HxW, HxWx3 (RGB) or HxWx4 (RGBA) float array in 0..1 as PNG."""
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=-1)
    a = (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    height, width, channels = a.shape
    color_type = 6 if channels == 4 else 2
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        raw.extend(a[y].tobytes())

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = b"\x89PNG\r\n\x1a\n"
    blob += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
    blob += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    blob += chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(blob)


def srgb(linear: np.ndarray) -> np.ndarray:
    """Linear -> sRGB encode (per channel, matches the engine's transfer)."""
    a = np.clip(linear, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1.0 / 2.4) - 0.055)


# ------------------------------------------------------------------- fields

def value_noise(res: int, freq: int, seed: int) -> np.ndarray:
    """Tileable bilinear-smoothstep value noise on a res x res grid."""
    rng = np.random.default_rng(seed)
    grid = rng.random((freq + 1, freq + 1)).astype(np.float32)
    grid[-1, :] = grid[0, :]
    grid[:, -1] = grid[:, 0]
    ys = np.linspace(0.0, freq, res, endpoint=False, dtype=np.float32)
    xs = np.linspace(0.0, freq, res, endpoint=False, dtype=np.float32)
    x0 = xs.astype(np.int32)
    y0 = ys.astype(np.int32)
    fx = (xs - x0)[None, :]
    fy = (ys - y0)[:, None]
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    v00 = grid[np.ix_(y0, x0)]
    v10 = grid[np.ix_(y0, x0 + 1)]
    v01 = grid[np.ix_(y0 + 1, x0)]
    v11 = grid[np.ix_(y0 + 1, x0 + 1)]
    top = v00 + (v10 - v00) * fx
    bot = v01 + (v11 - v01) * fx
    return top + (bot - top) * fy


def fbm(res: int, base_freq: int, octaves: int, seed: int,
        gain: float = 0.5, lacunarity: int = 2) -> np.ndarray:
    total = np.zeros((res, res), np.float32)
    amp = 1.0
    freq = base_freq
    norm = 0.0
    for octave in range(octaves):
        total += amp * value_noise(res, max(1, freq), seed + octave * 101)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def blur(field: np.ndarray, radius: int) -> np.ndarray:
    """Cheap wrap-around blur (radius small, ~gaussian for our purposes)."""
    out = field.copy()
    for i in range(1, radius + 1):
        out = (out + np.roll(field, i, 0) + np.roll(field, -i, 0)
               + np.roll(field, i, 1) + np.roll(field, -i, 1)) / 5.0
    return out


def normal_from_height(height: np.ndarray, strength: float) -> np.ndarray:
    """OpenGL-convention tangent normal map from a height field (0..1)."""
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    # Row index grows downward (texture V grows downward in Godot's images), so
    # the +Y (up) component is the negative row gradient.  Godot's default is
    # OpenGL (+Y), matching this.
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    normal = np.stack([-dx, dy, np.ones_like(height)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal * 0.5 + 0.5


def height_ao(height: np.ndarray, strength: float = 2.5,
              radius: int = 6, floor: float = 0.35) -> np.ndarray:
    """Height-field ambient occlusion: concavities darken, convexities stay open."""
    low = blur(height, radius)
    ao = 1.0 - np.clip((low - height) * strength, 0.0, 1.0)
    return np.clip(ao, floor, 1.0)


def grey(value: float) -> np.ndarray:  # placeholder helper for clarity
    return np.full((1, 1), value, np.float32)


# -------------------------------------------------------------------- stone

def _ashlar_layout(res: int, metres: float, block_w: float, block_h: float,
                   bond_offset: float = 0.5):
    """Staggered running-bond block layout fields (row, col, u, v in 0..1)."""
    px_per_m = res / metres
    rows = max(2, int(round(metres / block_h)))
    cols = max(2, int(round(metres / block_w)))
    yy, xx = np.mgrid[0:res, 0:res].astype(np.float32)
    row_f = yy / res * rows
    row = row_f.astype(np.int32) % rows
    x_off = (row % 2).astype(np.float32) * bond_offset
    col_f = xx / res * cols + x_off
    col = np.floor(col_f).astype(np.int32) % cols
    u = col_f - np.floor(col_f)
    v = row_f - np.floor(row_f)
    return row, col, u, v, rows, cols, px_per_m


def build_ashlar(res: int, metres: float, seed: int,
                 block_w: float = 1.55, block_h: float = 0.78,
                 base: tuple = (0.52, 0.48, 0.42), variation: float = 0.26,
                 mortar: tuple = (0.20, 0.185, 0.165), wear: float = 1.0,
                 chipped: float = 1.0) -> dict:
    """A dressed-ashlar stone set: albedo / height / normal / rough / ao.

    Large coursed blocks with a real recessed joint, per-course height jitter,
    corner wear and rain staining. No directional light is baked in: the
    brightness differences are material age and dirt only.
    """
    row, col, u, v, rows, cols, px_per_m = _ashlar_layout(res, metres, block_w, block_h)
    rng = np.random.default_rng(seed)
    block_rand = rng.random((rows, cols)).astype(np.float32)
    block_rand2 = rng.random((rows, cols)).astype(np.float32)
    block_rand3 = rng.random((rows, cols)).astype(np.float32)
    course_jitter = (rng.random(rows).astype(np.float32) - 0.5) * 0.02

    # Joint: a real recess (3-4 cm) whose width wobbles with the stone.
    edge_m = np.minimum(np.minimum(u, 1.0 - u) * block_w, np.minimum(v, 1.0 - v) * block_h)
    joint_wobble = (fbm(res, 20, 3, seed + 7) - 0.5) * 0.02 * wear
    joint_w = np.maximum(0.012, 0.034 + joint_wobble)
    joint_mask = np.clip(1.0 - edge_m / joint_w, 0.0, 1.0)
    joint_mask = joint_mask * joint_mask * (3.0 - 2.0 * joint_mask)

    # Corner chips: only near block corners, never across the face.
    corner_prox = np.maximum(np.clip(1.0 - np.minimum(u, 1.0 - u) / 0.14, 0.0, 1.0),
                             np.clip(1.0 - np.minimum(v, 1.0 - v) / 0.12, 0.0, 1.0))
    chip_noise = fbm(res, 30, 4, seed + 13)
    chip = np.clip((chip_noise - 0.70) * 7.0, 0.0, 1.0) * corner_prox * chipped
    chip *= np.clip(1.0 - joint_mask * 2.0, 0.0, 1.0)

    # Face relief: shallow dome per block, fine tooling marks, course jitter.
    dome = (np.sin(u * np.pi) * 0.09 + np.sin(v * np.pi) * 0.07)
    tooling = (fbm(res, 110, 3, seed + 21) - 0.5) * 0.06
    course = course_jitter[row]
    height = 0.78 + dome + tooling + course
    height -= joint_mask * 0.46
    height -= chip * 0.16
    height = np.clip(height, 0.0, 1.25)

    # Albedo: stronger per-block value variation, vertical rain streaks that
    # run down the wall (stretched noise), grime collecting in the joint.
    tint = ((block_rand - 0.35) * variation)[row, col]
    tint2 = (block_rand2 - 0.5)[row, col] * 0.08
    broad = (fbm(res, 10, 4, seed + 33) - 0.5) * 0.20 * wear
    # Rain streaks: a coarse field repeated vertically, so variation is
    # horizontal only and the stain runs down the wall.
    streak_field = fbm(max(8, res // 8), 24, 3, seed + 41)
    streaks = np.repeat(np.repeat(streak_field, 8, axis=0), 8, axis=1)[:res, :res]
    streaks = blur(streaks, 2)
    streaks = (streaks - 0.5) * 0.16 * wear
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = base[c] * (1.0 + tint + tint2 + broad + streaks)
    # Joint: dark and earthy, with grime creeping 4-6 cm onto the block edge.
    grime = np.clip(joint_mask * 1.25 + np.clip(1.0 - edge_m / 0.07, 0.0, 1.0) * 0.35 * wear, 0.0, 1.0)
    for c in range(3):
        albedo[..., c] = albedo[..., c] * (1.0 - grime * 0.72) + mortar[c] * grime * 0.72
    raw_stone = np.float32(0.66)
    albedo = albedo * (1.0 - chip[..., None] * 0.55) + raw_stone * chip[..., None] * 0.55
    albedo = np.clip(albedo, 0.02, 1.0)

    # Roughness: stone semi-matte; joints and stains rougher; chips rawer.
    rough = 0.60 + (block_rand3 - 0.5)[row, col] * 0.16
    rough = rough + (fbm(res, 40, 3, seed + 55) - 0.5) * 0.14
    rough = rough * (1.0 - joint_mask) + 0.94 * joint_mask
    rough = np.clip(rough + np.abs(streaks) * 0.4 + chip * 0.08, 0.3, 1.0)

    ao = height_ao(height, strength=2.0, radius=max(2, res // 256))

    return {
        "albedo": srgb(albedo),
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 2.4),
        "rough": rough,
        "ao": ao,
    }


def build_flagstones(res: int, metres: float, seed: int) -> dict:
    """Larger irregular flag floor slabs with worn traffic paths."""
    row, col, u, v, rows, cols, _ = _ashlar_layout(res, metres, 1.55, 1.55, bond_offset=0.5)
    rng = np.random.default_rng(seed)
    rand = rng.random((rows, cols)).astype(np.float32)
    rand2 = rng.random((rows, cols)).astype(np.float32)

    edge_m = np.minimum(np.minimum(u, 1.0 - u), np.minimum(v, 1.0 - v)) * (metres / rows)
    joint = fbm(res, 20, 3, seed + 3) * 0.02
    joint_mask = np.clip(1.0 - edge_m / np.maximum(0.018 + joint, 1e-5), 0.0, 1.0)
    joint_mask = joint_mask * joint_mask * (3.0 - 2.0 * joint_mask)

    wear = fbm(res, 8, 4, seed + 9)          # broad polish variation
    grain = fbm(res, 80, 4, seed + 15)
    height = 0.78 + (rand * 0.06)[row, col] + (grain - 0.5) * 0.10
    height -= joint_mask * 0.34
    height = np.clip(height, 0.0, 1.1)

    base = np.array([0.44, 0.43, 0.40], np.float32)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = base[c] * (1.0 + (rand - 0.5)[row, col] * 0.20
                                    + (rand2 - 0.5)[row, col] * 0.10
                                    + (grain - 0.5) * 0.16
                                    + (wear - 0.5) * 0.20)
    dark = np.array([0.24, 0.23, 0.21], np.float32)
    for c in range(3):
        albedo[..., c] = albedo[..., c] * (1.0 - joint_mask * 0.6) + dark[c] * joint_mask * 0.6
    # Slight polish where the wear field is high (traffic paths).
    polish = np.clip((wear - 0.55) * 2.0, 0.0, 1.0)
    rough = np.clip(0.66 - polish * 0.22 + (grain - 0.5) * 0.12 + joint_mask * 0.3, 0.18, 1.0)

    return {
        "albedo": srgb(albedo),
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 2.0),
        "rough": rough,
        "ao": height_ao(height, strength=2.0, radius=max(2, res // 256)),
    }


def build_trim_sheet(res: int, seed: int) -> dict:
    """Four horizontal trim bands (plinth, string course, cornice, plain ashlar).

    The kit maps each trim piece into its band, so a single sheet dresses every
    sill, band and cornice in the castle at a consistent scale.
    """
    yy, xx = np.mgrid[0:res, 0:res].astype(np.float32)
    v = yy / res
    band_id = np.clip((v * 4.0).astype(np.int32), 0, 3)

    grain = fbm(res, 80, 4, seed + 5)
    base = np.array([0.66, 0.62, 0.55], np.float32)
    height = np.full((res, res), 0.75, np.float32)

    # Band 0: plinth (chamfer at its top edge).
    plinth = (band_id == 0)
    chamfer = np.clip((0.235 - v) / 0.02, 0.0, 1.0)
    height = np.where(plinth, 0.78 + chamfer * 0.10, height)
    # Band 1: string course with a deep shadow groove at each edge.
    string = (band_id == 1)
    groove = np.minimum(np.abs(v - 0.25 + 0.018), np.abs(v - 0.5 + 0.018))
    height = np.where(string, np.clip(0.90 - np.clip((0.012 - groove) / 0.012, 0, 1) * 0.5, 0, 1.2), height)
    # Band 2: cornice (cavetto profile).
    corn = (band_id == 2)
    prof = np.clip((v - 0.5) / 0.25, 0.0, 1.0)
    height = np.where(corn, 0.72 + (prof * prof * 0.45), height)
    # Band 3: plain ashlar dresser.
    ashlar_blocks = np.sin(xx / res * 16.0 * np.pi) * 0.5 + 0.5
    height = np.where(band_id == 3, 0.8 + ashlar_blocks * 0.03, height)

    height += (grain - 0.5) * 0.06
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = base[c] * (1.0 + (grain - 0.5) * 0.18 + (band_id * 0.01))
    rough = np.clip(0.58 + (grain - 0.5) * 0.16 + (band_id == 0) * 0.08, 0.3, 1.0)

    return {
        "albedo": srgb(albedo),
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 1.8),
        "rough": rough,
        "ao": height_ao(height, strength=2.4, radius=max(2, res // 128)),
    }


def build_wood(res: int, seed: int, dark: float = 1.0) -> dict:
    """Straight-grain timber with knots, for furniture and doors."""
    stretch = 6  # grain runs along one axis
    grain = fbm(res, 4, 5, seed + 2)
    lines = np.sin((grain * 26.0 + fbm(res, 24, 3, seed + 4) * 2.0) * np.pi)
    lines = 0.5 + 0.5 * lines
    fine = fbm(res, 200, 3, seed + 8)
    knots = np.clip((fbm(res, 12, 3, seed + 11) - 0.72) * 8.0, 0.0, 1.0)

    light = np.array([0.42, 0.28, 0.16], np.float32) * dark
    darkc = np.array([0.22, 0.13, 0.07], np.float32) * dark
    albedo = np.zeros((res, res, 3), np.float32)
    t = np.clip(lines * 0.7 + fine * 0.3, 0.0, 1.0)
    for c in range(3):
        albedo[..., c] = light[c] * t + darkc[c] * (1.0 - t)
    albedo *= (1.0 - knots[..., None] * 0.55)
    rough = np.clip(0.62 + (fine - 0.5) * 0.22 + knots * 0.15, 0.35, 0.95)
    height = t * 0.35 + 0.5 - knots * 0.2
    return {
        "albedo": srgb(albedo),
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 0.9),
        "rough": rough,
    }


def build_iron(res: int, seed: int) -> dict:
    """Dark forged iron: pitted, semi-rough, metallic (used where metal is real)."""
    pits = fbm(res, 48, 4, seed + 3)
    scratches = np.clip(np.abs(np.sin(fbm(res, 6, 3, seed + 9) * 40.0)) - 0.6, 0.0, 1.0)
    base = np.array([0.10, 0.105, 0.12], np.float32)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = base[c] * (1.0 + (pits - 0.5) * 0.5 + scratches * 0.5)
    rough = np.clip(0.42 + (pits - 0.5) * 0.25 - scratches * 0.15, 0.18, 0.8)
    height = 0.5 + (pits - 0.5) * 0.5
    return {
        "albedo": srgb(albedo),
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 0.7),
        "rough": rough,
    }


def build_moss(res: int, seed: int) -> dict:
    """Moss decal: soft irregular alpha patch, dense mat albedo, fuzz normal."""
    blob = fbm(res, 5, 5, seed + 1)
    blob2 = fbm(res, 14, 4, seed + 2)
    mask = np.clip((blob * 0.65 + blob2 * 0.35 - 0.42) * 3.4, 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)
    fuzz = fbm(res, 160, 3, seed + 5)
    fine = fbm(res, 320, 2, seed + 6)
    deep = np.array([0.10, 0.20, 0.07], np.float32)
    bright = np.array([0.28, 0.44, 0.15], np.float32)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = deep[c] + (bright[c] - deep[c]) * (fuzz * 0.6 + fine * 0.4) * mask
    height = 0.5 + (fuzz - 0.5) * 0.5 * mask
    # Alpha: the mask, hardened at its edge so mipmaps do not smear a halo.
    alpha = np.clip((mask - 0.06) * 1.3, 0.0, 1.0)
    rgba = np.concatenate([srgb(albedo), alpha[..., None]], axis=-1)
    return {
        "albedo": rgba,
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 0.8),
        "rough": np.clip(0.9 + (fine - 0.5) * 0.1, 0.7, 1.0),
    }


def build_dirt(res: int, seed: int) -> dict:
    """Trampled ground decal: soft-edged earth patch with pebbles."""
    blob = fbm(res, 5, 5, seed + 1)
    mask = np.clip((blob - 0.40) * 3.0, 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)
    fine = fbm(res, 180, 3, seed + 4)
    pebble_noise = fbm(res, 40, 2, seed + 7)
    pebbles = np.clip((pebble_noise - 0.68) * 9.0, 0.0, 1.0)
    earth = np.array([0.33, 0.26, 0.18], np.float32)
    stone = np.array([0.45, 0.43, 0.40], np.float32)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = earth[c] * (0.75 + fine * 0.5)
        albedo[..., c] = albedo[..., c] * (1.0 - pebbles * 0.6) + stone[c] * pebbles * 0.6
    height = 0.5 + (fine - 0.5) * 0.25 + pebbles * 0.3
    alpha = np.clip((mask - 0.08) * 1.4, 0.0, 1.0)
    rgba = np.concatenate([srgb(albedo), alpha[..., None]], axis=-1)
    return {
        "albedo": rgba,
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 1.2),
        "rough": np.clip(0.95 - pebbles * 0.2 + (fine - 0.5) * 0.06, 0.6, 1.0),
    }


def build_grass_ground(res: int, seed: int) -> dict:
    """Opaque meadow ground: mottled green with clumped blades and bare patches."""
    base = fbm(res, 6, 5, seed + 1)
    clumps = fbm(res, 26, 4, seed + 2)
    blades = np.clip(np.abs(np.sin(fbm(res, 90, 3, seed + 3) * 44.0)), 0.0, 1.0)
    patch = np.clip((fbm(res, 9, 3, seed + 4) - 0.45) * 3.0, 0.0, 1.0)
    deep = np.array([0.09, 0.20, 0.06], np.float32)
    bright = np.array([0.30, 0.46, 0.16], np.float32)
    soil = np.array([0.30, 0.24, 0.15], np.float32)
    t = np.clip(base * 0.55 + clumps * 0.45, 0.0, 1.0)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = deep[c] + (bright[c] - deep[c]) * t
        albedo[..., c] = albedo[..., c] * (1.0 - blades * 0.28)
        albedo[..., c] = albedo[..., c] * (1.0 - patch * 0.7) + soil[c] * patch * 0.7
    height = 0.5 + (clumps - 0.5) * 0.5 + blades * 0.10 - patch * 0.12
    return {
        "albedo": srgb(albedo),
        "height": height,
        "normal": normal_from_height(height, strength=res / 512.0 * 1.4),
        "rough": np.clip(0.92 + (blades - 0.5) * 0.08, 0.7, 1.0),
        "ao": height_ao(height, strength=1.4, radius=max(2, res // 256)),
    }


def _leaf_alpha(res: int, count: int, seed: int) -> tuple:
    """Draw a cluster of rotated leaf ellipses; returns (alpha, leaf_id)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:res, 0:res].astype(np.float32)
    alpha = np.zeros((res, res), np.float32)
    leaf_id = np.zeros((res, res), np.float32)
    for i in range(count):
        cx = rng.uniform(0.10, 0.90) * res
        cy = rng.uniform(0.10, 0.90) * res
        ang = rng.uniform(0, np.pi)
        length = rng.uniform(0.06, 0.13) * res
        width = length * rng.uniform(0.35, 0.55)
        # Distance from cluster centre, biased to the upper half of the card is
        # handled by the caller; here scatter is uniform.
        dx = xx - cx
        dy = yy - cy
        u = dx * np.cos(ang) + dy * np.sin(ang)
        v = -dx * np.sin(ang) + dy * np.cos(ang)
        inside = (u / length) ** 2 + (v / width) ** 2 <= 1.0
        tip = np.clip(1.0 - ((u / length) ** 2), 0.0, 1.0)
        a = np.where(inside, np.clip(tip * 2.2, 0.4, 1.0), 0.0).astype(np.float32)
        alpha = np.maximum(alpha, a)
        leaf_id = np.where(a > 0.05, float(i), leaf_id)
    return alpha, leaf_id


def build_leafcard(res: int, seed: int) -> dict:
    alpha, leaf_id = _leaf_alpha(res, 58, seed)
    # Rounded canopy silhouette, but the interior stays leaf-shaped with
    # transparent gaps so the card reads as foliage, not a solid blob.
    yy, xx = np.mgrid[0:res, 0:res].astype(np.float32)
    canopy = 1.0 - np.clip((((xx / res - 0.5) * 2.1) ** 2 + ((yy / res - 0.55) * 1.9) ** 2) - 0.30, 0.0, 1.0)
    alpha = alpha * (0.45 + 0.55 * np.clip(canopy * 1.8, 0.0, 1.0))
    leaf_var = (np.sin(leaf_id * 12.9898) * 43758.5453) % 1.0
    dark = np.array([0.05, 0.14, 0.04], np.float32)
    light = np.array([0.16, 0.34, 0.10], np.float32)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = dark[c] + (light[c] - dark[c]) * leaf_var
    rgba = np.concatenate([srgb(albedo), np.clip(alpha * 1.4, 0.0, 1.0)[..., None]], axis=-1)
    return {"albedo": rgba, "normal": np.full((res, res, 3), 0.5, np.float32) + np.array([0, 0, 0.5])}


def build_grass_blade(res: int, seed: int) -> dict:
    """Cross-quad grass card: a few blades on transparent background."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:res, 0:res].astype(np.float32)
    alpha = np.zeros((res, res), np.float32)
    for i in range(9):
        base_x = rng.uniform(0.1, 0.9) * res
        height = rng.uniform(0.55, 0.95)
        width = rng.uniform(0.035, 0.06) * res
        lean = rng.uniform(-0.2, 0.2)
        t = np.clip((res * (1.0 - height) + (yy - res * (1.0 - height))), 0.0, res) / res
        cx = base_x + lean * (yy / res) * res
        taper = np.clip((yy / res - (1.0 - height)) / max(height, 1e-4), 0.0, 1.0)
        w = width * (1.0 - taper * 0.85)
        alpha = np.maximum(alpha, np.clip(1.0 - np.abs(xx - cx) / np.maximum(w, 1e-4), 0.0, 1.0))
    alpha = np.clip(alpha * 1.6, 0.0, 1.0)
    green = fbm(res, 40, 3, seed + 3)
    albedo = np.zeros((res, res, 3), np.float32)
    for c in range(3):
        albedo[..., c] = [0.10, 0.22, 0.06][c] + green * [0.08, 0.16, 0.04][c]
    rgba = np.concatenate([srgb(albedo), alpha[..., None]], axis=-1)
    return {"albedo": rgba}


# ------------------------------------------------------------------- driver

SETS = {}

def register_sets():
    SETS["stone_ashlar_01"] = lambda: build_ashlar(
        2048, 8.0, 101, block_w=1.55, block_h=0.78, base=(0.52, 0.48, 0.42),
        variation=0.26, mortar=(0.20, 0.185, 0.165), wear=1.0, chipped=1.0)
    SETS["stone_ashlar_02"] = lambda: build_ashlar(
        1024, 4.0, 202, block_w=0.95, block_h=0.50, base=(0.34, 0.325, 0.31),
        variation=0.32, mortar=(0.13, 0.125, 0.12), wear=1.5, chipped=0.5)
    SETS["floor_flagstone_01"] = lambda: build_flagstones(2048, 8.0, 303)
    SETS["trim_sheet_01"] = lambda: build_trim_sheet(1024, 404)
    SETS["wood_timber_01"] = lambda: build_wood(1024, 505, dark=1.0)
    SETS["metal_iron_01"] = lambda: build_iron(512, 606)
    SETS["moss_01"] = lambda: build_moss(1024, 707)
    SETS["grass_ground_01"] = lambda: build_grass_ground(1024, 909)
    SETS["dirt_ground_01"] = lambda: build_dirt(1024, 808)
    SETS["foliage_leafcard_01"] = lambda: build_leafcard(512, 909)
    SETS["grass_blade_01"] = lambda: build_grass_blade(512, 1010)


RES_SUFFIX = {
    512: "512", 1024: "1k", 2048: "2k", 4096: "4k",
}


def main() -> None:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    parsed = parser.parse_args(args)
    register_sets()
    names = [parsed.only] if parsed.only else list(SETS.keys())
    for name in names:
        data = SETS[name]()
        folder = os.path.join(parsed.out, name)
        os.makedirs(folder, exist_ok=True)
        for channel, field in data.items():
            if channel == "height":
                # Height stays for authoring/reference; not loaded by the game.
                pass
            suffix = RES_SUFFIX.get(field.shape[0], str(field.shape[0]))
            path = os.path.join(folder, "%s_%s_%s.png" % (name, channel, suffix))
            write_png(path, field)
            channels = field.shape[2] if field.ndim == 3 else 1
            print("[kit-textures] wrote %s (%dx%d, %d ch)" % (path, field.shape[1], field.shape[0], channels))
        # A tiny provenance note beside the maps.
        with open(os.path.join(folder, "PROVENANCE.txt"), "w", encoding="utf-8") as handle:
            handle.write(
                "Project-original procedural texture set '%s'.\n"
                "Authored in Blender %s via client/tools/blender/kit_textures.py.\n"
                "License: project-original (CC0-equivalent dedication by the project).\n"
                "Generated: deterministic seeded numpy fields; re-running the script reproduces\n"
                "these files byte-for-byte.\n" % (name, ".".join(str(v) for v in __import__("bpy").app.version)))


if __name__ == "__main__":
    main()
