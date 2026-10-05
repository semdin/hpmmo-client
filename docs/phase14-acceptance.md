# HPMMO Phase 14 acceptance report

**Phase:** 14 — Integrated performance, reliability and multiplayer QA (`client/docs/plan.md`).
**Date:** 2026-10-05.
**Frozen tree:** every measurement below was taken on one tree, frozen for the whole phase.
Nothing was committed; all new files are in the working tree (listed in §9).

| Item | Value |
| --- | --- |
| Client revision **measured** | `67b9f96` (working tree clean at the start of the phase) |
| Server revision **measured** | `8190681` (clean) |
| Client repo | `hpmmo-client` — `C:\Users\mehme\Desktop\sem\projects\game\client` |
| Server repo | `hpmmo-server` — `C:\Users\mehme\Desktop\sem\projects\game\server` |
| Engine | Godot `4.7.2.stable.official.ed1daf0bf` (console companion binary, `Godot_v4.7.2-stable_win64_console.exe`) |
| Renderer | Vulkan `1.4.348`, Forward+ |
| Protocol | `hpmmo-proto/6` (`HPProtocol.PROTOCOL_VERSION`) |

**The tree moved while this report was being written.** Every number below was
measured on the pair above; after the measurements, a parallel commit landed on
both repositories — client `9733e21` / server `499ed46`, *"the authority now has
interior collision, so players stop falling through the castle"*. That is
precisely the failure signature the journey hit inside the castle (§4.1), so the
interior half of the journey and the staircase result (D14-7) should be
re-measured on the new HEAD before anyone treats them as final. The two
corrective fixes this phase made (`launcher_cpp/src/updater.cpp`,
`scripts/ui/main_menu.gd`) are uncommitted working-tree changes on top of it, and
the Phase 14 harness files themselves were picked up by the owner's commits while
the phase was running (no commit was made from here).

## 1. Target hardware and settings

Recorded from the live machine (not copied from `docs/baseline.md`), matching it:

| Component | Value |
| --- | --- |
| CPU | Intel Core Ultra 7 255H, 16 cores / 16 logical processors |
| GPU | Intel(R) Graphics (integrated), driver `32.0.101.8826` (2026-05-29), adapter RAM reported 2,147,479,552 B (shared) |
| System RAM | 33,197,715,456 B (~31 GiB) |
| OS | Windows 11 Pro, build `10.0.26300` |
| Desktop | 1920x1200; the game window ran at its authored 1280x720 |
| Graphics settings | **low preset**, selected automatically by `scripts/world/quality_preset.gd` (Intel adapter ⇒ `low`): no sun shadows, no glow, no SSAO, MSAA off (the project's `msaa_3d=2` is overridden to 0 by the preset), vegetation 0.55, particles 0.5 |

The plan's target is "stable 30 FPS minimum on the agreed low preset, with 60 where
hardware permits". The machine is the plan's stated low-end class, so this is the
relevant profile. All frame-time numbers in §3 are on that preset at 1280x720.

## 2. Test matrix — what ran, and what did not

Every row was run on the frozen tree. "Not covered" rows are stated as not covered.

| Category | Scenario | Suite / probe | Result |
| --- | --- | --- | --- |
| Regression | Inventory decoding, vertical/zero-vector effects, all spell casts, world enter/exit, verbose shutdown | `tools/run_game_checks.ps1` (`test_scenario.tscn`) | `REGRESSION RESULT: 93 checks, 0 failures` |
| Protected area | Boundary crossing, delayed projectile, AoE, burn, knockback, boss chase, spawn sampling, dummy exception | `server/tests/multiplayer_sim.py` (protection) + `encounters_sim.py` (safe-zone placement) | `39 checks, 0 failures` / see §2.1 for the encounter line |
| Encounters | Reactive aggro, pack assistance, 3/5 members, solo/escorted boss, death, corpse cleanup, reward once, respawn | `server/tests/encounters_sim.py` | see §2.1 |
| Combat | Low mana, queued inputs, interruption, shield, line of sight, fast projectile, status expiration, death during windup | `client/scenes/test/phase9_regression.tscn` + `phase12_regression.tscn` + `test_scenario.tscn` (spell/status/cooldown assertions) | 93 / 53 / 470 checks, 0 failures |
| Character/flight | Animation blends, orientation, mount spam, wall/ceiling clearance, landing, remote mounted state | `tools/run_phase9_checks.ps1` | `PHASE9 RESULT: 53 checks, 0 failures` |
| Castle | Floor routes, moving stairs, doorway clearance, camera clipping, map transfer, reconnect during transfer | `tools/run_phase14_gates.ps1` (castle), `server/tests/staircase_sim.py`, `maps_sim.py` | walkthrough 87/0; see §2.1 for the other two |
| Persistence | Ownership, save/reload, concurrent reward/trade, stale revisions, outage, dev reset | `server/tests/integration_api.py`, extended by the journey (§4) | `INTEGRATION RESULT: 68 checks, 0 failures`; **journey logout fails — see D14-1** |
| Deployment | Countdown, login closure, save barrier, disconnect barrier, failed rollout, rollback, interrupted deploy | `server/tests/deploy_rehearsal.py` | `DEPLOY RESULT: 236 checks, 0 failures` |
| Launcher | Old install, tamper rejection, interrupted download, disk full, repair, running-game lock, incompatible version | `client/tools/release/test_updater.py` | `UPDATER RESULT: 100 checks, 0 failures` |
| Multiplayer | Two-client correctness (local/broadband/mobile/awful), then 4/16-player load | `multiplayer_sim.py` per profile, `phase14_tick.py` (load) | see §2.1 and §5 |
| Presentation | Neutral/final lighting comparison, art consistency, placeholder audit, spell visibility, audio mix | `phase10`/`phase12` check scenes + `phase12-*.png`, `phase13-*.png` captures | `PHASE10 RESULT: 120 checks, 0 failures`, `PHASE12 RESULT: 470 checks, 0 failures` |

### 2.1 The suites, with their result lines

| Suite | Command | Result line |
| --- | --- | --- |
| Client regression | `run_game_checks.ps1` | `REGRESSION RESULT: 93 checks, 0 failures` |
| Phase 9 (character/flight) | `run_phase9_checks.ps1` | `PHASE9 RESULT: 53 checks, 0 failures` |
| Phase 10 (castle/environment) | `run_phase10_checks.ps1` | `PHASE10 RESULT: 120 checks, 0 failures` |
| Phase 12 (spell VFX/audio) | `run_phase12_checks.ps1` | `PHASE12 RESULT: 470 checks, 0 failures` |
| Phase 13 (HUD/feedback) | `run_phase13_checks.ps1` | `PHASE13 RESULT: 111 checks, 0 failures` |
| Castle walkthrough | `castle_walkthrough.tscn` | `WALKTHROUGH RESULT: 87 checks, 0 failures` |
| Multiplayer (local) | `multiplayer_sim.py` | `MULTIPLAYER RESULT: 39 checks, 0 failures` |
| Multiplayer (awful) | `multiplayer_sim.py --profile awful` | `MULTIPLAYER RESULT: 39 checks, 0 failures` |
| Multiplayer (mobile) | `multiplayer_sim.py --profile mobile` | `39 checks, 1 failure` — twice, different check each time (D14-7) |
| Maps / transfer | `maps_sim.py` | `MAPS RESULT: 94 checks, 0 failures` |
| Encounters | `encounters_sim.py` | `ENCOUNTERS RESULT: 102 checks, 0 failures` (quiet machine; one contention flake on the first, loaded run) |
| Maintenance | `maintenance_sim.py` | `MAINTENANCE RESULT: 56 checks, 0 failures` |
| Staircase | `staircase_sim.py` | `STAIRCASE RESULT: 47 checks, 7 failures` — reproducible on a quiet machine (D14-7) |
| Persistence (service) | `integration_api.py` | `INTEGRATION RESULT: 68 checks, 0 failures` |
| End-to-end smoke | `smoke_end_to_end.py` | `SMOKE RESULT: 11 checks, 0 failures` |
| Deployment rehearsal | `deploy_rehearsal.py` | `DEPLOY RESULT: 236 checks, 0 failures` |
| Launcher / release pipeline | `tools/release/test_updater.py` | `UPDATER RESULT: 100 checks, 0 failures` |

### 2.2 Rows that are still not covered

* **Audio mix** and **art consistency by eye** — no automated check; not judged
  visually in this phase either (§10 item 1).
* **Camera clipping in the castle** — the walkthrough asserts route clearance
  rays, not the rendered camera.
* **Presentation "no placeholder spider/hero"** — no automated visual check; the
  manifest's status fields are the only evidence (`assets/manifest.json`).
* The staircase gate is **failing** (D14-7), so its row is covered by a probe
  that does not currently pass; it is reported as failing rather than as covered.

## 3. Performance on the target profile

Method: `scripts/test/phase14_perf.gd` — six fixed camera stops (the Phase 10
route, so the numbers compare with the greybox capture), a two-pass combat stop
driving the real spell path (`SkillFX.play_cast/play_impact` +
`SimAuthority.apply_spell_hit`) on a live pack, and an animation A/B on the
courtyard stop. Each stop samples **every rendered frame for 6 s** and reports
percentiles of the frame time, plus the engine's own monitors.

`p50`/`p95`/`p99` are frame times in milliseconds; `fps(p50)` is 1/p50. The run
was windowed on the Intel iGPU with **vsync disabled** (otherwise every sample
reads 16.67 ms and hides the cost). Raw logs:
`client/tools/downloads/phase14-perf-novsync.jsonl`.

| Stop | p50 | p95 | p99 | max | draw calls | primitives | tex MiB | fps(p50) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| out-approach | 13.33 | 13.97 | 14.32 | 15.02 | 1166 | 1,853,278 | 488 | 75 |
| out-courtyard | 13.95 | 15.00 | 15.39 | 15.72 | 1490 | 2,367,861 | 488 | 72 |
| out-terrain | 10.61 | 11.67 | 11.95 | 12.45 | 598 | 1,079,631 | 488 | 94 |
| in-great-hall | 15.00 | 15.28 | 16.89 | 18.23 | 654 | 805,436 | 629 | 67 |
| in-stair-hall | 12.96 | 12.96 | 12.96 | 13.52 | 251 | 340,288 | 629 | 77 |
| in-library | 10.42 | 10.61 | 10.79 | 11.69 | 267 | 362,088 | 629 | 96 |
| combat-1 | 13.89 | 15.20 | 21.87 | **142.90** | 1685 | 2,552,814 | 725 | 72 |
| combat-2 | 13.89 | 14.87 | 21.58 | **116.31** | 1685 | 2,552,814 | 725 | 72 |
| anim-on | 14.29 | 14.81 | 15.38 | 16.31 | 1692 | 2,661,583 | 633 | 70 |
| anim-off | 13.89 | 13.89 | 14.29 | 15.63 | 1692 | 2,662,315 | 633 | 72 |

**Gate verdict.** p95 is ≤ 15.4 ms everywhere and p50 ≥ 66 FPS, so the 30 FPS
floor is met with a wide margin and the 60 FPS target is met in every stop.
**The exception is the combat p99/max**: both passes recorded a ~116-143 ms
frame inside the 6 s window (p99 21.6-21.9 ms, i.e. the top ~3 frames). A single
120 ms hitch is a visible stutter, not a sustained drop; it is filed as D14-2.

Separated costs (same stops):

| Cost | Value | How |
| --- | --- | --- |
| Physics | 2.4-3.8 ms per frame (`physics_ms`) | `Performance.TIME_PHYSICS_PROCESS`; 24-26 active 3D bodies, 24-26 collision pairs |
| Navigation | 0.004-0.013 ms per frame; **0 regions, 0 polygons, 0 agents** | `Performance.TIME_NAVIGATION_PROCESS` / `NAVIGATION_*` — no navigation mesh is loaded anywhere, matching the standing residue (mobs steer, they do not path) |
| Animation | **≈0.40 ms/frame** (p50 14.29 on vs 13.89 off, 45 AnimationPlayers + 1 AnimationTree disabled for the control) | A/B on the courtyard stop, same camera and scene |
| Script (`TIME_PROCESS`) | 15.7-16.2 ms | engine monitor; see the caveat below |
| Dynamic lights in scene | 44 outdoors, 96 with the interior loaded | count of visible Omni/Spot lights in the world tree |
| Transparent overdraw | 76-79% outdoor, ~99.9% interior, by the Phase 10 debug-draw index | relative index (fraction of sampled pixels lit by the overdraw debug mode), not a physical number |
| Texture memory | 488 MiB outdoor → 629 MiB interior → 725 MiB during combat | `RENDER_TEXTURE_MEM_USED` |
| Video memory | 690 → 838 → 950 MiB | `RENDER_VIDEO_MEM_USED` |

Caveat, stated rather than hidden: the `TIME_PROCESS` monitor reads ~16 ms in
every stop, including stops whose end-to-end frame time is 10.6 ms — it is not a
usable "script cost" number on this build, so no conclusion is drawn from it.

Vsync-on reference (a player's default): every stop reads p50 = 16.666 ms; only
the combat stop leaves the cap (p95 19.0 ms, p99 72.6 ms, max 145.7 ms).
Log: `client/tools/downloads/phase14-perf.log`.

## 4. The complete journey (plan.md section 1)

Runner: `server/tests/phase14_journey.py`; client: `scripts/test/phase14_journey.gd`.
It is a real client — real autoloads, real HTTP account service, real session
token, real ENet transport, real intents — with the keyboard replaced by a script
(`SimNet.forced_intent`, the same hook the Phase 5 probes use). The stack is the
production one: PostgreSQL → C++ service → authoritative world server → client;
the character is registered, created, selected and loaded through the service,
and the join uses the service session token (no dev join: `HPMMO_ALLOW_DEV_JOIN`
is explicitly unset).

Steps exercised, each with its own pass/fail line in the transcript
(`server/tests/out/phase14/journey-*.jsonl`):

| # | Step | Status |
| --- | --- | --- |
| 1 | register → log in (service session token) | PASS |
| 2 | create/select the character through the service | PASS |
| 3 | join the world with the session token | PASS |
| 4 | enter the world scene (the same `change_scene_to_file` the menu uses) | PASS |
| 5 | walk the courtyard and cast (12 casts accepted in the protected zone) | PASS |
| 6 | fight a reactive pack and take the reward (5-member pack, 5 rewards, +365 exp) | PASS |
| 7 | mount, fly, land, dismount | see §4.1 |
| 8 | walk to the castle, transfer into the interior | PASS |
| 9 | ride the moving staircase to another floor | see §4.1 |
| 10 | leave the castle and log out with state intact | **FAIL — D14-1** |

### 4.1 Journey results

**Scripted journey, project build** (12:43 run, quiet machine; log
`server/tests/out/phase14/journey-journey_93425.jsonl`): login, character
creation, join, world entry, the courtyard cast (12 accepted) and the reactive
pack fight (5-member pack, 5 rewards, +365 exp) all **pass**. Three steps failed:

| Step | Result | Cause |
| --- | --- | --- |
| mount / fly / land | FAIL | the first mount request was refused (`is_on_floor()` was false at that instant) and the dismount was refused afterwards because the rider was over forest slope — a rider may only dismount on level ground (`player.gd:680-690`). Harness route, not a product bug; fixed by flying to the courtyard before dismounting. |
| castle exit | FAIL | a journey-script bug (the entry transfer's `transfer_sent` flag was never cleared, so no exit request was ever sent). Fixed. |
| logout state | **FAIL — D14-1** | the character reloaded with exp 0 against the session's 165. |

**Scripted journey, packaged build** (headless QA package whose main scene is
the journey driver, run alone on a quiet machine after the mains harness fixes):
**9 of 10 steps pass** — login, character creation, join, world entry, courtyard
cast, pack kill with 3 rewards and +129 exp, mount/fly/land/dismount, and the
castle transfer (`transfer committed to castle_interior`). The remaining step
(the interior route, then the exit transfer and logout) fails:
`staircase_missing {"controller": true, "interior": false, "map":
"castle_interior"}` at t = 124.7 — the map controller reports the interior map
while its interior reference is null, so the harness never finds the moving
staircase, and the run then sits until the 900 s cap without the exit request
firing. That is a harness/route defect in the interior half, reported rather than
papered over: **the interior half of the section-1 journey is not verified by
this run.** (`castle_walkthrough.tscn` covers the interior route 87/0; the
staircase's own suite fails — D14-7.) Logs: `phase14-journey_pkg.log`,
`journey-journey_99435.jsonl`.

**Launcher path, packaged build, non-default account-service port**
(`client/tools/downloads/phase14-launcher-portfix.log`, captures
`phase14-launcher/packaged-0*.png`):

| Check | Result |
| --- | --- |
| real package built by `package_client.py` from the Godot export | PASS |
| served over HTTPS with a throwaway cert + signed manifest | PASS |
| `HPMMO_Launcher.exe --update` installs it (`versions/0.7.0/HPMMO.exe`, 109 268 480 B) | PASS |
| `--verify` healthy, `--print-state` reports 0.7.0 | PASS |
| packaged game launched the way `LaunchInstalledGame` does (argv + `HPMMO_TICKET` / `HPMMO_API_URL` / `HPMMO_USER_DIR`) | PASS |
| the packaged window is up (title `HPMMO`) | PASS |
| Enter delivered to the window (real keystroke, the documented character-select key) | PASS |
| the game redeemed the single-use launcher ticket | PASS |
| the game auto-logged in | PASS |
| the game joined the world server | PASS |
| the server registered the session-bound player (`players=1`, uid 31, `map=grounds`) | PASS |

**13 of 13 checks pass end to end** (`LAUNCHER LAUNCH RESULT: 13 checks, 0
failures`, exit 0) with the account service on a **non-default ephemeral port**
and nothing listening on 8081 — that is the regression proof for D14-9. The
earlier failure of this same run (`Database service connection failed`) is
exactly the bug D14-9 describes and is now fixed.

Verdict for the matrix's Launcher and journey rows: the *packaging, install,
verify, launch, ticket handoff, login, character load, join* half of the
section-1 journey is proven on a packaged build through the launcher's own
tools. The *gameplay* half (courtyard → pack → reward → mount → castle →
floors → logout-with-state) is proven only on the project build and only
partially: the fight, rewards and courtyard pass; the mount/dismount step passes
once the harness lands on level ground; the castle route and the final logout
are blocked by D14-1 (persistence) and by the castle step's own timeout under
load. It is reported as **not complete** rather than rounded up.

## 5. Server tick headroom

Method: `server/tests/phase14_tick.py` runs the production world-server boot
(`phase14_tick.gd` performs `world_server.gd`'s exact steps: DEDICATED role, host
the ENet transport, build the real world scene, bridge authority events) with one
addition — it drives the simulation loop itself and times **every** call to
`SimAuthority._step`, the exact function the production accumulator calls, at the
production 20 Hz cadence (50 ms budget). Load is real: `n` headless clients (the
Phase 5 `agree` probes) walk to a pack, fight it and take rewards, added in
levels that stack on each other.

| Players | entities (mean) | steps measured | p50 µs | p95 µs | p99 µs | max µs |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 30.0 | 1 204 | 132 | 252 | 347 | 3 103 |
| 2 | 36.7 | 1 204 | 212 | 1 085 | 7 478 | 72 865 |
| 4 | 39.9 | 1 103 | 186 | 1 008 | 9 239 | 79 403 |
| 8 | 43.6 | 1 103 | 241 | 2 339 | 13 359 | 102 679 |
| 16 | 52.1 | 1 103 | 338 | **6 561** | 10 250 | 26 969 |

**Headroom at the worst level (16 players): p95 is 6.56 ms of the 50 ms tick,
i.e. 86.9% of the budget unused.** The p99 (10.25 ms) still leaves 4.9x margin.

Two honest caveats:

* Isolated single steps blew past the 50 ms budget at the 2-8 player levels
  (max 72-103 ms). The loop absorbs that with its bounded catch-up (up to five
  steps per frame), and the p95/p99 that decide whether the world keeps up stayed
  small — but a state that took 100 ms to advance by one tick did happen, and the
  cause was not isolated here.
* This measures the authoritative step only. Snapshot encoding and ENet sending
  run in `SimNet`'s own callback and are not inside this number; the clients were
  headless processes on the same machine over loopback (best-case network,
  shared-CPU worst case).

**Tick-rate verdict:** 20 Hz is justified by the measurement. Even at 16 real
clients on this machine the sim step uses under 14% of the tick at p95, so
nothing here argues for changing the rate. The numbers would also fit 30 Hz
(33 ms budget, p99 still 3.2x under), so a future feature that needs a faster
tick can afford it — but there is no measured reason to move today.

Command: `python server/tests/phase14_tick.py --levels 0,2,4,8,16`
(log `client/tools/downloads/phase14-tick.log`,
`server/tests/out/phase14/tick-summary.json`, copied to
`client/tools/downloads/phase14-tick-summary.json`).

## 6. Latency, loss and bandwidth

Method: `server/tests/phase14_profiles.py` reruns the Phase 5 multiplayer
scenario (one world server, two real headless clients that walk to a pack, fight
it and take the reward) under each documented profile, with **one UDP relay per
client** between client and server. The relay is a NAT: the server sees a
different source port per client, and the relay counts the bytes that actually
cross the wire in both directions. The profiles themselves (`local`, `mobile`,
`awful`) are the documented ones from `docs/phase5-latency-profiles.md`; the
delay/loss is applied by the sim on unreliable traffic only.

| Profile | one-way delay / loss | casts accepted | position updates received | inputs sent | hits landed | rewards | exp gain | up B/s | down B/s | total KiB/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `local` | 0 ms / 0% | 7 / 7 | 573 | 1 089 | 11 | 3 | +129 | 659 | 6 854 | **7.34** |
| `mobile` | 150 ms / 3% | 7 / 7 | 578 | 1 082 | 11 | 3 | +129 | 636 | 6 854 | **7.31** |
| `awful` | 300 ms / 10% | 6 / 6 | 578 | 1 083 | 10 | 3 | +129 | 594 | 6 809 | **7.23** |

Reading:

* **Bandwidth per player ≈ 7.3 KiB/s** (6.8 KiB/s downstream, ~0.6 KiB/s
  upstream) for a player actively fighting, measured at the wire including ENet
  and UDP/IP overhead. It is flat across profiles, which is what the fixed-cost
  snapshot design predicts.
* **Hit consistency:** every accepted cast landed (11, 11, 10 hit events for
  7, 7, 6 casts — a cast can land on more than one victim), and both clients took
  the **same 3 rewards and the same +129 exp**; the kills were credited once.
* **Correction frequency:** the probe's `corrections` counter is *every*
  authoritative position update for the local body (573-578 in ~54 s ≈ 10.6/s,
  i.e. about 0.53 per input frame), not only reconciliation snaps — the probe's
  name is narrower than what it counts. The number that matters for feel, "how
  often the server moved my body away from my prediction", is not separated out
  anywhere in this build.
* **Disconnect handling:** one client is hard-killed mid-fight. The server
  logged the leave, the surviving client kept playing, kept landing hits
  (`B_still_landed_hits_after: true`) and took its rewards; the final roster was
  empty. Both clients' transcripts agree on the pack, the deaths and the rewards
  (that agreement is what `multiplayer_sim.py` asserts per profile, §2.1).
* The killed client writes no final record by design (that is the disconnect
  test), so per-profile gameplay numbers above are the survivor's.

What this still does not cover: jitter (the profile delay is constant per
message), reordering, bandwidth saturation, and NAT/firewall behaviour. Logs:
`client/tools/downloads/phase14-profiles.log`.

## 7. Soak

Run: `client/tools/run_phase14_soak.ps1`, client `scripts/test/phase14_soak.gd`
(a real client against a real world server, forced intents, low preset, windowed).
Loop: mass casting → engaging and killing the nearest pack → mount/fly/land →
castle transfer in → (staircase attempt) → transfer out.

| Property | Value |
| --- | --- |
| Duration | **62 min 20 s of simulated play** (12:10:33 → 13:12:53 wall clock; the client's own clock read 3 740 s because frames were starved while other measurements overlapped the last two minutes). The client was stopped externally at that point, so the run has no `SOAK RESULT` line — the 187 samples are complete and that is what the numbers below are read from |
| Samples | 187, one every 20 s (`client/tools/downloads/phase14-soak-hour.jsonl`) |
| Casts | 4 656 accepted (0 rejected) |
| Pack kills | 77 |
| Mob respawns observed | 30 |
| Map transfers | 26 (grounds ↔ castle interior) |
| Mount/fly/land cycles | 15 |
| Player deaths | 1 |
| Rewards | 77 (one per kill — no duplicates) |
| Orphan nodes | **0 for the whole run** (max 0) |
| Resources | 554 → 583 in the first ten minutes, then flat at 582.4-584.0 (cache warm-up, no growth) |
| Client stderr | empty for the whole run (no script errors, no missing-resource lines) |

Memory (`Performance.MEMORY_STATIC` / `OS.get_static_memory_usage()`, both
report the same figure; 10-min means):

| Window | mean MiB | nodes | resources | tex MiB |
| --- | --- | --- | --- | --- |
| 0-10 min | 133.62 | 2290 | 572.2 | 628 |
| 10-20 min | 135.66 | 2245 | 583.1 | 658 |
| 20-30 min | 138.08 | 2307 | 582.6 | 650 |
| 30-40 min | 140.02 | 2344 | 582.4 | 648 |
| 40-50 min | 141.44 | 2351 | 582.4 | 651 |
| 50-60 min | 143.58 | 2401 | 582.4 | 646 |
| 60-70 min | 143.58 | 2339 | 584.0 | 663 |

Inside the castle only (entity count ≤ 3, the most like-for-like comparison):
first ten samples mean **130.44 MiB**, last ten mean **140.86 MiB** (+10.4 MiB).
Node counts do not grow (2 245-2 401 across the run) and the resource table is
flat after warm-up, so the rise is allocation rather than leaked objects.

**Verdict: not a clean plateau.** The curve rises ~10 MiB/hour with no
observable ceiling inside the hour, so it cannot be called "warm-up" without a
longer run. It is bounded (7% of a 140 MiB working set) and free of orphan or
resource growth, so it is filed as **D14-3 (Minor, needs a longer soak to
resolve)** rather than as a release blocker. Everything the phase explicitly
requires to be flat *is* flat: no orphan growth, no unexplained script errors
(zero `SCRIPT ERROR` lines in the client stderr log), no missing resources, no
duplicate rewards (74 kills → 74 rewards).

## 8. Defects found, classified by severity

Severity follows `docs/defects.md`: *Blocker* = data loss / security exposure /
a core promise broken; *Major* = clearly wrong behaviour a player or an operator
can hit; *Minor* = small correctness or polish gap; *Cosmetic* = copy, naming.

### D14-1 — Blocker. Online characters are never saved: the session is not bound to a character

* **Symptom (measured):** the journey logged out with exp 165 and level 2, then
  reloaded the same character from the service: **exp 0, level 1, position
  (0,0,0)** — the state the character was created with. The world log contains
  no save call for the session.
* **Cause (code):** `SimNet.sim_join` builds the player identity from
  `SimAuthority.persistence.resolve_session(token)`
  (`addons/hpmmo_sim/net.gd:208-239`); that token comes from `/api/session/introspect`,
  and the service only fills `sessions.character_id` for a ticket that carried a
  character (`server/services/cpp/src/app.cpp:490-525`, "Unbound tickets (and
  plain logins) leave character_id NULL"). The client never requests a
  character-bound ticket: `main_menu.gd:151-165` joins the game with the *login*
  session token, and character select happens after the join
  (`character_select.gd:243-254` only changes scene). So `record["character_id"]`
  is 0, and both the periodic autosave (`authority.gd:993-997`) and the
  last-save-on-exit (`authority.gd:490-492`) call
  `persistence.save_player`, which returns immediately when
  `character_id <= 0` (`persistence.gd:186-191`).
* **Blast radius:** every character played through a normal client login (and
  through the launcher, whose ticket is fetched before a character is chosen)
  loses all progression, position and inventory at logout. `integration_api.py`
  passes because it exercises the service directly, and `smoke_end_to_end.py`
  passes because its synthetic check requests an *unbound* ticket and only
  asserts login+join, not a character save.
* **Evidence:** `server/tests/out/phase14/journey-*.jsonl` (`state_at_logout`
  exp 165 → `reload` exp 0), `journey-client.log`, `stack-world.log`.
* **Recommended fix (not done here — it is a protocol/flow change, not a
  measurement):** after the player picks a character, have the client request a
  character-bound ticket (`POST /api/game-ticket {character_id}`, which the
  service already supports) and re-join with that session; or let the join carry
  the character id and have the world server validate ownership through the
  service token before binding `record["character_id"]`.

### D14-2 — Major. A ~120-140 ms frame inside combat (both passes)

* **Symptom:** in the combat stop (real spell path, live pack), p99 was
  21.6-21.9 ms but the maximum frame was **142.9 ms** in pass 1 and **116.3 ms**
  in pass 2; the same window at 60 Hz vsync shows 145.7 ms. Every non-combat stop
  stays inside 15.7 ms even at max.
* **Repro:** `godot --path client res://scenes/test/phase14_perf.tscn --quit-after 40000 -- --novsync --out=...`
  (log `client/tools/downloads/phase14-perf-novsync.log`).
* **Reading:** it is a rare hitch (~1 frame per 6 s of sustained casting), not a
  sustained drop — the 30 FPS floor is still met — but at 12 FPS for one frame it
  is visible, and it recurs in the second pass, so it is not purely first-use
  shader compilation. Not diagnosed further in this phase.

### D14-3 — Minor. Memory drifts ~10 MiB/hour with no plateau in a one-hour soak

See §7. Nodes and resources are flat and orphans are zero, so this is
allocation growth, not leaked objects. Needs a multi-hour soak to decide whether
it converges.

### D14-4 — Minor. The client package ships the test and tool trees

`tools/release/windows-desktop.export_presets.cfg` sets
`export_filter="all_resources"`, so the release artifact contains every
`scenes/test/*`, `scripts/test/*` and `tools/*` file: the packaged build is
`HPMMO.exe` 109 MB + `HPMMO.pck` 232 MB. The export log lists e.g.
`res://tools/probe_perf_monitors.gd.remap` as packaged. A release filter that
excludes the QA trees would shrink the download and stop shipping test hooks.

### D14-5 — Blocker (found here, fixed here). The launcher could not start the installed game at all

* **Symptom (measured):** with a packaged build installed by the launcher's own
  updater, clicking/launching the game produced an instant abort:
  `ERROR: Scene path was specified on the command line, but this Godot binary was
  compiled without support for path overrides. Aborting.` (log:
  `client/tools/downloads/phase14-launcher/launched-game.log`). No window, no
  login, no join.
* **Cause:** the official Windows export templates are built with
  `disable_path_overrides=yes`, so any positional scene argument aborts a
  packaged Godot binary before `main()`; `hpmmo::LaunchInstalledGame`
  (`launcher_cpp/src/updater.cpp:1566`) always passed
  `scenes/main/main_menu.tscn`.
* **Fix (one line, made here):** the launch command no longer passes a scene —
  the installed game's `application/run/main_scene` *is* the main menu, so the
  argument bought nothing. Rebuilt with the project's own chain
  (`ninja -C client/launcher_cpp/build`).
* **Before/after evidence:** before — `phase14-launcher.log`, launch checks
  `FAIL: the game redeemed the launcher ticket / auto-logged in / joined / world
  scene loaded` and the abort line above. After the rebuild —
  `phase14-launcher-after.log` (see §4.1 for the result).
* **Residual:** the *tracked* `client/HPMMO_Launcher.exe` binary in the tree is
  still the old build; the fix lives in `launcher_cpp/src/updater.cpp` and in the
  rebuilt `launcher_cpp/build/HPMMO_Launcher.exe`. A release must redistribute
  the launcher.

### D14-6 — Minor (environment). A TCP-free port is not a UDP-bindable port on Windows

The first journey run failed with ENet's "couldn't create host / cannot bind UDP"
because the driver's `free_port()` returned a TCP port. Windows keeps 860 UDP
ports excluded on this machine (`netsh int ipv4 show excludedportrange protocol=udp`).
The suites now pick UDP ports via a UDP bind (`server/tests/phase14_stack.py`).
Worth knowing for any harness that picks ports for the world server.

### D14-7 — Major (open). The staircase suite fails 7 of its checks, reproducibly on a quiet machine

* **Symptom:** `python server/tests/staircase_sim.py` → `47 checks, 7 failures`,
  identical on the loaded and the quiet run:
  `the rider boarded while the platform was docked`,
  `the rider was carried across levels (0.00 m of vertical travel)`,
  `the rider stayed on the deck for the whole trip`,
  `the server refused the entry with feedback (0 notice(s))`,
  `the fallback walk reached all 9 waypoints (got 2)`,
  `the fallback route ended on the second floor at y=0.00`,
  `the fallback walk recorded every landing it reached (reached_0, reached_1)`.
* **What still passes in the same run:** the two-client *agreement* half is
  intact — both clients report the same platform position, state and destination
  on every shared tick (worst disagreement 0.0000 m), the platform travels 6 m,
  the four states occur in order, and the disconnect-while-riding case resolves
  the rider to a landing. So the staircase itself is synchronised and authority
  owns it; what fails is the probe's *walk onto the deck* and the *fallback
  walk*.
* **Evidence:** probe transcripts
  (`%TEMP%/hpmmo-stair-*/rider.jsonl`, `fallback.jsonl`, `busy.jsonl`): the ride
  probe walks from (150, 0.6, 108) to (153.9, 0, 116.0) and stops ~0.6-2.6 m
  from the deck point without ever entering `on_deck`; the fallback walk reaches
  waypoint 1 at y = 2.67 and then stalls at y = 5.65 short of the second floor.
  The `rider_logout` scenario *does* board (boarded at tick 236), so the same
  code can succeed — this is timing/route-sensitive.
* **Not fixed here:** the honest reading is that either the walk route the probe
  uses no longer matches the Phase 10 collision geometry, or the dock window is
  too short for the approach. Both are bigger than a Phase 14 measurement fix,
  and the Phase 8 exit check ("two clients see the same staircase position") is
  demonstrably met while the *fallback route* claim is not.
* **Consequence for the matrix:** the Castle row's "moving stairs" scenario is
  **not** covered by a passing check at HEAD.

### D14-9 — Major (found here, fixed here). The account-service port was a literal 8081 on the launcher path

* **Symptom (found while chasing the launcher-path run):** the packaged game
  opened the main menu with `Server 127.0.0.1` and then failed every HTTP call
  with `Database service connection failed (Code: 2)` against a local stack,
  because `main_menu.gd`'s `--ip` handling set
  `DatabaseManager.api_base_url = "http://<ip>:8081"` with a literal port. Any
  account service that is not on 8081 is unreachable from the launcher path, and
  the `api_port` key in `client_config.json` — which the launcher *does* honour
  when it builds `HPMMO_API_URL` — is silently discarded by the client.
* **Why it was invisible:** in production the API is on 8081, so the literal and
  the config agree; the local suites never exercised the launcher path, and the
  ones that did hardcoded the same literal.
* **Fix (made here):** the menu now resolves the port once with documented
  precedence — `--api-port=N`, then `HPMMO_API_URL` (the launcher handoff), then
  `client_config.json`'s `api_port`, then the default 8081 — and `--ip` changes
  only the host (`client/scripts/ui/main_menu.gd`).
* **Proof, end to end:** the launcher-path driver now serves the account service
  on a **non-default** ephemeral port and runs with nothing listening on 8081;
  the packaged game still loads the character list, joins the world and appears
  on the server roster (`phase14-launcher-portfix.log`). Before the fix the same
  run stopped at `Database service connection failed`.
* **Regression coverage:** `run_game_checks.ps1` 93/0 and `run_phase13_checks.ps1`
  111/0 after the change; the launcher-path driver is the end-to-end proof.

### D14-10 — Minor (latent, not this phase's to fix). The launcher writes `client_config.json` relative to its working directory

`launcher_cpp/src/main.cpp:168-189` (`SaveConfig()`, called at `:895`) opens
`client_config.json` by relative path, so the launcher run from a different
working directory would create or overwrite a config wherever it happened to be,
rather than beside the launcher or in a user data directory. It has not bitten
yet because the launcher is normally started from its install directory. Worth
fixing when the launcher is next touched; written down here so it is not
rediscovered the hard way. (This is also the only writer of that file in the
repository — the game itself never writes it.)

### D14-8 — Minor (test stability). The mobile-profile multiplayer run fails intermittently, on a different check each time

Three runs of the same tree: `local` 39/0 and `awful` 39/0 on the first battery;
`--profile mobile` failed with `both clients were credited for the same 3 kill(s)`
on the loaded run and with `the same burn does tick outside the zone (positive
control, 0 damage events)` on the quiet re-run. The burn control runs in-process
(no network), and both failing checks measure events inside a **wall-clock**
window (`create_timer`) while the sim advances on **fixed** ticks — a starved
client accumulates fewer ticks than the window assumes. That makes the mobile
gate unable to distinguish a product regression from a slow machine. Not a
product defect, but it must be fixed to be a gate: make the two checks count
ticks, not seconds.

### Standing residue (carried in from earlier phases — these still prevent claiming the corresponding request is complete)

| Item | Where it is recorded | Consequence |
| --- | --- | --- |
| Hero has no authored texture maps of its own; house variation is a runtime material override on the single Quaternius-derived body | `assets/manifest.json` (`hero_final_art`, `character_equipment_variants: placeholder`) | "Replace short prototype proportions" is done (1.877 m measured); a fully authored hero texture set is not |
| No authored LODs on the hero or the kit (`"lods": "none"` throughout the manifest) | `assets/manifest.json` | Phase 10's "add LODs/visibility ranges" is only partly met (instancing yes, LODs no) |
| Two Quaternius minion bodies (Snatcher, Inferi) remain placeholders; `monster_variants_final: missing` | `assets/manifest.json`; plan Phase 11 | The spider and both bosses are authored; ordinary minions are not |
| No navigation mesh anywhere: `NAVIGATION_REGION_COUNT = 0` at every perf stop | measured in §3 | Mobs steer directly; "navigation" cannot be profiled because none is loaded |
| The Gothic roof-slope module is authored but not placed on the interior route | plan Phase 10 residue | The castle still reads as roofless from above |
| Potion use is client-side only: `inventory_ui.gd:64-80` heals `player.current_hp` and decrements the item locally, with no authoritative item-use intent | this report, §8 | An item-use path can be forged or desynced; "potion use updates the UI correctly" is true only locally |

No deferred placeholder is claimed as complete anywhere in this report.

## 9. Files this phase added, and corrective fixes

No commit was made from this session; the harness files below were picked up by
the owner's commits while the phase ran, and the two fixes in §9.1 are still
uncommitted working-tree changes.

Owned by this phase:

* `client/tools/run_phase14_gates.ps1`, `client/tools/run_phase14_soak.ps1`,
  `client/tools/run_phase14_server_suites.sh`, `client/tools/run_phase14_measurements.sh`,
  `client/tools/run_phase14_final.sh`, `client/tools/phase14_launcher.py`
* `client/scripts/test/phase14_{soak,perf,tick,journey}.gd` and
  `client/scenes/test/phase14_{soak,perf,tick,journey}.tscn`
* `server/tests/phase14_{stack,tick,profiles,journey,launcher}.py`
* `client/tools/probe_perf_monitors.gd` (monitor-name probe)
* `docs/phase14-acceptance.md` (this report; also copied to `client/docs/phase14-acceptance.md`)

### 9.1 Minimal corrective fixes (each with before/after evidence)

Deliberate working-tree changes to existing files:

* **`client/launcher_cpp/src/updater.cpp`** — `LaunchInstalledGame` no longer
  passes a scene path (D14-5). Before: the packaged game aborted at startup
  (`Scene path was specified on the command line... Aborting`), launcher launch
  6/13 checks. After: 13/13 (`phase14-launcher-portfix.log`), rebuilt with
  `ninja -C client/launcher_cpp/build`.
* **`client/scripts/ui/main_menu.gd`** — the account-service port is resolved
  with precedence (`--api-port`, then the launcher's `HPMMO_API_URL`, then
  `client_config.json`'s `api_port`, then the documented default 8081) instead of
  the literal 8081 in the `--ip` branch (D14-9). Before: `Database service
  connection failed (Code: 2)` against any non-8081 service. After: the packaged
  launcher-path run passes 13/13 with the API on an ephemeral port and nothing on
  8081. Gates re-run after the change: 93/0 and 111/0.

Environment/config:

* `client/export_presets.cfg` — staged from `tools/release/windows-desktop.export_presets.cfg`
  because the release workflow does exactly that before exporting (the file is
  not tracked by the client repo; `project.godot` was restored unchanged after
  the QA export).
* `client/project.godot` was temporarily pointed at the journey scene for the QA
  package export and restored; `git status` shows the tree as it was.
* `server/tests/out/encounters/*.jsonl` are **tracked** files that
  `encounters_sim.py` rewrites every run; they show as modified. That is the
  suite's own behaviour, not an edit of ours, but it means running the suite
  dirties the server repo.

## 10. What this phase could not verify

Stated plainly rather than implied by silence:

1. **Visual acceptance.** Art consistency, lighting comparison, spell readability
   and the audio mix need eyes and ears. The Phase 10/12/13 captures exist
   (`phase12-*.png`, `phase13-*.png`); nobody judged them visually in this phase,
   so no claim about how the game looks is made here.
2. **Camera clipping in the castle.** No automated check covers it; the Phase 8
   walkthrough asserts route clearance rays, not the rendered camera.
3. **Diagnosis of D14-2** (the 116-143 ms combat hitch). Measured, reproducible,
   not root-caused.
4. **The staircase ride on the journey** — see §4.1 for whether the packaged run
   achieved it; the Phase 8 suite covers the staircase itself.
5. **A multi-hour memory verdict** for D14-3.
6. **16-client tick load** and any level the sweep could not reach on this
   machine — see §5. (The 16-client level *was* reached; nothing above it was.)
7. **Wire bandwidth for the packaged client.** Bandwidth was measured with the
   headless dev-join probes through a UDP relay; the packaged client was not
   relayed.
8. **The live VPS.** Off-limits for this phase except read-only status; nothing
   was deployed and no measurement here describes the deployed box.
9. **Rows of the matrix with no automated check at all**: presentation quality
   (item 1), the launcher GUI's own login/Play interaction (the *install*,
   *verify*, *repair*, *self-update* and *launch command* are all exercised, but
   the Windows GUI was not clicked by a person or a UI driver in this phase),
   and "audio mix".

### 10.1 Note on test hygiene (windows and shared state)

For transparency, since it was visible on the machine: the soak ran **windowed**
for its 62 minutes (that is the intended representative-play configuration) and
the launcher-path driver necessarily runs the packaged game with a visible
window for ~45 s per attempt — those windows are test clients pointed at a local
ephemeral stack, never at the owner's launcher or the configured VPS. After this
review, every long-running client (soak, journey, packaged journey) now defaults
to `--headless`, the launcher driver kills any surviving game process by
executable path in its `finally` block, and journey runs point `HPMMO_USER_DIR`
at their own folder so nothing lands in the shared `%APPDATA%` profile. The
workspace PostgreSQL dev cluster those runs started was stopped and no test
process was left running. The client never writes `client/client_config.json`.

Captures and logs (all under `client/tools/downloads/`): `phase14-gate-*.log`,
`phase14-gates-summary.log`, `phase14-server-summary.log`, `phase14-*.log`
(tick, profiles, launcher, journey, staircase, encounters, mp_mobile),
`phase14-perf*.jsonl|log`, `phase14-soak-hour.jsonl`, `phase14-build/`
(the packaged builds), `phase14-launcher/packaged-*.png`.
