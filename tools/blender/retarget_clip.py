"""Retarget one generated motion clip onto the shipping hero rig and export it
as a small clip GLB the game merges at runtime.

Source today: fal-ai/hunyuan-motion (text -> SMPL-H FBX, 30 fps). The hero GLB
(`assets/models/characters/hero_wizard.glb`, humanoid bone names, A-pose rest)
is never rebuilt: the clip ships in its own GLB under
`assets/animations/hero/` (the hero armature, a one-triangle carrier mesh so
Godot imports a Skeleton3D, and the clip), and `HeroAnimation.merge_extra_clips`
adds it to the hero's library.

Why not hero_common.bake_retarget: that transfers the source's pose DELTA onto
the target rest, which is right only when both rigs share a rest pose. SMPL
rests in a T-pose, the hero in an A-pose, so each limb first gets a rest
alignment Q (the swing that turns the hero bone onto the source bone's rest
direction), then the source delta:

    R_world(dst, f) = delta_src(f) * Q * R_rest_world(dst)

Only rotations are transferred (plus the hips' height-scaled travel), so bone
lengths never stretch however different the proportions are.

Run:
  blender --background --python retarget_clip.py -- <clip.fbx> <out.glb> <ClipName>
          [--hand Right|Left] [--trim START END] [--release FRAME] [--spine-scale K] [--render <dir>]

Writes <out>.json: frame range, length, release frame/fraction (the frame the
wand hand is furthest in front of the chest) and the per-frame reach.
"""
import bpy, os, sys, json, math
from mathutils import Vector, Matrix, Quaternion

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) < 3:
    raise SystemExit("usage: retarget_clip.py -- <clip.fbx> <out.glb> <ClipName> [--hand Right] [--trim A B] [--render dir]")
FBX, OUT, CLIP = os.path.abspath(argv[0]), os.path.abspath(argv[1]), argv[2]
HAND = "Right"
TRIM = None
RENDER = None
RELEASE = None
SPINE_SCALE = 1.0
i = 3
while i < len(argv):
    if argv[i] == "--hand":
        HAND = argv[i + 1].capitalize(); i += 2
    elif argv[i] == "--trim":
        TRIM = (int(argv[i + 1]), int(argv[i + 2])); i += 3
    elif argv[i] == "--spine-scale":
        SPINE_SCALE = float(argv[i + 1]); i += 2
    elif argv[i] == "--release":
        RELEASE = int(argv[i + 1]); i += 2
    elif argv[i] == "--render":
        RENDER = os.path.abspath(argv[i + 1]); i += 2
    else:
        raise SystemExit("unknown argument %s" % argv[i])

HERE = os.path.dirname(os.path.abspath(__file__))
HERO_GLB = os.path.normpath(os.path.join(HERE, "..", "..", "assets", "models", "characters", "hero_wizard.glb"))
FPS = 30

# Source bone -> hero bone, per source skeleton (detected by its bone names).
PROFILES = {
    "smpl": {
        "detect": "L_Hip",
        "map": {
            "Pelvis": "Hips", "Spine1": "Spine", "Spine2": "Chest", "Spine3": "UpperChest", "Neck": "Neck",
            "L_Collar": "LeftShoulder", "L_Shoulder": "LeftUpperArm", "L_Elbow": "LeftLowerArm", "L_Wrist": "LeftHand",
            "R_Collar": "RightShoulder", "R_Shoulder": "RightUpperArm", "R_Elbow": "RightLowerArm", "R_Wrist": "RightHand",
            "L_Hip": "LeftUpperLeg", "L_Knee": "LeftLowerLeg", "L_Ankle": "LeftFoot",
            "R_Hip": "RightUpperLeg", "R_Knee": "RightLowerLeg", "R_Ankle": "RightFoot",
        },
        # (source bone, source child) whose head-to-head direction defines the
        # limb; the hero side uses the mapped pair.
        "aim": {
            "L_Collar": "L_Shoulder", "L_Shoulder": "L_Elbow", "L_Elbow": "L_Wrist", "L_Wrist": "L_Middle1",
            "R_Collar": "R_Shoulder", "R_Shoulder": "R_Elbow", "R_Elbow": "R_Wrist", "R_Wrist": "R_Middle1",
            "L_Hip": "L_Knee", "L_Knee": "L_Ankle", "R_Hip": "R_Knee", "R_Knee": "R_Ankle",
        },
        "aim_dst_child": {"LeftHand": "LeftMiddleProximal", "RightHand": "RightMiddleProximal"},
        "root": "Pelvis",
    },
}

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS

# ---------------------------------------------------------------- hero
print("[clip] importing hero %s" % HERO_GLB)
bpy.ops.import_scene.gltf(filepath=HERO_GLB)
hero = next(ob for ob in bpy.data.objects if ob.type == "ARMATURE")
hero.animation_data_create()
hero.animation_data.action = None
for act in list(bpy.data.actions):
    bpy.data.actions.remove(act)
for ob in list(bpy.data.objects):
    if ob.type == "MESH":
        bpy.data.objects.remove(ob, do_unlink=True)
for pb in hero.pose.bones:
    pb.rotation_mode = "QUATERNION"
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.scale = (1, 1, 1)
# One triangle skinned to the hips: the glTF needs a skin for Godot to build a
# Skeleton3D (bare joints import as plain nodes, whose tracks would not match).
mesh = bpy.data.meshes.new("ClipCarrier")
mesh.from_pydata([(0, 0, 0.9), (0.01, 0, 0.9), (0, 0.01, 0.9)], [], [(0, 1, 2)])
carrier = bpy.data.objects.new("ClipCarrier", mesh)
bpy.context.collection.objects.link(carrier)
carrier.parent = hero
group = carrier.vertex_groups.new(name="Hips")
group.add([0, 1, 2], 1.0, "REPLACE")
carrier.modifiers.new("Armature", "ARMATURE").object = hero
print("[clip] hero %s (%d bones)" % (hero.name, len(hero.data.bones)))

# ---------------------------------------------------------------- source
known = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=FBX, ignore_leaf_bones=True)
src = next(ob for ob in bpy.data.objects if ob.type == "ARMATURE" and ob not in known)
for ob in list(bpy.data.objects):
    if ob not in known and ob != src:
        bpy.data.objects.remove(ob, do_unlink=True)
profile = next(p for p in PROFILES.values() if p["detect"] in src.data.bones)
action = src.animation_data.action
if TRIM:
    action.frame_range = TRIM
    action.use_frame_range = True
f0, f1 = int(action.frame_range[0]), int(action.frame_range[1])
bone_map = {s: d for s, d in profile["map"].items() if s in src.data.bones and d in hero.data.bones}
print("[clip] source %s, %d bones mapped, frames %d-%d" % (src.name, len(bone_map), f0, f1))

def head_world(arm, name, posed=False):
    if posed:
        return arm.matrix_world @ arm.pose.bones[name].head
    return arm.matrix_world @ arm.data.bones[name].head_local

def rest_rot_world(arm, name):
    return (arm.matrix_world @ arm.data.bones[name].matrix_local).to_quaternion()

# Rest alignment per mapped hero bone.
scene.frame_set(f0)
src.animation_data.action = None
for pb in src.pose.bones:
    pb.matrix_basis = Matrix.Identity(4)
bpy.context.view_layer.update()
dst_of = {d: s for s, d in bone_map.items()}
align = {}
for s, d in bone_map.items():
    child_s = profile["aim"].get(s)
    if child_s is None or child_s not in src.data.bones:
        continue
    child_d = bone_map.get(child_s) or profile["aim_dst_child"].get(d)
    if child_d is None or child_d not in hero.data.bones:
        continue
    v_src = head_world(src, child_s) - head_world(src, s)
    v_dst = head_world(hero, child_d) - head_world(hero, d)
    align[d] = v_dst.normalized().rotation_difference(v_src.normalized())
src_rest_rot = {s: rest_rot_world(src, s) for s in bone_map}
dst_rest_rot = {d: rest_rot_world(hero, d) for d in bone_map.values()}
src_root = profile["root"]
src_root_rest = head_world(src, src_root)
height_ratio = head_world(hero, "Hips").z / max(0.05, src_root_rest.z - min(head_world(src, n).z for n in ("L_Ankle", "R_Ankle")))
print("[clip] aligned limbs: %s; hips height ratio %.3f" % (sorted(align), height_ratio))

def alignment_for(name):
    bone = hero.data.bones[name]
    while bone is not None:
        if bone.name in align:
            return align[bone.name]
        bone = bone.parent
    return Quaternion()

order = []
def walk(bone):
    order.append(bone.name)
    for c in bone.children:
        walk(c)
for b in hero.data.bones:
    if b.parent is None:
        walk(b)

# ---------------------------------------------------------------- bake
src.animation_data.action = action
scene.frame_set(f0)
root_start = head_world(src, src_root, True)
clip = bpy.data.actions.new(CLIP)
clip.use_fake_user = True
hero.animation_data.action = clip
hero_world_rot_inv = hero.matrix_world.to_quaternion().inverted()
hero_world_inv = hero.matrix_world.inverted()
rest_local = {b.name: b.matrix_local for b in hero.data.bones}
for frame in range(f0, f1 + 1):
    scene.frame_set(frame)
    pose_arm = {}
    for name in order:
        bone = hero.data.bones[name]
        parent = bone.parent
        follow = (pose_arm[parent.name] @ (rest_local[parent.name].inverted() @ rest_local[name])) if parent else rest_local[name]
        s = dst_of.get(name)
        if s is not None:
            src_world = (src.matrix_world @ src.pose.bones[s].matrix).to_quaternion()
            delta = src_world @ src_rest_rot[s].inverted()
            q_world = delta @ alignment_for(name) @ dst_rest_rot[name]
            q_arm = hero_world_rot_inv @ q_world
            target = q_arm.to_matrix().to_4x4()
            target.translation = follow.translation
            if s == src_root:
                # In place: the hips bob and sway in height only, never travel.
                # Measured from the clip's first frame: SMPL's rest puts the
                # pelvis at the armature origin, not at standing height.
                travel = (head_world(src, s, True) - root_start) * height_ratio
                travel.x = 0.0
                travel.y = 0.0
                target.translation = follow.translation + (hero_world_inv.to_3x3() @ travel)
            pose_arm[name] = target
        else:
            pose_arm[name] = follow
        base = follow if parent else rest_local[name]
        local = base.inverted() @ pose_arm[name] if parent else rest_local[name].inverted() @ pose_arm[name]
        loc, rot, _ = local.decompose()
        pb = hero.pose.bones[name]
        pb.rotation_quaternion = rot.normalized()
        pb.location = loc if s == src_root else Vector((0, 0, 0))
        pb.keyframe_insert("rotation_quaternion", frame=frame - f0)
        if s == src_root:
            pb.keyframe_insert("location", frame=frame - f0)
src.animation_data.action = None

n = f1 - f0
print("[clip] baked %s: %d frames" % (CLIP, n + 1))

# ---------------------------------------------------------------- release beat
hand = HAND + "Hand"
best, best_frame, reach, lift, side = -1e9, 0, [], [], []
facing = hero.matrix_world.to_3x3() @ Vector((0, -1, 0))   # the hero faces -Y in Blender
for frame in range(0, n + 1):
    scene.frame_set(frame)
    d = head_world(hero, hand, True) - head_world(hero, "UpperChest", True)
    forward = d.dot(facing.normalized())
    reach.append(round(forward, 3))
    lift.append(round(d.z, 3))
    side.append(round(d.x, 3))
    if forward > best:
        best, best_frame = forward, frame
if RELEASE is not None:
    # A plateau (arm held out) peaks late; the caller names the snap frame.
    best_frame = max(0, min(n, RELEASE))
    best = reach[best_frame]
length = n / FPS
release_fraction = best_frame / max(1, n)
print("[clip] %s %.2fs, release frame %d (fraction %.3f, hand %.2f m ahead of the chest)"
      % (CLIP, length, best_frame, release_fraction, best))

# ---------------------------------------------------------------- upper variant
upper = clip.copy()
upper.name = CLIP + "_Upper"
upper.use_fake_user = True
LOWER = ("Root", "Hips", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
         "RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes")

def fcurves_of(act):
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                out.extend(bag.fcurves)
    return out

def remove_fcurve(act, fc):
    if hasattr(act, "fcurves"):
        act.fcurves.remove(fc)
        return
    for layer in act.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                if fc in list(bag.fcurves):
                    bag.fcurves.remove(fc)
                    return

removed = 0
for fc in fcurves_of(upper):
    bone = fc.data_path.split('"')[1] if '"' in fc.data_path else ""
    if bone in LOWER:
        remove_fcurve(upper, fc)
        removed += 1
print("[clip] %s: stripped %d lower-body fcurves" % (upper.name, removed))

# The upper layer keeps the spine but not the knees, so a crouching bend reads
# as a bow over straight legs. --spine-scale softens the spine's rotation in
# the upper variant only (the arms ride on it, so a slam stays a forward push).
if SPINE_SCALE < 0.999:
    for bone in ("Spine", "Chest", "UpperChest", "Neck"):
        path = 'pose.bones["%s"].rotation_quaternion' % bone
        curves = {fc.array_index: fc for fc in fcurves_of(upper) if fc.data_path == path}
        if len(curves) != 4:
            continue
        for k in range(len(curves[0].keyframe_points)):
            q = Quaternion([curves[c].keyframe_points[k].co[1] for c in range(4)])
            q = Quaternion().slerp(q, SPINE_SCALE)
            for c in range(4):
                kp = curves[c].keyframe_points[k]
                kp.co[1] = q[c]
                kp.handle_left[1] = q[c]
                kp.handle_right[1] = q[c]
    print("[clip] %s: spine rotation scaled by %.2f" % (upper.name, SPINE_SCALE))

# ---------------------------------------------------------------- render check
if RENDER:
    os.makedirs(RENDER, exist_ok=True)
    hero.animation_data.action = clip
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 420
    scene.render.resolution_y = 420
    hero.data.display_type = "STICK"
    hero.show_in_front = True
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    # Three-quarter view from the hero's front-right.
    cam.location = Vector((-2.2, -2.6, 1.3))
    cam.rotation_euler = (Vector((0, 0, 1.1)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    picks = sorted({0, best_frame // 2, best_frame, (best_frame + n) // 2, n})
    for k, frame in enumerate(picks):
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(RENDER, "%s-%d-f%02d.png" % (CLIP, k, frame))
        bpy.ops.render.render(write_still=True)

# ---------------------------------------------------------------- export
bpy.data.objects.remove(src, do_unlink=True)
for act in list(bpy.data.actions):
    if act not in (clip, upper):
        bpy.data.actions.remove(act)
hero.animation_data.action = None
for pb in hero.pose.bones:
    pb.matrix_basis = Matrix.Identity(4)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
kwargs = dict(filepath=OUT, export_format="GLB", export_yup=True, export_animations=True,
              export_animation_mode="ACTIONS", export_force_sampling=True,
              export_skins=True, export_materials="NONE")
try:
    bpy.ops.export_scene.gltf(**kwargs)
except TypeError as exc:
    print("[clip] export kwargs rejected (%s); retrying minimal" % exc)
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, export_animations=True)
meta = {
    "clip": CLIP, "upper": CLIP + "_Upper", "source": os.path.basename(FBX),
    "fps": FPS, "frames": n + 1, "length": round(length, 4),
    "release_frame": best_frame, "release_fraction": round(release_fraction, 4),
    "hand": hand, "reach": reach, "lift": lift, "side": side,
}
with open(os.path.splitext(OUT)[0] + ".json", "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)
print("[clip] exported %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
