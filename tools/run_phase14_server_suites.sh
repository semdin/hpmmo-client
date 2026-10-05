#!/usr/bin/env bash
# Phase 14 server suite battery. Detached: writes one log per suite and a
# summary line file, so a killed shell cannot eat a long run.
set -u
ROOT="C:/Users/mehme/Desktop/sem/projects/game"
OUT="$ROOT/client/tools/downloads"
SUM="$OUT/phase14-server-summary.log"
cd "$ROOT/server" || exit 1
: > "$SUM"

run() {
  name="$1"; shift
  log="$OUT/phase14-$name.log"
  echo "=== $name: $* ==="
  timeout 3600 python "$@" > "$log" 2>&1
  code=$?
  line=$(grep -E "RESULT:|SKIP" "$log" | tail -1)
  printf '%s: exit=%s :: %s\n' "$name" "$code" "$line" >> "$SUM"
  echo "$name: exit=$code :: $line"
}

run multiplayer_mobile  tests/multiplayer_sim.py --profile mobile
run multiplayer_awful   tests/multiplayer_sim.py --profile awful
run maps_sim            tests/maps_sim.py
run encounters_sim      tests/encounters_sim.py
run maintenance_sim     tests/maintenance_sim.py
run staircase_sim       tests/staircase_sim.py
run integration_api     tests/integration_api.py
run smoke_end_to_end    tests/smoke_end_to_end.py
run deploy_rehearsal    tests/deploy_rehearsal.py
run release_pipeline    "$ROOT/client/tools/release/test_updater.py"
echo "PHASE14 SERVER BATTERY DONE" >> "$SUM"
