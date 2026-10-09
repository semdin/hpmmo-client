# Spell signatures

The remaining five spells use procedural Godot spatial shaders, world-space
ImmediateMesh strips and GPU particles. Existing local noise/flipbook assets are
reused; no external art dependency is required. Stupefy and the basic cast retain
their own compositions.

| Spell | Silhouette and motion | Upper-body gesture |
| --- | --- | --- |
| Incendio | Directional flame sheets fan across the configured cone; embers and rising fire on burning targets | Lateral wand sweep and torso turn |
| Bombarda | Molten core with counter-rotating arcs; ballistic sparks and two expanding ground shockwaves | Draw back, forward push, recoil |
| Expelliarmus | Crossed rose-coloured crescents with a thin trail and crossing impact slashes | Fast lateral wrist sweep |
| Protego | Translucent blue ward with moving surface lines, localized hit ripple and erosion on expiry | Raised defensive arm |
| Avada Arcana | Emerald branching trails, jagged ground discharge and vertical lightning | Raised preparation and stronger forward release |

`spell_signature_vfx.gd` reuses the Stupefy strip/history renderer. The travel
effect follows a reflected projectile's direction, then detaches and fades for
0.26 seconds at collision. Low quality reduces branches, flame sheets and arc
segments while keeping each spell's core silhouette. The hidden carrier mesh
does not render. The visible ward radius is 1.8 m, matching its collision shape.

Cone range/angle and blast radii come from GameData. Scenery rays limit the
Incendio fan's centre lines. Bombarda/Ultimate draw one full-radius blast from
the projectile collision, rather than repeating that area at every victim.
Damage, cooldowns and authoritative simulation rules are unchanged.

## Review

From the repository root:

```powershell
godot_console --path client res://scenes/test/spell_preview.tscn -- --spell=incendio
```

Supported spell IDs: `incendio`, `bombarda`, `expelliarmus`, `protego`, `ultimate`,
`stupefy`, `basic_cast`. Space replays, S switches speed, 1/2/3 changes quality.
To capture frames, put the engine's fixed FPS option before `--`:

```powershell
godot_console --path client res://scenes/test/spell_preview.tscn --fixed-fps 60 -- --spell=ultimate --capture --speed=0.7
```

The review uses the real character, real projectile collision and live Protego
shield. It inserts a short pose-settle delay only in this isolated review stage.
Incendio's target hit/burn and Protego's impact are staged for visual inspection.
Captured frames are saved under `client/tools/downloads/<spell>-preview/`.

Regression scenes: `vfx_regression.tscn`, `rig_regression.tscn`,
`test_scenario.tscn` in `scenes/test`. They cover resource loading, low/high
signatures, reflected aim, trail lifetime, configured area bounds, shield
surface hits, wand grip/aim and existing combat behavior.
