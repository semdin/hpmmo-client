"""Shared helpers for the rig hero build: import, socket convention, and a
rest-delta retargeter (Quaternius UAL -> Quaternius Universal Base rigs).

Both packs are Quaternius, but the base characters use `UpperArm.L` style names
and the Universal Animation Library uses `upperarm_l`, so a bone map is required
and the transfer is done in armature space:

    delta_armature  = B_src * q_src * B_src^-1        (B = rest rotation, armature space)
    q_dst           = B_dst^-1 * delta_armature * B_dst

which is rest-orientation independent, so it survives the two rigs' different
bone axes. Locations transfer the same way and are scaled by the height ratio.
"""
import bpy, math
from mathutils import Vector, Quaternion, Matrix

# UAL bone -> Universal Base Character bone
BONE_MAP = {
    "pelvis": "Hips",
    "spine_01": "Abdomen",
    "spine_02": "Torso",
    "spine_03": "Chest",
    "neck_01": "Neck",
    "Head": "Head",
    "clavicle_l": "Shoulder.L", "clavicle_r": "Shoulder.R",
    "upperarm_l": "UpperArm.L", "upperarm_r": "UpperArm.R",
    "lowerarm_l": "LowerArm.L", "lowerarm_r": "LowerArm.R",
    "hand_l": "Wrist.L", "hand_r": "Wrist.R",
    "thigh_l": "UpperLeg.L", "thigh_r": "UpperLeg.R",
    "calf_l": "LowerLeg.L", "calf_r": "LowerLeg.R",
    "foot_l": "Foot.L", "foot_r": "Foot.R",
    "ball_l": "PT.L", "ball_r": "PT.R",
}
for src, dst in (("index", "Index"), ("middle", "Middle"), ("ring", "Ring"), ("pinky", "Pinky")):
    for i in (1, 2, 3):
        BONE_MAP["%s_0%d_l" % (src, i)] = "%s%d.L" % (dst, i)
        BONE_MAP["%s_0%d_r" % (src, i)] = "%s%d.R" % (dst, i)
    BONE_MAP["%s_04_leaf_l" % src] = "%s4.L" % dst
    BONE_MAP["%s_04_leaf_r" % src] = "%s4.R" % dst
for i in (1, 2, 3):
    BONE_MAP["thumb_0%d_l" % i] = "Thumb%d.L" % i
    BONE_MAP["thumb_0%d_r" % i] = "Thumb%d.R" % i

# Bones that must never be animated by a retargeted clip (in-place policy).
NO_ROOT_MOTION = {"root", "Root"}


def find_armature(name_hint=""):
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE" and name_hint in ob.name:
            return ob
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE":
            return ob
    return None


def purge_unwanted(keep_armature, drop_meshes=("Icosphere", "Sword")):
    removed = []
    for ob in list(bpy.data.objects):
        if ob.type == "MESH" and any(ob.name.startswith(d) for d in drop_meshes):
            removed.append(ob.name)
            bpy.data.objects.remove(ob, do_unlink=True)
    for ob in list(bpy.data.objects):
        if ob.type == "EMPTY" and ob.parent is None and ob.name.startswith("RootNode"):
            # keep the scene root; the exporter re-creates hierarchy anyway
            pass
    return removed


def rest_quat(arm_obj, bone_name):
    return arm_obj.data.bones[bone_name].matrix_local.to_quaternion()


def height_of(arm_obj):
    """Crown height in metres, measured from the mesh bound box (Blender Z-up)."""
    top, bottom = -1e9, 1e9
    for ob in bpy.data.objects:
        if ob.type == "MESH" and (ob.parent == arm_obj or ob.parent is None):
            for corner in ob.bound_box:
                w = ob.matrix_world @ Vector(corner)
                top = max(top, w.z)
                bottom = min(bottom, w.z)
    return top - bottom


def _hierarchy_order(arm):
    order = []
    seen = set()

    def walk(bone):
        if bone.name in seen:
            return
        seen.add(bone.name)
        order.append(bone.name)
        for child in bone.children:
            walk(child)

    for bone in arm.data.bones:
        if bone.parent is None:
            walk(bone)
    for bone in arm.data.bones:
        walk(bone)
    return order


def bake_retarget(src_arm, src_action, dst_arm, dst_action_name, fps,
                  start_offset=0.0, end_offset=0.0):
    """Sample a source action and key every mapped bone onto the destination.

    World-space transfer: for each bone the source's world pose delta (current
    pose vs rest) is applied to the target's rest world matrix, and the target's
    local pose is solved from the hierarchy. That is independent of each rig's
    bone axes, bind orientation and armature object transform - the two packs
    disagree on all three - and it reproduces the source's world motion exactly.
    """
    scene = bpy.context.scene
    f0, f1 = src_action.frame_range
    f0 = int(math.ceil(f0 + start_offset))
    f1 = int(math.floor(f1 - end_offset))
    if f1 <= f0:
        return None

    src_arm.animation_data_create()
    src_arm.animation_data.action = src_action

    dst_action = bpy.data.actions.new(dst_action_name)
    dst_action.use_fake_user = True
    dst_arm.animation_data_create()
    dst_arm.animation_data.action = dst_action

    rev = {d: s for s, d in BONE_MAP.items() if d in dst_arm.data.bones and s in src_arm.data.bones}
    order = _hierarchy_order(dst_arm)
    src_rest_world = {s: src_arm.matrix_world @ src_arm.data.bones[s].matrix_local
                      for s in rev.values()}
    dst_rest_world = {d: dst_arm.matrix_world @ dst_arm.data.bones[d].matrix_local
                      for d in rev.keys()}
    dst_rest_arm = {b.name: b.matrix_local for b in dst_arm.data.bones}
    dst_world_inv = dst_arm.matrix_world.inverted()
    pose_arm = {}
    for frame in range(f0, f1 + 1):
        scene.frame_set(frame)
        pose_arm.clear()
        for name in order:
            bone = dst_arm.data.bones[name]
            s_name = rev.get(name)
            if s_name is not None:
                src_pose_world = src_arm.matrix_world @ src_arm.pose.bones[s_name].matrix
                delta_world = src_pose_world @ src_rest_world[s_name].inverted()
                pose_arm[name] = dst_world_inv @ (delta_world @ dst_rest_world[name])
            else:
                rest = dst_rest_arm[name]
                parent = bone.parent
                if parent is None:
                    pose_arm[name] = rest
                else:
                    parent_rest_rel = parent.matrix_local.inverted() @ rest
                    pose_arm[name] = pose_arm[parent.name] @ parent_rest_rel
            pb = dst_arm.pose.bones[name]
            parent = bone.parent
            if parent is None:
                local = dst_rest_arm[name].inverted() @ pose_arm[name]
            else:
                parent_rest_rel = parent.matrix_local.inverted() @ dst_rest_arm[name]
                local = (pose_arm[parent.name] @ parent_rest_rel).inverted() @ pose_arm[name]
            loc, rot, _scale = local.decompose()
            pb.location = loc
            pb.rotation_quaternion = rot.normalized()
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            # Every bone needs its translation keyed, not just the hips: this
            # rig parents the legs to `Body` rather than to `Hips`, so a hip
            # move only reaches the legs through their own local offsets.
            pb.keyframe_insert("location", frame=frame)

    # reset both rigs so the next bake starts clean
    src_arm.animation_data.action = None
    for pb in src_arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    for pb in dst_arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    dst_arm.animation_data.action = None
    return dst_action


def reunit_pose_translations(actions, factor):
    """Rescale pose-bone translation channels by `factor`, in place.

    The body packs ship with a 100x scale on the armature and compensating mesh
    scales (`transform_apply` bakes that into the rests and the meshes). Pose
    channels are a deviation from rest, so they are unitless only for rotation -
    a location fcurve authored in the pack's own unit is left behind by the
    bake, and every bone those clips translate ends up moving 1/factor as far as
    its rest says it should.

    Location fcurves are pure deviation, so scaling the values (handles included)
    is the whole correction; there is no rest term to preserve.
    """
    if abs(factor - 1.0) < 1e-6:
        return 0
    scaled = 0
    for action in actions:
        for fcurve in action_fcurves(action):
            if not fcurve.data_path.endswith(".location"):
                continue
            for point in fcurve.keyframe_points:
                point.co[1] *= factor
                point.handle_left[1] *= factor
                point.handle_right[1] *= factor
            fcurve.update()
            scaled += 1
    return scaled


def rename_actions(mapping):
    for old, new in mapping.items():
        act = bpy.data.actions.get(old)
        if act is None:
            print("[hero] action not found for rename: %s" % old)
            continue
        act.name = new
        act.use_fake_user = True


def action_fcurves(action):
    """Blender 5.x actions are layered; older ones expose .fcurves directly."""
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    out = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def _remove_fcurve(action, fcurve):
    if hasattr(action, "fcurves"):
        action.fcurves.remove(fcurve)
        return
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                if fcurve in list(bag.fcurves):
                    bag.fcurves.remove(fcurve)
                    return


def strip_lower_body(action, keep_upper=True):
    """Reduce an action to upper-body tracks (spine/arms/hands/head)."""
    upper = ("Spine", "spine", "Chest", "Torso", "Abdomen", "Neck", "Head", "Shoulder",
             "UpperArm", "LowerArm", "Wrist", "Index", "Middle", "Ring", "Pinky", "Thumb",
             "clavicle", "upperarm", "lowerarm", "hand", "index", "middle", "ring", "pinky", "thumb")
    removed = 0
    for fc in action_fcurves(action):
        path = fc.data_path
        if "pose.bones[" not in path:
            continue
        bone = path.split('"')[1] if '"' in path else ""
        if keep_upper and not any(bone.startswith(u) for u in upper):
            _remove_fcurve(action, fc)
            removed += 1
    return removed
