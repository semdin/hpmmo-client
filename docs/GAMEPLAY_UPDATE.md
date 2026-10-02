# Castle and gameplay update — 2 October 2026

## What changed

- Database inventories are copied into the player's typed array after validating entries. Empty inventories remain empty. Saved levels restore their EXP thresholds, wand aura and nameplate before the HUD is bound.
- HP/mana regeneration retains fractional progress instead of rounding every frame to zero. Damage, spell costs, EXP, level changes and bag currency refresh the UI. Chat entry and open inventory/workshop panels suppress movement and gameplay hotkeys.
- Left click selects **and attacks**. Holding it repeats the basic combo. A short input buffer handles casts near the end of recovery. Projectiles use swept collision, one-hit guards and faction checks; Bombarda/ultimate apply one area hit with falloff. Incendio is a cone with burn; disarm interrupts and weakens; stun retains aggro. Dead players cannot move, cast, collect loot or consume potions.
- The original seven leaked grass meshes are freed when a scatter position is skipped. Vertical spell effects choose a safe up vector. World re-entry rebuilds its geometry. Uncollected loot expires after 90 seconds.
- An original Hogwarts-inspired castle now has a continuous walkable entrance, Great Hall, cloisters, library and Charms classroom. Solid walls, floors, roof ceilings and furniture use collision. A cross aisle connects both wings. Tables, benches, books, house banners, masonry, windows, arches, candlelight and five spires replace the solid decorative keep. Repeated box geometry is batched into MultiMeshes.
- NPC interaction uses F; Esc closes dialogue/panels. Madam Pince and Professor Flitwick occupy the new rooms. NPCs use animated wizard models and are excluded from combat.
- Seven encounter groups include normal packs of three/five, a solo matriarch, and a commander with two bodyguards. Clear spawn anchors are randomized within designated outdoor zones. Pulling one member alerts its group; dead groups respawn together elsewhere after 25–35 seconds (boss groups: 90–120 seconds). Corpses animate, linger four seconds, then sink. Boss windups are interruptible and cancel on death; respawn resets enrage and status effects.
- New Quaternius animated models replace the Inferi/Snatcher placeholders and distinguish the commander. A new original articulated spider rig provides walking and collapse animation. These are stylized assets, matching the existing wizard art direction.
- Flight blends into a seated animation, with acceleration, hover, pitch/bank and textured flame particles. Shift mounts/dismounts; Space rises; Ctrl descends. Dismount is permitted only within three metres of suitable ground; altitude is capped at 45 metres.
- Fog is disabled, bloom is reduced, daylight is clearer, and the large translucent boundary walls are hidden. Collision boundaries remain. Sparks and fire use soft particle textures rather than opaque primitives.

## Try it

Launch with the existing launcher or `play.bat`. From the courtyard, follow the **north stone road** to the open castle entrance. Walk through the Great Hall's central aisle; take the cross passage left for the library or right for Charms. Outdoor packs and bosses live away from the castle approach.

| Control | Action |
| --- | --- |
| WASD | Camera-relative movement |
| Right mouse / wheel | Orbit / zoom |
| Left click / hold | Select and attack / repeat basic combo |
| Tab | Cycle nearby valid enemies |
| 1–4, Q, E | Skills, shield, ultimate |
| Shift | Mount / safe dismount |
| Space / Ctrl | Rise / descend while mounted |
| Space | Jump on foot |
| F / Esc | Talk / close panels |
| I / O / Z | Inventory / workshop / pickup |

## Verification

`tools/run_game_checks.ps1 -GodotPath <path-to-Godot-executable>` imports resources, runs the regression scene, and fails on script errors, test failures, missing completion or leaked objects/resources.

The suite uses synthetic character data and disables quest persistence. It covers 72 checks, including JSON inventory loading, regen at 120 FPS, HP/mana/EXP binding, actual projectile damage, duplicate-hit rejection, friendly NPCs, linked aggro, group respawn, enrage reset, boss cancellation, monolith wave thresholds, real character movement through the entrance and library passage, chat input isolation, inventory updates, safe flight, death/respawn and scene re-entry.

Validated on Godot **4.7.2**, both headless and Forward+ Vulkan on **Intel Graphics**. The reported inventory assignment error, collinear-vector warnings and seven-mesh shutdown leak did not recur. Verbose Vulkan output still contains driver registry/RGB8 conversion warnings; these are separate from the reported gameplay/resource failures.

`scenes/test/capture_world.tscn` renders repeatable exterior, interior, HUD, enemy and flight screenshots into `tools/downloads/` using a graphical renderer.

## Scope and remaining limits

This is a local gameplay and art update. The remote VPS has **not** been deployed or tested with multiple clients. The existing networking layer still relays client state/spells; shared server-authoritative encounters, loot and progression require a separate networking implementation. The new indoor rooms are playable; the decorative towers do not contain upper-floor interiors. Assets and architecture remain stylized rather than photorealistic.

New asset sources and licenses are recorded in [asset credits](../assets/ASSET_CREDITS.md).

## Rendered previews

![Castle exterior](previews/castle-exterior.png)

![Walkable Great Hall](previews/great-hall.png)

![Library and Madam Pince](previews/library.png)

![Enemy models](previews/enemy-assets.png)

![Gameplay HUD](previews/gameplay-hud.png)
