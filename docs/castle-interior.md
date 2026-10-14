# Castle interior redesign (F0 design)

Status: **F3 first pass done** (2026-10-13): Gothic build + atmosphere, enchanted ceiling, candles, banners, stained glass, furniture, hourglasses; perf tuned for the low preset. Replaces the code-built greybox in
`scripts/world/castle_interior_builder.gd`, removed at F1b (2026-10-13).

Decisions: stylized-realistic and original (inspired by the castle, never a film
copy), the full room programme below, the `maps.json` floor/portal contract may
change, Blender authors the architecture, fal.ai supplies concept art, textures,
2D dressing and a measured number (~10-20) of hero props.

## Why the old interior fails

* **Scale:** rooms are 40-60 m boxes with 6 m flat ceilings - hangars, not halls.
  Nothing is tall and narrow, nothing frames a view.
* **Logic:** rooms are rectangles placed where they fit; corridors connect
  nothing in particular; galleries float in an empty stair hall.
* **Wayfinding:** text signs ("↑ FIRST FLOOR") do the job architecture should do.
* **Surface:** one brick texture everywhere, no trim, no depth, flat lighting.

## Design pillars

1. **Read the way without signs.** Every junction shows its destinations through
   light, sound, colour and silhouette. Text labels are a fallback, not the plan.
2. **Every room has a job.** A room exists because a quest, a class, a social
   activity or a route needs it. No filler rooms.
3. **One landmark per wing.** Something tall or bright that is visible from the
   junction leading to it.
4. **Compression → release.** Narrow, lower corridors open into tall rooms; the
   contrast is what makes the Great Hall feel great.
5. **Built from a kit.** Every wall, arch, vault and stair is a module on a 1 m
   grid (4 m bays), so collision, LOD and batching stay predictable.

## Levels

HP-scale revision (2026-10-13, after the first walk-through felt small): storey
**10 m** (stacked rooms 9 m tall), seven floors plus the dungeons, like the castle
in the books. Heights are fixed in `art/castle/scripts/make_layout.py` and copied
into `maps.json` `floors` at F1b.

| Level | y (local / world) | Contents |
| --- | --- | --- |
| L-1 Dungeons | -10 / 190 | Dungeon crossing under the tower, Potions, Slytherin, kitchens, Hufflepuff, encounter gate |
| L0 Ground | 0 / 200 | Front doors, Entrance Hall, Great Hall, Dueling Club, foot of the Grand Staircase |
| L1 | 10 / 210 | Entrance balcony, Transfiguration |
| L2 | 20 / 220 | Defence Against the Dark Arts, Charms |
| L3-L4 | 30-40 / 230-240 | Library (double height, mezzanine at L4) |
| L5 | 50 / 250 | Ravenclaw (above the library) |
| L6 | 60 / 260 | Bridge to the Owlery (roof 75 = broom take-off) |
| L7 "seventh floor" | 70 / 270 | Gryffindor (portrait), Room of Requirement (tapestry) |

Every floor has the Grand Staircase gallery, an east corridor and a door to the
service stair (the always-available fallback route).

## Grand Staircase (moving stairs)

* Tower 46 x 46 m, open well 35 x 35 m, galleries 5.5 m deep on every floor,
  85 m to the roof.
* One 30 m flight (rise 10, 18.4 deg, 5 m wide) per storey, seven in all. Each
  swings 90 deg about the tower axis between two docks; where it docks, a stone
  tongue reaches from the gallery edge to its end, and a gate closes every tongue
  whose flight is away.
* Docks were chosen by `art/castle/scripts/stair_solver.py`: for adjacent storeys,
  every dock combination and every swing (one storey at a time) leaves >= 2.6 m
  head room; the result is a spiral (each storey's docks are the one below rotated
  -90 deg) where consecutive flights meet tongues 6 m apart on the same gallery
  side, so a route up exists in many states and the gallery ring always connects.
* Schedule: even storeys swing in two windows of each 32 s cycle, odd storeys a
  quarter-cycle later - adjacent storeys never move together (the solver's
  assumption, and the authority's rule at F1b).

## Room programme

| # | Room | Gameplay job | Landmark / identity | Rough size (w × l × h) |
| --- | --- | --- | --- | --- |
| 1 | **Entrance Hall** | Spawn, respawn, hub; three exits (Great Hall W, Dueling Club E, Grand Staircase N) plus the dungeon stair under the marble stair | Marble staircase, four house hourglasses, huge front doors | 36 × 44 × 28 |
| 2 | **Great Hall** | Social space, quest giver hub, events, feasts | Enchanted ceiling (sky shader), floating candles, four long tables, staff dais, house banners | 28 × 84 × 28 |
| 3 | **Grand Staircase** | Vertical travel L0-L3; the existing server-authoritative moving stairs keep their role | Square well open to the roof, moving flights, talking portraits on every wall | 46 × 46 × 85 |
| 4 | **Library** | Lore, research quests, quiet zone | Two-storey shelves, mezzanine, Restricted Section gate (rank-gated) | 54 × 40 × 19 |
| 5 | **Classrooms** (Charms, Defence, Transfiguration, Potions) | Class quests, spell training | Each has its own prop: tiered benches, skeleton dragon, cages, cauldrons | 26 × 27 × 9 each |
| 6 | **Common rooms** (4) | House-only social space, tied to house standing | House colours, fireplace, crest; each entrance is distinct (portrait, eagle knocker, barrels, wall in the dungeon) | 26-30 × 25 × 8-9 |
| 7 | **Dungeons** | Route to Potions, Slytherin, encounter gate | Cold green light, dripping water, low vaults | corridors 6 × 6 |
| 8 | **Room of Requirement** | Pace past the tapestry wall 3 times → a door appears for that player; inside: a training room (dummies, duel targets). Later versions can change the room by need | Tapestry of dancing trolls, a door that fades in | 26 × 27 × 9 |
| 9 | **Owlery** | Mail/delivery quests; the open top is the castle's broom take-off point (portal to the grounds, landing in the air near the tower) | Round tower with perches, owls, open arches, wind | 20 × 20, 15 h + roof |
| 10 | **Dueling Club** | Opt-in PvP duels and spectating (rules are a separate gameplay task; F1 builds only the space) | Raised duel platform 4 × 20, tiered gallery, banners | 36 × 32 × 18 |

## Flow (top view, L0, north up, front doors south)

```
                 [ Grand Staircase well ]  -- moving stairs to L1-L3
                           │
 [ Great Hall ]════[ Entrance Hall ]════[ Dueling Club ]
  (W, long axis E-W)       │   ↓ stair under the marble stair to L-1 (dungeons)
                     [ Front doors ]  -> grounds portal
```

* **First visit:** doors → the Entrance Hall opens up (release) → the Great Hall's
  warm light and noise pull the player west → the quest giver is there.
* **Upward routes:** the Grand Staircase is the only main vertical; a plain service
  stair in the east wing is the fallback when the moving flights point elsewhere,
  as today.
* **Owlery:** reached only from L3 over an open bridge, so the take-off point sits
  at the end of a deliberate climb.
* **Dungeons:** the light gets colder and the ceiling lower the deeper you go.

## Scale rules (player = 1.8 m)

| Element | Rule |
| --- | --- |
| Grid | 1 m snap, 4 m structural bays |
| Doors | 3 × 4.5 standard, 6 × 9 ceremonial (Great Hall, front doors) |
| Corridors | 8 m wide, 9 m high, a window or torch every 6 m |
| Stairs | 0.2 m rise / 0.35 m tread visual, one ramp collider (as now), 3 m minimum width |
| Rails | 1.1 m, on every drop over 0.6 m |
| Halls | Height ≥ width; long axis ≥ 2.5 × width |
| Sightlines | From each junction, the next landmark is visible within 30 m |

## Wayfinding and lighting

* **Colour by function:** warm candle gold = social (Great Hall, common rooms);
  cool daylight through windows = study (Library, classrooms); green-cyan =
  dungeons; violet = magic/secret (Room of Requirement, encounter gate).
* **Light:** LightmapGI bake for the static architecture, a few dynamic lights for
  candles/fires, ReflectionProbe per room, volumetric fog for window shafts.
* **Sound:** each room has its ambience bed; open doorways leak it into corridors.

## Pipeline

| Stage | Tool | Output |
| --- | --- | --- |
| Concepts | fal.ai (nano-banana) | 2-4 images per hero room, chosen before blockout |
| Kit + blockout | Blender 5.2, Python (`art/castle/scripts/`, next to `art/map/`) | `art/castle/castle_interior.blend`, glTF per wing |
| Textures | fal.ai seamless + Poly Haven CC0 | PBR sets and trim sheets in `assets/castle/textures/` |
| Hero props | fal image-to-3D, cleaned and decimated in Blender | `assets/castle/props/` |
| 2D dressing | fal.ai | portraits, stained glass, tapestries, banners, decals |
| Collision | glTF `-colonly` meshes from the same Blender file | one source for client and server |
| Lighting | Godot LightmapGI | baked per wing |

Provenance of every AI-generated asset is recorded in
`assets/castle/LICENSES/AI_GENERATED.md`.

## Milestones

* **F0 Design** - this document, concepts for the Entrance Hall and Great Hall
  (first round in `art/castle/concepts/`, see `PROVENANCE.md` there).
* **F1a Blockout (done)** - `scripts/make_layout.py` writes `art/castle/layout.json`
  (never hand-edit the JSON);
  `scripts/castle_geometry.py` (pure Python) -> `build_blockout.py` (Blender,
  `blender -b --factory-startup -P build_blockout.py -- layout.json
  <client>/assets/castle/castle_blockout.glb castle_blockout.blend`); plans via
  `plan_render.py`, Blender views via `render_views.py`. Visual meshes are merged
  per room+material, collision is one `-convcolonly` box per piece. Copy
  `layout.json` to `assets/castle/castle_layout.json` after a change.
  Walk it: `tools/castle/castle_blockout_preview.tscn` (F6, P pauses the stairs; `-- --check` runs
  floor/door/stair checks plus every moving flight at both docks and a rider
  carried through a swing, 145/0 on the HP-scale build; `-- --shots <dir>`).
* **F1b Live switch (done 2026-10-13)** - `castle_interior.gd` loads the glb
  through `scripts/world/castle/castle_blockout.gd` (grid materials + bay
  lights on the client, visuals stripped on the collision-only server);
  `art/castle/scripts/export_catalog.py` writes the vestibule spawn, the exit
  portal and a `staircases` list (one HPStaircase spec per flight) into the
  server-owned `maps.json`. `HPStaircase` runs one instance per entry
  (`spec_index`, object ids 11-17): swing about `pivot`, tongue gates,
  `start_delay_ms` staggering, no built-in landings/fallback (`map_geometry`),
  state published only to players on its map; the single-spec dev/test path is
  unchanged. Two rider rules fixed on the way: a docked deck no longer clamps
  its riders (they could never step off), and the docked rider set is rebuilt
  every tick. `bash art/castle/rebuild.sh` runs the whole chain.
  Evidence: `dev.ps1 test` green, `castle_walkthrough.tscn` 152/0 (derived
  from the layout), preview `--check` 145/0, `journey_e2e.py` castle entry ->
  ride -> exit -> save all pass. Known red, not from this work (same failures
  on HEAD without it): `staircase_sim.py`'s outdoor dev-hook probes cannot
  board, `maps_sim.py`'s grounds door approach, the journey's `fight` step.
* **F2 Gothic dressing (first pass done 2026-10-13)** - instead of fixed-size
  kit modules (the old `assets/models/gothic_kit` is sized for the 6 m storey),
  `art/castle/scripts/gothic_dress.py` dresses every room parametrically from
  the layout: quadripartite ribbed groin vaults (one bay per long-wall window
  pitch, windows centred in the lunettes - the layout's windows are placed on
  bay centres for that), transverse/diagonal/ridge/wall ribs and bosses,
  engaged shafts with bases and capitals (with colliders), plinth and
  springing courses broken at openings, pointed heads + moulded surrounds +
  leaded glass + mullions/transoms in windows, pointed heads and surrounds on
  doorways, stone balustrades on every rail. `build_blockout.py --gothic`
  writes `assets/castle/castle_interior.glb` (the live map's choice; the grey
  `castle_blockout.glb` stays for `--grey` previews). Materials are
  world-space triplanar PBR (`castle_blockout.gd kit_material`): Poly Haven CC0
  sandstone ashlar walls, dressed sandstone mouldings, plaster webs, worn
  flagstones, cold grey stone in the dungeons (`art/textures/scripts/
  ph_textures.py` fetches sets with their licence manifest). ~315k dressing
  triangles; LOD / visibility ranges come with F3.
* **F3 Vertical slice (first pass done 2026-10-13)** - Entrance Hall + Great Hall:
  * atmosphere (`scripts/world/castle/castle_atmosphere.gd`, applied by the
    map controller on the way in, restored on the way out): dim ambient,
    SSAO + SSIL + volumetric fog on medium/high, SDFGI on high, glow;
  * `castle_decor.gd`: floating candles (MultiMesh, bobbing in
    `assets/shaders/castle/floating_candle.gdshader` + `candle_flame.gdshader`),
    chandeliers, wall sconces, shadowed moonlight through the windows (beams
    in the fog); the enchanted ceiling (`enchanted_sky.gdshader`, view-direction
    dusk sky with stars and clouds) on the Great Hall's vault webs;
  * `art/castle/scripts/castle_props.py`: trestle tables, benches (colliders),
    staff table and chairs, four giant house-point hourglasses (brass, glass,
    glowing gems), house banners; fal-generated original banner and stained
    glass textures (`assets/castle/textures/`, PROVENANCE.md there);
  * performance: occlusion culling on (box occluders from the glb's wall /
    floor / ceiling bodies), the PBR shader's `lite` path (no roughness / AO
    reads) on low. Measured on the Intel iGPU at 1600x900 with
    `castle_blockout_preview.tscn -- --perf --quality=low`: 46-64 fps across
    the review views (was 31-45). Medium/high are 20-30 fps there - auto picks
    low on integrated GPUs. Two traps found: a spatial shader that writes
    `SSS_STRENGTH` turns on a full-screen subsurface pass (~5 ms on the iGPU);
    the PBR texture reads are the castle's main per-pixel cost, not the lights.
  * second pass: 26 framed original portraits (Entrance Hall, every Grand
    Staircase gallery), a compass-rose inlay (round alpha mask), the Great
    Hall doors standing open (colliders), and fal image-to-3D hero props
    (`fal-ai/trellis-2`, ~30k vertices, `assets/castle/props/`): the golden
    owl lectern on the dais and two suits of armour by the Great Hall doors,
    placed and height-normalised by `castle_decor.gd _prop`.
* **F4 Remaining rooms** in this order: Grand Staircase, Dungeons + Potions,
  Library, classrooms, common rooms, Dueling Club, Room of Requirement, Owlery.
* **F5 Integration** - server collision from the glTF, walkthrough and
  multiplayer gates rewritten for the new layout, old builder removed.

## Open questions

* Server collision: the world server today runs the builder collision-only; at
  F5 it loads the collision glTF instead. Check that the headless import path and
  `dev.ps1 sync-world` carry the asset.
* Owlery take-off needs a matching grounds-side landing (and an Owlery tower on
  the exterior); the exterior pass comes after the interior settles.
* Common-room access: house-only, and whether a minimum house rank applies.
