"""Author the rig flight broom (broom tasks).

Not a scaled primitive: a shaped, slightly-curved shaft with a wrapped leather
grip, two foot pegs, a metal ferrule, a leather seat pad and a flared bristle
bundle, with generated base-colour/roughness textures packed into the GLB.

Authoring convention "forward +Z for vehicles":
  Blender is Z-up / -Y-forward, and the glTF exporter maps Blender -Y -> glTF +Z,
  so a nose authored towards -Y lands at +Z in Godot. Up stays +Y in Godot.

Sockets (single documented convention, exported as empties):
  MountRoot  - the point the rider's mount node attaches to (shaft centre, at the seat)
  SeatSocket - where the rider's hips sit (must coincide with the hero's Socket_Hips)
  GripSocket - the two-handed grip centre
  TailSocket - bristle tip, the trail/thrust origin

Run:  blender --background --python build_broom.py -- <out.glb> [--render <dir>]
"""
import bpy, bmesh, sys, math, os, random
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
RENDER_DIR = None
if "--render" in argv:
    RENDER_DIR = argv[argv.index("--render") + 1]

random.seed(20261004)

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

# geometry constants (metres), authored along -Y forward
NOSE_Y = -0.95          # nose tip (forward)
TAIL_Y = 0.82           # shaft meets the ferrule
BRISTLE_END = 1.34      # bristle tips (rear)
SEAT_Y = 0.30
GRIP_FRONT_Y = -0.50
GRIP_BACK_Y = 0.04
PEG_Y = -0.10
R_NOSE, R_MID, R_TAIL = 0.028, 0.036, 0.044


def make_material(name, color, rough, metal=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    mat.diffuse_color = (color[0], color[1], color[2], 1.0)
    mat.roughness = rough
    mat.metallic = metal
    return mat


def make_texture(name, size, fn):
    """Generate a packed sRGB-ish base-colour image from a pixel function."""
    img = bpy.data.images.new(name, size, size, alpha=False)
    px = [0.0] * (size * size * 4)
    for y in range(size):
        v = y / (size - 1)
        for x in range(size):
            u = x / (size - 1)
            r, g, b = fn(u, v)
            i = (y * size + x) * 4
            px[i] = r
            px[i + 1] = g
            px[i + 2] = b
            px[i + 3] = 1.0
    img.pixels.foreach_set(px)
    img.pack()
    return img


def _fbm(u, v, seed, octaves=4):
    """Cheap value-noise fbm (deterministic, no numpy needed)."""
    def corner(ix, iy):
        return random.Random((ix * 73856093) ^ (iy * 19349663) ^ seed).random()

    total, amp, freq = 0.0, 0.5, 4.0
    for _ in range(octaves):
        x, y = u * freq, v * freq
        ix, iy = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - ix, y - iy
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        a = corner(ix, iy) * (1 - fx) + corner(ix + 1, iy) * fx
        b = corner(ix, iy + 1) * (1 - fx) + corner(ix + 1, iy + 1) * fx
        total += (a * (1 - fy) + b * fy) * amp
        amp *= 0.5
        freq *= 2.0
    return total


def wood_px(u, v):
    # grain runs along U (the shaft's unwrapped axis), knots via fbm
    grain = 0.5 + 0.5 * math.sin((v * 22.0 + _fbm(u, v, 11) * 5.0) * math.pi)
    streak = _fbm(u * 3.0, v, 12, 5)
    t = 0.55 * grain + 0.45 * streak
    r = 0.34 + 0.22 * t
    g = 0.21 + 0.15 * t
    b = 0.10 + 0.07 * t
    return (r, g, b)


def straw_px(u, v):
    streak = _fbm(u * 6.0, v * 40.0, 21, 3)
    t = 0.35 + 0.65 * streak
    r = 0.62 + 0.25 * t
    g = 0.50 + 0.22 * t
    b = 0.20 + 0.12 * t
    return (r, g, b)


def leather_px(u, v):
    n = _fbm(u * 8.0, v * 8.0, 31, 5)
    t = 0.5 + 0.5 * n
    r = 0.16 + 0.10 * t
    g = 0.10 + 0.07 * t
    b = 0.07 + 0.05 * t
    return (r, g, b)


def wood_rough(u, v):
    t = _fbm(u * 2.0, v, 13, 4)
    r = 0.55 + 0.3 * t
    return (r, r, r)


print("[broom] generating textures")
tex_wood = make_texture("broom_wood_basecolor", 512, wood_px)
tex_straw = make_texture("broom_straw_basecolor", 512, straw_px)
tex_leather = make_texture("broom_leather_basecolor", 256, leather_px)
tex_wood_rough = make_texture("broom_wood_rough", 256, wood_rough)

MAT_WOOD = make_material("Broom_Wood", (0.36, 0.22, 0.11), 0.62)
MAT_GRIP = make_material("Broom_Grip", (0.17, 0.11, 0.07), 0.78)
MAT_BRISTLE = make_material("Broom_Bristles", (0.68, 0.55, 0.25), 0.88)
MAT_METAL = make_material("Broom_Metal", (0.42, 0.40, 0.36), 0.42, 0.85)
MAT_SEAT = make_material("Broom_Seat", (0.14, 0.09, 0.06), 0.72)


def hook_texture(mat, image, rough_image=None):
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.location = (-400, 300)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if rough_image is not None:
        rtex = nt.nodes.new("ShaderNodeTexImage")
        rtex.image = rough_image
        rtex.image.colorspace_settings.name = "Non-Color"
        rtex.location = (-400, 0)
        nt.links.new(rtex.outputs["Color"], bsdf.inputs["Roughness"])


hook_texture(MAT_WOOD, tex_wood, tex_wood_rough)
hook_texture(MAT_GRIP, tex_leather)
hook_texture(MAT_BRISTLE, tex_straw)
hook_texture(MAT_SEAT, tex_leather)

# ---------------------------------------------------------------- mesh helpers
class MeshBuilder:
    def __init__(self):
        self.verts = []
        self.faces = []
        self.uvs = []      # per-loop uv
        self.mat_faces = []  # per-face material index

    def add_quad(self, a, b, c, d, uv, mat):
        base = len(self.verts)
        self.verts.extend([a, b, c, d])
        self.faces.append((base, base + 1, base + 2, base + 3))
        self.uvs.extend(uv)
        self.mat_faces.append(mat)

    def add_tri(self, a, b, c, uv, mat):
        base = len(self.verts)
        self.verts.extend([a, b, c])
        self.faces.append((base, base + 1, base + 2))
        self.uvs.extend(uv)
        self.mat_faces.append(mat)

    def to_object(self, name, materials):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.verts, [], self.faces)
        me.validate()
        uv_layer = me.uv_layers.new(name="UVMap")
        for i, uv in enumerate(self.uvs):
            uv_layer.data[i].uv = uv
        for mat in materials:
            me.materials.append(mat)
        for poly, mi in zip(me.polygons, self.mat_faces):
            poly.material_index = mi
        me.update()
        ob = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(ob)
        return ob


def shaft_point(t):
    """Shaft centre line: nose at t=0 (-Y) to tail at t=1 (+Y), nose lifts up."""
    y = NOSE_Y + (TAIL_Y - NOSE_Y) * t
    z = 0.075 * math.sin(math.pi * (1.0 - t) * 0.5) ** 2  # gentle upward curl at the nose
    return y, z


def shaft_radius(t):
    if t < 0.10:
        return R_MID + (R_NOSE - R_MID) * (0.10 - t) / 0.10
    return R_MID + (R_TAIL - R_MID) * (t - 0.10) / 0.90


def build_shaft_proper(mb, mat_wood, segments=14, rings=26):
    ring_prev = None
    for r in range(rings + 1):
        t = r / rings
        y, z = shaft_point(t)
        rad = shaft_radius(t)
        ring = []
        for s in range(segments):
            a = 2.0 * math.pi * s / segments
            k = 1.0 + 0.06 * math.cos(a * 4.0)
            ring.append(Vector((math.cos(a) * rad * k, y, z + math.sin(a) * rad * k)))
        if ring_prev:
            for s in range(segments):
                s2 = (s + 1) % segments
                u0, u1 = s / segments, (s + 1) / segments
                v0, v1 = r / rings, (r + 1) / rings
                mb.add_quad(ring_prev[s], ring_prev[s2], ring[s2], ring[s],
                            [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], mat_wood)
        if r == 0:
            # nose cap fan
            y0, z0 = shaft_point(0.0)
            tip = Vector((0.0, y0 - 0.035, z0 + 0.008))
            for s in range(segments):
                s2 = (s + 1) % segments
                mb.add_tri(tip, ring[s], ring[s2], [(0.5, 0.0), (s / segments, 0.04), ((s + 1) / segments, 0.04)], mat_wood)
        ring_prev = ring
    # tail cap
    yt, zt = shaft_point(1.0)
    back = Vector((0.0, yt + 0.02, zt))
    for s in range(segments):
        s2 = (s + 1) % segments
        mb.add_tri(back, ring_prev[s2], ring_prev[s], [(0.5, 1.0), ((s + 1) / segments, 0.96), (s / segments, 0.96)], mat_wood)


def build_grip_wrap(mb, mat_grip, turns=9, segments=8):
    """Helical leather wrap around the grip section."""
    y0, y1 = GRIP_FRONT_Y, GRIP_BACK_Y
    width = 0.028
    prev = None
    steps = turns * 10
    for i in range(steps + 1):
        t = i / steps
        y = y0 + (y1 - y0) * t
        zz = 0.0
        rt = shaft_radius(max(0.0, (y - NOSE_Y) / (TAIL_Y - NOSE_Y))) + width * 0.5
        ang = 2.0 * math.pi * turns * t
        ring = []
        for s in range(segments):
            a = ang + 2.0 * math.pi * s / segments
            ring.append(Vector((math.cos(a) * rt, y, zz + math.sin(a) * rt)))
        if prev:
            for s in range(segments):
                s2 = (s + 1) % segments
                u0, u1 = s / segments, (s + 1) / segments
                v0, v1 = i / steps, (i + 1) / steps
                mb.add_quad(prev[s], prev[s2], ring[s2], ring[s],
                            [(u0, v0 * 4.0), (u1, v0 * 4.0), (u1, v1 * 4.0), (u0, v1 * 4.0)], mat_grip)
        prev = ring


def build_seat(mb, mat_seat):
    """Leather seat pad: a shaped saddle behind the grip."""
    cy = SEAT_Y
    top = 0.052
    profile = [
        (0.0, cy - 0.17, 0.0),
        (0.11, cy - 0.10, 0.0),
        (0.135, cy + 0.02, 0.0),
        (0.10, cy + 0.13, 0.0),
    ]
    ring_prev = None
    for (rad, y, z) in profile:
        ring = [Vector((math.cos(2 * math.pi * s / 8) * rad, y, top + math.sin(2 * math.pi * s / 8) * rad * 0.45)) for s in range(8)]
        if ring_prev:
            for s in range(8):
                s2 = (s + 1) % 8
                mb.add_quad(ring_prev[s], ring_prev[s2], ring[s2], ring[s],
                            [(s / 8, 0.0), ((s + 1) / 8, 0.0), ((s + 1) / 8, 0.3), (s / 8, 0.3)], mat_seat)
        ring_prev = ring
    # rear + front caps
    for idx, flip in ((0, False), (len(profile) - 1, True)):
        rad, y, z = profile[idx]
        ring = [Vector((math.cos(2 * math.pi * s / 8) * rad, y, top + math.sin(2 * math.pi * s / 8) * rad * 0.45)) for s in range(8)]
        ctr = Vector((0.0, y + (-0.03 if flip else 0.03), z + top))
        for s in range(8):
            s2 = (s + 1) % 8
            if flip:
                mb.add_tri(ctr, ring[s2], ring[s], [(0.5, 0.5), ((s2) / 8, 0.5), (s / 8, 0.5)], mat_seat)
            else:
                mb.add_tri(ctr, ring[s], ring[s2], [(0.5, 0.5), (s / 8, 0.5), (s2 / 8, 0.5)], mat_seat)


def build_pegs(mb, mat_wood):
    for side in (-1, 1):
        x = side * 0.20
        y = PEG_Y
        # short angled peg with a knob
        p0 = Vector((side * 0.045, y, -0.02))
        p1 = Vector((x, y - 0.02, -0.075))
        r = 0.023
        ring0 = [Vector((p0.x + math.cos(2 * math.pi * s / 6) * r, p0.y + math.sin(2 * math.pi * s / 6) * r, p0.z)) for s in range(6)]
        ring1 = [Vector((p1.x + math.cos(2 * math.pi * s / 6) * r * 0.85, p1.y + math.sin(2 * math.pi * s / 6) * r * 0.85, p1.z)) for s in range(6)]
        for s in range(6):
            s2 = (s + 1) % 6
            mb.add_quad(ring0[s], ring0[s2], ring1[s2], ring1[s],
                        [(s / 6, 0.0), ((s + 1) / 6, 0.0), ((s + 1) / 6, 1.0), (s / 6, 1.0)], mat_wood)


def build_ferrule(mb, mat_metal, segments=14):
    y0, y1 = TAIL_Y - 0.12, TAIL_Y + 0.02
    r0 = shaft_radius((y0 - NOSE_Y) / (TAIL_Y - NOSE_Y)) * 1.32
    r1 = r0 * 0.92
    ring_prev = None
    for (y, rad) in ((y0, r0), (y1, r1), (y1 + 0.02, r1)):
        ring = [Vector((math.cos(2 * math.pi * s / segments) * rad, y, math.sin(2 * math.pi * s / segments) * rad)) for s in range(segments)]
        if ring_prev:
            for s in range(segments):
                s2 = (s + 1) % segments
                mb.add_quad(ring_prev[s], ring_prev[s2], ring[s2], ring[s],
                            [(s / segments, 0.0), ((s + 1) / segments, 0.0), ((s + 1) / segments, 1.0), (s / segments, 1.0)], mat_metal)
        ring_prev = ring


def build_bristles(mb, mat_bristle, strands=84):
    """Flared bundle of tapered straw strands, plus an inner core."""
    base_y = TAIL_Y + 0.02
    for i in range(strands):
        ang = 2.0 * math.pi * (i * 0.618034)  # golden-angle scatter
        tier = (i % 3) / 3.0
        rad0 = 0.026 + tier * 0.030
        spread = 0.040 + tier * 0.048
        length = 0.40 + (0.05 if i % 4 == 0 else 0.0) - tier * 0.04
        jitter = random.uniform(-0.015, 0.015)
        a0 = Vector((math.cos(ang) * rad0, base_y, math.sin(ang) * rad0))
        a1 = Vector((math.cos(ang) * (rad0 + spread * 0.6), base_y + length * 0.55, math.sin(ang) * (rad0 + spread * 0.6) + jitter))
        a2 = Vector((math.cos(ang) * (rad0 + spread), base_y + length, math.sin(ang) * (rad0 + spread) + jitter * 2.0))
        w = 0.016
        up = Vector((0, 0, 1))
        side = Vector((-math.sin(ang), 0, math.cos(ang))) * w
        # 3-segment tapered quad strip (2 quads per strand)
        for (p, q, u0, u1) in ((a0, a1, 0.0, 0.55), (a1, a2, 0.55, 1.0)):
            w0 = w * (1.0 - u0 * 0.75)
            w1 = w * (1.0 - u1 * 0.75)
            s0 = side.normalized() * w0
            s1 = side.normalized() * w1
            mb.add_quad(p - s0, p + s0, q + s1, q - s1,
                        [(0.0, u0), (1.0, u0), (1.0, u1), (0.0, u1)], mat_bristle)
            mb.add_quad(p - s0, q - s1, q + s1, p + s0,
                        [(0.0, u0), (1.0, u1), (1.0, u1), (0.0, u0)], mat_bristle)


print("[broom] building meshes")
mb_shaft = MeshBuilder()
build_shaft_proper(mb_shaft, 0)
build_grip_wrap(mb_shaft, 1)
build_seat(mb_shaft, 4)
build_pegs(mb_shaft, 0)
build_ferrule(mb_shaft, 3)
shaft_obj = mb_shaft.to_object("Broom_Shaft", [MAT_WOOD, MAT_GRIP, MAT_BRISTLE, MAT_METAL, MAT_SEAT])

mb_bristles = MeshBuilder()
build_bristles(mb_bristles, 0)
bristles_obj = mb_bristles.to_object("Bristles", [MAT_BRISTLE])
# Give the bundle its own origin at the middle of the bristles, so the node's
# position (which the client and the offline harness read) sits at the bundle
# rather than at the world origin.
_bristle_centre = Vector((0.0, (TAIL_Y + BRISTLE_END) * 0.5, 0.0))
for _v in bristles_obj.data.vertices:
    _v.co -= _bristle_centre
bristles_obj.location = _bristle_centre

# ---------------------------------------------------------------- hierarchy
root = bpy.data.objects.new("BroomRoot", None)
root.empty_display_size = 0.25
bpy.context.collection.objects.link(root)

shaft_obj.parent = root
# The bristle bundle stays a top-level node on purpose: Godot's glTF importer
# adds a file-named scene root, and the client binds `Visuals/BroomMesh/Bristles`
# as the trail/thrust origin, so Bristles must be a direct child of that root.
bristles_obj.parent = None

def add_socket(name, location):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.12
    ob.location = Vector(location)
    bpy.context.collection.objects.link(ob)
    ob.parent = root
    return ob

# Godot-space (+Z forward, +Y up) -> Blender (-Y forward, +Z up): (x, y, z)_blender = (x_g, -z_g, y_g)
seat_bl = (0.0, SEAT_Y, 0.06)
add_socket("MountRoot", seat_bl)
add_socket("SeatSocket", (0.0, SEAT_Y + 0.02, 0.18))       # hips ride 0.18 above the shaft
add_socket("GripSocket", (0.0, (GRIP_FRONT_Y + GRIP_BACK_Y) * 0.5, 0.0))
add_socket("TailSocket", (0.0, BRISTLE_END, 0.0))

# ---------------------------------------------------------------- report + render
deps = bpy.context.evaluated_depsgraph_get()
tri_total = 0
for ob in bpy.data.objects:
    if ob.type == "MESH":
        me = ob.evaluated_get(deps).to_mesh()
        tris = sum(len(p.vertices) - 2 for p in me.polygons)
        print("[broom] mesh %s: %d tris" % (ob.name, tris))
        tri_total += tris
print("[broom] total tris: %d" % tri_total)
print("[broom] bbox: %s" % [tuple(round(c, 3) for c in ob.dimensions) for ob in bpy.data.objects if ob.type == "MESH"])

if RENDER_DIR:
    os.makedirs(RENDER_DIR, exist_ok=True)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 700
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    views = {
        "front": (0.0, -4.2, 0.6),     # looking at the nose (forward = -Y)
        "side": (4.2, 0.1, 0.6),
        "rear": (0.0, 4.2, 0.6),
        "three_quarter": (3.0, -3.0, 1.6),
    }
    target = Vector((0.0, 0.05, 0.05))
    for name, pos in views.items():
        cam.location = Vector(pos)
        direction = target - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = os.path.join(RENDER_DIR, "broom-%s.png" % name)
        bpy.ops.render.render(write_still=True)
        print("[broom] rendered %s" % scene.render.filepath)

# ---------------------------------------------------------------- export
kwargs = dict(filepath=OUT, export_format="GLB", export_yup=True, export_apply=True)
try:
    bpy.ops.export_scene.gltf(export_animations=False, **kwargs)
except TypeError:
    bpy.ops.export_scene.gltf(**kwargs)
print("[broom] exported %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
