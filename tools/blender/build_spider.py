"""Author the creature pass acromantula (creature asset tasks).

Not a pile of spheres and sticks.  The body is one continuous loft (sloped
carapace -> narrow pedicel -> heart-shaped abdomen) with a compact sternum,
chelicerae with fangs, pedipalps, eight eyes in the classic two-row
arrangement and three spinnerets.  Eight legs are built independently (a
mirrored leg is a mirrored *geometry* build, never a negative scale): each is a
five-segment articulated chain -- coxa, femur, patella, tibia, tarsus -- whose
femur rises into a knee, whose tibia descends, and whose flattened tarsus
rests on the ground in the bind pose.

Authoring convention: Blender is Z-up / -Y
forward, and the glTF exporter maps Blender -Y -> glTF +Z, so a face authored
towards -Y lands at +Z in Godot.  Up stays +Y in Godot.  Blender +X is the
creature's right, so the `LegR*` chains are built on +X.

Rig: 48 bones (8 core + 8 legs x 5 segments), armature-deformed with analytic
chain-parameter weights that blend across every joint -- not rigid parenting.

Textures are generated in this script from numpy value-noise / Worley fields
and packed into the GLB: `acromantula_albedo` (1024, sRGB),
`acromantula_normal` (1024, Non-Color, OpenGL +Y) and `acromantula_rough`
(512, Non-Color).  The UV atlas is a 4x4 grid of cells with a gutter; every
island sits in its own cell except the four leg pairs, where the left leg
reuses the right leg's island (the deliberate mirror).

Run:  blender -b --factory-startup --python build_spider.py -- <out.glb> [--render <dir>]
"""
import bpy
import bmesh
import math
import os
import sys
import struct
import json
from mathutils import Vector, Quaternion

import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if "--out" in argv:
    _out_arg = argv[argv.index("--out") + 1]
elif argv and not argv[0].startswith("--"):
    _out_arg = argv[0]
else:
    print("[spider] FAIL: no output path; pass -- --out <out.glb>")
    raise SystemExit(1)
# Blender resolves a relative render path against the (absent) blend directory,
# so every output path is made absolute here.
OUT = os.path.abspath(_out_arg)
if not OUT.lower().endswith(".glb"):
    OUT += ".glb"
RENDER_DIR = os.path.abspath(argv[argv.index("--render") + 1]) if "--render" in argv else None

FPS = 24
SEED = 20261005

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

# =============================================================== geometry plan
#
# metres, Z-up, head towards -Y.
#   body length : pedipalp tip y=-0.836 .. spinneret tip y=+0.866   1.70 m
#   leg span    : widest tarsus tips |x| = 1.120 (+ foot radius)    ~2.31 m
#   body top    : carapace crown z=0.646, abdomen crown z=0.620
#   knees       : 0.590 .. 0.625 centre line, bulged crown ~0.69
#
# Mesh and bones are shifted together on Z at the end so the lowest LOD0
# vertex sits exactly on z = 0 (bind-pose ground contact).

# (y, half_width, z_top, z_bottom, z_mid_fraction)
BODY_STATIONS = [
    # carapace: fused head + thorax, sloped crown, compact sternum
    (-0.600, 0.058, 0.462, 0.332, 0.56),
    (-0.578, 0.110, 0.516, 0.300, 0.51),
    (-0.548, 0.157, 0.558, 0.278, 0.48),
    (-0.505, 0.197, 0.596, 0.258, 0.46),
    (-0.455, 0.224, 0.620, 0.240, 0.44),
    (-0.400, 0.240, 0.636, 0.228, 0.43),
    (-0.342, 0.246, 0.646, 0.220, 0.43),
    (-0.286, 0.245, 0.646, 0.216, 0.43),
    (-0.232, 0.237, 0.640, 0.214, 0.43),
    (-0.181, 0.224, 0.628, 0.214, 0.44),
    (-0.132, 0.207, 0.610, 0.216, 0.45),
    (-0.087, 0.186, 0.588, 0.220, 0.46),
    (-0.048, 0.162, 0.562, 0.226, 0.48),
    (-0.018, 0.134, 0.534, 0.240, 0.52),
    # pedicel: the narrow waist
    (0.004, 0.103, 0.500, 0.272, 0.56),
    (0.026, 0.092, 0.484, 0.288, 0.58),
    # opisthosoma / abdomen, heart-shaped in plan
    (0.048, 0.114, 0.492, 0.280, 0.55),
    (0.082, 0.170, 0.530, 0.256, 0.50),
    (0.132, 0.235, 0.574, 0.238, 0.47),
    (0.192, 0.289, 0.602, 0.226, 0.45),
    (0.258, 0.327, 0.618, 0.220, 0.44),
    (0.328, 0.343, 0.620, 0.219, 0.44),
    (0.398, 0.337, 0.613, 0.221, 0.44),
    (0.468, 0.319, 0.599, 0.226, 0.45),
    (0.538, 0.288, 0.577, 0.235, 0.46),
    (0.608, 0.246, 0.545, 0.250, 0.48),
    (0.672, 0.196, 0.503, 0.272, 0.50),
    (0.727, 0.138, 0.451, 0.300, 0.54),
    (0.766, 0.080, 0.396, 0.334, 0.58),
    (0.790, 0.034, 0.358, 0.352, 0.62),
]
BODY_RING_POINTS = 24

# (leg index, sternum y, tarsus tip x, tarsus tip y, knee z, gait swing deg)
LEG_DEF = [
    (1, -0.435, 0.860, -1.230, 0.586, 13.0),
    (2, -0.315, 1.120, -0.520, 0.560, 11.0),
    (3, -0.195, 1.120, 0.420, 0.570, 11.0),
    (4, -0.075, 0.880, 1.150, 0.596, 13.0),
]
LEG_HFRAC = [0.00, 0.12, 0.42, 0.58, 0.82, 1.00]
LEG_SEG_NAMES = ["Coxa", "Femur", "Patella", "Tibia", "Tarsus"]
LEG_JOINT_R = [0.081, 0.073, 0.065, 0.060, 0.042, 0.029]
CROWN_POW = 0.62          # flattens the carapace crown into a shield
BELLY_POW = 2.2           # flattens the sternum / underside
LEG_RING_POINTS = 14
LEG_RINGS_PER_SEG = 6
ANKLE_Z = 0.088
TARSUS_TIP_Z = 0.024
COXA_BASE_Z = 0.315

# (row, x, y, radius) -- posterior row first (larger), then the anterior row
EYE_ROWS = [
    ("posterior", 0.050, -0.503, 0.026),
    ("posterior", 0.097, -0.486, 0.019),
    ("anterior", 0.036, -0.552, 0.015),
    ("anterior", 0.076, -0.539, 0.017),
]

# ============================================================== UV atlas plan
UV_GRID = 4
UV_MARGIN = 0.014
UV_RECTS = {}
UV_PLACEMENTS = []


def cell(col, row):
    s = 1.0 / UV_GRID
    return (col * s + UV_MARGIN, row * s + UV_MARGIN, (col + 1) * s - UV_MARGIN, (row + 1) * s - UV_MARGIN)


def place_rect(name, rect):
    assert name not in UV_RECTS, name
    UV_RECTS[name] = rect
    UV_PLACEMENTS.append(name)
    return rect


place_rect("carapace", cell(0, 0))
place_rect("abdomen", cell(1, 0))
place_rect("pedipalp_R", cell(2, 0))
place_rect("pedipalp_L", cell(3, 0))
place_rect("leg_R1", cell(0, 1))
place_rect("leg_R2", cell(1, 1))
place_rect("leg_R3", cell(2, 1))
place_rect("leg_R4", cell(3, 1))
place_rect("chelicera_R", cell(0, 2))
place_rect("chelicera_L", cell(1, 2))
place_rect("eye", cell(2, 2))
place_rect("membrane", cell(3, 2))
place_rect("spinneret", cell(0, 3))

_eye_cell = UV_RECTS["eye"]
EYE_SUB = []
for _r in range(4):
    for _c in range(4):
        _w = (_eye_cell[2] - _eye_cell[0]) / 4.0
        _h = (_eye_cell[3] - _eye_cell[1]) / 4.0
        EYE_SUB.append((_eye_cell[0] + _c * _w + 0.0015, _eye_cell[1] + _r * _h + 0.0015,
                        _eye_cell[0] + (_c + 1) * _w - 0.0015, _eye_cell[1] + (_r + 1) * _h - 0.0015))

# The four leg pairs are the single deliberate UV mirror: leg_Ln maps into
# leg_Rn's rectangle, so the left leg's texture reads mirrored across the body.
MIRRORED_RECTS = ["leg_R1", "leg_R2", "leg_R3", "leg_R4"]
UV_ISLANDS = len(UV_PLACEMENTS) + len(EYE_SUB)

# ============================================================ small maths bits


def sstep(a, b, x):
    t = (x - a) / (b - a)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def uv_in(rect, u, v):
    return (rect[0] + u * (rect[2] - rect[0]), rect[1] + v * (rect[3] - rect[1]))


def _interp_station(y):
    tab = BODY_STATIONS
    if y <= tab[0][0]:
        return tab[0][1:]
    if y >= tab[-1][0]:
        return tab[-1][1:]
    for i in range(len(tab) - 1):
        y0, y1 = tab[i][0], tab[i + 1][0]
        if y0 <= y <= y1:
            t = (y - y0) / (y1 - y0)
            return tuple(lerp(tab[i][k], tab[i + 1][k], t) for k in range(1, 5))
    return tab[-1][1:]


def body_section(y):
    w, zt, zb, zmf = _interp_station(y)
    return w, zt, zb, zb + zmf * (zt - zb)


def surface_x(y, z):
    """Half-width of the body silhouette at height z (0 when outside)."""
    w, zt, zb, zm = body_section(y)
    if z > zt or z < zb or w <= 1e-6:
        return 0.0
    if z >= zm:
        k = ((z - zm) / max(1e-6, zt - zm)) ** (1.0 / 0.75)
    else:
        k = ((zm - z) / max(1e-6, zm - zb)) ** (1.0 / 2.2)
    k = clamp01(k)
    return w * math.sqrt(max(0.0, 1.0 - k * k))


def surface_z(y, x):
    """Height of the upper carapace surface at (x, y)."""
    w, zt, zb, zm = body_section(y)
    if w <= 1e-6:
        return zm
    c = clamp01(abs(x) / w)
    s = math.sqrt(max(0.0, 1.0 - c * c))
    return zm + (zt - zm) * (s ** CROWN_POW)


def body_ring(y, n):
    w, zt, zb, zm = body_section(y)
    pts = []
    for i in range(n + 1):
        a = 2.0 * math.pi * (i % n) / n
        c, s = math.cos(a), math.sin(a)
        x = c * w
        if s >= 0.0:
            z = zm + (zt - zm) * (s ** CROWN_POW)
        else:
            z = zm + (zm - zb) * ((-s) ** BELLY_POW)
        pts.append((Vector((x, y, z)), i / float(n)))
    return pts


def surface_normal(y, x):
    d = 0.006
    nx = -(surface_z(y, x + d) - surface_z(y, x - d)) / (2.0 * d)
    ny = -(surface_z(y + d, x) - surface_z(y - d, x)) / (2.0 * d)
    return Vector((nx, ny, 1.0)).normalized()


def frame_for(fwd):
    """A right-handed (side, up) frame perpendicular to a segment direction."""
    up = Vector((0.0, 0.0, 1.0))
    up = up - fwd * fwd.dot(up)
    if up.length < 1e-6:
        up = Vector((1.0, 0.0, 0.0)) - fwd * fwd.dot(Vector((1.0, 0.0, 0.0)))
    up.normalize()
    return up.cross(fwd).normalized(), up


def tube_ring(center, fwd, r, n, kx=1.0, ky=1.0):
    sd, up = frame_for(fwd)
    pts = []
    for i in range(n + 1):
        a = 2.0 * math.pi * (i % n) / n
        pts.append((center + sd * (math.cos(a) * r * kx) + up * (math.sin(a) * r * ky), i / float(n)))
    return pts


def mirror_pts(pts):
    """Mirror a ring across x and reverse its order so the winding stays outward."""
    n = len(pts) - 1
    return [(Vector((-pts[n - i][0].x, pts[n - i][0].y, pts[n - i][0].z)), i / float(n))
            for i in range(n + 1)]


# ================================================================= mesh builder


class MeshBuilder:
    """Verts/faces/UVs/material slots with per-vertex skin weights and per-face
    region tags.  Geometry is emitted as a polygon soup and welded by position
    afterwards; UVs are per-loop so welding never merges a UV seam."""

    def __init__(self, name):
        self.name = name
        self.verts = []
        self.faces = []
        self.uvs = []
        self.mat_faces = []
        self.weights = []
        self.face_regions = []
        self._w = {"Body": 1.0}
        self._region = "body"

    def skin(self, weights, region):
        self._w = weights
        self._region = region

    def add_quad(self, a, b, c, d, uv, mat):
        base = len(self.verts)
        self.verts.extend([a, b, c, d])
        self.uvs.extend(uv)
        self.weights.extend([dict(self._w)] * 4)
        self.faces.append((base, base + 1, base + 2, base + 3))
        self.mat_faces.append(mat)
        self.face_regions.append(self._region)

    def add_tri(self, a, b, c, uv, mat):
        base = len(self.verts)
        self.verts.extend([a, b, c])
        self.uvs.extend(uv)
        self.weights.extend([dict(self._w)] * 3)
        self.faces.append((base, base + 1, base + 2))
        self.mat_faces.append(mat)
        self.face_regions.append(self._region)

    def loft(self, rings, mat, rect, v0=0.0, v1=1.0):
        n = len(rings[0]) - 1
        total = len(rings) - 1
        for k in range(total):
            A, B = rings[k], rings[k + 1]
            va = lerp(v0, v1, k / float(total))
            vb = lerp(v0, v1, (k + 1) / float(total))
            for i in range(n):
                j = i + 1
                self.add_quad(A[i][0], A[j][0], B[j][0], B[i][0],
                              [uv_in(rect, A[i][1], va), uv_in(rect, A[j][1], va),
                               uv_in(rect, B[j][1], vb), uv_in(rect, B[i][1], vb)], mat)

    def cap(self, ring, center, mat, rect, v, flip=False):
        """Close a lofted tube.  The cap is a tiny disc, so its whole fan is
        collapsed onto one v line inside the island: it costs no meaningful
        texture area and can never overlap the tube band beside it."""
        n = len(ring) - 1
        uc, vc = uv_in(rect, 0.5, v)
        for i in range(n):
            j = i + 1
            u0, _ = uv_in(rect, ring[i][1], v)
            u1, _ = uv_in(rect, ring[j][1], v)
            if flip:
                self.add_tri(center, ring[j][0], ring[i][0], [(uc, vc), (u1, vc), (u0, vc)], mat)
            else:
                self.add_tri(center, ring[i][0], ring[j][0], [(uc, vc), (u0, vc), (u1, vc)], mat)

    def weld(self, eps=1.0e-5):
        """Merge coincident vertices (keeping per-loop UVs) and average weights."""
        key_of = {}
        remap = []
        verts = []
        weights = []
        for i, v in enumerate(self.verts):
            k = (round(v.x / eps), round(v.y / eps), round(v.z / eps))
            j = key_of.get(k)
            if j is None:
                j = len(verts)
                key_of[k] = j
                verts.append(v)
                weights.append(dict(self.weights[i]))
            else:
                w = weights[j]
                for bone, val in self.weights[i].items():
                    w[bone] = w.get(bone, 0.0) + val
            remap.append(j)
        for w in weights:
            tot = sum(w.values())
            if tot > 1e-9:
                for b in list(w.keys()):
                    w[b] /= tot
        faces, mats, regions = [], [], []
        loop_uvs = []
        pos = 0
        for f, mi, reg in zip(self.faces, self.mat_faces, self.face_regions):
            chunk = self.uvs[pos:pos + len(f)]
            pos += len(f)
            nf = tuple(remap[i] for i in f)
            if len(set(nf)) < len(f):
                continue
            faces.append(nf)
            mats.append(mi)
            regions.append(reg)
            loop_uvs.extend(chunk)
        self.verts = verts
        self.weights = weights
        self.faces = faces
        self.uvs = loop_uvs
        self.mat_faces = mats
        self.face_regions = regions
        return len(verts)

    def to_object(self, name=None):
        me = bpy.data.meshes.new(name or self.name)
        me.from_pydata([tuple(v) for v in self.verts], [], self.faces)
        me.update()
        uvl = me.uv_layers.new(name="UVMap")
        assert len(me.loops) == len(self.uvs), (len(me.loops), len(self.uvs))
        for i, uv in enumerate(self.uvs):
            uvl.data[i].uv = uv
        for poly, mi in zip(me.polygons, self.mat_faces):
            poly.material_index = mi
        me.update()
        ob = bpy.data.objects.new(name or self.name, me)
        bpy.context.collection.objects.link(ob)
        return ob


# =================================================================== textures


def _lattice(n, seed):
    return np.random.RandomState(seed).random_sample((n, n)).astype(np.float32)


def fbm2(size, base_freq, octaves, seed, gain=0.5):
    a = (np.arange(size, dtype=np.float32) + 0.5) / size
    total = np.zeros((size, size), dtype=np.float32)
    amp, norm, freq = 1.0, 0.0, base_freq
    for o in range(octaves):
        g = _lattice(freq, seed + o * 1013)
        x = a * freq
        i0 = np.floor(x).astype(np.int32) % freq
        fx = x - np.floor(x)
        fx = fx * fx * (3.0 - 2.0 * fx)
        i1 = (i0 + 1) % freq
        c00 = g[np.ix_(i0, i0)]
        c01 = g[np.ix_(i0, i1)]
        c10 = g[np.ix_(i1, i0)]
        c11 = g[np.ix_(i1, i1)]
        row0 = c00 * (1.0 - fx)[None, :] + c01 * fx[None, :]
        row1 = c10 * (1.0 - fx)[None, :] + c11 * fx[None, :]
        total += (row0 * (1.0 - fx)[:, None] + row1 * fx[:, None]) * amp
        norm += amp
        amp *= gain
        freq *= 2
    return total / norm


def worley2(size, cells, seed):
    r = np.random.RandomState(seed)
    jx = r.random_sample((cells, cells)).astype(np.float32)
    jy = r.random_sample((cells, cells)).astype(np.float32)
    a = (np.arange(size, dtype=np.float32) + 0.5) / size * cells
    i0 = np.floor(a).astype(np.int32)
    f1 = np.full((size, size), 1e9, np.float32)
    f2 = np.full((size, size), 1e9, np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cy = (i0[:, None] + dy) % cells
            cx = (i0[None, :] + dx) % cells
            gx = cx + jx[cy, cx]
            gy = cy + jy[cy, cx]
            d = (gx - a[None, :]) ** 2 + (gy - a[:, None]) ** 2
            m = d < f1
            f2 = np.where(m, f1, np.minimum(f2, d))
            f1 = np.where(m, d, f1)
    return np.sqrt(f1), np.sqrt(f2)


def region_index(size):
    u = (np.arange(size, dtype=np.float32) + 0.5) / size
    reg = np.full((size, size), -1, dtype=np.int32)
    for idx, name in enumerate(UV_PLACEMENTS):
        r = UV_RECTS[name]
        m = ((u[None, :] >= r[0]) & (u[None, :] < r[2])) & ((u[:, None] >= r[1]) & (u[:, None] < r[3]))
        reg[m] = idx
    return reg, {n: i for i, n in enumerate(UV_PLACEMENTS)}


def _dilate(col, mask, iters=10):
    col = col.copy()
    mask = mask.copy()
    for _ in range(iters):
        if mask.all():
            break
        acc = np.zeros_like(col)
        cnt = np.zeros(mask.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            acc += np.roll(col, (dy, dx), axis=(0, 1)) * np.roll(mask, (dy, dx), axis=(0, 1))[..., None]
            cnt += np.roll(mask, (dy, dx), axis=(0, 1))
        fill = (~mask) & (cnt > 0.5)
        safe = np.maximum(cnt, 1.0)[..., None]
        col[fill] = acc[fill] / safe[fill]
        mask = mask | fill
    return col


def build_textures():
    print("[spider] generating textures")
    S = 1024
    fine = fbm2(S, 64, 4, SEED + 11)
    blotch = fbm2(S, 9, 5, SEED + 23)
    ridge = fbm2(S, 3, 3, SEED + 53)
    f1, f2 = worley2(S, 6, SEED + 41)
    edge = np.clip((f2 - f1) / 0.30, 0.0, 1.0)          # 0 on a plate seam, 1 inside

    u = (np.arange(S, dtype=np.float32) + 0.5) / S
    reg, R = region_index(S)

    def isin(name):
        return reg == R[name]

    # --- base chitin: dark brown-grey with plate-to-plate variation ---------
    t = np.clip((0.30 + 0.70 * edge) * (0.80 + 0.40 * blotch), 0.0, 1.0) ** 0.9
    dark = np.array([0.066, 0.059, 0.053], np.float32)
    warm = np.array([0.176, 0.148, 0.121], np.float32)
    col = dark[None, None, :] + (warm - dark)[None, None, :] * t[..., None]
    col += ((fine - 0.5) * 0.030)[..., None]
    col += ((blotch - 0.5) * 0.040)[..., None]
    col *= (0.62 + 0.38 * edge)[..., None]        # dark joint gaps between plates
    height = 0.42 * fine + 0.20 * blotch - 0.80 * (1.0 - edge) ** 2

    # --- carapace: a darker shield with a faint radial rise -----------------
    m = isin("carapace")
    col[m] *= 0.86
    col[m] += ((ridge[m] - 0.5) * 0.030)[:, None]
    height[m] += 0.10 * ridge[m]
    crect = UV_RECTS["carapace"]
    ccu = (u[None, :] - crect[0]) / (crect[2] - crect[0])
    ccv = (u[:, None] - crect[1]) / (crect[3] - crect[1])
    fov = np.exp(-(((ccu - 0.25) / 0.055) ** 2 + ((ccv - 0.20) / 0.075) ** 2)) * m
    height -= 0.85 * fov
    col *= (1.0 - 0.55 * fov)[..., None]

    # --- abdomen: lighter heart marking + chevrons --------------------------
    m = isin("abdomen")
    rect = UV_RECTS["abdomen"]
    cu = (u[None, :] - rect[0]) / (rect[2] - rect[0])
    cv = (u[:, None] - rect[1]) / (rect[3] - rect[1])
    dc = (cu - 0.25) / 0.15
    mark = np.exp(-(((dc) ** 2 + ((cv - 0.16) / 0.13) ** 2)))
    for cy, wdt in ((0.42, 0.30), (0.60, 0.24), (0.78, 0.17)):
        mark = np.maximum(mark, np.exp(-((cv - cy) / 0.035) ** 2) * np.exp(-(np.abs(dc) / wdt) ** 2) * 0.85)
    mark = np.clip(mark, 0.0, 1.0) * m
    lightm = np.array([0.300, 0.232, 0.150], np.float32)
    col = col * (1.0 - 0.85 * mark[..., None]) + lightm[None, None, :] * 0.85 * mark[..., None]
    height -= 0.12 * mark

    # --- legs: darker joint bands at the real joints, dorsal ridge ----------
    for name in MIRRORED_RECTS:
        m = isin(name)
        rect = UV_RECTS[name]
        cv = (u[:, None] - rect[1]) / (rect[3] - rect[1])
        band = np.zeros((S, S), np.float32)
        for j in (0.12, 0.42, 0.58, 0.82):
            band = np.maximum(band, np.exp(-((cv - j) / 0.024) ** 2))
        band = np.clip(band, 0.0, 1.0) * m
        col = col * (1.0 - 0.62 * band[..., None])
        height -= 0.30 * band
        cu = (u[None, :] - rect[0]) / (rect[2] - rect[0])
        rg = np.exp(-(((cu - 0.25) / 0.10) ** 2)) * m
        col += (0.045 * rg)[..., None]
        height += 0.16 * rg

    # --- chelicerae, with reddish-brown fang tips ---------------------------
    for name in ("chelicera_R", "chelicera_L"):
        m = isin(name)
        rect = UV_RECTS[name]
        cv = (u[:, None] - rect[1]) / (rect[3] - rect[1])
        fang = (np.clip((cv - 0.42) / 0.40, 0.0, 1.0) ** 1.4) * m
        col = col * (1.0 - fang[..., None]) + np.array([0.330, 0.092, 0.052], np.float32)[None, None, :] * fang[..., None]
        height += 0.10 * fang

    # --- membrane / underside: lighter and soft ----------------------------
    m = isin("membrane")
    mem = np.array([0.222, 0.190, 0.158], np.float32)
    col = np.where(m[..., None], col * 0.35 + mem[None, None, :] * (0.55 + 0.45 * blotch)[..., None], col)
    height = np.where(m, 0.30 + 0.10 * fine, height)

    # --- spinnerets, pedipalps, eyes ---------------------------------------
    m = isin("spinneret")
    col = np.where(m[..., None], col * 0.75 + np.array([0.155, 0.128, 0.104], np.float32)[None, None, :] * 0.25, col)
    for name in ("pedipalp_R", "pedipalp_L"):
        m = isin(name)
        col = np.where(m[..., None], col * 0.94, col)
    m = isin("eye")
    col = np.where(m[..., None], np.array([0.045, 0.028, 0.016], np.float32)[None, None, :], col)
    height = np.where(m, 0.05, height)

    albedo = _dilate(np.clip(col, 0.0, 1.0), reg >= 0)

    # --- normal map: OpenGL (+Y) tangent space from the height field --------
    gy, gx = np.gradient(height.astype(np.float32))
    nx, ny = -gx * 9.0, -gy * 9.0
    nz = np.ones_like(nx)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.empty((S, S, 3), np.float32)
    normal[..., 0] = nx * inv * 0.5 + 0.5
    normal[..., 1] = ny * inv * 0.5 + 0.5
    normal[..., 2] = nz * inv * 0.5 + 0.5

    # --- roughness 512: plates 0.25-0.40, joints/membranes 0.60-0.75 --------
    S2 = 512
    fine2 = fbm2(S2, 32, 3, SEED + 11)
    g1, g2 = worley2(S2, 6, SEED + 41)
    edge2 = np.clip((g2 - g1) / 0.30, 0.0, 1.0)
    reg2, R2 = region_index(S2)
    u2 = (np.arange(S2, dtype=np.float32) + 0.5) / S2
    rough = 0.245 + 0.135 * edge2 + 0.055 * fine2
    for name in MIRRORED_RECTS:
        m = reg2 == R2[name]
        rect = UV_RECTS[name]
        cv = (u2[:, None] - rect[1]) / (rect[3] - rect[1])
        band = np.zeros((S2, S2), np.float32)
        for j in (0.12, 0.42, 0.58, 0.82):
            band = np.maximum(band, np.exp(-((cv - j) / 0.024) ** 2))
        rough = np.where(m, np.maximum(rough, 0.62 + 0.10 * band), rough)
    rough = np.where(reg2 == R2["membrane"], 0.68 + 0.07 * fine2, rough)
    rough = np.where(reg2 == R2["eye"], 0.15 + 0.05 * fine2, rough)
    for name in ("chelicera_R", "chelicera_L"):
        rough = np.where(reg2 == R2[name], 0.30 + 0.12 * fine2, rough)
    rough = np.clip(rough, 0.0, 1.0)

    def make_img(name, size, rgb, color_space=None):
        img = bpy.data.images.new(name, size, size, alpha=False)
        if color_space:
            img.colorspace_settings.name = color_space
        buf = np.empty((size, size, 4), dtype=np.float32)
        buf[..., 0] = rgb[..., 0]
        buf[..., 1] = rgb[..., 1]
        buf[..., 2] = rgb[..., 2]
        buf[..., 3] = 1.0
        img.pixels.foreach_set(np.ascontiguousarray(buf.ravel()))
        img.file_format = "PNG"
        img.pack()
        return img

    return (make_img("acromantula_albedo", S, albedo),
            make_img("acromantula_normal", S, normal, "Non-Color"),
            make_img("acromantula_rough", S2, np.repeat(rough[..., None], 3, axis=2), "Non-Color"))


# ================================================================== body parts
mb = MeshBuilder("Acromantula")
MAT_CHITIN, MAT_MEMBRANE, MAT_EYE, MAT_FANG = 0, 1, 2, 3


def skin_body(y):
    wh = sstep(-0.36, -0.54, y)
    wa = sstep(-0.012, 0.105, y)
    wb = max(0.0, 1.0 - wh - wa)
    tot = wh + wa + wb
    return {"Head": wh / tot, "Body": wb / tot, "Abdomen": wa / tot}


def build_body():
    n = BODY_RING_POINTS
    rect, abd = UV_RECTS["carapace"], UV_RECTS["abdomen"]
    ys = [s[0] for s in BODY_STATIONS]
    rings = [body_ring(y, n) for y in ys]
    total = len(rings) - 1
    for k in range(total):
        A, B = rings[k], rings[k + 1]
        va = k / float(total)
        vb = (k + 1) / float(total)
        mid_y = 0.5 * (ys[k] + ys[k + 1])
        r = rect if mid_y < 0.0 else abd
        mb.skin(skin_body(mid_y), "carapace" if mid_y < 0.0 else "abdomen")
        for i in range(n):
            j = i + 1
            ventral = math.sin(2.0 * math.pi * (i + 0.5) / n) < -0.30
            mb.add_quad(A[i][0], A[j][0], B[j][0], B[i][0],
                        [uv_in(r, A[i][1], va), uv_in(r, A[j][1], va),
                         uv_in(r, B[j][1], vb), uv_in(r, B[i][1], vb)],
                        MAT_MEMBRANE if ventral else MAT_CHITIN)
    mb.skin(skin_body(ys[0]), "carapace")
    mb.cap(rings[0], Vector((0.0, ys[0] - 0.014, 0.395)), MAT_CHITIN, rect, 0.0, flip=True)
    mb.skin(skin_body(ys[-1]), "abdomen")
    mb.cap(rings[-1], Vector((0.0, ys[-1] + 0.022, 0.355)), MAT_CHITIN, abd, 1.0, flip=False)


def build_spinnerets():
    rect = UV_RECTS["spinneret"]
    specs = [
        (Vector((0.000, 0.760, 0.302)), Vector((0.000, 0.850, 0.289)), 0.036),
        (Vector((0.058, 0.746, 0.300)), Vector((0.072, 0.832, 0.293)), 0.030),
        (Vector((-0.058, 0.746, 0.300)), Vector((-0.072, 0.832, 0.293)), 0.030),
    ]
    for si, (base, tip, r0) in enumerate(specs):
        mb.skin({"Abdomen": 1.0}, "spinneret")
        fwd = (tip - base).normalized()
        rings = []
        for k in range(6):
            t = k / 5.0
            rings.append(tube_ring(base.lerp(tip, t), fwd, r0 * (1.0 - 0.72 * t), 8, 1.0, 0.85))
        # three spinnerets, three bands of the one island
        v0 = si / 3.0 + 0.012
        v1 = (si + 1) / 3.0 - 0.012
        mb.loft(rings, MAT_CHITIN, rect, v0, v1)
        mb.cap(rings[-1], tip + fwd * 0.010, MAT_CHITIN, rect, v1, flip=False)


def build_eye(center_base, radius, normal, sub_rect):
    up = normal.normalized()
    ref = Vector((0.0, 0.0, 1.0)) if abs(up.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    side = up.cross(ref).normalized()
    fwd = up.cross(side).normalized()
    rings = []
    for t in (0.25, 0.55, 0.86):
        th = t * math.pi * 0.5
        pts = []
        for i in range(9):
            a = 2.0 * math.pi * (i % 8) / 8.0
            p = center_base + up * (radius * math.cos(th)) + (side * math.cos(a) + fwd * math.sin(a)) * (radius * math.sin(th))
            pts.append((p, i / 8.0))
        rings.append(pts)
    apex = center_base + up * radius
    r0 = rings[0]
    for i in range(8):
        j = i + 1
        mb.add_tri(apex, r0[j][0], r0[i][0],
                   [uv_in(sub_rect, 0.5, 0.95), uv_in(sub_rect, r0[j][1], 0.72), uv_in(sub_rect, r0[i][1], 0.72)],
                   MAT_EYE)
    for k in range(len(rings) - 1):
        A, B = rings[k], rings[k + 1]
        va = 0.72 - 0.34 * k
        vb = va - 0.34
        for i in range(8):
            j = i + 1
            mb.add_quad(A[j][0], A[i][0], B[i][0], B[j][0],
                        [uv_in(sub_rect, A[j][1], va), uv_in(sub_rect, A[i][1], va),
                         uv_in(sub_rect, B[i][1], vb), uv_in(sub_rect, B[j][1], vb)], MAT_EYE)
    base = rings[-1]
    for i in range(8):
        j = i + 1
        # the base fan sits below every ring band's lowest v (0.04) so the eye
        # island never overlaps itself
        mb.add_tri(center_base, base[i][0], base[j][0],
                   [uv_in(sub_rect, 0.5, 0.014), uv_in(sub_rect, base[i][1], 0.0), uv_in(sub_rect, base[j][1], 0.0)],
                   MAT_EYE)


def build_eyes():
    slot = 0
    for side in (-1, 1):
        for row, x, y, r in EYE_ROWS:
            px = side * x
            nrm = surface_normal(y, px)
            base = Vector((px, y, surface_z(y, abs(px)))) - nrm * (r * 0.45)
            mb.skin(skin_body(y), "eye")
            build_eye(base, r, nrm, EYE_SUB[slot])
            slot += 1
    assert slot == 8, slot


def build_chelicerae():
    for side in (-1, 1):
        sname = "R" if side > 0 else "L"
        bone = "Chelicera_%s" % sname
        rect_name = "chelicera_%s" % sname
        rect = UV_RECTS[rect_name]
        base = Vector((side * 0.088, -0.572, 0.402))
        knee = Vector((side * 0.080, -0.688, 0.338))
        fang0 = Vector((side * 0.074, -0.716, 0.312))
        fang1 = Vector((side * 0.058, -0.800, 0.252))
        fwd = (knee - base).normalized()
        rings = []
        for k in range(7):
            t = k / 6.0
            r = lerp(0.048, 0.036, t) * (1.0 + 0.20 * math.exp(-(((1.0 - t)) / 0.35) ** 2))
            rings.append(tube_ring(base.lerp(knee, t), fwd, r, 10, 0.92, 1.0))
        for k in range(6):
            t0 = k / 6.0
            wh = 0.55 * (1.0 - sstep(0.0, 0.45, t0))
            mb.skin({bone: 1.0 - wh, "Head": wh}, rect_name)
            A, B = rings[k], rings[k + 1]
            v0, v1 = 0.08 + 0.54 * t0, 0.08 + 0.54 * (k + 1) / 6.0
            for i in range(10):
                j = i + 1
                mb.add_quad(A[i][0], A[j][0], B[j][0], B[i][0],
                            [uv_in(rect, A[i][1], v0), uv_in(rect, A[j][1], v0),
                             uv_in(rect, B[j][1], v1), uv_in(rect, B[i][1], v1)], MAT_FANG)
        mb.skin({bone: 0.45, "Head": 0.55}, rect_name)
        mb.cap(rings[0], base - fwd * 0.030, MAT_FANG, rect, 0.06, flip=True)
        # fang
        ffwd = (fang1 - fang0).normalized()
        frings = []
        for k in range(6):
            t = k / 5.0
            frings.append(tube_ring(fang0.lerp(fang1, t), ffwd, lerp(0.030, 0.006, t ** 0.8), 8))
        for k in range(5):
            mb.skin({bone: 1.0}, rect_name)
            A, B = frings[k], frings[k + 1]
            v0, v1 = 0.62 + 0.36 * k / 5.0, 0.62 + 0.36 * (k + 1) / 5.0
            for i in range(8):
                j = i + 1
                mb.add_quad(A[i][0], A[j][0], B[j][0], B[i][0],
                            [uv_in(rect, A[i][1], v0), uv_in(rect, A[j][1], v0),
                             uv_in(rect, B[j][1], v1), uv_in(rect, B[i][1], v1)], MAT_FANG)
        mb.skin({bone: 1.0}, rect_name)
        mb.cap(frings[0], fang0 - ffwd * 0.020, MAT_FANG, rect, 0.60, flip=True)
        mb.cap(frings[-1], fang1 + ffwd * 0.014, MAT_FANG, rect, 1.0, flip=False)


def build_pedipalps():
    for side in (-1, 1):
        sname = "R" if side > 0 else "L"
        bone = "Pedipalp_%s" % sname
        rect_name = "pedipalp_%s" % sname
        rect = UV_RECTS[rect_name]
        joints = [
            Vector((side * 0.150, -0.512, 0.306)),
            Vector((side * 0.208, -0.606, 0.252)),
            Vector((side * 0.252, -0.696, 0.176)),
            Vector((side * 0.268, -0.778, 0.098)),
            Vector((side * 0.258, -0.814, 0.062)),
        ]
        radii = [0.040, 0.034, 0.026, 0.019, 0.014]
        rings = []
        for k in range(4):
            a, b = joints[k], joints[k + 1]
            fwd = (b - a).normalized()
            for s in range(3):
                t = s / 3.0
                rings.append(tube_ring(a.lerp(b, t), fwd, lerp(radii[k], radii[k + 1], t), 10))
        tipfwd = (joints[4] - joints[3]).normalized()
        rings.append(tube_ring(joints[4], tipfwd, radii[4] * 0.7, 10))
        total = len(rings) - 1
        for k in range(total):
            t0 = k / float(total)
            wh = 0.65 * (1.0 - sstep(0.0, 0.35, t0))
            mb.skin({bone: 1.0 - wh, "Head": wh}, rect_name)
            A, B = rings[k], rings[k + 1]
            v0, v1 = 0.05 + 0.90 * t0, 0.05 + 0.90 * (k + 1) / float(total)
            for i in range(10):
                j = i + 1
                mb.add_quad(A[i][0], A[j][0], B[j][0], B[i][0],
                            [uv_in(rect, A[i][1], v0), uv_in(rect, A[j][1], v0),
                             uv_in(rect, B[j][1], v1), uv_in(rect, B[i][1], v1)], MAT_CHITIN)
        mb.skin({bone: 0.55, "Head": 0.45}, rect_name)
        mb.cap(rings[0], joints[0] - (joints[1] - joints[0]).normalized() * 0.024,
               MAT_CHITIN, rect, 0.03, flip=True)


# ======================================================================== legs


def leg_joints(base_y, tip_x, tip_y, knee_z):
    """Right-side joint chain: coxa -> femur -> patella -> tibia -> tarsus."""
    bx = surface_x(base_y, COXA_BASE_Z) * 0.82
    base = Vector((bx, base_y, COXA_BASE_Z))
    tip = Vector((tip_x, tip_y, TARSUS_TIP_Z))
    d = Vector((tip.x - base.x, tip.y - base.y, 0.0))
    reach = d.length
    out = d.normalized()
    zs = [COXA_BASE_Z, COXA_BASE_Z + 0.020, knee_z, knee_z - 0.055, ANKLE_Z, TARSUS_TIP_Z]
    joints = [Vector((base.x + out.x * (LEG_HFRAC[k] * reach),
                      base.y + out.y * (LEG_HFRAC[k] * reach), zs[k])) for k in range(6)]
    return joints, out, reach


def leg_rings(joints):
    rings = []
    for k in range(5):
        a, b = joints[k], joints[k + 1]
        r0, r1 = LEG_JOINT_R[k], LEG_JOINT_R[k + 1]
        fwd = (b - a).normalized()
        for s in range(LEG_RINGS_PER_SEG):
            t = s / float(LEG_RINGS_PER_SEG)
            base_r = lerp(r0, r1, t)
            bulge = 1.0
            if k > 0:
                bulge += 0.22 * math.exp(-((t / 0.17) ** 2))
            if k < 4:
                bulge += 0.22 * math.exp(-(((1.0 - t) / 0.17) ** 2))
            kx, ky = 0.94, 1.06
            if k == 4:                                  # the tarsus is a flat foot
                kx, ky = lerp(1.05, 1.30, t), lerp(0.92, 0.74, t)
            rings.append(tube_ring(a.lerp(b, t), fwd, base_r * bulge, LEG_RING_POINTS, kx, ky))
    fwd = (joints[5] - joints[4]).normalized()
    rings.append(tube_ring(joints[5], fwd, LEG_JOINT_R[5], LEG_RING_POINTS, 1.18, 0.80))
    return rings


LEG_INFO = []


def build_legs():
    for sname in ("R", "L"):
        for (index, base_y, tip_x, tip_y, knee_z, amp) in LEG_DEF:
            joints, out, reach = leg_joints(base_y, tip_x, tip_y, knee_z)
            rings = leg_rings(joints)
            if sname == "L":
                # mirror by geometry, not by scale (and keep the winding)
                joints = [Vector((-j.x, j.y, j.z)) for j in joints]
                out = Vector((-out.x, out.y, 0.0))
                rings = [mirror_pts(r) for r in rings]
            chain = ["Leg%s%d_%s" % (sname, index, n) for n in LEG_SEG_NAMES]
            rect = UV_RECTS["leg_R%d" % index]
            region = "leg_%s%d" % (sname, index)
            total = len(rings) - 1
            ring_skin = []
            for ri in range(len(rings)):
                k = min(4, ri // LEG_RINGS_PER_SEG)
                t = (ri - k * LEG_RINGS_PER_SEG) / float(LEG_RINGS_PER_SEG)
                BL = 0.34
                if t < BL:
                    prev = chain[k - 1] if k > 0 else "Body"
                    wp = (0.62 if k == 0 else 0.5) * (1.0 - t / BL)
                    ring_skin.append({chain[k]: 1.0 - wp, prev: wp})
                else:
                    ring_skin.append({chain[k]: 1.0})
            for k in range(total):
                mb.skin(ring_skin[k], region)
                A, B = rings[k], rings[k + 1]
                v0, v1 = k / float(total), (k + 1) / float(total)
                for i in range(LEG_RING_POINTS):
                    j = i + 1
                    mb.add_quad(A[i][0], A[j][0], B[j][0], B[i][0],
                                [uv_in(rect, A[i][1], v0), uv_in(rect, A[j][1], v0),
                                 uv_in(rect, B[j][1], v1), uv_in(rect, B[i][1], v1)], MAT_CHITIN)
            mb.skin({chain[0]: 0.4, "Body": 0.6}, region)
            mb.cap(rings[0], joints[0] - (joints[1] - joints[0]).normalized() * 0.030,
                   MAT_CHITIN, rect, 0.0, flip=True)
            mb.skin({chain[4]: 1.0}, region)
            mb.cap(rings[-1], joints[5] + (joints[5] - joints[4]).normalized() * 0.006,
                   MAT_CHITIN, rect, 1.0, flip=False)
            lift = Vector((out.x, out.y, 0.0)).cross(Vector((0.0, 0.0, 1.0))).normalized()
            LEG_INFO.append({
                "side": sname, "index": index, "prefix": "Leg%s%d" % (sname, index),
                "chain": chain, "joints": joints, "out": out, "lift": lift,
                "yaw": Vector((0.0, 0.0, 1.0)) if sname == "L" else Vector((0.0, 0.0, -1.0)),
                "reach": reach, "amp": amp,
                # classic spider alternation: L1 L3 R2 R4 against L2 L4 R1 R3
                "gait": 0.0 if (index + (0 if sname == "L" else 1)) % 2 == 1 else 0.5,
            })


print("[spider] building body")
build_body()
build_spinnerets()
build_chelicerae()
build_pedipalps()
build_eyes()
print("[spider] building 8 legs")
build_legs()

SOUP_VERTS = len(mb.verts)
WELDED = mb.weld()
print("[spider] welded %d soup verts -> %d" % (SOUP_VERTS, WELDED))

mesh_obj = mb.to_object("LOD0")
min_z = min(v.co.z for v in mesh_obj.data.vertices)
# Body length is measured over the body silhouette only (fangs, pedipalps and
# spinnerets included) -- the outstretched legs are not part of it.
BODY_REGIONS = {"carapace", "abdomen", "eye", "chelicera_R", "chelicera_L",
                "pedipalp_R", "pedipalp_L", "spinneret"}
body_ys = [mesh_obj.data.vertices[vi].co.y
           for pi, poly in enumerate(mesh_obj.data.polygons)
           if mb.face_regions[pi] in BODY_REGIONS
           for vi in poly.vertices]
BODY_LENGTH = max(body_ys) - min(body_ys)
if abs(min_z) > 1e-9:
    for v in mesh_obj.data.vertices:
        v.co.z -= min_z
GROUND_SHIFT = -min_z

# ======================================================================== rig

BONES = []


def add_bone(name, head, tail, parent=None, connect=False):
    BONES.append((name, Vector(head) - Vector((0.0, 0.0, min_z)),
                  Vector(tail) - Vector((0.0, 0.0, min_z)), parent, connect))


add_bone("Root", (0.0, 0.0, 0.0), (0.0, -0.28, 0.0))
add_bone("Body", (0.0, -0.220, 0.415), (0.0, 0.055, 0.428), "Root")
add_bone("Head", (0.0, -0.360, 0.455), (0.0, -0.628, 0.440), "Body")
add_bone("Abdomen", (0.0, 0.048, 0.428), (0.0, 0.700, 0.442), "Body")
for side, sname in ((-1, "L"), (1, "R")):
    add_bone("Chelicera_%s" % sname, (side * 0.088, -0.572, 0.402), (side * 0.058, -0.800, 0.252), "Head")
    add_bone("Pedipalp_%s" % sname, (side * 0.150, -0.512, 0.306), (side * 0.258, -0.814, 0.062), "Head")
for info in LEG_INFO:
    j = info["joints"]
    chain = info["chain"]
    for k in range(5):
        add_bone(chain[k], j[k], j[k + 1], "Body" if k == 0 else chain[k - 1], k > 0)

arm_data = bpy.data.armatures.new("Acromantula_Armature")
arm_obj = bpy.data.objects.new("Acromantula", arm_data)
bpy.context.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode="EDIT")
for name, head, tail, parent, connect in BONES:
    eb = arm_data.edit_bones.new(name)
    eb.head = head
    eb.tail = tail
    if parent:
        eb.parent = arm_data.edit_bones[parent]
        eb.use_connect = bool(connect)
    eb.align_roll(Vector((0.0, 0.0, 1.0)))
bpy.ops.object.mode_set(mode="OBJECT")
print("[spider] armature: %d bones" % len(arm_data.bones))

# ------------------------------------------------------------------ skinning
GROUP_NAMES = [b[0] for b in BONES]
for gname in GROUP_NAMES:
    mesh_obj.vertex_groups.new(name=gname)
vg = {g.name: g for g in mesh_obj.vertex_groups}
for i, w in enumerate(mb.weights):
    for bone, val in w.items():
        if val > 1e-4:
            vg[bone].add([i], val, "REPLACE")
mesh_obj.parent = arm_obj
mesh_obj.modifiers.new("Armature", "ARMATURE").object = arm_obj
mesh_obj.data.polygons.foreach_set("use_smooth", [True] * len(mesh_obj.data.polygons))
# every shell is closed, so normal recalculation is unambiguous
bm = bmesh.new()
bm.from_mesh(mesh_obj.data)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(mesh_obj.data)
bm.free()
mesh_obj.data.update()


# ================================================================ materials


def make_materials():
    alb, nrm, rgh = build_textures()

    def base_mat(name):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        return m

    def hook(mat, base_img, normal_img, rough_img, rough_scalar):
        nt = mat.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        bsdf.inputs["Metallic"].default_value = 0.0
        if base_img is not None:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = base_img
            tex.location = (-520, 320)
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if normal_img is not None:
            ntex = nt.nodes.new("ShaderNodeTexImage")
            ntex.image = normal_img
            ntex.image.colorspace_settings.name = "Non-Color"
            ntex.location = (-520, 40)
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.location = (-250, 40)
            nmap.inputs["Strength"].default_value = 1.0
            nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        if rough_img is not None:
            rtex = nt.nodes.new("ShaderNodeTexImage")
            rtex.image = rough_img
            rtex.image.colorspace_settings.name = "Non-Color"
            rtex.location = (-520, -220)
            nt.links.new(rtex.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            bsdf.inputs["Roughness"].default_value = rough_scalar
        return bsdf

    m_chitin = base_mat("Acromantula_Chitin")
    hook(m_chitin, alb, nrm, rgh, 0.32)
    m_membrane = base_mat("Acromantula_Membrane")
    hook(m_membrane, alb, nrm, None, 0.70)
    m_eye = base_mat("Acromantula_Eyes")
    b = hook(m_eye, None, None, None, 0.18)
    b.inputs["Base Color"].default_value = (0.030, 0.019, 0.013, 1.0)
    b.inputs["Emission Color"].default_value = (1.0, 0.20, 0.030, 1.0)
    b.inputs["Emission Strength"].default_value = 0.65
    m_eye.diffuse_color = (0.030, 0.019, 0.013, 1.0)
    m_fang = base_mat("Acromantula_Fang")
    hook(m_fang, alb, nrm, None, 0.30)
    return [m_chitin, m_membrane, m_eye, m_fang]


MATERIALS = make_materials()
for m in MATERIALS:
    mesh_obj.data.materials.append(m)
print("[spider] material slots: %d %s" % (len(MATERIALS), [m.name for m in MATERIALS]))

# ======================================================================= LOD1

mesh_obj.name = "LOD0"
mesh_obj.data.name = "LOD0"
lod1 = bpy.data.objects.new("LOD1", mesh_obj.data.copy())
lod1.data.name = "LOD1"
bpy.context.collection.objects.link(lod1)
# the deform layer travels with the mesh data; the object needs matching groups
for g in mesh_obj.vertex_groups:
    lod1.vertex_groups.new(name=g.name)
dec = lod1.modifiers.new("Decimate", "DECIMATE")
dec.decimate_type = "COLLAPSE"
dec.ratio = 0.50
bpy.ops.object.select_all(action="DESELECT")
lod1.select_set(True)
bpy.context.view_layer.objects.active = lod1
bpy.ops.object.modifier_apply(modifier="Decimate")
lod1.select_set(False)
lod1.parent = arm_obj
lod1.modifiers.new("Armature", "ARMATURE").object = arm_obj
lod1.data.polygons.foreach_set("use_smooth", [True] * len(lod1.data.polygons))
lod1.data.update()


def tri_count(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


TRIS0 = tri_count(mesh_obj)
TRIS1 = tri_count(lod1)
print("[spider] LOD0 %d tris, LOD1 %d tris (%.1f%%)" % (TRIS0, TRIS1, 100.0 * TRIS1 / max(1, TRIS0)))

# ================================================================ animations

CLIPS = {}
LOOP_CLIPS = {"Idle", "Walk", "Stun"}
LEG_ANIM = {i["prefix"]: i for i in LEG_INFO}
AXIS_VEC = {"X": Vector((1.0, 0.0, 0.0)), "Y": Vector((0.0, 1.0, 0.0)), "Z": Vector((0.0, 0.0, 1.0))}


def q_from(spec):
    q = Quaternion((1.0, 0.0, 0.0, 0.0))
    for axis, deg in spec:
        v = AXIS_VEC[axis] if isinstance(axis, str) else axis
        q = Quaternion(v, math.radians(deg)) @ q
    return q


REST_Q = {b.name: b.matrix_local.to_quaternion() for b in arm_data.bones}


def clear_pose():
    for pb in arm_obj.pose.bones:
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def apply_pose(deltas):
    clear_pose()
    for name, spec in deltas.items():
        pb = arm_obj.pose.bones.get(name)
        if pb is None:
            continue
        B = REST_Q[name]
        rot = spec.get("rot")
        if rot:
            pb.rotation_quaternion = (B.inverted() @ q_from(rot) @ B).normalized()
        loc = spec.get("loc")
        if loc:
            pb.location = B.inverted() @ Vector(loc)
        sc = spec.get("scale")
        if sc:
            pb.scale = Vector(sc)


def R(d, bone, axis, deg):
    if abs(deg) < 1e-6:
        return
    d.setdefault(bone, {}).setdefault("rot", []).append((axis, deg))


def T(d, bone, loc):
    d.setdefault(bone, {})["loc"] = loc


def SCL(d, bone, sc):
    d.setdefault(bone, {})["scale"] = sc


def leg_delta(d, info, yaw=0.0, coxa_lift=0.0, femur=0.0, patella=0.0, tibia=0.0, tarsus=0.0):
    c = info["chain"]
    R(d, c[0], info["yaw"], yaw)
    R(d, c[0], info["lift"], coxa_lift)
    R(d, c[1], info["lift"], femur)
    R(d, c[2], info["lift"], patella)
    R(d, c[3], info["lift"], tibia)
    R(d, c[4], info["lift"], tarsus)


def author_clip(name, frames, pose_fn):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm_obj.animation_data_create()
    arm_obj.animation_data.action = act
    last = float(frames[-1])
    for f in frames:
        apply_pose(pose_fn(f, f / last if last else 0.0))
        for pb in arm_obj.pose.bones:
            pb.keyframe_insert("rotation_quaternion", frame=f)
            pb.keyframe_insert("location", frame=f)
            pb.keyframe_insert("scale", frame=f)
    arm_obj.animation_data.action = None
    clear_pose()
    act.use_frame_range = True
    act.frame_start = 0.0
    act.frame_end = last
    act.use_cyclic = name in LOOP_CLIPS
    act["hpmmo_loop"] = bool(name in LOOP_CLIPS)
    act["hpmmo_duration_s"] = round(last / float(FPS), 4)
    CLIPS[name] = (int(last), name in LOOP_CLIPS)
    return act


def nframes(seconds):
    return int(round(seconds * FPS))


# ---------------------------------------------------------------- Idle (2.0 s)
def idle_pose(f, t):
    d = {}
    ph = 2.0 * math.pi * t
    sp = math.sin(ph)
    SCL(d, "Abdomen", (1.0 + 0.013 * sp, 1.0 + 0.032 * sp, 1.0 + 0.013 * sp))
    R(d, "Abdomen", "X", 1.8 * math.sin(ph + 0.7))
    R(d, "Body", "Z", 1.6 * math.sin(ph * 0.5))
    R(d, "Body", "Y", 0.9 * sp)
    R(d, "Head", "Z", 2.2 * math.sin(ph * 0.5 + 1.1))
    R(d, "Head", "X", -1.0 * math.sin(ph + 0.4))
    T(d, "Body", (0.004 * math.sin(ph * 0.5 + 0.9), 0.0, 0.006 * sp))
    for key, offset, sign in (("LegL1", 0.20, 1.0), ("LegR1", 0.66, -1.0),
                              ("LegL2", 0.44, 1.0), ("LegR2", 0.88, -1.0)):
        info = LEG_ANIM[key]
        tap = math.exp(-(((t - offset) % 1.0) / 0.055) ** 2)
        leg_delta(d, info, yaw=2.5 * sign * math.sin(ph), coxa_lift=1.5 * tap, femur=6.5 * tap,
                  patella=3.0 * tap, tibia=5.0 * tap, tarsus=-3.5 * tap)
    for key, off in (("LegL3", 0.0), ("LegR3", math.pi), ("LegL4", 0.4),
                     ("LegR4", math.pi + 0.4), ("LegL2", 1.2), ("LegR2", math.pi + 1.2)):
        leg_delta(d, LEG_ANIM[key], yaw=0.9 * math.sin(ph * 0.5 + off), femur=0.8 * math.sin(ph + off))
    R(d, "Pedipalp_L", "X", -7.0 * math.sin(ph + 0.3))
    R(d, "Pedipalp_L", "Y", 4.0 * math.sin(ph * 0.5))
    R(d, "Pedipalp_R", "X", -7.0 * math.sin(ph + 2.0))
    R(d, "Pedipalp_R", "Y", -4.0 * math.sin(ph * 0.5 + 1.7))
    R(d, "Chelicera_L", "Z", 2.0 * math.sin(ph + 0.8))
    R(d, "Chelicera_R", "Z", -2.0 * math.sin(ph + 0.8))
    return d


# ---------------------------------------------------------------- Walk (1.0 s)
def walk_pose(f, t):
    d = {}
    SCL(d, "Abdomen", (1.0, 1.0 + 0.012 * math.sin(2.0 * math.pi * t), 1.0))
    for info in LEG_INFO:
        ph = (t + info["gait"]) % 1.0
        amp = info["amp"]
        if ph < 0.5:                       # stance: planted foot sweeps backwards
            u = ph / 0.5
            yaw = amp * (1.0 - 2.0 * u)
            fem = pat = tib = tar = 0.0
        else:                              # swing: lift and reach forward again
            u = (ph - 0.5) / 0.5
            sm = u * u * (3.0 - 2.0 * u)
            yaw = -amp + 2.0 * amp * sm
            s = math.sin(math.pi * u)
            fem, pat, tib, tar = 6.0 * s, 3.5 * s, 7.0 * s, -5.0 * s
        leg_delta(d, info, yaw=yaw, femur=fem, patella=pat, tibia=tib, tarsus=tar)
    bob = 2.0 * math.pi * 2.0 * t
    T(d, "Body", (0.010 * math.sin(2.0 * math.pi * t), 0.0, 0.011 * math.sin(bob + 1.1)))
    R(d, "Body", "Z", 1.5 * math.sin(2.0 * math.pi * t + 1.6))
    R(d, "Body", "Y", 1.1 * math.sin(2.0 * math.pi * t))
    R(d, "Body", "X", 0.8 * math.sin(bob))
    R(d, "Abdomen", "X", 1.4 * math.sin(bob + 0.8))
    R(d, "Head", "X", -1.0 * math.sin(bob + 0.5))
    R(d, "Pedipalp_L", "X", -9.0 * math.sin(2.0 * math.pi * t))
    R(d, "Pedipalp_R", "X", 9.0 * math.sin(2.0 * math.pi * t))
    return d


# ---------------------------------------------------------------- Turn (0.8 s)
def turn_pose(f, t):
    d = {}
    lean = math.sin(math.pi * t)           # returns to neutral so it blends both ways
    R(d, "Body", "Z", 15.0 * lean)
    R(d, "Body", "Y", 7.0 * lean)
    R(d, "Body", "X", -2.0 * lean)
    R(d, "Head", "Z", 9.0 * lean)
    R(d, "Abdomen", "Z", -7.0 * lean)
    R(d, "Abdomen", "Y", 4.0 * lean)
    T(d, "Body", (-0.02 * lean, 0.0, -0.012 * lean))
    for info in LEG_INFO:
        reach = 1.0 if info["side"] == "L" else -1.0
        front = info["index"] in (1, 2)
        leg_delta(d, info,
                  yaw=(13.0 * reach + 3.0 * (info["gait"] * 2.0)) * lean,
                  coxa_lift=(3.0 if front else 0.0) * lean,
                  femur=(7.0 if front else 2.5) * lean,
                  patella=2.0 * lean, tibia=4.0 * lean, tarsus=-3.0 * lean)
    R(d, "Pedipalp_L", "Y", 12.0 * lean)
    R(d, "Pedipalp_R", "Y", -6.0 * lean)
    return d


# --------------------------------------------------- Bite_Anticipation (0.45 s)
def bite_anticipation_pose(f, t):
    d = {}
    e = sstep(0.0, 0.75, t)
    R(d, "Body", "X", -20.0 * e)
    R(d, "Head", "X", -13.0 * e)
    R(d, "Abdomen", "X", 15.0 * e)
    T(d, "Body", (0.0, 0.05 * e, 0.115 * e))
    for info in LEG_INFO:
        front = info["index"] == 1
        leg_delta(d, info,
                  yaw=((10.0 if info["side"] == "L" else -10.0) if front else 0.0) * e,
                  coxa_lift=(10.0 if front else 3.0) * e,
                  femur=(34.0 if front else 6.0) * e,
                  patella=(16.0 if front else 3.0) * e,
                  tibia=(-8.0 if front else 5.0) * e,
                  tarsus=(-22.0 if front else -4.0) * e)
    R(d, "Chelicera_L", "Z", 26.0 * e)
    R(d, "Chelicera_R", "Z", -26.0 * e)
    R(d, "Chelicera_L", "X", 16.0 * e)
    R(d, "Chelicera_R", "X", 16.0 * e)
    R(d, "Pedipalp_L", "X", -34.0 * e)
    R(d, "Pedipalp_R", "X", -34.0 * e)
    R(d, "Pedipalp_L", "Y", 14.0 * e)
    R(d, "Pedipalp_R", "Y", -14.0 * e)
    return d


# --------------------------------------------------------- Bite_Attack (0.5 s)
def bite_attack_pose(f, t):
    d = {}
    if t < 0.30:
        e = (t / 0.30) ** 2
        rec = 0.0
    else:
        e = 1.0
        rec = sstep(0.0, 1.0, (t - 0.30) / 0.70)
    rear = 1.0 - rec
    stab = sstep(0.30, 0.52, t) * (1.0 - sstep(0.62, 1.0, t))
    R(d, "Body", "X", (-12.0 * e + 34.0 * stab) * (1.0 - 0.30 * rec))
    R(d, "Head", "X", (-6.0 * e + 22.0 * stab) * (1.0 - 0.30 * rec))
    R(d, "Abdomen", "X", 12.0 * e * (1.0 - 0.4 * rec))
    T(d, "Body", (0.0, -0.30 * e * (1.0 - 0.55 * rec), 0.055 * rear - 0.02 * rec))
    for info in LEG_INFO:
        front = info["index"] == 1
        leg_delta(d, info,
                  yaw=((16.0 if info["side"] == "L" else -16.0) if front else 2.0) * e * (1.0 - 0.5 * rec),
                  coxa_lift=(16.0 if front else 2.0) * rear,
                  femur=(30.0 if front else -4.0) * rear + (6.0 if front else 2.0) * rec,
                  patella=(12.0 if front else 0.0) * rear,
                  tibia=(-6.0 if front else 4.0) * rear,
                  tarsus=(-18.0 if front else -3.0) * rear)
    R(d, "Chelicera_L", "Z", 24.0 * rear)
    R(d, "Chelicera_R", "Z", -24.0 * rear)
    R(d, "Chelicera_L", "X", 16.0 * rear - 52.0 * stab)
    R(d, "Chelicera_R", "X", 16.0 * rear - 52.0 * stab)
    R(d, "Pedipalp_L", "X", -28.0 * rear + 12.0 * rec)
    R(d, "Pedipalp_R", "X", -28.0 * rear + 12.0 * rec)
    return d


# ---------------------------------------------------------------- Hit (0.5 s)
def hit_pose(f, t):
    d = {}
    e = math.sin(math.pi * min(1.0, t * 1.35)) ** 0.7
    R(d, "Body", "X", 11.0 * e)
    R(d, "Body", "Z", -9.0 * e)
    R(d, "Body", "Y", -7.0 * e)
    R(d, "Head", "X", 13.0 * e)
    R(d, "Abdomen", "X", -12.0 * e)
    T(d, "Body", (0.04 * e, 0.085 * e, -0.045 * e))
    for info in LEG_INFO:
        brace = 1.0 if info["side"] == "R" else 0.55
        leg_delta(d, info, yaw=-9.0 * e * brace, coxa_lift=-4.0 * e, femur=-5.0 * e,
                  patella=-3.0 * e, tibia=9.0 * e, tarsus=-6.0 * e)
    R(d, "Chelicera_L", "Z", -20.0 * e)
    R(d, "Chelicera_R", "Z", 20.0 * e)
    R(d, "Pedipalp_L", "X", 22.0 * e)
    R(d, "Pedipalp_R", "X", 22.0 * e)
    return d


# --------------------------------------------------------------- Stun (1.2 s)
def stun_pose(f, t):
    d = {}
    ph = 2.0 * math.pi * t
    tw = math.sin(ph * 2.0)
    R(d, "Body", "X", 7.0 + 1.5 * tw)
    R(d, "Body", "Y", 3.0 * math.sin(ph) + 1.2 * tw)
    R(d, "Body", "Z", 2.5 * math.sin(ph * 0.5))
    R(d, "Head", "X", 12.0 + 2.0 * tw)
    R(d, "Head", "Z", 3.0 * math.sin(ph))
    R(d, "Abdomen", "X", -9.0 - 2.0 * tw)
    T(d, "Body", (0.012 * math.sin(ph), 0.012, -0.075))
    SCL(d, "Abdomen", (1.0, 0.985, 1.0))
    for info in LEG_INFO:
        leg_delta(d, info,
                  yaw=2.5 * math.sin(ph + info["gait"] * math.pi) + 0.8 * tw,
                  coxa_lift=-5.0, femur=-6.0 + 1.2 * tw, patella=-2.0,
                  tibia=13.0 + 1.5 * tw, tarsus=-6.5)
    R(d, "Pedipalp_L", "X", 20.0 + 3.0 * tw)
    R(d, "Pedipalp_R", "X", 22.0 - 3.0 * tw)
    R(d, "Chelicera_L", "X", 8.0 + 2.0 * tw)
    R(d, "Chelicera_R", "X", 8.0 - 2.0 * tw)
    return d


# -------------------------------------------------------------- Death (1.8 s)
def death_pose(f, t):
    """Collapse, not a pose change.  The body sinks until the sternum and the
    sagging abdomen rest on the ground, the knees buckle so the femurs rise and
    the tarsi fold inwards under the body, and the last frames hold a settled
    corpse pose.  The knee-buckle is what keeps the feet above the floor while
    the body drops 0.105 m: the femur gains angle as fast as the body loses
    height, so the tarsus stays planted and then drags inward."""
    d = {}
    brace = math.exp(-((t - 0.10) / 0.075) ** 2)
    curl = sstep(0.16, 0.64, t)
    settle = sstep(0.60, 0.92, t)
    quiver = math.exp(-((t - 0.74) / 0.045) ** 2)
    R(d, "Body", "X", 4.0 * brace + 6.0 * curl + 1.5 * settle)
    R(d, "Body", "Y", -3.0 * brace + 11.0 * curl)
    R(d, "Body", "Z", -6.0 * curl)
    R(d, "Head", "X", 6.0 * brace + 16.0 * curl + 2.0 * settle)
    R(d, "Head", "Z", -6.0 * curl)
    R(d, "Abdomen", "X", -7.0 * brace - 18.0 * curl - 2.0 * settle)
    R(d, "Abdomen", "Y", 6.0 * curl)
    SCL(d, "Abdomen", (1.0 - 0.06 * curl, 1.0 - 0.08 * curl, 1.0 - 0.06 * curl))
    T(d, "Body", (0.016 * curl, 0.050 * brace, -0.018 * brace - 0.098 * curl - 0.007 * settle))
    for info in LEG_INFO:
        sign = 1.0 if info["side"] == "L" else -1.0
        front = info["index"] in (1, 2)
        leg_delta(d, info,
                  yaw=(5.0 * brace + (7.0 + 3.0 * info["index"]) * curl) * sign,
                  coxa_lift=6.0 * brace - 4.0 * curl,
                  femur=-10.0 * brace + (24.0 + (4.0 if front else 0.0)) * curl + 1.6 * quiver,
                  patella=-5.0 * brace - 24.0 * curl,
                  tibia=18.0 * brace - 4.0 * curl + 1.8 * quiver,
                  tarsus=-26.0 * brace + 16.0 * curl)
    R(d, "Chelicera_L", "X", 12.0 * curl + 4.0 * settle)
    R(d, "Chelicera_R", "X", 12.0 * curl + 4.0 * settle)
    R(d, "Chelicera_L", "Z", -9.0 * curl)
    R(d, "Chelicera_R", "Z", 9.0 * curl)
    R(d, "Pedipalp_L", "X", 26.0 * brace + 40.0 * curl)
    R(d, "Pedipalp_R", "X", 26.0 * brace + 40.0 * curl)
    R(d, "Pedipalp_L", "Y", 12.0 * curl)
    R(d, "Pedipalp_R", "Y", -12.0 * curl)
    return d


CLIP_SPECS = [
    ("Idle", 2.0, idle_pose, 2),
    ("Walk", 1.0, walk_pose, 1),
    ("Turn", 0.8, turn_pose, 1),
    ("Bite_Anticipation", 0.45, bite_anticipation_pose, 1),
    ("Bite_Attack", 0.5, bite_attack_pose, 1),
    ("Hit", 0.5, hit_pose, 1),
    ("Stun", 1.2, stun_pose, 2),
    ("Death", 1.8, death_pose, 1),
]

print("[spider] authoring %d clips" % len(CLIP_SPECS))
for name, dur, fn, step in CLIP_SPECS:
    last = nframes(dur)
    frames = list(range(0, last + 1, step))
    if frames[-1] != last:
        frames.append(last)
    author_clip(name, frames, fn)
    print("[spider]   %-18s %2d frames  %5.2fs  %s  (%d keys)"
          % (name, last, last / float(FPS), "loop" if name in LOOP_CLIPS else "once", len(frames)))

KEEP = {n for n, _, _, _ in CLIP_SPECS}
for act in list(bpy.data.actions):
    if act.name not in KEEP:
        bpy.data.actions.remove(act)
for act in bpy.data.actions:
    act.use_fake_user = True
arm_obj.animation_data_create()
arm_obj.animation_data.action = None

# ======================================================== measurement + checks


def evaluated_bounds(ob):
    deps = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(deps).to_mesh()
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    out = (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
    ob.evaluated_get(deps).to_mesh_clear()
    return out


BX0, BX1, BY0, BY1, BZ0, BZ1 = evaluated_bounds(mesh_obj)
SPAN_M = BX1 - BX0
LENGTH_M = BODY_LENGTH
HEIGHT_M = BZ1 - BZ0
MIN_Y = BZ0

arm_obj.animation_data.action = bpy.data.actions["Death"]
scene.frame_set(0)
bpy.context.view_layer.update()
h0 = arm_obj.pose.bones["Body"].head.z
scene.frame_set(CLIPS["Death"][0])
bpy.context.view_layer.update()
h1 = arm_obj.pose.bones["Body"].head.z
arm_obj.animation_data.action = None
scene.frame_set(0)
clear_pose()
bpy.context.view_layer.update()

BONES_N = len(arm_data.bones)
LEG_CHAINS = len(LEG_INFO)


def uv_overlap_report(ob, res=512):
    """Rasterise every UV triangle (shrunk 8% toward its centroid) into a
    coverage grid; report texels covered more than once, with and without the
    deliberately mirrored left-leg islands, plus the worst offending island
    pairs so a real overlap can be told apart from rasteriser noise."""
    me = ob.data
    uvl = me.uv_layers.active.data
    cov_all = np.zeros((res, res), np.int32)
    cov_noleft = np.zeros((res, res), np.int32)
    owner = np.full((res, res), -1, np.int32)
    region_ids = {n: i for i, n in enumerate(UV_PLACEMENTS + ["leg_L1", "leg_L2", "leg_L3", "leg_L4"])}
    pairs = {}
    leg_faces = 0
    for pi, poly in enumerate(me.polygons):
        reg = mb.face_regions[pi]
        if reg.startswith("leg_"):
            leg_faces += 1
        left = reg in ("leg_L1", "leg_L2", "leg_L3", "leg_L4")
        ridx = region_ids.get(reg, -1)
        pts = [tuple(uvl[li].uv) for li in poly.loop_indices]
        for tri in range(1, len(pts) - 1):
            a, b, c = pts[0], pts[tri], pts[tri + 1]
            cx = (a[0] + b[0] + c[0]) / 3.0
            cy = (a[1] + b[1] + c[1]) / 3.0
            a = (cx + (a[0] - cx) * 0.92, cy + (a[1] - cy) * 0.92)
            b = (cx + (b[0] - cx) * 0.92, cy + (b[1] - cy) * 0.92)
            c = (cx + (c[0] - cx) * 0.92, cy + (c[1] - cy) * 0.92)
            x0 = max(0, int(min(a[0], b[0], c[0]) * res) - 1)
            x1 = min(res - 1, int(max(a[0], b[0], c[0]) * res) + 1)
            y0 = max(0, int(min(a[1], b[1], c[1]) * res) - 1)
            y1 = min(res - 1, int(max(a[1], b[1], c[1]) * res) + 1)
            if x1 < x0 or y1 < y0:
                continue
            gx = (np.arange(x0, x1 + 1) + 0.5) / res
            gy = (np.arange(y0, y1 + 1) + 0.5) / res
            PX, PY = gx[None, :], gy[:, None]
            d = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if abs(d) < 1e-12:
                continue
            w0 = ((b[0] - PX) * (c[1] - PY) - (b[1] - PY) * (c[0] - PX)) / d
            w1 = ((c[0] - PX) * (a[1] - PY) - (c[1] - PY) * (a[0] - PX)) / d
            inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
            cov_all[y0:y1 + 1, x0:x1 + 1] += inside.astype(np.int32)
            if left:
                continue
            sub = cov_noleft[y0:y1 + 1, x0:x1 + 1]
            sub += inside.astype(np.int32)
            ow = owner[y0:y1 + 1, x0:x1 + 1]
            clash = inside & (ow >= 0) & (ow != ridx)
            if clash.any():
                for v in np.unique((np.minimum(ow[clash], ridx).astype(np.int64) * 64
                                    + np.maximum(ow[clash], ridx))).tolist():
                    key = (int(v // 64), int(v % 64))
                    pairs[key] = pairs.get(key, 0) + 1
            newv = inside & (ow < 0)
            ow[newv] = ridx
            owner[y0:y1 + 1, x0:x1 + 1] = ow
    names = UV_PLACEMENTS + ["leg_L1", "leg_L2", "leg_L3", "leg_L4"]
    worst = sorted(pairs.items(), key=lambda kv: -kv[1])[:5]
    self_ov = {}
    for ridx, nm in enumerate(names):
        m = owner == ridx
        n = int(m.sum())
        if n:
            self_ov[nm] = (n, int(((cov_noleft >= 2) & m).sum()))
    top_self = sorted(self_ov.items(), key=lambda kv: -kv[1][1])[:6]
    return (int((cov_all >= 2).sum()), int((cov_noleft >= 2).sum()), leg_faces,
            [(names[k[0]], names[k[1]], n) for k, n in worst],
            int((cov_noleft >= 1).sum()), top_self)


UV_ALL_OVERLAP, UV_OVERLAP, UV_LEG_FACES, UV_WORST, UV_COVERED, UV_SELF = uv_overlap_report(mesh_obj)

# ------------------------------------------------------------- validation gate
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("[spider] FAIL: %s" % msg)
    return cond


REQUIRED_ACTIONS = ["Idle", "Walk", "Turn", "Bite_Anticipation", "Bite_Attack", "Hit", "Stun", "Death"]
check(BONES_N == 48, "bone count %d != 48" % BONES_N)
check(LEG_CHAINS == 8, "leg chain count %d != 8" % LEG_CHAINS)
for a in REQUIRED_ACTIONS:
    check(a in bpy.data.actions, "required action missing: %s" % a)
check(TRIS0 <= 20000, "LOD0 tris %d above the 20000 ceiling" % TRIS0)
check(abs(MIN_Y) <= 0.02, "bind-pose min y %.4f outside +-0.02" % MIN_Y)
check(2.0 <= SPAN_M <= 2.6, "leg span %.3f m outside 2.0-2.6" % SPAN_M)
check(h1 < h0 - 0.05, "Death does not end lowered (body bone z %.3f -> %.3f)" % (h0, h1))
for ob in (mesh_obj, lod1):
    check(ob.matrix_world.to_3x3().determinant() > 0.0, "%s carries a negative scale" % ob.name)
for pb in arm_obj.pose.bones:
    check(pb.scale.x > 0.0 and pb.scale.y > 0.0 and pb.scale.z > 0.0,
          "bone %s carries a negative scale" % pb.name)

if FAILS:
    raise SystemExit(1)

print("[spider] tris=%d bones=%d clips=%d span_m=%.3f length_m=%.3f height_m=%.3f min_y=%.4f uv_mirrored=%d lods=2"
      % (TRIS0, BONES_N, len(bpy.data.actions), SPAN_M, LENGTH_M, HEIGHT_M, MIN_Y, len(MIRRORED_RECTS)))
print("[spider] lod0_tris=%d lod1_tris=%d lod1_ratio=%.3f" % (TRIS0, TRIS1, TRIS1 / float(TRIS0)))
print("[spider] leg_chains=%d leg_faces=%d uv_islands=%d uv_overlap_texels=%d uv_overlap_excl_mirror=%d"
      % (LEG_CHAINS, UV_LEG_FACES, UV_ISLANDS, UV_ALL_OVERLAP, UV_OVERLAP))
print("[spider] uv_overlap_pairs=%s" % UV_WORST)
print("[spider] uv_covered_texels=%d uv_self_overlap=%s" % (UV_COVERED, UV_SELF))
print("[spider] body_top_m=%.3f ground_shift_m=%.5f welded_verts=%d"
      % (HEIGHT_M, GROUND_SHIFT, len(mesh_obj.data.vertices)))
print("[spider] death_body_z first=%.3f last=%.3f delta=%.3f" % (h0, h1, h1 - h0))
print("[spider] loops=%s onceshots=%s" % (sorted(LOOP_CLIPS), sorted(set(CLIPS) - LOOP_CLIPS)))
print("[spider] clip_frames=%s" % {k: CLIPS[k][0] for k in sorted(CLIPS)})
print("[spider] bone_names=%s" % [b[0] for b in BONES])

# ==================================================================== renders


def try_render():
    if not RENDER_DIR:
        print("[spider] renders skipped: no --render directory given")
        return []
    try:
        os.makedirs(RENDER_DIR, exist_ok=True)
        cam_data = bpy.data.cameras.new("spider_cam")
        cam_data.angle = math.radians(65.0)
        cam = bpy.data.objects.new("spider_cam", cam_data)
        cam_data.lens_unit = "FOV"
        bpy.context.collection.objects.link(cam)
        scene.camera = cam
        cam.location = Vector((3.20, 7.30, 1.60))
        target = Vector((0.0, 0.02, 0.34))
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        sun_d = bpy.data.lights.new("sun", "SUN")
        sun_d.energy = 4.6
        sun = bpy.data.objects.new("sun", sun_d)
        bpy.context.collection.objects.link(sun)
        sun.rotation_euler = (math.radians(52.0), 0.0, math.radians(38.0))
        fill_d = bpy.data.lights.new("fill", "AREA")
        fill_d.energy = 900.0
        fill_d.size = 6.0
        fill = bpy.data.objects.new("fill", fill_d)
        bpy.context.collection.objects.link(fill)
        fill.location = Vector((-4.0, 4.0, 3.0))
        fill.rotation_euler = (Vector((0.0, 0.0, 0.5)) - fill.location).to_track_quat("-Z", "Y").to_euler()
        key_d = bpy.data.lights.new("key", "AREA")
        key_d.energy = 700.0
        key_d.size = 5.0
        key = bpy.data.objects.new("key", key_d)
        bpy.context.collection.objects.link(key)
        key.location = Vector((2.6, -5.2, 2.2))
        key.rotation_euler = (Vector((0.0, -0.15, 0.40)) - key.location).to_track_quat("-Z", "Y").to_euler()
        gmesh = bpy.data.meshes.new("ground")
        gmesh.from_pydata([(-14.0, -14.0, 0.0), (14.0, -14.0, 0.0), (14.0, 14.0, 0.0), (-14.0, 14.0, 0.0)],
                          [], [(0, 1, 2, 3)])
        gmesh.update()
        gmat = bpy.data.materials.new("GroundMat")
        gmat.use_nodes = True
        gb = gmat.node_tree.nodes["Principled BSDF"]
        gb.inputs["Base Color"].default_value = (0.045, 0.048, 0.042, 1.0)
        gb.inputs["Roughness"].default_value = 0.92
        gmesh.materials.append(gmat)
        ground = bpy.data.objects.new("ground", gmesh)
        bpy.context.collection.objects.link(ground)
        world = bpy.data.worlds.new("spider_world")
        world.use_nodes = True
        bg = world.node_tree.nodes["Background"]
        bg.inputs[0].default_value = (0.085, 0.095, 0.115, 1.0)
        bg.inputs[1].default_value = 1.0
        scene.world = world
        scene.render.resolution_x = 800
        scene.render.resolution_y = 600
        scene.render.image_settings.file_format = "PNG"
    except Exception as exc:
        print("[spider] renders skipped: scene setup failed (%s)" % exc)
        return []
    engine = "EEVEE"
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except Exception:
        engine = "WORKBENCH"
        try:
            scene.render.engine = "BLENDER_WORKBENCH"
        except Exception as exc:
            print("[spider] renders skipped: no usable engine (%s)" % exc)
            return []
    if engine == "WORKBENCH":
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
    # gameplay framing for the three required shots, plus a close anatomy check
    GAME = (Vector((3.20, 7.30, 1.60)), Vector((0.0, 0.02, 0.34)), 65.0)
    DETAIL = (Vector((1.70, -2.05, 0.86)), Vector((0.0, -0.30, 0.36)), 42.0)
    shots = [("idle", "Idle", 12, GAME),
             ("walk", "Walk", 6, GAME),
             ("death", "Death", CLIPS["Death"][0], GAME),
             ("detail", "Idle", 20, DETAIL)]
    paths = []
    for label, action, frame, (cpos, ctgt, cfov) in shots:
        cam.location = cpos
        cam_data.angle = math.radians(cfov)
        cam.rotation_euler = (ctgt - cpos).to_track_quat("-Z", "Y").to_euler()
        arm_obj.animation_data_create()
        arm_obj.animation_data.action = bpy.data.actions[action]
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        path = os.path.join(RENDER_DIR, "spider-%s.png" % label)
        scene.render.filepath = path
        done = False
        try:
            bpy.ops.render.render(write_still=True)
            done = True
        except Exception as exc:
            if engine == "EEVEE":
                print("[spider] EEVEE failed (%s); falling back to Workbench" % exc)
                try:
                    scene.render.engine = "BLENDER_WORKBENCH"
                    scene.display.shading.light = "STUDIO"
                    scene.display.shading.color_type = "MATERIAL"
                    engine = "WORKBENCH"
                    bpy.ops.render.render(write_still=True)
                    done = True
                except Exception as exc2:
                    print("[spider] renders skipped: %s" % exc2)
            else:
                print("[spider] renders skipped: %s" % exc)
        if done:
            paths.append(path)
            print("[spider] rendered %s (%s, %d bytes)" % (path, engine, os.path.getsize(path)))
        if not done:
            break
    arm_obj.animation_data.action = None
    scene.frame_set(0)
    clear_pose()
    # The render rig must not leak into the GLB: drop every helper object and
    # the datablocks that only existed to take the pictures.
    scene.camera = None
    for ob in list(bpy.data.objects):
        if ob.name in ("spider_cam", "sun", "fill", "key", "ground"):
            bpy.data.objects.remove(ob, do_unlink=True)
    for blk in (bpy.data.cameras, bpy.data.lights, bpy.data.meshes,
                bpy.data.materials, bpy.data.worlds):
        for item in list(blk):
            if item.users == 0:
                blk.remove(item)
    print("[spider] render rig removed before export")
    return paths


RENDERS = try_render()
if not RENDERS:
    print("[spider] renders skipped: none produced")

# ===================================================================== export

arm_obj.animation_data_create()
arm_obj.animation_data.action = None
kwargs = dict(filepath=OUT, export_format="GLB", export_yup=True, export_apply=False,
              export_animations=True, export_animation_mode="ACTIONS",
              export_skins=True, export_optimize_animation_size=False,
              export_extras=True, export_image_format="AUTO")
try:
    bpy.ops.export_scene.gltf(**kwargs)
except TypeError as exc:
    print("[spider] export kwargs rejected (%s); retrying minimal" % exc)
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True,
                              export_apply=False, export_animations=True,
                              export_animation_mode="ACTIONS")
print("[spider] exported %s (%d bytes)" % (OUT, os.path.getsize(OUT)))

# --------------------------------------------------------------- GLB readback
try:
    with open(OUT, "rb") as fh:
        raw = fh.read()
    off = 12
    gj = None
    while off < len(raw):
        clen, ctype = struct.unpack("<II", raw[off:off + 8])
        if ctype == 0x4E4F534A:
            gj = json.loads(raw[off + 8:off + 8 + clen].decode("utf-8"))
            break
        off += 8 + clen
    if gj is None:
        print("[spider] glb readback: no JSON chunk found")
    else:
        nodes = [n.get("name") for n in gj.get("nodes", [])]
        lod_nodes = [n for n in nodes if n in ("LOD0", "LOD1")]
        print("[spider] glb meshes=%s" % [m.get("name") for m in gj.get("meshes", [])])
        print("[spider] glb lod_nodes=%s count=%d" % (lod_nodes, len(lod_nodes)))
        print("[spider] glb images=%s" % [(i.get("name"), i.get("mimeType")) for i in gj.get("images", [])])
        print("[spider] glb materials=%s" % [m.get("name") for m in gj.get("materials", [])])
        print("[spider] glb animations=%s" % sorted(a.get("name") for a in gj.get("animations", [])))
        print("[spider] glb skins=%d joints=%s"
              % (len(gj.get("skins", [])), [len(s.get("joints", [])) for s in gj.get("skins", [])]))
        print("[spider] glb size_mb=%.2f nodes=%d" % (len(raw) / 1048576.0, len(nodes)))
        if len(lod_nodes) != 2:
            print("[spider] FAIL: LOD1 not present inside the GLB; writing a sidecar file instead")
            arm_obj.animation_data.action = None
            bpy.ops.object.select_all(action="DESELECT")
            lod1.select_set(True)
            side = os.path.join(os.path.dirname(OUT), "acromantula_lod1.glb")
            bpy.ops.export_scene.gltf(filepath=side, export_format="GLB", export_yup=True,
                                      use_selection=True, export_apply=False,
                                      export_animations=False, export_skins=True)
            lod1.select_set(False)
            print("[spider] wrote sidecar %s (%d bytes)" % (side, os.path.getsize(side)))
except Exception as exc:
    print("[spider] glb readback failed: %s" % exc)

print("[spider] DONE")
