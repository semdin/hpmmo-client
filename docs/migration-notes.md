# HPMMO Phase 3 migration notes

**Date:** 2026-10-03. Single checkout (`semdin/hpmmo`, HEAD `a5d5d08`) split into `client/` and `server/` repositories under this workspace container. The old checkout is preserved intact at `_legacy/` as the recoverable snapshot.

## What moved where

| From (old repo) | To | Notes |
| --- | --- | --- |
| Godot project, scenes, scripts, assets, launcher_cpp, tools, data, docs, plan.md | `client/` | `plan.md` became `client/docs/plan.md` (canonical roadmap) |
| `server/db_service.py`, `server/schema.sql`, `server/version.json` | `server/services/`, `server/db/migrations/`, `server/services/` | Paths updated in deploy scripts |
| `setup_server.sh`, `update_server.sh` | `server/deploy/` | Rewritten: env-file credentials, staged package swap with rollback |
| `package_server.bat` (packed the whole repo) | `server/deploy/package_server.ps1` | Now packages only server content and FAILS the build if account DBs or client visuals leak in |
| — (new) | `server/world/` | 107-file authoritative world exported from the client project (`WORLD_EXPORT.json` pins per-file sha256 + source revision; regenerate with `dev.ps1 sync-world`) |
| — (new) | `server/contracts/` | Protocol (15 RPCs) + gameplay schemas (spells/items/houses/quests/safe_zones), server-owned, hash-pinned in `workspace.lock.json` |
| — (new) | `server/tests/smoke_service.py` | Boots the service on temp SQLite and pins health/auth/CRUD/save-contract/trade-503 behavior |

## History handling

- Both new histories were **filtered with git-filter-repo**: the client history drops all server-only files, `HPMMO_Launcher.exe`, the tracked SQLite DB, and pyc junk; the server history keeps only server paths (the DB was then removed from it too).
- The hardcoded PostgreSQL credentials that existed in `db_service.py` / deploy scripts were scrubbed from the server history (`--replace-text`) and the service now reads credentials **only from the environment** (`deploy/hpmmo.env.example`). Verified: `git log -p --all` contains **0** occurrences of the old passwords in either repo.
- **Operator actions required (rotation):** the legacy database password still exists wherever the live VPS runs the old checkout. Change the `hpmmo` PostgreSQL role password on the VPS, update `/etc/hpmmo/hpmmo.env` (created by the new `setup_server.sh`), and deploy via the packaged release. Until then the deployed server keeps the old code/paths — this repository no longer contains them.

## Deliberate decisions

1. **Fresh vs exported history:** history was carried and filtered (not squashed) so blame/context survive where they are clean.
2. **World export, not ownership inversion:** the authoritative Godot world is still authored in the client project and exported (hash-pinned) to the server until Phase 5 moves authority server-side. This is a *tracked, generated* copy — regenerating is one command and drift is caught by hashes, not by convention.
3. **Contracts:** server owns `contracts/`; `workspace.lock.json` pins the hashes of both copies; `dev.ps1 verify-contracts` fails on drift. Generated types/validation fixtures are Phase 4/5 work.
4. **LFS:** both repos enable Git LFS for binary assets (`*.glb`, `*.gltf`, textures, audio) with history migrated; a clone needs `git lfs` installed.
5. **Client releases:** no export pipeline exists yet (no export templates); the client "build" is validation-only until Phase 7 ships the launcher updater. The server "build" produces `server/dist/hpmmo-server-<stamp>.tar.gz` today.
6. **Known carry-overs:** `launcher_cpp/src/main.cpp` contains machine-specific Godot paths (Phase 7 fixes); the harness/launcher both accept a `HPMMO_GODOT` / `-GodotPath` override in the meantime.

## Verification (adversarial; failures found and fixed)

An independent verification pass re-ran every claim from fresh clones and **found four real defects — all fixed and re-proven**:

1. **LFS pointer stubs in the working trees.** `git lfs migrate import` left both workspace trees as 132-byte pointer stubs (fresh clones smudged correctly; the source trees did not), and the world export therefore baked stubs into `server/world`. Fixed with `git lfs checkout` in both repos plus a re-export; export hashes are now computed from the exported copies, so a fresh clone re-hashes to **0 drift (107/107 verified)**.
2. **Broken glTF texture URIs** (pre-existing in the props, plus a name mismatch inside the Phase 2 candidate pack) tripped the harness import gate on a cold clone: `props/mage_texture.png` was never in the repo, and the Quaternius base-character GLTFs reference `*_Normal_png.png` filenames the pack itself does not ship. Fixed by adding the real KayKit atlas under `props/` and byte-identical `_png` variants; a cold-clone harness run now passes **on the first try: "93 checks, 0 failures"**.
3. **Over-broad packaging guard**: the "no assets in the package" check banned the world's own `world/assets`, so no server release could ever be produced. The guard now bans root-level client payloads (`assets/`, `docs/`, `launcher_cpp/`, `tools/`), `candidates` dirs, and any `*.db`; the packager also cleans its staging dir on failure and pins Windows' bsdtar (a Git-Bash GNU tar on PATH rejects `C:\` paths).
4. **Stale / one-commit-behind pins** in `workspace.lock.json` (history rewrites move revisions). The lock is refreshed by every `sync-world`; `dev.ps1 status` prints pins next to live HEADs so a trailing pin is visible by design.

Re-verified after the fixes: fresh **client** clone, first-run harness 93/0; fresh **server** clone: `py_compile` + smoke (0 failures) + world import (0 ERROR lines) + boot ("Game World successfully loaded! Server is READY"); server package 3.0 MB with zero forbidden entries and real model bytes inside; contract hashes match the lock in both repos; `git log -p --all` in both repos contains **zero** occurrences of the legacy database passwords (a planted-token sanity check confirmed the scan is live).

**Client release boundary:** no client export pipeline exists yet (no export templates), so "a client-only change produces a client release" is demonstrated at Phase 3 only as *build independence* (siblingless clone + full harness); the launcher-driven client release arrives in Phase 7. The server half of that exit check is satisfied today: `dev.ps1 build` produces `server/dist/hpmmo-server-<stamp>.tar.gz`.
