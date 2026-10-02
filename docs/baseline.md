# HPMMO Baseline Record

**Status:** Phase 0 complete (every plan §2 assertion checked against revision `697c335`; runtime-only gaps listed in §6). **Phase 1 implemented and reviewed — see §7.**
**Companion files:** defect list in [`docs/defects.md`](defects.md); captured evidence in [`docs/baseline-captures/`](baseline-captures/).
**Rule for this document:** every statement is either (a) directly observed by running a command on the recorded machine, or (b) code evidence at `path:line` on the recorded revision. Nothing here is copied from plan.md's assumptions without verification.

## 1. Provenance

| Item | Value |
| --- | --- |
| Git revision | `697c3350be2ef4c08e6788c5d5b57a6fae848ad6` ("Refactor and rename project from PotterMetin MMO to HPMMO") |
| Branch | `master` |
| Remote | `https://github.com/semdin/hpmmo.git` |
| Working tree | Clean except untracked files: `plan.md`, `docs/baseline.md`, `docs/baseline-captures/`, `launcher.log`, `hpmmo_server.tar.gz` (last two gitignored). **`plan.md` is untracked and *not* ignored — a `git clean` would destroy the roadmap** |
| Engine | Godot `4.7.2.stable.official.ed1daf0bf` (resolved via WinGet shim `godot.exe`, which is a **GUI-subsystem** binary; the console companion `Godot_v4.7.2-stable_win64_console.exe` exists next to it) |
| Project renderer | Forward Plus (`project.godot:12`); MSAA `msaa_3d=2` = **4x MSAA** (engine enum hint "Disabled,2x,4x,8x") + FXAA (`project.godot:31-32`) |
| Main scene | `res://scenes/main/main_menu.tscn` (`project.godot:11`) |
| Window | 1280x720 default, stretch `canvas_items`/`expand` (`project.godot:24-27`); no [physics] section (engine default 60 Hz); no [input] section — GameData registers 19 actions at runtime (`game_data.gd:285-306`) |
| Autoloads (load order) | `GameData`, `DatabaseManager` (a server-path script, also autoloaded on clients), `NetworkManager`, `AudioManager`, `QuestManager` (`project.godot:16-20`) |
| Client version | `version.json`: `1.1.0`, installed 2026-10-02 |
| Client server config | `client_config.json` (tracked in git; also hardcoded in `main_menu.tscn:217` and `network_manager.gd:112`): `server_ip=213.250.145.75`, `server_port=7777`, `api_port=8081`, `last_username` recorded |
| Tracked artifacts of note | `HPMMO_Launcher.exe` (1.5 MB, current — md5 matches local build output), `client_config.json`, `server/pottermetin_server.db` (28,672 B SQLite, 0 rows), `docs/previews/*.png` |

## 2. Test hardware profile

| Component | Value |
| --- | --- |
| CPU | Intel Core Ultra 7 255H, 16 cores / 16 logical processors |
| GPU | Intel Graphics (integrated), driver `32.0.101.8826`, adapter RAM reported 2,147,479,552 bytes (shared) |
| RAM | ~32 GB (33,197,715,456 bytes) |
| OS | Windows 11 Pro, build `10.0.26300` |
| Runtime paths tested | `godot --headless` (regression), windowed Vulkan 1.4.348 Forward+ @1280x720 (captures), headless `-s` SceneTree probe (transforms) |

This machine is in the same class as the plan's stated low-end target (Intel integrated graphics), so §5 measurements are relevant to the 30 FPS low-preset target.

## 3. Reproduction matrix (Phase 0 task 2)

Legend: **Reproduced** = observed running something on this machine; **Statically confirmed** = code path proven by reading + adversarial verification (runtime confirmation pending); **Feature absent** = the flow cannot be reproduced because it does not exist.

| Journey / flow step | Status | Evidence |
| --- | --- | --- |
| Login / character load | Statically confirmed (code) — needs live session | `main_menu.gd` → HTTP `:8081` login (`db_manager.gd:25-27`); game RPC path `network_manager.gd:351-378,398-417`. Live VPS reachability recorded only from `launcher.log` (…-21:13-23:21). Cannot be exercised headlessly without running client + server + DB service |
| Stat changes (damage / heal / spend / regen / XP / level-up) | Reproduced (headless regression) | 72/72 checks PASS at HEAD incl. HUD stat emission, regen at 120 FPS, EXP rollover, mana payment (`docs/baseline-captures/run1-test-scenario.log`) |
| One of each spell | Statically confirmed; cast behavior in regression limited | Regression covers basic cast damage, one Protego, stupefy/expelliarmus mob status; no per-spell visual capture (spell shapes gap, §6) |
| Mount / dismount / flight | Reproduced statically + probe; single still captured | Mount/dismount booleans PASS in regression; **broom reversed (brush leads) — probe-confirmed** (`docs/defects.md` M25); moving orientation not captured |
| Enemy aggro | Statically confirmed | Proximity aggro `mob_base.gd:141-148`; pack behavior asserted by regression (packs 7, assist, respawn timers) |
| Death / respawn | Reproduced (headless regression) | "Player death animation ends in a clean respawn", "dead-untargetable", "new-anchor respawn" PASS |
| Castle traversal | Reproduced (headless regression) + captures | Traversal rays, wall blocking, 2 scripted routes PASS; `baseline-great-hall.png`, `baseline-library.png` |
| Return to menu | **Feature absent** | No in-world return/quit path exists (`docs/defects.md` M35). The only transition back to main_menu is character-select's Logout |
| Shutdown cleanliness | Reproduced (windowed + verbose) | `run1b-test-scenario-verbose.log`: 72/0, **no** leaked-instance/RID/orphan lines; teardown is the normal engine sequence. The historically reported renderer shutdown warning did **not** reproduce (§6) |

## 4. Verified findings against plan.md Section 2

Every row was audited and then independently re-verified by a second agent instructed to falsify it; the flagged corrections are incorporated below.

| Plan §2 claim | Verdict | Key evidence |
| --- | --- | --- |
| Engine: Godot 4.7.2, scenes/GDScript/C++ launcher | **Confirmed** | `godot --version`; `.godot/editor/project_metadata.cfg:7`; `main.cpp` ✓. Consequence "pin engine" is **not implemented**: no export presets, any `godot.exe` accepted (`play.bat:4`, launcher search paths), server download unverified (`setup_server.sh:32`) |
| Game server: `network_manager.gd` + dedicated Godot server implement networking | **Confirmed** | ENet UDP star, port 7777, 32 max; 15 RPCs (7 gameplay, 8 auth pairs); `scenes/server/dedicated_server.tscn` |
| Python service: accounts, characters, persistence, trade, version, patches | **Confirmed** | 11 route entries; stdlib `http.server`; inventory in `server/db_service.py` (see defects B3) |
| DB inconsistency: PG reported while CRUD uses SQLite | **Confirmed** | `PG_CONN` opened (`:33-46`) never queried; all 7 handlers call `get_sqlite()`; `/api/health` reports `DB_TYPE`; `init_db()` skips DDL when PG connects (`:59`); tracked `pottermetin_server.db` is the live path via `:20-23` fallback |
| Auth/saves: IDs in request bodies; launcher passes password in argv | **Confirmed** | `db_service.py:229-353` (raw IDs); `main.cpp:321-323` (`--pass`); plus: game RPC lets any peer load any character (`network_manager.gd:398-417`); **online saves are currently rejected entirely** — payload keyed `id` vs required `character_id` (`db_manager.gd:37-38` + `db_service.py:301-303`), so nothing persists |
| Trade: recipient gains without sender losing | **Confirmed verbatim** | `db_service.py:373-381`; deterministic on one request; also self-trade and negative-galleon variants; endpoint still enabled (plan says disable) |
| Multiplayer authority central to prototype | **Confirmed** | Per-peer mob simulation (`game_world.gd:269-272`), client-resolved damage (`player.gd:553-567`), server persists client-reported hp/level/pos (`network_manager.gd:220,161-175`). Note: the "multi-client state/spell relaying" commit is `24961d8`, not `ab4ddd9` |
| Castle: procedural hall/wings/towers in outdoor world | **Confirmed** | `castle_builder.gd` builds ~1,100 primitives at world (0,0,-72); static GLB `CastleFront` is freed at startup (`game_world.gd:29-31`) |
| Castle: not a complete multi-floor interior | **Confirmed with nuance** | There **is** a real single-storey walkable interior (30×48 m Great Hall + LIBRARY and CHARMS wings with props and NPCs); zero vertical circulation — "stair" appears only in plan.md; all 5 towers solid colliders (`castle_builder.gd:224-232`); project's own `docs/GAMEPLAY_UPDATE.md:45` admits no upper floors |
| Castle surfaces: color textures + masonry.gdshader are prototypes | **Confirmed, plus** | Shader is albedo+constant-roughness only (26 lines, no PBR channels); all 44 environment "palette textures" are byte-identical 1024² flat swatches (single MD5); the 8 baked 256² texture PNGs are referenced by nothing |
| Characters: stylized proportions | **Confirmed numerically** | One rigged `wizard.glb` for all houses (41 joints, 76 clips @30fps); bind pose crown 2.203 m / hat 2.716 m vs 1.8 m capsule; animation via bare `AnimationPlayer.play()` (no tree, no loop modes, cast truncated at 0.35 s) |
| Spiders/monsters: procedural spider + Quaternius monsters; placeholders | **Confirmed (existence), Unimplemented (marking)** | Acromantula = 39 primitive meshes + sine motion (`spider_rig.gd`); Snatcher/Ghoul/Commander = Quaternius GLTFs at 0.75 scale with the identical 14-clip set; nothing marks them placeholders in code |
| Encounters: `encounter_director` packs + proximity aggro | **Confirmed; plus** | 7 data-defined zones (counts 3,3,5,3,5,1,3 incl. solo boss + boss w/ 2 escorts), random placement, pack-wide assist, leash 26/40 with immune full-heal return, whole-pack respawn 25-35 s (90-120 s boss). **No safe zone exists**; `aggro_mode`/`assist_radius`/`leash_distance` absent (Phase 1 work) |
| Spell art: spheres/rings/cylinders + procedural flashes | **Confirmed** | `skill_fx.gd` (275 lines, 0 texture refs); one shared projectile scene for 5 ranged spells; Protego = emissive sphere; broom = static quad puff |
| Dedicated VFX: `flame_01.png`, `spark_01.png` present, library missing | **Confirmed** | Both 512² stills (8-bit indexed PNG) + Kenney CC0 license; no flipbooks/atlases/animated textures anywhere; Kenney pack (80 named elements) sits in `tools/downloads/particles` (duplicated into `res://assets/vfx`, imported twice) |
| Launcher: native C++ auth+launch; legacy Python has version logic | **Confirmed; plus** | C++ launcher has the reported behavior **and zero update logic**; `HPMMO_Launcher.exe` is current (not stale); it launches the Godot **editor** binary against the project (hardcoded dev path among candidates) — no packaged build exists; legacy launcher version check hits `/version` but server serves `/api/version` (404 → fallback) |
| Deployment: `update_server.sh` stops services, updates live files | **Confirmed; plus** | git pull/tar over live files, schema re-apply with hardcoded credentials, restart; no staging/drain/save/verify/rollback; `package_server.bat` tars the whole repo root (ships the account DB, launcher exes, `.godot` cache, `client_config.json`, nested old archive) |
| Repository: one repo (`semdin/hpmmo`), client+server together | **Confirmed; plus** | Single repo, no CI/lockfile/LFS config; `.git` = 376 MB (442 MiB unreachable blobs incl. two >150 MiB); hardcoded DB credentials in tracked history require rotation during Phase 3 |

Regression scope (plan §2 closing paragraph): see `docs/defects.md` §4 — inventory restore, HUD stats, and cleanup are fixed/working at HEAD; collinear look directions are mitigated via `combat_rules.safe_up`; the shutdown renderer warning did not reproduce; the backward **rider** is fixed but the **broom** is reversed.

## 5. Runtime measurements and captures

### 5.1 Regression harness (`tools/run_game_checks.ps1`)
- **As-documented invocation fails on this machine** (defect M56): PATH `godot.exe` is GUI-subsystem, PowerShell doesn't wait, `$LASTEXITCODE` is empty → "Godot import failed." at `run_game_checks.ps1:12`; the import log is written as 0 bytes and the regression never runs. Verified directly (`godot --version` leaves `$LASTEXITCODE` empty; PE subsystem = 2).
- **With the console companion binary** (`-GodotPath …_console.exe`): **`REGRESSION RESULT: 72 checks, 0 failures`**, exit 0, 0 ERROR / 0 SCRIPT ERROR / 0 WARNING / 0 leaked-instance lines. Reproduced in three independent logs at HEAD: `tools/downloads/check-regression.log` (UTF-16) and `docs/baseline-captures/run1-test-scenario.log`, `run1b-test-scenario-verbose.log`.
- Coverage (72 checks): character restore + inventory sanitization + HUD binding; regen at 120 FPS; damage/EXP/mana HUD updates; cooldown double-payment rejection; aimed projectile hit + duplicate-collision single damage + friendly-fire/NPC immunity + vertical up-vector; 7 encounter packs (composition, 23 anchors, pack aggro, stun/disarm, wipe respawn timer, dead-untargetable, re-anchor, commander enrage, telegraph cancel); castle traversal rays + wall block + 2 scripted routes; chat-typing focus; loot currency refresh; mount/dismount + flight particle structure; monolith wave thresholds; death/respawn; scene re-entry.
- **Not covered** (from the same audit): zero-length look directions, VFX node cleanup assertions, menu/character-select/launcher flows, network relay, loot expiry, particle restart, renderer allocations beyond the outer log regex, and any networking/persistence (NetworkManager stubbed, `persistence_enabled=false`).

### 5.2 Shutdown behavior (windowed, Vulkan Forward+, Intel iGPU)
- Run 1 (`--quit-after 900`, windowed): exit 0, 72/72, stderr empty, **no shutdown warnings**.
- Run 1b (`--verbose`): full teardown is the normal engine sequence (no `ObjectDB instances leaked`, no `Resources still in use`, no orphan nodes/RIDs). Only renderer-adjacent warnings: Vulkan loader registry note (benign) and `Image format RGB8 not supported by hardware, converting to RGBA8` ×3 (texture import path).
- **The "renderer allocations at shutdown" item from earlier feedback did not reproduce on this build/hardware/scene** (see §6 for residual scope).

### 5.3 Baseline captures (`docs/baseline-captures/`, 6 full frames + 3 crops, from `capture_world.tscn` at HEAD)
| File | Content observed (multimodal reading) |
| --- | --- |
| `baseline-castle-exterior.png` | Blocky grey-brick castle, 4 blue conical towers, flat saturated lawn, uniform cone/sphere trees, magenta "magic" trees and monolith beams, white sun disc, slight haze only, tiling low-detail brick |
| `baseline-great-hall.png` | Long grey-brick hall, dark beam ceiling, repeating white arcade "tubes", red carpet, plank tables + glowing candle discs, floating candles, 4 house banners; dim cool interior, no fog |
| `baseline-library.png` | Dim room, checkerboard "books" (flat colored rectangles), center table, **short chibi wizard** with tiny wand sparkle, "LIBRARY" sign |
| `baseline-gameplay-hud.png` | Third-person **short chibi wizard**, purple hat + red robe; full HUD (name/house/galleons, zone "Hogwarts Grounds", minimap, quest tracker, controls, chat, HP 500/500, mana 300/300, 6-slot action bar, EXP bar); nameplates over NPCs; hat overlaps the nameplate |
| `baseline-enemy-assets.png` | 4 mobs in lineup: red horned imp; **spider = glossy ball + bead-jointed cylinder legs, no chitin/hair/mouthparts** ("sticks and spheres"); hooded assassin; green ogre boss; all chibi/toy proportions |
| `baseline-broom-flight.png` (+ `crop-broom-rider.png`) | Airborne rider at ~4-5 m; upright torso with legs hanging (not a riding pose); broom shaft crosses at hip height ending in a dark bristle cluster; **single still cannot prove axis alignment** — motion capture still needed (§6) |
| `crop-spider.png`, `crop-enemy-lineup.png` | Zoom crops of the above |
| `run1/run1b/run2-*.log` | Raw logs for every run above (note: `*.log` is gitignored — use `git add -f` to commit them) |

Capture-harness perf readings (context only, not a gate): fps 39-60; draw calls 363 (library) → 2,189 (castle exterior) → 3,232 (enemy lineup) — `run2-capture-world.log`.

### 5.4 Direct probes performed during baseline write-up
- Trade handler, save-key mismatch, `0.0.0.0` bind, unsalted SHA-256, and `can_damage`'s lack of zone logic: read end-to-end by the author (evidence in `docs/defects.md`).
- Broom orientation: headless Godot probe instantiating `player.tscn` — BroomMesh `basis.y = (0, 0.05, -0.999)`; Bristles at Visuals-space `(0, 0.575, +0.949)`; `BroomParticles` at `(0, 0.56, +1.249)` ⇒ brush and exhaust lead the +Z-facing rider (**broom reversed confirmed**).

## 6. Gaps — reported issues not yet reproduced, with reasons

Per Phase 0 exit check ("every reported issue has a reproducible case or a documented reason it cannot yet be reproduced"):

1. **Interactive login → character select → world → relog journey**: needs a live client session against a running DB service/dedicated server; not driven headlessly. Code paths verified statically; launcher.log proves the VPS endpoints were reachable on 2026-10-02 (21:13-23:21) only.
2. **Two-client behaviors** (mob desync, visual-only spells, chat one-way, host silence, remote animation/rider states): require two running clients + server on this machine; all are code-proven in `docs/defects.md` B1/B2, M2-M4, M29.
3. **Renderers at shutdown in packaged/launcher runs and across repeated world↔menu transitions**: the reported warning did not reproduce in the test scene; the population where it could still appear (packaged build, long sessions, repeated transitions) is unexercised.
4. **Spell shape captures** (Phase 0 task 3 deliverable "current spell shapes"): `capture_world.tscn` never casts a spell; only static effects (wand sparkle, monolith beams) appear. Needs a dedicated capture scene or manual session.
5. **Broom/rider motion capture** (front/side/rear while moving): single stills exist; motion proof pending. Orientation is code/probe-proven regardless.
6. **Phase 0 task-8 metrics** (frame-time percentiles, visible triangles, particle overdraw, RAM/VRAM, server tick time, network traffic): no instrumentation exists in the project; only fps + draw calls are emitted by the capture harness.
7. **Live VPS state**: which backend `/api/health` reports, whether the deployed revision matches 697c335, whether a `server/patches/latest.zip` artifact exists, and whether the deployed SQLite file has rows — all require contacting the production host (deliberately not done from this baseline task).
8. **Audio/visual quality judgments** (alpha quality of the 2 stills against dark/light, loudness/clipping, overdraw): require speakers/eyes on a running build; all silence/primitive findings are static call-graph evidence consistent with the zero-audio-file state.

## 7. Phase 1 status (implemented 2026-10-03, reviewed)

**Change set:** 16 files changed + 2 new (`scripts/world/safe_zone.gd`, `data/json/safe_zones.json`). Summary:

- **Protected volumes** — authored in `data/json/safe_zones.json` (courtyard r21 @ origin; castle approach r12 @ (0,-28); village square r9 @ (35,20); 8 m spawn buffer; y band −10..200), loaded via `GameData.SAFE_ZONES` with a code fallback. `combat_rules.can_damage` now rejects any attack where caster or target is protected, except training dummies. A 5-lens adversarial review traced every damage path (projectiles, AoE, cone, melee, ranged, slam, burn DoT, knockback, summons, remote casts) and found **no live bypass**.
- **Reactive encounters** — `aggro_mode`/`assist_radius`/`leash_distance` on mobs, set per pack by `encounter_director` (bosses 20/40); proximity scanning only for explicit `"aggressive"` data; assist radius-limited; spawn anchors **and full ring formations** validated against zones+buffer; displaced mobs cancel and return home; burn ticks skip protected volumes.
- **Broom orientation** — `BroomMesh` rotated 180° at the wrapper (one transform): bristles and exhaust now sit behind the +Z-facing rider. Verified three ways: headless probe, regression assertions (local z < −0.4/−0.5), and captures `phase1-mount-rear/front/side.png`.
- **Mounting** — 0.3 s toggle debounce, capsule-clearance dismount query (normal-offset), mounted offensive casts blocked with throttled feedback and held-input drop.
- **Cleanup fixes** — monolith respawn via child `Timer` (M49) + albedo-restoring tween; `peer_account_map`/`peer_char_data_map` cleared on disconnect and in `disconnect_game`; zero-length guards on all three SkillFX direction consumers; unreferenced `bombarda_blast.gd` gated; potion heal/mana feedback.
- **Harness** — console-binary auto-resolution, `Start-Process` argument quoting, stricter result regex; native stderr can no longer abort the script.

**Verification:** `REGRESSION RESULT: 93 checks, 0 failures` — headless ×2 and windowed ×3 (Vulkan Forward+, exit 0, no ERROR/leak/RID/orphan lines). Review workflow: 5 reviewer lenses + independent falsification of all 20 findings + runtime agent; the one major finding (held-LMB floating-text spam while mounted) and both minors (harness arg quoting, missing monolith-respawn coverage) are fixed and regression-covered. Details in `docs/defects.md` §0.

**Phase 1 exit checks (plan.md):** walking beside ordinary mobs does not start combat ✅; a hit activates only the intended pack ✅; enemies cannot attack or follow into the courtyard ✅ (three tests: attack gate, give-up, displaced-return); dummies remain usable ✅; rider/broom face travel in front/side/rear ✅ (probe + checks + captures; the rider *pose* stays the chair-sit fallback until Phase 9); HUD updates on damage/healing/spending/regen/XP/level-up ✅.

**Residuals carried forward:** clip loop-mode visual confirmation (M23), dismount clearance samples the pre-dismount spot only, protected space is caller-side (server authority arrives in Phase 5), HUD does not yet grey out spells while mounted (Phase 13).
