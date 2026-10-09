# Daylight and vegetation palette

Outdoor lighting uses subdued blue-grey sky fill (0.62 energy), a warm neutral
sun (1.1), ACES exposure 0.92 and restrained glow with no full-screen bloom.
SSAO works over 0.9 m at high quality to ground feet, props and architectural
corners. The sunlight angle is 38 degrees above the ground.

All meadow surfaces share `PBR.MEADOW_TINT`, including the core terrain, distant
meadow, hill bands, pitch and grass cards. Leaf cards use a related muted green.
These multiply the existing textured materials, retaining their surface detail.

The PBR shader now transforms its sampled world-space normal into view space
before assigning `NORMAL`, as required by [Godot's spatial shader contract](https://docs.godotengine.org/en/4.7/tutorials/shaders/shader_reference/spatial_shader.html).
It also uses the normal matrix for nonuniform model scaling. Previously the
surface light response changed incorrectly with camera orientation.

Quality budgets are applied after world construction, so the light rig cannot
overwrite them. Low retains two shadow cascades to 45 m; high uses four to
110 m. Low still disables SSAO, glow and MSAA and reduces vegetation/particles.
Nearby shadows now have an intentional GPU cost on low quality.

Visual review: run `art_capture.tscn` with `-- --mode=after-lighting --quality=high`
or `--quality=low`. Captures include exterior, meadow and interior views.
Run `lighting_regression.tscn` graphically to measure whether diffuse lighting
stays stable as the camera circles a matte floor. `art_regression.tscn` verifies
the live quality settings and material contracts headlessly.
