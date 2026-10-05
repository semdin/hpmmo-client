#!/usr/bin/env python3
"""Phase 14 D14-3: summarise the resource-class soak.

Reads client/tools/downloads/phase14-memsoak-<name>.jsonl (one row every 5 s
from scripts/test/phase14_memsoak.gd) and prints:

  * a window table (default 5 minutes): mean static/texture/video memory, node,
    resource, object and orphan counts, so a plateau and a drift look different;
  * a linear growth estimate for static memory over the run, in MiB/hour;
  * per-class live-resource counts (ResourceLoader.has_cached) at each window;
  * the phase accounting table (static-memory delta and actions per phase name);
  * the frame histogram and the spike rate per phase, so the D14-2 real-play
    correlate can be read off the same run.

Usage: python client/tools/phase14_memsoak_summary.py [name] [--window=300]
"""
import json
import sys
from pathlib import Path

DOWNLOADS = Path(r"C:/Users/mehme/Desktop/sem/projects/game/client/tools/downloads")


def load(name):
    path = DOWNLOADS / f"phase14-memsoak-{name}.jsonl"
    rows, final = [], None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("event") == "final":
                final = row
            else:
                rows.append(row)
    return rows, final


def mean(values):
    return sum(values) / len(values) if values else 0.0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    window = 300.0
    for a in sys.argv[1:]:
        if a.startswith("--window="):
            window = float(a.split("=")[1])
    name = args[0] if args else "long30"
    rows, final = load(name)
    if not rows:
        raise SystemExit(f"no samples for {name}")
    classes = sorted(k[7:] for k in rows[-1] if k.startswith("cached_"))
    print(f"=== soak '{name}': {len(rows)} samples, t={rows[-1]['t']:.0f}s, "
          f"window={window:.0f}s ===")
    header = (f"{'window':>9} {'static':>8} {'tex':>7} {'vid':>7} {'nodes':>7} {'res':>6} "
              f"{'objs':>7} {'orph':>5} {'entities':>8} " + " ".join(f"{c[:9]:>9}" for c in classes))
    print(header)
    bucket_start = rows[0]["t"]
    bucket = []
    for row in rows:
        if row["t"] - bucket_start >= window:
            emit(bucket, classes, bucket_start)
            bucket = []
            bucket_start = row["t"]
        bucket.append(row)
    if bucket:
        emit(bucket, classes, bucket_start)

    # growth over the whole run (least squares on static_mib vs t)
    n = len(rows)
    xs = [r["t"] for r in rows]
    ys = [r["static_mib"] for r in rows]
    mx, my = mean(xs), mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0.0
    print(f"\nstatic memory: first sample {ys[0]:.2f} MiB, last {ys[-1]:.2f} MiB, "
          f"linear slope {slope * 3600:.2f} MiB/hour over {xs[-1] - xs[0]:.0f}s")
    first_third = mean(ys[: max(1, n // 3)])
    last_third = mean(ys[-max(1, n // 3):])
    print(f"mean of first third {first_third:.2f} MiB -> last third {last_third:.2f} MiB "
          f"({last_third - first_third:+.2f} MiB)")
    # the drift after the first 10 minutes, where the acceptance also started
    # reading it (cache warm-up excluded)
    steady = [r for r in rows if r["t"] >= 600.0]
    if len(steady) > 10:
        sx = [r["t"] for r in steady]
        sy = [r["static_mib"] for r in steady]
        smx, smy = mean(sx), mean(sy)
        sden = sum((x - smx) ** 2 for x in sx)
        sslope = sum((x - smx) * (y - smy) for x, y in zip(sx, sy)) / sden if sden else 0.0
        print(f"after t=600s ({len(steady)} samples): slope {sslope * 3600:.2f} MiB/hour, "
              f"{sy[0]:.2f} -> {sy[-1]:.2f} MiB")
    # like-for-like: the acceptance compared the first and last ten samples with
    # the entity count low (quiet phase). Same comparison here, and a
    # phase-controlled one (each phase's samples in the first vs second half).
    quiet = [r for r in rows if r.get("entities", 0) <= 3]
    if len(quiet) >= 6:
        head, tail = quiet[:10], quiet[-10:]
        print(f"quiet samples (entities<=3): first {len(head)} mean "
              f"{mean([r['static_mib'] for r in head]):.2f} MiB, last {len(tail)} mean "
              f"{mean([r['static_mib'] for r in tail]):.2f} MiB "
              f"({mean([r['static_mib'] for r in tail]) - mean([r['static_mib'] for r in head]):+.2f} MiB)")
    half = xs[-1] / 2.0
    print(f"\n{'phase':>10} {'n1/n2':>7} {'first half MiB':>15} {'second half MiB':>16} {'delta':>8}")
    for phase in sorted(set(r["phase"] for r in rows)):
        early = [r["static_mib"] for r in rows if r["phase"] == phase and r["t"] < half]
        late = [r["static_mib"] for r in rows if r["phase"] == phase and r["t"] >= half]
        if not early or not late:
            continue
        print(f"{phase:>10} {len(early):>3}/{len(late):<3} {mean(early):>15.2f} "
              f"{mean(late):>16.2f} {mean(late) - mean(early):>+8.2f}")
    if final:
        print("\nframe histogram: " + json.dumps(final.get("frame_hist", {})))
        print(f"frames={final.get('frames')} spikes(>= {final.get('spike_ms_threshold')}ms)="
              f"{final.get('spike_count')} cycles={final.get('cycles')} "
              f"casts={final.get('casts')} kills={final.get('kills')} "
              f"transfers={final.get('transfers')} mounts={final.get('mounts')}")
        accounting = final.get("phase_accounting", {})
        print(f"\n{'phase':>10} {'runs':>5} {'seconds':>9} {'static delta MiB':>18} "
              f"{'per run KiB':>12} {'casts':>7} {'kills':>6} {'transfers':>10} {'mounts':>7}")
        for phase, acc in accounting.items():
            runs = max(1, int(acc.get("runs", 0)))
            total = float(acc.get("mem_kib", 0.0))
            print(f"{phase:>10} {runs:>5} {float(acc.get('seconds', 0.0)):>9.1f} "
                  f"{total / 1024.0:>18.3f} {total / runs:>12.1f} {int(acc.get('casts', 0)):>7} "
                  f"{int(acc.get('kills', 0)):>6} {int(acc.get('transfers', 0)):>10} "
                  f"{int(acc.get('mounts', 0)):>7}")


def emit(bucket, classes, bucket_start):
    def m(key):
        return mean([r.get(key, 0.0) for r in bucket])
    cached = " ".join(f"{m('cached_' + c):>9.1f}" for c in classes)
    print(f"{bucket_start:>9.0f} {m('static_mib'):>8.2f} {m('tex_mib'):>7.1f} {m('vid_mib'):>7.1f} "
          f"{m('nodes'):>7.0f} {m('resources'):>6.1f} {m('objects'):>7.0f} {m('orphans'):>5.0f} "
          f"{m('entities'):>8.1f} {cached}")


if __name__ == "__main__":
    main()
