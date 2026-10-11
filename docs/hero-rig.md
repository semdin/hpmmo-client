# Hero rig

The player hero (`assets/models/characters/hero_wizard.glb`) is a generated
1.75 m mesh (40k triangles, one PBR material at 2048 px) rigged with Rigify in
Blender. The source lives next to this repository, in the workspace's
`art/hero/` folder:

| Path | What it is |
| --- | --- |
| `art/hero/hero_new.blend` | Source of truth: metarig, Rigify control rig, GameRig, mesh, all actions |
| `art/hero/scripts/build_gamerig.py` | Rigify generate → GameRig → skin → finger weights → 4-influence limit |
| `art/hero/scripts/retarget.py` | Rest-aligned world-space retarget onto GameRig, with ground-contact fix |
| `art/hero/scripts/export_hero.py` | Exports GameRig + `Hero_Body` + every GameRig action to this GLB |
| `art/hero/scripts/test_pose.py` | Stress pose for reviewing weights |
| `art/hero/textures/*_4k.png` | Full-resolution textures (the GLB carries 2048 px copies) |
| `art/hero/legacy/hero_wizard_quaternius_old.glb` | The previous hero; source of the 41 retargeted clips |

## Two skeletons

- **rig** (Rigify, 400+ bones): IK/FK arms and legs, foot roll, finger
  controls. Animate here. Never exported.
- **GameRig** (53 bones): what the game sees. Each bone follows its Rigify
  deform/ORG bone through a `Copy Transforms` constraint (`Root` uses `Child Of`).
  All constraints share one driver, the `use_control_rig` property on GameRig:
  `1` while animating with Rigify, `0` when GameRig plays its own baked actions
  and for export.

GameRig bones use Godot's `SkeletonProfileHumanoid` names (`Hips`, `Spine`,
`Chest`, `UpperChest`, `Neck`, `Head`, `LeftShoulder`, `LeftUpperArm`,
`LeftLowerArm`, `LeftHand`, `LeftIndexProximal`…, `LeftUpperLeg`, `LeftFoot`,
`LeftToes`). Gameplay code never spells a bone name itself: it asks
`HeroBones` (`scripts/entities/hero_bones.gd`), which also records the
measured axis facts the procedural layers rely on (finger curl sign, thumb curl
sign, palm axis per hand). `rig_regression.gd` re-measures those facts on the
shipped skeleton, so a re-rig that flips an axis fails loudly instead of
bending fingers backwards.

## Common jobs

All in `hero_new.blend`, from the Scripting tab
(`exec(open(r"<workspace>/art/hero/scripts/<script>.py").read())`).

**Re-export after any change**: run `export_hero.py` and then call `export()`.

**Author a new clip**: set `GameRig["use_control_rig"] = 1`, animate the
Rigify `rig`, then bake GameRig (Pose ▸ Animation ▸ Bake Action, visual
keying, only GameRig's bones) into an action named for the clip. Set
`use_control_rig` back to 0 and export. Name it after the existing clip to
replace one (`Idle`, `Walk_A`, …); `hero_animation.gd` resolves clips by name.

**Bring in clips from another humanoid** (Mixamo, Quaternius UAL, mocap):
`src = import_source(path)` from `retarget.py`, extend `QUATERNIUS_MAP` with a
map for that skeleton (GameRig name → source name), `retarget_all(src, MAP)`,
`remove_source()`, export.

**Change the mesh or the joint placement**: edit the `metarig` bones, then
run `build_gamerig.py` (regenerates Rigify, GameRig and the skin). Actions are
per-bone rotations relative to rest, so re-run the retarget afterwards if the
rest pose moved.

## Known limits

- The 41 clips are the previous hero's animations retargeted; they carry that
  animation set's style (for example the wide-armed idle). Replacing them with
  a better humanoid library is now a retarget, not a rig job.
- The body is a single baked material, so `HeroAppearance.apply_house_tint`
  has no trim/robe slot to recolour. House colours need a mask texture or a
  split material.
- Fingers are fused in the mesh; weights are separated per finger by
  `redistribute_fingers`, which is good at game distance but not for close-ups.
