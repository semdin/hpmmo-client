#!/usr/bin/env bash
# Phase 14 re-runs: the three steps whose first attempt was invalidated by a
# driver bug (not by the product). Runs after the closing batch, on a quiet box.
set -u
ROOT="C:/Users/mehme/Desktop/sem/projects/game"
OUT="$ROOT/client/tools/downloads"
SUM="$OUT/phase14-rerun-summary.log"
QA_EXE="$OUT/phase14-build/journey-client/HPMMO.exe"
: > "$SUM"

until grep -q "PHASE14 FINAL BATCH DONE" "$OUT/phase14-final-summary.log" 2>/dev/null; do
  sleep 30
done
sleep 20

run() {
  name="$1"; shift
  log="$OUT/phase14-$name.log"
  echo "=== $name ==="
  ( cd "$ROOT" && timeout 3600 "$@" > "$log" 2>&1 )
  code=$?
  line=$(grep -E "RESULT:|LAUNCHER (INSTALL|LAUNCH) RESULT|SKIP|FAIL:" "$log" | tail -2 | tr '\n' ' ')
  printf '%s: exit=%s :: %s\n' "$name" "$code" "$line" | tee -a "$SUM"
}

run profiles   python server/tests/phase14_profiles.py
run launcher   python client/tools/phase14_launcher.py
run journey_pkg python server/tests/phase14_journey.py --client-exe "$QA_EXE" --seconds 900
echo "PHASE14 RERUN BATCH DONE" | tee -a "$SUM"
