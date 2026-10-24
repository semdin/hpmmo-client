"""Reject VFX clips that spill to the frame edge.

An additive flipbook shows a hard square wherever the source touches its border,
so every frame's border band (5 % of the side by default) must stay near black.

  python check_clip_edges.py clip.mp4 [clip2.mp4 ...] [--band 0.05] [--limit 0.03]

Prints the worst frame per clip and exits 1 when any clip is over the limit.
"""
import argparse
import sys

import cv2
import numpy as np


def edge_profile(path, band):
    cap = cv2.VideoCapture(path)
    values = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        lum = frame.max(axis=2).astype(np.float32) / 255.0
        h, w = lum.shape
        b = max(1, int(min(h, w) * band))
        border = np.concatenate([lum[:b].ravel(), lum[-b:].ravel(), lum[:, :b].ravel(), lum[:, -b:].ravel()])
        values.append(float(border.mean()))
    return values


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--band", type=float, default=0.05)
    ap.add_argument("--limit", type=float, default=0.03)
    args = ap.parse_args()
    failed = False
    for path in args.clips:
        values = edge_profile(path, args.band)
        if not values:
            print("[fail] %s: no frames" % path)
            failed = True
            continue
        worst = int(np.argmax(values))
        verdict = "ok" if values[worst] <= args.limit else "fail"
        failed |= verdict == "fail"
        print("[%s] %s: %d frames, worst edge %.3f at frame %d (limit %.3f)"
              % (verdict, path, len(values), values[worst], worst, args.limit))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
