# Assets added in the October 2026 gameplay pass

- `vfx/flame_01.png`, `vfx/spark_01.png`: **Kenney Particle Pack**, CC0 1.0. https://kenney.nl/assets/particle-pack — original license included in `vfx/Kenney-License.txt`.
- `models/monsters/Demon.gltf`, `Ninja.gltf`, `Orc_Skull.gltf`, `Atlas_Monsters.png`: **Quaternius Ultimate Monsters**, CC0 1.0. https://quaternius.com/packs/ultimatemonsters.html — downloaded from the author's linked public Google Drive, Big/glTF folder. Original license included in `models/monsters/License.txt` (the author's shared license text uses the title “Ultimate Platformer Pack”). The GLTFs contain their own embedded textures and animations.
- `scripts/assets/spider_rig.gd`: original articulated spider geometry and motion made for this project.
- `scripts/world/castle_builder.gd`, `textures/masonry.gdshader`: original modular Hogwarts-inspired architecture and procedural masonry. No extracted commercial-game meshes or textures.

# Icon pass (2026-10-08)

The icon set was replaced with pictures made for this project.

- `assets/ui/icons/icon_*.png` (64 files): spell, item, material, stat, status,
  map-marker, interface-control and house-crest icons. **Generated for this project
  with OpenAI Imagegen** from project art notes, delivered 512x512 RGBA with real
  transparency, installed 2026-10-08. Provenance note:
  `assets/ui/LICENSES/AI_GENERATED_ICONS.md`; per-file hashes:
  `assets/manifest.json` (`family-icon-set`). No third-party icon set was used as an
  image input, and the file names carry project ids only.
- `assets/ui/icons/icons_preview.jpg`: contact sheet of the same 64 files, shipped
  with the pack.
- The 19 icons this pass replaced came from gnola14's *496 pixel art icons for
  medieval/fantasy RPG* (CC0 1.0,
  https://opengameart.org/content/496-pixel-art-icons-for-medievalfantasy-rpg).
  No gnola14 image is distributed any more: the licence text stays at
  `assets/ui/LICENSES/oga-rpg-icons-496.txt` for the record, and the pack is listed as
  superseded in `assets/manifest.json`.

The chrome did not change. Frames, buttons, slots, bars and the minimap bezel are
still flat `StyleBoxFlat` boxes in `assets/ui/hpmmo.tres`; the icons are the only
images under `assets/ui`, and `UITheme.chrome_at()` scales one to the size each
widget asks for.

# UI (October 2026 UI pass)
The interface is **not drawn from art**. `assets/ui/hpmmo.tres` is a single
Godot `Theme` whose palette, control styles and type scale are flat
`StyleBoxFlat` boxes, and every surface in the game takes its look from it (the
project default theme is the same file, so a bare `Button.new()` already matches).
There is no frame, button, slot or bar image to slice, tint or re-export.

- `assets/ui/icons/icon_*.png`: see the icon pass above - the whole folder was
  replaced on 2026-10-08, so the set is no longer the gnola14 CC0 pixels.
- Everything else in the interface — window and card frames, buttons in all four
  states, the hotbar cells, the gauges, the scrollbars, the minimap bezel and its
  markers, the player plate, the level badge — is a `StyleBoxFlat` in the theme.
- Fonts: **Cinzel** (headings) and **Alegreya Sans** (body), both SIL OFL 1.1,
  vendored in `assets/fonts/` with the licence beside each face.

The earlier PNG kit (Kenney *Fantasy UI Borders*, Kenney *UI Pack* and the
procedural shapes) was removed in the same pass: nothing in the project loads
those files any more, and their licence copies went with them.

Existing KayKit character/environment files are retained. This document records the provenance of newly added assets; it does not change the terms of existing assets.
