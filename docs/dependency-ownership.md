# HPMMO dependency ownership table (Phase 3)

Who owns what, how cross-repo dependencies are pinned, and where each item is headed. "Export" = generated from the owning side with per-file sha256; "contract" = hash-pinned in `workspace.lock.json` and checked by `dev.ps1 verify-contracts`.

| Artifact | Owner today | Consumer | Mechanism | Later phase |
| --- | --- | --- | --- | --- |
| Godot project, scenes, scripts, assets, UI, launcher source | client | client | — | — |
| Authoritative world (Godot headless) | client (authored) → server (exported) | server runs it | `world/` export, 107 files, `WORLD_EXPORT.json` + lock | Phase 5 inverts ownership: server-owned sim package |
| Network RPC surface | client code (`network_manager.gd`) → server (contract doc) | both | `contracts/protocol.md` (15 RPCs, generated), hash-pinned | Phase 5: versioned contract package with generated types |
| Gameplay schemas (`data/json/*.json`) | server (contract copies) | client GameData + server GameData | `contracts/schemas/` + lock hashes; client keeps runtime copy | Phase 4/5: schema validation fixtures |
| Safe-zone volumes | same as gameplay schemas | both (client gameplay, server authority later) | identical file both sides, hash-pinned | Phase 5: server-owned rule evaluation |
| Account/character persistence service | server (`services/db_service.py`) | client via HTTP (127.0.0.1 on the host) | not a contract: HTTP API | Phase 4: C++ service, authenticated, PostgreSQL |
| Database schema/migrations | server (`db/migrations/`) | server | — | Phase 4: numbered migrations + schema version checks |
| Deploy scripts + packaging | server (`deploy/`) | server | — | Phase 6: staged deployment controller |
| Server release artifact | server (`dist/*.tar.gz`) | VPS | package_server.ps1 enforces exclusions | Phase 6 signatures/checksums |
| Client distribution (launcher, manifests) | client (`launcher_cpp/`, tools) | players | none yet (no updater) | Phase 7 signed manifests + verified packages |
| Check harness + workspace tooling | client (`tools/`, `tools/workspace/`) | both (root dev.ps1 is generated from client) | — | — |
| Roadmap (`plan.md`) | client (`docs/plan.md`) | both | — | — |
| Credentials | nobody (env files only) | server runtime | `/etc/hpmmo/hpmmo.env`, `deploy/hpmmo.env.example` template | Phase 4: one-time tickets, argon2 |

**Rules:** a repository builds from a fresh checkout without reading its sibling; every cross-boundary dependency is either a hash-pinned contract/export or a documented external interface (HTTP API today). `dev.ps1 status` shows drift at a glance.
