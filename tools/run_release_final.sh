#!/usr/bin/env bash
# Release closing batch: waits for the measurement batch to finish (so the box
# is quiet), then measures the server tick headroom sweep and re-runs every
# client gate on the final tree.
set -u
ROOT="C:/Users/mehme/Desktop/sem/projects/game"
OUT="$ROOT/client/tools/downloads"
SUM="$out/release-final-summary.log"
: > "$SUM"

echo "waiting for the measurement batch ..."
until grep -q "RELEASE MEASUREMENT BATCH DONE" "$out/release-measurements-summary.log" 2>/dev/null; do
  sleep 30
done
# and for the soak client itself, which the batch's own wait can miss
until ! powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name like '%Godot%'\").CommandLine" 2>/dev/null | grep -q soak; do
  sleep 20
done
echo "box is quiet" | tee -a "$SUM"

echo "=== tick sweep ===" | tee -a "$SUM"
( cd "$ROOT" && timeout 2400 python server/tests/server_tick_headroom.py --levels 0,2,4,8,16 > "$out/release-tick.log" 2>&1 )
printf 'tick: exit=%s :: %s\n' "$?" "$(grep -E 'TICK RESULT' "$out/release-tick.log" | tail -1)" | tee -a "$SUM"
cp "$ROOT/server/tests/out/release/tick-summary.json" "$out/release-tick-summary.json" 2>/dev/null

echo "=== client gates on the final tree ===" | tee -a "$SUM"
( cd "$ROOT" && timeout 2400 powershell -ExecutionPolicy Bypass -File client/tools/run_release_gates.ps1 > "$out/release-gates-driver.log" 2>&1 )
cat "$out/release-gates-summary.log" | tee -a "$SUM"
echo "RELEASE FINAL BATCH DONE" | tee -a "$SUM"
