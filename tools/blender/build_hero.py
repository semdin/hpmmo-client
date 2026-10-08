"""Build the rig hero (character + broom-rider tasks).

Body: quaternius-hooded-adventurer (CC0 1.0, 1.877 m, 7,276 tris, 62-joint rig).
Clips:
  * native clips shipped with the body pack, renamed to the project convention
    (idle / walk / run / strafe / interaction / hit / death / melee),
  * the clips the body pack lacks, retargeted from the Quaternius Universal
    Animation Library (CC0 1.0) with the documented bone map in hero_common.py
    (jump / fall / land / spell casts / sitting),
  * broom-riding clips authored here by posing and keying the hero rig
    (mount, seated idle, takeoff, acceleration, cruise, bank, climb, dive,
    brake, landing, dismount) plus stun and revive,
  * upper-body-only cast variants (legs/hips stripped) for cast blending.

Materials are consolidated from 14 source slots to 5 (skin / robe / dark /
leather / trim); house colour is applied at runtime to the `Trim` and `Robe`
slots, so no second rig is needed for house variation.

Run:  blender --background --python build_hero.py -- <out.glb> [--render <dir>] [--pose-check <dir>]
"""
import bpy, sys, os, math
from mathutils import Vector, Quaternion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hero_common as hc

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
RENDER_DIR = argv[argv.index("--render") + 1] if "--render" in argv else None
POSE_CHECK = argv[argv.index("--pose-check") + 1] if "--pose-check" in argv else None

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.abspath(os.path.join(HERE, "..", "..", "assets", "candidates", "character"))
BODY_GLB = os.path.join(CAND, "quaternius-hooded-adventurer", "hooded-adventurer.glb")
UAL_GLB = os.path.join(CAND, "quaternius-universal-animation-library", "UAL1_Standard.glb")

FPS = 30
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS
scene.unit_settings.system = "METRIC"

# ---------------------------------------------------------------- import body
print("[hero] importing %s" % BODY_GLB)
bpy.ops.import_scene.gltf(filepath=BODY_GLB)
hero_arm = hc.find_armature("CharacterArmature")
assert hero_arm is not None, "hero armature not found"
hero_meshes = [ob for ob in bpy.data.objects if ob.type == "MESH" and ob.parent == hero_arm]
print("[hero] armature %s, %d bones; meshes: %s" % (hero_arm.name, len(hero_arm.data.bones), [m.name for m in hero_meshes]))
dropped = hc.purge_unwanted(hero_arm)
print("[hero] dropped artifacts: %s" % dropped)
hero_meshes = [ob for ob in bpy.data.objects if ob.type == "MESH" and ob.parent == hero_arm]

# Normalise the source transforms before doing anything else. The shipped pack
# keeps a 100x scale on the armature with compensating mesh scales, and Godot
# then renders correctly while every bone-space position (sockets, attachments)
# is off by the residual factor. Applying the transforms bakes that into the
# bones and the mesh, so bone space and visible space agree 1:1.
bpy.ops.object.select_all(action="SELECT")
for _ob in bpy.data.objects:
    if _ob.type in ("ARMATURE", "MESH", "EMPTY"):
        _ob.select_set(True)
bpy.context.view_layer.objects.active = hero_arm
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
print("[hero] applied source transforms; armature scale now %s" % (tuple(round(v, 4) for v in hero_arm.scale),))
print("[hero] mesh scales: %s" % {ob.name: tuple(round(v, 4) for v in ob.scale) for ob in hero_meshes})

FAMILY = {
    "Skin": "Hero_Skin",
    "DarkBrown": "Hero_Robe",
    "Brown": "Hero_Robe",
    "Black": "Hero_Dark",
    "LightBrown": "Hero_Leather",
    "White": "Hero_Leather",     # silver hair folds into the leather family (light tone)
    "Grey": "Hero_Leather",
    "Gold": "Hero_Trim",         # house-tinted at runtime
    "Metal": "Hero_Trim",
}
BASE_COLOR = {
    "Hero_Skin": ((0.85, 0.66, 0.50), 0.72, 0.0),
    "Hero_Robe": ((0.28, 0.13, 0.07), 0.82, 0.0),
    "Hero_Dark": ((0.07, 0.06, 0.06), 0.86, 0.0),
    "Hero_Leather": ((0.42, 0.25, 0.12), 0.78, 0.0),
    "Hero_Trim": ((0.55, 0.52, 0.45), 0.40, 0.60),
}
new_mats = {}
for fam, (col, rough, metal) in BASE_COLOR.items():
    mat = bpy.data.materials.new(fam)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (col[0], col[1], col[2], 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    mat.diffuse_color = (col[0], col[1], col[2], 1.0)
    mat.roughness = rough
    mat.metallic = metal
    new_mats[fam] = mat

slot_count_before = 0
for ob in hero_meshes:
    me = ob.data
    slot_count_before += len([m for m in me.materials if m])
    old_names = [m.name if m else "" for m in me.materials]
    fam_list = [FAMILY.get(n, "Hero_Leather") for n in old_names]
    # clear() resets every polygon to slot 0, so the original indices are read
    # out first and re-applied afterwards.
    original_indices = [poly.material_index for poly in me.polygons]
    remap = {}
    me.materials.clear()
    for i, fam in enumerate(fam_list):
        if fam not in [m.name for m in me.materials]:
            me.materials.append(new_mats[fam])
        remap[i] = [m.name for m in me.materials].index(fam)
    for poly, original in zip(me.polygons, original_indices):
        poly.material_index = remap.get(original, 0)
    print("[hero]   %s: %d -> %d slots %s" % (ob.name, len(old_names),
          len(me.materials), [m.name for m in me.materials]))
print("[hero] material slots: %d -> %d" % (slot_count_before, sum(len([m for m in ob.data.materials if m]) for ob in hero_meshes)))

# One skinned mesh, not four: fewer primitives/draw calls and a single surface
# for the runtime house-material override.
# join() reads selection from the context; in background mode the view layer's
# selection is unreliable, so drive it with an explicit override.
target = hero_meshes[0]
with bpy.context.temp_override(active_object=target, selected_editable_objects=hero_meshes,
        selected_objects=hero_meshes):
    bpy.ops.object.join()
print("[hero] joined %d meshes into %s" % (len(hero_meshes), target.name))
hero_meshes = [target]
hero_meshes[0].name = "Hero_Body"
hero_meshes[0].data.name = "Hero_Body"
slots = [m.name for m in hero_meshes[0].data.materials if m]
used = {}
for poly in hero_meshes[0].data.polygons:
    used[poly.material_index] = used.get(poly.material_index, 0) + 1
print("[hero] merged mesh %s: %d slots %s, %d verts"
      % (hero_meshes[0].name, len(slots), slots, len(hero_meshes[0].data.vertices)))
print("[hero] faces per slot: %s" % {slots[i] if i < len(slots) else i: n for i, n in sorted(used.items())})
# Only slots that actually carry faces are exported; drop empty ones so the
# runtime material lookup cannot bind to a slot that never ships.
keep_indices = sorted(used.keys())
if len(keep_indices) != len(slots):
    new_slots = [hero_meshes[0].data.materials[i] for i in keep_indices]
    old_to_new = {old: new for new, old in enumerate(keep_indices)}
    hero_meshes[0].data.materials.clear()
    for material in new_slots:
        hero_meshes[0].data.materials.append(material)
    for poly in hero_meshes[0].data.polygons:
        poly.material_index = old_to_new[poly.material_index]
    print("[hero] kept only used slots: %s" % [m.name for m in hero_meshes[0].data.materials])
hero_arm = hc.find_armature("CharacterArmature")

crown = hc.height_of(hero_arm)
print("[hero] crown height (m): %.3f" % crown)

# ---------------------------------------------------------------- native clips
NATIVE_RENAME = {
    "CharacterArmature|Idle": "Idle",
    "CharacterArmature|Walk": "Walk_A",
    "CharacterArmature|Run": "Running_A",
    "CharacterArmature|Run_Back": "Walk_Back",
    "CharacterArmature|Run_Left": "Strafe_L",
    "CharacterArmature|Run_Right": "Strafe_R",
    "CharacterArmature|Interact": "Interact",
    "CharacterArmature|HitRecieve": "Hit_A",
    "CharacterArmature|HitRecieve_2": "Hit_B",
    "CharacterArmature|Punch_Left": "Melee_Chop_A",
    "CharacterArmature|Punch_Right": "Melee_Chop_B",
    "CharacterArmature|Roll": "Roll",
    "CharacterArmature|Death": "Death_A",
    "CharacterArmature|Wave": "Emote_Wave",
}
# Clips the hero does not need: drop so the GLB carries only shipping animations.
DROP_NATIVE = [
    "CharacterArmature|Gun_Shoot", "CharacterArmature|Idle_Gun", "CharacterArmature|Idle_Gun_Pointing",
    "CharacterArmature|Idle_Gun_Shoot", "CharacterArmature|Idle_Sword", "CharacterArmature|Idle_Neutral",
    "CharacterArmature|Sword_Slash", "CharacterArmature|Run_Shoot", "CharacterArmature|Kick_Left",
    "CharacterArmature|Kick_Right",
]
for name in DROP_NATIVE:
    act = bpy.data.actions.get(name)
    if act:
        bpy.data.actions.remove(act)
hc.rename_actions(NATIVE_RENAME)
print("[hero] native clips kept: %s" % sorted(a.name for a in bpy.data.actions))

# ---------------------------------------------------------------- retarget UAL
print("[hero] importing UAL for retargeting")
hero_action_names = {a.name for a in bpy.data.actions}
bpy.ops.import_scene.gltf(filepath=UAL_GLB)
ual_arm = hc.find_armature("Armature")
assert ual_arm is not None, "UAL armature not found"
ual_action_names = {a.name for a in bpy.data.actions} - hero_action_names
print("[hero] UAL armature %s, %d bones, %d actions" % (ual_arm.name, len(ual_arm.data.bones), len(ual_action_names)))

UAL_MAP = {
    "Jump_Start": "Jump_Start",
    "Jump_Loop": "Fall_Loop",
    "Jump_Land": "Land",
    "Spell_Simple_Enter": "Spellcast_Raise",
    "Spell_Simple_Shoot": "Spellcast_Shoot",
    "Spell_Simple_Idle_Loop": "Cast_Idle_Loop",
    "Spell_Simple_Exit": "Cast_Exit",
    "Sitting_Enter": "Sit_Enter",
    "Sitting_Idle_Loop": "Sit_Chair_Idle",
    "Sitting_Exit": "Sit_Exit",
    "Driving_Loop": "Drive_Reference",     # reference pose for the authored ride set
}
for src_name, dst_name in UAL_MAP.items():
    act = bpy.data.actions.get(src_name)
    if act is None:
        print("[hero] MISSING UAL action %s" % src_name)
        continue
    tmp_name = "RT_" + dst_name
    made = hc.bake_retarget(ual_arm, act, hero_arm, tmp_name, FPS)
    if made:
        made.name = dst_name
    print("[hero] retargeted %s -> %s (%s)" % (src_name, dst_name, "ok" if made else "empty"))

# remove every object and action the UAL import brought in, so the export
# carries only the hero and its own clips
for ob in list(bpy.data.objects):
    if ob.type in ("ARMATURE", "MESH") and ob != hero_arm and ob not in hero_meshes:
        bpy.data.objects.remove(ob, do_unlink=True)
for act in list(bpy.data.actions):
    if act.name in ual_action_names:
        bpy.data.actions.remove(act)
# Blender appends .001 when a retargeted name collided with a UAL name; the
# original is gone now, so reclaim the clean name.
for act in list(bpy.data.actions):
    if act.name.endswith(".001"):
        base = act.name[:-4]
        if bpy.data.actions.get(base) is None:
            print("[hero] reclaimed action name %s -> %s" % (act.name, base))
            act.name = base
print("[hero] actions after retarget: %s" % sorted(a.name for a in bpy.data.actions))

# ---------------------------------------------------------------- authored clips
#
# The ride set is authored on the hero rig relative to a real animator pose:
# the retargeted UAL Drive_Reference frame is captured as the seat pose, and
# every authored clip composes per-bone armature-space deltas on top of it
# (lean, bank, tuck, leg swing). Deltas are applied as
#     q_local = B^-1 * D * B * q_base          (B = bone rest, armature space)
# so they are independent of the rig bone axes. Mount_Broom, Dismount_Broom,
# Broom_Takeoff, Broom_Land, Stun_Loop and Revive are keyed from the standing
# rest through to the seat pose.

AXIS = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}

FINGERS_L = [b for b in ("Index1.L", "Index2.L", "Index3.L", "Index4.L", "Middle1.L", "Middle2.L",
                         "Middle3.L", "Middle4.L", "Ring1.L", "Ring2.L", "Ring3.L", "Ring4.L",
                         "Pinky1.L", "Pinky2.L", "Pinky3.L", "Pinky4.L", "Thumb1.L", "Thumb2.L",
                         "Thumb3.L") if b in hero_arm.data.bones]
FINGERS_R = [b.replace(".L", ".R") for b in FINGERS_L]


def qrot(spec):
    q = Quaternion((1, 0, 0, 0))
    for axis, deg in spec:
        q = Quaternion(AXIS[axis], math.radians(deg)) @ q
    return q


def rest_quat(bone):
    return hero_arm.data.bones[bone].matrix_local.to_quaternion()


def capture_pose(action, frame):
    """Freeze an action frame into a {bone: (quat, loc)} snapshot."""
    hero_arm.animation_data_create()
    hero_arm.animation_data.action = action
    scene.frame_set(frame)
    snap = {}
    for pb in hero_arm.pose.bones:
        snap[pb.name] = (pb.rotation_quaternion.copy(), pb.location.copy())
    hero_arm.animation_data.action = None
    return snap


def rest_pose():
    return {pb.name: (Quaternion((1, 0, 0, 0)), Vector((0, 0, 0))) for pb in hero_arm.pose.bones}


def apply_pose(base, deltas=None, hips_offset=None):
    """base snapshot + armature-space deltas (degrees) per bone."""
    deltas = deltas or {}
    for name, (rot, loc) in base.items():
        if name not in hero_arm.pose.bones:
            continue
        pb = hero_arm.pose.bones[name]
        B = rest_quat(name)
        spec = deltas.get(name)
        if spec:
            q = qrot(spec)
            pb.rotation_quaternion = ((B.inverted() @ q @ B) @ rot).normalized()
        else:
            pb.rotation_quaternion = rot
        pb.location = loc
    hips = hero_arm.pose.bones.get("Hips")
    if hips is not None and hips_offset is not None:
        # hips_offset is authored in world metres; the armature carries a 100x
        # scale (the source rig is authored in centimetres), so convert through
        # the armature matrix before expressing it in the bone's local frame.
        B = rest_quat("Hips")
        offset_arm = hero_arm.matrix_world.inverted().to_3x3() @ hips_offset
        hips.location = hips.location + (B.inverted() @ offset_arm)


def key_all(frame):
    for pb in hero_arm.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        pb.keyframe_insert("location", frame=frame)


def author_clip(name, keys):
    """keys: list of (frame, base_snapshot, deltas, hips_offset)."""
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    hero_arm.animation_data_create()
    hero_arm.animation_data.action = act
    for f, base, deltas, offset in keys:
        apply_pose(base, deltas, offset)
        key_all(f)
    hero_arm.animation_data.action = None
    for pb in hero_arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    return act


drive = bpy.data.actions.get("Drive_Reference")
assert drive is not None, "Drive_Reference missing; cannot author ride clips"
SEAT = capture_pose(drive, 10)
STAND = rest_pose()
print("[hero] captured seat pose from Drive_Reference frame 10")

# A broom rider legs straddle the shaft: extra abduction plus a deeper grip on
# top of the driving pose.
RIDE_DELTAS = {
    "UpperLeg.L": [("Y", -16)], "UpperLeg.R": [("Y", 16)],
    "LowerLeg.L": [("Y", 6)], "LowerLeg.R": [("Y", -6)],
    "Wrist.L": [("X", -8)], "Wrist.R": [("X", -8)],
}
for b in FINGERS_L + FINGERS_R:
    RIDE_DELTAS[b] = [("X", 26)]


def ride(extra=None):
    d = {b: list(v) for b, v in RIDE_DELTAS.items()}
    for bone, spec in (extra or {}).items():
        d[bone] = d.get(bone, []) + list(spec)
    return d


LEAN_FWD = {"Hips": [("X", -12)], "Torso": [("X", -9)], "Chest": [("X", -7)], "Neck": [("X", -4)]}
LEAN_BACK = {"Hips": [("X", 10)], "Torso": [("X", 7)], "Chest": [("X", 5)], "Neck": [("X", 5)]}


def mix(base_d, extra):
    d = {b: list(v) for b, v in base_d.items()}
    for bone, spec in extra.items():
        d[bone] = d.get(bone, []) + list(spec)
    return d


print("[hero] authoring broom-riding clips")
author_clip("Broom_Seated_Idle", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (15, SEAT, ride({"Torso": [("X", -1.5)], "Neck": [("Z", -2)]}), Vector((0, 0, 0.012))),
    (30, SEAT, ride(), Vector((0, 0, 0))),
    (45, SEAT, ride({"Torso": [("X", 1.5)], "Neck": [("Z", 2)]}), Vector((0, 0, -0.01))),
    (60, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Broom_Cruise", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (12, SEAT, ride({"Hips": [("X", -2)], "Chest": [("Z", 2)]}), Vector((0, 0.006, 0.012))),
    (24, SEAT, ride(), Vector((0, 0, 0))),
    (36, SEAT, ride({"Hips": [("X", 2)], "Chest": [("Z", -2)]}), Vector((0, -0.006, -0.008))),
    (48, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Broom_Accelerate", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (8, SEAT, ride(mix(LEAN_FWD, {"UpperLeg.L": [("X", -6)], "UpperLeg.R": [("X", -6)]})),
     Vector((0, 0.02, -0.02))),
    (22, SEAT, ride(mix(LEAN_FWD, {"UpperLeg.L": [("X", -8)], "UpperLeg.R": [("X", -8)]})),
     Vector((0, 0.026, -0.028))),
    (30, SEAT, ride(LEAN_FWD), Vector((0, 0.022, -0.024))),
])
author_clip("Broom_Bank_L", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (8, SEAT, ride({"Hips": [("Y", -14)], "Torso": [("Y", -8)], "Chest": [("Y", -6)],
                    "Neck": [("Y", 8)], "Head": [("Y", 5)], "Foot.L": [("X", -6)]}),
     Vector((0.012, 0, 0.008))),
    (16, SEAT, ride({"Hips": [("Y", -22)], "Torso": [("Y", -12)], "Chest": [("Y", -8)],
                     "Neck": [("Y", 12)], "Head": [("Y", 8)], "Foot.L": [("X", -9)]}),
     Vector((0.018, 0, 0.012))),
    (24, SEAT, ride({"Hips": [("Y", -14)], "Torso": [("Y", -8)], "Chest": [("Y", -6)],
                     "Neck": [("Y", 8)]}), Vector((0.012, 0, 0.008))),
    (32, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Broom_Bank_R", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (8, SEAT, ride({"Hips": [("Y", 14)], "Torso": [("Y", 8)], "Chest": [("Y", 6)],
                    "Neck": [("Y", -8)], "Head": [("Y", -5)], "Foot.R": [("X", -6)]}),
     Vector((-0.012, 0, 0.008))),
    (16, SEAT, ride({"Hips": [("Y", 22)], "Torso": [("Y", 12)], "Chest": [("Y", 8)],
                     "Neck": [("Y", -12)], "Head": [("Y", -8)], "Foot.R": [("X", -9)]}),
     Vector((-0.018, 0, 0.012))),
    (24, SEAT, ride({"Hips": [("Y", 14)], "Torso": [("Y", 8)], "Chest": [("Y", 6)],
                     "Neck": [("Y", -8)]}), Vector((-0.012, 0, 0.008))),
    (32, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Broom_Climb", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (10, SEAT, ride(mix(LEAN_BACK, {"UpperLeg.L": [("X", -10)], "UpperLeg.R": [("X", -10)],
                                    "LowerLeg.L": [("X", -8)], "LowerLeg.R": [("X", -8)]})),
     Vector((0, -0.012, 0.01))),
    (22, SEAT, ride(mix(LEAN_BACK, {"UpperLeg.L": [("X", -12)], "UpperLeg.R": [("X", -12)],
                                    "LowerLeg.L": [("X", -10)], "LowerLeg.R": [("X", -10)]})),
     Vector((0, -0.014, 0.012))),
    (32, SEAT, ride(LEAN_BACK), Vector((0, -0.012, 0.01))),
])
author_clip("Broom_Dive", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (10, SEAT, ride(mix(LEAN_FWD, {"Hips": [("X", -18)], "UpperLeg.L": [("X", 8)],
                                   "UpperLeg.R": [("X", 8)]})), Vector((0, 0.028, -0.032))),
    (22, SEAT, ride(mix(LEAN_FWD, {"Hips": [("X", -22)], "UpperLeg.L": [("X", 10)],
                                   "UpperLeg.R": [("X", 10)]})), Vector((0, 0.034, -0.038))),
    (32, SEAT, ride(mix(LEAN_FWD, {"Hips": [("X", -18)]})), Vector((0, 0.028, -0.032))),
])
author_clip("Broom_Brake", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (8, SEAT, ride(mix(LEAN_BACK, {"UpperLeg.L": [("X", -14)], "UpperLeg.R": [("X", -14)],
                                   "LowerLeg.L": [("X", -10)], "LowerLeg.R": [("X", -10)],
                                   "UpperArm.L": [("Z", 10)], "UpperArm.R": [("Z", -10)]})),
     Vector((0, -0.022, 0.012))),
    (18, SEAT, ride(mix(LEAN_BACK, {"Hips": [("X", 16)], "UpperLeg.L": [("X", -18)],
                                    "UpperLeg.R": [("X", -18)], "LowerLeg.L": [("X", -14)],
                                    "LowerLeg.R": [("X", -14)], "UpperArm.L": [("Z", 14)],
                                    "UpperArm.R": [("Z", -14)]})), Vector((0, -0.028, 0.016))),
    (30, SEAT, ride(LEAN_BACK), Vector((0, -0.022, 0.012))),
])
author_clip("Broom_Takeoff", [
    (0, SEAT, ride(mix(LEAN_BACK, {"UpperLeg.L": [("X", -18)], "UpperLeg.R": [("X", -18)],
                                   "LowerLeg.L": [("X", -22)], "LowerLeg.R": [("X", -22)]})),
     Vector((0, 0.02, -0.09))),
    (7, SEAT, ride({"Hips": [("X", 6)], "UpperLeg.L": [("X", -8)], "UpperLeg.R": [("X", -8)],
                    "LowerLeg.L": [("X", -10)], "LowerLeg.R": [("X", -10)]}), Vector((0, 0.01, -0.02))),
    (15, SEAT, ride(mix(LEAN_FWD, {"Hips": [("X", -6)]})), Vector((0, -0.004, 0.03))),
    (24, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Broom_Land", [
    (0, SEAT, ride(mix(LEAN_FWD, {"Hips": [("X", -16)]})), Vector((0, 0.026, -0.03))),
    (10, SEAT, ride(mix(LEAN_BACK, {"UpperLeg.L": [("X", -10)], "UpperLeg.R": [("X", -10)]})),
     Vector((0, -0.012, 0.024))),
    (20, SEAT, ride({"Hips": [("X", 10)], "UpperLeg.L": [("X", -22)], "UpperLeg.R": [("X", -22)],
                     "LowerLeg.L": [("X", 18)], "LowerLeg.R": [("X", 18)]}), Vector((0, -0.008, -0.05))),
    (30, SEAT, ride({"Hips": [("X", 3)]}), Vector((0, -0.002, -0.012))),
    (36, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Mount_Broom", [
    (0, STAND, {}, None),
    (8, STAND, {"Hips": [("X", -8)], "UpperLeg.L": [("X", -30)], "LowerLeg.L": [("X", 26)],
                "UpperArm.L": [("X", 12)], "UpperArm.R": [("X", 12)]}, Vector((0, 0.01, 0.03))),
    (17, SEAT, ride({"Hips": [("X", -6)], "UpperLeg.L": [("Y", -8)], "UpperLeg.R": [("Y", 8)]}),
     Vector((0, 0.02, -0.03))),
    (24, SEAT, ride(), Vector((0, 0, 0))),
    (30, SEAT, ride(), Vector((0, 0, 0))),
])
author_clip("Dismount_Broom", [
    (0, SEAT, ride(), Vector((0, 0, 0))),
    (10, SEAT, ride({"Hips": [("X", -6), ("Y", 6)], "UpperLeg.L": [("Y", 14)],
                     "UpperLeg.R": [("Y", -14)], "Foot.L": [("X", -6)]}), Vector((0, 0.01, -0.02))),
    (20, STAND, {"Hips": [("X", -10)], "UpperLeg.L": [("X", -34)], "LowerLeg.L": [("X", 28)],
                 "UpperLeg.R": [("X", -6)]}, Vector((0, 0.012, -0.05))),
    (28, STAND, {}, None),
])
author_clip("Stun_Loop", [
    (0, STAND, {"Hips": [("X", 10)], "Torso": [("X", 12)], "Chest": [("X", 10)], "Neck": [("X", 14)],
                "Head": [("X", 8), ("Z", 5)], "UpperArm.L": [("Z", -18), ("Y", 6)],
                "UpperArm.R": [("Z", 18), ("Y", -6)], "LowerArm.L": [("X", -18)],
                "LowerArm.R": [("X", -20)]}, Vector((0, 0.01, -0.06))),
    (15, STAND, {"Hips": [("X", 11), ("Z", 4)], "Torso": [("X", 13)], "Chest": [("X", 10)],
                 "Neck": [("X", 15), ("Z", -5)], "Head": [("X", 8), ("Z", -7)],
                 "UpperArm.L": [("Z", -20), ("Y", 8)], "UpperArm.R": [("Z", 16), ("Y", -8)],
                 "LowerArm.L": [("X", -20)], "LowerArm.R": [("X", -22)]}, Vector((0.012, 0.01, -0.062))),
    (30, STAND, {"Hips": [("X", 10)], "Torso": [("X", 12)], "Chest": [("X", 10)], "Neck": [("X", 14)],
                 "Head": [("X", 8), ("Z", 5)], "UpperArm.L": [("Z", -18), ("Y", 6)],
                 "UpperArm.R": [("Z", 18), ("Y", -6)], "LowerArm.L": [("X", -18)],
                 "LowerArm.R": [("X", -20)]}, Vector((0, 0.01, -0.06))),
])
author_clip("Revive", [
    (0, STAND, {"Hips": [("X", 74)], "Torso": [("X", 26)], "Chest": [("X", 20)], "Neck": [("X", -14)],
                "UpperLeg.L": [("X", 52), ("Y", -16)], "UpperLeg.R": [("X", 40), ("Y", 10)],
                "LowerLeg.L": [("X", 36)], "LowerLeg.R": [("X", 18)],
                "UpperArm.L": [("Z", -30)], "UpperArm.R": [("Z", 26)]}, Vector((0, 0.02, -0.5))),
    (16, STAND, {"Hips": [("X", 40)], "Torso": [("X", 16)], "Chest": [("X", 12)], "Neck": [("X", -8)],
                 "UpperLeg.L": [("X", 26), ("Y", -12)], "UpperLeg.R": [("X", 34), ("Y", 12)],
                 "LowerLeg.L": [("X", 52)], "LowerLeg.R": [("X", 34)]}, Vector((0, 0.01, -0.3))),
    (30, STAND, {"Hips": [("X", 10)], "Torso": [("X", 5)], "UpperLeg.L": [("X", 5)],
                 "UpperLeg.R": [("X", 7)]}, Vector((0, 0, -0.1))),
    (44, STAND, {}, None),
])


# ---------------------------------------------------------------- cast variants
print("[hero] building upper-body cast variants")
for src, dst in (("Spellcast_Shoot", "Spellcast_Shoot_Upper"), ("Spellcast_Raise", "Spellcast_Raise_Upper")):
    act = bpy.data.actions.get(src)
    if act is None:
        print("[hero] MISSING cast source %s" % src)
        continue
    copy = act.copy()
    copy.name = dst
    copy.use_fake_user = True
    removed = hc.strip_lower_body(copy)
    print("[hero] %s -> %s (stripped %d lower-body fcurves, %d kept)"
          % (src, dst, removed, len(hc.action_fcurves(copy))))

# ---------------------------------------------------------------- pose check render
if POSE_CHECK:
    os.makedirs(POSE_CHECK, exist_ok=True)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 700
    scene.render.resolution_y = 700
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    cam.location = Vector((3.0, -3.0, 1.4))
    direction = Vector((0, 0, 1.0)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    checks = {
        "ride-base": merged({}),
        "bank-l": merged({"Hips": [("Y", -22)], "Torso": [("Y", -12)]}),
        "dive": merged({"Hips": [("X", -20)], "Torso": [("X", -16)]}),
        "stand": merged(STAND_POSE),
        "stun": merged({"Hips": [("X", 12)], "Torso": [("X", -14)], "Neck": [("X", -18)]}),
    }
    hero_arm.animation_data_create()
    hero_arm.animation_data.action = None
    for name, pose in checks.items():
        apply_pose(pose, Vector((0, 0, 0)))
        bpy.context.view_layer.update()
        scene.render.filepath = os.path.join(POSE_CHECK, "hero-%s.png" % name)
        bpy.ops.render.render(write_still=True)
        print("[hero] pose check rendered %s" % scene.render.filepath)
    apply_pose(merged({}), Vector((0, 0, 0)))

# ---------------------------------------------------------------- export
# Keep list: only clips the game actually consumes may ship in the GLB.
KEEP = (set(NATIVE_RENAME.values()) | set(UAL_MAP.values()) |
        {"Broom_Seated_Idle", "Broom_Cruise", "Broom_Accelerate", "Broom_Bank_L", "Broom_Bank_R",
         "Broom_Climb", "Broom_Dive", "Broom_Brake", "Broom_Takeoff", "Broom_Land",
         "Mount_Broom", "Dismount_Broom", "Stun_Loop", "Revive",
         "Spellcast_Shoot_Upper", "Spellcast_Raise_Upper"})
for act in list(bpy.data.actions):
    if act.name not in KEEP:
        print("[hero] dropping non-shipping action %s" % act.name)
        bpy.data.actions.remove(act)
print("[hero] actions for export (%d): %s" % (len(bpy.data.actions), sorted(a.name for a in bpy.data.actions)))
for act in bpy.data.actions:
    act.use_fake_user = True
hero_arm.animation_data_create()
hero_arm.animation_data.action = None
kwargs = dict(filepath=OUT, export_format="GLB", export_yup=True, export_apply=False,
              export_animations=True, export_animation_mode="ACTIONS")
try:
    bpy.ops.export_scene.gltf(**kwargs)
except TypeError as exc:
    print("[hero] export kwargs rejected (%s); retrying minimal" % exc)
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, export_animations=True)
print("[hero] exported %s (%d bytes)" % (OUT, os.path.getsize(OUT)))

tris = 0
deps = bpy.context.evaluated_depsgraph_get()
for ob in hero_meshes:
    me = ob.evaluated_get(deps).to_mesh()
    tris += sum(len(p.vertices) - 2 for p in me.polygons)
print("[hero] hero mesh tris: %d" % tris)
print("[hero] bones: %d" % len(hero_arm.data.bones))
print("[hero] clips: %d" % len(bpy.data.actions))
