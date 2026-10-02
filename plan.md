# HPMMO Development and Art Rebuild Plan

**Prepared:** 2026-10-03  
**Status:** Proposed implementation roadmap. Creating this document does not implement these phases, split repositories, deploy services, purchase assets, or reset databases.  
**Baseline:** The current Godot project and the player's latest feedback. Existing procedural art and previous automated checks are prototype foundations, not evidence that the requested visual quality has been reached.

## 1. Intended result

Build a coherent, playable wizard MMORPG slice with a protected social courtyard, reactive enemy packs, readable combat, taller characters, convincing broom flight, and a detailed Hogwarts castle interior that loads as a separate shared map. Replace obvious primitive-based effects and inconsistent character/monster art with properly authored or sourced assets. Establish reliable PostgreSQL persistence, separate client/server repositories, controlled server maintenance, and a working native launcher updater.

The first complete slice must support this journey:

1. Open the launcher, check compatibility, install a verified update if needed, log in, and select a character.
2. Enter a safe courtyard with NPCs and training dummies. Nearby enemies neither initiate combat nor enter the protected area.
3. Leave the safe area, encounter a randomly placed pack of three or five mobs, and deliberately attack it to begin combat.
4. Cast responsive spells with synchronized animation, layered VFX, sound, damage, mana costs, cooldowns, and live HUD feedback.
5. Kill enemies, see proper death animations, receive rewards once, and observe the server-controlled respawn lifecycle.
6. Fight both a solo boss and a boss with two escorts, with readable attack warnings and recovery opportunities.
7. Mount a correctly oriented broom, fly, bank, brake, land, and dismount with appropriate body animation and a textured magical trail.
8. Approach the castle entrance, transition into a separately loaded interior, and explore several connected floors, rooms, and a working magical staircase.
9. Relog or change maps without losing or duplicating character state.
10. Receive a maintenance countdown, be safely disconnected before server replacement begins, and reconnect after a healthy compatible release is available.

## 2. What the current code actually contains

These findings are from the repository, not assumptions about a typical MMO.

| Area | Current evidence | Consequence for the plan |
| --- | --- | --- |
| Engine | Reported runtime is Godot 4.7.2; the project uses Godot scenes, GDScript, and a native C++ launcher. | Pin the tested engine/export templates and native dependencies; do not upgrade them incidentally during an art pass. |
| Game server | `scripts/autoload/network_manager.gd` and the dedicated Godot server implement game networking. | Python is not the main game simulation server. |
| Python service | `server/db_service.py` handles accounts, characters, persistence, trade, version information, and patch downloads. | Separate public account/release endpoints from private persistence operations. |
| Database inconsistency | PostgreSQL connection setup exists, but account/character/trade handlers call `get_sqlite()`. Health reporting uses `DB_TYPE`. | PostgreSQL can be reported while actual CRUD still uses SQLite. Replace this mixed path with a verified PostgreSQL implementation. |
| Authentication and saves | The service accepts account/character IDs in request bodies; character load/save lookups use the supplied character ID. The native launcher passes a password in the game process arguments. | Add authenticated sessions, ownership validation, private save APIs, and a one-time game login ticket. |
| Trade | The current trade handler appends offered items to recipients without removing the corresponding offered items from senders. | Disable this path until inventory transfer, validation, locking, and retry behavior are correct. A database transaction alone does not make the game rules correct. |
| Multiplayer authority | Local world/encounter logic and client-reported state remain central to the prototype. | Shared authoritative mobs, rewards, combat, map ownership, and persistence are prerequisites for an MMO-quality result. |
| Castle | `scripts/world/castle_builder.gd` constructs a procedural hall, wings, and decorative towers in the outdoor world. | It is not a complete multi-floor interior. Replace its role with authored exterior and interior maps. |
| Castle surfaces | Existing color textures and `assets/textures/masonry.gdshader` provide a prototype appearance. | Audit resolution, tiling, and material channels; add coherent PBR material sets and architectural detail. |
| Characters | Existing wizard models have stylized proportions. | Retarget onto a taller, coherent humanoid rig; do not simply stretch the mesh vertically. |
| Spiders and monsters | Procedural spider geometry and imported Quaternius monsters exist. | Their current appearance does not meet the player's requested art direction. Use them only as explicitly marked placeholders. |
| Encounters | `scripts/world/encounter_director.gd` contains pack spawning; `mob_base.gd` includes proximity aggro. | Retain useful lifecycle concepts, replace unwanted automatic aggression, and implement real protected zones. |
| Spell art | `skill_fx.gd` uses many spheres, rings, cylinders, and procedural flashes. | Redesign spell appearance around textures, coherent flipbooks, ribbons, distortion, and authored timing. |
| Dedicated VFX images | `assets/vfx/flame_01.png` and `spark_01.png` are present. | They are a small reusable starting point, not a complete spell library. The requested flame/energy flipbooks are missing from this dedicated VFX inventory. |
| Launcher | `launcher_cpp/src/main.cpp` implements HTTP authentication and game launch; legacy Python launcher code contains version-related logic. | Audit the executable actually distributed. Do not mistake a version request or old launcher feature for a working native patch installer. |
| Deployment | `update_server.sh` stops services and updates live files using Git/archive extraction. | Replace it with build-first, drain, save, disconnect, staged deployment, readiness checks, and rollback. |
| Repository | The configured remote is `semdin/hpmmo`; client and server are currently together. | Plan a controlled migration into two independently buildable repositories managed from the same local workspace. |

The initial error report remains part of regression scope: typed inventory restoration, collinear `look_at` directions, HUD stat changes, scene/VFX cleanup, and renderer allocations at shutdown. Some defensive changes already exist, including a safe-up helper. Reproduce against the actual distributed build before calling an issue fixed; do not assume every renderer shutdown warning has the same cause.

## 3. Core design decisions

### 3.1 Castle exterior and interior

**Use separate outdoor and castle-interior maps.** This is a practical choice for a large detailed castle, particularly on integrated graphics. An open entrance into one enormous scene is possible, but it is not required for a convincing experience.

- `grounds`: courtyard, castle exterior shell, paths, vegetation, combat areas, and outdoor broom flight.
- `castle_interior`: entrance hall, Great Hall, grand staircase, classrooms, library, upper galleries, and selected towers.
- `dungeon`: a later separate encounter map when the first two maps are stable.
- Divide the interior into room/wing chunks for visibility and resource management. Separate maps and internal chunking solve different problems.
- Use a vestibule, doorway interaction, short fade, and loading indicator to hide the transition naturally.
- Keep the interior shared between players by default. A separate map does **not** automatically mean a private instance or a separate operating-system process.
- Start with multiple logical zones in the same authoritative server process. Distribute zones across processes only when profiling and player capacity require it.
- Persist `map_id`, `instance_id` where applicable, and a valid spawn/location reference. Outdoor coordinates must never be reused blindly inside the castle.

Godot supports threaded resource requests; poll completion before retrieving a large resource to avoid turning the loading screen into another blocking load. Scene instantiation and GPU upload still need profiling. [Godot background loading](https://docs.godotengine.org/en/stable/tutorials/io/background_loading.html)

### 3.2 Python, C++, and PostgreSQL

The original author's rationale is not recorded in the inspected files. Python and SQLite are common prototype choices because they reduce setup, but that is an inference, not an established history of this project. SQLite is not inherently unusable; the concrete problem here is an inconsistent implementation and the absence of the required multiplayer persistence guarantees.

**Recommended target:** PostgreSQL for online persistence, a C++ account/persistence service, and an authoritative Godot headless world server initially. Keep the native C++ launcher. Use C++ GDExtension for measured world-simulation hot paths when useful.

| Option | Benefits | Cost / risk | Decision |
| --- | --- | --- | --- |
| Python service + PostgreSQL | Shortest route to correct persistence; Python can be adequate for account APIs. | Keeps an additional runtime and still requires a service rewrite of the current handlers. | Valid fallback if delivery speed becomes the priority. |
| C++ service + PostgreSQL + Godot world server | Matches the requested C++ direction while retaining engine physics/navigation/network integration. | Native builds, dependency management, memory safety, and async service design need care. | Planned target for this roadmap. |
| Fully standalone C++ world server | Maximum control of simulation and protocol. | Requires an explicit wire protocol, world-data pipeline, collision/navigation solution, replication, and client integration. | Separate decision gate after the authoritative slice; not a drop-in replacement. |

Database choice is independent of language. C++ can use PostgreSQL through `libpq` or its C++ binding `libpqxx`. Choose and pin a maintained library version after a small build/transaction spike. [PostgreSQL libpq](https://www.postgresql.org/docs/current/libpq.html), [libpqxx](https://pqxx.org/libpqxx/)

Godot supports dedicated headless exports and native C++ extensions. Its SceneMultiplayer wire format is an engine implementation detail intended for Godot peers; an arbitrary ENet C++ program is not automatically compatible with existing RPCs. [Dedicated server exports](https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_dedicated_servers.html), [GDExtension C++](https://docs.godotengine.org/en/stable/tutorials/scripting/cpp/gdextension_cpp_example.html), [SceneMultiplayer protocol note](https://docs.godotengine.org/en/stable/classes/class_scenemultiplayer.html)

### 3.3 Gameplay policy

- Ordinary mobs are **reactive by default**: proximity alone does not trigger an attack.
- A valid player hit outside protected space activates the attacked pack. Assistance is limited to that pack, preventing accidental chains across an entire region.
- Aggressive enemy types may be added later as explicit encounter data with clear presentation. They are not the default.
- The NPC/training courtyard is protected in simulation, navigation, spawn rules, targeting, and damage resolution.
- Training dummies are a separate target category: spells may practice against them in the courtyard without enabling enemy damage or ordinary PvP.
- Boss compositions include one boss alone and one boss with two escorts. Standard pack sizes are three and five members; the number of packs in a region is a separate setting.
- Ground combat is the first balanced combat mode. Disable offensive casting while mounted for this slice; reserve airborne combat for a later designed feature.
- Development character resets are acceptable during the database transition. Resets must be deliberate development operations, not silent deployment defaults.

## 4. Phase sequence and dependencies

All phases below begin as **planned**. A phase is complete only when its deliverables and exit checks are demonstrated. Estimates should be made after Phase 0 against available people and tools; this is a substantial game rebuild, not a single cosmetic patch.

| Phase | Work package | Depends on | Completion evidence |
| --- | --- | --- | --- |
| 0 | Baseline, reproduction, and quality targets | None | Reproduction matrix and captured baseline |
| 1 | Immediate gameplay containment and regression fixes | 0 | Safe courtyard, reactive mobs, correct broom orientation |
| 2 | Art direction, scale, and asset production pipeline | 0 | Asset manifest, reference scene, scale/rig standards |
| 3 | Two repositories and shared contracts | 0 | Independent clean builds from one local workspace |
| 4 | C++ service and PostgreSQL persistence | 3 | Authenticated end-to-end persistence tests |
| 5 | Authoritative gameplay, combat, and zone state | 1, 3, 4 | Consistent multi-client world and validated gameplay |
| 6 | Server release and maintenance automation | 3, 4, 5 | Successful update and failure/rollback rehearsal |
| 7 | Native launcher update pipeline | 3, 4, 6 release contract | Verified update, recovery, and compatibility checks |
| 8 | Separate castle map and multi-floor greybox | 2, 5 | Complete traversable greybox and reliable transitions |
| 9 | Character redesign and complete broom animation | 2, 5, 8 scale validation | Accepted character and flight test scene |
| 10 | Castle/environment art, PBR surfaces, and lighting | 2, 8, 9 proportions | Finished exterior/interior route and performance capture |
| 11 | Monster assets, pack AI, and bosses | 2, 5, 9 rig conventions | Accepted spider and synchronized encounters |
| 12 | Spell VFX, sound, and final combat presentation | 2, 5, 9, 11 | Every spell has assets, timing, sound, and proof captures |
| 13 | HUD, interaction, onboarding, and accessibility | 5, 7, 8, 12 | Correct live UI through all gameplay transitions |
| 14 | Integrated performance, reliability, and multiplayer QA | 6-13 | Measured acceptance report and resolved blockers |
| 15 | Release the slice and expand castle content | 14 | Reproducible release and prioritized expansion backlog |

Asset research can begin during infrastructure work after Phase 2. Keep final room dressing behind scale validation and final effects behind combat timing. Functional HUD fixes are addressed in Phases 1 and 5; Phase 13 is the integrated presentation pass, not a reason to leave stats broken until the end.

## Phase 0 - Establish a trustworthy baseline

**Purpose:** Separate reproduced defects, already changed code, incomplete systems, and rejected art.

Tasks:

- Record the exact source revision, running executable, Godot version, renderer, resolution, hardware, launcher path, server build, and database mode.
- Reproduce login/character load, stat changes, one of each spell, mount/dismount, enemy aggro, death, respawn, castle traversal, return to menu, and shutdown.
- Record video or screenshots of the backward broom, spider motion, castle surfaces, fog/lighting, and current spell shapes.
- Trace the inventory error across JSON decoding, typed `Array[Dictionary]` conversion, player initialization, and HUD binding order. Test empty, populated, and malformed inventory entries.
- Trace collinear look directions and zero-length directions in all effect helpers, not only the reported arc slash.
- Run the existing `tools/run_game_checks.ps1` and inspect its current coverage. Keep regression coverage that tests meaningful behavior.
- Use verbose shutdown logs and repeated scene transitions to distinguish orphan nodes, resources held by effects, and engine-specific renderer issues. Produce a minimal reproduction if an engine problem remains.
- Measure frame time, draw calls, visible triangles, particle overdraw, RAM/VRAM, server tick time, and network traffic for the same repeatable route.

**Deliverables:** `docs/baseline.md`, a defect list with reproduction steps, baseline screenshots/video, and a test hardware profile. Suggested file names in this plan are future outputs unless already present.

**Exit checks:** Every reported issue has a reproducible case or a documented reason it cannot yet be reproduced. A clean startup is not treated as proof that combat, art, or shutdown is correct.

## Phase 1 - Fix immediate gameplay failures

**Purpose:** Make the prototype safe to play while larger systems are rebuilt.

Tasks:

1. Add a data-defined courtyard protection volume covering NPCs, training dummies, spawn points, and approach paths. Account for height and boundary tolerances; do not use only a distance from world origin.
2. Exclude this volume and a buffer from enemy spawn sampling and enemy navigation. If an enemy is displaced inside, cancel its attacks and return it to a valid home point.
3. Enforce protection at attack initiation, projectile impact, AoE, damage-over-time ticks, knockback, and reward attribution. Attacks fired across the boundary must not bypass the rule.
4. Block attacks from protected players against outdoor mobs. This prevents invulnerable courtyard sniping. Keep an explicit training-dummy exception with no XP/loot farming.
5. Change ordinary mobs to reactive aggro; use `aggro_mode`, `pack_id`, `assist_radius`, and `leash_distance` rather than a universal proximity trigger.
6. Inspect imported model forward direction, player visual root, camera aim, broom root, and seat marker. Normalize axes once at the model wrapper; fix the reversed rider without scattering 180-degree offsets.
7. Add a mount state guard so repeated input cannot duplicate brooms, lose the rider, or dismount into geometry. Reject dismount when no valid landing position exists.
8. Repair typed inventory restoration, health/mana/XP notifications, cast cancellation, zero-length look directions, and scene cleanup wherever the baseline reproduces failures.
9. Disable the faulty trade endpoint until Phase 4 replaces its behavior.

**Deliverables:** Protected-zone data, reactive encounter configuration, orientation test scene, and targeted regression coverage. Prototype checks must later be rerun against authoritative logic in Phase 5.

**Exit checks:** Walking beside ordinary mobs does not start combat. Hitting one activates only the intended pack. Enemies cannot attack or follow into the courtyard. Dummies remain usable. Rider and broom face the travel direction in front/side/rear views. HUD stats update on damage, healing, spending, regeneration, XP gain, and level-up.

## Phase 2 - Set art direction and build the asset pipeline

**Purpose:** Stop adding individually acceptable assets that look wrong together.

Target direction: grounded magical fantasy, believable stone/wood/cloth/chitin, taller human silhouettes, warm readable interiors, clear outdoor daylight, and expressive magic. Avoid mixing chibi heroes, toy-like monsters, realistic stone, and oversized opaque spell geometry.

Tasks:

- Produce a small art reference board and an in-engine material/character test room under neutral and final lighting.
- Establish one unit as one meter. Start with approximately 1.75-1.90 m adult-height characters and roughly 7-7.5 head proportions; validate appearance and gameplay before locking the rig.
- Define shared forward/up conventions, applied transforms, rig names, sockets, root-motion policy, UV conventions, texture naming, and animation event metadata.
- Establish modular architecture dimensions around the approved character: doors, stair rise/run, corridor width, handrails, camera clearance, and broom clearance outdoors.
- Use authored or properly licensed models with coherent topology, UVs, materials, LODs, collision, and animations. A generated concept image is not a usable rigged 3D asset.
- Keep editable source files, exported GLB/GLTF, textures, animation clips, Godot scenes/materials, import settings, and provenance together through an asset manifest.
- Define artifact storage and Git LFS rules for large binaries. Keep Blender/source art and server collision packages out of unnecessary release downloads.

Every manifest entry must record: asset ID, purpose, status, author/source URL, license/receipt, attribution requirements, local paths, source hash, scale, polygon count, material slots, texture channels/resolution, rig, animations, collision, LODs, and visual acceptance evidence. Use `missing`, `candidate`, `placeholder`, `integrated`, and `accepted` as distinct states.

### Starting asset budget proposals

These are planning limits to test, not measured capacity claims.

| Asset | Initial budget / format | Validation |
| --- | --- | --- |
| Player hero | About 25k-45k triangles at LOD0; 2k textures; limited material slots | Compare close-up quality and crowded-scene cost; generate lower LODs |
| Ordinary monster | About 8k-20k triangles; 1k-2k textures | Test five-member packs and several nearby packs |
| Boss | About 25k-50k triangles; 2k textures; larger silhouette | Budget alongside escorts and simultaneous VFX |
| Architecture | Modular meshes, shared trim sheets, tiling PBR, occlusion-friendly rooms | Measure actual visible surfaces and material changes |
| Particles | Mostly 256-512 px source elements; 1k-2k atlases | Profile transparent screen coverage, not just particle count |
| Audio masters | WAV masters; engine-appropriate compressed playback for long ambience | Check looping, spatialization, loudness, and voice count |

### Asset sourcing strategy

| Need | Source / creation route | Required checks |
| --- | --- | --- |
| Stone, slate, wood, ground PBR | Poly Haven or ambientCG candidates; author matching trims/decals | Correct scale, channel packing, normal orientation, visible tiling, exact license |
| Simple particle elements | Existing Kenney pack plus authored masks/noise | These are ingredients; they do not replace complete animated spell effects |
| Humanoid animation | Licensed animations, custom keyframing, or Mixamo where rig-compatible | Retargeting, hand/wand contact, root motion, foot sliding, redistribution terms |
| Spiders and bosses | Original Blender assets or selected licensed rigged creature models | A humanoid auto-rigger does not solve an eight-legged spider rig |
| Castle modules | Original modular kit; selected compatible architectural assets | Door/stair scale, collision, UVs, LODs, material consistency |
| Sound | Original recording/synthesis or per-file licensed sound libraries | Exact per-file license, clean loops, no clipping, matching ambience |
| Concept art / texture ideas | Image generation where useful, then production processing | Seamlessness, true alpha, coherent animation, PBR validity; never label a concept as a finished model |

Poly Haven and ambientCG provide CC0 asset licensing; record the individual selected asset pages when downloading. Kenney's Particle Pack is CC0. Mixamo has specific usage and character limitations. Freesound licenses vary per file. These are source candidates, not a claim that new production assets have already been selected or downloaded. [Poly Haven license](https://polyhaven.com/license), [ambientCG license](https://docs.ambientcg.com/license/), [Kenney Particle Pack](https://kenney.nl/assets/particle-pack), [Mixamo FAQ](https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html), [Freesound licensing FAQ](https://freesound.org/help/faq/)

**Deliverables:** `docs/art-direction.md`, `assets/manifest.json`, an asset review scene, and an initial missing-asset list. Record purchases as candidates until a budget is provided; use suitable free/original work in the meantime.

**Exit checks:** Representative hero, spider, stone-wall, and fire candidates are reviewed together at actual gameplay camera distance to establish the production standard. These may be candidate previews or clearly labeled look-development samples; final assets are delivered in later phases. A screenshot alone does not approve rigging or animation.

## Phase 3 - Separate client and server repositories

**Purpose:** Independent release cycles while retaining one convenient local development folder.

Proposed target workspace:

```text
game/                              local workspace container
  hpmmo.code-workspace              generated workspace configuration
  dev.ps1                          root convenience entry point
  workspace.lock.json              pinned compatible revisions/packages
  client/                          Git repository: hpmmo-client
    project.godot
    scenes/ scripts/ assets/
    launcher_cpp/
    tools/workspace/                source of workspace bootstrap tools
    docs/plan.md                    canonical roadmap after migration
    .github/workflows/
  server/                          Git repository: hpmmo-server
    world/                         Godot authoritative server project
    services/                      C++ account/persistence service
    db/migrations/ db/seeds/
    contracts/                     protocol and gameplay schemas
    deploy/ tests/
    .github/workflows/
```

Tasks:

- Inventory shared scripts, autoloads, resource paths, schemas, maps, and export dependencies before moving anything.
- Preserve the current repository and local changes in a recoverable local snapshot. Perform history filtering/export in temporary copies; validate the two new histories and working trees before replacing the workspace layout.
- Do not simply create two nested repositories while the old parent continues tracking their files. Archive the old checkout after validation and make `game/` a workspace container.
- Scan the new histories for embedded credentials, databases, logs, and generated artifacts. Remove credentials from publishable history and rotate affected secrets during implementation.
- Keep client visuals, audio, UI, and launcher in the client repository. Keep persistence, migrations, deployment, authority rules, and world simulation in the server repository.
- Put network/gameplay contract schemas under server ownership. Publish versioned contract packages with generated types and validation fixtures consumed by the client at pinned versions.
- Export collision/navigation/zone manifests from the map-authoring pipeline as versioned content artifacts consumed by the server. Pin their hashes with corresponding client content releases.
- If shared Godot simulation code is still needed, publish a versioned package owned by the server repository. Do not maintain untracked manual copies of RPC declarations or combat math.
- Provide root commands such as `dev.ps1 start`, `test`, `status`, and `build` that operate on both child repositories. The tracked bootstrap source lives in the client repo; generated root files require no third GitHub repository.
- Build each repository from a fresh checkout without reading undeclared files from its sibling directory.

**Deliverables:** Two repository layouts, migration notes, a dependency ownership table, shared contract packaging, and local workspace tooling. Creating/pushing actual remotes is future implementation work, not part of this document task.

**Exit checks:** A client-only change produces a client release; a server-only change produces a server release. Both build independently. Compatible revisions can be reproduced from the workspace lock. Server packages contain no unnecessary visual assets or account database files.

## Phase 4 - Implement C++ services and real PostgreSQL persistence

**Purpose:** Make the database behavior match its configuration and support authoritative multiplayer state.

Tasks:

1. Build a minimal C++ service spike with request routing, structured JSON validation, asynchronous work, PostgreSQL transactions, configuration, logging, and integration tests. Select the HTTP library based on build/support requirements; avoid writing HTTP/TLS primitives from scratch.
2. Separate public account/session APIs from private character save, trade, and administrative APIs. Restrict private endpoints to authenticated server services; keep PostgreSQL off the public client network.
3. Replace raw account/character IDs as authorization with authenticated sessions and server-side ownership checks. Add expiry, logout/revocation, and duplicate-login policy.
4. Replace unsalted SHA-256 password storage with a maintained password-hashing library using Argon2id and per-password salts. Development accounts may be recreated rather than retaining the insecure format.
5. Replace launcher password command-line arguments with a short-lived, single-use game ticket delivered through a controlled local handoff. Do not log tickets or passwords.
6. Make PostgreSQL the online source of truth. Fail readiness when it is unavailable; never silently switch a live online service to SQLite or local JSON.
7. Add numbered migrations and schema-version checks. Store accounts, characters, inventory ownership, progression, quests, sessions, zone/location, and transactional reward/trade records with constraints and indexes.
8. Use normalized ownership records for mutable item instances/currency. Keep JSONB for appropriate flexible metadata, with schema validation. Apply atomic operations and a consistent lock order for trades.
9. Validate offered quantities, sender ownership, destination capacity, currency bounds, and item eligibility. Remove transferred items from the sender in the same transaction that grants them to the recipient.
10. Make reward grants and retried saves/trades idempotent using operation IDs and uniqueness constraints. Distinguish an uncertain commit result from a confirmed rollback.
11. Persist HP, mana, XP, level, inventory, equipment, currency, quests, map, and safe location consistently. Use revisions to reject stale writes from an old session or zone.
12. Add real liveness/readiness checks: the readiness probe must verify the configured database and required migration level, not merely return a selected backend name.

**Development reset policy:** Provide a named development reset command that verifies environment/database identity, records the reset and schema epoch, recreates migrations/seeds, and invalidates stale sessions. Existing development characters can be discarded. Normal server updates must not run the reset command. No SQLite-to-PostgreSQL data migration is required for disposable test characters unless later requested.

**Deliverables:** C++ service, PostgreSQL migrations/seeds, environment templates without secrets, API contracts, service health checks, and database integration tests.

**Exit checks:** Register, log in, create a character, gain/spend resources, save, restart services, and load the same state from PostgreSQL. A second account cannot load/save another account's character. Repeating a reward/trade request cannot duplicate items. A PostgreSQL outage causes an explicit unavailable state, not a new SQLite database.

## Phase 5 - Make gameplay and combat authoritative

**Purpose:** All connected players must agree on mobs, hits, rewards, locations, and safe-zone rules.

Tasks:

- Introduce server-owned entity IDs, pack IDs, zone IDs, simulation timestamps, and state revisions. One server-owned spawn decision is replicated to clients; clients do not independently randomize online encounters.
- Accept player intent: movement input, selected target, cast request, mount request, and interaction request. Validate speed, position constraints, range, line of sight, cooldown, mana, life state, and zone membership server-side.
- Use client prediction for responsiveness and authoritative reconciliation for results. Interpolate remote movement and animations. Define separate reliable event and movement/snapshot channels.
- Define the combat state machine: `idle -> windup -> release -> recovery -> idle`, with explicit stun, interrupt, death, mount, map-transfer, and disconnect transitions.
- Add a bounded input buffer; start with approximately 100-150 ms and tune by playtest. Repeated input cannot bypass recovery or spend mana twice.
- Give every cast a unique ID and release timestamp. Predicted effects reconcile with the server result; rejected casts remove predicted feedback cleanly.
- Separate animation timing, effect timing, and damage authority. A late animation callback must never create a second hit or reward.
- Define every spell's targeting shape and mechanics in shared data. Resolve the current ambiguity between Incendio's described cone/stream and projectile-like behavior. Recommended slice behavior: short-range cone burst plus a server-timed burn; visuals must match it.
- Validate projectile swept collision, AoE victim filtering, friendly/NPC exclusions, interrupt/weakening duration, knockback, shield behavior, status stacking, immunity, and death cancellation.
- Protego must have one explicit rule for blocked versus reflected projectiles and reduction of other damage. Match the tooltip, VFX, and authority logic.
- Reimplement Phase 1 protection and reactive aggro rules on the server. Replicate the protected flag for presentation, but never trust the client's flag for damage decisions.
- Publish complete stat snapshots and ordered deltas to a character-state model that drives HUD updates. Include max-stat changes, reconnect snapshots, level-up, and reward events.
- Serialize encounter rewards, death, resurrection, and persistence around a clear ownership model. Disconnecting mid-fight must not duplicate an entity or reward.
- Implement zone interest filtering so players do not receive all entity state from every map.

**Deliverables:** Server-owned combat/encounter systems, versioned messages, client prediction/reconciliation, synchronized stat events, and multi-client tests.

**Exit checks:** At least two independent clients see the same pack, health, cast outcome, death, and respawn. Forged damage/XP/position requests are rejected. Test latency and packet loss with documented profiles. A protected target cannot be damaged by delayed projectiles, burn ticks, or boss AoE. Each kill rewards eligible players exactly once.

## Phase 6 - Automate server maintenance and deployment

**Purpose:** A successful server release triggers a controlled maintenance cycle that removes players before live server replacement.

Use GitHub Actions for build/release orchestration and a restricted deployment mechanism on the server. GitHub does not itself know how to save or disconnect in-game players; implement those operations in the world server's authenticated administration interface.

Recommended development trigger: a merge to the designated server release branch builds/tests automatically, then deploys only a successful artifact. Feature branches must not interrupt a live server. Pin exact commit/artifact identifiers throughout.

Required state sequence:

```text
ONLINE
  -> BUILD_AND_STAGE       existing world remains playable
  -> ANNOUNCING            publish maintenance reason and deadline
  -> DRAINING              reject new logins; finish/cancel pending operations safely
  -> SAVING               freeze new state mutations; flush authoritative state
  -> DISCONNECTING        notify and remove every connected player
  -> MAINTENANCE          confirm zero sessions; stop the old world process
  -> APPLYING             migrate if required; switch to the staged release
  -> VERIFYING            readiness, contract, database, and synthetic login checks
  -> ONLINE               reopen logins and publish the active version
```

Tasks:

- Build, test, sign/checksum, and stage an immutable release before disrupting players. Eliminate live `git pull` and in-place extraction over running code.
- Use a configurable countdown, initially five minutes with shorter notifications near the deadline. Display it in the game and launcher.
- Close logins and prevent new long-running transfers/trades near the deadline. Freeze mutations before the final save barrier; a save followed by more gameplay is not a final save.
- Await persistence acknowledgments with bounded timeouts. On failure, remain in a clearly reported safe state and abort the replacement; do not report a successful update after losing saves.
- Disconnect players before applying the server update, verify the connected-session count is zero, then stop the process.
- Store releases in separate directories with an atomic active-release pointer. Keep the previous known-good artifact and its configuration reference.
- Run schema migrations explicitly. Prefer compatible expand/contract migrations; a binary rollback does not automatically undo a database migration.
- Start the new services and verify readiness, database schema, protocol/content versions, login, character load, and world spawn before reopening access.
- Keep a lightweight status/release endpoint available while the world server is stopped so the launcher can distinguish maintenance from an unreachable service.
- Serialize deployments per environment and keep a server-side deployment lock/state journal. Do not cancel a deployment mid-migration just because another commit arrives. New build jobs may replace obsolete build jobs; active deployment mutation must recover safely.
- If verification fails, keep maintenance active and restore the previous compatible release. For an irreversible migration, use its planned recovery procedure instead of pretending a pointer switch is sufficient.
- Log the initiating release, prior release, drain result, save result, migration, readiness, and rollback outcome without secrets.

GitHub environments and concurrency controls support this orchestration; the application-specific drain/save logic still belongs in HPMMO. [GitHub deployment controls](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)

**Deliverables:** Server CI/release workflow, deployment controller/scripts, maintenance API/events, persistent deployment journal, status endpoint, and rollback runbook.

**Exit checks:** Rehearse with connected players, a failed build, a failed final save, a failed migration, an unhealthy new binary, two closely spaced releases, and a deployment-controller restart. No live files change before the player-disconnect barrier. No failed release is advertised as online.

## Phase 7 - Build the native launcher updater

**Purpose:** Client updates happen through the launcher with verification and recovery.

Tasks:

- Make the C++ launcher the single supported distribution path; archive or clearly label legacy Python launchers after feature parity.
- Define a signed release manifest containing channel, client version, minimum launcher version, protocol range, content version/hash, minimum server compatibility, platform, download URLs, sizes, file hashes, and release notes.
- Separate `client_version`, `server_version`, `protocol_version`, `content_version`, and `schema_version`. Not every server patch requires a client patch, but compatibility-breaking changes must be enforced.
- Fetch manifest/status over HTTPS, verify its signature using a pinned trusted key, and verify downloaded artifact hashes. A hash from an untrusted manifest is not sufficient authenticity.
- Download into a staging directory with progress, cancellation, resume, retries, disk-space checks, and clear error messages.
- Validate archive entries against absolute paths and directory traversal. Verify the complete staged installation before activation.
- Use versioned installation directories and an atomic active-version switch. Keep the previous known-good version for repair/rollback.
- Detect a running game and wait for it to close before switching its installation. Do not overwrite open executable/PCK files.
- Preserve user settings, keybinds, logs, and screenshots separately from versioned game files.
- Support repair of missing/corrupt files. Prefer complete verified packages first; add delta patching only after full updates and recovery are reliable.
- Handle launcher self-updates through a small verified bootstrap/helper after the old launcher exits.
- Show online/maintenance/offline states, update requirements, release notes, and retry actions. Launch only a server-compatible build.
- Use the Phase 4 session/ticket flow. Never embed server credentials or private deployment tokens in the client package.
- Coordinate cross-repository releases: publish required client content first, keep the server compatibility window explicit, then switch server requirements after artifacts are available.

**Deliverables:** Native update state machine, signed manifest generator, client build/release workflow, repair feature, bootstrap strategy, and compatibility tests.

**Exit checks:** Install from an older version; interrupt/resume a download; reject a tampered package; handle insufficient disk space; repair a missing file; preserve settings; recover after interruption during activation; display maintenance correctly; reject incompatible online play without entering a login loop.

## Phase 8 - Build separate maps and a real multi-floor castle greybox

**Purpose:** Validate navigation and map ownership before expensive art production.

Initial playable layout:

| Map / floor | Required spaces | Gameplay purpose |
| --- | --- | --- |
| Grounds | Safe courtyard, training terrace, entrance approach, forest paths, distinct encounter clearings | Social hub, practice, travel, pack combat, flight |
| Interior ground floor | Entrance vestibule, Great Hall, grand staircase hall, side corridors | Arrival, orientation, social encounters |
| Interior first floor | Library, classroom, gallery overlooking the stair hall | Exploration, NPC/quest destinations |
| Interior second floor | Upper classrooms, tower landing, balcony/gallery connections | Vertical route and staircase interaction |
| Interior basement | Dungeon classroom and a clearly marked future encounter entrance | A contrasting atmosphere and expansion route |

Tasks:

- Replace the single flat-floor assumption with elevations, meaningful sightlines, overlooks, corridors, and alternate routes. Use a readable floor plan and landmark hierarchy.
- Author walkable floors, stairs/ramps, railings, doorways, collision, navigation, portal markers, and spawn points before final materials.
- Keep exterior and interior scale visually plausible through the entrance vestibule; avoid a sudden camera-scale mismatch at the transition.
- Implement server-authorized map transfer: request, validate, reserve destination, mark transfer pending, load client map, acknowledge readiness, transfer entity ownership, and spawn from a server-approved location.
- Persist or recover a transfer token/state so reconnecting during a transition cannot duplicate a character or strand it between maps. Expire failed reservations and return to the last valid safe spawn.
- Keep only the appropriate player controller, HUD bindings, ambient audio, and map resources alive after a transition. Verify that old worlds actually unload.
- Prohibit broom flight inside the initial castle slice. Provide a landing/dismount area before entry and clear feedback when mounted entry is attempted.
- Add floor-aware map labels and direction signs. Every important room must have a reachable route without developer teleportation.

### Magical staircase prototype

- Build one functional staircase connecting alternative landings across at least three levels.
- Define `docked`, `boarding_warning`, `moving`, and `docking` states, with server-owned timing and destination.
- Move collision and visuals together. Carry riders consistently with the platform; do not teleport only the mesh while the player falls through.
- Block new entry during unsafe motion and keep passengers protected from crushing/falling edge cases through tested railings and movement rules.
- Enable navigation links only when docked. NPCs must not path across an absent connection.
- Keep a conventional fallback stair route so the moving staircase cannot make required rooms permanently inaccessible.
- Resolve logout, disconnect, death, and loading while on a moving stair to a valid landing or safely reconstructed platform state.

**Deliverables:** `grounds` and `castle_interior` map scenes, floor plan, portal/transfer system, zone collision/navigation artifacts, and a moving-stair test scene.

**Exit checks:** Walk the entire route from courtyard to upper floor and back without clipping, flight, or teleport cheats. Two clients see the same staircase position. Repeated transitions, transfer interruption, and relog inside the castle produce a valid character location and no duplicate HUD/world nodes.

## Phase 9 - Redesign characters and broom animation

**Purpose:** Replace short prototype proportions and make the rider physically belong on the broom.

Character tasks:

- Create or source a taller humanoid with coherent face/hair/robe/boots/hands and the approved Phase 2 proportions.
- Use a stable deforming skeleton and sensible robe weighting. Test shoulders, elbows, hips, knees, and cloth intersections in extreme casting and riding poses.
- Author house variations through materials/clothing details without duplicating the entire character rig unnecessarily.
- Add sockets for wand, broom seat, hands, feet, and wearable equipment. Update collision capsule, camera pivot, targeting height, nameplates, and interaction distances to match the new body.
- Build an animation graph for idle, walk, run, strafe, turn, jump, fall, land, cast variants, hit, stun, death, revive, interact, and mounted states.
- Use upper-body casting blends where appropriate, with explicit movement restrictions for committed attacks. Footsteps and wand release events should align with contact/motion.

Broom tasks:

- Replace the placeholder broom with a shaped wooden shaft, wrapped grip, bristles, and proper material detail.
- Establish a single `MountRoot` and `SeatSocket`; normalize model axes in one wrapper. Godot's conventional forward direction is -Z, but imported models must be measured rather than assumed.
- Create dedicated mount, seated idle, takeoff, acceleration, cruise, bank left/right, climb, dive, braking, landing, and dismount clips. A generic chair-sitting animation is a temporary fallback only.
- Blend rider lean with acceleration and banking; maintain plausible hand/foot contact through animation or IK. Keep camera roll restrained and configurable.
- Drive the magical trail from speed/acceleration and broom socket velocity. Use tapered textured ribbons, flame wisps, and sparse sparks; remove visible cube-like particles.
- Handle mount requests during combat, stun, death, map changes, insufficient clearance, and unstable ground. Replicate mount state and animation phase to remote clients.
- Check landing ground normal, capsule clearance, ceiling height, and safe dismount position before committing the transition.

**Deliverables:** New character and broom source/export files, animation libraries/graph, socket specification, mount state machine, and flight presentation scene.

**Exit checks:** No backward riding, floating hands, severe robe clipping, foot sliding, abrupt pose resets, or dismount-through-floor behavior in the test route. Repeat mount/dismount while turning and after a network correction. Remote players see the same mounted state.

## Phase 10 - Replace castle art and improve the environment

**Purpose:** Turn the approved greybox into a detailed castle with believable surfaces and readable lighting.

Tasks:

- Build a reusable Gothic-inspired kit: wall modules, corners, pointed arches, columns, buttresses, windows, doors, floors, stairs, rails, roof pieces, towers, trim, and damaged/aged variants.
- Replace procedural brick coloring as the main final surface with authored PBR materials: base color, normal, roughness, appropriate AO, and optional height/detail masks.
- Use non-metallic stone/wood/cloth values and metallic maps only where appropriate. Confirm normal-map orientation and texture color-space/import settings in Godot.
- Add trim sheets, consistent texel density, stone size references, edge wear, mortar depth, dirt/moisture masks, and sparse decals to break repetition. Do not bake strong directional lighting into base color.
- Dress rooms by purpose: long tables and candles in the Great Hall; shelves, ladders, desks, and reading corners in the library; lecterns, teaching props, and benches in classrooms; banners, portraits, suits of armor, and signage in circulation spaces.
- Make at least one tower accessible from the interior route. Clearly label inaccessible exterior towers as later content rather than implying that every visible tower is enterable.
- Replace the empty flat outdoors with shaped terrain, slopes, path edges, courtyards, rock clusters, vegetation variation, landmarks, and encounter clearings. Keep safe-zone boundaries visually understandable.
- Use daylight and sky/ambient contribution that preserve texture detail. Add warm interior fixtures and local contrast around important routes.
- Reduce broad haze and excessive bloom. Use localized atmosphere only where it serves the room/landscape; fog must not obscure ordinary navigation or disguise unfinished terrain.
- Compare neutral-light and final-light material captures. Increasing brightness alone does not fix low-resolution textures or flat geometry.
- Bake suitable static lighting and limit shadow-casting dynamic lights. Profile the selected Godot rendering path; offer reduced particles, shadows, and postprocessing for the Intel integrated GPU profile.
- Add occlusion-friendly room boundaries, LODs, visibility ranges, and instancing for repeated props. Avoid one giant merged interior mesh that defeats room-level culling.

**Deliverables:** Exterior kit, dressed first interior route, PBR material library, terrain/vegetation pass, lighting presets, collision/navigation exports, and before/after captures.

**Exit checks:** Stone reads as stone at normal viewing distance; walls are not visibly stretched; interiors have connected multiple floors; important destinations remain readable without heavy fog; the same route is checked on the target Intel graphics configuration.

## Phase 11 - Rebuild monster assets, packs, and bosses

**Purpose:** Replace poor spiders/monsters and deliver the requested group encounter behavior.

### Creature asset requirements

- Create/source an anatomically readable eight-legged spider: cephalothorax, abdomen, articulated leg chains, mouthparts, and a purposeful silhouette. Avoid a collection of obvious spheres and sticks.
- Use chitin roughness variation, subtle normal detail, appropriate eyes, and controlled hair detail where affordable. Validate leg count, mirrored UVs, joint deformation, ground contact, and silhouette from the gameplay camera.
- Rig a coordinated walking cycle, turning, idle motion, bite anticipation, attack, hit reaction, stun, and a proper death curl/collapse. Dead spiders must not keep walking or attacking.
- Replace mismatched toy-like humanoid/boss placeholders with creatures and dark wizards matching the hero/environment style.
- Give bosses distinctive silhouettes, readable weapons/anatomy, unique attack animations, and stronger audiovisual identity rather than only larger scale and more HP.

### Spawn and AI requirements

| Rule | Planned behavior |
| --- | --- |
| Ordinary pack | Three or five members; separate setting controls pack count per region |
| Solo boss | One boss with a defined arena/leash and longer respawn |
| Escorted boss | One boss plus exactly two configured escorts |
| Random placement | Server samples valid encounter polygons/navmesh, then validates all member locations |
| Exclusions | Safe zones and buffers, interiors without encounters, cliffs, water, solid geometry, portal arrivals, and occupied spawns |
| Aggro | Reactive on a valid player attack by default; pack assistance stays within its configured group |
| Chase | Pathfinding, local separation, attack slots, line of sight, leash, and target validity |
| Return | Clear attacks/statuses as designed, return home, reset encounter when all valid targets are lost |
| Death | Mark dead immediately; stop damage/collision as appropriate; play animation; grant rewards once; retain corpse briefly; fade/despawn |
| Respawn | Server-owned timer after pack defeat; select a newly validated anchor; avoid spawning on visible nearby players |

Tasks:

- Use data-defined encounter templates, weighted region choices, stable encounter IDs, maximum alive counts, and reproducible debug seeds.
- Validate every formation member, not just the pack center. If placement fails after bounded retries, defer spawning instead of placing enemies inside walls.
- Use navigation paths around obstacles, separation to reduce stacking, and attack slots so five mobs do not occupy one point.
- Set attack anticipation, release, recovery, and facing rules. Boss attack areas need a visible warning that matches authoritative damage timing.
- Add at least two boss patterns: a directional attack and an area attack, with recovery windows. Introduce health phases only after the base patterns work reliably.
- Define escort reset/respawn behavior with the boss, party loot/XP eligibility, contribution rules, and leash-reset reward cancellation.
- Match corpse lifetime to animation duration. Pooling, if used, must reset health, animation, effects, targets, collision, and signals completely.

**Deliverables:** Accepted creature assets, animation libraries, encounter templates, authoritative pack/boss AI, loot/death lifecycle, and encounter debug tooling.

**Exit checks:** Three- and five-member packs appear in different valid positions across cycles. Proximity alone does not trigger ordinary mobs. Packs cannot enter the hub. Solo and escorted bosses work. Corpses visibly finish a death animation, rewards occur once, and respawns do not overlap players or geometry. All clients observe the same results.

## Phase 12 - Rebuild spell VFX and sound from an asset inventory

**Purpose:** Replace visibly primitive magic with layered, animated effects that explain combat.

### 12.1 Required terminology

| Term | Meaning | Spell example |
| --- | --- | --- |
| Asset | Any production content used by the game | Model, texture, sound, animation, or effect scene |
| Mesh | Geometry forming a 3D shape | Wand, ice shard, trail ribbon, shield shell |
| Texture | Image sampled on a surface or particle | Smoke opacity, flame frame, energy noise |
| Material | The surface/effect appearance configuration | Transparent emissive flame or rough stone |
| Shader | Program controlling how pixels/vertices render | Distortion, flowing energy, erosion/dissolve |
| Particles | Many small elements emitted and animated over time | Embers, smoke, sparks, magical dust |
| Animation | Motion or property changes over time | Wand swing, flame sequence, impact expansion |
| VFX | The complete visual effect assembled from these parts | Cast, travel, impact, lingering state, and dissipation |
| Flipbook | Ordered animation frames stored in an atlas/sequence | Evolving flame plume or explosive smoke |
| Rig | Skeleton and controls that animate a model | Wizard arm/hand motion or spider leg chains |
| SFX | Sound effects | Cast snap, projectile hiss, impact, shield crack |
| PBR | Physically based surface shading inputs | Stone base color, normal, roughness, and AO |

### 12.2 Inventory before implementation

The following is a production list, not a claim that the missing content already exists. The dedicated VFX folder currently contains the two Kenney images noted below. Audit reusable images and embedded resources elsewhere before commissioning duplicates.

| Asset ID | Required content | Suggested starting format | Current status |
| --- | --- | --- | --- |
| `vfx_flame_static` | Existing flame element | Current PNG; verify alpha/import | Present: `flame_01.png`; ingredient only |
| `vfx_spark_static` | Existing spark element | Current PNG; verify alpha/import | Present: `spark_01.png`; ingredient only |
| `vfx_soft_glow` | Soft radial opacity/glow | 256-512 px RGBA | Missing from dedicated inventory |
| `vfx_noise_flow` | Tileable noise and directional flow | 512 px linear data textures | Missing / audit shader-generated alternatives |
| `vfx_noise_erosion` | Dissolve/erosion noise | 512 px grayscale | Missing |
| `vfx_flame_loop` | Coherent looping flame animation | 8x8 atlas, 2048 px, 64 frames, transparent | Missing |
| `vfx_fire_burst` | Non-looping directional fire burst | 8x8 atlas, 2048 px | Missing |
| `vfx_smoke_puff` | Evolving soft smoke/dust | 8x8 atlas, 2048 px | Missing |
| `vfx_energy_impact` | Irregular magical impact | 4x4 or 8x8 atlas, 1024-2048 px | Missing |
| `vfx_energy_streak` | Tapered streak/trail mask | 1024x256 RGBA | Missing |
| `vfx_lightning_branches` | Irregular branching energy masks | 512-1024 px or authored ribbon inputs | Missing |
| `vfx_shield_ripple` | Local impact ripple and fracture masks | 512-1024 px | Missing |
| `vfx_distortion` | Smooth distortion vector/noise input | 256-512 px linear data | Missing |
| `vfx_ground_marks` | Scorch, dust, and fragmented impact marks | Small atlas, 1024 px | Missing |
| `vfx_rune_masks` | Optional restrained rune/telegraph masks | 512-1024 px | Missing; use only where design calls for them |
| `vfx_trail_mesh` | Camera-aware tapered strip/ribbon | Reusable procedural/authored mesh | Needs authored UVs and motion testing |
| `vfx_shield_mesh` | Smooth low-cost shell | Reusable mesh with distortion/ripple material | Existing shield logic must be audited; final art pending |
| `vfx_shard_meshes` | Small irregular debris/shards | 3-5 low-poly mesh variants | Missing |
| `vfx_projectile_mesh` | Optional subtle carrier/core geometry | Low-cost mesh | Existing primitive core is a placeholder |
| `sfx_spell_library` | Cast, travel, impact, sustain, and end layers | WAV masters and imported playback files | Required set not established; full audio audit needed |

Atlas specifications must include frame count, frame order, FPS, loop/non-loop flag, alpha convention, padding, and color space. Do not treat 64 unrelated AI-generated flame pictures as a coherent flipbook. Prefer rendered simulation or deliberately authored frame sequences for temporal consistency. Inspect alpha against both dark and light backgrounds and test atlas bleeding under mipmapping.

Use base-color images in the appropriate color space; treat masks, normals, and flow maps as data. Alpha blending, additive blending, depth behavior, and billboard orientation must be chosen per layer. Smoke should not look like glowing white light. Additive blending is unsuitable for every layer.

### 12.3 Spell-by-spell composition

| Spell | Visual layers | Animation/audio/gameplay alignment |
| --- | --- | --- |
| Basic Cast | Small wand flash, tapered golden trail, irregular impact flecks, short glow decay | Fast wand flick; sharp cast snap and light hit; minimal screen coverage |
| Stupefy | Red energy buildup, narrow trail, textured impact, restrained stun indicator | Release at the cast event; impact and stun cue from confirmed hit; distinct stun end |
| Incendio | Flame burst flipbook, overlapping transparent flame wisps, ember particles, smoke fade, brief heat distortion | Cone shape/range matches Phase 5 definition; fire onset, short roar, burn loop, extinguish |
| Bombarda | Traveling charge, very short impact flash, expanding textured dust, debris shards, smoke and optional ground mark | Telegraph/impact matches actual AoE; weighted blast with controlled low-frequency content |
| Expelliarmus | Red/pink tapered ribbon, irregular energy streaks, directional impact, weakening/interrupt cue | Wand sweep aligns with launch; recoil and interruption follow confirmed outcome |
| Protego | Transparent shell with flowing noise, rim detail, localized hit ripples, optional fracture on expiration | Shield raise, sustained low hum, positional impact ping, clear end; shell geometry is appropriate here |
| Ultimate | Anticipation field, irregular branching lightning/ribbons, layered impacts, residual sparks/smoke | Readable warning before damage; limited exposure/bloom; distinct charge, strike, and tail |
| Broom trail | Tapered energy ribbon, translucent wisps, sparse embers | Driven by speed/acceleration; loop fades on braking and stops on dismount |
| Boss warning | Ground mask/shape matching the hit area, edge motion, countdown cue | Authority provides start/release timing; warning remains readable in crowds |

### 12.4 Godot integration and timing

- Create reusable effect scenes with explicit `cast`, `travel`, `impact`, `sustain`, and `end` stages where applicable.
- Use GPU particles where the target rendering path benefits, with tested reduced-quality variants. Prefer textured billboards/ribbons for flame and energy; keep solid geometry only where it serves a physical or shield form.
- Use animation curves for opacity, scale, emission, velocity, light energy, distortion, and sound volume. A light turning on/off abruptly is not a polished effect.
- Treat visual effects as presentation: their cleanup, quality setting, or culling must never change authoritative damage.
- Align emission origins with the actual animated wand socket. Protect against near-wall launches, vertical aiming, zero-length directions, and abrupt orientation flips.
- Limit distortion, dynamic lights, transparent overlap, and camera shake. Provide reduced flash/shake options and maintain target/telegraph visibility.
- Build low/medium/high variants by reducing layer counts, atlas size, and dynamic lighting while preserving gameplay information.
- Ensure effects finish or cancel correctly on death, map transfer, interruption, network rejection, and shutdown. Pool only after ownership and reset behavior are tested.

Example Incendio presentation timeline, to tune against gameplay: 0.00-0.12 s anticipation; release at approximately 0.12 s; primary burst over the next 0.25-0.40 s; embers/smoke fade over roughly 0.8 s; burn feedback continues only for the authoritative status duration. These are starting art timings, not a reason to silently change balance data.

### 12.5 Soundscape

- Create cast/travel/impact/end variants for all seven spells; avoid the same generic sound on every action.
- Add surface-specific footsteps, robe movement, mount/dismount, broom wind, landing, spider movement/bites/death, boss attacks/death, UI feedback, and map transitions.
- Add exterior wind/birds and interior room tones, fire/candles, distant activity, and moving-stair mechanisms. Give the Great Hall, library, and dungeon distinct acoustic character.
- Use spatial emitters, attenuation, interior/exterior reverb treatment, voice limits, subtle variation, and separate music/SFX/UI/ambience volume controls.
- Keep dialogue/intelligibility and combat warnings audible during large spell combinations. Check headphones and ordinary speakers.

**Deliverables:** Completed VFX/audio manifest, source flipbooks/textures/meshes/audio, reusable Godot effects, spell presentation definitions, credits, and a showcase/test scene for every effect.

**Exit checks:** Flames and energy have soft detailed animated structure without visible cubes or opaque primitive stacks. Shield/telegraph geometry remains intentional. Every required asset is integrated or explicitly listed as missing; placeholder art cannot pass final acceptance. Each spell's visuals and sound match its actual timing, range, status, and cancellation behavior.

## Phase 13 - Finish HUD, interaction, and player feedback

**Purpose:** Make important game state continuously understandable.

Tasks:

- Bind HP, mana, XP, level, currency, target health, cooldowns, and status icons to the authoritative character/target state model. Subscribe/unsubscribe safely across death, relog, and scene replacement.
- Apply max/current values together, clamp only for display safety, and distinguish smooth bar animation from the actual numeric state. A tween must not overwrite a newer server value.
- Add cast progress/recovery feedback, insufficient-mana reasons, out-of-range/blocked-target reasons, safe-area indication, boss health, loot/XP feedback, and clear death/respawn UI.
- Add indoor floor/location labels, portal/loading progress, staircase warnings, mounted controls, invalid landing feedback, and maintenance countdowns.
- Make menus and interaction prompts respect input focus so clicks/keys in UI do not unexpectedly cast or mount.
- Provide scalable UI at common aspect ratios and resolutions, readable contrast, key rebinding, sensitivity settings, and independent shake/flash/volume controls.
- Add a short training flow covering dummy practice, safe-zone boundaries, reactive packs, broom controls, and castle entrance.

**Deliverables:** Integrated HUD/menus, state-binding tests, player-facing feedback messages, settings, and a short onboarding route.

**Exit checks:** Damage, potion use, regeneration, spending, rewards, level-up, death, respawn, reconnect, maintenance, and map transfer all update the UI correctly. No stale duplicate listeners remain. UI animation cannot show an older HP/mana/XP value after a newer update.

## Phase 14 - Validate the complete multiplayer slice

**Purpose:** Demonstrate the requested result rather than declaring success from isolated features.

### Required test matrix

| Category | Required scenarios |
| --- | --- |
| Regression | Inventory decoding, vertical/zero-vector effects, all spell casts, world enter/exit, verbose shutdown |
| Protected area | Boundary crossing, delayed projectile, AoE, burn, knockback, boss chase, spawn sampling, dummy exception |
| Encounters | Reactive aggro, pack assistance, 3/5 members, solo/escorted boss, death, corpse cleanup, reward once, respawn |
| Combat | Low mana, queued inputs, interruption, shield, line of sight, fast projectile, status expiration, death during windup |
| Character/flight | All animation blends, orientation, mount spam, wall/ceiling clearance, landing, remote mounted state |
| Castle | Every floor route, moving stairs, doorway clearance, camera clipping, map transfer, reconnect during transfer |
| Persistence | Ownership checks, save/reload, concurrent reward/trade, stale revisions, database outage, deliberate dev reset |
| Deployment | Countdown, login closure, save barrier, disconnect barrier, failed rollout, rollback, interrupted deploy |
| Launcher | Old install, tamper rejection, interrupted download, disk full, repair, running-game lock, incompatible version |
| Multiplayer | Two-client correctness first; then 4/16-player sessions and larger simulated load with measured limits |
| Presentation | Neutral/final lighting comparison, art consistency, no placeholder spider/hero, spell visibility, audio mix |

### Performance and reliability gates

- Record the exact Intel graphics device/driver and test resolution. Initial target: stable 30 FPS minimum on the agreed low preset, with a 60 FPS target where hardware permits; measure frame-time percentiles and publish exceptions before locking a release target.
- Select a server tick rate from measurement; 20-30 Hz is a starting evaluation range, not a promised capacity. Track p95/p99 tick time and leave scheduling headroom under the chosen budget.
- Test packet delay/loss profiles and report correction frequency, hit consistency, disconnect handling, and bandwidth per player.
- Run a minimum one-hour representative soak plus repeated map entry/exit, mass casts, pack deaths/respawns, and mount cycles. Memory must not grow continually after expected caches warm up.
- Inspect visible draw calls, transparent overdraw, dynamic lights, texture memory, animation cost, navigation, and physics separately. Reduce actual bottlenecks rather than blindly lowering every setting.
- Require no unexplained script errors, missing resources, duplicate rewards, or monotonically growing orphan/resource counts. Isolate and document any reproducible engine-only shutdown issue instead of hiding the log.
- Verify clean checkout/build/install and test a packaged game through the launcher, not only editor play mode.

**Deliverables:** Acceptance report with build IDs, hardware, settings, measurements, captures, test outcomes, and remaining defects classified by severity.

**Exit checks:** The complete journey in Section 1 passes on packaged builds with multiple clients. Visual acceptance is separate from automated correctness. Any deferred visual placeholder is named explicitly and prevents claiming its corresponding request is complete.

## Phase 15 - Release the slice and expand deliberately

Tasks:

- Publish a reproducible client/server release pair and its compatibility manifest after Phase 14 passes.
- Rehearse the actual launcher-to-maintenance-to-reconnect journey against the deployed development environment.
- Archive the baseline captures beside final captures so visual improvement is demonstrable.
- Extend the castle wing by wing using the same modular kit, zone data, navigation, lighting, and performance gates: additional towers, dormitories/common rooms, courtyard variants, advanced classrooms, dungeon encounters, and secrets.
- Expand enemy families and boss patterns only after the first spider pack and two boss compositions meet the quality bar.
- Reassess a fully standalone C++ world server using measured bottlenecks, desired scale, protocol requirements, and implementation cost. Do not rewrite a working server solely because another language sounds more MMO-like.

**Deliverables:** Release notes, artifact/contract versions, deployment record, updated asset registry, and the next content backlog.

**Exit checks:** A new installation can complete the slice without editor tools. A server-only compatible update does not unnecessarily force a client download. A required client update is detected and applied by the launcher. The castle is demonstrably multi-floor and accessible, rather than a detailed facade around one flat room.

## 5. Copy-ready English implementation prompts

These prompts are instructions for future implementation work. They do not mean that the assets or systems have already been created.

### A. Master implementation prompt

```text
You are implementing the HPMMO roadmap in plan.md in the current workspace.
Read the plan, repository instructions, existing code, and asset credits first.
Inspect what actually exists and select the earliest incomplete phase whose
dependencies are satisfied. Preserve unrelated work and existing usable features.

Build a coherent, playable wizard MMORPG with a protected NPC/training courtyard,
reactive packs of three or five mobs, solo bosses and bosses with two escorts,
proper death animations, server-authoritative combat, taller characters, smooth
broom riding, and a detailed multi-floor Hogwarts castle interior loaded as a
separate shared map. Include functioning magical stairs and a normal fallback route.

Create original assets or find suitable licensed assets online: models, rigs,
animations, PBR textures, materials, shaders, particle elements, coherent flipbooks,
spell effects, sounds, room props, terrain, and architectural modules. Research
actual downloadable files and their licenses, not just search-result thumbnails.
Maintain an asset manifest with source URLs, licenses, hashes, import settings,
status, and missing items. A concept image is not a completed 3D model; a static
flame image is not an animated fire effect; a placeholder is not final art.

Before building each effect, list its required textures, flipbooks, meshes, sounds,
and animation events. Assemble them as layered Godot scenes. Use detailed soft
transparent flame/energy imagery and textured ribbons instead of obvious opaque
spheres, cubes, and rings, except where geometry is intentional, such as a shield.

Use the architecture and phase dependencies in plan.md. Implement separate client
and server repositories under one local workspace, PostgreSQL persistence, the
planned C++ service, an authoritative Godot world server, controlled server
maintenance, and a verified native launcher updater. Keep dev resets explicit.

For each phase, deliver working code/content, the required tests, actual in-engine
captures, and a concise report of what changed, what was verified, and what remains
missing. Test packaged client/server builds where relevant. Never claim visual
quality from passing headless tests. Never invent downloaded/generated assets or
claim an unavailable tool produced a rig, animation, sound, or model.

Complete the selected phase's acceptance checks before moving on. If an external
asset/tool/budget is unavailable, continue independent work and record the exact
gap. Keep the art direction and performance budget consistent across the game.
```

### B. Asset discovery and production prompt

```text
Audit HPMMO's assets and produce a production manifest for the current phase.
For each needed asset, specify purpose, visual style, scale, geometry/texture budget,
rig/animation requirements, collision/LOD requirements, and Godot integration path.
Find 2-3 credible candidates where useful, verify the original asset page and
license, and distinguish free, paid, original, placeholder, and accepted content.
Prefer a consistent family of assets over unrelated high-quality individual files.

Create original assets where available tools support the required output. Deliver
editable source plus game-ready GLB/GLTF, PBR maps, animation clips, and Godot scenes
as applicable. If only image generation is available, use it for concepts or texture
ingredients and explicitly list the remaining modeling/rigging work. Verify scale,
UVs, normals, alpha, animation continuity, and gameplay-camera readability in engine.
Do not buy assets without a provided budget. Do not mark unavailable content done.
```

### C. Castle, materials, and level-design prompt

```text
Implement the approved castle greybox as a separate shared interior map connected
to the outdoor grounds through a validated entrance transition. Build an entrance
hall, Great Hall, library, classrooms, basement, upper galleries, and an accessible
tower route. Include at least three connected levels and a functioning magical
staircase with synchronized collision, navigation links, and a fallback route.

Use the approved taller character scale. Create a modular Gothic architectural kit,
believable PBR stone/wood/slate, trim sheets, varied room props, coherent texel
density, warm readable interior lighting, and restrained atmosphere. Remove the
flat single-floor layout and obvious repeating procedural brick appearance.
Keep exterior/interior transitions, camera clearance, performance, and navigation
correct. Deliver floor plans, source assets, Godot scenes, material provenance,
walkthrough captures, and tested map-transfer/reconnect behavior.
```

### D. Spider, packs, and boss prompt

```text
Replace the current spider with a well-proportioned, rigged eight-legged creature
matching HPMMO's grounded magical fantasy art direction. Include coordinated walk,
turn, idle, bite anticipation/release/recovery, hit, stun, and death curl animations.
Use detailed chitin materials and validate leg contact/deformation from the player
camera. Provide source files, GLB export, textures, collision, LODs, and credits.

Integrate it into server-owned reactive packs of three or five. Proximity must not
start ordinary combat; a valid hit activates only the intended pack. Exclude the
NPC/training safe zone from spawning, navigation, targeting, and all damage paths.
Add a solo boss and a boss with two escorts, readable warnings, real death
animations, exactly-once rewards, corpse cleanup, and valid randomized respawns.
Prove the results with multiple connected clients and gameplay captures.
```

### E. Spell VFX and audio prompt

```text
Redesign HPMMO's seven spells and broom trail using the VFX inventory in plan.md.
Before implementation, list all required textures, transparent masks, coherent
flipbooks, ribbon/shield/debris meshes, shaders, sounds, and timing events. Mark
existing, missing, sourced, created, integrated, and accepted assets separately.

Create or source temporally coherent fire, smoke, energy-impact, and lightning
elements. Supply frame layout/FPS/alpha metadata and licenses. Build layered cast,
travel, impact, sustain, and end stages in Godot, synchronized with authoritative
spell events and character animation. Use detailed translucent images for flame
and energy; avoid visible cubes and opaque geometric stacks. Use a mesh shell only
where the effect calls for one, such as Protego.

Add distinct spatial cast/flight/impact/status/end sounds, voice limits, quality
presets, and reduced flash/shake options. Ensure cleanup, interruption, rejection,
death, and map transfer cannot leave effects or sounds running. Deliver a test
scene and captures of every spell in daylight, a dark interior, and a group fight.
List any missing asset explicitly instead of disguising a placeholder as finished.
```

### F. Character and flight prompt

```text
Replace the short prototype wizard with a taller, properly proportioned character
using the approved rig and art direction. Update collision, camera, sockets,
equipment, targeting height, and animation blending to the new body.

Fix broom/rider forward axes at the model wrapper and seat socket. Create dedicated
mount, takeoff, seated idle, cruise, bank, climb, dive, brake, land, and dismount
animations with believable hand/foot contact and controlled body lean. Replace
cube-like exhaust with textured magical ribbons, wisps, and sparks driven by speed.
Validate ground clearance, walls/ceilings, repeated input, death, and map transitions.
Deliver source/export assets, animation graphs, in-engine front/side/rear captures,
and proof that remote clients see the same mounted state.
```

### G. Infrastructure and update prompt

```text
Implement the repository, PostgreSQL/C++ service, authority, deployment, and native
launcher phases in plan.md in dependency order. Preserve the old checkout until
the two new repositories build independently under the shared local workspace.

Replace the mixed PostgreSQL/SQLite path with real PostgreSQL CRUD, authenticated
ownership checks, correct transactional item transfers, and explicit development
reset tooling. Use the proposed C++ service while retaining Godot headless for world
simulation until a separate standalone C++ protocol/physics spike is justified.

For server releases: build and stage first; announce maintenance; close logins;
freeze state changes; save and await acknowledgments; notify and disconnect every
player; then stop, migrate, activate, verify, and reopen. Keep a status endpoint
available and rehearse failure recovery. Do not deploy by pulling into live files.

For client releases: publish signed manifests and verified packages; implement
launcher checking, download/resume, staging, integrity validation, atomic activation,
repair, rollback, compatibility gating, and self-update. Preserve user data and
never overwrite a running game. Demonstrate both a successful update and failed
update recovery with packaged builds.
```

## 6. Definition of completion

The rebuild is complete for the first slice when all of the following are true:

- [ ] The original inventory, effect-orientation, HUD, and shutdown problems are resolved or precisely isolated with evidence.
- [ ] The courtyard is protected and ordinary mobs require a deliberate valid attack before aggro.
- [ ] Randomized packs contain three/five members; bosses support solo/two-escort configurations.
- [ ] Spiders, bosses, and the taller hero meet the shared art direction and have proper animation sets.
- [ ] Death, loot, respawn, combat, and character state agree across clients and persist correctly.
- [ ] Broom orientation, mounting, flight, landing, dismounting, and trails meet the requested visual/functional quality.
- [ ] The castle has a separately loaded, accessible, multi-floor interior with working magical stairs and believable PBR materials.
- [ ] Lighting is readable and the scene is not washed out by excessive fog or bloom.
- [ ] All seven spells have a documented asset inventory, layered animated VFX, appropriate sounds, and smooth combat timing.
- [ ] HP, mana, XP, level, target status, cooldowns, and maintenance state update correctly in the UI.
- [ ] Online persistence uses PostgreSQL through the planned service without silent SQLite fallback.
- [ ] Client/server repositories are separate and can be managed/built from the same local workspace.
- [ ] Server releases drain/save/disconnect players before replacement and recover from failed updates.
- [ ] The native launcher detects, verifies, installs, and recovers client updates while preserving user data.
- [ ] The packaged multiplayer slice passes the documented functional, visual, and performance gates.

Anything still represented by a placeholder, unverified download, concept image, or untested architecture proposal remains on the backlog and must be reported as such.
