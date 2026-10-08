#!/usr/bin/env bash
# Release re-runs: the three steps whose first attempt was invalidated by a
# driver bug (not by the product). Runs after the closing batch, on a quiet box.
set -u
ROOT="C:/Users/mehme/Desktop/sem/projects/game"
OUT="$ROOT/client/tools/downloads"
SUM="$out/release-rerun-summary.log"
QA_EXE="$out/release-build/journey-client/HPMMO.exe"
: > "$SUM"

until grep -q "RELEASE FINAL BATCH DONE" "$out/release-final-summary.log" 2>/dev/null; do
  sleep 30
done
sleep 20

run() {
  name="$1"; shift
  log="$out/release-$name.log"
  echo "=== $name ==="
  ( cd "$ROOT" && timeout 3600 "$@" > "$log" 2>&1 )
  code=$?
  line=$(grep -E "RESULT:|LAUNCHER (INSTALL|LAUNCH) RESULT|SKIP|FAIL:" "$log" | tail -2 | tr '\n' ' ')
  printf '%s: exit=%s :: %s\n' "$name" "$code" "$line" | tee -a "$SUM"
}

run profiles   python server/tests/net_profiles.py
run launcher   python client/tools/launcher_package.py
run journey_pkg python server/tests/journey_e2e.py --client-exe "$QA_EXE" --seconds 900
echo "RELEASE RERUN BATCH DONE" | tee -a "$SUM"
