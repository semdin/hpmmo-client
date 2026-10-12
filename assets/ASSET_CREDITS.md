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

# Arcane interface and equipment pass (2026-10-08)

The HUD and inventory now opt into four generated chrome images through
`scripts/ui/arcane_skin.gd`: window, primary button, inset slot and circular
minimap bezel. Layout, gauges, tooltips and interaction states remain code-driven.
Seven additional equipment icons accompany the obtainable accessories.
Provenance and slice geometry: `assets/ui/arcane/PROVENANCE.md`.
Hashes: `family-arcane-chrome` and `family-arcane-equipment-icons` in the manifest.
Existing screens continue to use the central flat theme unless they opt in.

- Fonts: **Cinzel** (headings) and **Alegreya Sans** (body), both SIL OFL 1.1,
  vendored in `assets/fonts/` with the licence beside each face.

The earlier PNG kit (Kenney *Fantasy UI Borders*, Kenney *UI Pack* and the
procedural shapes) was removed in the same pass: nothing in the project loads
those files any more, and their licence copies went with them.

# Audio pass (2026-10-10)

The whole sound set was regenerated from `tools/audio/synth_spell_sfx.py`
(still project-original synthesis; still zero downloaded audio): a loudness
mastering stage levels every file, the interface speaks one wand-chime
material, footsteps are five-layer material recordings, each creature species
owns its voice family (spider, snatcher, inferi, boss), and five stereo
classical music beds were added (menu, overworld, castle, dungeon, combat).
The classical beds are original synthesised arrangements of public-domain works
by Grieg, Pachelbel, Bach, Beethoven and Satie - no recording or arrangement by
a third party is used. Full provenance: `assets/audio/CREDITS-spell-audio.md`.

Existing KayKit character/environment files are retained. This document records the provenance of newly added assets; it does not change the terms of existing assets.
- `models/characters/hero_wizard.glb` animations: ground, combat and spell clips retargeted from **Quaternius Universal Animation Library 1**, CC0 1.0, https://quaternius.itch.io/universal-animation-library (source GLB and license in `candidates/character/quaternius-universal-animation-library`). Broom, stun and two-handed cast clips are project-authored.

# Grounds terrain (2026-10-12)

The outdoor map's terrain runs on **Terrain3D** 1.0.2 by Cory Petkovsek and
Roope Palmroos (MIT; `addons/terrain_3d/LICENSE.txt`). Heights and painting are
project-original, generated from `art/map/layout.json` by the scripts in
`art/map/scripts/`.

Ground textures in `assets/terrain/textures/` (repacked to Terrain3D's
albedo+height / normal+roughness layout at 1024 px by
`art/map/scripts/pack_terrain_textures.py`), all CC0 1.0:

| Slot | Source |
| --- | --- |
| grass_meadow | ambientCG *Ground037* (as shipped in the Terrain3D demo) |
| cliff_rock | ambientCG *Rock023* (as shipped in the Terrain3D demo) |
| forest_floor, sand_shore (also the tinted dirt_path), grass_lush | CC0 Textures leaves / sand / grass sets, as shipped in Zylann's *godot_hterrain* demo |
| gravel | CC0 Textures *Rocks07* (now ambientCG), via the same demo |
| cobblestone | Poly Haven *stone_tiles_02* (already in `assets/textures/pbr/`) |

# Grounds vegetation, props and architecture textures (2026-10-12)

All CC0 1.0 from **Poly Haven** (https://polyhaven.com). The models were
rebuilt into game LODs (decimated wood, clustered leaf cards rendered from the
source sprays, a crossed-quad impostor) by
`art/vegetation/scripts/build_foliage.py` and `build_props.py`; the cooked game
scenes live in `assets/terrain/vegetation/`.

| Game model (`assets/models/vegetation/`) | Poly Haven source |
| --- | --- |
| fir_a, fir_b, fir_c | *fir_tree_01* |
| pine_a, pine_b, pine_c | *pine_tree_01* |
| broadleaf_a | *tree_small_02* |
| broadleaf_b | *island_tree_01* |
| fern_a, fern_b | *fern_02* |
| shrub | *shrub_04* |
| rock_boulder | *boulder_01* |
| rock_slab | *namaqualand_boulder_05* |
| rock_moss_a0-a2, rock_moss_b0-b2 | *rock_moss_set_01*, *rock_moss_set_02* |
| stump | *tree_stump_01* |
| log | *dead_tree_trunk_02* |

Castle and village textures in `assets/textures/pbr/` (2k, Poly Haven, CC0 1.0):
*castle_wall_varriation*, *stone_wall*, *roof_slates_02*, *grey_roof_tiles*,
*medieval_wood*, *wooden_planks*, *white_rough_plaster*, *mossy_stone_wall*,
*cobblestone_floor_04*. The castle, village and site buildings themselves are
project-original geometry (`scripts/world/grounds/`).
