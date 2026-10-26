# Test and preview tools

The automated test cycle is `.\dev.ps1 ready` (client import, world boot,
`server/tests/multiplayer_sim.py`); see `dev-cycle.md`. Everything below is a
tool you run when you want to look at something.

## Local multiplayer (two players on one machine)

```powershell
.\dev.ps1 local                                  # Harry + Draco, level 35 test characters
.\dev.ps1 local -Names "Harry,Draco,Luna" -Char 50
```

Starts a dev world server on 127.0.0.1:7777 (no account service, nothing is
saved, `HPMMO_ALLOW_DEV_JOIN=1`) and one game window per name, side by side.
Every joiner gets the `-Char` test character (`--test-char` presets: `trial`,
`corridor`, `fluffy`, `max`, or a level). Close the windows and the server
stops. Server log: `%TEMP%\hpmmo-local-server.log`.

A single window can join any dev server by hand:
`godot --path client res://scenes/main/main_menu.tscn --dev-join=Harry [--server IP] [--port N]`.

Use it for anything between players: party invites, duels and group duels
(right-click the other player), chat.

## Solo with a test character

```powershell
cd client; godot scenes/main/main_menu.tscn --solo --test-char=fluffy
```

## Screenshot tools (`client/scenes/test/`)

Run windowed; shots land in `client/tools/downloads/`. Every tool that boots
the game world plays a `--test-char` wizard (`TestGround.use_test_character`)
and stands at current-map spots (`TestGround.at`, `TestGround.pack_spot`,
authored map spawns), never at hand-typed coordinates.

| Scene | Shows |
|---|---|
| `ui_hud_capture.tscn` | HUD in a fight beside a real pack, castle interior, maintenance countdown, broom flight badges, settings, social layer (invites, player menu, duel). `-- --only=social` for the social shots. |
| `ui_capture.tscn` | Inventory, merchant, tooltips, skills, chest, bestiary, map, character, Floo, Ollivander, NPC dialogue, target ring. |
| `ui_menu_capture.tscn` | Login, register, maintenance notice, character select and create (`--resolution 1280x800`). |
| `rig_capture.tscn` | Wand in hand, cast aim, broom grip, walking feet. |
| `bestiary_capture.tscn` | Regenerates `assets/ui/bestiary/<species>.png` (writes game assets). |

## Interactive previews

| Scene | Use |
|---|---|
| `vfx_viewer.tscn` | Spell VFX tuning on the real world (`-- --spell=stupefy`, `--shot` saves frames and exits). |
| `spell_preview.tscn` / `stupefy_preview.tscn` | Isolated projectile + VFX stage. |
| `clip_preview.tscn` | A spell's cast clip through the game path (`-- --spell stupefy`). |
| `motion_preview.tscn` | The player controller on a neutral stage. |

`net_client_probe.tscn` is the headless client `multiplayer_sim.py` drives; it
also has manual modes (`--mode=portkey`, `--mode=duel`).

`ui_hud_capture.tscn` takes `-- --only=<combat|castle|maintenance|onboarding|mounted|settings|social>`
to shoot one subject.

## Offline travel and map probes (`client/tools/capture/`)

Each walks the real request path offline, prints its findings and ends with a
verdict line; `-- --out=<dir>` also saves photographs.

| Scene | Checks | Verdict |
|---|---|---|
| `cavern_probe.tscn` | crypt portal into the Blackweb Caverns, packs on the floor, Venomfang poison, Broodguard web, the seal stone breaks and drops loot | `CAVERN PASS` |
| `floo_probe.tscn` | courtyard -> Hagrid -> Great Hall -> caverns camp; the last trip is refused for lack of powder (by design) | `FLOO PASS` |
| `passage_probe.tscn` | Hogsmeade trapdoor <-> One-Eyed Witch, Room of Requirement <-> Egg Caverns cabinets | `PASSAGE PASS` |
| `portkey_probe.tscn` | a boot set down in the courtyard carries its owner to Hagrid's hut | `PORTKEY ... PASS` |
| `portal_probe.tscn` | portals in order as a level-35 tester: `-- --route=castle_door,fc_entry,fc_exit,vestibule_exit`, `trial_entry,trial_exit`, `crypt_descend,caverns_ascend` (or `--there=<id> --back=<id>`); refusals are reported | `PROBE PASS` |
| `world_shots.tscn` | stills from a views file (`-- --views=<views.json> --out=<dir> [--map=<id>] [--interior]`) | - |

Previews: `tools/castle/castle_blockout_preview.tscn` (castle interior),
`tools/terrain/grounds_preview.tscn` (grounds). Asset builders that rewrite game
assets from `art/` inputs: `tools/terrain/build_grounds.gd`,
`cook_vegetation.gd`, `tools/maps/build_cavern_collision.gd`,
`tools/ui/dump_heights.tscn` (heights for `paint_world_map.py`).
Inspectors: `tools/inspect_import.gd`, `tools/measure_import.gd` (`--script`).
