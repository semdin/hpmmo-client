"""Import generated spell and creature SFX (fal.ai ElevenLabs Sound Effects v2) into the game.

Source WAVs live in art/audio_fal/<sound_library key>.wav with their prompts in
art/audio_fal/sfx_spec.json. For each key this writes the file the sound
library already points at (assets/audio/spells/<spell>/<stage>.wav), so every
caller keeps its key, and refreshes that entry in sound_library.json.

Processing, per file:
  * downmix to mono (spell sounds are played positionally on AudioStreamPlayer3D);
  * trim leading silence (game SFX must start on the frame they are triggered);
  * one-shots: 8 ms fade-out at the tail, tail silence trimmed;
  * loops: a 60 ms equal-power crossfade of the tail into the head so the
    import's forward loop has no click;
  * RMS-match to the library's existing targets (one-shots -17 dBFS, beds -20)
    with a -1 dBFS peak ceiling, so the authored per-entry gain_db still mixes.

A spec (or one of its sounds) may name its own `source` (with %s for the key) and a `note` appended
to the library's provenance and licence, for sounds made elsewhere (Stupefy:
Stable Audio 3, art/audio_sa3). The library's own provenance and licence text
is left as it is otherwise.

Usage: python import_fal_sfx.py --art ../art/audio_fal --client . [--keys k1 k2]
"""
import argparse, json, os, wave
import numpy as np

ONE_SHOT_RMS_DB = -17.0
BED_RMS_DB = -20.0
PEAK_DB = -1.0


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return data.reshape(-1, ch).mean(axis=1), sr


def write_wav(path, mono, sr):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pcm = (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def db(x):
    return 20.0 * np.log10(max(1e-9, x))


def process(mono, sr, loop):
    # Leading silence: the first sample above -50 dBFS of the peak, minus 2 ms.
    peak = np.abs(mono).max() + 1e-9
    above = np.nonzero(np.abs(mono) > peak * 0.003)[0]
    if len(above) and not loop:
        start = max(0, above[0] - int(0.002 * sr))
        end = min(len(mono), above[-1] + int(0.02 * sr))
        mono = mono[start:end]
    if loop:
        xf = int(0.06 * sr)
        if len(mono) > 3 * xf:
            t = np.linspace(0.0, np.pi / 2, xf)
            head = mono[:xf].copy()
            tail = mono[-xf:].copy()
            mono = mono[:-xf].copy()
            mono[:xf] = head * np.sin(t) + tail * np.cos(t)
    else:
        fade = min(len(mono), int(0.008 * sr))
        mono[-fade:] *= np.linspace(1.0, 0.0, fade)
    rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-9)
    target = BED_RMS_DB if loop else ONE_SHOT_RMS_DB
    gain = 10 ** ((target - db(rms)) / 20.0)
    mono = mono * gain
    pk = float(np.abs(mono).max() + 1e-9)
    ceiling = 10 ** (PEAK_DB / 20.0)
    if pk > ceiling:
        mono = mono * (ceiling / pk)
    return mono


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--keys", nargs="*", help="import only these sounds")
    args = ap.parse_args()
    spec = json.load(open(os.path.join(args.art, "sfx_spec.json"), encoding="utf-8"))
    lib_path = os.path.join(args.client, "assets", "audio", "sound_library.json")
    library = json.load(open(lib_path, encoding="utf-8"))
    sounds = library["sounds"]
    done = []
    for key, item in spec["sounds"].items():
        if args.keys and key not in args.keys:
            continue
        src = os.path.join(args.art, key + ".wav")
        if not os.path.exists(src):
            print("missing source", src)
            continue
        entry = sounds.get(key)
        if entry is None:
            print("no library entry for", key)
            continue
        loop = bool(item.get("loop", False))
        mono, sr = read_wav(src)
        mono = process(mono, sr, loop)
        out = os.path.join(args.client, entry["path"])
        write_wav(out, mono, sr)
        entry["seconds"] = round(len(mono) / sr, 3)
        entry["sample_rate"] = sr
        entry["loop"] = loop
        entry["loop_mode"] = "forward" if loop else "disabled"
        entry["purpose"] = item["text"].split(", no music")[0].split(", game sound effect")[0]
        source = item.get("source", spec.get("source"))
        if not source:
            source = "fal.ai %s (ElevenLabs Sound Effects v2); art/audio_fal/%%s.wav" % spec["model"]
        entry["source"] = source % key if "%s" in source else source
        done.append(key)
    note = spec.get("note")
    if note:
        for field in ["provenance", "license"]:
            if note not in library[field]:
                library[field] = library[field].rstrip(".") + ". " + note
    with open(lib_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(library, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("imported %d sounds" % len(done))


if __name__ == "__main__":
    main()
