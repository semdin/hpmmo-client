# HPMMO Defect List — Phase 0 Baseline

**Revision audited:** `697c3350be2ef4c08e6788c5d5b57a6fae848ad6` (master, working tree clean except untracked `plan.md`, `docs/baseline.md`, `docs/baseline-captures/`)
**Date:** 2026-10-03
**Provenance:** every entry below comes from a 45-agent adversarial audit (16 subsystem areas + 5 follow-up sweeps; each area audited, then every cited line independently re-checked by a second agent told to falsify it) plus runtime runs of the existing check harness and windowed baseline captures. The write-up authors re-verified, by hand, the trade handler, the save-key mismatch, the `0.0.0.0` bind, the unsalted hashing, `can_damage`'s lack of zone logic, and the broom orientation (with a headless Godot probe, not just reading code).
**Severity:** *Blocker* = data corruption/loss, security exposure, or a core promise of the game broken. *Major* = clearly wrong behavior a player or operator can hit. *Minor* = small correctness/polish gap. *Cosmetic* = copy, dead code, naming.
**Status:** *Open* = present at this revision. *Fixed at HEAD* = the previously reported problem is already repaired in 697c335. *Needs runtime* = code path is proven by reading, but a two-client or packaged-build run is required for final confirmation.
**Do not paste real credentials anywhere:** items that reference hardcoded passwords deliberately cite only the file/line.

---

## 0. Phase 1 resolution status (2026-10-03)

Phase 1 was implemented on top of this list and adversarially reviewed (5 lenses + falsification pass + runtime re-run; 20 findings, all verified, 1 major and 2 minor addressed, rest nits noted). Gate: `REGRESSION RESULT: 93 checks, 0 failures` headless and windowed (Vulkan Forward+, zero leak/ERROR lines). Evidence: `docs/baseline-captures/phase1-*.png`, `tools/downloads/check-regression.log`.

**Resolved by Phase 1:**
- **B4** → `/api/trade` now returns 503; the handler stays for the Phase 4 rewrite. Not on the network anymore.
- **M15/M16/M17/M18/M20** → data-defined safe zones (`data/json/safe_zones.json` + `scripts/world/safe_zone.gd`); `can_damage` gates every damage path in either direction (verified: no live bypass); reactive aggro with `aggro_mode`/`assist_radius`/`leash_distance`; spawn anchors and full ring formations excluded from zones+buffer; displaced/returning mobs give up and walk home; burn ticks skip protected volumes.
- **M22/M25/M26** → broom rotated 180° at the wrapper (bristles + exhaust now behind the rider; probe-confirmed, regression-covered, captured front/side/rear); mounted casting blocked (Protego allowed) with throttled feedback and held-input drop.
- **M27** (partial) → dismount adds a capsule-clearance query (offsets along the ground normal); residual: clearance samples the pre-dismount spot only (noted for Phase 9).
- **M28** → implemented in full (offensive casts disabled while mounted).
- **M29** → dead remote seat-offset double-write removed; `_update_flight_pose` owns seat height for all players.
- **M49** → monolith respawn is a child `Timer` (no 30 s await); flash is a tween restoring the authored albedo; regression-covered (destroy + respawn checks).
- **M56** → harness resolves the console Godot binary, uses `Start-Process` (native stderr no longer aborts PS 5.1), quotes space-containing args, requires ≥1 check.
- **m22/m23/m24, M14 (guard half)** → monolith albedo drift, `broom_particles`/`broom_mesh` null guards, stale keybind text, `peer_account_map`/`peer_char_data_map` cleanup (also cleared in `disconnect_game`).
- Effect helpers `_muzzle_flash`/`_arc_slash`/`_fire_cone` all guard zero-length directions; unreferenced `bombarda_blast.gd` is gated too.

**Deliberately deferred:** everything else (persistence/auth B3/B5, authority B1/B2/B6, castle, characters/broom redesign, VFX/audio, launcher/updater/deploy, repo split) — owners listed in §6.

---

## 1. Blockers

### B1. No shared world state: every peer simulates its own mobs, HP, deaths, respawns
- **Evidence:** `scripts/world/game_world.gd:269-272` starts `EncounterDirector` on every peer; `scripts/world/encounter_director.gd:13-15` uses `rng.randomize()` per peer; `scripts/autoload/network_manager.gd` has no mob/spawn/health/death RPC (only player state, spell visuals, chat, auth).
- **Repro:** run two clients + dedicated server; each client sees its own pack placement; kill a mob on client A — client B's copy still lives; both clients can kill "the same" pack and each receive XP/loot.
- **Status:** Open. Phase 5 scope.

### B2. Remote spell casts are visual-only — damage is decided entirely by the caster's client
- **Evidence:** `scripts/entities/player.gd:553-567` applies damage locally then broadcasts only `(spell_id, from_pos, dir)`; `scripts/world/game_world.gd:300-303` sets `proj.visual_only = true`; `scripts/spells/spell_projectile.gd:111` gates all damage behind `if not visual_only`.
- **Repro:** two clients; have A cast Stupefy at B's character — B receives a visual projectile and takes no damage, no status.
- **Status:** Open. Phase 5 scope.

### B3. The database API has no authentication or ownership checks and is reachable from outside
- **Evidence:** `server/db_service.py:401` binds `0.0.0.0:8081`; `setup_server.sh:74` opens 8081/tcp in UFW; every data handler trusts raw IDs from the body: list `:229`, create `:238`, load `:285`, save `:301`, trade `:339`. Only `handle_login` (`:197-226`) checks a password, and it issues no session — subsequent calls need nothing.
- **Repro:** with the service running (locally, not the production host), `curl -X POST http://localhost:8081/api/characters/load -d '{"character_id":1}'` returns that character with full inventory; `.../save` overwrites it.
- **Status:** Open. Phase 4 scope (sessions + ownership + private API). Until then the endpoint should not be exposed.

### B4. Trade endpoint mints items and galleons (sender is never debited)
- **Evidence:** `server/db_service.py:373-377` appends each side's offered items to the other's inventory and writes both inventories back (`:380-381`) without removing the offers from the senders; no ownership/quantity/schema validation; negative `galleons` passes the sufficiency check (`:364-371`); `player1_id == player2_id` (self-trade) is accepted (`:339-340,355-356`).
- **Repro (local service):** POST `/api/trade` with `{"player1_id":1,"player2_id":2,"player1_offer":{"galleons":0,"items":[{"id":"potion_health","amount":5}]},"player2_offer":{"galleons":0,"items":[]}}` → both characters end up with the 5 potions; repeat the request to mint more. Self-trade with a galleon offer also mints currency.
- **Status:** **Disabled in Phase 1** — the route returns 503 before any parsing/DB work (verified by the Phase 1 review); the handler remains for the Phase 4 rewrite. Re-enable only with validated, transactional transfers.

### B5. Any connected peer can load any account's character (game protocol)
- **Evidence:** `scripts/autoload/network_manager.gd:398-417` — `rpc_request_select_character` is `@rpc("any_peer")` and calls `DatabaseManager.load_character(char_id)` with the client-supplied id, never comparing against `peer_account_map`.
- **Repro:** connect to the dedicated server with any (even non-logged-in) ENet client and call the RPC with someone else's `char_id`; the server returns the full character payload.
- **Status:** Open. Phase 4/5 scope. A one-line ownership check is the interim guard.

### B6. The Dark Monolith is a per-peer private economy
- **Evidence:** `scripts/world/game_world.gd:257-267` instantiates 4 monoliths on every peer; zero `@rpc`/`.rpc(` under `scripts/entities/`/`scripts/world/`; rewards and loot are granted locally: 850 XP (`dark_monolith.gd:139-140`), 7-8 loot piles (`:153-174`), private 30 s respawn (`:150-151`).
- **Repro:** two clients damage the "same" monolith — each shatters its own copy, each receives 850 XP plus a full loot shower (1,000-3,000 galleons per shatter), repeatable every 30 s per peer.
- **Status:** Open. Phase 5 scope; until then this is the dominant currency faucet (see also M44).

---

## 2. Major defects

### Networking / authority
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M1 | Server persists client-reported HP/level/position with no validation | `network_manager.gd:220` sends them; `:236-240` stores whatever the sender says; `:165-170` writes them into the saved record | Any client can set its own level/hp; Needs runtime (wire-level) |
| M2 | Client chat never reaches other clients | `network_manager.gd:288-298`: `rpc_send_chat` is `any_peer + call_local`, handler only emits a signal; no server re-broadcast (movement/spells do re-broadcast at `:243-246,257-260`) | Two clients: A's chat appears on A and the server only. Needs runtime |
| M3 | A hosting player never broadcasts its own **position** | `network_manager.gd:206-212` — `if multiplayer.is_server(): … return` runs before the 15 Hz broadcast branch | Host in client list appears frozen to others. (Spells from the host DO broadcast — verifier correction.) Needs runtime |
| M4 | Remote animation state (cast/hit/death) is not replicated at all | `player.gd:284-292` — non-local players only infer Running/Idle/Sit from interpolated movement + `is_mounted`; no animation RPC | Remote players never visibly cast or die. Needs runtime |
| M5 | **Online character saves never persist**: client posts a payload keyed `id`, server requires `character_id` → HTTP 400, and the client only logs successes | `scripts/server/db_manager.gd:37-38` posts `char_data` as-is; `network_manager.gd:161-175` passes the load-shaped dict (`char_data.get("id")` at `:174`); `server/db_service.py:301-303` rejects missing `character_id`; failure is silent (`network_manager.gd:172-175` prints only on success) | Log in, play, wait 30 s auto-save, check service log: 400. **Nothing** (not even pos/hp/level) reaches the DB from the game client. Needs runtime to observe, code-proven |
| M5a | "Host/offline" 15 s local JSON save is the only save that works, and it writes `"id": 1` unconditionally | `game_world.gd:115-138`, `:119-120` | Offline slot-2 characters overwrite slot 1 (see M36) |

### Database / auth / transport
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M6 | PostgreSQL is decorative: health can report `postgresql` while every CRUD call writes SQLite | `db_service.py:33-46` opens `PG_CONN` (never queried); every handler calls `get_sqlite()` (`:185,202,230,245,286,319,344`); `/api/health` reports `DB_TYPE` (`:121`) | On a VPS with PG installed: `GET /api/health` → `"db":"postgresql"`, yet accounts/characters live in `pottermetin_server.db`. Needs runtime |
| M7 | On a PG-connected host, `init_db()` skips table creation entirely, so a fresh host fails on first write; SQLite path also silently falls back to the legacy `pottermetin_server.db` whenever `hpmmo_server.db` is absent | `db_service.py:58-59, 20-23` | Fresh deploy without the shipped DB file → SQLite tables never created and/or the legacy file is used. Needs runtime |
| M8 | Character save is fully client-authoritative and reports success for IDs that don't exist | `db_service.py:306-332` accepts arbitrary level/exp/hp/galleons/inventory; UPDATE by id, commits, never checks `cur.rowcount`; untyped `int()`/`pos[0]` can raise ValueError/IndexError → unhandled 500-style failure | POST save with `character_id: 99999` → 200 "saved successfully". Phase 4 scope |
| M9 | Unsalted single-round SHA-256 password storage; 4-character minimum; no rate limiting or lockout on login/register | `db_service.py:50-51, 180, 197-208, 174-195` | Phase 4 scope (switch to Argon2id) |
| M10 | Hardcoded PostgreSQL credentials committed at HEAD **and in history**, duplicated across scripts | `db_service.py:29-30`; `setup_server.sh:57,61,65-66`; `update_server.sh:44-46`; introduced in `cfbe5de` | Rotate credentials during Phase 3/4; history scan required (a `git log -p --all` match set exists) |
| M11 | Credentials and account data travel in cleartext: plain HTTP on 8081, unencrypted ENet, and launcher HTTP without TLS | `db_service.py:401`; `launcher_cpp/src/main.cpp:174-176, 391`; `network_manager.gd:363-372`; legacy launcher `launcher/hpmmo_launcher.py:210` | Phase 4/6 scope; do not expose 8081 publicly |
| M12 | Launcher passes the plaintext password in the game process command line; the legacy Python launcher also prints the whole command (with `--pass`) to its log | `launcher_cpp/src/main.cpp:314-323, 331`; `launcher/hpmmo_launcher.py:248-255`; password also retained in `g_AuthedPass` for the launcher's lifetime (`main.cpp:49,550,593`) | Password visible in the OS process list. Phase 4/7 (one-time ticket) |
| M13 | Play button launches the game even when authentication never succeeded | `launcher_cpp/src/main.cpp:483-486` (no `WS_DISABLED`), `:549-556` (click always calls `LaunchGame`); `:598` enable path is unused | Phase 7 scope; the game then authenticates/rejects inside itself |
| M14 | No sessions, expiry, logout/revocation or duplicate-login policy; and the disconnect cleanup has a guard bug that leaves stale `peer_account_map` entries for peers that logged in but never selected a character | `network_manager.gd:370` (in-memory only), `:150-153` (`erase` nested inside `if peer_char_data_map.has(id)`) | Phase 4 scope; the guard bug is a quick Phase 1/5 fix |

### Encounters / safe zone (Phase 1 targets)
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M15 | **No protected zone exists anywhere** — no spawn, navigation, targeting, or damage exclusion for the NPC/training courtyard | `combat_rules.gd:4-24` has only faction checks; `player.gd:592-599`; `encounter_director.gd:36-55` only avoids spawning within 16 m of a player | Walk a pack toward the courtyard — combat works everywhere, including on NPCs' doorstep. Phase 1 core work |
| M16 | Ordinary mobs aggro on proximity alone (0.35 s scan, radius 9/12), so walking near a pack starts combat | `mob_base.gd:141-148`; `encounter_director.gd:78` overrides per-scene radii | Stand near a pack → pulled. Phase 1: reactive aggro |
| M17 | Packs can chase into the courtyard: leash 26 m vs zone corners ~27-29 m from the player spawn, and the courtyard fence has **no collision** | `mob_base.gd:181`; `encounter_director.gd:17` (zone at (17,-18)); `game_world.gd:104` (spawn 0,0.5,5); `world_builder.gd:452-471` fence is meshes only; player respawn point is the unprotected courtyard center (`player.gd:625`) | Needs runtime chase test; geometry supports the risk |
| M18 | `aggro_mode`, `assist_radius`, `leash_distance` don't exist; pack assist is unlimited-range by `pack_id` | `mob_base.gd:172-175` (no distance check); zero repo hits for the three fields outside plan.md | Phase 1: introduce the fields |
| M19 | Rewards are client-local and repeatable across clients (XP to last-hit killer, free-for-all loot, once per mob life **per client**) | `mob_base.gd:307-318`; no reward RPC anywhere | Phase 5 scope; blocks "receive rewards once" journey step online |
| M20 | Boss slam AoE damages every player within 5.5 m of impact (not just the target) and Incendio burn ticks keep crediting the original caster — both matter for boundary rules | `mob_base.gd:250-252`, `:283-286` | Fold into Phase 1 boundary enforcement + Phase 5 validation |

### Characters / broom (Phase 1 + 9 targets)
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M21 | Rendered body exceeds its collision capsule: bind-pose crown 2.203 m (hat 2.716 m) vs capsule height 1.8 m at scale 1.0 — doors/camera/targeting assume the capsule | `player.tscn:6-8, 60`; GLB measured by audit (feet y=0) | Open; Phase 9 redesign, but note doorway/camera consequences now |
| M22 | Cast animations truncated at 0.35 s vs clip lengths 0.933-2.1 s, then overwritten by run/idle | `player.gd:579` (`create_timer(0.35)` clears `is_casting_anim`); clips `Spellcast_Shoot` 0.933 s, `Spellcast_Raise` 2.1 s | Visual truncation every cast. Needs runtime confirmation |
| M23 | Player clips are never set to loop (mobs explicitly set `loop_mode`; the player never does) — imported clips may freeze after one cycle | `player.gd` (no `loop_mode` call); `mob_base.gd:65-68` sets it for the same import style | Needs runtime: watch Idle/Running_A for looping |
| M24 | Mounted state is the generic 3.6 s `Sit_Chair_Idle` on a primitive cylinder broom; no `SeatSocket`/`MountRoot`; rider height is a hard-coded blend | `player.gd:346-348, 359-361, 435`; `player.tscn:77-88`; grep for seat/socket returns nothing outside plan.md | Phase 9 scope |
| M25 | **Broom is reversed 180°: brush end and exhaust point forward** (probe-confirmed, not just read from code) | `player.tscn:78` basis maps the cylinder's +Y to **-Z**; a headless Godot probe of the real scene shows Bristles at Visuals-space `(0, 0.575, +0.949)` and `BroomParticles` at `(0, 0.56, +1.249)`; the rider faces +Z (`player.gd:341`, wizard.glb front = +Z) | Mount, move forward, observe bristles leading. Phase 1 fix: rotate `BroomMesh` 180° about the axis that keeps the bristle tilt, then re-capture |
| M26 | Flight exhaust emits ~1.25 m **in front of** the rider, not behind; it is also a static downward puff, not a speed-driven trail | `player.tscn:87`; `player.gd:106-113`; no Line3D/ribbon/trail anywhere | Phase 1 (flip with M25) / Phase 9 (real trail) |
| M27 | Dismount geometry check is a single 3 m downward ray (normal > 0.7): no capsule/ceiling/wall clearance, no landing reposition | `player.gd:401-407, 385-399` | Dismount under a low ceiling/prop. Needs runtime |
| M28 | Casting is allowed while mounted, contradicting plan §3.3 ("disable offensive casting while mounted for this slice") | `player.gd:479-490` (no `is_mounted` branch); `:549-564` fires normally | Phase 1 policy change |
| M29 | Remote riders get conflicting seat offsets (`visuals.position.y = 0.55` written by the remote branch, overwritten to ~0.15 every frame) | `player.gd:275` vs `:227, 435` | Two-client visual check. Needs runtime |

### Castle / map
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M30 | No vertical circulation anywhere: single walkable storey; the word "stair" exists only in plan.md; all 5 towers are solid colliders | `castle_builder.gd:26,47` (one floor + one ceiling per volume), `:224-232` tower colliders; `docs/GAMEPLAY_UPDATE.md:45` admits it | Walk the castle: hall + 2 wings on one level. Phase 8 scope |
| M31 | Masonry is albedo-only: no texture sampling, no normal/roughness/AO, constant roughness 0.86 | `assets/textures/masonry.gdshader` (26 lines, outputs ALBEDO+ROUGHNESS only) | Phase 10 scope |
| M32 | Texel density varies ~17x between objects sharing one material (constant `uv1_scale = 6` against per-face 0-1 box UVs), and windows are opaque appliqués on both wall faces | `material_kit.gd:39`; `castle_builder.gd:40-41, 188-199` | Visible stretched brick. Phase 10 |
| M33 | All 44 environment palette textures are byte-identical 1024² flat swatches (1 distinct MD5), and the 8 baked 256² castle textures are referenced by nothing | MD5 sweep of `assets/models/environment/*_texture.png`; only `masonry.gdshader` preloads exist in code | Phase 2/10 |
| M34 | Static batching folds all same-material boxes into one MultiMesh, foreclosing per-room culling and per-instance changes | `static_batch.gd:25-39` | Perf architecture note for Phase 8/10 |
| M35 | No return-to-menu or quit affordance inside the world; the only path back is character-select's Logout, and world teardown is implicit | `game_world.gd` has no `change_scene`/quit; `character_select.gd:347` is the only transition back | Phase 13 scope; needed for the journey's "return to menu" step |
| M36 | Offline persistence hardcodes character id 1 into one file — slot-2 offline characters overwrite/lose progress | `game_world.gd:119-120`; `db_manager.gd:8,77-81` | Create 2 offline characters, play slot 2, relog. Phase 4/5 |

### Spells / VFX / audio (Phase 12 targets, but silent casting is felt now)
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M37 | **Every spell is silent**: `AudioManager.play_spell` (all 7 spell tones) has zero call sites; the HUD's cast hook is literally `pass` | `audio_manager.gd:70-90`; `hud.gd:185-186`; no audio files exist repo-wide | Cast anything — no sound. Phase 12 (or a cheap Phase 1 wire-up) |
| M38 | Spell VFX are untextured unshaded primitives (spheres/tori/cylinders + tween flashes); `skill_fx.gd` has 0 texture references; the only textures in spell FX are the two shared stills via `particle_kit.gd` | `skill_fx.gd` (275 lines); `particle_kit.gd:11` | Phase 12 scope; capture evidence in `docs/baseline-captures/` |
| M39 | No flipbooks/atlases/animated textures exist anywhere; `assets/vfx` holds 2 still 512² PNGs (Kenney, CC0) duplicated under `tools/downloads/particles` | inventory + md5 sweep | Phase 12 scope |
| M40 | Remote players' spells replay as generic projectiles for any `spell_id`, including Incendio (and Protego is not broadcast at all, so remote Protego never appears) | `game_world.gd:295-303`; `player.gd:549-550` (no Protego broadcast), `:559,567` | Two-client visual mismatch. Phase 5 presentation scope |
| M41 | Broom exhaust is a static 55-quad flame puff; no trail geometry exists | `player.gd:105-113`; regression test locks in `QuadMesh` (`test_scenario.gd:151`) | Phase 9 |
| M42 | No spatial audio, reverb, buses, volume controls, music or ambience; 8 flat `AudioStreamPlayer` voices on the built-in Master bus only | `audio_manager.gd:15-16`; no `default_bus_layout.tres`; zero `.wav/.ogg/.mp3` files | Phase 12.5 scope |

### Data layer / quests (Phase 4/5 + Phase 2 targets)
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M43 | House traits advertised in UI are dead data: `houses.json` `starting_bonus` (crit, life leech, damage reduction…) has zero consumers; player.gd hardcodes a numeric subset; README contradicts the JSON for all 4 houses | `houses.json:8,16,32`; `character_select.gd:280`; `player.gd:159-163,423,500-501,544-547`; `README.md:19-22` | Pick a house and compare; traits don't apply |
| M44 | Health potion tooltip says +180 HP, clicking heals +150 (hardcoded); item JSON stat vocabulary (`heal_hp`, `bonus_hp`, `mount_speed`, `base_multiplier`, `rarity`…) is entirely unconsumed | `items.json:63-64` vs `inventory_ui.gd:67`; grep for the 7 fields matches only the JSON | Visible per-use |
| M45 | Spell balance/status JSON fields (stun/burn duration, cone angle, knockback) are unconsumed; `mob_base.gd` hardcodes them, so HUD tooltips can diverge from behavior (e.g. stupefy 1.8 s vs tooltip 2.0 s) | `game_data.gd:123-124` (ultimate range/speed dropped by JSON); `mob_base.gd:280-284`; `spells.json:17,79-88` | Needs runtime to see stun duration vs tooltip |
| M46 | `data/json/quests.json` (3 quests) is dead content; QuestManager runs a divergent hardcoded 6-quest chain; quest progress is **install-global** (`user://hpmmo_save.json`, no character/account key); completions are never stored with the character; deleting the local file re-grants all rewards | `game_data.gd:264-266`; `quest_manager.gd:9-58, 148-166`; `network_manager.gd:220` | Two characters on one machine share progress. Phase 4/5 + sweep evidence |
| M47 | `QuestManager.load_progress` does `var d: Dictionary = JSON.parse_string(...)` with no null/parse guard — a malformed/empty save triggers a Godot typed-assignment error and silently resets quest state (same defect class as the previously reported inventory bug) | `quest_manager.gd:160` | Corrupt/empty `user://hpmmo_save.json`, start game |
| M48 | Unbounded galleon faucet: 4 monoliths × per-peer copies × 1,000-3,000 galleons per 30 s shatter, plus ~1,300 from summons, versus a single 60,850-galleon sink (Ollivander, whose material requirements are display-only and never consumed) | `dark_monolith.gd:139-185`; `game_data.gd:132-143`; `ollivander_ui.gd:63,73` | Phase 5 economy scope |
| M49 | `dark_monolith.gd` awaits (30 s respawn timer `:150-151`; 0.08 s flash `:83`) without `is_instance_valid` guards; a scene teardown during the timer resumes into freed nodes | `dark_monolith.gd:150-151,176-185` | Phase 1 cleanup hygiene / Phase 8 |

### Launcher / deployment / repository (Phase 3/6/7 targets)
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M50 | The "distributable" launcher requires the developer's Godot editor: it launches `godot.exe` + `.tscn` with a hardcoded `C:\Users\mehme\…` candidate path; no `.pck`, no `export_presets.cfg` exists anywhere | `launcher_cpp/src/main.cpp:291-311, 319-331` | Cannot ship to a machine without the editor + project tree |
| M51 | Server release tarball packages client artifacts, the account DB, logs, and a nested copy of itself (packages the whole repo root) | `package_server.bat:7`; the actual `hpmmo_server.tar.gz` (75.6 MB, 1,537 entries) contains `server/pottermetin_server.db`, `HPMMO_Launcher.exe` ×2, `.godot` cache, `client_config.json`, `plan.md` | Phase 3/6 scope |
| M52 | Deployment updates live files in place: `git pull`/tar extraction into `$HOME/hpmmo/game` after stopping services, then schema re-apply and restart — no build, staging, drain, save barrier, verification, or rollback | `update_server.sh:18-62` | Phase 6 scope |
| M53 | No updater exists in either launcher; the advertised patch URL (`server/version.json:7` → `/patch/latest.zip`) is dead (no `server/patches/` directory ships) | `main.cpp` (no download/hash/manifest code); `db_service.py:129-141` | Phase 7 scope |
| M54 | Repo hygiene: hardcoded DB credentials in tracked history; `HPMMO_Launcher.exe`, `client_config.json` (tracked despite `.gitignore`), and `server/pottermetin_server.db` are committed; `.git` holds 442 MiB of unreachable blobs (two >150 MiB) making `.git` 376 MB vs 36.8 MiB of content; no CI, lockfile, LFS config or export presets | `git ls-files`; `git fsck --unreachable`; sweep evidence | Phase 3 scope; credential rotation required |
| M55 | Engine/toolchain not pinned on the client pipeline (any `godot.exe` from PATH is accepted; `project.godot` records "4.7" only) and the server install downloads Godot 4.7.2 without a checksum and never refreshes an existing binary | `play.bat:4`; launcher search paths; `setup_server.sh:26-32` | Phase 3/6 |

### Tooling
| ID | Defect | Evidence | Repro / status |
| --- | --- | --- | --- |
| M56 | `tools/run_game_checks.ps1` fails on this machine **as documented**: the PATH `godot.exe` is a GUI-subsystem binary (PE subsystem 2, confirmed), so PowerShell never waits, `$LASTEXITCODE` stays empty, and line 12 throws "Godot import failed." The regression itself is green when the harness is pointed at the console companion (`-GodotPath …_console.exe`): **72 checks, 0 failures** | `tools/run_game_checks.ps1:9-12`; verified: `godot --version` leaves `$LASTEXITCODE` empty; console exe run passes | Phase 1 chore: use `Start-Process -Wait`, or default the script to the console exe |

---

## 3. Minor / cosmetic (grouped)

| ID | Defect | Evidence |
| --- | --- | --- |
| m1 | `/patch/` edge cases: empty-name path returns 404 only because no patches dir exists; on Windows a drive-letter basename discards the patches dir | `db_service.py:129-141` |
| m2 | Character-create reports **every** `IntegrityError` as "name already taken"; SQLite foreign keys not enforced | `db_service.py:280-282, 238` |
| m3 | `GET /api/version` fallback still says "PotterMetin MMO"; version identifiers disagree across artifacts (launcher hardcodes "v2.0.0", files say 1.1.0) | `db_service.py:128`; `main.cpp:692`; `version.json` |
| m4 | No request-size limit: `rfile.read(Content-Length)` is unbounded on a single-threaded server (DoS) | `db_service.py:147-148` |
| m5 | Launcher health check counts HTTP 400/404 as ONLINE, and the UDP probe returns "online" when `sendto` merely succeeds | `main.cpp:270, 235-260, 275-278` |
| m6 | `NetworkManager` disconnect path leaves stale `peer_account_map` for logged-in-but-unselected peers (see M14) | `network_manager.gd:150-153` |
| m7 | Client "SQLite / Local JSON" labels and several comments assert PostgreSQL persistence the code does not deliver; no client code ever opens SQLite | `db_manager.gd:4,74`; `network_manager.gd:205,301` |
| m8 | Legal-window issue: open bag shows stale Galleons after a **failed** refine (success path does emit), bag stays open on death, potion heal/mana spend produce no floating text, grid can double-build rows in one frame | `ollivander_ui.gd:81`; `inventory_ui.gd:27-28,33-34,64-79` |
| m9 | No hit-interrupt feedback and no cast-progress indicator; damage does not interrupt a cast | `player.gd:497,603`; `hud.gd:131-140,185-186` |
| m10 | Ollivander's "Required" material is display-only (never checked/consumed) | `ollivander_ui.gd:63,73` |
| m11 | Nameplate at y=2.3 sits inside the hat silhouette; floating combat text at +2.2 m too | `player.tscn:96-98`; `player.gd:740` |
| m12 | `WandTipMarker` and `WandAuraParticles` sit at z=-0.6 behind the +Z-facing model and are dead (spells spawn from body+1.2 m) | `player.tscn:62-73`; `player.gd:509` |
| m13 | 4 of 5 character GLBs (16.8 MB) unreferenced; 33 of 44 environment GLBs unreferenced; duplicate texture files; all unimported-for-nothing weight shipped | `assets/models/characters`, `assets/models/environment` |
| m14 | `model_factory.gd` (355 lines) is dead code whose header claims it is called; second cruder procedural monster builder inside | `model_factory.gd:5-7,175-335` |
| m15 | Stale Ranged mobs play a melee clip while firing; spider collision sphere (r=1.0) is smaller than its ~1.5 m leg span | `mob_base.gd:198-201`; `mob_acromantula.tscn:7-8` |
| m16 | Dead VFX code: `play_stun_stars`, local Protego cast FX branch, `bombarda_explosion.tscn` + `bombarda_blast.gd`, `bombarda` cone branch reachable only via remote replay | `skill_fx.gd:29-30,48-51,65-87`; grep unreferenced |
| m17 | Kenney particle PNGs duplicated in two `res://` trees (imported twice); both licenses byte-identical | `assets/vfx` + `tools/downloads/particles` |
| m18 | AudioManager cache key omits volume; voice stealing always reuses player 0; first-play tone synthesis is synchronous (up to 17,640 loop iterations); no stop/reset on scene changes | `audio_manager.gd:20-23,29-49,65-68` |
| m19 | Quest polish: golden marker shows on every NPC unconditionally; "broom" quest completes on foot (zone entry only); zone-transition-only visit trigger can stall the last quest; duplicate save write per completion; NPC says "click to talk" but only F works; reward galleons bypass loot feedback | `npc.gd:58-73,78`; `mmorpg_overlay.gd:248-256`; `quest_manager.gd:135-137` |
| m20 | Partial pack kills stall respawn indefinitely; packed member RETURNs are invulnerable and heal to full; only the pack anchor is probe-validated (members can land in geometry on the 3.1 ring) | `encounter_director.gd:109-113,45-65`; `mob_base.gd:273,129-131` |
| m21 | Encounter director overrides per-scene `aggro_radius`, making exported mob tuning dead; ranged-escort branch unreachable | `encounter_director.gd:78,95-98` |
| m22 | `mat_elder_core` exists only in code (not in `items.json`); monolith `_flash_red` restores a hardcoded color and permanently shifts the monolith's authored albedo after first hit | `dark_monolith.gd:82-85,164-166` |
| m23 | `BroomParticles` dereferenced without null guard in `toggle_broom_mount` (and in `_die`) | `player.gd:398,618` |
| m24 | On-screen keybind text says "Shift or Ctrl to mount/dismount" but Ctrl is now descend | `game_data.gd:180,291-292` |
| m25 | Pre-existing `CastleFront` GLB cluster is instantiated in `game_world.tscn` then freed at startup; dead duplicate character-select UI in `main_menu.gd`; capture harness brittle (hardcoded pack indices, writes to `res://`) | `game_world.gd:29-31`; `main_menu.gd:206-311`; `capture_world.gd:29-31,51` |
| m26 | Default server endpoint (live VPS IP) hardcoded in scene + network manager; location labels hardcoded | `main_menu.tscn:217`; `network_manager.gd:112`; `mmorpg_overlay.gd:240-246` |
| m27 | KayKit asset family has a one-line blanket credit with no per-file license/URL/receipt; only `monsters/License.txt` names a pack (and it says "Ultimate Platformer Pack") | `ASSET_CREDITS.md:8`; `assets/models/monsters/License.txt` |
| m28 | `docs/baseline-captures/*.log` are gitignored by `*.log` (need `git add -f` or an allowlist rule); `plan.md` and the Phase 0 docs are untracked | `.gitignore:29`; `git check-ignore` verified |
| m29 | 21 non-deforming IK/control bones imported into the Skeleton3D; 7 of 76 clips are zero-duration poses; `Spellcast_Long` never played | GLB inspection |

---

## 4. Previously reported regressions — current status

| Reported issue (plan §2 closing paragraph) | Status at 697c335 | Evidence |
| --- | --- | --- |
| Typed inventory restoration error | **Fixed** — `restore_character` validates each entry into the typed array; malformed entries are skipped; regression covers JSON restore incl. malformed | `player.gd:441-470`; verifier refuted presence; `test_scenario.gd` inventory checks PASS |
| Collinear `look_at` directions | **Mitigated** — `safe_up()` applied at every effect `look_at` (`skill_fx.gd:134,186`, `spell_projectile.gd:82`); entry points guard zero vectors; residual: helper bodies themselves unguarded for `dir==0` | `combat_rules.gd:23-24`; sweep evidence |
| HUD stat changes | **Working** — bars update on damage/heal/spend/regen/XP/level-up; spell cooldowns render; death invalidates casts | verifier-confirmed; regression PASS |
| Scene/VFX cleanup | **Working in tested paths** — `queue_free`-based cleanup; nothing parented to `get_tree().root`; 72-check run shows 0 leaked instances | regression logs |
| Renderer allocations at shutdown | **Not reproduced** — windowed (Vulkan Forward+) and verbose windowed runs of `test_scenario` show no leak/RID/orphan lines; only benign Vulkan-loader and RGB8→RGBA8 import warnings. Residual: packaged/launcher run and repeated map transitions not exercised | `docs/baseline-captures/run1b-test-scenario-verbose.log` |
| Backward broom/rider | **Rider fixed in 697c335** (Ry180 wrapper removed; rider faces travel). **Broom itself is reversed at HEAD** — brush leads (M25, probe-confirmed). Manual front/side/rear capture still required for the Phase 1 exit check | probe + captures |
| Trade endpoint | **Resolved in Phase 1** — route returns 503; handler kept for Phase 4 | B4 |

---

## 5. Not reproducible without more than one machine/client (documented per Phase 0 exit check)

1. Two-client behaviors: mob desync (B1), visual-only spells (B2), chat one-way (M2), host position silence (M3), remote animation gaps (M4), remote rider seat offset (M29), remote spell mismatch (M40).
2. Live VPS state: which backend `/api/health` reports, whether the deployed revision matches 697c335, whether `server/patches/latest.zip` exists (M53), and whether the deployed SQLite file has rows (M6/M7).
3. Packaged-client behavior: launcher launch on a clean machine (M50), updater (absent), Windows process-list exposure of `--pass` (M12).
4. Phase 0 task-8 metrics (frame-time percentiles, triangles, overdraw, RAM/VRAM, server tick, network traffic) — not instrumented anywhere; only fps/draw-calls from the capture harness exist (`docs/baseline-captures/run2-capture-world.log`).
5. Spell-shape captures: `capture_world.tscn` never casts spells; needs a dedicated capture or manual session.
6. Audio audibility/quality checks (all silent-spell findings are static call-graph evidence, consistent with zero audio files).

## 6. Suggested Phase 1 cut (per plan Phase 1 scope)

Delivered in Phase 1 (see §0): safe zones + reactive aggro + chase containment (M15-M18, M20), broom orientation (M25/M26), mounted-cast policy (M28), peer-map cleanup guard (M14), monolith timer guards (M49), harness fix (M56), trade disable (B4), m22-m24 polish. Remaining: M23 (clip loop modes) needs a live visual check; the rest defer to their owning phases.
Defer (owner phase in parentheses): persistence/auth/transport (4), authority/rewards (5), castle/maps (8/10), character/broom redesign (9), VFX/audio (12), data/quests wiring (4/5), launcher/updater/deploy (6/7), repo split & credential rotation (3).
