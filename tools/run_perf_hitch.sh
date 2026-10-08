#!/usr/bin/env bash
# Combat-hitch diagnosis driver.
#
# Runs the per-frame spike probe against a FROZEN copy of the client tree, so a
# measurement is never taken while another workstream is mid-edit (the live tree
# is dirty while the persistence fix lands). The probe sources themselves live in
# the live tree; they are copied into the frozen tree on every run, so the files
# under client/scripts/test/perf_hitch_* stay the single source of truth.
#
# Usage: run_perf_hitch.sh <name> [probe args...]
#   every run writes client/tools/downloads/perf-hitch-<name>.jsonl (+ .log)
set -u
ROOT="C:/Users/mehme/Desktop/sem/projects/game"
FROZEN="${HPMMO_FROZEN_CLIENT:-C:/Users/mehme/hpmmo-measure/client}"
OUT="$ROOT/client/tools/downloads"
GODOT="${HPMMO_GODOT:-C:/Users/mehme/AppData/Local/Microsoft/WinGet/Packages/GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe/Godot_v4.7.2-stable_win64_console.exe}"

NAME="$1"; shift
mkdir -p "$OUT" "$FROZEN/scripts/test" "$FROZEN/scenes/test"
cp "$ROOT/client/scripts/test/perf_hitch_probe.gd" "$FROZEN/scripts/test/"
cp "$ROOT/client/scripts/test/perf_hitch_marker.gd" "$FROZEN/scripts/test/"
cp "$ROOT/client/scenes/test/perf_hitch_probe.tscn" "$FROZEN/scenes/test/"

LOG="$out/release-spike-$NAME.log"
JSONL="$out/release-spike-$NAME.jsonl"
echo "=== spike run: $NAME :: $* ==="
"$GODOT" --path "$FROZEN" res://scenes/test/perf_hitch_probe.tscn -- --out="$JSONL" "$@" > "$LOG" 2>&1
CODE=$?
echo "exit=$CODE log=$LOG"
grep -E "SPIKE (START|HIST|RESULT|PASS|FRAME|PREWARM)" "$LOG" | head -40
grep -E "SCRIPT ERROR|ERROR:" "$LOG" | head -10
