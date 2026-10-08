"""Build the boss creature: the Dark Snatcher Commander.

A purpose-built, rigged, animated, textured dark-wizard boss that replaces the
scaled Quaternius `Orc_Skull` placeholder. Everything is generated here -- there
is no downloaded source art: the mesh is lofted from authored profiles, the
19-bone rig is built from the same numbers, the nine clips are keyed by pose
deltas, and the three maps (albedo / OpenGL normal / roughness) are generated
into one 1024 atlas and packed into the GLB.

Conventions
  * 1 unit = 1 metre, forward +Z in Godot = -Y in Blender (the exporter maps
    Blender -Y -> glTF +Z), up +Y in Godot = +Z in Blender.
  * Bind pose stands on z = 0; the crown (the hood peak) measures ~2.20 m.
  * No root motion: every clip is authored in place.
  * Mirror plane is x = 0; +x is the character's LEFT (Godot +Z forward, +Y up),
    so `_L` bones and the cape's left panel sit at +x, the staff at -x.
  * Robe_F/Robe_B/Robe_L/Robe_R name the skirt quadrants *in game space*
    (F = facing direction = Blender -Y).

Materials: four slots sharing one 1024 atlas, every UV island in unique texel
space (no overlaps, no mirrored islands -- the guard below asserts it).
  Commander_Robe   cloth: robe, cape, collar, hood, sleeves, boots
  Commander_Trim   leather + iron: belt, sash, chest strap, gloves, iron bands,
                   buckles, the staff's claw head
  Commander_Staff  wood + bone + dark orb: the shaft, the bone shards, the orb
  Commander_Eyes   the shadowed face plane and the two glowing eyes
Metallic policy is a single non-metallic one: metallicFactor is 0 on all four
slots (verified by reading the exported GLB back). The iron reads as dull steel
through the albedo and the 0.30-0.45 roughness band of the atlas rather than
through a metal map, so the glTF carries the roughness in the
metallicRoughness texture's G channel with a zeroed metallic factor. The eyes
glow because the eyes slot drives Emission Color from the same albedo atlas,
where only the eye islands are bright red.

Run:
  blender -b --factory-startup --python client/tools/blender/build_boss_commander.py \
      -- --out client/assets/models/monsters/boss_commander.glb
"""
import bpy, bmesh, sys, os, math, json, struct, zlib
import numpy as np
from mathutils import Vector, Quaternion

# ------------------------------------------------------------------ arguments
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.abspath(os.path.join(HERE, "..", "..", "assets", "models", "monsters", "boss_commander.glb"))
DEFAULT_RENDER = os.path.abspath(os.path.join(HERE, "..", "downloads"))
OUT = os.path.abspath(argv[argv.index("--out") + 1]) if "--out" in argv else DEFAULT_OUT
RENDER_DIR = os.path.abspath(argv[argv.index("--render") + 1]) if "--render" in argv else DEFAULT_RENDER
os.makedirs(os.path.dirname(OUT), exist_ok=True)

FPS = 24
TEX = 1024
ROUGH_RES = 512
SEED = 20261005

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

# =====================================================================
# 1. deterministic noise / texture helpers
# =====================================================================
def vnoise(W, H, fx, fy, seed):
    """Tiling value noise on a W x H grid with an fx x fy lattice."""
    g = np.random.default_rng(seed).random((fy, fx)).astype(np.float32)
    xs = np.arange(W, dtype=np.float32) * (fx / W)
    ys = np.arange(H, dtype=np.float32) * (fy / H)
    x0 = np.floor(xs).astype(np.int32) % fx
    y0 = np.floor(ys).astype(np.int32) % fy
    tx = (xs - np.floor(xs)).astype(np.float32)
    ty = (ys - np.floor(ys)).astype(np.float32)
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)
    x1 = (x0 + 1) % fx
    y1 = (y0 + 1) % fy
    a = g[np.ix_(y0, x0)] * (1 - tx)[None, :] + g[np.ix_(y0, x1)] * tx[None, :]
    b = g[np.ix_(y1, x0)] * (1 - tx)[None, :] + g[np.ix_(y1, x1)] * tx[None, :]
    return a * (1 - ty)[:, None] + b * ty[:, None]


def fbm(W, H, fx, fy, octaves, seed):
    total = np.zeros((H, W), np.float32)
    amp, norm = 1.0, 0.0
    for i in range(octaves):
        total += vnoise(W, H, max(1, int(fx * (2 ** i))), max(1, int(fy * (2 ** i))), seed + i * 977) * amp
        norm += amp
        amp *= 0.5
    return total / norm


def normal_from_height(height, strength):
    """OpenGL (+Y) tangent-space normal from a height field.

    Blender's image rows run bottom-up (row 0 = v = 0) and the PNG writer flips
    them on save, so +row is +v: n = normalize(-dh/du, -dh/dv, 1).
    """
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    n = np.stack([-dx, -dy, np.ones_like(height)], axis=-1)
    n /= np.maximum(1e-6, np.linalg.norm(n, axis=-1, keepdims=True))
    return n * 0.5 + 0.5


def clamp01(x):
    return np.clip(x, 0.0, 1.0)


# ------------------------------------------------------------------ atlas
# Region table: the whole asset samples one 1024 atlas. Cloth takes the left
# 70 %, the six detail families tile the right column, the small eye/face/orb
# patches take the bottom-right. Nothing overlaps; islands are packed per
# region so a part never leaves its family's pattern.
REGION_RECTS = {
    "CLOTH":   (0.000, 0.000, 0.700, 1.000),
    "LEATHER": (0.700, 0.750, 1.000, 1.000),
    "METAL":   (0.700, 0.500, 1.000, 0.750),
    "WOOD":    (0.700, 0.250, 1.000, 0.500),
    "BONE":    (0.700, 0.125, 0.850, 0.250),
    "ORB":     (0.850, 0.125, 1.000, 0.250),
    "EYE":     (0.700, 0.000, 0.850, 0.125),
    "FACE":    (0.850, 0.000, 1.000, 0.125),
}
MARGIN = 6  # px inset that keeps islands off the region borders (bleed guard)


class Region:
    def __init__(self, name, rect):
        self.name = name
        self.rect = rect
        x0, y0, x1, y1 = (int(round(v * TEX)) for v in rect)
        self.px = (x0 + MARGIN, y0 + MARGIN, x1 - MARGIN, y1 - MARGIN)
        self.items = []
        self.rects = None
        self.density = 0.0

    def add(self, key, world_w, world_h):
        self.items.append((key, max(1e-4, world_w), max(1e-4, world_h)))

    def pack(self, gutter=5, fill=0.68):
        W = self.px[2] - self.px[0]
        H = self.px[3] - self.px[1]
        area = sum(w * h for _, w, h in self.items)
        rho = math.sqrt(max(1e-6, W * H * fill / max(1e-6, area)))
        for _ in range(30):
            placed = self._try(rho, W, H, gutter)
            if placed is not None:
                self.density = rho
                self.rects = placed
                return True
            rho *= 0.93
        raise RuntimeError("atlas region %s cannot pack %d islands" % (self.name, len(self.items)))

    def _try(self, rho, W, H, gutter):
        items = sorted(self.items, key=lambda it: (-it[2], it[0]))
        cx = 0
        cy = 0
        shelf = 0
        out = {}
        for key, w, h in items:
            pw = max(4, int(math.ceil(w * rho)))
            ph = max(4, int(math.ceil(h * rho)))
            if cx + pw > W and cx > 0:
                cx = 0
                cy += shelf + gutter
                shelf = 0
            if cy + ph > H or pw > W:
                return None
            out[key] = (self.px[0] + cx, self.px[1] + cy, self.px[0] + cx + pw, self.px[1] + cy + ph)
            cx += pw + gutter
            shelf = max(shelf, ph)
        return out


class Atlas:
    def __init__(self):
        self.regions = {name: Region(name, rect) for name, rect in REGION_RECTS.items()}

    def add(self, region, key, world_w, world_h):
        self.regions[region].add(key, world_w, world_h)

    def pack(self):
        for name in sorted(self.regions):
            self.regions[name].pack()

    def island(self, region, key):
        return self.regions[region].rects[key]

    def islands(self, region):
        return self.regions[region].rects


# =====================================================================
# 2. character constants
# =====================================================================
HEM_Z = 0.14          # skirt hem ring (smooth row above the tatters)
NECK_Z = 1.80         # robe top
THICK = 0.024         # cloth shell thickness

ROBE_PROFILE = [      # (z, rx, ry) -- the draped body + skirt
    (0.140, 0.418, 0.386),
    (0.260, 0.410, 0.378),
    (0.420, 0.396, 0.364),
    (0.600, 0.366, 0.336),
    (0.780, 0.330, 0.298),
    (0.930, 0.296, 0.264),
    (1.020, 0.278, 0.250),   # hips
    (1.140, 0.252, 0.228),
    (1.250, 0.240, 0.216),   # waist
    (1.360, 0.246, 0.206),
    (1.480, 0.262, 0.206),
    (1.600, 0.288, 0.214),
    (1.700, 0.294, 0.220),   # shoulder line
    (1.760, 0.240, 0.200),
    (1.800, 0.184, 0.160),   # neck
]
CAPE_PROFILE = [
    (1.420, 0.374, 0.338),   # tattered edge row above
    (1.510, 0.358, 0.324),
    (1.600, 0.340, 0.308),
    (1.690, 0.312, 0.286),
    (1.760, 0.276, 0.252),
    (1.840, 0.200, 0.186),
]
HOOD_PROFILE = [      # (z, rx, ry, y-centre)
    (1.700, 0.212, 0.202, 0.030),
    (1.780, 0.226, 0.216, 0.018),
    (1.860, 0.234, 0.226, 0.004),
    (1.940, 0.232, 0.224, -0.006),
    (2.020, 0.214, 0.206, -0.018),
    (2.090, 0.182, 0.176, -0.032),
    (2.150, 0.122, 0.120, -0.052),
    (2.200, 0.048, 0.048, -0.072),
]
HOOD_OPENING = [(1.740, 0.00), (1.770, 0.74), (1.860, 0.71), (1.940, 0.60),
                (2.000, 0.43), (2.050, 0.22), (2.090, 0.00)]

FRONT = -math.pi / 2.0          # -Y is the facing direction in Blender

# The right arm reaches forward so the staff (and the hand on it) clears the
# skirt silhouette; the left arm hangs a little forward of the robe.
ARM_L = [Vector((0.235, 0.0, 1.700)), Vector((0.372, 0.020, 1.300)), Vector((0.396, -0.170, 1.060))]
HAND_L = [Vector((0.396, -0.170, 1.060)), Vector((0.400, -0.262, 0.996))]
ARM_R = [Vector((-0.235, 0.0, 1.700)), Vector((-0.378, 0.005, 1.300)), Vector((-0.404, -0.262, 1.060))]
HAND_R = [Vector((-0.404, -0.262, 1.060)), Vector((-0.408, -0.338, 1.022))]

STAFF_X, STAFF_Y = -0.420, -0.306
STAFF_BOTTOM = 0.055
STAFF_TOP = 2.140
GRIP_Z = 1.020
ORB_Z = 2.225
ORB_R = 0.084

EYE_L = Vector((0.049, -0.092, 1.905))
EYE_R = Vector((-0.049, -0.092, 1.905))

BONES = [
    # name, head, tail, parent, connected
    ("Root",       (0.0, 0.0, 0.000),  (0.0, 0.0, 0.220),  None, False),
    ("Hips",       (0.0, 0.0, 1.000),  (0.0, 0.0, 1.160),  "Root", False),
    ("Spine",      (0.0, 0.0, 1.160),  (0.0, 0.0, 1.420),  "Hips", True),
    ("Chest",      (0.0, 0.0, 1.420),  (0.0, 0.0, 1.720),  "Spine", True),
    ("Neck",       (0.0, 0.0, 1.720),  (0.0, 0.0, 1.840),  "Chest", True),
    ("Head",       (0.0, 0.0, 1.840),  (0.0, 0.0, 2.080),  "Neck", True),
    ("Shoulder_L", (0.050, 0.0, 1.660), (0.230, 0.0, 1.700), "Chest", False),
    ("UpperArm_L", (0.235, 0.0, 1.700), (0.372, 0.020, 1.300), "Shoulder_L", False),
    ("LowerArm_L", (0.372, 0.020, 1.300), (0.396, -0.170, 1.060), "UpperArm_L", True),
    ("Hand_L",     (0.396, -0.170, 1.060), (0.400, -0.262, 0.996), "LowerArm_L", True),
    ("Shoulder_R", (-0.050, 0.0, 1.660), (-0.230, 0.0, 1.700), "Chest", False),
    ("UpperArm_R", (-0.235, 0.0, 1.700), (-0.378, 0.005, 1.300), "Shoulder_R", False),
    ("LowerArm_R", (-0.378, 0.005, 1.300), (-0.404, -0.262, 1.060), "UpperArm_R", True),
    ("Hand_R",     (-0.404, -0.262, 1.060), (-0.408, -0.338, 1.022), "LowerArm_R", True),
    ("Staff",      (-0.408, -0.276, GRIP_Z), (-0.408, -0.276, 1.800), "Hand_R", False),
    ("Robe_F",     (0.0, -0.100, 1.000), (0.0, -0.440, 0.150), "Hips", False),
    ("Robe_B",     (0.0, 0.100, 1.000),  (0.0, 0.440, 0.150),  "Hips", False),
    ("Robe_L",     (0.100, 0.0, 1.000),  (0.440, 0.0, 0.150),  "Hips", False),
    ("Robe_R",     (-0.100, 0.0, 1.000), (-0.440, 0.0, 0.150), "Hips", False),
]
BONE_NAMES = [b[0] for b in BONES]
ROBE_BONES = ("Robe_F", "Robe_B", "Robe_L", "Robe_R")

MAT_ROBE, MAT_TRIM, MAT_STAFF, MAT_EYES = 0, 1, 2, 3

# =====================================================================
# 3. mesh builder
# =====================================================================
def sstep(x):
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def spline(ctrl, x):
    """Catmull-Rom through (key, value) control points, clamped at the ends."""
    if x <= ctrl[0][0]:
        return ctrl[0][1]
    if x >= ctrl[-1][0]:
        return ctrl[-1][1]
    i = 0
    while i < len(ctrl) - 2 and x > ctrl[i + 1][0]:
        i += 1
    x0, y0 = ctrl[i]
    x1, y1 = ctrl[i + 1]
    t = (x - x0) / max(1e-9, x1 - x0)
    ym = ctrl[i - 1][1] if i > 0 else y0
    yp = ctrl[i + 2][1] if i + 2 < len(ctrl) else y1
    return 0.5 * ((2 * y0) + (-ym + y1) * t +
                  (2 * ym - 5 * y0 + 4 * y1 - yp) * t * t +
                  (-ym + 3 * y0 - 3 * y1 + yp) * t * t * t)


class MB:
    """Accumulates positions, faces, per-loop UVs, material ids and part tags."""

    def __init__(self):
        self.v = []
        self.f = []
        self.uv = []
        self.mat = []
        self.tag = []
        self.smooth = []

    def vert(self, p, tag):
        self.v.append(Vector(p))
        self.tag.append(tag)
        return len(self.v) - 1

    def face(self, idx, uvs, mat, smooth=True):
        assert len(idx) == len(uvs)
        self.f.append(tuple(idx))
        self.uv.extend(uvs)
        self.mat.append(mat)
        self.smooth.append(smooth)

    def tri_count(self):
        return sum(len(f) - 2 for f in self.f)


def uvlerp(island, a, b):
    x0, y0, x1, y1 = island
    return ((x0 + (x1 - x0) * a) / TEX, (y0 + (y1 - y0) * b) / TEX)


def loft(mb, rows, tag, mat, island, smooth=True, flip=False, closed_ring=True):
    """rows[r][i] = (Vector position, a, b natural coords).

    Ring rows are generated with a duplicated closing column, so `a` runs 0..1
    across the ring and the seam lands on a UV boundary instead of wrapping.
    """
    idx = [[mb.vert(p, tag) for (p, a, b) in row] for row in rows]
    for r in range(len(rows) - 1):
        for i in range(len(rows[0]) - 1):
            quad = (idx[r][i], idx[r][i + 1], idx[r + 1][i + 1], idx[r + 1][i])
            uv = [uvlerp(island, rows[r][i][1], rows[r][i][2]),
                  uvlerp(island, rows[r][i + 1][1], rows[r][i + 1][2]),
                  uvlerp(island, rows[r + 1][i + 1][1], rows[r + 1][i + 1][2]),
                  uvlerp(island, rows[r + 1][i][1], rows[r + 1][i][2])]
            if flip:
                quad = tuple(reversed(quad))
                uv = list(reversed(uv))
            mb.face(quad, uv, mat, smooth)


def fan(mb, center, ring, tag, mat, island, smooth=True, flip=False, c_uv=(0.5, 0.5)):
    idx_c = mb.vert(center[0], tag)
    idx = [mb.vert(p, tag) for (p, a, b) in ring]
    for i in range(len(ring) - 1):
        tri = (idx_c, idx[i], idx[i + 1])
        uv = [uvlerp(island, c_uv[0], c_uv[1]),
              uvlerp(island, ring[i][1], ring[i][2]),
              uvlerp(island, ring[i + 1][1], ring[i + 1][2])]
        if flip:
            tri = tuple(reversed(tri))
            uv = list(reversed(uv))
        mb.face(tri, uv, mat, smooth)


def stitch(mb, row_a, row_b, tag, mat, island, smooth=False, flip=False, u0=0.0, u1=1.0):
    """Bridge two open rows (rims); each quad gets its own strip of the island.

    A shell has two rims (bottom and top); they share one island in halves via
    u0/u1 so neither touches the other's texels.
    """
    ia = [mb.vert(p, tag) for (p, a, b) in row_a]
    ib = [mb.vert(p, tag) for (p, a, b) in row_b]
    n = len(row_a) - 1
    for i in range(n):
        a0, a1 = u0 + (u1 - u0) * i / float(n), u0 + (u1 - u0) * (i + 1) / float(n)
        quad = (ia[i], ia[i + 1], ib[i + 1], ib[i])
        uv = [uvlerp(island, a0, 0.0), uvlerp(island, a1, 0.0),
              uvlerp(island, a1, 1.0), uvlerp(island, a0, 1.0)]
        if flip:
            quad = tuple(reversed(quad))
            uv = list(reversed(uv))
        mb.face(quad, uv, mat, smooth)


def tatter(s, n, count, base, depth, phase=0.0, power=0.85):
    """Discrete hem tatter height; lands exactly on ring vertices."""
    x = (s * count / float(n)) + phase
    f = x - math.floor(x)
    tri = 1.0 - abs(2.0 * f - 1.0)
    return base - depth * (tri ** power)


def setb(rows, vals=None):
    """Rewrite the v coordinate of every vertex in a list of rows."""
    R = len(rows)
    for r, row in enumerate(rows):
        b = (r / float(R - 1)) if vals is None else vals[r]
        for i in range(len(row)):
            p, a, _ = row[i]
            row[i] = (p, a, b)
    return rows


def ring_pts(z, rx, ry, n, yc=0.0, folds=0.0, fold_n=7, fold_phase=0.0, tag_extra=None):
    """Closed ring as (pos, a, b) triples with a duplicated closing column."""
    out = []
    for s in range(n + 1):
        si = s % n                      # the closing column repeats vertex 0
        th = 2.0 * math.pi * si / n
        k = 1.0
        if folds:
            p = (0.55 * math.cos(fold_n * th + fold_phase + 0.7) +
                 0.28 * math.cos(2 * fold_n * th + fold_phase + 2.1) +
                 0.17 * math.cos(3 * fold_n * th + fold_phase + 4.0))
            k = 1.0 + folds * (math.copysign(abs(p) ** 0.8, p))
        out.append((Vector((rx * k * math.cos(th), yc + ry * k * math.sin(th), z)), s / float(n), 0.0))
    return out


# =====================================================================
# 4. parts
# =====================================================================
def build_robe(mb, atlas, D):
    isl = atlas.island("CLOTH", "robe")
    isl_in = atlas.island("CLOTH", "robe_in")
    isl_rim = atlas.island("CLOTH", "robe_rim")
    isl_cap = atlas.island("CLOTH", "robe_cap")
    n = D["robe_seg"]
    bands = D["robe_bands"]
    tags = "robe"
    rows_out, rows_in = [], []
    for r in range(bands + 1):
        t = r / float(bands)
        if r == 0:
            rows_out.append(ring_pts(0.0, 1.0, 1.0, n))       # placeholder, filled below
        else:
            z = 0.20 + (NECK_Z - 0.20) * ((r - 1) / float(bands - 1))
            rx = spline([(p[0], p[1]) for p in ROBE_PROFILE], z)
            ry = spline([(p[0], p[2]) for p in ROBE_PROFILE], z)
            fold = 0.014 + 0.070 * sstep((0.86 - t) / 0.86)
            rows_out.append(ring_pts(z, rx, ry, n, folds=fold, fold_n=D["folds"],
                                     fold_phase=0.55 * t))
    # hem tatter row (r = 0): recomputed per vertex so the points are crisp
    hem = []
    inner_hem = []
    for s in range(n + 1):
        si = s % n
        th = 2.0 * math.pi * si / n
        z = tatter(si, n, D["tatters"], 0.195, 0.125, phase=0.18)
        z2 = tatter(si, n, D["tatters"], 0.195, 0.110, phase=0.18)
        rx = spline([(p[0], p[1]) for p in ROBE_PROFILE], z)
        ry = spline([(p[0], p[2]) for p in ROBE_PROFILE], z)
        k = 1.0 + 0.084 * math.cos(7 * th + 0.9)
        hem.append((Vector((rx * k * math.cos(th), ry * k * math.sin(th), z)), s / float(n), 0.0))
        ki = 1.0 + 0.084 * math.cos(7 * th + 0.9)
        inner_hem.append((Vector(((rx - THICK) * ki * math.cos(th), (ry - THICK) * ki * math.sin(th), z2)),
                          s / float(n), 1.0))
    rows_out[0] = hem
    for r in range(len(rows_out)):
        row = []
        for (p, a, _b) in rows_out[r]:
            d = Vector((p.x, p.y))
            rl = max(0.02, d.length)
            sc = max(0.02, (rl - THICK)) / rl
            row.append((Vector((p.x * sc, p.y * sc, p.z + (0.010 if r > 0 else 0.0))), a, 1.0 - r / float(bands)))
        rows_in.append(row)
    # b coordinate runs 0 at the hem .. 1 at the neck (top of the atlas island)
    for r in range(len(rows_out)):
        for i in range(len(rows_out[r])):
            p, a, _ = rows_out[r][i]
            rows_out[r][i] = (p, a, r / float(bands))
            p, a, _ = rows_in[r][i]
            rows_in[r][i] = (p, a, r / float(bands))
    loft(mb, rows_out, tags, MAT_ROBE, isl, smooth=True)
    loft(mb, rows_in, tags, MAT_ROBE, isl_in, smooth=True, flip=True)
    stitch(mb, rows_out[0], rows_in[0], tags, MAT_ROBE, isl_rim)              # hem rim
    stitch(mb, rows_in[-1], rows_out[-1], tags, MAT_ROBE, isl_rim, u0=0.5)    # neck rim
    top = []
    for (p, a, b) in rows_out[-1]:
        top.append((Vector((p.x * 0.55, p.y * 0.55, p.z + 0.010)), a, 0.0))
    fan(mb, (Vector((0.0, 0.0, NECK_Z + 0.010)), 0.5, 0.5), top, tags, MAT_ROBE, isl_cap)
    return mb.tri_count()


def build_cape(mb, atlas, D):
    isl = atlas.island("CLOTH", "cape")
    isl_in = atlas.island("CLOTH", "cape_in")
    isl_rim = atlas.island("CLOTH", "cape_rim")
    n = D["cape_seg"]
    bands = D["cape_bands"]
    rows_out, rows_in = [], []
    for r in range(bands + 1):
        z = 1.400 + (1.840 - 1.400) * (r / float(bands))
        rx = spline([(p[0], p[1]) for p in CAPE_PROFILE], z)
        ry = spline([(p[0], p[2]) for p in CAPE_PROFILE], z)
        rows_out.append(ring_pts(z, rx, ry, n, folds=0.020, fold_n=D["folds"] + 3,
                                 fold_phase=0.3 * r / bands))
    edge, edge_in = [], []
    for s in range(n + 1):
        si = s % n
        th = 2.0 * math.pi * si / n
        z = tatter(si, n, D["cape_tatters"], 1.400, 0.105, phase=0.42)
        rx = spline([(p[0], p[1]) for p in CAPE_PROFILE], z) + 0.014
        ry = spline([(p[0], p[2]) for p in CAPE_PROFILE], z) + 0.014
        k = 1.0 + 0.030 * math.cos(10 * th + 0.4)
        edge.append((Vector((rx * k * math.cos(th), ry * k * math.sin(th), z)), s / float(n), 0.0))
        edge_in.append((Vector(((rx - 0.020) * k * math.cos(th), (ry - 0.020) * k * math.sin(th), z + 0.006)),
                        s / float(n), 0.0))
    rows_out.insert(0, edge)
    rows_in = []
    for r in range(len(rows_out)):
        row = []
        for (p, a, _b) in rows_out[r]:
            d = Vector((p.x, p.y))
            rl = max(0.02, d.length)
            sc = max(0.02, (rl - 0.020)) / rl
            row.append((Vector((p.x * sc, p.y * sc, p.z + (0.006 if r > 0 else 0.0))), a, 0.0))
        rows_in.append(row)
    total = len(rows_out) - 1
    for r in range(len(rows_out)):
        for i in range(len(rows_out[r])):
            p, a, _ = rows_out[r][i]
            rows_out[r][i] = (p, a, r / float(total))
            p, a, _ = rows_in[r][i]
            rows_in[r][i] = (p, a, r / float(total))
    loft(mb, rows_out, "cape", MAT_ROBE, isl, smooth=True)
    loft(mb, rows_in, "cape", MAT_ROBE, isl_in, smooth=True, flip=True)
    stitch(mb, rows_out[0], rows_in[0], "cape", MAT_ROBE, isl_rim)
    stitch(mb, rows_in[-1], rows_out[-1], "cape", MAT_ROBE, isl_rim, u0=0.5)
    return mb.tri_count()


def build_collar(mb, atlas, D):
    isl = atlas.island("CLOTH", "collar")
    isl_in = atlas.island("CLOTH", "collar_in")
    isl_rim = atlas.island("CLOTH", "collar_rim")
    n = D["collar_seg"]
    rows_out, rows_in = [], []
    for r in range(3):
        t = r / 2.0
        out, inn = [], []
        for s in range(n + 1):
            si = s % n
            th = 2.0 * math.pi * si / n
            back = 0.5 + 0.5 * math.sin(th)                  # 1 at the back, 0 at the front
            ztop = 1.800 + 0.215 * back
            z = lerp(1.720, ztop, t)
            rad = 0.204 + 0.088 * back * t
            k = 1.0 + 0.022 * math.cos(6 * th)
            out.append((Vector((rad * k * math.cos(th), rad * k * math.sin(th), z)), s / float(n), t))
            ri = max(0.05, rad - 0.020)
            inn.append((Vector((ri * k * math.cos(th), ri * k * math.sin(th), z - 0.004)), s / float(n), t))
        rows_out.append(out)
        rows_in.append(inn)
    loft(mb, rows_out, "collar", MAT_ROBE, isl, smooth=True)
    loft(mb, rows_in, "collar", MAT_ROBE, isl_in, smooth=True, flip=True)
    stitch(mb, rows_out[-1], rows_in[-1], "collar", MAT_ROBE, isl_rim)
    stitch(mb, rows_in[0], rows_out[0], "collar", MAT_ROBE, isl_rim, u0=0.5)
    return mb.tri_count()


def build_hood(mb, atlas, D):
    isl = atlas.island("CLOTH", "hood")
    isl_cb = atlas.island("CLOTH", "hood_cap_b")
    isl_ct = atlas.island("CLOTH", "hood_cap_t")
    n = D["hood_seg"]
    bands = D["hood_bands"]
    rows = []
    for r in range(bands + 1):
        z = 1.700 + (2.200 - 1.700) * (r / float(bands))
        rx = spline([(p[0], p[1]) for p in HOOD_PROFILE], z)
        ry = spline([(p[0], p[2]) for p in HOOD_PROFILE], z)
        yc = spline([(p[0], p[3]) for p in HOOD_PROFILE], z)
        alpha = spline(HOOD_OPENING, z)
        front_y = yc - ry + 0.150
        frx, fry = 0.108, 0.088
        ycf = front_y + fry
        row = []
        for s in range(n + 1):
            si = s % n
            th = 2.0 * math.pi * si / n
            ox = rx * math.cos(th)
            oy = yc + ry * math.sin(th)
            fx = frx * math.cos(th)
            fy = ycf + fry * math.sin(th)
            d = abs((th - (2.0 * math.pi + FRONT)) % (2.0 * math.pi))
            d = min(d, 2.0 * math.pi - d)
            k = sstep((alpha + 0.16 - d) / 0.16)
            row.append((Vector((lerp(ox, fx, k), lerp(oy, fy, k), z)), s / float(n), r / float(bands)))
        rows.append(row)
    loft(mb, rows, "hood", MAT_ROBE, isl, smooth=True)
    # bottom cap (hidden inside the collar) and top cap at the peak
    cap = [((p.x, p.y, 1.694), a, 0.0) for (p, a, b) in rows[0]]
    fan(mb, (Vector((0.0, 0.03, 1.690)), 0.5, 0.5), cap, "hood", MAT_ROBE, isl_cb, flip=True)
    apex = [(p, a, 0.0) for (p, a, b) in rows[-1]]
    fan(mb, (Vector((0.0, -0.072, 2.202)), 0.5, 0.5), apex, "hood", MAT_ROBE, isl_ct)
    return mb.tri_count()


def build_eyes(mb, atlas, D):
    tris = mb.tri_count()
    for centre, key in ((EYE_L, "eye_L"), (EYE_R, "eye_R")):
        isl = atlas.island("EYE", key)
        seg, rings = D["eye_seg"], 6
        rows = []
        for r in range(rings + 1):
            phi = math.pi * (r / float(rings)) - math.pi * 0.5
            zz = math.sin(phi)
            rr = math.cos(phi)
            row = []
            for s in range(seg + 1):
                si = s % seg
                th = 2.0 * math.pi * si / seg
                p = Vector((centre.x + 0.026 * rr * math.cos(th),
                            centre.y + 0.019 * rr * math.sin(th) * 0.55 - 0.004 * zz,
                            centre.z + 0.019 * zz))
                row.append((p, s / float(seg), r / float(rings)))
            rows.append(row)
        loft(mb, rows, "eyes", MAT_EYES, isl, smooth=True)
    return mb.tri_count() - tris


def build_face(mb, atlas, D):
    """A shallow dark dome just behind the eyes so the hood recess is a face."""
    isl = atlas.island("FACE", "face")
    tris = mb.tri_count()
    seg, rings = D["face_seg"], 4
    cx, cy, cz = 0.0, 0.028, 1.905
    rows = []
    for r in range(rings + 1):
        t = r / float(rings)
        rad = 0.145 * (1.0 - 0.92 * t * t)
        zz = cz + 0.115 * t
        row = []
        for s in range(seg + 1):
            si = s % seg
            th = 2.0 * math.pi * si / seg
            p = Vector((cx + rad * math.cos(th), cy - 0.052 - 0.030 * (1.0 - t), zz))
            row.append((p, s / float(seg), t))
        rows.append(row)
    loft(mb, rows, "face", MAT_EYES, isl, smooth=True)
    return mb.tri_count() - tris


def frame_ring(centre, tangent, ra, rb, n, phase=0.0):
    t = tangent.normalized()
    ref = Vector((0.0, 1.0, 0.0)) if abs(t.z) > 0.7 else Vector((0.0, 0.0, 1.0))
    ax = ref.cross(t).normalized()
    ay = t.cross(ax).normalized()
    out = []
    for s in range(n + 1):
        si = s % n
        th = 2.0 * math.pi * si / n + phase
        out.append((ax * (ra * math.cos(th)) + ay * (rb * math.sin(th)), s / float(n)))
    return out, ax, ay


def poly_point(path, t):
    """Position + tangent at normalised arc length t along a polyline path."""
    segs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
    lens = [(b - a).length for a, b in segs]
    total = sum(lens)
    want = t * total
    acc = 0.0
    for (a, b), L in zip(segs, lens):
        if acc + L >= want or L == 0.0:
            u = 0.0 if L == 0.0 else (want - acc) / L
            u = min(1.0, max(0.0, u))
            return a.lerp(b, u), (b - a).normalized()
        acc += L
    return path[-1], (path[-1] - path[-2]).normalized()


SLEEVE_R = [(0.00, 0.118), (0.14, 0.101), (0.34, 0.093), (0.50, 0.089),
            (0.66, 0.086), (0.82, 0.098), (0.93, 0.116), (1.00, 0.112)]


def build_sleeve(mb, atlas, D, side):
    isl = atlas.island("CLOTH", "sleeve_%s" % side)
    isl_in = atlas.island("CLOTH", "sleeve_%s_in" % side)
    isl_rim = atlas.island("CLOTH", "sleeve_%s_rim" % side)
    path = ARM_L if side == "L" else ARM_R
    n = D["sleeve_seg"]
    bands = D["sleeve_bands"]
    rows_out, rows_in = [], []
    for r in range(bands + 1):
        t = r / float(bands)
        c, tan = poly_point(path, t)
        rad = spline(SLEEVE_R, t)
        ring, ax, ay = frame_ring(c, tan, rad, rad * 0.92, n)
        out, inn = [], []
        for (v, a) in ring:
            p = c + v
            q = c + v * (1.0 - 0.012 / max(0.02, v.length))
            out.append((p, a, t))
            inn.append((q, a, t))
        rows_out.append(out)
        rows_in.append(inn)
    loft(mb, rows_out, "arm_%s" % side, MAT_ROBE, isl, smooth=True)
    loft(mb, rows_in, "arm_%s" % side, MAT_ROBE, isl_in, smooth=True, flip=True)
    stitch(mb, rows_out[-1], rows_in[-1], "arm_%s" % side, MAT_ROBE, isl_rim)
    stitch(mb, rows_in[0], rows_out[0], "arm_%s" % side, MAT_ROBE, isl_rim, u0=0.5)
    return mb.tri_count()


def build_hand(mb, atlas, D, side):
    isl = atlas.island("LEATHER", "hand_%s" % side)
    isl_t = atlas.island("LEATHER", "thumb_%s" % side)
    path = HAND_L if side == "L" else HAND_R
    n = D["hand_seg"]
    ax_dir = (path[1] - path[0]).normalized()
    rows = []
    stops = [(0.00, 0.052, 0.040), (0.16, 0.060, 0.044), (0.45, 0.062, 0.042),
             (0.74, 0.055, 0.036), (1.00, 0.030, 0.020)]
    for (t, ra, rb) in stops:
        c = path[0].lerp(path[1], t) if len(path) == 2 else path[0]
        ring, ax, ay = frame_ring(c, ax_dir, ra, rb, n)
        rows.append([(c + v, a, t) for (v, a) in ring])
    isl_c = atlas.island("LEATHER", "hand_%s_cap" % side)
    loft(mb, rows, "hand_%s" % side, MAT_TRIM, isl, smooth=True)
    cap0 = [(Vector((path[0].x, path[0].y, path[0].z)), a, 0.0) for (p, a, b) in rows[0]]
    fan(mb, (path[0], 0.5, 0.5), cap0, "hand_%s" % side, MAT_TRIM, isl_c, flip=True)
    tip = path[1] + ax_dir * 0.024
    cap1 = [(p, a, 0.0) for (p, a, b) in rows[-1]]
    fan(mb, (tip, 0.5, 0.5), cap1, "hand_%s" % side, MAT_TRIM, isl_c)
    # thumb
    tang = ax_dir
    ref = Vector((0.0, 0.0, 1.0))
    side_v = ref.cross(tang).normalized() * (1.0 if side == "L" else -1.0)
    base = path[0].lerp(path[1], 0.30)
    trows = []
    for (t, rad) in ((0.0, 0.024), (0.5, 0.021), (1.0, 0.012)):
        c = base + tang * (0.055 * t) + side_v * (0.030 * t) - Vector((0.0, 0.010 * t, 0.0))
        ring, _, _ = frame_ring(c, (tang * 0.8 + side_v * 0.5 - Vector((0, 0.2, 0))).normalized(), rad, rad, max(6, n // 2))
        trows.append([(c + v, a, t) for (v, a) in ring])
    isl_tc = atlas.island("LEATHER", "thumb_%s_cap" % side)
    loft(mb, trows, "hand_%s" % side, MAT_TRIM, isl_t, smooth=True)
    fan(mb, (trows[0][0][0] - tang * 0.005, 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in trows[0]],
        "hand_%s" % side, MAT_TRIM, isl_tc, flip=True)
    fan(mb, (trows[-1][0][0] + (tang * 0.8 + side_v * 0.5).normalized() * 0.012, 0.5, 0.5),
        [(p, a, 0.0) for (p, a, b) in trows[-1]], "hand_%s" % side, MAT_TRIM, isl_tc)
    return mb.tri_count()


def box(mb, centre, half, tag, mat, island, uvb=0.0):
    """Axis-aligned 8-vertex box with flat shading."""
    idx = []
    for dx in (-1.0, 1.0):
        for dy in (-1.0, 1.0):
            for dz in (-1.0, 1.0):
                idx.append(mb.vert(centre + Vector((dx * half[0], dy * half[1], dz * half[2])), tag))
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 2, 6, 4), (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6)]
    for f in faces:
        mb.face([idx[i] for i in f],
                [uvlerp(island, uvb + 0.12 * k, uvb + 0.12 * k) for k in range(4)], mat, smooth=False)
    return idx


def build_belt(mb, atlas, D):
    isl = atlas.island("LEATHER", "belt")
    isl_in = atlas.island("LEATHER", "belt_in")
    isl_rim = atlas.island("LEATHER", "belt_rim")
    n = D["belt_seg"]
    rows = []
    for (z, ex, ey) in ((1.150, 0.000, 0.000), (1.176, 0.020, 0.017),
                        (1.268, 0.020, 0.017), (1.296, 0.000, 0.000)):
        rx = spline([(p[0], p[1]) for p in ROBE_PROFILE], z) + 0.016 + ex
        ry = spline([(p[0], p[2]) for p in ROBE_PROFILE], z) + 0.016 + ey
        rows.append(ring_pts(z, rx, ry, n, folds=0.010, fold_n=D["folds"]))
    setb(rows)
    inner = []
    for row in rows:
        inner.append([(Vector((p.x * 0.90, p.y * 0.90, p.z)), a, b) for (p, a, b) in row])
    setb(inner)
    loft(mb, rows, "belt", MAT_TRIM, isl, smooth=True)
    loft(mb, inner, "belt", MAT_TRIM, isl_in, smooth=True, flip=True)
    stitch(mb, rows[0], inner[0], "belt", MAT_TRIM, isl_rim, flip=True)
    stitch(mb, inner[-1], rows[-1], "belt", MAT_TRIM, isl_rim, flip=True, u0=0.5)
    # buckle
    box(mb, Vector((0.0, -0.268, 1.222)), (0.054, 0.026, 0.048), "belt", MAT_TRIM,
        atlas.island("METAL", "buckle"))
    return mb.tri_count()


def build_sash(mb, atlas, D):
    isl = atlas.island("LEATHER", "sash")
    n = D["belt_seg"] // 2
    path = [Vector((0.115, -0.236, 1.270)), Vector((0.150, -0.268, 1.020)),
            Vector((0.160, -0.262, 0.800)), Vector((0.150, -0.250, 0.660))]
    rows = []
    bands = D["sash_bands"]
    for r in range(bands + 1):
        t = r / float(bands)
        c, tan = poly_point(path, t)
        wid = 0.052 * (1.0 - 0.35 * t)
        ring, ax, ay = frame_ring(c, tan, wid, 0.012, n)
        rows.append([(c + v, a, 0.93 * t) for (v, a) in ring])
    end = [(p, a, 1.0) for (p, a, b) in rows[-1]]
    tipz = [((p.x, p.y + 0.0, p.z - 0.05 - 0.04 * math.cos(6 * k)), a, 1.0) for k, (p, a, b) in enumerate(end)]
    isl_c = atlas.island("LEATHER", "sash_cap")
    loft(mb, rows + [tipz], "sash", MAT_TRIM, isl, smooth=True)
    cap0 = [(Vector((p.x, p.y, p.z)), a, 0.0) for (p, a, b) in rows[0]]
    fan(mb, (rows[0][0][0] - Vector((0, 0, 0.01)), 0.5, 0.5), cap0, "sash", MAT_TRIM, isl_c, flip=True)
    fan(mb, (Vector(tipz[0][0]) + Vector((0, 0, -0.02)), 0.5, 0.5), tipz, "sash", MAT_TRIM, isl_c)
    return mb.tri_count()


def build_strap(mb, atlas, D):
    """Diagonal chest strap with a small iron clasp -- the layered-robe detail."""
    isl = atlas.island("LEATHER", "strap")
    n = 8
    bands = 14
    path = []
    for r in range(bands + 1):
        t = r / float(bands)
        th = math.radians(lerp(212.0, 318.0, t))
        z = lerp(1.700, 1.190, t)
        rx = spline([(p[0], p[1]) for p in ROBE_PROFILE], z) + 0.022
        ry = spline([(p[0], p[2]) for p in ROBE_PROFILE], z) + 0.022
        path.append(Vector((rx * math.cos(th), ry * math.sin(th), z)))
    rows = []
    for r in range(bands + 1):
        t = r / float(bands)
        c = path[r]
        tan = (path[min(bands, r + 1)] - path[max(0, r - 1)]).normalized()
        ring, ax, ay = frame_ring(c, tan, 0.030, 0.010, n)
        rows.append([(c + v, a, t) for (v, a) in ring])
    isl_c = atlas.island("LEATHER", "strap_cap")
    loft(mb, rows, "strap", MAT_TRIM, isl, smooth=True)
    fan(mb, (path[0] - Vector((0, 0, 0.008)), 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in rows[0]],
        "strap", MAT_TRIM, isl_c, flip=True)
    fan(mb, (path[-1] + Vector((0, 0, -0.008)), 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in rows[-1]],
        "strap", MAT_TRIM, isl_c)
    misl = atlas.island("METAL", "clasp")
    box(mb, path[bands // 2], (0.030, 0.030, 0.020), "strap", MAT_TRIM, misl, uvb=0.25)
    return mb.tri_count()


def build_boots(mb, atlas, D):
    n = D["boot_seg"]
    for sx in (1.0, -1.0):
        key = "boot_%s" % ("L" if sx > 0 else "R")
        bisl = atlas.island("CLOTH", key)
        rows = []
        stops = [(0.004, 0.058, 0.128, -0.030), (0.052, 0.060, 0.120, -0.026),
                 (0.104, 0.054, 0.098, -0.012), (0.168, 0.047, 0.078, 0.0), (0.214, 0.042, 0.070, 0.0)]
        for (z, ex, ey, oy) in stops:
            rows.append(ring_pts(z, ex, ey, n, yc=oy))
        setb(rows)
        for r, row in enumerate(rows):
            rows[r] = [(Vector((p.x + sx * 0.118, p.y, p.z)), a, b) for (p, a, b) in row]
        cisl = atlas.island("CLOTH", "%s_cap" % key)
        loft(mb, rows, key, MAT_TRIM, bisl, smooth=True)
        sole = [(Vector((p.x, p.y, 0.004)), a, 0.0) for (p, a, b) in rows[0]]
        fan(mb, (Vector((sx * 0.118, -0.030, 0.002)), 0.5, 0.5), sole, key, MAT_TRIM, cisl, flip=True)
        top = [(p, a, 0.0) for (p, a, b) in rows[-1]]
        fan(mb, (Vector((sx * 0.118, 0.0, 0.226)), 0.5, 0.5), top, key, MAT_TRIM, cisl)
    return mb.tri_count()


def build_staff(mb, atlas, D):
    wisl = atlas.island("WOOD", "shaft")
    misl = atlas.island("METAL", "ferrule")
    oisl = atlas.island("ORB", "orb")
    n = D["staff_seg"]
    bands = D["staff_bands"]
    # shaft: gnarled, tapered, running bottom -> orb
    rows = []
    for r in range(bands + 1):
        z = STAFF_BOTTOM + (STAFF_TOP - STAFF_BOTTOM) * (r / float(bands))
        t = r / float(bands)
        rad = 0.030 - 0.006 * t + 0.0035 * math.sin(t * 19.0)
        gn = 1.0 + 0.10 * math.cos(4.0 * t * 6.283 + 0.7)
        row = []
        for s in range(n + 1):
            si = s % n
            th = 2.0 * math.pi * si / n
            rr = rad * gn * (1.0 + 0.05 * math.cos(3 * th + 5.0 * t))
            row.append((Vector((STAFF_X + rr * math.cos(th), STAFF_Y + rr * math.sin(th), z)),
                        s / float(n), t))
        rows.append(row)
    wcisl = atlas.island("WOOD", "shaft_cap")
    loft(mb, rows, "staff", MAT_STAFF, wisl, smooth=True)
    fan(mb, (Vector((STAFF_X, STAFF_Y, STAFF_TOP + 0.005)), 0.5, 0.5),
        [(p, a, 0.0) for (p, a, b) in rows[-1]], "staff", MAT_STAFF, wcisl)
    # taper at the base + the iron ferrule
    bot = [(p, a, 0.0) for (p, a, b) in rows[0]]
    fan(mb, (Vector((STAFF_X, STAFF_Y, STAFF_BOTTOM - 0.030)), 0.5, 0.5), bot, "staff", MAT_STAFF,
        wcisl, flip=True)
    frows = []
    for (z, rr) in ((0.085, 0.031), (0.140, 0.040), (0.165, 0.038), (0.185, 0.031)):
        frows.append(ring_pts(z, rr, rr, n))
    setb(frows)
    for r in range(len(frows)):
        frows[r] = [(Vector((p.x + STAFF_X, p.y + STAFF_Y, p.z)), a, b) for (p, a, b) in frows[r]]
    loft(mb, frows, "staff", MAT_TRIM, misl, smooth=False)
    # iron bands
    band_z = [0.320, 0.640, 1.310, 1.700, 1.960]
    brows = []
    for z in band_z:
        brows.append([(z - 0.026, 0.0385), (z - 0.022, 0.0405), (z + 0.022, 0.0405), (z + 0.026, 0.0385)])
    for i, prof in enumerate(brows):
        b_isl = atlas.island("METAL", "band%d" % i)
        b_cap = atlas.island("METAL", "band%d_cap" % i)
        rws = []
        for (z, rr) in prof:
            rws.append(ring_pts(z, rr, rr, n))
        setb(rws)
        for r in range(len(rws)):
            rws[r] = [(Vector((p.x + STAFF_X, p.y + STAFF_Y, p.z)), a, b) for (p, a, b) in rws[r]]
        top = rws[-1]
        bot = rws[0]
        loft(mb, rws, "staff", MAT_TRIM, b_isl, smooth=False)
        fan(mb, (Vector((STAFF_X, STAFF_Y, prof[0][0] - 0.004)), 0.5, 0.5),
            [(p, a, 0.0) for (p, a, b) in bot], "staff", MAT_TRIM, b_cap, flip=True, smooth=False)
        fan(mb, (Vector((STAFF_X, STAFF_Y, prof[-1][0] + 0.004)), 0.5, 0.5),
            [(p, a, 0.0) for (p, a, b) in top], "staff", MAT_TRIM, b_cap, smooth=False)
    # head: four iron claws curling up out of the shaft to cradle the orb
    claws = D["claws"]
    for ci in range(claws):
        c_isl = atlas.island("METAL", "claw%d" % ci)
        c_cap = atlas.island("METAL", "claw%d_cap" % ci)
        th = 2.0 * math.pi * ci / claws
        crows = []
        steps = 7
        for r in range(steps + 1):
            t = r / float(steps)
            z = STAFF_TOP + 0.018 + 0.130 * t
            rad = 0.030 + 0.062 * math.sin(t * 1.35)
            c = Vector((STAFF_X + rad * math.cos(th), STAFF_Y + rad * math.sin(th), z))
            tan = Vector((-math.sin(th) * 0.35, math.cos(th) * 0.35, 1.0)).normalized()
            ring, _, _ = frame_ring(c, tan, 0.016 * (1.0 - 0.45 * t), 0.011 * (1.0 - 0.45 * t),
                                    max(6, n // 2))
            crows.append([(c + v, a, t) for (v, a) in ring])
        loft(mb, crows, "staff", MAT_TRIM, c_isl, smooth=False)
        fan(mb, (crows[0][0][0] - Vector((0, 0, 0.006)), 0.5, 0.5),
            [(p, a, 0.0) for (p, a, b) in crows[0]], "staff", MAT_TRIM, c_cap, flip=True, smooth=False)
        tipv = Vector((STAFF_X + 0.056 * math.cos(th) + 0.02 * math.cos(th),
                       STAFF_Y + 0.056 * math.sin(th) + 0.02 * math.sin(th), STAFF_TOP + 0.168))
        fan(mb, (tipv, 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in crows[-1]], "staff", MAT_TRIM, c_cap,
            smooth=False)
    # the dark orb
    orow = []
    oseg, orings = D["orb_seg"], 8
    for r in range(orings + 1):
        phi = math.pi * (r / float(orings)) - math.pi * 0.5
        zz = math.sin(phi)
        rr = math.cos(phi)
        row = []
        for s in range(oseg + 1):
            si = s % oseg
            th = 2.0 * math.pi * si / oseg
            p = Vector((STAFF_X + ORB_R * rr * math.cos(th), STAFF_Y + ORB_R * rr * math.sin(th),
                        ORB_Z + ORB_R * zz))
            row.append((p, s / float(oseg), r / float(orings)))
        orow.append(row)
    loft(mb, orow, "staff", MAT_STAFF, oisl, smooth=True)
    # bone shards lashed under the head, and a bone charm at the grip
    for bi, (z0, ang, ln) in enumerate(((2.010, 0.6, 0.115), (1.905, 3.5, 0.095), (2.070, 5.2, 0.080))):
        bisl = atlas.island("BONE", "bone%d" % bi)
        bcap = atlas.island("BONE", "bone%d_cap" % bi)
        base = Vector((STAFF_X + 0.040 * math.cos(ang), STAFF_Y + 0.040 * math.sin(ang), z0))
        dirv = Vector((math.cos(ang) * 0.45, math.sin(ang) * 0.45, 1.0)).normalized()
        rws = []
        for (t, rad) in ((0.0, 0.014), (0.35, 0.019), (0.70, 0.013), (1.0, 0.007)):
            c = base + dirv * (ln * t)
            ring, _, _ = frame_ring(c, dirv, rad, rad * 0.7, max(6, n // 2))
            rws.append([(c + v, a, t) for (v, a) in ring])
        loft(mb, rws, "staff", MAT_STAFF, bisl, smooth=True)
        fan(mb, (base - dirv * 0.008, 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in rws[0]],
            "staff", MAT_STAFF, bcap, flip=True)
        fan(mb, (base + dirv * (ln + 0.008), 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in rws[-1]],
            "staff", MAT_STAFF, bcap)
    bisl = atlas.island("BONE", "charm")
    bcap = atlas.island("BONE", "charm_cap")
    charm = Vector((STAFF_X + 0.052, STAFF_Y + 0.010, 1.115))
    crws = []
    for (t, rad) in ((0.0, 0.013), (0.4, 0.026), (0.75, 0.020), (1.0, 0.010)):
        c = charm + Vector((0.0, 0.0, -0.075 * t))
        ring, _, _ = frame_ring(c, Vector((0.0, 0.0, -1.0)), rad, rad * 0.8, max(6, n // 2))
        crws.append([(c + v, a, t) for (v, a) in ring])
    loft(mb, crws, "staff", MAT_STAFF, bisl, smooth=True)
    fan(mb, (charm + Vector((0, 0, 0.006)), 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in crws[0]],
        "staff", MAT_STAFF, bcap, flip=True)
    fan(mb, (charm + Vector((0, 0, -0.082)), 0.5, 0.5), [(p, a, 0.0) for (p, a, b) in crws[-1]],
        "staff", MAT_STAFF, bcap)
    return mb.tri_count()


# =====================================================================
# 5. atlas registration + detail levels
# =====================================================================
def register_atlas(atlas, D):
    """One island per authored surface -- nothing shares texel space."""
    atlas.add("CLOTH", "robe", 2.55, 1.70)
    atlas.add("CLOTH", "robe_in", 2.40, 1.70)
    atlas.add("CLOTH", "robe_rim", 2.60, 0.035)
    atlas.add("CLOTH", "robe_cap", 0.22, 0.22)
    atlas.add("CLOTH", "cape", 2.25, 0.62)
    atlas.add("CLOTH", "cape_in", 2.15, 0.62)
    atlas.add("CLOTH", "cape_rim", 2.30, 0.035)
    atlas.add("CLOTH", "collar", 1.32, 0.26)
    atlas.add("CLOTH", "collar_in", 1.26, 0.26)
    atlas.add("CLOTH", "collar_rim", 1.36, 0.035)
    atlas.add("CLOTH", "hood", 1.45, 0.56)
    atlas.add("CLOTH", "hood_cap_b", 0.30, 0.30)
    atlas.add("CLOTH", "hood_cap_t", 0.22, 0.22)
    for side in ("L", "R"):
        atlas.add("CLOTH", "sleeve_%s" % side, 0.64, 0.72)
        atlas.add("CLOTH", "sleeve_%s_in" % side, 0.62, 0.72)
        atlas.add("CLOTH", "sleeve_%s_rim" % side, 0.66, 0.030)
        atlas.add("CLOTH", "boot_%s" % side, 0.30, 0.24)
        atlas.add("CLOTH", "boot_%s_cap" % side, 0.05, 0.05)
        atlas.add("LEATHER", "hand_%s" % side, 0.34, 0.16)
        atlas.add("LEATHER", "hand_%s_cap" % side, 0.05, 0.05)
        atlas.add("LEATHER", "thumb_%s" % side, 0.10, 0.06)
        atlas.add("LEATHER", "thumb_%s_cap" % side, 0.05, 0.05)
    atlas.add("LEATHER", "belt", 1.68, 0.16)
    atlas.add("LEATHER", "belt_in", 1.60, 0.16)
    atlas.add("LEATHER", "belt_rim", 1.70, 0.030)
    atlas.add("LEATHER", "sash", 0.14, 0.62)
    atlas.add("LEATHER", "sash_cap", 0.05, 0.05)
    atlas.add("LEATHER", "strap", 0.70, 0.06)
    atlas.add("LEATHER", "strap_cap", 0.05, 0.05)
    atlas.add("METAL", "buckle", 0.12, 0.10)
    atlas.add("METAL", "clasp", 0.07, 0.07)
    atlas.add("METAL", "ferrule", 0.22, 0.10)
    for i in range(5):
        atlas.add("METAL", "band%d" % i, 0.26, 0.055)
        atlas.add("METAL", "band%d_cap" % i, 0.05, 0.05)
    for i in range(4):
        atlas.add("METAL", "claw%d" % i, 0.10, 0.17)
        atlas.add("METAL", "claw%d_cap" % i, 0.05, 0.05)
    atlas.add("WOOD", "shaft", 0.20, 2.09)
    atlas.add("WOOD", "shaft_cap", 0.06, 0.06)
    for i in range(3):
        atlas.add("BONE", "bone%d" % i, 0.09, 0.11)
        atlas.add("BONE", "bone%d_cap" % i, 0.05, 0.05)
    atlas.add("BONE", "charm", 0.08, 0.09)
    atlas.add("BONE", "charm_cap", 0.05, 0.05)
    atlas.add("ORB", "orb", 0.53, 0.17)
    for side in ("L", "R"):
        atlas.add("EYE", "eye_%s" % side, 0.10, 0.05)
    atlas.add("FACE", "face", 0.30, 0.20)


DETAIL = {
    "lod0": dict(robe_seg=84, robe_bands=30, folds=7, tatters=10,
                 cape_seg=68, cape_bands=12, cape_tatters=11,
                 collar_seg=44, hood_seg=48, hood_bands=18,
                 sleeve_seg=22, sleeve_bands=16, hand_seg=14,
                 belt_seg=44, sash_bands=11, boot_seg=14, eye_seg=14, face_seg=20,
                 staff_seg=18, staff_bands=38, claws=4, orb_seg=20),
    "lod1": dict(robe_seg=58, robe_bands=21, folds=6, tatters=8,
                 cape_seg=46, cape_bands=9, cape_tatters=9,
                 collar_seg=30, hood_seg=32, hood_bands=13,
                 sleeve_seg=15, sleeve_bands=11, hand_seg=10,
                 belt_seg=30, sash_bands=8, boot_seg=10, eye_seg=10, face_seg=12,
                 staff_seg=13, staff_bands=26, claws=4, orb_seg=14),
}


def build_character(D, atlas, lod):
    mb = MB()
    build_robe(mb, atlas, D)
    build_cape(mb, atlas, D)
    build_collar(mb, atlas, D)
    build_hood(mb, atlas, D)
    if lod == 0:
        build_face(mb, atlas, D)
    build_eyes(mb, atlas, D)
    build_sleeve(mb, atlas, D, "L")
    build_sleeve(mb, atlas, D, "R")
    build_hand(mb, atlas, D, "L")
    build_hand(mb, atlas, D, "R")
    build_belt(mb, atlas, D)
    build_sash(mb, atlas, D)
    build_strap(mb, atlas, D)
    build_boots(mb, atlas, D)
    build_staff(mb, atlas, D)
    return mb


# =====================================================================
# 6. meshes -> objects
# =====================================================================
print("[commander] packing texture atlas")
ATLAS = Atlas()
register_atlas(ATLAS, DETAIL["lod0"])
ATLAS.pack()
for name in sorted(ATLAS.regions):
    reg = ATLAS.regions[name]
    print("[commander] atlas %-8s px=%s density=%.0f px/m islands=%d"
          % (name, tuple(reg.px), reg.density, len(reg.items)))


def mesh_from_mb(mb, name):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in mb.v], [], mb.f)
    me.validate(verbose=False)
    if len(me.polygons) != len(mb.f):
        raise SystemExit("mesh %s lost faces during validate (%d != %d)"
                         % (name, len(me.polygons), len(mb.f)))
    uvl = me.uv_layers.new(name="UVMap")
    loop_i = 0
    for f_i, poly in enumerate(me.polygons):
        for k in range(poly.loop_total):
            uvl.data[poly.loop_start + k].uv = mb.uv[loop_i + k]
        loop_i += poly.loop_total
    for m in (MAT_ROBE, MAT_TRIM, MAT_STAFF, MAT_EYES):
        me.materials.append(bpy.data.materials["Commander_%s" % ("Robe", "Trim", "Staff", "Eyes")[m]])
    for poly, mi, sm in zip(me.polygons, mb.mat, mb.smooth):
        poly.material_index = mi
        poly.use_smooth = sm
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    # merge the duplicated UV-seam columns and orient every closed island outward
    bm = bmesh.new()
    bm.from_mesh(me)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0004)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    print("[commander] %s: %d verts (%d merged), %d faces, %d tris"
          % (name, len(me.vertices), before - len(me.vertices), len(me.polygons),
             sum(len(p.vertices) - 2 for p in me.polygons)))
    return ob


# =====================================================================
# 7. textures
# =====================================================================
print("[commander] generating textures")
ALB = np.zeros((TEX, TEX, 3), np.float32)
RGH = np.full((TEX, TEX), 0.7, np.float32)
HGT = np.full((TEX, TEX), 0.5, np.float32)


def region_grid(name):
    x0, y0, x1, y1 = ATLAS.regions[name].px
    W, H = x1 - x0, y1 - y0
    rho = ATLAS.regions[name].density
    uw = np.arange(W, dtype=np.float32) / rho
    vs = np.arange(H, dtype=np.float32) / rho
    return (slice(y0, y1), slice(x0, x1)), W, H, np.meshgrid(uw, vs)


def put(name, alb=None, rgh=None, hgt=None):
    sl, W, H, (U, V) = region_grid(name)
    if alb is not None:
        ALB[sl] = alb
    if rgh is not None:
        RGH[sl] = rgh
    if hgt is not None:
        HGT[sl] = hgt


# --- cloth: near-black woven robe with worn (lighter) weave crests
sl, W, H, (U, V) = region_grid("CLOTH")
cell = 0.019
tw1 = np.sin(2 * np.pi * U / cell)
tw2 = np.sin(2 * np.pi * V / cell)
diag = np.sin(2 * np.pi * (U + V) / (cell * 1.7))
weave = 0.5 + 0.5 * (0.55 * tw1 + 0.55 * tw2 + 0.45 * diag) / 1.55
fib = fbm(W, H, 90, 90, 3, SEED + 11) - 0.5
wear = fbm(W, H, 13, 13, 4, SEED + 12)
dirt = fbm(W, H, 34, 34, 4, SEED + 13)
crest = np.maximum(weave - 0.55, 0.0) / 0.45
base = np.array([0.104, 0.100, 0.120], np.float32)
alb = base[None, None, :] + (crest ** 1.9)[..., None] * np.array([0.062, 0.058, 0.055], np.float32)
alb += fib[..., None] * 0.016
alb += np.clip(wear - 0.55, 0.0, 1.0)[..., None] * 0.034
alb *= (0.84 + 0.26 * dirt)[..., None]
put("CLOTH", alb=np.clip(alb, 0.0, 1.0),
    rgh=np.clip(0.78 + 0.12 * (1.0 - weave) - 0.05 * np.clip(wear - 0.5, 0, 1), 0.75, 0.9),
    hgt=0.5 + 0.30 * (weave - 0.5) + 0.16 * fib)

# --- leather
sl, W, H, (U, V) = region_grid("LEATHER")
grain = fbm(W, H, 70, 70, 4, SEED + 21)
veins = fbm(W, H, 9, 26, 4, SEED + 22)
scuff = fbm(W, H, 20, 20, 4, SEED + 23)
alb = np.array([0.335, 0.228, 0.142], np.float32)[None, None, :] * (0.72 + 0.55 * grain)[..., None]
alb *= (0.85 + 0.28 * veins)[..., None]
t = np.clip(veins - 0.6, 0.0, 1.0)[..., None] * np.array([0.10, 0.06, 0.04], np.float32)
put("LEATHER", alb=np.clip(alb + t, 0, 1),
    rgh=np.clip(0.56 + 0.14 * grain + 0.06 * scuff, 0.55, 0.70),
    hgt=0.5 + 0.34 * (grain - 0.5) + 0.2 * (veins - 0.5))

# --- metal: dull steel with banding along u and hammered dents
sl, W, H, (U, V) = region_grid("METAL")
band = fbm(W, H, 3, 80, 3, SEED + 31)
dent = fbm(W, H, 26, 26, 4, SEED + 32)
edge = fbm(W, H, 7, 44, 3, SEED + 33)
sc = 0.5 + 0.5 * band
alb = np.array([0.575, 0.565, 0.545], np.float32)[None, None, :] * (0.58 + 0.62 * sc)[..., None]
alb *= (0.86 + 0.24 * dent)[..., None]
alb = np.clip(alb + np.clip(edge - 0.65, 0, 1)[..., None] * 0.20, 0, 1)
put("METAL", alb=alb,
    rgh=np.clip(0.30 + 0.16 * dent + 0.08 * (1.0 - band), 0.30, 0.45),
    hgt=0.5 + 0.30 * (band - 0.5) + 0.25 * (dent - 0.5))

# --- wood: grain along v (the shaft axis)
sl, W, H, (U, V) = region_grid("WOOD")
warp = fbm(W, H, 10, 200, 4, SEED + 41)
rings = np.sin(2 * np.pi * (U / 0.014 + warp * 3.2))
grain = 0.5 + 0.5 * rings
knot = fbm(W, H, 26, 90, 3, SEED + 42)
alb = np.array([0.320, 0.205, 0.115], np.float32)[None, None, :] * (0.55 + 0.85 * grain)[..., None]
alb *= (0.80 + 0.42 * knot)[..., None]
put("WOOD", alb=np.clip(alb, 0, 1),
    rgh=np.clip(0.55 + 0.14 * knot, 0.50, 0.70),
    hgt=0.5 + 0.34 * (grain - 0.5) + 0.18 * (knot - 0.5))

# --- bone
sl, W, H, (U, V) = region_grid("BONE")
pore = fbm(W, H, 50, 50, 4, SEED + 51)
crack = fbm(W, H, 14, 40, 4, SEED + 52)
cr = np.clip(crack - 0.58, 0, 1)
alb = np.array([0.70, 0.655, 0.545], np.float32)[None, None, :] * (0.80 + 0.34 * pore)[..., None]
alb *= (1.0 - 0.45 * cr)[..., None]
put("BONE", alb=np.clip(alb, 0, 1), rgh=np.clip(0.50 + 0.12 * pore, 0.45, 0.65),
    hgt=0.5 + 0.22 * (pore - 0.5) - 0.35 * cr)

# --- orb: near-black with a violet swirl
sl, W, H, (U, V) = region_grid("ORB")
swirl = fbm(W, H, 6, 6, 4, SEED + 61)
cy = np.clip(0.5 + 0.5 * swirl, 0, 1)
alb = np.array([0.045, 0.036, 0.070], np.float32)[None, None, :] + \
      cy[..., None] * np.array([0.105, 0.042, 0.205], np.float32)
put("ORB", alb=np.clip(alb, 0, 1), rgh=np.clip(0.20 + 0.16 * (1 - cy), 0.18, 0.40),
    hgt=0.5 + 0.10 * (swirl - 0.5))

# --- eye: deep red glow (also the emissive source)
sl, W, H, (U, V) = region_grid("EYE")
core = np.clip(1.0 - np.sqrt((U - 0.5 * W / ATLAS.regions["EYE"].density) ** 2 +
                             (V - 0.5 * H / ATLAS.regions["EYE"].density) ** 2) / 0.12, 0, 1)
core = np.clip(core, 0, 1) ** 0.8
mixv = fbm(W, H, 8, 8, 3, SEED + 71)
alb = np.array([0.16, 0.012, 0.010], np.float32)[None, None, :] + \
      core[..., None] * np.array([0.72, 0.075, 0.045], np.float32)
put("EYE", alb=np.clip(alb * (0.85 + 0.3 * mixv[..., None]), 0, 1),
    rgh=np.full((H, W), 0.34, np.float32), hgt=np.full((H, W), 0.5, np.float32))

# --- face: the shadow inside the hood
sl, W, H, (U, V) = region_grid("FACE")
shade = fbm(W, H, 10, 10, 3, SEED + 81)
alb = np.array([0.030, 0.026, 0.038], np.float32)[None, None, :] * (0.6 + 0.9 * shade)[..., None]
put("FACE", alb=np.clip(alb, 0, 1), rgh=np.full((H, W), 0.88, np.float32),
    hgt=np.full((H, W), 0.5, np.float32))


def make_image(name, arr, srgb):
    h, w = arr.shape[0], arr.shape[1]
    img = bpy.data.images.new(name, w, h, alpha=False)
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    px = np.ones((h, w, 4), np.float32)
    px[..., :3] = arr if arr.ndim == 3 else arr[..., None]
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img


IMG_ALB = make_image("commander_albedo", np.clip(ALB, 0, 1), True)
IMG_NRM = make_image("commander_normal", np.clip(normal_from_height(HGT, 2.6), 0, 1), False)
rough_small = RGH.reshape(ROUGH_RES, 2, ROUGH_RES, 2).mean(axis=(1, 3))
IMG_RGH = make_image("commander_rough", np.clip(rough_small, 0, 1), False)
print("[commander] textures: albedo %s sRGB, normal %s OpenGL(+Y), rough %s Non-Color"
      % (tuple(IMG_ALB.size), tuple(IMG_NRM.size), tuple(IMG_RGH.size)))


def make_material(name, base, rough, emit=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (base[0], base[1], base[2], 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = 0.0
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = IMG_ALB
    tex.location = (-760, 420)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    ntex = nt.nodes.new("ShaderNodeTexImage")
    ntex.image = IMG_NRM
    ntex.location = (-760, 120)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.location = (-420, 60)
    nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    rtex = nt.nodes.new("ShaderNodeTexImage")
    rtex.image = IMG_RGH
    rtex.location = (-760, -220)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.location = (-460, -220)
    nt.links.new(rtex.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Roughness"])
    if emit:
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 3.0
    mat.diffuse_color = (base[0], base[1], base[2], 1.0)
    mat.roughness = rough
    mat.metallic = 0.0
    return mat


MATERIALS = [
    make_material("Commander_Robe", (0.108, 0.104, 0.126), 0.84),
    make_material("Commander_Trim", (0.335, 0.228, 0.142), 0.62),
    make_material("Commander_Staff", (0.320, 0.205, 0.115), 0.60),
    make_material("Commander_Eyes", (0.55, 0.05, 0.04), 0.35, emit=True),
]
print("[commander] materials: %s" % [m.name for m in MATERIALS])

print("[commander] building LOD0 mesh")
MB0 = build_character(DETAIL["lod0"], ATLAS, 0)
print("[commander] building LOD1 mesh")
MB1 = build_character(DETAIL["lod1"], ATLAS, 1)
OBJ0 = mesh_from_mb(MB0, "Commander_Body")
OBJ1 = mesh_from_mb(MB1, "LOD1")
if os.environ.get("COMMANDER_DEBUG"):
    uvd_d = OBJ0.data.uv_layers["UVMap"].data
    us = [uvd_d[i].uv[0] for i in range(len(uvd_d))]
    vs = [uvd_d[i].uv[1] for i in range(len(uvd_d))]
    print("[commander] debug uv u %.4f..%.4f v %.4f..%.4f"
          % (min(us), max(us), min(vs), max(vs)))

# =====================================================================
# 8. armature
# =====================================================================
arm_data = bpy.data.armatures.new("CommanderArmature")
ARM = bpy.data.objects.new("CommanderArmature", arm_data)
bpy.context.collection.objects.link(ARM)
bpy.context.view_layer.objects.active = ARM
ARM.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for name, head, tail, parent, connected in BONES:
    eb = arm_data.edit_bones.new(name)
    eb.head = Vector(head)
    eb.tail = Vector(tail)
    eb.roll = 0.0
    if parent:
        eb.parent = arm_data.edit_bones[parent]
        eb.use_connect = bool(connected)
bpy.ops.object.mode_set(mode="OBJECT")
print("[commander] armature %s: %d bones" % (ARM.name, len(arm_data.bones)))
assert len(arm_data.bones) == 19, "bone count %d != 19" % len(arm_data.bones)

REST_Q = {b.name: b.matrix_local.to_quaternion() for b in arm_data.bones}


def spine_weights(z):
    ctrl = [("Hips", 0.94, 0.34), ("Spine", 1.30, 0.23), ("Chest", 1.58, 0.30),
            ("Neck", 1.77, 0.16), ("Head", 1.99, 0.36)]
    w = {}
    for name, c, wid in ctrl:
        k = max(0.0, 1.0 - abs(z - c) / wid)
        if k > 0.0:
            w[name] = k * k
    return w


ROBE_DIR = {"Robe_F": (0.0, -1.0), "Robe_B": (0.0, 1.0), "Robe_L": (1.0, 0.0), "Robe_R": (-1.0, 0.0)}


def robe_quadrant(p):
    d = Vector((p.x, p.y))
    if d.length < 1e-5:
        d = Vector((0.0, -1.0))
    d.normalize()
    w = {}
    for name, (dx, dy) in ROBE_DIR.items():
        c = max(0.0, d.x * dx + d.y * dy)
        if c > 0.0:
            w[name] = c ** 1.6
    return w


def torso_weights(p):
    rk = sstep((1.06 - p.z) / 0.34)
    w = {}
    for k, v in spine_weights(p.z).items():
        w[k] = w.get(k, 0.0) + v * (1.0 - rk)
    if rk > 0.0:
        for k, v in robe_quadrant(p).items():
            w[k] = w.get(k, 0.0) + v * rk
    return w


def polyline_param(path, p):
    best_d, best_l = 1e9, 0.0
    acc = 0.0
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ab = b - a
        L = ab.length
        t = 0.0 if L < 1e-9 else max(0.0, min(1.0, (p - a).dot(ab) / (L * L)))
        q = a + ab * t
        d = (p - q).length
        if d < best_d:
            best_d, best_l = d, acc + t * L
        acc += L
    return best_l, best_d


def arm_weights(side, p):
    path = ARM_L if side == "L" else ARM_R
    hand = HAND_L if side == "L" else HAND_R
    l_elbow = (path[1] - path[0]).length
    l_wrist = l_elbow + (path[2] - path[1]).length
    l_end = l_wrist + (hand[1] - hand[0]).length
    d, _ = polyline_param(path + [hand[1]], p)
    w = {}
    up = 1.0 - sstep((d - (l_elbow - 0.085)) / 0.17)
    lo = 1.0 - up
    hnd = sstep((d - (l_wrist - 0.055)) / 0.11)
    lw = lo * (1.0 - hnd)
    sh = (1.0 - sstep(d / 0.17)) * 0.55
    w["Shoulder_%s" % side] = sh
    w["UpperArm_%s" % side] = up * (1.0 - sh) + lw * 0.0
    w["LowerArm_%s" % side] = lw
    w["Hand_%s" % side] = lo * hnd
    w["UpperArm_%s" % side] += (1.0 - sstep(d / 0.30)) * 0.0
    return w


def vertex_weights(tag, p):
    if tag == "staff":
        return {"Staff": 1.0}
    if tag == "eyes" or tag == "face":
        return {"Head": 1.0}
    if tag.startswith("hand_"):
        side = tag[-1]
        d, _ = polyline_param([HAND_L[0], HAND_L[1]] if side == "L" else [HAND_R[0], HAND_R[1]], p)
        k = sstep((d - 0.030) / 0.070)
        return {"Hand_%s" % side: 0.55 + 0.45 * k, "LowerArm_%s" % side: 0.45 * (1.0 - k)}
    if tag.startswith("arm_"):
        return arm_weights(tag[-1], p)
    if tag.startswith("boot_"):
        w = robe_quadrant(p)
        return w if w else {"Robe_L": 1.0}
    return torso_weights(p)


def apply_weights(ob, mb):
    groups = {name: ob.vertex_groups.new(name=name) for name in BONE_NAMES}
    stats = {}
    for i, v in enumerate(ob.data.vertices):
        w = vertex_weights(mb.tag[i] if i < len(mb.tag) else "robe", Vector(v.co))
        w = {k: val for k, val in w.items() if val > 1e-4}
        s = sum(w.values())
        if s <= 1e-6:
            w = {"Hips": 1.0}
            s = 1.0
        for k in sorted(w):
            groups[k].add([i], w[k] / s, "REPLACE")
        stats[len(w)] = stats.get(len(w), 0) + 1
    mod = ob.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = ARM
    ob.parent = ARM
    print("[commander] %s weights: influence histogram %s" % (ob.name, dict(sorted(stats.items()))))


# mb.tag is indexed by the pre-merge vertex order; rebuild the tag lookup from
# the merged mesh by nearest-original-vertex mapping.
def tag_map_after_merge(ob, mb):
    src = np.array([[v.x, v.y, v.z] for v in mb.v], np.float32)
    dst = np.array([[v.co.x, v.co.y, v.co.z] for v in ob.data.vertices], np.float32)
    out = []
    for row in dst:
        d = np.sum((src - row[None, :]) ** 2, axis=1)
        out.append(mb.tag[int(np.argmin(d))])
    return out


MB0.tag = tag_map_after_merge(OBJ0, MB0)
MB1.tag = tag_map_after_merge(OBJ1, MB1)
apply_weights(OBJ0, MB0)
apply_weights(OBJ1, MB1)

# =====================================================================
# 9. animation
# =====================================================================
AXIS = {"x": Vector((1.0, 0.0, 0.0)), "y": Vector((0.0, 1.0, 0.0)), "z": Vector((0.0, 0.0, 1.0))}
LOC_BONES = ("Root", "Hips")


def q_delta(spec):
    q = Quaternion((1.0, 0.0, 0.0, 0.0))
    for a in ("x", "y", "z"):
        deg = spec.get(a, 0.0)
        if abs(deg) > 1e-9:
            q = Quaternion(AXIS[a], math.radians(deg)) @ q
    return q


def apply_pose(pose):
    for pb in ARM.pose.bones:
        spec = pose.get(pb.name, {})
        B = REST_Q[pb.name]
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (B.inverted() @ q_delta(spec) @ B).normalized()
        loc = spec.get("loc")
        if loc is not None:
            pb.location = B.inverted() @ Vector(loc)
        else:
            pb.location = Vector((0.0, 0.0, 0.0))
        sc = spec.get("scale", 1.0)
        pb.scale = Vector((sc, sc, sc))
    # "_staff_aim": solve the Staff bone so the weapon points at a target world
    # direction (armature space = game space: -Y forward, +Z up). The staff is
    # the boss's readable weapon, so its direction is authored declaratively
    # instead of being an accumulation of arm rotations.
    aim = pose.get("_staff_aim")
    if aim is not None:
        bpy.context.view_layer.update()
        staff = ARM.pose.bones["Staff"]
        if isinstance(aim, str):
            # two-handed grips: point the shaft at (or away from) the left hand,
            # which is where the second hand has to be
            hand = ARM.pose.bones["Hand_L"].tail
            head = staff.head
            aim = (hand - head) if aim == "toward_hand_l" else (head - hand)
        parent = staff.parent
        off = parent.bone.matrix_local.inverted() @ staff.bone.matrix_local
        M = (parent.matrix @ off).to_3x3()
        U = (M.inverted() @ Vector(aim)).normalized()
        staff.rotation_quaternion = Vector((0.0, 1.0, 0.0)).rotation_difference(U)


def key_all(frame):
    for pb in ARM.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        if pb.name in LOC_BONES:
            pb.keyframe_insert("location", frame=frame)
        if pb.name in ROBE_BONES:
            pb.keyframe_insert("scale", frame=frame)


def action_fcurves(act):
    """Blender 5.x actions are layered; older ones expose .fcurves directly."""
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def author(name, keys, loop):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    if hasattr(act, "use_cyclic"):
        act.use_cyclic = bool(loop)
    ARM.animation_data_create()
    ARM.animation_data.action = act
    for f, pose in keys:
        apply_pose(pose)
        key_all(f)
    for fc in action_fcurves(act):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO_CLAMPED"
            kp.handle_right_type = "AUTO_CLAMPED"
    ARM.animation_data.action = None
    for pb in ARM.pose.bones:
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    print("[commander] clip %-30s frames %d-%d (%s)" % (name, keys[0][0], keys[-1][0],
          "loop" if loop else "one-shot"))
    return act


def merge(*poses):
    out = {}
    for p in poses:
        for k, v in p.items():
            if k.startswith("_") or not isinstance(v, dict):
                out[k] = v
            elif k in out:
                out[k] = dict(out[k])
                out[k].update(v)
            else:
                out[k] = dict(v)
    return out


def scaled(pose, k):
    out = {}
    for name, spec in pose.items():
        if name.startswith("_") or not isinstance(spec, dict):
            out[name] = spec
            continue
        out[name] = {}
        for key, val in spec.items():
            if key in ("x", "y", "z"):
                out[name][key] = val * k
            else:
                out[name][key] = val
    return out


BASE = {
    "Spine": {"x": 1.5}, "Chest": {"x": 1.0}, "Neck": {"x": 3.0}, "Head": {"x": 2.0},
    "UpperArm_L": {"y": -4.0}, "UpperArm_R": {"y": 4.0},
    "LowerArm_L": {"x": -9.0}, "LowerArm_R": {"x": -7.0},
    "Hand_R": {"x": -6.0}, "Staff": {"x": 5.0},
}

STANCE = merge(BASE, {"Hips": {"loc": (0.0, 0.0, 0.0)}})


def pose_idle(k, sway):
    return merge(STANCE, {
        "Hips": {"loc": (0.0, 0.0, -0.012 * k), "y": 1.2 * sway},
        "Spine": {"x": 1.5 - 1.2 * k, "y": -1.0 * sway},
        "Chest": {"x": 1.0 - 1.6 * k, "z": 1.4 * sway},
        "Neck": {"x": 3.0 + 1.0 * k, "z": -1.2 * sway},
        "Head": {"x": 2.0 + 1.4 * k, "z": -1.6 * sway, "y": 1.0 * sway},
        "UpperArm_L": {"y": -4.0 - 1.4 * k, "x": -1.5 * k},
        "UpperArm_R": {"y": 4.0 + 1.2 * k, "x": -2.0 * k},
        "LowerArm_R": {"x": -7.0 - 2.0 * k},
        "Hand_R": {"x": -6.0 + 1.6 * k, "z": 1.2 * sway},
        "Staff": {"x": 5.0 - 2.2 * k, "y": 1.4 * sway},
        "Robe_F": {"x": -1.6 * k}, "Robe_B": {"x": 1.4 * k},
        "Robe_L": {"y": -1.8 * k - 1.2 * sway}, "Robe_R": {"y": 1.8 * k - 1.2 * sway},
        "Cape": {},
    })


print("[commander] authoring clips")
# ---------------- Idle: 2.2 s loop (0..53 = 53 frames = 2.208 s)
author("Idle", [
    (0,  pose_idle(0.0, 0.0)),
    (13, pose_idle(1.0, 0.6)),
    (26, pose_idle(0.15, 1.0)),
    (39, pose_idle(0.85, -0.5)),
    (53, pose_idle(0.0, 0.0)),
], True)


def pose_walk(step, bob, cane, swing):
    """step: +1 left panel forward, -1 right panel forward."""
    p = merge(STANCE, {
        "Hips": {"loc": (0.012 * step, 0.0, bob), "z": -3.0 * step, "y": 2.0 * step},
        "Spine": {"z": 2.0 * step, "x": 2.4},
        "Chest": {"z": 3.2 * step, "x": 1.6},
        "Neck": {"z": -2.0 * step, "x": 3.0},
        "Head": {"z": -2.4 * step, "x": 2.4},
        "UpperArm_L": {"x": -7.0 * step, "y": -4.0},
        "LowerArm_L": {"x": -9.0 - 4.0 * max(0.0, -step)},
        "UpperArm_R": {"x": 3.0 * swing, "y": 4.0},
        "LowerArm_R": {"x": -7.0 - 3.0 * cane},
        "Hand_R": {"x": -6.0 + 4.0 * cane},
        "Staff": {"x": 5.0 - 7.0 * cane, "z": 2.0 * step},
        "Robe_L": {"x": -15.0 * step, "y": -3.0 - 3.0 * max(0.0, step)},
        "Robe_R": {"x": 15.0 * step, "y": 3.0 + 3.0 * max(0.0, -step)},
        "Robe_F": {"x": -6.0 * step, "y": 1.5 * step},
        "Robe_B": {"x": 5.0 * step, "y": 1.5 * step},
    })
    if cane > 0.6:
        p["_staff_aim"] = (0.05, -0.16, 0.985)     # cane planted under the hand
    return p


# ---------------- Walk: 1.1 s loop (0..27 = 27 frames = 1.125 s)
author("Walk", [
    (0,  pose_walk(1.0, -0.004, 1.0, 0.0)),
    (7,  pose_walk(0.15, 0.018, 0.15, 0.4)),
    (13, pose_walk(-1.0, -0.010, 0.0, 1.0)),
    (20, pose_walk(-0.15, 0.016, 0.5, 0.5)),
    (27, pose_walk(1.0, -0.004, 1.0, 0.0)),
], True)


def pose_dir_aim(k, aim=(0.06, -0.985, 0.16)):
    """Staff levelled forward at the facing direction, energy gathering."""
    p = merge(STANCE, {
        "Hips": {"loc": (0.0, -0.035 * k, -0.030 * k), "x": 6.0 * k},
        "Spine": {"x": 7.0 * k, "z": -3.0 * k},
        "Chest": {"x": 6.0 * k, "z": -6.0 * k},
        "Neck": {"x": 1.0 * k, "z": 4.0 * k},
        "Head": {"x": -3.0 * k, "z": 5.0 * k},
        "Shoulder_R": {"z": -6.0 * k},
        "UpperArm_R": {"x": -62.0 * k, "y": 12.0 * k, "z": -10.0 * k},
        "LowerArm_R": {"x": -34.0 * k, "y": 0.0},
        "Hand_R": {"x": 26.0 * k},
        "Shoulder_L": {"z": 8.0 * k},
        "UpperArm_L": {"x": -54.0 * k, "y": 34.0 * k, "z": 16.0 * k},
        "LowerArm_L": {"x": -42.0 * k, "y": -10.0 * k},
        "Hand_L": {"x": 20.0 * k, "z": -10.0 * k},
        "Robe_F": {"x": 8.0 * k}, "Robe_B": {"x": -9.0 * k},
        "Robe_L": {"x": -6.0 * k}, "Robe_R": {"x": 6.0 * k},
    })
    if k > 0.5:
        p["_staff_aim"] = aim
    return p


# ---------------- Cast_Directional_Anticipation: 0.9 s (0..22 = 22 = 0.917 s)
author("Cast_Directional_Anticipation", [
    (0,  STANCE),
    (6,  merge(BASE, {k: v for k, v in scaled(pose_dir_aim(1.0), 0.35).items()
                      if k != "_staff_aim"}, {"_staff_aim": (0.20, -0.62, 0.76)})),
    (14, pose_dir_aim(1.0)),
    (22, merge(pose_dir_aim(1.0), {
        "Hips": {"loc": (0.0, -0.045, -0.036), "x": 8.0},
        "Spine": {"x": 9.0}, "Chest": {"x": 8.0},
        "Robe_F": {"x": 12.0}, "Robe_B": {"x": -13.0}})),
], False)

# ---------------- Cast_Directional_Attack: 0.7 s (0..17 = 17 = 0.708 s)
author("Cast_Directional_Attack", [
    (0,  merge(pose_dir_aim(1.0), {
        "Hips": {"loc": (0.0, -0.045, -0.036), "x": 8.0},
        "_staff_aim": (0.06, -0.955, 0.29)})),
    (3,  merge(pose_dir_aim(1.0), {
        "Hips": {"loc": (0.0, 0.030, -0.020), "x": 2.0},
        "Spine": {"x": 3.0}, "Chest": {"x": 1.0},
        "UpperArm_R": {"x": -46.0, "y": 18.0, "z": -16.0},
        "_staff_aim": (0.10, -0.86, 0.50),
        "Robe_F": {"x": -8.0}, "Robe_B": {"x": 10.0}})),
    (6,  merge(pose_dir_aim(1.0), {
        "Hips": {"loc": (0.0, -0.085, -0.045), "x": 13.0},
        "Spine": {"x": 13.0}, "Chest": {"x": 13.0}, "Neck": {"x": -4.0}, "Head": {"x": -6.0},
        "UpperArm_R": {"x": -74.0, "y": 6.0, "z": -4.0},
        "LowerArm_R": {"x": -20.0},
        "Hand_R": {"x": 34.0},
        "_staff_aim": (0.04, -0.975, 0.22),
        "UpperArm_L": {"x": -66.0, "y": 30.0, "z": 12.0},
        "Robe_F": {"x": 22.0}, "Robe_B": {"x": -24.0},
        "Robe_L": {"x": -12.0}, "Robe_R": {"x": 12.0}})),
    (9,  merge(pose_dir_aim(1.0), {
        "Hips": {"loc": (0.0, -0.020, -0.028), "x": 7.0},
        "Spine": {"x": 6.0}, "Chest": {"x": 5.0},
        "UpperArm_R": {"x": -58.0, "y": 12.0, "z": -12.0},
        "_staff_aim": (0.06, -0.97, 0.24),
        "Robe_F": {"x": 8.0}, "Robe_B": {"x": -10.0}})),
    (17, STANCE),
], False)


def pose_area_lift(k):
    p = merge(STANCE, {
        "Hips": {"loc": (0.0, 0.010 * k, -0.020 * k), "x": -4.0 * k},
        "Spine": {"x": -6.0 * k}, "Chest": {"x": -7.0 * k},
        "Neck": {"x": 4.0 * k}, "Head": {"x": 8.0 * k},
        "Shoulder_R": {"z": -10.0 * k}, "Shoulder_L": {"z": 10.0 * k},
        "UpperArm_R": {"x": -118.0 * k, "y": 30.0 * k, "z": 6.0 * k},
        "LowerArm_R": {"x": -54.0 * k},
        "Hand_R": {"x": 26.0 * k},
        "UpperArm_L": {"x": -128.0 * k, "y": 40.0 * k, "z": 12.0 * k},
        "LowerArm_L": {"x": -46.0 * k, "y": -18.0 * k},
        "Hand_L": {"x": 18.0 * k, "z": -12.0 * k},
        "Robe_F": {"x": -6.0 * k}, "Robe_B": {"x": 4.0 * k},
        "Robe_L": {"y": -10.0 * k}, "Robe_R": {"y": 10.0 * k},
    })
    if k > 0.5:
        p["_staff_aim"] = "toward_hand_l"          # both hands on the shaft, overhead
    return p


# ---------------- Cast_Area_Anticipation: 1.2 s (0..29 = 29 = 1.208 s)
author("Cast_Area_Anticipation", [
    (0,  STANCE),
    (9,  scaled(pose_area_lift(1.0), 0.45)),
    (19, pose_area_lift(1.0)),
    (29, merge(pose_area_lift(1.0), {
        "Hips": {"loc": (0.0, 0.018, -0.028), "x": -7.0},
        "Spine": {"x": -9.0}, "Chest": {"x": -10.0},
        "Staff": {"x": 10.0, "y": 78.0},
        "Robe_F": {"x": -14.0}, "Robe_B": {"x": 12.0},
        "Robe_L": {"y": -16.0}, "Robe_R": {"y": 16.0}})),
], False)


def pose_area_slam(k):
    p = merge(STANCE, {
        "Hips": {"loc": (0.0, -0.020 * k, -0.115 * k), "x": 15.0 * k},
        "Spine": {"x": 15.0 * k}, "Chest": {"x": 12.0 * k},
        "Neck": {"x": -6.0 * k}, "Head": {"x": 4.0 * k},
        "Shoulder_R": {"z": 4.0 * k}, "Shoulder_L": {"z": -4.0 * k},
        "UpperArm_R": {"x": -30.0 * k, "y": 12.0 * k, "z": -10.0 * k},
        "LowerArm_R": {"x": -14.0 * k},
        "Hand_R": {"x": 10.0 * k},
        "UpperArm_L": {"x": -26.0 * k, "y": 26.0 * k, "z": 8.0 * k},
        "LowerArm_L": {"x": -34.0 * k},
        "Hand_L": {"x": 14.0 * k},
        "Robe_F": {"x": 16.0 * k}, "Robe_B": {"x": -14.0 * k},
        "Robe_L": {"y": 14.0 * k}, "Robe_R": {"y": -14.0 * k},
    })
    if k > 0.5:
        p["_staff_aim"] = (0.06, -0.420, 0.905)    # butt driven into the ground in front
    return p


# ---------------- Cast_Area_Attack: 0.8 s (0..19 = 19 = 0.792 s)
author("Cast_Area_Attack", [
    (0,  merge(pose_area_lift(1.0), {"_staff_aim": "toward_hand_l"})),
    (4,  merge(scaled(pose_area_lift(1.0), 0.55), {
        "Hips": {"loc": (0.0, 0.0, -0.020), "x": 8.0},
        "Spine": {"x": 6.0}, "Chest": {"x": 2.0},
        "UpperArm_R": {"x": -50.0, "y": 20.0, "z": 0.0},
        "_staff_aim": (0.55, -0.55, 0.63)})),
    (6,  pose_area_slam(1.0)),
    (10, merge(pose_area_slam(1.0), {
        "Hips": {"loc": (0.0, -0.024, -0.135), "x": 19.0},
        "Spine": {"x": 19.0}, "Chest": {"x": 15.0},
        "_staff_aim": (0.06, -0.500, 0.864),
        "Robe_F": {"x": 24.0}, "Robe_B": {"x": -20.0}})),
    (19, STANCE),
], False)


def pose_hit(k):
    return merge(STANCE, {
        "Hips": {"loc": (0.0, 0.075 * k, -0.030 * k), "x": -12.0 * k},
        "Spine": {"x": -16.0 * k}, "Chest": {"x": -14.0 * k},
        "Neck": {"x": -14.0 * k}, "Head": {"x": -12.0 * k, "z": 6.0 * k},
        "UpperArm_L": {"x": 26.0 * k, "y": -18.0 * k, "z": -10.0 * k},
        "LowerArm_L": {"x": -30.0 * k},
        "UpperArm_R": {"x": 22.0 * k, "y": 16.0 * k},
        "LowerArm_R": {"x": -26.0 * k},
        "Hand_R": {"x": -14.0 * k},
        "_staff_aim": (0.05, 0.34, 0.94),
        "Robe_F": {"x": -18.0 * k}, "Robe_B": {"x": 16.0 * k},
        "Robe_L": {"y": -8.0 * k}, "Robe_R": {"y": 8.0 * k},
    })


# ---------------- Hit: 0.5 s (0..12 = 12 = 0.5 s)
author("Hit", [
    (0,  STANCE),
    (3,  pose_hit(1.0)),
    (6,  pose_hit(0.45)),
    (9,  pose_hit(-0.18)),
    (12, STANCE),
], False)


def pose_stun(k, sway):
    return merge(STANCE, {
        "Hips": {"loc": (0.010 * sway, 0.030, -0.140), "x": 12.0, "z": 2.5 * sway},
        "Spine": {"x": 22.0, "z": -3.0 * sway},
        "Chest": {"x": 16.0, "z": -2.0 * sway},
        "Neck": {"x": 22.0, "z": 4.0 * sway},
        "Head": {"x": 14.0, "z": 7.0 * sway, "y": 4.0 * sway},
        "UpperArm_L": {"x": 14.0 + 6.0 * k, "y": -14.0, "z": -6.0},
        "LowerArm_L": {"x": -34.0 - 8.0 * k},
        "UpperArm_R": {"x": 18.0 + 7.0 * k, "y": 12.0},
        "LowerArm_R": {"x": -16.0 - 6.0 * k},
        "Hand_R": {"x": -18.0},
        "_staff_aim": (-0.140, -0.330, 0.933),
        "Robe_F": {"x": 10.0, "scale": 0.90}, "Robe_B": {"x": -8.0, "scale": 0.90},
        "Robe_L": {"y": -3.0 - 2.0 * sway, "scale": 0.90},
        "Robe_R": {"y": 3.0 - 2.0 * sway, "scale": 0.90},
    })


# ---------------- Stun: 1.3 s loop (0..31 = 31 = 1.292 s)
author("Stun", [
    (0,  pose_stun(0.0, 1.0)),
    (8,  pose_stun(1.0, 0.45)),
    (16, pose_stun(0.3, -1.0)),
    (24, pose_stun(0.9, -0.35)),
    (31, pose_stun(0.0, 1.0)),
], True)


def pose_death(k):
    """k: 0 = standing, 1 = fully collapsed."""
    hips_z = -0.640 * k
    lean = 74.0 * k
    return merge(STANCE, {
        "Hips": {"loc": (0.0, 0.045 * k, hips_z), "x": lean * 0.45},
        "Spine": {"x": lean * 0.42},
        "Chest": {"x": lean * 0.34},
        "Neck": {"x": lean * 0.20},
        "Head": {"x": lean * 0.10},
        "Shoulder_L": {"z": 6.0 * k}, "Shoulder_R": {"z": -6.0 * k},
        "UpperArm_L": {"x": 34.0 * k, "y": -26.0 * k},
        "LowerArm_L": {"x": -44.0 * k},
        "UpperArm_R": {"x": 26.0 * k, "y": 22.0 * k},
        "LowerArm_R": {"x": -30.0 * k},
        "Hand_R": {"x": -22.0 * k},
        "Staff": {"x": -58.0 * k, "z": -18.0 * k},
        "Robe_F": {"x": -lean * 0.92, "y": -16.0 * k, "scale": 1.0 - 0.30 * k},
        "Robe_B": {"x": -lean * 0.86, "y": 22.0 * k, "scale": 1.0 - 0.34 * k},
        "Robe_L": {"x": -lean * 0.88, "y": -30.0 * k, "scale": 1.0 - 0.32 * k},
        "Robe_R": {"x": -lean * 0.90, "y": 30.0 * k, "scale": 1.0 - 0.32 * k},
    })


# ---------------- Death: 2.0 s one-shot (0..48 = 48 = 2.0 s)
author("Death", [
    (0,  STANCE),
    (5,  pose_hit(0.85)),
    (13, merge(pose_death(0.28), {"Spine": {"x": 16.0}, "Head": {"x": -6.0},
                                  "Hips": {"loc": (0.0, 0.030, -0.180), "x": 10.0}})),
    (24, pose_death(0.62)),
    (34, pose_death(0.92)),
    (41, merge(pose_death(1.0), {"_staff_aim": (0.26, 0.83, 0.49)})),
    (48, merge(pose_death(1.0), {"_staff_aim": (0.30, 0.86, 0.42),
                                 "Neck": {"x": 16.0}, "Head": {"x": 10.0},
                                 "Robe_F": {"x": -70.0, "y": -18.0, "scale": 0.70},
                                 "Robe_B": {"x": -66.0, "y": 24.0, "scale": 0.66},
                                 "Robe_L": {"x": -67.0, "y": -32.0, "scale": 0.68},
                                 "Robe_R": {"x": -68.0, "y": 32.0, "scale": 0.68}})),
], False)

CLIPS = ["Idle", "Walk", "Cast_Directional_Anticipation", "Cast_Directional_Attack",
         "Cast_Area_Anticipation", "Cast_Area_Attack", "Hit", "Stun", "Death"]
LOOPS = {"Idle", "Walk", "Stun"}
for name in CLIPS:
    if bpy.data.actions.get(name) is None:
        raise SystemExit("missing action %s" % name)
ARM.animation_data_create()
ARM.animation_data.action = None

# =====================================================================
# 10. self-validation
# =====================================================================
deps = bpy.context.evaluated_depsgraph_get()
tris0 = sum(len(p.vertices) - 2 for p in OBJ0.data.polygons)
tris1 = sum(len(p.vertices) - 2 for p in OBJ1.data.polygons)
for m in (OBJ0, OBJ1):
    m.data.calc_loop_triangles()

verts = OBJ0.data.vertices
min_y = min(v.co.z for v in verts)
max_y = max(v.co.z for v in verts)
body_min_y = min(v.co.z for v in verts if MB0.tag[v.index] != "staff")
staff_v = [v.co for v in verts if MB0.tag[v.index] == "staff"]
staff_len = (max(v.z for v in staff_v) - min(v.z for v in staff_v))
# crown = tallest point of the character itself (the staff orb stands taller)
crown = max(v.co.z for v in verts if MB0.tag[v.index] != "staff")
height = crown - min(v.co.z for v in verts if MB0.tag[v.index] != "staff")

# UV overlap check. Every island is unique texel space by construction, so this
# is a guard against a mapping mistake, not a packer result: each triangle is
# inset by >= 1.6 cells before rasterising, so neighbours that merely share an
# edge cannot register as an overlap, while two islands that really share texel
# space still do.
uvd = OBJ0.data.uv_layers["UVMap"].data
CELLN = 1024
CELL = 1.0 / CELLN
cover = np.zeros((CELLN, CELLN), np.int8)
last_tag = {}
overlap_by_tag = {}
area_sum = 0.0
tiny_area = 0.0
degen = 0
DEBUG_UV = bool(os.environ.get("COMMANDER_DEBUG"))
for poly in OBJ0.data.polygons:
    pts = [np.array(uvd[l].uv, np.float32) for l in range(poly.loop_start, poly.loop_start + poly.loop_total)]
    c = sum(pts) / len(pts)
    shoelace = 0.0
    per = 0.0
    for t in range(len(pts)):
        a, b = pts[t], pts[(t + 1) % len(pts)]
        shoelace += a[0] * b[1] - b[0] * a[1]
        per += float(np.linalg.norm(b - a))
    area = 0.5 * abs(shoelace)
    area_sum += area
    r_in = (2.0 * area / per) if per > 0 else 0.0
    if r_in * CELLN < 2.5:            # too small to rasterise without aliasing
        degen += 1
        tiny_area += area
        continue
    s = 1.0 - 1.6 * CELL / r_in
    ftag = MB0.tag[poly.vertices[0]]
    pts = [c + (p - c) * s for p in pts]
    for t in range(1, len(pts) - 1):
        tri = [pts[0], pts[t], pts[t + 1]]
        x0 = max(0, int(min(p[0] for p in tri) * CELLN))
        x1 = min(CELLN - 1, int(max(p[0] for p in tri) * CELLN) + 1)
        y0 = max(0, int(min(p[1] for p in tri) * CELLN))
        y1 = min(CELLN - 1, int(max(p[1] for p in tri) * CELLN) + 1)
        for gy in range(y0, y1 + 1):
            for gx in range(x0, x1 + 1):
                px, py = (gx + 0.5) * CELL, (gy + 0.5) * CELL
                d = []
                for i in range(3):
                    a = tri[i]
                    b = tri[(i + 1) % 3]
                    e = b - a
                    w = np.array([px, py], np.float32) - a
                    d.append(e[0] * w[1] - e[1] * w[0])
                if (d[0] >= 0.0 and d[1] >= 0.0 and d[2] >= 0.0) or \
                   (d[0] <= 0.0 and d[1] <= 0.0 and d[2] <= 0.0):
                    cover[gy, gx] += 1
                    if DEBUG_UV:
                        prev = last_tag.get((gy, gx))
                        if prev is not None and prev != poly.index:
                            key = (min(prev, poly.index), max(prev, poly.index))
                            overlap_by_tag[key] = overlap_by_tag.get(key, 0) + 1
                        last_tag[(gy, gx)] = poly.index
covered = int((cover > 0).sum())
overlap = int((cover > 1).sum())
mirrored = 0
print("[commander] uv area=%.3f of atlas, covered cells=%d, overlap cells=%d (%.4f%%), "
      "untestable tiny tris=%d (%.2f%% of uv area), mirrored islands=%d"
      % (area_sum, covered, overlap, 100.0 * overlap / max(1, covered), degen,
         100.0 * tiny_area / max(1e-9, area_sum), mirrored))
if DEBUG_UV:
    uvd_d = OBJ0.data.uv_layers["UVMap"].data
    for k, v in sorted(overlap_by_tag.items(), key=lambda kv: -kv[1])[:6]:
        print("[commander] debug overlap polys %s : %d cells" % (k, v))
        for pi in k:
            poly = OBJ0.data.polygons[pi]
            print("[dbg]   poly %d tag %s uv %s" % (pi, MB0.tag[poly.vertices[0]],
                  [tuple(round(c, 4) for c in uvd_d[l].uv) for l in range(poly.loop_start, poly.loop_start + poly.loop_total)]))

# Death settles: head bone height must drop
act = bpy.data.actions["Death"]
ARM.animation_data.action = act
scene.frame_set(0)
bpy.context.view_layer.update()
head_top = ARM.pose.bones["Head"].head.z
scene.frame_set(48)
bpy.context.view_layer.update()
head_bot = ARM.pose.bones["Head"].head.z
ARM.animation_data.action = None

# staff orientation per combat key frame (game space: forward = -Y here = +Z in
# Godot, so "forward" means the staff's tip points at -Y)
def staff_report(clip, frame, want):
    ARM.animation_data.action = bpy.data.actions[clip]
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    pb = ARM.pose.bones["Staff"]
    v = pb.matrix.col[1].to_3d().normalized()
    fwd = -v.y
    up = v.z
    side = v.x
    hand_l = ARM.pose.bones["Hand_L"].tail
    head = pb.head
    along = (hand_l - head).dot(v)
    gap = ((hand_l - head) - v * along).length
    grip_gap = gap if -0.96 <= along <= 1.40 else (hand_l - head).length
    print("[commander] pose %-30s f%-3d staff_dir=(%.2f,%.2f,%.2f) fwd=%.2f up=%.2f "
          "elev=%+.0fdeg butt_z=%.2f left_hand_off_shaft=%.2f (%s)"
          % (clip, frame, v.x, v.y, v.z, fwd, up, math.degrees(math.asin(max(-1, min(1, up)))),
             ARM.pose.bones["Staff"].head.z - 0.96 * up, grip_gap, want))
    ARM.animation_data.action = None


print("[commander] staff check (butt_z = where the staff butt lands)")
staff_report("Cast_Directional_Anticipation", 22, "want fwd high, elev near 0")
staff_report("Cast_Directional_Attack", 6, "want fwd high, elev near 0")
staff_report("Cast_Area_Anticipation", 29, "want overhead: |side| high, up ~0")
staff_report("Cast_Area_Attack", 6, "want butt planted: up ~1, butt_z ~0")
staff_report("Stun", 0, "want butt dragging: butt_z ~0")
staff_report("Hit", 3, "want upright, slight back lean")
staff_report("Idle", 0, "want upright")
staff_report("Death", 48, "want fallen over")
staff_report("Walk", 0, "want cane plant: butt_z ~0")

CLIP_RANGES = {}
for name in CLIPS:
    a = bpy.data.actions[name]
    fr = a.frame_range
    CLIP_RANGES[name] = (int(fr[0]), int(fr[1]))
    print("[commander] clip frames %-30s %d-%d  loop=%d  dur=%.3fs"
          % (name, int(fr[0]), int(fr[1]), 1 if name in LOOPS else 0,
             (int(fr[1]) - int(fr[0])) / float(FPS)))

print("[commander] tris=%d lod1_tris=%d bones=%d clips=%d height_m=%.3f min_y=%.3f staff_len_m=%.3f uv_mirrored=%d"
      % (tris0, tris1, len(arm_data.bones), len(bpy.data.actions), height, min_y, staff_len, mirrored))
print("[commander] bbox_with_staff_m=%.3f crown_m=%.3f lowest_robe_or_boot_y=%.3f head_drop_death=%.3f->%.3f"
      % (max_y - min_y, crown, body_min_y, head_top, head_bot))

fail = []
if len(arm_data.bones) != 19:
    fail.append("bone count %d" % len(arm_data.bones))
for name in CLIPS:
    if bpy.data.actions.get(name) is None:
        fail.append("missing clip %s" % name)
if len(bpy.data.actions) != 9:
    fail.append("action count %d != 9" % len(bpy.data.actions))
if tris0 > 50000:
    fail.append("tris %d > 50000" % tris0)
if abs(min_y) > 0.02:
    fail.append("min_y %.4f outside +-0.02" % min_y)
if not (2.05 <= height <= 2.35):
    fail.append("height %.3f outside 2.05-2.35" % height)
if head_bot > head_top - 0.30:
    fail.append("death did not lower the head (%.3f -> %.3f)" % (head_top, head_bot))
if overlap > 0.002 * max(1, covered):
    fail.append("uv overlap %.3f%% of covered texels" % (100.0 * overlap / max(1, covered)))
if fail:
    print("[commander] VALIDATION FAILED: %s" % "; ".join(fail))
    raise SystemExit(1)

# =====================================================================
# 11. export
# =====================================================================
for ob in bpy.data.objects:
    ob.select_set(False)
kwargs = dict(filepath=OUT, export_format="GLB", export_yup=True, export_apply=False,
              export_animations=True, export_animation_mode="ACTIONS",
              export_skins=True, export_materials="EXPORT", export_cameras=False,
              export_lights=False, export_extras=False, export_frame_range=False)
try:
    bpy.ops.export_scene.gltf(**kwargs)
except TypeError as exc:
    print("[commander] export kwargs rejected (%s); retrying minimal" % exc)
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True,
                              export_apply=False, export_animations=True,
                              export_animation_mode="ACTIONS")
print("[commander] exported %s (%d bytes)" % (OUT, os.path.getsize(OUT)))


# =====================================================================
# 12. read the GLB back
# =====================================================================
def png_stats(raw, w, h, ch=3):
    """Unfilter an 8-bit PNG body and return the per-channel means."""
    stride = w * ch
    prev = bytearray(stride)
    total = np.zeros(3, np.float64)
    n = 0
    for y in range(h):
        ft = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            x = line[i]
            if ft == 1:
                x = (x + a) & 255
            elif ft == 2:
                x = (x + b) & 255
            elif ft == 3:
                x = (x + ((a + b) >> 1)) & 255
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                x = (x + pr) & 255
            line[i] = x
        prev = line
        if y % max(1, h // 48) == 0:
            arr = np.frombuffer(bytes(line), np.uint8).reshape(-1, ch).astype(np.float64)
            total += arr[:, :3].mean(axis=0)
            n += 1
    return total / max(1, n) / 255.0


def read_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, length = struct.unpack("<III", data[:12])
    assert magic == 0x46546C67, "not a GLB"
    off = 12
    js, bin_chunk = None, b""
    while off + 8 <= length:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        chunk = data[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = chunk
        off += 8 + clen + ((4 - clen % 4) % 4 if clen % 4 else 0)
    return js, bin_chunk, data


try:
    G, GBIN, GRAW = read_glb(OUT)
    anims = [a.get("name", "?") for a in G.get("animations", [])]
    imgs = G.get("images", [])
    skin_joints = [len(s.get("joints", [])) for s in G.get("skins", [])]
    nodes = [n.get("name", "") for n in G.get("nodes", [])]
    print("[commander] glb: nodes=%d meshes=%d materials=%d images=%d skins=%d joints=%s"
          % (len(G.get("nodes", [])), len(G.get("meshes", [])), len(G.get("materials", [])),
             len(imgs), len(G.get("skins", [])), skin_joints))
    print("[commander] glb node names: %s" % nodes)
    print("[commander] glb animations (%d): %s" % (len(anims), sorted(anims)))
    for m in G.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        print("[commander] glb material %-18s metallic=%s rough=%s baseTex=%s mrTex=%s normTex=%s emis=%s"
              % (m.get("name", "?"), pbr.get("metallicFactor", 1.0), pbr.get("roughnessFactor", 1.0),
                 "baseColorTexture" in pbr, "metallicRoughnessTexture" in pbr,
                 "normalTexture" in m, m.get("emissiveFactor")))
    for i, im in enumerate(imgs):
        bv = G["bufferViews"][im["bufferView"]]
        print("[commander] glb image[%d] name=%s mime=%s bytes=%d"
              % (i, im.get("name", "?"), im.get("mimeType", "?"), bv["byteLength"]))
    # decode one embedded PNG and sample it, proving the atlas survived packing
    for i, im in enumerate(imgs):
        if im.get("name", "").startswith("commander_albedo"):
            bv = G["bufferViews"][im["bufferView"]]
            o = bv.get("byteOffset", 0)
            blob = GBIN[o:o + bv["byteLength"]]
            j = 8
            idat = b""
            w = h = 0
            while j < len(blob):
                ln = struct.unpack(">I", blob[j:j + 4])[0]
                typ = blob[j + 4:j + 8]
                if typ == b"IHDR":
                    w, h, bd, ct = struct.unpack(">IIBB", blob[j + 8:j + 18])
                    chans = 4 if ct == 6 else 3
                if typ == b"IDAT":
                    idat += blob[j + 8:j + 8 + ln]
                j += 12 + ln
            print("[commander] glb albedo png %dx%d mean_rgb=%s"
                  % (w, h, [round(v, 3) for v in png_stats(zlib.decompress(idat), w, h, chans)]))
            break
    for i, im in enumerate(imgs):
        if im.get("name", "").startswith("commander_rough"):
            bv = G["bufferViews"][im["bufferView"]]
            o = bv.get("byteOffset", 0)
            blob = GBIN[o:o + bv["byteLength"]]
            j = 8
            idat = b""
            while j < len(blob):
                ln = struct.unpack(">I", blob[j:j + 4])[0]
                typ = blob[j + 4:j + 8]
                if typ == b"IHDR":
                    w, h, bd, ct = struct.unpack(">IIBB", blob[j + 8:j + 18])
                    chans = 4 if ct == 6 else 3
                if typ == b"IDAT":
                    idat += blob[j + 8:j + 8 + ln]
                j += 12 + ln
            st = png_stats(zlib.decompress(idat), w, h, chans)
            print("[commander] glb metallicRoughness png %dx%d ch=%d mean(R,G,B)=%s "
                  "(G = roughness, B = metallic)"
                  % (w, h, chans, [round(v, 3) for v in st]))
            break
except Exception as exc:  # never let a readback problem lose the build
    print("[commander] glb readback failed: %r" % (exc,))

# =====================================================================
# 13. pose renders (best effort)
# =====================================================================
RENDER_POSES = [("idle", "Idle", 26), ("directional", "Cast_Directional_Attack", 7),
                ("area", "Cast_Area_Attack", 6), ("dead", "Death", 47)]
# extra inspection views at review distance (same lighting, closer camera)
RENDER_CLOSEUPS = [("closeup-front", "Idle", 0, (-1.30, -3.60, 1.30)),
                   ("closeup-side", "Idle", 0, (-4.00, -0.55, 1.35)),
                   ("closeup-head", "Cast_Area_Anticipation", 29, (-0.95, -1.85, 1.95)),
                   ("pose-walk7", "Walk", 7, (-4.00, -0.55, 1.35)),
                   ("pose-walk13", "Walk", 13, (-4.00, -0.55, 1.35)),
                   ("pose-aim", "Cast_Directional_Attack", 6, (-1.60, -3.50, 1.30)),
                   ("pose-death48", "Death", 48, (-2.60, -2.60, 1.05)),
                   ("pose-stun", "Stun", 16, (-1.90, -3.30, 1.25)),
                   ("pose-hit", "Hit", 3, (-3.60, -1.20, 1.35))]


def render_poses():
    os.makedirs(RENDER_DIR, exist_ok=True)
    cam_data = bpy.data.cameras.new("CommanderCam")
    cam_data.angle = math.radians(65.0)
    cam_data.sensor_fit = "HORIZONTAL"
    cam = bpy.data.objects.new("CommanderCam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    cam.location = Vector((-6.20, -6.20, 1.70))
    tgt = Vector((0.0, 0.0, 1.05))
    cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(6.0)
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(58.0), 0.0, math.radians(-135.0))
    fill_data = bpy.data.lights.new("Fill", type="AREA")
    fill_data.energy = 900.0
    fill_data.size = 8.0
    fill = bpy.data.objects.new("Fill", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = Vector((5.0, -4.0, 2.4))
    fill.rotation_euler = (Vector((0, 0, 1.2)) - fill.location).to_track_quat("-Z", "Y").to_euler()
    rim_data = bpy.data.lights.new("Rim", type="AREA")
    rim_data.energy = 600.0
    rim_data.size = 3.0
    rim = bpy.data.objects.new("Rim", rim_data)
    bpy.context.collection.objects.link(rim)
    rim.location = Vector((-3.4, 3.6, 2.6))
    rim.rotation_euler = (Vector((0, 0, 1.3)) - rim.location).to_track_quat("-Z", "Y").to_euler()
    world = bpy.data.worlds.new("CommanderWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.17, 0.19, 0.23, 1.0)
    scene.world = world
    scene.render.resolution_x = 800
    scene.render.resolution_y = 600
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except Exception as exc:
        print("[commander] view transform not set: %r" % (exc,))
    engines = ["BLENDER_EEVEE", "BLENDER_WORKBENCH"]
    chosen = None
    for eng in engines:
        try:
            scene.render.engine = eng
            chosen = eng
            break
        except Exception as exc:
            print("[commander] engine %s unavailable (%s)" % (eng, exc))
    if chosen is None:
        raise RuntimeError("no render engine")
    ARM.animation_data.action = None
    for label, clip, frame, pos in ([("%s" % l, c, f, None) for (l, c, f) in RENDER_POSES] + RENDER_CLOSEUPS):
        ARM.animation_data.action = bpy.data.actions[clip]
        scene.frame_set(frame)
        if pos is not None:
            cam.location = Vector(pos)
            cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        scene.render.filepath = os.path.join(RENDER_DIR, "commander-%s.png" % label)
        bpy.ops.render.render(write_still=True)
        print("[commander] render %s (%s @ %d, %s)" % (scene.render.filepath, clip, frame, chosen))
    ARM.animation_data.action = None


try:
    render_poses()
except Exception as exc:
    print("[commander] renders skipped: %r" % (exc,))

print("[commander] done")
