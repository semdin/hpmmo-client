"""Build the boss creature: the Acromantula Matriarch.

Project-original, authored parametrically in Blender. Nothing is imported and
nothing is downloaded: every vertex, UV, weight, key and texel in the shipped
GLB is produced by this file, deterministically (fixed seeds; two runs print
identical counts).

What makes it read as a boss rather than "the spider again, with more HP":
  * leg span 3.2 m (the ordinary acromantula is 2.2-2.4 m) and a raised, spiked
    carapace carrying a crown of eight backward-swept, bone-tipped spikes
    (0.25-0.36 m) over a bristle crest, so the silhouette is taller and much
    spikier at 20 m;
  * thicker barbed legs - every femur/tibia carries a comb of spurs and a
    bristle fringe - and a heavy mottled abdomen with a pale egg sac slung
    under its rear, a second readability shape that no other mob has;
  * a glowing red eye cluster (emissive material) and oversize protruding
    fangs with deep red tips;
  * its own attack vocabulary: Slam_Anticipation/Slam_Attack (rear up, front
    two leg pairs crash down) and Spit_Anticipation/Spit_Attack (tilt back,
    fangs spread, then a thrust along the facing direction).

Authoring convention: forward +Z for creatures.
Blender is Z-up / -Y-forward and the glTF exporter maps Blender -Y -> glTF +Z,
so the head is authored towards -Y. Up stays +Y in Godot. 1 unit = 1 metre,
bind-pose feet on the ground plane (lowest vertex within 2 cm of y=0).

Rig: 49 bones - Root, Body, Abdomen, Head, Chelicera_L/R, Pedipalp_L/R,
EggSac, and 8 legs x (Coxa, Femur, Patella, Tibia, Tarsus) as Leg{L,R}{1..4}_*.
Skin weights are computed here from bind-pose bone-segment distance with a
per-part bone whitelist and a soft falloff, so joints blend smoothly and no
weight bleeds across legs.

Feet are placed by an analytic 2-link in-plane IK solver (see leg_ik): every key
of Walk/Idle/Hit/Stun and of the planted legs of the attack clips names a
world-space foot target, so a stance foot stays exactly where it was put
(measured residual 0.00000 m) instead of skating. Walk stance is a straight,
constant-speed sweep, so the clip implies a ground speed the mob can match
(printed at validation).

Every clip is swept frame by frame after authoring: the evaluated mesh may not
pierce the ground plane, and Death's corpse must be lower than its first frame.

Textures are generated in numpy and packed into the GLB:
    matriarch_albedo  1024 sRGB   (encoded here; no lighting baked in)
    matriarch_normal  1024 OpenGL (+Y) tangent normal from a height field
    matriarch_rough    512 linear
Each is one atlas; islands are shelf-packed per region with a gutter, and the
islands are dilated into the gutters before the normal is differenced so the
maps stay seamless at island borders. UVs are 0-1 with no mirroring and no
overlap (uv_mirrored=0).

Run headless (always --factory-startup):
    blender -b --factory-startup --python build_boss_matriarch.py -- \
        --out client/assets/models/monsters/boss_matriarch.glb [--render <dir>]
"""

import math
import os
import sys

import numpy as np
import bpy
from mathutils import Matrix, Quaternion, Vector

# --------------------------------------------------------------------- args

def _argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(name, default=None):
    argv = _argv()
    return argv[argv.index(name) + 1] if name in argv else default


OUT = _arg("--out")
if not OUT:
    raise SystemExit("[matriarch] usage: --out <path.glb> [--render <dir>]")
OUT = os.path.abspath(OUT)
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RENDER_DIR = os.path.abspath(_arg("--render") or os.path.join(PROJECT, "client", "tools", "downloads"))
MAKE_LOD1 = "--no-lod1" not in _argv()

SEED = 20261005
FPS = 24
# Bone count the rig must have: 9 core + 8 legs x 5 segments.
EXPECTED_BONES = 49

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = FPS
bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = 1.0

print("[matriarch] blender %s" % bpy.app.version_string)
print("[matriarch] out=%s" % OUT)

# --------------------------------------------------------------- dimensions

# Leg geometry. Every number is metres in Blender space (X right, -Y forward,
# Z up) and is used both to lay the bones out and to build the mesh, so the
# bind pose and the rest skeleton cannot drift apart.
HIP_X = 0.26                        # hip attachment, distance off the centre line
HIP_Y = (-0.40, -0.20, 0.00, 0.16)  # front to rear
HIP_Z = 0.52
AZIMUTH = tuple(math.radians(a) for a in (-34.0, -11.0, 12.0, 36.0))

COXA_OUT, COXA_UP = 0.14, 0.06      # hip -> shoulder
FEMUR_LEN, FEMUR_ANG = 0.55, math.radians(28.0)     # shoulder -> patella head
PATELLA_LEN, PATELLA_ANG = 0.13, math.radians(18.0)
TIBIA_LEN, TIBIA_ANG = 0.82, math.radians(-60.0)    # -> ankle, then the tarsus
TARSUS_ANG = math.radians(-37.26)                   # chosen so the tip lands on z=0

SEG_R = {                            # (start radius, end radius) per segment
    "Coxa": (0.090, 0.078),
    "Femur": (0.082, 0.068),
    "Patella": (0.066, 0.060),
    "Tibia": (0.058, 0.036),
    "Tarsus": (0.036, 0.017),
}

# Body masses.
CEPH_C = Vector((0.0, -0.26, 0.655))
CEPH_R = Vector((0.335, 0.360, 0.180))
ABDO_C = Vector((0.0, 0.340, 0.650))
ABDO_R = Vector((0.395, 0.520, 0.290))
EGG_C = Vector((0.0, 0.715, 0.375))
EGG_R = Vector((0.285, 0.300, 0.285))
HEAD_Y = -0.62

DENSITY = dict(                      # tessellation knobs (tri budget lives here)
    ceph_seg=64, ceph_ring=28,
    abdo_seg=68, abdo_ring=30,
    egg_seg=44, egg_ring=18,
    leg_sides=20, leg_station=6,
    joint_sides=14, joint_ring=7,
    eye_seg=12, eye_ring=6,
    spike_sides=14, spike_station=5,
    palp_sides=12, palp_station=5,
    barb_sides=6,
    barb_count=9,                    # spurs per leg (femur + tibia comb)
    hair_count=30,                   # bristles per leg
    body_hair=260,                   # bristles on the abdomen/carapace fringe
)

MAT_CHITIN, MAT_MEMBRANE, MAT_EYES, MAT_FANGSAC = 0, 1, 2, 3

# ------------------------------------------------------------------ textures
# One atlas per channel, split into regions; every UV island is shelf-packed
# inside its region and painted with the region's pattern, so island content is
# explicit instead of "whatever happens to be under the UV".

S = 1024
REGIONS = {
    # name       u0     v0     u1     v1    cols rows
    "chitin": (0.008, 0.008, 0.492, 0.492, 26, 26),
    "membrane": (0.508, 0.008, 0.992, 0.492, 16, 16),
    "abdomen": (0.008, 0.508, 0.492, 0.992, 12, 12),
    "egg": (0.508, 0.508, 0.828, 0.992, 8, 8),
    "fang": (0.836, 0.508, 0.992, 0.992, 8, 8),
}
REGION_ROLE = {
    "chitin": "chitin", "membrane": "membrane", "abdomen": "abdomen",
    "egg": "egg", "fang": "fang",
}


def vnoise(h, w, freq, seed):
    """Tileable bilinear-smoothstep value noise on an h x w grid. The cell count
    is clamped so a cell is never smaller than 4 px: small UV islands would
    otherwise alias into per-pixel randomness (ugly normal maps, huge PNGs)."""
    freq = max(1, min(int(freq), max(1, min(h, w) // 4)))
    rng = np.random.default_rng(seed)
    g = rng.random((freq + 1, freq + 1)).astype(np.float32)
    g[-1, :] = g[0, :]
    g[:, -1] = g[:, 0]
    ys = np.linspace(0.0, freq, h, endpoint=False, dtype=np.float32)
    xs = np.linspace(0.0, freq, w, endpoint=False, dtype=np.float32)
    x0 = xs.astype(np.int32)
    y0 = ys.astype(np.int32)
    fx = (xs - x0)[None, :]
    fy = (ys - y0)[:, None]
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    v00 = g[np.ix_(y0, x0)]
    v10 = g[np.ix_(y0, x0 + 1)]
    v01 = g[np.ix_(y0 + 1, x0)]
    v11 = g[np.ix_(y0 + 1, x0 + 1)]
    top = v00 + (v10 - v00) * fx
    bot = v01 + (v11 - v01) * fx
    return top + (bot - top) * fy


def fbm(h, w, base, octaves, seed, gain=0.5):
    total = np.zeros((h, w), np.float32)
    amp, freq, norm = 1.0, base, 0.0
    for o in range(octaves):
        total += amp * vnoise(h, w, max(1, int(freq)), seed + o * 101)
        norm += amp
        amp *= gain
        freq *= 2
    return total / norm


def srgb(a):
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1.0 / 2.4) - 0.055)


def smooth(field, passes=1):
    """3x3-ish blur: trims per-pixel noise so the normal map is smooth shading
    detail instead of static (and compresses far better as PNG)."""
    out = field
    for _ in range(passes):
        out = (out * 4.0 + np.roll(out, 1, 0) + np.roll(out, -1, 0)
               + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 8.0
    return out


def normal_from_height(height, strength):
    """OpenGL (+Y) tangent normal from a height field (Godot's default)."""
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    n = np.stack([-dx, dy, np.ones_like(height)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


CHITIN_DARK = np.array([0.070, 0.016, 0.026], np.float32)
CHITIN_MID = np.array([0.185, 0.042, 0.055], np.float32)
BONE = np.array([0.660, 0.585, 0.415], np.float32)
CREAM = np.array([0.760, 0.700, 0.540], np.float32)
MEMB = np.array([0.085, 0.062, 0.050], np.float32)
FANGRED = np.array([0.330, 0.020, 0.028], np.float32)


def pattern(role, h, w, seed, opts=None):
    """Per-island material content. Returns (albedo_linear, height, roughness)."""
    opts = opts or {}
    u = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    v = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    n_big = fbm(h, w, 3, 4, seed)
    n_mid = fbm(h, w, 9, 4, seed + 31)
    n_fine = fbm(h, w, 26, 3, seed + 71)
    detail = 0.55 * n_mid + 0.45 * n_fine

    if role == "chitin":
        # Banding runs along u (tube length): darker, recessed seams every
        # segment. opts["bands"] adds the joint rings.
        t = np.clip(0.62 * n_big + 0.38 * detail, 0.0, 1.0)
        alb = CHITIN_DARK[None, None, :] + (CHITIN_MID - CHITIN_DARK)[None, None, :] * t[..., None]
        hgt = 0.35 * t + 0.65 * detail
        rough = 0.24 + 0.10 * n_big
        if opts.get("bands"):
            band = 0.5 + 0.5 * np.cos(2.0 * math.pi * u * opts["bands"])
            seam = np.clip((band - 0.72) / 0.28, 0.0, 1.0)
            alb *= (1.0 - 0.38 * seam)[..., None]
            hgt = hgt * (1.0 - 0.8 * seam) - 0.10 * seam
            rough = rough + 0.18 * seam
        # coarse pale flecks (worn plate, mineral dust)
        fleck = np.clip((n_fine - 0.78) / 0.22, 0.0, 1.0)
        alb = alb + (BONE * 0.55 - alb) * (fleck * 0.35)[..., None]
        return alb, hgt, np.clip(rough, 0.16, 0.62)

    if role == "spike":
        # u runs base -> tip: chitin at the root, pale bone at the point, with
        # longitudinal ridges in the height field.
        g = np.clip((u - 0.04) / 0.70, 0.0, 1.0) ** 0.7
        base = CHITIN_DARK[None, None, :] + (CHITIN_MID - CHITIN_DARK)[None, None, :] * detail[..., None]
        alb = base + (BONE[None, None, :] - base) * g[..., None]
        ridge = 0.5 + 0.5 * np.cos(2.0 * math.pi * v * opts.get("ridges", 5))
        hgt = 0.75 * ridge * (0.55 + 0.45 * n_fine) + 0.25 * g
        rough = 0.30 - 0.12 * g + 0.06 * n_mid
        return alb, hgt, np.clip(rough, 0.15, 0.55)

    if role == "abdomen":
        # Broad mottling: cream blotches over the dark ground, warm olive
        # patches between, thin dark crest lines. Reads at 20 m.
        blotch = fbm(h, w, 2, 3, seed + 5)
        m = np.clip((blotch - 0.46) / 0.32, 0.0, 1.0)
        alb = CHITIN_DARK[None, None, :] + (CHITIN_MID - CHITIN_DARK)[None, None, :] * detail[..., None]
        cream = CREAM * 0.85
        alb = alb + (cream[None, None, :] - alb) * np.clip(m * 0.85, 0, 1)[..., None]
        olive = np.array([0.085, 0.075, 0.030], np.float32)
        o = np.clip((n_big - 0.55) / 0.3, 0.0, 1.0) * (1.0 - m)
        alb = alb + (olive[None, None, :] - alb) * np.clip(o * 0.6, 0, 1)[..., None]
        alb *= (0.72 + 0.28 * np.clip(n_mid * 1.5, 0, 1))[..., None]
        hgt = 0.55 * blotch + 0.45 * detail
        rough = 0.30 + 0.16 * n_mid
        return alb, hgt, np.clip(rough, 0.18, 0.62)

    if role == "membrane":
        t = 0.6 * n_mid + 0.4 * n_fine
        alb = MEMB[None, None, :] * (0.55 + 0.75 * t)[..., None]
        # soft wrinkle creases
        wr = 0.5 + 0.5 * np.sin((u * 7.0 + n_mid * 3.0) * math.pi)
        hgt = 0.5 * wr * (0.4 + 0.6 * n_mid) + 0.5 * t
        rough = 0.62 + 0.18 * n_mid
        return alb, hgt, np.clip(rough, 0.45, 0.88)

    if role == "egg":
        # Pale cream silk with faint darker banding and speckle.
        t = 0.5 * n_big + 0.5 * n_mid
        alb = CREAM[None, None, :] * (0.80 + 0.24 * t)[..., None]
        spec = np.clip((n_fine - 0.80) / 0.20, 0.0, 1.0)
        alb = alb * (1.0 - 0.22 * spec)[..., None]
        band = 0.5 + 0.5 * np.cos(2.0 * math.pi * (u * 6.0 + n_big))
        alb *= (0.90 + 0.10 * band)[..., None]
        hgt = 0.6 * n_big + 0.4 * n_mid
        rough = np.full((h, w), 0.50, np.float32) + 0.06 * (n_mid - 0.5)
        return alb, hgt, np.clip(rough, 0.40, 0.60)

    if role == "fang":
        # Base -> tip along u: near-black root, deep red bleeding up the shaft.
        g = np.broadcast_to(np.clip((u - 0.30) / 0.55, 0.0, 1.0) ** 1.4, (h, w))
        alb = (CHITIN_DARK * 0.55)[None, None, :] + (FANGRED - CHITIN_DARK * 0.55)[None, None, :] * g[..., None]
        alb *= (0.82 + 0.36 * detail)[..., None]
        hgt = 0.5 + 0.5 * n_mid
        rough = 0.20 + 0.08 * n_mid
        return alb, hgt, np.clip(rough, 0.12, 0.36)

    if role == "eye":
        alb = np.broadcast_to(np.array([0.45, 0.02, 0.02], np.float32), (h, w, 3)).copy()
        return alb, np.full((h, w), 0.5, np.float32), np.full((h, w), 0.22, np.float32)

    raise SystemExit("[matriarch] unknown texture role %r" % role)


class Packer:
    """Deterministic first-fit block allocator over a region of the atlas."""

    def __init__(self, name, rect):
        u0, v0, u1, v1, cols, rows = rect
        self.name = name
        self.u0, self.v0, self.u1, self.v1 = u0, v0, u1, v1
        self.cols, self.rows = cols, rows
        self.used = np.zeros((rows, cols), bool)
        self.count = 0

    def alloc(self, wcells, hcells, label=""):
        wcells = max(1, min(wcells, self.cols))
        hcells = max(1, min(hcells, self.rows))
        for r in range(self.rows - hcells + 1):
            for c in range(self.cols - wcells + 1):
                if not self.used[r:r + hcells, c:c + wcells].any():
                    self.used[r:r + hcells, c:c + wcells] = True
                    self.count += 1
                    cw = (self.u1 - self.u0) / self.cols
                    ch = (self.v1 - self.v0) / self.rows
                    gx, gy = cw * 0.18, ch * 0.18        # gutter inside the block
                    return (self.u0 + c * cw + gx, self.v0 + r * ch + gy,
                            self.u0 + (c + wcells) * cw - gx, self.v0 + (r + hcells) * ch - gy)
        raise SystemExit("[matriarch] uv packer overflow: region %s, %s needs %dx%d cells"
                         % (self.name, label, wcells, hcells))

    def fill(self):
        return float(self.used.mean())


PACKERS = {name: Packer(name, rect) for name, rect in REGIONS.items()}
ISLANDS = []          # (region, role, seed, opts, rect, label)


def island(region, wcells, hcells, role=None, seed=None, label="", **opts):
    """Allocate a UV island and remember how to paint it."""
    packer = PACKERS[region]
    rect = packer.alloc(wcells, hcells, label)
    rec = dict(region=region, role=role or REGION_ROLE[region], seed=SEED + len(ISLANDS) * 131,
               opts=opts, rect=rect, label=label)
    if seed is not None:
        rec["seed"] = seed
    ISLANDS.append(rec)
    return rect


def paint_maps(size, want_rough=False):
    """Rasterise the atlas: base fill, then every island's pattern."""
    scale = size / float(S)
    alb = np.zeros((size, size, 3), np.float32)
    hgt = np.zeros((size, size), np.float32)
    rough = np.zeros((size, size), np.float32)
    mask = np.zeros((size, size), bool)

    # Base fill: plausible chitin everywhere, so gutters and mip bleed sample
    # something the creature could actually be made of.
    g = size // 8
    base = fbm(size, size, g, 4, SEED + 999)
    fine = fbm(size, size, g * 6, 3, SEED + 1234)
    t = np.clip(0.6 * base + 0.4 * fine, 0, 1)
    alb[:] = (CHITIN_DARK[None, None, :] + (CHITIN_MID - CHITIN_DARK)[None, None, :] * t[..., None])
    hgt[:] = t
    rough[:] = 0.30 + 0.12 * base

    for rec in ISLANDS:
        u0, v0, u1, v1 = rec["rect"]
        x0, x1 = int(round(u0 * size)), int(round(u1 * size))
        y0, y1 = int(round(v0 * size)), int(round(v1 * size))
        w, h = x1 - x0, y1 - y0
        if w < 2 or h < 2:
            continue
        a, hh, r = pattern(rec["role"], h, w, rec["seed"], rec["opts"])
        alb[y0:y1, x0:x1] = a
        hgt[y0:y1, x0:x1] = hh
        rough[y0:y1, x0:x1] = r
        mask[y0:y1, x0:x1] = True

    # Dilate island content into the gutters (6 px) so bilinear/mip filtering
    # at island borders never picks up the base fill.
    stack = np.concatenate([alb, hgt[..., None], rough[..., None]], axis=-1)
    solid = mask.copy()
    for _ in range(max(1, int(round(6 * scale)))):
        grown = solid.copy()
        acc = np.zeros_like(stack)
        cnt = np.zeros(mask.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = np.roll(solid, (dy, dx), axis=(0, 1))
            acc += np.roll(stack, (dy, dx), axis=(0, 1)) * nb[..., None]
            cnt += nb
        hole = (~solid) & (cnt > 0)
        stack[hole] = (acc[hole] / cnt[hole][..., None])
        grown |= hole
        solid = grown
    alb = stack[..., :3]
    hgt = stack[..., 3]
    rough = stack[..., 4]
    if want_rough:
        # 2x2 box downsample to the shipped roughness resolution.
        k = size // 2
        rough = rough.reshape(k, 2, k, 2).mean(axis=(1, 3))
        return alb, hgt, rough
    return alb, hgt, rough


def image_from(name, arr, colorspace, size=None):
    """Create a packed Blender image from a float array (RGBA written raw)."""
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=-1)
    h, w = arr.shape[0], arr.shape[1]
    img = bpy.data.images.new(name, w, h, alpha=False)
    # Colours first: assigning colorspace_settings reallocates the image buffer
    # and would wipe pixels written before it (verified on 5.2).
    img.colorspace_settings.name = colorspace
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = arr
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def build_textures():
    """Rasterise the atlas once every island has been allocated by the mesh
    build (island content is painted into its own rect, not sampled by luck)."""
    print("[matriarch] generating textures %dpx (albedo/normal) + %dpx (rough), %d islands"
          % (S, S // 2, len(ISLANDS)))
    albedo, height, rough = paint_maps(S, want_rough=True)
    normal = normal_from_height(smooth(height, 2), 30.0)
    imgs = {"matriarch_albedo": image_from("matriarch_albedo", srgb(albedo), "sRGB"),
            "matriarch_normal": image_from("matriarch_normal", normal, "Non-Color"),
            "matriarch_rough": image_from("matriarch_rough", rough, "Non-Color")}
    print("[matriarch] textures: albedo %s normal %s rough %s"
          % (imgs["matriarch_albedo"].size[:], imgs["matriarch_normal"].size[:],
             imgs["matriarch_rough"].size[:]))
    return [
        make_material("Matriarch_Chitin", imgs["matriarch_albedo"], imgs["matriarch_normal"],
                      imgs["matriarch_rough"], 1.0),
        make_material("Matriarch_Membrane", imgs["matriarch_albedo"], imgs["matriarch_normal"],
                      imgs["matriarch_rough"], 0.35),
        make_material("Matriarch_Eyes", imgs["matriarch_albedo"], None, None,
                      emissive=(0.90, 0.035, 0.02, 3.0)),
        make_material("Matriarch_FangSac", imgs["matriarch_albedo"], imgs["matriarch_normal"],
                      imgs["matriarch_rough"], 0.6),
    ]


def make_material(name, albedo, normal, rough, normal_strength=1.0, emissive=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Metallic"].default_value = 0.0
    ta = nt.nodes.new("ShaderNodeTexImage")
    ta.image = albedo
    ta.location = (-620, 300)
    nt.links.new(ta.outputs["Color"], bsdf.inputs["Base Color"])
    if normal is not None:
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = normal
        tn.image.colorspace_settings.name = "Non-Color"
        tn.location = (-620, 0)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = normal_strength
        nm.location = (-320, 0)
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if rough is not None:
        tr = nt.nodes.new("ShaderNodeTexImage")
        tr.image = rough
        tr.image.colorspace_settings.name = "Non-Color"
        tr.location = (-620, -300)
        nt.links.new(tr.outputs["Color"], bsdf.inputs["Roughness"])
    if emissive:
        bsdf.inputs["Emission Color"].default_value = (emissive[0], emissive[1], emissive[2], 1.0)
        bsdf.inputs["Emission Strength"].default_value = emissive[3]
    mat.diffuse_color = (0.16, 0.05, 0.07, 1.0)
    return mat


# Materials are created in the mesh section, once every UV island exists.

# ----------------------------------------------------------------- armature

Z = Vector((0.0, 0.0, 1.0))


def plane_dir(ang, out):
    """Unit vector in the leg's vertical plane, 'ang' above the outward axis."""
    return out * math.cos(ang) + Z * math.sin(ang)


R_TIP = 1.38          # horizontal hip -> foot-tip distance (sets the leg span)


def leg_chain(side, i):
    """All leg joints in armature space. Planar by construction: the whole
    chain lives in the vertical plane through the hip at its azimuth."""
    az = AZIMUTH[i]
    out = Vector((side * math.cos(az), math.sin(az), 0.0))
    hip = Vector((side * HIP_X, HIP_Y[i], HIP_Z))
    shoulder = hip + out * COXA_OUT + Z * COXA_UP
    patella = shoulder + plane_dir(FEMUR_ANG, out) * FEMUR_LEN
    tibia = patella + plane_dir(PATELLA_ANG, out) * PATELLA_LEN
    ankle = tibia + plane_dir(TIBIA_ANG, out) * TIBIA_LEN
    d = Vector((out.x, out.y, 0.0)) * (R_TIP - (ankle - hip).dot(out)) - Z * ankle.z
    return dict(az=az, out=out, hip=hip, shoulder=shoulder, patella=patella,
                tibia=tibia, ankle=ankle, tip=ankle + d,
                tarsus_len=d.length, tarsus_ang=math.atan2(d.z, math.hypot(d.x, d.y)))


def leg_points(side, i, seg):
    ch = LEG_CHAIN[(side, i)]
    return dict(Coxa=(ch["hip"], ch["shoulder"]),
                Femur=(ch["shoulder"], ch["patella"]),
                Patella=(ch["patella"], ch["tibia"]),
                Tibia=(ch["tibia"], ch["ankle"]),
                Tarsus=(ch["ankle"], ch["tip"]))[seg]


LEG_CHAIN = {(s, i): leg_chain(s, i) for s in (1, -1) for i in range(4)}
LEG_BONES = ["Coxa", "Femur", "Patella", "Tibia", "Tarsus"]


def build_armature():
    ad = bpy.data.armatures.new("MatriarchRig")
    arm = bpy.data.objects.new("MatriarchRig", ad)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = ad.edit_bones

    root = eb.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, -0.30, 0.0)

    body = eb.new("Body")
    body.head = (0.0, 0.02, 0.54)
    body.tail = (0.0, -0.30, 0.60)
    body.parent = root

    abdo = eb.new("Abdomen")
    abdo.head = (0.0, 0.06, 0.60)
    abdo.tail = (0.0, 0.60, 0.66)
    abdo.parent = body

    egg = eb.new("EggSac")
    egg.head = (0.0, 0.42, 0.52)
    egg.tail = (0.0, 0.72, 0.38)
    egg.parent = abdo

    head = eb.new("Head")
    head.head = (0.0, -0.40, 0.66)
    head.tail = (0.0, HEAD_Y, 0.62)
    head.parent = body

    for side, sfx in ((1, "_L"), (-1, "_R")):
        che = eb.new("Chelicera" + sfx)
        che.head = (side * 0.135, -0.60, 0.56)
        che.tail = (side * 0.150, -0.71, 0.30)
        che.parent = head
        palp = eb.new("Pedipalp" + sfx)
        palp.head = (side * 0.235, -0.50, 0.53)
        palp.tail = (side * 0.60, -1.00, 0.12)
        palp.parent = head

    for (side, i), ch in LEG_CHAIN.items():
        sfx = ("L" if side > 0 else "R") + str(i + 1)     # LegL1_Coxa, LegR4_Tarsus
        parent = body
        for seg in LEG_BONES:
            a, b = leg_points(side, i, seg)
            bone = eb.new("Leg" + sfx + "_" + seg)
            bone.head = a
            bone.tail = b
            bone.parent = parent
            bone.use_connect = seg != "Coxa"
            parent = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    print("[matriarch] armature: %d bones" % len(ad.bones))
    return arm


ARM = build_armature()

# --------------------------------------------------------------- mesh build


class Mesh:
    def __init__(self):
        self.co = []
        self.part = []
        self.faces = []
        self.uv = []
        self.mat = []
        self.smooth = []

    def v(self, co, part):
        self.co.append(Vector(co))
        self.part.append(part)
        return len(self.co) - 1

    def face(self, idx, uvs, mat, smooth=True):
        self.faces.append(tuple(idx))
        self.uv.extend(uvs)
        self.mat.append(mat)
        self.smooth.append(smooth)

    def tris(self):
        return sum(len(f) - 2 for f in self.faces)


M = Mesh()


def uv_at(rect, u, v):
    return (rect[0] + (rect[2] - rect[0]) * u, rect[1] + (rect[3] - rect[1]) * v)


def island_grid(rect, cols, rows):
    """Split one island into sub-rects: every tiny element still owns pixels."""
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append((rect[0] + (rect[2] - rect[0]) * c / cols,
                        rect[1] + (rect[3] - rect[1]) * r / rows,
                        rect[0] + (rect[2] - rect[0]) * (c + 1) / cols,
                        rect[1] + (rect[3] - rect[1]) * (r + 1) / rows))
    return out


def frame_chain(pts):
    """Parallel-transport frames along a polyline (deterministic)."""
    n = len(pts)
    tans = []
    for i in range(n):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == n - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        tans.append(t.normalized())
    ref = Vector((0.0, 0.0, 1.0))
    if abs(tans[0].dot(ref)) > 0.9:
        ref = Vector((0.0, 1.0, 0.0))
    e1 = (ref - tans[0] * ref.dot(tans[0])).normalized()
    frames = [(e1, tans[0].cross(e1).normalized())]
    for i in range(1, n):
        q = tans[i - 1].rotation_difference(tans[i])
        e1 = (q @ frames[-1][0])
        e1 = (e1 - tans[i] * e1.dot(tans[i])).normalized()
        frames.append((e1, tans[i].cross(e1).normalized()))
    return frames


def tube(pts, radii, sides, part, mat, rect, cap0=True, cap1=True, squash=1.0,
         smooth=True):
    """Tapered tube through a polyline. u runs along the length, v around."""
    pts = [Vector(p) for p in pts]
    frames = frame_chain(pts)
    rings = []
    for i, p in enumerate(pts):
        e1, e2 = frames[i]
        r = radii[i]
        ring = []
        for s in range(sides):
            a = 2.0 * math.pi * s / sides
            co = p + e1 * (math.cos(a) * r) + e2 * (math.sin(a) * r * squash)
            ring.append(M.v(co, part))
        rings.append(ring)
    npts = len(pts)
    for i in range(npts - 1):
        for s in range(sides):
            s2 = (s + 1) % sides
            u0, u1 = i / (npts - 1), (i + 1) / (npts - 1)
            v0, v1 = s / sides, (s + 1) / sides
            M.face((rings[i][s], rings[i][s2], rings[i + 1][s2], rings[i + 1][s]),
                   [uv_at(rect, u0, v0), uv_at(rect, u1, v0), uv_at(rect, u1, v1), uv_at(rect, u0, v1)],
                   mat, smooth)
    if cap0:
        c = M.v(pts[0], part)
        for s in range(sides):
            s2 = (s + 1) % sides
            M.face((c, rings[0][s2], rings[0][s]),
                   [uv_at(rect, 0.02, 0.5), uv_at(rect, 0.02, s2 / sides), uv_at(rect, 0.02, s / sides)],
                   mat, False)
    if cap1:
        c = M.v(pts[-1], part)
        for s in range(sides):
            s2 = (s + 1) % sides
            M.face((c, rings[-1][s], rings[-1][s2]),
                   [uv_at(rect, 0.98, 0.5), uv_at(rect, 0.98, s / sides), uv_at(rect, 0.98, s2 / sides)],
                   mat, False)
    return rings


def ellipsoid(centre, radii, seg, rings, part, band_fn, deform=None):
    """UV-sphere shell. band_fn(row_index) -> (material, uv island); each band
    of latitude rows owns its own island so the island's v maps 0-1 inside the
    band instead of across the whole sphere (keeps texel density even)."""
    centre = Vector(centre)
    radii = Vector(radii)

    def surf(lat, lon):
        d = Vector((math.sin(lat) * math.cos(lon), math.sin(lat) * math.sin(lon), math.cos(lat)))
        p = centre + Vector((d.x * radii.x, d.y * radii.y, d.z * radii.z))
        return p + deform(p, d) if deform else p

    rows = [[M.v(surf(0.0, 0.0), part)]]
    for j in range(1, rings):
        lat = math.pi * j / rings
        rows.append([M.v(surf(lat, 2.0 * math.pi * i / seg), part) for i in range(seg)])
    rows.append([M.v(surf(math.pi, 0.0), part)])

    for j in range(rings):
        mat, rect, v0, v1 = band_fn(j)
        for i in range(seg):
            i2 = (i + 1) % seg
            u0, u1 = i / seg, (i + 1) / seg
            if j == 0:
                M.face((rows[0][0], rows[1][i], rows[1][i2]),
                       [uv_at(rect, 0.5, v0), uv_at(rect, u0, v1), uv_at(rect, u1, v1)], mat)
            elif j == rings - 1:
                M.face((rows[rings][0], rows[rings - 1][i2], rows[rings - 1][i]),
                       [uv_at(rect, 0.5, v1), uv_at(rect, u1, v0), uv_at(rect, u0, v0)], mat)
            else:
                M.face((rows[j][i], rows[j][i2], rows[j + 1][i2], rows[j + 1][i]),
                       [uv_at(rect, u0, v0), uv_at(rect, u1, v0), uv_at(rect, u1, v1), uv_at(rect, u0, v1)], mat)


def spike(base, direction, length, radius, sides, part, mat, rect, curve=0.30, stations=None):
    """Tapered swept cone (crown spike / spur). u runs base -> tip."""
    d = Vector(direction).normalized()
    up = Vector((0, 0, 1))
    perp = up - d * d.dot(up)                      # vertical-plane normal: bend sweeps back
    if perp.length < 1e-5:
        perp = d.cross(up)
    perp = perp.normalized()
    pts, radii = [], []
    stations = stations or DENSITY["spike_station"]
    for k in range(stations + 1):
        t = k / stations
        p = Vector(base) + d * (length * t) + perp * (curve * length * t * t)
        pts.append(p)
        radii.append(max(0.0035, radius * (1.0 - t) ** 0.85))
    tube(pts, radii, sides, part, mat, rect, cap0=True, cap1=False, smooth=False)


def hair(base, direction, length, width, part, mat, rect):
    """Single opaque blade - the bristly fringe that sells 'spikier' at range."""
    d = Vector(direction).normalized()
    up = Vector((0, 0, 1))
    side = d.cross(up)
    side = side.normalized() * width if side.length > 1e-6 else Vector((width, 0, 0))
    a = M.v(Vector(base) - side, part)
    b = M.v(Vector(base) + side, part)
    c = M.v(Vector(base) + d * length, part)
    M.face((a, b, c), [uv_at(rect, 0.05, 0.05), uv_at(rect, 0.05, 0.95), uv_at(rect, 0.95, 0.5)],
           mat, False)


def ellipsoid_point(centre, radii, d):
    d = Vector(d).normalized()
    return Vector(centre) + Vector((d.x * radii.x, d.y * radii.y, d.z * radii.z))


# ------------------------------------------------------------- creature mesh

print("[matriarch] building mesh")
ISL = dict(
    ceph_top=island("chitin", 12, 8, label="ceph-top"),
    ceph_bot=island("membrane", 8, 5, label="ceph-under"),
    abdo_top=island("abdomen", 10, 8, label="abdomen"),
    abdo_bot=island("membrane", 8, 4, label="abdomen-under"),
    egg=island("egg", 7, 7, label="eggsac"),
    fang=[island("fang", 3, 1, label="fang"),
          island("fang", 3, 1, label="fang")],
    eye=[island("fang", 1, 1, label="eye") for _ in range(8)],
    palp=[island("chitin", 2, 2, label="pedipalp") for _ in range(2)],
    cheli=[island("chitin", 3, 1, label="chelicera") for _ in range(2)],
    crown=island("chitin", 8, 4, label="crown-spikes"),
    bristle=island("abdomen", 3, 3, label="body-bristles"),
)
CROWN_SUB = island_grid(ISL["crown"], 4, 3)
BRISTLE_SUB = island_grid(ISL["bristle"], 14, 14)
LEG_ISL = {}
for _side in (1, -1):
    for _i in range(4):
        key = (_side, _i)
        segs = [island("chitin", 3, 2, label="leg-seg") for _ in LEG_BONES]
        joint = island("membrane", 2, 2, label="leg-joint")
        detail = island("chitin", 4, 3, label="leg-spurs")
        LEG_ISL[key] = dict(
            segs=segs,
            joints=island_grid(joint, 2, 2),
            detail=island_grid(detail, 6, 7),
        )

ROWS_CEPH = DENSITY["ceph_ring"]
ROWS_ABDO = DENSITY["abdo_ring"]


def ceph_band(j):
    mid = ROWS_CEPH // 2
    if j < mid:
        return MAT_MEMBRANE, ISL["ceph_bot"], j / mid, (j + 1) / mid
    return MAT_CHITIN, ISL["ceph_top"], (j - mid) / (ROWS_CEPH - mid), (j + 1 - mid) / (ROWS_CEPH - mid)


def abdo_band(j):
    mid = ROWS_ABDO // 2
    if j < mid:
        return MAT_MEMBRANE, ISL["abdo_bot"], j / mid, (j + 1) / mid
    return MAT_CHITIN, ISL["abdo_top"], (j - mid) / (ROWS_ABDO - mid), (j + 1 - mid) / (ROWS_ABDO - mid)


def ceph_deform(p, d):
    """Raised, spiked carapace: centre ridge, brow over the eyes, flat belly."""
    x, y, z = p.x, p.y, p.z
    top = max(0.0, d.z) ** 1.3
    ridge = 0.075 * math.exp(-(x / 0.105) ** 2) * max(0.0, 1.0 - ((y + 0.24) / 0.34) ** 2)
    brow = 0.030 * math.exp(-((y + 0.50) / 0.14) ** 2) * max(0.0, 1.0 - (abs(x) / 0.30) ** 2)
    shoulder = 0.045 * math.exp(-((y + 0.02) / 0.16) ** 2) * max(0.0, 1.0 - (abs(x) / 0.34) ** 2)
    belly = -0.030 * max(0.0, -d.z) ** 2
    return Vector((0.0, 0.0, (ridge + brow + shoulder) * top + belly))


def abdo_deform(p, d):
    """Heavy abdomen: lumpy rear dome, slight downward taper, silk dimple."""
    x, y, z = p.x, p.y, p.z
    top = max(0.0, d.z)
    lumps = (0.024 * math.sin(5.1 * x + 0.9) * math.cos(4.3 * y + 1.7)
             + 0.016 * math.sin(9.3 * y + 2.1) * math.cos(7.7 * x - 0.4))
    rear = 0.040 * math.exp(-((y - 0.62) / 0.26) ** 2) * max(0.0, 1.0 - (abs(x) / 0.30) ** 2) * top
    dimple = -0.05 * math.exp(-((y - 0.70) / 0.20) ** 2) * max(0.0, -d.z)
    return Vector((0.0, 0.0, lumps * (0.35 + 0.65 * top) + rear + dimple))


ellipsoid(CEPH_C, CEPH_R, DENSITY["ceph_seg"], ROWS_CEPH, "body", ceph_band, ceph_deform)
ellipsoid(ABDO_C, ABDO_R, DENSITY["abdo_seg"], ROWS_ABDO, "abdomen", abdo_band, abdo_deform)


def egg_deform(p, d):
    lumps = 0.018 * math.sin(7.0 * p.x + 0.3) * math.cos(6.0 * p.z + 1.1)
    return Vector((0.0, 0.0, lumps + 0.02 * max(0.0, d.z) ** 2))


ellipsoid(EGG_C, EGG_R, DENSITY["egg_seg"], DENSITY["egg_ring"], "egg",
          lambda j: (MAT_FANGSAC, ISL["egg"], j / DENSITY["egg_ring"],
                     (j + 1) / DENSITY["egg_ring"]), egg_deform)
# silk collar tying the sac to the abdomen's underside
tube([Vector((0.0, 0.60, 0.44)), Vector((0.0, 0.66, 0.40)), Vector((0.0, 0.715, 0.375))],
     [0.14, 0.155, 0.16], 18, "egg", MAT_FANGSAC, ISL["egg"], cap0=False, cap1=False)

# crown of backward-swept spikes on the carapace
CROWN = [
    (0.000, -0.520, 0.250, 0.060, 0.08),
    (-0.130, -0.470, 0.290, 0.068, 0.16),
    (0.130, -0.470, 0.290, 0.068, 0.16),
    (-0.190, -0.310, 0.355, 0.082, 0.26),
    (0.190, -0.310, 0.355, 0.082, 0.26),
    (-0.150, -0.120, 0.330, 0.074, 0.32),
    (0.150, -0.120, 0.330, 0.074, 0.32),
    (0.000, -0.080, 0.300, 0.070, 0.00),
]
CROWN_TIPS = []
for k, (cx, cy, ln, rad, out_tilt) in enumerate(CROWN):
    base = Vector((cx, cy, 0.0))
    ell = math.sqrt(max(0.0, 1.0 - (cx / CEPH_R.x) ** 2 - ((cy - CEPH_C.y) / CEPH_R.y) ** 2))
    base.z = CEPH_C.z + CEPH_R.z * ell - 0.010
    dirv = Vector((math.copysign(out_tilt * 0.55, cx) if cx else 0.0, 0.86, 0.50))
    spike(base, dirv, ln, rad, DENSITY["spike_sides"], "body", MAT_CHITIN,
          CROWN_SUB[k % len(CROWN_SUB)], curve=-0.24)
    CROWN_TIPS.append(base + Vector(dirv).normalized() * ln)

# eight eyes in two rows on the brow
EYES = [
    (0.062, -0.585, 0.760, 0.062, 0.55),
    (0.150, -0.545, 0.762, 0.048, 0.60),
    (0.086, -0.600, 0.690, 0.033, 0.75),
    (0.190, -0.520, 0.700, 0.029, 0.80),
]
_eye_i = 0
for side in (1, -1):
    for (ex, ey, ez, er, fwd) in EYES:
        c = Vector((side * ex, ey, ez))
        d = (c - CEPH_C)
        surf = ellipsoid_point(CEPH_C, CEPH_R, Vector((d.x, d.y, d.z)))
        n = Vector((d.x / CEPH_R.x ** 2, d.y / CEPH_R.y ** 2, d.z / CEPH_R.z ** 2)).normalized()
        centre = surf + n * (er * 0.52)
        rect = ISL["eye"][_eye_i]
        _eye_i += 1
        ellipsoid(centre, Vector((er, er * 1.15, er)), DENSITY["eye_seg"], DENSITY["eye_ring"],
                  "head", lambda j, r=rect: (MAT_EYES, r, j / DENSITY["eye_ring"],
                                             (j + 1) / DENSITY["eye_ring"]))

# chelicerae + fangs, pedipalps
for side, k in ((1, 0), (-1, 1)):
    part = "cheli_" + ("L" if side > 0 else "R")
    rect = ISL["cheli"][k]
    a = Vector((side * 0.135, -0.520, 0.585))
    b = Vector((side * 0.150, -0.640, 0.470))
    c = Vector((side * 0.152, -0.700, 0.360))
    tube([a, b, c], [0.098, 0.082, 0.066], 14, part, MAT_CHITIN, rect, cap0=False)
    # barb on the chelicera knuckle
    spike(b + Vector((side * 0.06, -0.02, 0.03)), Vector((side * 0.6, -0.4, 0.7)), 0.075, 0.022,
          6, part, MAT_CHITIN, CROWN_SUB[k], curve=0.0, stations=2)
    # fang: thick, protruding, curving down and inward
    f0 = c + Vector((0.0, 0.0, -0.02))
    f1 = c + Vector((-side * 0.012, -0.055, -0.115))
    f2 = c + Vector((-side * 0.030, -0.062, -0.205))
    f3 = c + Vector((-side * 0.052, -0.040, -0.255))
    tube([f0, f1, f2, f3], [0.056, 0.044, 0.028, 0.010], 12, part, MAT_FANGSAC,
         ISL["fang"][k], cap0=False, cap1=False)

    p0 = Vector((side * 0.240, -0.500, 0.520))
    p1 = Vector((side * 0.400, -0.700, 0.360))
    p2 = Vector((side * 0.520, -0.860, 0.190))
    p3 = Vector((side * 0.585, -0.960, 0.115))
    rect = ISL["palp"][k]
    tube([p0, p1, p2, p3], [0.085, 0.066, 0.050, 0.042], 12, "palp_" + ("L" if side > 0 else "R"),
         MAT_CHITIN, rect, cap0=False)
    ellipsoid(p3 + Vector((side * 0.03, -0.03, -0.01)), Vector((0.045, 0.055, 0.042)),
              10, 5, "palp_" + ("L" if side > 0 else "R"),
              lambda j, r=rect: (MAT_CHITIN, r, j / 5, (j + 1) / 5))
    # sensory hairs on the palpus
    for h in range(6):
        t = 0.25 + 0.13 * h
        base = p0.lerp(p3, t)
        hair(base, Vector((side * 0.5, -0.3, 0.8)), 0.075, 0.011,
             "palp_" + ("L" if side > 0 else "R"), MAT_CHITIN,
             CROWN_SUB[(k * 3 + h) % len(CROWN_SUB)])


def leg_bow(a, b, out, amount, stations):
    """Sample a slightly bowed path between two joints, inside the leg plane."""
    d = (b - a)
    dirv = d.normalized()
    perp = dirv.cross(out.cross(Z))
    if perp.length < 1e-6:
        perp = dirv.cross(Z)
    perp = perp.normalized()
    if perp.dot(Z) < 0:
        perp = -perp
    pts = []
    for k in range(stations):
        t = k / (stations - 1)
        pts.append(a + d * t + perp * (amount * math.sin(math.pi * t)))
    return pts


for (side, i), ch in LEG_CHAIN.items():
    part = "leg_" + ("L" if side > 0 else "R") + str(i + 1)
    isl = LEG_ISL[(side, i)]
    out = ch["out"]
    for si, seg in enumerate(LEG_BONES):
        a, b = leg_points(side, i, seg)
        r0, r1 = SEG_R[seg]
        stations = DENSITY["leg_station"]
        bow = {"Femur": 0.030, "Tibia": -0.030, "Patella": 0.012, "Coxa": 0.0, "Tarsus": 0.0}[seg]
        pts = leg_bow(a, b, out, bow, stations)
        radii = [r0 + (r1 - r0) * (k / (stations - 1)) for k in range(stations)]
        tube(pts, radii, DENSITY["leg_sides"], part, MAT_CHITIN, isl["segs"][si],
             cap0=(seg == "Coxa"), cap1=False)
    # joints as soft membrane sleeves over the chitin hinges
    for ji, jp in enumerate((ch["shoulder"], ch["patella"], ch["tibia"], ch["ankle"])):
        rr = {"Coxa": 0.092, "Femur": 0.075, "Patella": 0.062, "Tibia": 0.045}[LEG_BONES[ji]]
        ellipsoid(jp, Vector((rr * 1.05, rr * 1.05, rr * 0.92)), DENSITY["joint_sides"],
                  DENSITY["joint_ring"], part,
                  lambda j, r=isl["joints"][ji]: (MAT_MEMBRANE, r, j / DENSITY["joint_ring"],
                                                  (j + 1) / DENSITY["joint_ring"]))
    # spur comb on femur + tibia, and the bristle fringe
    sub = isl["detail"]
    n_barb = DENSITY["barb_count"]
    for b in range(n_barb):
        seg = "Femur" if b % 2 == 0 else "Tibia"
        a, bb = leg_points(side, i, seg)
        t = 0.16 + 0.68 * ((b // 2) / max(1, (n_barb // 2 - 1)))
        base = a.lerp(bb, t)
        sgn = 1.0 if b % 4 < 2 else -1.0
        dirv = (out * 0.45 + Z * 0.55 + Vector((0.0, sgn * 0.75, 0.0))).normalized()
        if seg == "Tibia":
            dirv = (out * 0.5 - Z * 0.5 + Vector((0.0, sgn * 0.6, 0.0))).normalized()
        spike(base, dirv, 0.140 + 0.045 * ((b % 3) / 2.0), 0.032, DENSITY["barb_sides"],
              part, MAT_CHITIN, sub[b], curve=0.0, stations=2)
    for h in range(DENSITY["hair_count"]):
        seg = "Femur" if h % 2 == 0 else "Tibia"
        a, bb = leg_points(side, i, seg)
        t = 0.10 + 0.80 * ((h % 13) / 12.0)
        base = a.lerp(bb, t)
        sgn = 1.0 if (h // 2) % 2 == 0 else -1.0
        dirv = (out * 0.3 + Z * (0.7 if seg == "Femur" else -0.6) + Vector((0.0, sgn * 0.8, 0.0))).normalized()
        hair(base, dirv, 0.13 + 0.06 * ((h % 5) / 4.0), 0.018, part, MAT_CHITIN,
             sub[(n_barb + h) % len(sub)])

# abdomen / carapace fringe: the bristly silhouette from 20 m
for h in range(DENSITY["body_hair"]):
    a = 2.0 * math.pi * h * 0.618034
    t = 0.72 + 0.28 * ((h % 7) / 6.0)
    lon = a
    lat = math.pi * t
    d = Vector((math.sin(lat) * math.cos(lon), math.sin(lat) * math.sin(lon), math.cos(lat)))
    p = ellipsoid_point(ABDO_C, ABDO_R, d)
    p += Vector((0.0, 0.0, abdo_deform(p, d).z))
    dirv = Vector((d.x, d.y, d.z * 0.4 + 0.75)).normalized()
    hair(p, dirv, 0.13 + 0.07 * ((h % 5) / 4.0), 0.018, "abdomen", MAT_CHITIN,
         BRISTLE_SUB[h % len(BRISTLE_SUB)])
for h in range(48):
    t = h / 47.0
    ang = -0.55 + 1.10 * t
    d = Vector((math.sin(ang) * 0.9, -0.55, 0.55 + 0.35 * math.cos(ang)))
    p = ellipsoid_point(CEPH_C, CEPH_R, d)
    p += Vector((0.0, 0.0, ceph_deform(p, d).z))
    hair(p, Vector((d.x, -0.55, 0.78)).normalized(), 0.145, 0.017, "body", MAT_CHITIN,
         BRISTLE_SUB[(h * 3) % len(BRISTLE_SUB)])

print("[matriarch] mesh: %d verts, %d faces, %d tris" % (len(M.co), len(M.faces), M.tris()))
print("[matriarch] uv islands: %d (%s)" % (
    len(ISLANDS), ", ".join("%s %d/%d cells" % (p.name, int(p.used.sum()), p.used.size)
                            for p in PACKERS.values())))
MATS = build_textures()
print("[matriarch] materials: %s" % [m.name for m in MATS])

# ------------------------------------------------------------ mesh object


def to_object(name):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in M.co], [], M.faces)
    me.validate(verbose=False)
    assert len(me.polygons) == len(M.faces), "validate() dropped faces"
    assert len(me.loops) == len(M.uv), "loop/uv mismatch"
    uvl = me.uv_layers.new(name="UVMap")
    uvl.data.foreach_set("uv", [c for uv in M.uv for c in uv])
    for m in MATS:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", M.mat)
    me.polygons.foreach_set("use_smooth", [int(s) for s in M.smooth])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


BODY = to_object("Matriarch")

# Ground snap: put the lowest vertex exactly on z=0, then move the skeleton
# with it so the bind pose still matches the geometry 1:1.
_minz = min(v.z for v in M.co)
print("[matriarch] raw min z %.4f -> snapping" % _minz)
for v in BODY.data.vertices:
    v.co.z -= _minz
bpy.context.view_layer.objects.active = ARM
bpy.ops.object.mode_set(mode="EDIT")
for bone in ARM.data.edit_bones:
    if bone.name == "Root":
        continue            # root stays on the ground plane
    bone.tail.z -= _minz
    if bone.parent is None or not bone.use_connect:
        bone.head.z -= _minz    # connected heads follow their parent's tail

bpy.ops.object.mode_set(mode="OBJECT")
for _ch in LEG_CHAIN.values():
    for _k in ("hip", "shoulder", "patella", "tibia", "ankle", "tip"):
        _ch[_k] = _ch[_k] - Vector((0.0, 0.0, _minz))
# The IK solver models the leg from LEG_CHAIN; make sure the bones it drives
# really sit exactly there (this is what keeps planted feet planted).
_bone_dev = 0.0
_bone_dev_at = ""
for (side, i), _ch in LEG_CHAIN.items():
    _sfx = ("L" if side > 0 else "R") + str(i + 1)
    for _seg, _a, _b in (("Coxa", _ch["hip"], _ch["shoulder"]), ("Femur", _ch["shoulder"], _ch["patella"]),
                         ("Patella", _ch["patella"], _ch["tibia"]), ("Tibia", _ch["tibia"], _ch["ankle"]),
                         ("Tarsus", _ch["ankle"], _ch["tip"])):
        _bo = ARM.data.bones["Leg" + _sfx + "_" + _seg]
        _bd = max((Vector(_bo.head_local) - _a).length, (Vector(_bo.tail_local) - _b).length)
        if _bd > _bone_dev:
            _bone_dev = _bd
            _bone_dev_at = "%s head=%s want=%s" % (_bo.name, tuple(round(c, 4) for c in _bo.head_local),
                                                   tuple(round(c, 4) for c in _a))
print("[matriarch] bone/geometry deviation: %.6f m %s" % (_bone_dev, _bone_dev_at))

# --------------------------------------------------------------- skin weights

PART_BONES = {"body": ["Body", "Head", "Abdomen"],
              "head": ["Head", "Body"],
              "abdomen": ["Abdomen", "Body"],
              "egg": ["EggSac", "Abdomen"]}
PART_SIGMA = {"body": 0.24, "head": 0.16, "abdomen": 0.32, "egg": 0.28}
for side, sfx in ((1, "L"), (-1, "R")):
    PART_BONES["cheli_" + sfx] = ["Chelicera_" + sfx, "Head"]
    PART_BONES["palp_" + sfx] = ["Pedipalp_" + sfx, "Head"]
    PART_SIGMA["cheli_" + sfx] = 0.12
    PART_SIGMA["palp_" + sfx] = 0.16
    for i in range(4):
        key = "leg_" + sfx + str(i + 1)
        PART_BONES[key] = ["Leg" + sfx + str(i + 1) + "_" + s for s in LEG_BONES] + ["Body"]
        PART_SIGMA[key] = 0.085

MAX_INFLUENCES = 4
print("[matriarch] skinning %d verts" % len(BODY.data.vertices))
bones = ARM.data.bones
bone_names = [b.name for b in bones]
seg = {b.name: (np.array(b.head_local, np.float32), np.array(b.tail_local, np.float32))
       for b in bones}
for name in bone_names:
    BODY.vertex_groups.new(name=name)
groups = {g.name: g for g in BODY.vertex_groups}

co = np.array([tuple(v.co) for v in BODY.data.vertices], np.float32)
nverts = len(co)
weight_rows = [None] * nverts
for part in sorted(PART_BONES.keys()):
    idx = np.array([i for i, p in enumerate(M.part) if p == part], np.int64)
    if not len(idx):
        continue
    allowed = PART_BONES[part]
    a = np.stack([seg[n][0] for n in allowed])
    b = np.stack([seg[n][1] for n in allowed])
    p = co[idx]
    ab = b - a
    denom = np.maximum((ab * ab).sum(-1), 1e-9)
    t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(-1) / denom[None], 0.0, 1.0)
    closest = a[None] + ab[None] * t[..., None]
    dist = np.linalg.norm(p[:, None, :] - closest, axis=-1)
    sigma = PART_SIGMA[part]
    w = np.exp(-(dist / sigma) ** 2)
    # keep at most MAX_INFLUENCES bones, normalised
    order = np.argsort(-w, axis=1)[:, :MAX_INFLUENCES]
    for r, vi in enumerate(idx):
        picked = [(allowed[c], float(w[r, c])) for c in order[r] if w[r, c] > 1e-5]
        s = sum(x[1] for x in picked) or 1.0
        picked = [(n, x / s) for n, x in picked if x / s > 0.008]
        s = sum(x[1] for x in picked) or 1.0
        weight_rows[vi] = [(n, x / s) for n, x in picked]
missing = [i for i, r in enumerate(weight_rows) if not r]
assert not missing, "verts without weights: %d" % len(missing)
for vi, row in enumerate(weight_rows):
    for name, wv in row:
        groups[name].add([vi], wv, "REPLACE")
used_groups = sorted({n for row in weight_rows for n, _ in row})
print("[matriarch] weights: %d groups used of %d, max influences %d"
      % (len(used_groups), len(bone_names), max(len(r) for r in weight_rows)))
BODY.parent = ARM
mod = BODY.modifiers.new("Armature", "ARMATURE")
mod.object = ARM

# ------------------------------------------------------------ pose engine
# Deltas are armature-space rotations applied about the bone's head:
#     q_local = B^-1 * D * B          (B = bone rest, armature space)
# so a delta is independent of the bone's own axes and composes down the
# hierarchy as total_world_delta(child) = total(parent) * own_delta.

AXES = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}
REST_Q = {b.name: b.matrix_local.to_quaternion() for b in ARM.data.bones}
REST_M = {b.name: b.matrix_local.copy() for b in ARM.data.bones}
PARENT = {b.name: (b.parent.name if b.parent else None) for b in ARM.data.bones}
WORLD = {}


def qrot(axis, deg):
    return Quaternion(AXES[axis] if isinstance(axis, str) else axis, math.radians(deg))


def clear_pose():
    WORLD.clear()
    for pb in ARM.pose.bones:
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)


def delta(name, q):
    WORLD[name] = q @ WORLD.get(name, Quaternion((1, 0, 0, 0)))
    B = REST_Q[name]
    pb = ARM.pose.bones[name]
    pb.rotation_quaternion = ((B.inverted() @ q @ B) @ pb.rotation_quaternion).normalized()


def parent_delta(name):
    q = Quaternion((1, 0, 0, 0))
    chain, p = [], PARENT[name]
    while p:
        chain.append(p)
        p = PARENT[p]
    for n in reversed(chain):
        q = q @ WORLD.get(n, Quaternion((1, 0, 0, 0)))
    return q


def world_offset(name, v):
    pb = ARM.pose.bones[name]
    B = REST_M[name].to_3x3()
    pb.location = pb.location + (B.inverted() @ (parent_delta(name).inverted() @ Vector(v)))


def update():
    bpy.context.view_layer.update()


def wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _ik_data(ch):
    out, n = ch["out"], ch["out"].cross(Z).normalized()
    hip, sh, tib, tip = ch["hip"], ch["shoulder"], ch["tibia"], ch["tip"]
    so = sh - hip
    v1, v2 = tib - sh, tip - tib
    a1r = math.atan2(v1.z, v1.dot(out))
    a2r = math.atan2(v2.z, v2.dot(out))
    base = math.atan2(tip.z - sh.z, (tip - sh).dot(out))
    return dict(n=n, out=out, hip=hip, sr=so.dot(out), sz=so.z, L1=v1.length, a1r=a1r,
                L2=v2.length, a2r=a2r, sgn=(1.0 if a1r > base else -1.0))


LEG_IK = {k: _ik_data(ch) for k, ch in LEG_CHAIN.items()}
LEG_N = {k: v["n"] for k, v in LEG_IK.items()}
LEG_SUFFIX = {k: ("L" if k[0] > 0 else "R") + str(k[1] + 1) for k in LEG_CHAIN}
IK_CLAMPS = []
IK_ERR = [0.0]


def leg_ik(key, target):
    """Analytic 2-link in-plane IK: yaw the leg plane at the hip, then solve the
    femur/tibia knee so the tarsus tip lands on the world-space target."""
    ch, ik = LEG_CHAIN[key], LEG_IK[key]
    M = ARM.pose.bones["Body"].matrix @ REST_M["Body"].inverted()
    d = (M.inverted() @ Vector(target)) - ik["hip"]
    dh = Vector((d.x, d.y, 0.0))
    if dh.length < 1e-6:
        dh = Vector((ch["out"].x, ch["out"].y, 0.0)) * 1e-6
    phi = wrap(math.atan2(dh.y, dh.x) - math.atan2(ch["out"].y, ch["out"].x))
    pr, pz = dh.length - ik["sr"], d.z - ik["sz"]
    dl = math.hypot(pr, pz)
    lo, hi = abs(ik["L1"] - ik["L2"]) + 0.02, ik["L1"] + ik["L2"] - 0.012
    if dl < lo or dl > hi:
        IK_CLAMPS.append((key, dl, lo, hi))
    dl = min(max(dl, lo), hi)
    base = math.atan2(pz, pr)
    ca = max(-1.0, min(1.0, (ik["L1"] ** 2 + dl * dl - ik["L2"] ** 2) / (2.0 * ik["L1"] * dl)))
    a1 = base + ik["sgn"] * math.acos(ca)
    a2 = math.atan2(pz - ik["L1"] * math.sin(a1), pr - ik["L1"] * math.cos(a1))
    sfx = LEG_SUFFIX[key]
    delta("Leg" + sfx + "_Coxa", Quaternion(Z, phi))  # LegL1_Coxa / LegR4_Tarsus
    delta("Leg" + sfx + "_Femur", Quaternion(ik["n"], a1 - ik["a1r"]))
    delta("Leg" + sfx + "_Tibia", Quaternion(ik["n"], (a2 - ik["a2r"]) - (a1 - ik["a1r"])))


def leg_fk(key, femur=0.0, tibia=0.0, tarsus=0.0, yaw=0.0):
    n, sfx = LEG_N[key], LEG_SUFFIX[key]
    if yaw:
        delta("Leg" + sfx + "_Coxa", Quaternion(Z, math.radians(yaw)))
    if femur:
        delta("Leg" + sfx + "_Femur", Quaternion(n, math.radians(femur)))
    if tibia:
        delta("Leg" + sfx + "_Tibia", Quaternion(n, math.radians(tibia)))
    if tarsus:
        delta("Leg" + sfx + "_Tarsus", Quaternion(n, math.radians(tarsus)))


REST_STANCE = {k: ch["tip"].copy() for k, ch in LEG_CHAIN.items()}
ALL_LEGS = sorted(LEG_CHAIN.keys(), key=lambda k: (k[0] < 0, k[1]))


def apply_frame(spec, stance):
    clear_pose()
    for bone, attr in (("Root", "root"), ("Body", "body"), ("Abdomen", "abdo"),
                       ("Head", "head"), ("EggSac", "egg"),
                       ("Chelicera_L", "cheli_L"), ("Chelicera_R", "cheli_R"),
                       ("Pedipalp_L", "palp_L"), ("Pedipalp_R", "palp_R")):
        for ax, deg in spec.get(attr, []):
            delta(bone, qrot(ax, deg))
    for attr, bone in (("root_off", "Root"), ("body_off", "Body"), ("head_off", "Head"),
                       ("abdo_off", "Abdomen")):
        v = spec.get(attr)
        if v:
            world_offset(bone, Vector(v))
    update()
    overrides = spec.get("legs", {})
    fk = spec.get("leg_fk", {})
    targets = {}
    for key in ALL_LEGS:
        tgt = overrides.get(key)
        if tgt == "fk":
            continue
        targets[key] = stance[key] if tgt is None else Vector(tgt)
        leg_ik(key, targets[key])
    for key, kw in fk.items():
        leg_fk(key, **kw)
    update()
    for key, tgt in targets.items():
        tip = ARM.pose.bones["Leg" + LEG_SUFFIX[key] + "_Tarsus"].tail
        IK_ERR[0] = max(IK_ERR[0], (Vector(tip) - Vector(tgt)).length)


def key_all(frame):
    for pb in ARM.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        pb.keyframe_insert("location", frame=frame)


def author(name, frames, loop, stance=None):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ARM.animation_data_create()
    ARM.animation_data.action = act
    stance = stance or REST_STANCE
    for f, spec in frames:
        apply_frame(spec, stance)
        key_all(f)
    act.use_frame_range = True
    act.frame_start = float(frames[0][0])
    act.frame_end = float(frames[-1][0])
    act.use_cyclic = bool(loop)
    ARM.animation_data.action = None
    clear_pose()
    print("[matriarch] clip %-18s frames %3d-%3d  %4.2fs  loop=%d  keys=%d"
          % (name, frames[0][0], frames[-1][0], (frames[-1][0] - frames[0][0]) / FPS,
             loop, len(frames)))
    return act


# ------------------------------------------------------------------- clips

print("[matriarch] authoring clips")

# --- Idle: heavier and slower than the small spider: a slow abdomen pulse, the
# body settling under its own weight, palps probing the ground ahead.
IDLE_KEYS = [
    (0, dict(body_off=(0.0, 0.0, 0.0), abdo=[("X", -1.0)], egg=[("X", 1.0)],
             palp_L=[("X", 0.0)], palp_R=[("X", 0.0)])),
    (15, dict(body_off=(0.012, 0.0, 0.024), body=[("X", -1.4), ("Y", 0.8)],
              abdo=[("X", 3.0)], egg=[("X", -2.0)], head=[("X", -1.5)],
              cheli_L=[("X", -3.0)], cheli_R=[("X", -3.0)],
              palp_L=[("X", 9.0), ("Z", -4.0)], palp_R=[("X", 5.0)])),
    (29, dict(body_off=(0.0, 0.0, -0.012), body=[("X", 0.8)], abdo=[("X", -2.6)],
              egg=[("X", 2.5)], cheli_L=[("X", 4.0)], cheli_R=[("X", 4.0)],
              palp_L=[("X", -4.0)], palp_R=[("X", 10.0), ("Z", 4.0)])),
    (44, dict(body_off=(-0.012, 0.0, 0.016), body=[("X", -1.0), ("Y", -0.8)],
              abdo=[("X", 2.0)], egg=[("X", -1.5)], head=[("X", -1.0)],
              palp_L=[("X", 6.0), ("Z", 3.0)], palp_R=[("X", -3.0)])),
]
IDLE_KEYS.append((58, IDLE_KEYS[0][1]))

# --- Walk: alternating tetrapod, matched-velocity swing so the stance feet
# track a dead-straight constant-speed path (no skating).
WALK_N = 34
WALK_DUTY = 0.62
WALK_SWEEP = 0.72
FWD = Vector((0.0, -1.0, 0.0))
WALK_GROUP = {(1, 0): 0.0, (-1, 1): 0.0, (1, 2): 0.0, (-1, 3): 0.0,
              (-1, 0): 0.5, (1, 1): 0.5, (-1, 2): 0.5, (1, 3): 0.5}


def walk_target(key, t):
    base = LEG_CHAIN[key]["tip"]
    half = WALK_SWEEP * 0.5
    if t < WALK_DUTY:
        s = t / WALK_DUTY
        return base + FWD * (half - WALK_SWEEP * s)
    u = (t - WALK_DUTY) / (1.0 - WALK_DUTY)
    m = -WALK_SWEEP * (1.0 - WALK_DUTY) / WALK_DUTY          # match stance velocity
    h00 = 2 * u ** 3 - 3 * u ** 2 + 1
    h10 = u ** 3 - 2 * u ** 2 + u
    h01 = -2 * u ** 3 + 3 * u ** 2
    h11 = u ** 3 - u ** 2
    off = h00 * (-half) + h10 * m + h01 * half + h11 * m
    lift = 0.24 * math.sin(math.pi * u) ** 0.85
    return base + FWD * off + Vector((0.0, 0.0, lift))


def walk_frame(f):
    t = (f / float(WALK_N)) % 1.0
    legs = {k: walk_target(k, (t - WALK_GROUP[k]) % 1.0) for k in ALL_LEGS}
    bob = math.sin(4.0 * math.pi * t + math.pi * 0.5)
    roll = math.sin(2.0 * math.pi * t) * 2.2
    return dict(legs=legs,
                body_off=(math.sin(2.0 * math.pi * t) * 0.02, 0.0, 0.032 * bob),
                body=[("X", -1.6 + 1.2 * bob), ("Y", roll), ("Z", math.sin(2 * math.pi * t + 1.0) * 2.4)],
                abdo=[("X", 2.2 * math.sin(4.0 * math.pi * t + 2.2))],
                egg=[("X", -3.0 * math.sin(4.0 * math.pi * t + 2.6))],
                head=[("X", -1.0 * bob)],
                palp_L=[("X", 6.0 * math.sin(2 * math.pi * t + 0.4))],
                palp_R=[("X", 6.0 * math.sin(2 * math.pi * t + 0.4 + math.pi))])


WALK_KEYS = [(f, walk_frame(f)) for f in range(0, WALK_N + 1)]

# --- Hit: recoil, legs brace.
HIT_KEYS = [
    (0, dict()),
    (2, dict(root_off=(0.0, 0.10, 0.03), body=[("X", 5.0)], head=[("X", 4.0)],
             abdo=[("X", -4.0)], egg=[("X", 6.0)],
             legs={(1, 0): "fk", (-1, 0): "fk"},
             leg_fk={(1, 0): dict(femur=14.0, tibia=-16.0),
                     (-1, 0): dict(femur=14.0, tibia=-16.0)},
             palp_L=[("X", -14.0)], palp_R=[("X", -14.0)])),
    (5, dict(root_off=(0.0, 0.15, 0.05), body=[("X", 8.0)], head=[("X", 7.0)],
             abdo=[("X", -7.0)], egg=[("X", 11.0)],
             cheli_L=[("X", 6.0)], cheli_R=[("X", 6.0)],
             legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.06 if k[0] > 0 else -0.06, -0.04, 0.0)))
                   for k in ALL_LEGS},
             palp_L=[("X", -18.0), ("Z", -6.0)], palp_R=[("X", -18.0), ("Z", 6.0)])),
    (9, dict(root_off=(0.0, 0.05, 0.015), body=[("X", 3.0)], abdo=[("X", -2.0)],
             egg=[("X", 4.0)], palp_L=[("X", -6.0)], palp_R=[("X", -6.0)])),
    (14, dict()),
]

# --- Stun: sagging, legs splayed wider, head down.
STUN_KEYS = [
    (0, dict(body_off=(0.0, 0.0, -0.09), body=[("X", 3.5)], head=[("X", 7.0)],
             abdo=[("X", -3.0)], egg=[("X", 4.0)],
             legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.10 if k[0] > 0 else -0.10, 0.05, 0.0)))
                   for k in ALL_LEGS},
             cheli_L=[("X", -22.0)], cheli_R=[("X", -22.0)],
             palp_L=[("X", -24.0)], palp_R=[("X", -24.0)])),
    (9, dict(body_off=(0.022, 0.0, -0.098), body=[("X", 3.0), ("Y", 1.6)], head=[("X", 8.0), ("Z", 5.0)],
             abdo=[("X", -2.0)], egg=[("X", 3.0)],
             legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.11 if k[0] > 0 else -0.11, 0.05, 0.0)))
                   for k in ALL_LEGS},
             cheli_L=[("X", -21.0)], cheli_R=[("X", -23.0)],
             palp_L=[("X", -26.0)], palp_R=[("X", -22.0)])),
    (17, dict(body_off=(0.0, 0.0, -0.105), body=[("X", 4.0)], head=[("X", 9.0)],
              abdo=[("X", -4.0)], egg=[("X", 5.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.10 if k[0] > 0 else -0.10, 0.05, 0.0)))
                    for k in ALL_LEGS},
              cheli_L=[("X", -24.0)], cheli_R=[("X", -24.0)],
              palp_L=[("X", -23.0)], palp_R=[("X", -25.0)])),
    (26, dict(body_off=(-0.022, 0.0, -0.098), body=[("X", 3.0), ("Y", -1.6)],
              head=[("X", 8.0), ("Z", -5.0)], abdo=[("X", -2.0)], egg=[("X", 3.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.11 if k[0] > 0 else -0.11, 0.05, 0.0)))
                    for k in ALL_LEGS},
              cheli_L=[("X", -23.0)], cheli_R=[("X", -21.0)],
              palp_L=[("X", -22.0)], palp_R=[("X", -26.0)])),
]
STUN_KEYS.append((34, STUN_KEYS[0][1]))

CURL = {k: dict(femur=40.0, tibia=-30.0, tarsus=-22.0,
                yaw=(10.0 if k[0] > 0 else -10.0)) for k in ALL_LEGS}
CURL_HARD = {k: dict(femur=48.0, tibia=-24.0, tarsus=-30.0,
                     yaw=(16.0 if k[0] > 0 else -16.0)) for k in ALL_LEGS}
DEAD_LEGS = {k: "fk" for k in ALL_LEGS}

# --- Death: buckles, sinks, legs curl over the body, settles as a corpse.
DEATH_KEYS = [
    (0, dict()),
    (4, dict(body_off=(0.0, 0.02, 0.035), body=[("X", -4.0)], abdo=[("X", 3.0)],
             head=[("X", -3.0)], egg=[("X", -4.0)])),
    (10, dict(root_off=(0.0, 0.0, -0.02), body_off=(0.0, 0.03, -0.09), body=[("X", 3.0), ("Y", 4.0)],
              abdo=[("X", -2.0)], head=[("X", -7.0)], egg=[("X", 2.0)],
              cheli_L=[("X", -6.0), ("Z", 6.0)], cheli_R=[("X", -6.0), ("Z", -6.0)],
              palp_L=[("X", -12.0)], palp_R=[("X", -12.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.13 if k[0] > 0 else -0.13,
                                                      0.06, 0.0))) for k in ALL_LEGS})),
    (18, dict(root_off=(0.0, 0.0, -0.04), body_off=(0.0, 0.05, -0.15), body=[("X", 3.0), ("Y", 3.0)],
              abdo=[("X", 5.0)], head=[("X", -13.0)], egg=[("X", 0.0)],
              cheli_L=[("X", -10.0), ("Z", 10.0)], cheli_R=[("X", -10.0), ("Z", -10.0)],
              palp_L=[("X", -17.0)], palp_R=[("X", -17.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.19 if k[0] > 0 else -0.19,
                                                      0.08, 0.0))) for k in ALL_LEGS})),
    (28, dict(root_off=(0.0, 0.0, -0.055), body_off=(0.0, 0.06, -0.19), body=[("X", 2.0), ("Y", 1.0)],
              abdo=[("X", 11.0)], head=[("X", -14.0)], egg=[("X", -3.0)],
              cheli_L=[("X", -11.0), ("Z", 13.0)], cheli_R=[("X", -11.0), ("Z", -13.0)],
              palp_L=[("X", -18.0), ("Z", -6.0)], palp_R=[("X", -18.0), ("Z", 6.0)],
              legs=DEAD_LEGS, leg_fk=CURL)),
    (38, dict(root_off=(0.0, 0.0, -0.06), body_off=(0.0, 0.055, -0.21), body=[("X", 1.0)],
              abdo=[("X", 15.0)], head=[("X", -18.0)], egg=[("X", -4.0)],
              cheli_L=[("X", -12.0), ("Z", 14.0)], cheli_R=[("X", -12.0), ("Z", -14.0)],
              palp_L=[("X", -24.0), ("Z", -8.0)], palp_R=[("X", -24.0), ("Z", 8.0)],
              legs=DEAD_LEGS, leg_fk=CURL_HARD)),
    (46, dict(root_off=(0.0, 0.0, -0.06), body_off=(0.0, 0.05, -0.215), body=[("X", 1.0)],
              abdo=[("X", 17.0)], head=[("X", -19.0)], egg=[("X", -4.0)],
              cheli_L=[("X", -13.0), ("Z", 15.0)], cheli_R=[("X", -13.0), ("Z", -15.0)],
              palp_L=[("X", -26.0), ("Z", -9.0)], palp_R=[("X", -26.0), ("Z", 9.0)],
              legs=DEAD_LEGS, leg_fk=CURL_HARD)),
    (53, dict(root_off=(0.0, 0.0, -0.06), body_off=(0.0, 0.05, -0.215), body=[("X", 1.0)],
              abdo=[("X", 17.0)], head=[("X", -19.0)], egg=[("X", -4.0)],
              cheli_L=[("X", -13.0), ("Z", 15.0)], cheli_R=[("X", -13.0), ("Z", -15.0)],
              palp_L=[("X", -26.0), ("Z", -9.0)], palp_R=[("X", -26.0), ("Z", 9.0)],
              legs=DEAD_LEGS, leg_fk=CURL_HARD)),
]

FRONT = [(1, 0), (-1, 0), (1, 1), (-1, 1)]
REAR = [(1, 2), (-1, 2), (1, 3), (-1, 3)]
LIFT_LEGS = {k: "fk" for k in FRONT}
LIFT_HIGH = {k: dict(femur=62.0, tibia=-26.0, tarsus=-18.0) for k in FRONT}
LIFT_MID = {k: dict(femur=34.0, tibia=-14.0, tarsus=-8.0) for k in FRONT}

# --- Slam_Anticipation: rear up, both front leg pairs high. No damage frame.
SLAM_ANT_KEYS = [
    (0, dict()),
    (6, dict(root=[("X", -5.0)], body_off=(0.0, 0.0, 0.05), body=[("X", -3.0)],
             abdo=[("X", -2.0)], head=[("X", -4.0)], egg=[("X", 3.0)],
             legs=LIFT_LEGS, leg_fk=LIFT_MID,
             palp_L=[("X", 12.0)], palp_R=[("X", 12.0)])),
    (14, dict(root=[("X", -14.0)], body_off=(0.0, -0.02, 0.16), body=[("X", -4.0)],
              abdo=[("X", -6.0)], head=[("X", -8.0)], egg=[("X", 8.0)],
              cheli_L=[("X", -12.0), ("Z", 9.0)], cheli_R=[("X", -12.0), ("Z", -9.0)],
              legs=LIFT_LEGS, leg_fk=LIFT_HIGH,
              palp_L=[("X", 20.0), ("Z", -8.0)], palp_R=[("X", 20.0), ("Z", 8.0)])),
    (22, dict(root=[("X", -17.0)], body_off=(0.0, -0.02, 0.185), body=[("X", -5.0)],
              abdo=[("X", -7.0)], head=[("X", -9.0)], egg=[("X", 9.0)],
              cheli_L=[("X", -14.0), ("Z", 10.0)], cheli_R=[("X", -14.0), ("Z", -10.0)],
              legs=LIFT_LEGS, leg_fk={k: dict(femur=68.0, tibia=-30.0, tarsus=-20.0) for k in FRONT},
              palp_L=[("X", 24.0), ("Z", -9.0)], palp_R=[("X", 24.0), ("Z", 9.0)])),
]
SLAM_ANT_KEYS.append((29, SLAM_ANT_KEYS[-1][1]))

SLAM_SPREAD = {k: (LEG_CHAIN[k]["tip"] + Vector((0.16 * (1 if k[0] > 0 else -1), -0.30, 0.0)))
               for k in FRONT}

# --- Slam_Attack: both front pairs crash down, body drops, recovers.
SLAM_ATK_KEYS = [
    (0, SLAM_ANT_KEYS[-1][1]),
    (2, dict(root=[("X", 4.0)], body_off=(0.0, -0.01, 0.08), body=[("X", 2.0)],
             abdo=[("X", 1.0)], head=[("X", 4.0)], egg=[("X", -2.0)],
             legs=LIFT_LEGS, leg_fk={k: dict(femur=40.0, tibia=-30.0, tarsus=-20.0) for k in FRONT},
             cheli_L=[("X", 6.0)], cheli_R=[("X", 6.0)])),
    (4, dict(root=[("X", 3.0)], body_off=(0.0, 0.0, -0.070), body=[("X", 2.0)],
             abdo=[("X", 9.0)], head=[("X", 3.0)], egg=[("X", -12.0)],
             legs=SLAM_SPREAD, cheli_L=[("X", -20.0), ("Z", 10.0)], cheli_R=[("X", -20.0), ("Z", -10.0)],
             palp_L=[("X", -40.0)], palp_R=[("X", -40.0)])),
    (7, dict(root=[("X", 2.0)], body_off=(0.0, 0.0, -0.045), body=[("X", 1.0)],
             abdo=[("X", 5.0)], head=[("X", 2.0)], egg=[("X", -7.0)],
             legs=SLAM_SPREAD, cheli_L=[("X", -12.0), ("Z", 6.0)], cheli_R=[("X", -12.0), ("Z", -6.0)],
             palp_L=[("X", -24.0)], palp_R=[("X", -24.0)])),
    (12, dict(root=[("X", 2.0)], body_off=(0.0, 0.0, -0.015), body=[("X", 1.0)],
              abdo=[("X", 2.0)], egg=[("X", -2.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.07 * (1 if k[0] > 0 else -1),
                                                      -0.12 if k[1] <= 1 else 0.0, 0.0)))
                    for k in FRONT})),
    (19, dict()),
]

# --- Spit_Anticipation: tilt back, fangs spread, abdomen rises.
SPIT_ANT_KEYS = [
    (0, dict()),
    (6, dict(root=[("X", -4.0)], body_off=(0.0, 0.02, 0.03), body=[("X", -3.0)],
             abdo=[("X", 3.0)], head=[("X", -6.0)], egg=[("X", -3.0)],
             cheli_L=[("X", -8.0), ("Z", 8.0)], cheli_R=[("X", -8.0), ("Z", -8.0)],
             palp_L=[("X", 8.0)], palp_R=[("X", 8.0)])),
    (12, dict(root=[("X", -9.0)], body_off=(0.0, 0.05, 0.07), body=[("X", -6.0)],
              abdo=[("X", 6.0)], head=[("X", -12.0)], egg=[("X", -6.0)],
              cheli_L=[("X", -16.0), ("Z", 15.0)], cheli_R=[("X", -16.0), ("Z", -15.0)],
              palp_L=[("X", 16.0), ("Z", -6.0)], palp_R=[("X", 16.0), ("Z", 6.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.08 * (1 if k[0] > 0 else -1),
                                                      0.10 if k[1] >= 2 else 0.0, 0.0)))
                    for k in ALL_LEGS})),
    (18, dict(root=[("X", -11.0)], body_off=(0.0, 0.06, 0.085), body=[("X", -7.0)],
              abdo=[("X", 8.0)], head=[("X", -14.0)], egg=[("X", -7.0)],
              cheli_L=[("X", -19.0), ("Z", 18.0)], cheli_R=[("X", -19.0), ("Z", -18.0)],
              palp_L=[("X", 19.0), ("Z", -7.0)], palp_R=[("X", 19.0), ("Z", 7.0)],
              legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.09 * (1 if k[0] > 0 else -1),
                                                      0.11 if k[1] >= 2 else 0.0, 0.0)))
                    for k in ALL_LEGS})),
]
SPIT_ANT_KEYS.append((22, SPIT_ANT_KEYS[-1][1]))

# --- Spit_Attack: forward thrust of head and chelicerae, then recovery.
SPIT_ATK_KEYS = [
    (0, SPIT_ANT_KEYS[-1][1]),
    (3, dict(root=[("X", -2.0)], body_off=(0.0, -0.17, 0.01), body=[("X", 3.0)],
             abdo=[("X", 6.0)], head=[("X", 16.0)], head_off=(0.0, -0.06, 0.0),
             egg=[("X", 4.0)],
             cheli_L=[("X", 26.0), ("Z", 4.0)], cheli_R=[("X", 26.0), ("Z", -4.0)],
             palp_L=[("X", -22.0)], palp_R=[("X", -22.0)],
             legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.05 * (1 if k[0] > 0 else -1),
                                                     -0.06 if k[1] <= 1 else 0.06, 0.0)))
                   for k in ALL_LEGS})),
    (6, dict(root=[("X", -1.0)], body_off=(0.0, -0.115, 0.005), body=[("X", 2.0)],
             abdo=[("X", 4.0)], head=[("X", 11.0)], head_off=(0.0, -0.04, 0.0),
             egg=[("X", 3.0)],
             cheli_L=[("X", 17.0), ("Z", 6.0)], cheli_R=[("X", 17.0), ("Z", -6.0)],
             palp_L=[("X", -16.0)], palp_R=[("X", -16.0)],
             legs={k: (LEG_CHAIN[k]["tip"] + Vector((0.05 * (1 if k[0] > 0 else -1),
                                                     -0.04 if k[1] <= 1 else 0.04, 0.0)))
                   for k in ALL_LEGS})),
    (10, dict(root=[("X", -3.0)], body_off=(0.0, -0.03, 0.02), body=[("X", -1.0)],
              abdo=[("X", 2.0)], head=[("X", 2.0)], egg=[("X", 1.0)],
              cheli_L=[("X", 2.0)], cheli_R=[("X", 2.0)])),
    (17, dict()),
]

CLIPS = [
    ("Idle", IDLE_KEYS, True),
    ("Walk", WALK_KEYS, True),
    ("Hit", HIT_KEYS, False),
    ("Stun", STUN_KEYS, True),
    ("Death", DEATH_KEYS, False),
    ("Slam_Anticipation", SLAM_ANT_KEYS, False),
    ("Slam_Attack", SLAM_ATK_KEYS, False),
    ("Spit_Anticipation", SPIT_ANT_KEYS, False),
    ("Spit_Attack", SPIT_ATK_KEYS, False),
]
ACTIONS = {}
for name, keys, loop in CLIPS:
    ACTIONS[name] = author(name, keys, loop)
    if IK_CLAMPS:
        print("[matriarch] WARNING: %d ik targets clamped (first %s)" % (len(IK_CLAMPS), IK_CLAMPS[0]))
        IK_CLAMPS = []
print("[matriarch] ik solver residual: %.5f m" % IK_ERR[0])

# ---------------------------------------------------------------------- LOD1

LOD1 = None
if MAKE_LOD1:
    lod = BODY.copy()
    lod.name = "LOD1"
    lod.data = BODY.data.copy()
    lod.data.name = "LOD1"
    bpy.context.collection.objects.link(lod)
    for m in list(lod.modifiers):
        lod.modifiers.remove(m)
    dec = lod.modifiers.new("Decimate", "DECIMATE")
    dec.decimate_type = "COLLAPSE"
    dec.ratio = 0.5
    dec.use_collapse_triangulate = False
    bpy.context.view_layer.objects.active = lod
    bpy.ops.object.modifier_apply(modifier=dec.name)
    lod.parent = ARM
    am = lod.modifiers.new("Armature", "ARMATURE")
    am.object = ARM
    LOD1 = lod
    print("[matriarch] LOD1: %d tris (%.0f%% of LOD0)"
          % (sum(len(p.vertices) - 2 for p in lod.data.polygons),
             100.0 * sum(len(p.vertices) - 2 for p in lod.data.polygons) / M.tris()))
else:
    print("[matriarch] LOD1: skipped (--no-lod1)")

# ---------------------------------------------------------------- validation

scene = bpy.context.scene
scene.render.fps = FPS
scene.unit_settings.system = "METRIC"
ARM.animation_data_create()
ARM.animation_data.action = None
clear_pose()
update()

LOD0_TRIS = sum(len(p.vertices) - 2 for p in BODY.data.polygons)
BONE_N = len(ARM.data.bones)
CLIP_N = len(ACTIONS)
LEG_CHAINS = 8
co = np.array([tuple(v.co) for v in BODY.data.vertices], np.float32)
SPAN = float(co[:, 0].max() - co[:, 0].min())
HEIGHT = float(co[:, 2].max())
MIN_Y = float(co[:, 2].min())
# UV islands may not overlap. Nothing is mirrored: every left/right leg island
# is generated from its own layout, so uv_mirrored is 0 by construction.
_uv_overlaps = [1 for _i in range(len(ISLANDS)) for _j in range(_i + 1, len(ISLANDS))
                if ISLANDS[_i]["rect"][0] < ISLANDS[_j]["rect"][2]
                and ISLANDS[_j]["rect"][0] < ISLANDS[_i]["rect"][2]
                and ISLANDS[_i]["rect"][1] < ISLANDS[_j]["rect"][3]
                and ISLANDS[_j]["rect"][1] < ISLANDS[_i]["rect"][3]]
UV_MIRRORED = 0
BAD = []
if _uv_overlaps:
    BAD.append("%d uv islands overlap" % len(_uv_overlaps))
if not all(0.0 <= c <= 1.0 for isl in ISLANDS for c in isl["rect"]):
    BAD.append("uv island outside 0-1")
if LOD0_TRIS < 25000:
    print("[matriarch] WARNING: LOD0 under the 25k budget (%d tris)" % LOD0_TRIS)

if BONE_N != EXPECTED_BONES:
    BAD.append("bone count %d != %d" % (BONE_N, EXPECTED_BONES))
for s, sfx in ((1, "L"), (-1, "R")):
    for i in range(4):
        for seg in LEG_BONES:
            if "Leg" + sfx + str(i + 1) + "_" + seg not in ARM.data.bones:
                BAD.append("missing leg bone")
                LEG_CHAINS -= 1
                break
REQUIRED = [c[0] for c in CLIPS]
for name in REQUIRED:
    if name not in ACTIONS:
        BAD.append("missing action %s" % name)
if LOD0_TRIS > 50000:
    BAD.append("triangle budget exceeded: %d" % LOD0_TRIS)
if abs(MIN_Y) > 0.02:
    BAD.append("feet not on y=0: min_y=%.4f" % MIN_Y)
if not (2.9 <= SPAN <= 3.6):
    BAD.append("leg span out of range: %.3f" % SPAN)

# Death must end lowered: the body bone's world height has to drop clearly.
deps = bpy.context.evaluated_depsgraph_get()
ARM.animation_data.action = ACTIONS["Death"]
scene.frame_set(int(ACTIONS["Death"].frame_start))
z_start = ARM.pose.bones["Body"].head.z
scene.frame_set(int(ACTIONS["Death"].frame_end))
z_end = ARM.pose.bones["Body"].head.z
DEATH_DROP = z_start - z_end
DEATH_FEET_UP = min(ARM.pose.bones["Leg" + LEG_SUFFIX[k] + "_Tarsus"].tail.z for k in ALL_LEGS)

# Ground sweep: no clip may drive the mesh through the floor.
GROUND = {}
CORPSE_MIN_Z, CORPSE_WORST_F, CORPSE_WORST_PART = 9.0, 0, ""
for name, keys, loop in CLIPS:
    ARM.animation_data.action = ACTIONS[name]
    zmin, zframe, zpart = 9.0, 0, ""
    for f in range(keys[0][0], keys[-1][0] + 1):
        scene.frame_set(f)
        me = BODY.evaluated_get(deps).to_mesh()
        zi = min(range(len(me.vertices)), key=lambda i: me.vertices[i].co.z)
        if me.vertices[zi].co.z < zmin:
            zmin, zframe = me.vertices[zi].co.z, f
            zpart = "%s rest=%s" % (M.part[zi], tuple(round(c, 2) for c in M.co[zi]))
        BODY.evaluated_get(deps).to_mesh_clear()
    GROUND[name] = (zmin, zframe, zpart)
    if name == "Death":
        CORPSE_MIN_Z, CORPSE_WORST_F, CORPSE_WORST_PART = zmin, zframe, zpart
ARM.animation_data.action = None
clear_pose()
scene.frame_set(0)
if DEATH_DROP < 0.15:
    BAD.append("Death last frame not lowered (drop %.3f m)" % DEATH_DROP)
for name, (zmin, zframe, zpart) in GROUND.items():
    if zmin < -0.06:
        BAD.append("%s drives the mesh through the floor (min y %.3f at frame %d, %s)"
                   % (name, zmin, zframe, zpart))

# Walk accuracy: how far the stance feet stray from the intended dead-straight
# constant-speed path once the action is sampled frame by frame.
ARM.animation_data.action = ACTIONS["Walk"]
walk_worst = 0.0
walk_low = 0.0
walk_worst_at = ("", 0)
for f in range(0, WALK_N + 1):
    scene.frame_set(f)
    t = (f / float(WALK_N)) % 1.0
    for key in ALL_LEGS:
        lt = (t - WALK_GROUP[key]) % 1.0
        tip = ARM.pose.bones["Leg" + LEG_SUFFIX[key] + "_Tarsus"].tail
        walk_low = min(walk_low, tip.z)
        if lt < WALK_DUTY:
            err = (Vector(tip) - walk_target(key, lt)).length
            if err > walk_worst:
                walk_worst, walk_worst_at = err, (key, f)
ARM.animation_data.action = None
clear_pose()
WALK_SPEED = WALK_SWEEP / (WALK_DUTY * WALK_N / float(FPS))

# ---------------------------------------------------------------- pose renders

RENDERS = []
try:
    os.makedirs(RENDER_DIR, exist_ok=True)
    engine = None
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = candidate
            engine = candidate
            break
        except TypeError:
            continue
    if engine is None:
        raise RuntimeError("no usable render engine")
    print("[matriarch] render engine: %s" % engine)
    if engine != "BLENDER_WORKBENCH":
        scene.eevee.taa_render_samples = 32
    else:
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 800
    scene.render.resolution_y = 600
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.exposure = 0.2
    except TypeError:
        pass
    world = bpy.data.worlds.new("BossWorld")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.20, 0.22, 0.26, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    # Sun direction: a sun emits along its own -Z, so aiming +Z at the light
    # position puts the key over the creature's front-right shoulder.
    for nm, energy, to_light in (("Key", 7.0, (0.55, -0.72, 0.60)),
                                 ("Fill", 2.2, (-0.80, -0.35, 0.30)),
                                 ("Rim", 2.4, (-0.25, 0.90, 0.45))):
        ld = bpy.data.lights.new(nm, "SUN")
        ld.energy = energy
        lod = Vector(to_light).normalized()
        lo = bpy.data.objects.new(nm, ld)
        lo.rotation_euler = lod.to_track_quat("Z", "Y").to_euler()
        bpy.context.collection.objects.link(lo)
    cam_data = bpy.data.cameras.new("GameplayCam")
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(65.0)
    cam = bpy.data.objects.new("GameplayCam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    cam.location = Vector((7.0, -7.0, 1.8))
    cam.rotation_euler = (Vector((0.0, 0.10, 0.75)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    if LOD1 is not None:
        LOD1.hide_render = True
    for tag, clip, frame in (("idle", "Idle", 15), ("slam", "Slam_Attack", 4), ("dead", "Death", 53)):
        ARM.animation_data.action = ACTIONS[clip]
        scene.frame_set(frame)
        path = os.path.join(RENDER_DIR, "matriarch-%s.png" % tag)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        RENDERS.append(path)
        print("[matriarch] rendered %s (%s frame %d)" % (path, clip, frame))
    ARM.animation_data.action = ACTIONS["Slam_Anticipation"]
    scene.frame_set(22)
    cam.location = Vector((3.6, -4.6, 1.35))
    cam.rotation_euler = (Vector((0.0, -0.20, 0.80)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    path = os.path.join(RENDER_DIR, "matriarch-review-rearup.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    RENDERS.append(path)
    print("[matriarch] rendered %s (Slam_Anticipation frame 22)" % path)
    # Close review passes (same rig, neutral pose) for asset review.
    ARM.animation_data.action = ACTIONS["Idle"]
    scene.frame_set(0)
    for tag, loc, target in (("front", (0.0, -5.4, 0.95), (0.0, 0.0, 0.62)),
                             ("three_quarter", (3.9, -3.9, 1.25), (0.0, -0.05, 0.60)),
                             ("rear", (2.6, 4.6, 1.2), (0.0, 0.35, 0.55))):
        cam.location = Vector(loc)
        cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(RENDER_DIR, "matriarch-review-%s.png" % tag)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        RENDERS.append(path)
        print("[matriarch] rendered %s" % path)
    # Flat-albedo pass (Workbench, texture colour): shows UV islands, seams and
    # the texture atlas without lighting getting in the way.
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "TEXTURE"
    cam.location = Vector((0.0, -5.4, 0.95))
    cam.rotation_euler = (Vector((0.0, 0.0, 0.62)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    path = os.path.join(RENDER_DIR, "matriarch-review-albedo.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    RENDERS.append(path)
    print("[matriarch] rendered %s (flat albedo)" % path)
    ARM.animation_data.action = None
    clear_pose()
    scene.frame_set(0)
except Exception as exc:                                     # noqa: BLE001
    print("[matriarch] renders skipped: %s" % exc)
    RENDERS = []

# --------------------------------------------------------------------- export

for act in bpy.data.actions:
    act.use_fake_user = True
ARM.animation_data_create()
ARM.animation_data.action = None
clear_pose()
print("[matriarch] exporting %s" % OUT)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True,
                          export_apply=False, export_animations=True,
                          export_animation_mode="ACTIONS",
                          export_optimize_animation_size=True,
                          export_image_format="AUTO", export_skins=True,
                          export_def_bones=False, export_influence_nb=4)
SIZE = os.path.getsize(OUT)

import json
import struct
with open(OUT, "rb") as fh:
    blob = fh.read()
jlen = struct.unpack("<I", blob[12:16])[0]
GLTF = json.loads(blob[20:20 + jlen].decode("utf-8"))
GLB_ANIMS = [a.get("name", "?") for a in GLTF.get("animations", [])]
GLB_TEX = [i.get("name") for i in GLTF.get("images", [])]
for name in REQUIRED:
    if name not in GLB_ANIMS:
        BAD.append("glb missing animation %s" % name)

# ---------------------------------------------------------------------- report

print("[matriarch] tris=%d bones=%d clips=%d span_m=%.2f height_m=%.2f min_y=%.3f uv_mirrored=%d"
      % (LOD0_TRIS, BONE_N, CLIP_N, SPAN, HEIGHT, MIN_Y, UV_MIRRORED))
for name, keys, loop in CLIPS:
    print("[matriarch] clip %-18s frames %3d-%3d  %.2fs  loop=%d  keys=%d"
          % (name, keys[0][0], keys[-1][0], (keys[-1][0] - keys[0][0]) / FPS, int(loop), len(keys)))
print("[matriarch] lod1=%s lod0_tris=%d glb_bytes=%d" %
      (("%d tris" % sum(len(p.vertices) - 2 for p in LOD1.data.polygons)) if LOD1 else "missing", LOD0_TRIS, SIZE))
print("[matriarch] glb animations: %s" % GLB_ANIMS)
print("[matriarch] glb images: %s" % GLB_TEX)
print("[matriarch] ik residual=%.5f m  walk_stance_drift=%.4f m (%s frame %d, constant-speed stance path)"
      "  walk_swing_min_z=%.3f  implied_walk_speed=%.2f m/s"
      % (IK_ERR[0], walk_worst, walk_worst_at[0], walk_worst_at[1], walk_low, WALK_SPEED))
print("[matriarch] death: body drop=%.3f m  corpse_min_y=%.3f m at frame %d (%s)  curled_feet_min_y=%.3f m"
      % (DEATH_DROP, CORPSE_MIN_Z, CORPSE_WORST_F, CORPSE_WORST_PART, DEATH_FEET_UP))
print("[matriarch] per-clip min y: %s"
      % ", ".join("%s %.3f@%d" % (n, v[0], v[1]) for n, v in sorted(GROUND.items())))
print("[matriarch] renders: %s" % (RENDERS if RENDERS else "skipped"))

if BAD:
    for b in BAD:
        print("[matriarch] FAIL: %s" % b)
    raise SystemExit(1)
print("[matriarch] OK")

