# Development cycle

One command takes a change from "edited" to "ready to commit":

```powershell
.\dev.ps1 ready          # every change (~5 min)
.\dev.ps1 local          # two game windows on a local dev server (party, duel checks) - see test-tools.md
```

Run it from the workspace folder (`game/`). It does not open the Godot editor:
everything Godot has to do (importing new assets, rebuilding the class cache)
runs headless.

## Who owns what

There are two generated copies. Edit the source, never the copy:

| You change... | Edit it in | Copied to (generated) |
|---|---|---|
| Gameplay rules, protocol, authority, combat, data in `hpmmo_sim` | `server/world/addons/hpmmo_sim/` | `client/addons/hpmmo_sim/` (`SYNC.json`) |
| Scenes, client scripts, assets, maps, UI | `client/` | `server/world/` (`WORLD_EXPORT.json`) |
| World server entry (`server/world/server/`) | `server/world/server/` | - |

`ready` refuses to run when a generated copy has hand edits it would overwrite,
and names the files. Move those edits to the source side, then run it again.

## What `ready` does, in order

1. **Simulation package, server -> client** (`sync_sim.py`).
2. **World file list** (`gen_world_files.py`). This picks up new scripts,
   shaders and assets the server needs. A missing entry used to ship a server
   world whose scripts could not compile, for example the castle interior with
   no collision.
3. **World export, client -> `server/world`** (`export_world.py`).
4. **Import + tests** (`dev.ps1 test`):
   - client headless import, which writes the `.import` / `.uid` files for new assets
     (a parse error in any script fails here)
   - C++ service build
   - world import, `multiplayer_sim.py` (agreement, forged input, protection,
     quests, party) and world boot

   The other suites were retired on 2026-10-17; the screenshot and preview
   tools are listed in `test-tools.md`.
5. **Commit summary**: what changed in each repository.

## Committing

Commit both repositories together when both changed: a client change usually
also changes `server/world/`. A new asset is committed with its `.import` and
`.uid` side files. `workspace.lock.json` lives in the workspace folder, outside
both repositories.

## Outside `ready`

- Art pipelines that need Blender or fal (castle layout, terrain bake, icons)
  keep their own scripts: `art/castle/rebuild.sh`, `art/map/scripts/`. Run
  `ready` after them.
