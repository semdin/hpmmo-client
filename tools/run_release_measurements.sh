#!/usr/bin/env bash
# Release measurement batch, run after the soak releases the machine so the
# CPU-sensitive numbers are measured on a quiet box. One log per step and a
# summary line file, so a killed shell cannot eat a long run.
set -u
ROOT="C:/Users/mehme/Desktop/sem/projects/game"
CLIENT="$ROOT/client"
OUT="$CLIENT/tools/downloads"
SUM="$out/release-measurements-summary.log"
QA_EXE="$out/release-build/journey-client/HPMMO.exe"
mkdir -p "$OUT"

# 1. wait for the soak client (window title HPMMO, launched from the soak scene)
echo "waiting for the soak to finish ..."
until ! powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like '%Godot%'\" | Where-Object { \$_.CommandLine -like '*soak*' } | Select-Object -First 1" | grep -q soak; do
  sleep 30
done
echo "soak finished" | tee -a "$SUM"

run() {
  name="$1"; shift
  log="$out/release-$name.log"
  echo "=== $name ==="
  ( cd "$ROOT" && env -u HPMMO_ALLOW_DEV_JOIN -u HPMMO_DEV_SPAWN -u HPMMO_DEV_FAST_RESPAWN timeout 3600 "$@" > "$log" 2>&1 )
  code=$?
  line=$(grep -E "RESULT:|SKIP|FAIL:" "$log" | tail -2 | tr '\n' ' ')
  printf '%s: exit=%s :: %s\n' "$name" "$code" "$line" | tee -a "$SUM"
}

run tick          python server/tests/server_tick_headroom.py --levels 0,2,4,8,16
run profiles      python server/tests/net_profiles.py
run launcher      python client/tools/launcher_package.py
run journey_pkg   python server/tests/journey_e2e.py --client-exe "$QA_EXE" --seconds 900
run staircase     python server/tests/staircase_sim.py
run encounters    python server/tests/encounters_sim.py
run mp_mobile     python server/tests/multiplayer_sim.py --profile mobile
echo "RELEASE MEASUREMENT BATCH DONE" | tee -a "$SUM"
