"""Find the most seamless loop window in a generated motion clip.

blender --background --python find_loop.py -- <clip.fbx> [min_s] [max_s]

Compares every frame pair (a, b) whose span is a plausible cycle length:
pose distance = summed quaternion angle over the leg, hip and spine bones plus
the pelvis height. Prints the best windows as "--trim a b-1" arguments for
retarget_clip.py (frame b repeats frame a, so the clip ends one frame early).
"""
import bpy, sys, math

argv = sys.argv[sys.argv.index("--") + 1:]
FBX = argv[0]
MIN_S = float(argv[1]) if len(argv) > 1 else 0.7
MAX_S = float(argv[2]) if len(argv) > 2 else 1.6
FPS = 30
BONES = ["Pelvis", "L_Hip", "L_Knee", "L_Ankle", "R_Hip", "R_Knee", "R_Ankle", "Spine1", "Spine2", "L_Shoulder", "R_Shoulder", "L_Elbow", "R_Elbow"]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = FPS
bpy.ops.import_scene.fbx(filepath=FBX, ignore_leaf_bones=True)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = arm.animation_data.action
f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
poses = []
for f in range(f0, f1 + 1):
    bpy.context.scene.frame_set(f)
    poses.append(({b: arm.pose.bones[b].matrix_basis.to_quaternion() for b in BONES if b in arm.pose.bones},
                  (arm.matrix_world @ arm.pose.bones["Pelvis"].matrix).translation.copy()))


def dist(i, j):
    qa, pa = poses[i]
    qb, pb = poses[j]
    ang = sum(math.degrees(qa[b].rotation_difference(qb[b]).angle) for b in qa)
    return ang + 400.0 * abs(pa.z - pb.z)


best = []
n = len(poses)
skip = int(0.4 * FPS)        # leave the settling-in start out
for a in range(skip, n):
    for b in range(a + int(MIN_S * FPS), min(n, a + int(MAX_S * FPS) + 1)):
        best.append((dist(a, b), a, b))
best.sort()
seen = []
for d, a, b in best:
    if any(abs(a - x) < 6 and abs(b - y) < 6 for x, y in seen):
        continue
    seen.append((a, b))
    print("[loop] score %.1f  frames %d..%d (%.2f s)  --trim %d %d" % (d, f0 + a, f0 + b, (b - a) / FPS, f0 + a, f0 + b - 1))
    if len(seen) >= 5:
        break
