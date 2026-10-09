# Stupefy: scarlet discharge

Stupefy uses a textured plasma heart, four irregular helical filaments, GPU
sparks, broken impact arcs and ballistic light splinters. The plasma uses alpha
blending to retain crimson colour against daylight; the narrow filaments use
additive blending. Both shaders use the effect clock so slow motion and pause
work consistently. The source textures are the project's existing original
flow/noise texture and spark sprite; no external texture pack was imported.

The cast discharge follows the animated wand tip. Travel samples the actual
projectile path, including reflections. Impact retains a detached fading wake
for 0.26 seconds, hides the travelling heart immediately, then releases the
effect. Rejection, death and transfer still cancel it immediately. Damage,
projectile speed, range, cooldown and stun rules are unchanged.

## Review in Godot

From the workspace root:

```powershell
godot --path client res://scenes/test/stupefy_preview.tscn
```

This isolated scene uses the real equipped character, projectile and collision.
Space replays, S switches 0.4x/1x, 1/2/3 selects quality, Escape closes. The
normal world viewer remains available for checking daylight and world scale:

```powershell
godot --path client res://scenes/test/vfx_viewer.tscn -- --spell=stupefy
```

For frame evidence, use `--fixed-fps 60 -- --capture` with the isolated scene.
Frames go to `tools/downloads/stupefy-preview`. `--quality=low` and `--speed=1`
can be supplied after `--` as well.

## Tuning

- `scripts/spells/vfx_library.gd`: stage lengths, sparks, lights and base wake.
- `scripts/spells/stupefy_vfx.gd`: filament paths, width, impact arcs, splinters.
- `assets/shaders/stupefy_plasma.gdshader`: flow distortion, erosion, colour.
- `assets/shaders/stupefy_filament.gdshader`: filament core, glow and flow.

Low quality keeps the readable plasma core, two filaments and twelve impact
splinters, and removes optional GPU sparks and dynamic lights. High uses four
filaments and twenty-six splinters. Histories and tessellation are bounded.

References: [Simon Trümpler's VFX texture resource index](https://simonschreibt.notion.site/Textures-for-VFX-Database-2c72eccccfa84a0eae927d778ad746cc)
and [Godot's particle system](https://docs.godotengine.org/en/stable/classes/class_gpuparticles3d.html).
These are workflow references; the effect's geometry and shaders are authored
in this project.
