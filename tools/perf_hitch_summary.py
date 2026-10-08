#!/usr/bin/env python3
"""Combat-hitch: turn the spike probe's per-frame jsonl into the A/B table.

Reads client/tools/downloads/perf-hitch-<name>.jsonl (one row per rendered
frame, written by scripts/test/perf_hitch_probe.gd) and prints p50/p95/p99/max of
the frame time plus the spike count, for every run named on the command line.

Usage:
  python client/tools/perf_hitch_summary.py full1 instr-fix hitonly ...
  python client/tools/perf_hitch_summary.py --all
"""
import json
import sys
from pathlib import Path

DOWNLOADS = Path(r"C:/Users/mehme/Desktop/sem/projects/game/client/tools/downloads")


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(fraction * len(sorted_values)))
    return sorted_values[index]


def summarise(name):
    path = DOWNLOADS / f"perf-hitch-{name}.jsonl"
    if not path.exists():
        return None
    frames = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    if not frames:
        return None
    times = sorted(row["dt_ms"] for row in frames)
    scripts = sorted(row.get("script_us", 0) / 1000.0 for row in frames)
    spike_frames = [row for row in frames if row["dt_ms"] >= 25.0]
    return {
        "name": name,
        "frames": len(frames),
        "p50": percentile(times, 0.50),
        "p95": percentile(times, 0.95),
        "p99": percentile(times, 0.99),
        "max": times[-1],
        "over25": len(spike_frames),
        "over50": sum(1 for t in times if t >= 50.0),
        "over100": sum(1 for t in times if t >= 100.0),
        "script_p50": percentile(scripts, 0.50),
        "spike_script_p50": percentile(sorted(r.get("script_us", 0) / 1000.0 for r in spike_frames), 0.50) if spike_frames else 0.0,
    }


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        names = sorted(p.stem.replace("perf-hitch-", "") for p in DOWNLOADS.glob("perf-hitch-*.jsonl"))
    else:
        names = args
    header = f"{'run':16} {'frames':>7} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>8} {'>=25ms':>7} {'>=50ms':>7} {'>=100ms':>7} {'script p50':>10} {'spike script p50':>16}"
    print(header)
    print("-" * len(header))
    for name in names:
        row = summarise(name)
        if row is None:
            print(f"{name:16} (missing)")
            continue
        print(f"{row['name']:16} {row['frames']:>7} {row['p50']:>7.2f} {row['p95']:>7.2f} "
              f"{row['p99']:>7.2f} {row['max']:>8.2f} {row['over25']:>7} {row['over50']:>7} "
              f"{row['over100']:>7} {row['script_p50']:>10.2f} {row['spike_script_p50']:>16.2f}")


if __name__ == "__main__":
    main()
