# Hero rig

The player hero (`assets/models/characters/hero_wizard.glb`, 1.76 m) is an
MPFB2 / MakeHuman base human (CC0 core assets: real eyeballs, lashes, brows,
teeth, morph targets) wearing a generated outfit and hairstyle, rigged through
Rigify into the same 53-bone GameRig as before. It ships as separate skinned
meshes on one skeleton: `Hero_Body` (skin; the parts the outfit covers are
removed), `Hero_Outfit`, one `Hero_Hair_<style>` per hairstyle, `Hero_Eyes`,
`Hero_Brows`, `Hero_Lashes`, `Hero_Teeth`, `Hero_Tongue`.
`HeroAppearance.dress_parts` gives each its look (cloth rim on the outfit,
the skin / hair / eye / brow shaders below, alpha scissor on lashes). The source lives next to this repository, in the workspace's
`art/characters/hero_v2/` folder (shared rig scripts stay in `art/hero/scripts/`):

| Path | What it is |
| --- | --- |
| `mpfb/build_base.py` | The MPFB human from one `human_info` dict (phenotype, face targets, eyes, brows, lashes, skin) |
| `mpfb/render_head_views.py`, `hair/extract_hair.py` | Hairstyles: bald-head views → Sunburst adds the hair → Hunyuan multi-view → hair cut out and fitted to this skull |
| `outfit/landmarks.py`, `outfit/fit_outfit.py` | The Hunyuan student outfit warped onto the MPFB body (3D thin-plate spline through matched landmarks), skin cut away, kept 4 mm outside the skin, baked |
| `rig/rig_hero.py` | MPFB Rigify meta rig + its hand-made weights → Rigify → `art/hero/scripts/build_gamerig.py` GameRig; weights folded onto GameRig bones, outfit weights from the body |
| `rig/bake_clips.py` | Every clip (UAL, broom, spells, portkey) onto the GameRig and the export of this GLB and `assets/animations/hero/*.glb` (the one to run) |
| `rig/pose_test.py`, `rig/clip_sheet.py`, `rig/shape_sheet.py` | Review renders: stress poses, a clip's frames + planted-toe speed, the blend shapes |
| `mpfb/hero_spec.py`, `mpfb/build_variants.py` | The look sliders' MPFB variants (muscle, jaw, nose, cheeks) baked into blend shapes |
| `build_hero.sh` | The whole rebuild: rig, clips, export, Godot import, VRAM texture settings |
| `art/hero/scripts/retarget.py`, `ual_clips.py`, `broom_clips.py` | Shared clip sources (unchanged contract: GameRig bone names) |
| `art/hero/legacy/hero_v1/` | The previous generated hero and its clip GLBs |

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

**Rebuild and re-export everything**: `bash art/characters/hero_v2/build_hero.sh`
(prints `BUILD_DONE`), then review with `scenes/test/look_capture.tscn`.

**Add a hairstyle**: bald views → Sunburst → Hunyuan → `hair/extract_hair.py`
(knobs: `HAIR_BACK_DEPTH`, `HAIR_FRONT_LINE`, `HAIR_ISLAND_MIN`, `HAIR_TRIS`,
`HAIR_SMOOTH`) → `outfit/fix_normal_specks.py <normal> 40 25` → append the
style to `SCALP_ORDER` in `rig_hero.py` (four RGBA mask channels: a fifth style
needs a second colour layer), to `HPRules.LOOK_HAIR_STYLES` and to
`HAIR_REF_LUMA` (its mean baked luminance) → rebuild.

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

## Customization

A character's look is `HPRules.clean_look` data (server-owned rules,
`quests.look` in the save): hair style + colour, eye colour, skin tone (palette
indices) and the sliders `muscle`, `jaw`, `nose`, `cheeks`, `height`.
`HeroAppearance.apply_look` turns it into the model:

- hair: only the chosen `Hero_Hair_<style>` is visible; `hero_hair.gdshader`
  takes the baked strand shading (normalised by `HAIR_REF_LUMA`) and paints it
  in the picked colour;
- skin: `hero_skin.gdshader` multiplies the skin tone and paints the scalp under
  the worn style (vertex colour `scalp`, one RGBA channel per style, picked by
  `scalp_select`) in the hair colour; with no hair it draws stubble;
- eyes: `hero_eye.gdshader` recolours the two iris discs of the MPFB eye
  texture (the cornea shell is cut by alpha scissor);
- brows: `hero_brow.gdshader`, the card's alpha in the hair colour;
- sliders: blend shapes on body, outfit and hair (the outfit and hair inherit
  the body's deltas), height scales the skeleton ±5 %.

Every shader value is an `instance uniform`, so all players share one
material per part. The editor is `scripts/ui/look_editor.gd` on the character
screen; a look is sent once with `sim_look_request` (protocol v28) and
broadcast in `player_info`.

## Where each clip comes from

| Game clip | Source |
| --- | --- |
| `Walk_A`, `Running_A` (UAL `Jog_Fwd_Loop`: 19° lean, planted toe 6.04 m/s; the old `Sprint_Loop` leaned 35° and slid at 9 m/s), `Jump_Start`, `Fall_Loop`, `Land`, `Hit_A/B`, `Death_A`, `Roll`, `Interact`, `Sit_*`, `Melee_Chop_A/B` (punches) | Quaternius Universal Animation Library 1, CC0 (`assets/candidates/character/quaternius-universal-animation-library`) |
| `Spellcast_Raise`, `Spellcast_Shoot`, `Cast_Idle_Loop`, `Cast_Exit` (+ `_Upper`) | UAL `Spell_Simple_*`, mirrored: UAL casts with the left hand, the wand is in the right |
| `Idle`, `Walk_Back` (2.81 m/s), `Strafe_R` (2.43 m/s; `Strafe_L` is its mirror) | Generated with fal `hunyuan-motion`, looped with `tools/blender/find_loop.py` and `retarget_clip.py --loop` (prompts and trims: `art/hero/motion_fal/loco/README.md`) |
| Spell casts (`Cast_*`), `Portkey_Place` | Generated with `hunyuan-motion`, `retarget_clip.py` (`art/hero/motion_fal/README.md`) |
| `Revive` | `Death_A` played backwards |
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

- The broom clips are authored poses with procedural motion, not motion capture.
- The outfit is one baked material, so `HeroAppearance.apply_house_tint` has
  no trim/robe slot to recolour yet (the tie is the natural house slot).
- Walk and run speeds the clips were authored at are measured, not guessed:
  `HeroAnimation.WALK_NATURAL_SPEED` / `RUN_NATURAL_SPEED`; a new locomotion
  clip needs its planted-toe speed measured the same way.
- The outfit is warped from a slimmer body; raising an arm above the shoulder
  stretches the vest's armhole a little.
