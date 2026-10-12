# Hero rig

The player hero (`assets/models/characters/hero_wizard.glb`) is a generated
1.75 m mesh (40k triangles, one PBR material at 2048 px) rigged with Rigify in
Blender. The source lives next to this repository, in the workspace's
`art/hero/` folder:

| Path | What it is |
| --- | --- |
| `art/hero/hero_new.blend` | Source of truth: metarig, Rigify control rig, GameRig, mesh, all actions |
| `art/hero/scripts/build_gamerig.py` | Rigify generate → GameRig → skin → finger weights → 4-influence limit |
| `art/hero/scripts/bake_all.py` | Rebuilds every clip below in order and exports the GLB (the one to run) |
| `art/hero/scripts/retarget.py` | Rest-aligned world-space retarget onto GameRig, with ground-contact fix |
| `art/hero/scripts/ual_clips.py` | Ground/combat clips from Quaternius UAL1 (CC0), plus derived clips |
| `art/hero/scripts/broom_clips.py` | Authored broom-riding clips, the stun loop and the two-handed power cast |
| `art/hero/scripts/export_hero.py` | Exports GameRig + `Hero_Body` + every GameRig action to this GLB |
| `art/hero/scripts/test_pose.py` | Stress pose for reviewing weights |
| `art/hero/textures/*_4k.png` | Full-resolution textures (the GLB carries 2048 px copies) |
| `art/hero/legacy/hero_wizard_quaternius_old.glb` | The previous hero (kept for reference; no clip comes from it any more) |

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

**Rebuild every clip and re-export**: run `bake_all.py`.

**Re-export only**: run `export_hero.py` and then call `export()`.

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

## Where each clip comes from

| Game clip | Source |
| --- | --- |
| `Idle`, `Walk_A`, `Running_A` (UAL `Sprint_Loop`), `Jump_Start`, `Fall_Loop`, `Land`, `Hit_A/B`, `Death_A`, `Roll`, `Interact`, `Sit_*`, `Melee_Chop_A/B` (punches) | Quaternius Universal Animation Library 1, CC0 (`assets/candidates/character/quaternius-universal-animation-library`) |
| `Spellcast_Raise`, `Spellcast_Shoot`, `Cast_Idle_Loop`, `Cast_Exit` (+ `_Upper`) | UAL `Spell_Simple_*`, mirrored: UAL casts with the left hand, the wand is in the right |
| `Walk_Back`, `Revive` | `Walk_A` / `Death_A` played backwards |
| `Strafe_L`, `Strafe_R` | `Walk_A` with the leg swing turned 90° |
| `Spellcast_Heavy` (+ `_Upper`) | Authored: wand raised back, both hands thrust forward. Used by `HEAVY_CAST_SPELLS` (Bombarda, ultimate); every other cast is one-handed |
| `Broom_*`, `Mount_Broom`, `Dismount_Broom`, `Stun_Loop` | Authored in `broom_clips.py` from per-bone world directions |

The broom clips give the arms a pose that is already near the shaft;
`BroomGripModifier` then solves the exact grip (0.38 m ahead of the seat) and
leans the spine only as far as the hands need, inside the 22–48° band, so each
clip keeps its own body language (sitting up to brake, flat to dive).

## Lighting

The body is one baked PBR material. Under the world's sky ambient, dark
clothing facing away from the sun reads as a black silhouette, so
`HeroAppearance` puts hero bodies on render layer 20 with a small cloth rim, and
the local camera carries a soft, shadowless `CharacterFill` light that only
lights that layer (the usual third-person character fill). Tune
`FILL_ENERGY` / `CLOTH_RIM` in `hero_appearance.gd`.

## Known limits

- UAL1 has no dedicated strafe or backward walk; those are derived from the
  forward walk and read well at gameplay distance, not in close-up. UAL2 or a
  mocap set would replace them by adding a row to `UAL_CLIPS`.
- The broom clips are authored poses with procedural motion, not motion capture.
- The body is a single baked material, so `HeroAppearance.apply_house_tint`
  has no trim/robe slot to recolour. House colours need a mask texture or a
  split material.
- Fingers are fused in the mesh; weights are separated per finger by
  `redistribute_fingers`, which is good at game distance but not for close-ups.
