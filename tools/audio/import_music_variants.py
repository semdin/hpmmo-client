"""Import chosen Stable Audio 3 music takes as extra variants of a soundtrack key.

review_alts.py ranks the raw takes of each music key (alts.json lists them, best
first, as Alt 1..3). A picked alt is not a replacement here: it becomes its own
library entry (<key>_alt<n>, file <track>_alt<n>.mp3 next to the original) and
is listed in the base entry's "variants", so AudioManager alternates between
the original and its variants (a variant plays with its base entry's mix).

Per take: stereo, cut to the original's length; a one-shot track gets a 1.5 s
fade-out, a looping one a 2 s crossfade of its tail into its head; levelled to
the original's RMS with a -1 dBFS peak ceiling; written as 160 kbps MP3.

Runs in the Stable Audio 3 venv (soundfile with MP3 support).
Usage: python import_music_variants.py --review ../art/audio_review/alts.json
           --raw ../art/audio_sa3/alts_raw --client . music_castle_a:1 stinger_boss:1,2,3
"""
import argparse, json, os
import numpy as np
import soundfile

PEAK = 10 ** (-1.0 / 20.0)
SOURCE = "Stable Audio 3 small-music (local, CPU); art/audio_sa3/alts_raw/%s"
NOTE = ("Soundtrack variants (*_alt<n>): generated 2026-10-31 with Stable Audio 3 small-music (Stability AI Community "
    "License, free commercial use under US$1M annual revenue), picked in art/audio_review.")


def shape(x, sr, seconds, loop):
    x = x[:int(seconds * sr)].copy()
    if loop:
        k = min(int(2.0 * sr), len(x) // 4)
        ramp = np.sqrt(np.linspace(0.0, 1.0, k))[:, None]
        x[:k] = x[:k] * ramp + x[-k:] * ramp[::-1]
        return x[:-k]
    k = min(len(x), int(1.5 * sr))
    x[-k:] *= np.linspace(1.0, 0.0, k)[:, None]
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("picks", nargs="+", help="key:n[,n...]")
    args = ap.parse_args()
    chosen = json.load(open(args.review, encoding="utf-8"))["chosen"]
    lib_path = os.path.join(args.client, "assets", "audio", "sound_library.json")
    library = json.load(open(lib_path, encoding="utf-8"))
    sounds = library["sounds"]
    for pick in args.picks:
        key, alts = pick.split(":")
        base = sounds[key]
        now, _ = soundfile.read(os.path.join(args.client, base["path"]), dtype="float32", always_2d=True)
        loudness = float(np.sqrt(np.mean(now ** 2)))
        variants = list(base.get("variants", []))
        for n in [int(a) for a in alts.split(",")]:
            take = chosen[key][n - 1]["take"]
            x, sr = soundfile.read(os.path.join(args.raw, take), dtype="float32", always_2d=True)
            x = shape(x, sr, float(base["seconds"]), bool(base["loop"]))
            x *= loudness / (float(np.sqrt(np.mean(x ** 2))) + 1e-9)
            x /= max(1.0, float(np.abs(x).max()) / PEAK)
            name = "%s_alt%d" % (key, n)
            rel = os.path.splitext(base["path"])[0] + "_alt%d.mp3" % n
            soundfile.write(os.path.join(args.client, rel), x, sr, format="MP3", subtype="MPEG_LAYER_III",
                bitrate_mode="CONSTANT", compression_level=0.55)
            entry = {f: v for f, v in base.items() if f != "variants"}
            entry.update({"path": rel, "sample_rate": sr, "seconds": round(len(x) / sr, 3), "source": SOURCE % take})
            sounds[name] = entry
            if name not in variants:
                variants.append(name)
            print(name, take, entry["seconds"])
        base["variants"] = variants
    for field in ["provenance", "license"]:
        if NOTE not in library[field]:
            library[field] = library[field].rstrip(".") + ". " + NOTE
    library["sounds"] = dict(sorted(sounds.items()))
    with open(lib_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(library, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


if __name__ == "__main__":
    main()
