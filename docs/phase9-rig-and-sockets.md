# Phase 9 — hero rig, sockets and the flight broom

Status: implemented. Scope: `plan.md` Phase 9 (character tasks, broom tasks, exit checks).
Everything below is measured from the shipped files, not assumed.

## 1. What ships, and from where

| Artifact | Origin | License | Local path |
| --- | --- | --- | --- |
| Hero body + native clips | Quaternius "Hooded Adventurer" (poly.pizza/m/y9KWOVG21R) | CC0 1.0 | source kept at `assets/candidates/character/quaternius-hooded-adventurer/` |
| Retargeted clips (jump/fall/land, casts, sitting) | Quaternius Universal Animation Library (`UAL1_Standard.glb`) | CC0 1.0 | `assets/candidates/character/quaternius-universal-animation-library/` |
| Shipped hero `hero_wizard.glb` | Built by `tools/blender/build_hero.py` + `hero_common.py` | derivative of the CC0 packs | `assets/models/characters/hero_wizard.glb` |
| Broom `broom_flight.glb` | Authored by `tools/blender/build_broom.py` (no third-party asset) | project-original | `assets/models/props/broom_flight.glb` |

Measured: hero bind height **1.877 m**, 6,404 tris, 62 joints, 41 clips, **5 material slots**
(14 source slots consolidated); broom 3,012 tris, 4 materials, 2.275 m long, 512/256 px
generated textures packed in the GLB. Both have **no LODs yet** — an open deviation from the
art-direction LOD standard, recorded in `assets/manifest.json`.

## 2. Sockets — one convention

Sockets are `BoneAttachment3D` nodes created from `player.gd:SOCKET_BONES`, so a bone rename
happens in exactly one place.

| Socket | Bone | Used for |
| --- | --- | --- |
| `Socket_Wand` | `Wrist.R` | wand / casting hand |
| `Socket_Hand_L`, `Socket_Hand_R` | `Wrist.L`, `Wrist.R` | hand-held equipment |
| `Socket_Foot_L`, `Socket_Foot_R` | `Foot.L`, `Foot.R` | boots / ground contact checks |
| `Socket_Torso` | `Chest` | wearable equipment |
| `Socket_Head` | `Head` | head wear / nameplate anchoring |
| `Socket_Hips` | `Hips` | **the mount seat reference** |

Broom sockets come from the GLB itself (exported empties):

| Socket | Meaning (Godot space: +Z forward, +Y up) |
| --- | --- |
| `MountRoot` | shaft point the rider's mount node attaches to (y +0.06, z −0.30) |
| `SeatSocket` | where the rider's hips sit (y +0.18, z −0.32) |
| `GripSocket` | two-handed grip centre (z +0.23) |
| `TailSocket` | bristle tip; trail/thrust origin (z −1.34) |

**Mount convention:** the broom node is positioned so `SeatSocket` coincides with the hero's
`Socket_Hips` (`player.gd:_align_broom_to_hips`). The Phase 9 regression measures the gap
(0.000 m) instead of trusting it, and a 0.35 m tolerance is asserted after every turn.

**Axes:** authored `+Z` forward / `+Y` up (art-direction §3), then *measured*: nose +0.99 Z,
bristles −1.29 Z, verified in `BroomFlight.verify_axes()` and asserted by the regression —
this is the check a reversed rider fails.

## 3. Clips

| Group | Clips |
| --- | --- |
| Native (body pack) | `Idle`, `Walk_A`, `Running_A`, `Walk_Back`, `Strafe_L`, `Strafe_R`, `Interact`, `Hit_A`, `Hit_B`, `Death_A`, `Roll`, `Emote_Wave`, `Melee_Chop_A/B` |
| Retargeted (UAL) | `Jump_Start`, `Fall`, `Land`, `Spellcast_Shoot`, `Spellcast_Raise`, `Cast_Idle`, `Cast_Exit`, `Sit_Enter`, `Sit_Chair_Idle`, `Sit_Exit`, `Drive_Reference` |
| Authored on the rig | `Mount_Broom`, `Dismount_Broom`, `Broom_Seated_Idle`, `Broom_Cruise`, `Broom_Accelerate`, `Broom_Bank_L/R`, `Broom_Climb`, `Broom_Dive`, `Broom_Brake`, `Broom_Takeoff`, `Broom_Land`, `Stun_Loop`, `Revive` |
| Upper-body variants | `Spellcast_Shoot_Upper`, `Spellcast_Raise_Upper` |

**Turn** is served by `Strafe_L` / `Strafe_R`; neither source pack ships a dedicated turn clip,
and that is a mapping, not a new asset. `Drive_Reference` is a captured reference pose used as
the riding base — it ships so the capture is reproducible, and is never played at runtime.

Loop modes are declared once, in `hero_animation.gd:LOOPING` (the Godot glTF importer strips a
trailing `_Loop` and turns it into the import's loop flag, hence the `ALIASES` table).

### Cast layer
`Spellcast_*_Upper` is blended over locomotion by `cast_layer_modifier.gd`, a
`SkeletonModifier3D` that writes only the bones the cast clip owns. This is deliberate:
**Godot's `AnimationNodeBlend2` pulls any track a clip does not animate toward the rest pose**
(measured: 0.46 rad of leg drift when the cast was blended through the tree), so a masked layer
is the only way to keep the legs running. The regression measures the legs A/B (with and without
the cast) and asserts they are untouched, and that the arm takes the cast pose (1.44 rad).

## 4. Mount state and replication

- Client presentation states: `Ground → Mounting → Flying → Landing` (`player.gd:MountState`).
- The authority stays the decider (`SimAuthority.submit_mount`); the client's `mount_block_reason()`
  only explains a refusal: defeated, stunned, in combat (2 s window after taking damage),
  transfer pending, not on the floor, unstable ground, no clearance, flight not allowed on the map.
- Dismount checks, in the plan's order: ground normal ≥ 0.7, capsule clearance
  (r 0.35 / h 1.85), ceiling ≥ 2.15 m, safe standing position.
- **Replicated phase:** `HPProtocol.MountPhase` rides in the existing `state` byte of the
  snapshot for PLAYER entities (`authority.gd:_tick_mount_phases`). Remote clients render the
  phase the authority chose; they never derive it. An additive hook, no new packet.

## 5. Traps found the hard way (kept here so they are not re-learned)

1. **Quaternius rigs disagree on everything**: bone names (`UpperArm.L` vs `upperarm_l`), bone
   axes, and armature scale (100×). Retargeting is done in **world space** per bone
   (`hero_common.py:bake_retarget`); armature-space or bone-local transfer produced a body lying
   at 90°.
2. **This rig parents the legs to `Body`, not `Hips`**, so retargeted clips must key *every*
   bone's translation — keying only the hips left the legs floating in place.
3. **Source transforms are normalised at build time.** The pack keeps a 100× armature scale with
   compensating mesh scales and inverse bind matrices ~2×; Godot renders correctly but every
   bone-space position (sockets, attachments) is then off by the residual factor. `build_hero.py`
   applies the transforms so bone space and visible space agree 1:1.
4. `bpy.ops.object.join()` reads the view-layer selection and silently skips objects in
   background mode — an explicit `temp_override` fixed a mesh that had lost 3 of 5 material slots.
5. `mesh.materials.clear()` resets every polygon to slot 0; the original indices must be read
   **before** the clear (this is what produced a fully dark hero).
6. The Godot glTF importer renames `Foo_Loop` → `Foo` and sets the loop flag.

## 6. Still placeholder / missing

- **Textures:** the hero uses flat PBR constants — no cloth/skin/trim texture maps yet (Phase 10 pass).
- **LODs:** none for hero or broom.
- **Equipment variants:** house colour is a runtime material override on `Robe`/`Trim`; hat, robe
  and cloak equipment meshes do not exist (`character_equipment_variants`, manifest `placeholder`).
- **Turn clip:** no dedicated one; strafe clips stand in.
- **Animation events:** glTF cannot carry method tracks, so footsteps are emitted from measured
  foot contact in `hero_animation.gd` and the wand release is emitted on the cast beat — the
  `fx:`/`sfx:`/`footstep:` naming from the art direction is used, but the timing source is the
  runtime contact test, not an authored method track.
- **Live-server phase agreement:** the replication path (state byte → record → puppet clip) is
  covered headlessly; a two-client live run was not performed in this phase.
