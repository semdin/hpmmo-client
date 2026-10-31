"""Import the generated ambience / interface / footstep / music set into the game.

Sources: <art>/<sound_library key>.wav (ElevenLabs Sound Effects v2 via fal.ai,
pcm_44100) and <art>/<key>.mp3 (ElevenLabs Music v2.5), described by
tools/audio/audio_spec.json (written by make_audio_spec.py). For every key whose
source exists this writes the asset at the spec's path and (re)creates the
sound_library.json entry; keys with no source yet keep whatever entry they had.

Processing (WAV):
  * positional sounds are downmixed to mono (AudioStreamPlayer3D); flat beds
    and interface sounds keep their stereo image;
  * one-shots: leading/trailing silence trimmed, 10 ms fade-out;
  * loops: a 120 ms equal-power crossfade of the tail into the head (the model
    already aims for a seamless loop; this removes any residual click);
  * RMS matched (one-shots -17 dBFS, beds -20) under a -1 dBFS peak ceiling,
    so the per-entry gain_db is what mixes them.
MP3 music is copied as is (Godot imports MP3 natively; the loop flag is set by
AudioManager from the library at load time).

`--retire` also drops library entries (and their files) that no spec knows
about any more - the old synthesised set.

Usage: python import_audio_spec.py --art ../../../art/audio_v2 --client ../.. [--retire]
"""
import argparse, json, os, shutil, wave
import numpy as np

ONE_SHOT_RMS_DB = -17.0
BED_RMS_DB = -20.0
PEAK_DB = -1.0


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return data.reshape(-1, ch), sr


def write_wav(path, frames, sr):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pcm = (np.clip(frames, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(frames.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def db(x):
    return 20.0 * np.log10(max(1e-9, x))


def process(frames, sr, loop, mono):
    if mono and frames.shape[1] > 1:
        frames = frames.mean(axis=1, keepdims=True)
    level = np.abs(frames).max(axis=1)
    peak = level.max() + 1e-9
    if not loop:
        above = np.nonzero(level > peak * 0.003)[0]
        if len(above):
            start = max(0, above[0] - int(0.002 * sr))
            end = min(len(frames), above[-1] + int(0.03 * sr))
            frames = frames[start:end].copy()
        fade = min(len(frames), int(0.010 * sr))
        frames[-fade:] *= np.linspace(1.0, 0.0, fade)[:, None]
    else:
        xf = int(0.12 * sr)
        if len(frames) > 4 * xf:
            t = np.linspace(0.0, np.pi / 2, xf)[:, None]
            head = frames[:xf].copy()
            tail = frames[-xf:].copy()
            frames = frames[:-xf].copy()
            frames[:xf] = head * np.sin(t) + tail * np.cos(t)
    rms = float(np.sqrt(np.mean(frames ** 2)) + 1e-9)
    target = BED_RMS_DB if loop else ONE_SHOT_RMS_DB
    frames = frames * 10 ** ((target - db(rms)) / 20.0)
    pk = float(np.abs(frames).max() + 1e-9)
    ceiling = 10 ** (PEAK_DB / 20.0)
    if pk > ceiling:
        frames = frames * (ceiling / pk)
    return frames


def remove_asset(client, rel):
    for suffix in ("", ".import"):
        path = os.path.join(client, rel + suffix)
        if os.path.exists(path):
            os.remove(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--retire", action="store_true")
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    spec = json.load(open(os.path.join(here, "audio_spec.json"), encoding="utf-8"))
    fal_spec_path = os.path.join(args.art, "..", "audio_fal", "sfx_spec.json")
    fal_keys = set(json.load(open(fal_spec_path, encoding="utf-8"))["sounds"].keys()) if os.path.exists(fal_spec_path) else set()
    lib_path = os.path.join(args.client, "assets", "audio", "sound_library.json")
    library = json.load(open(lib_path, encoding="utf-8"))
    sounds = library["sounds"]
    done, missing = [], []
    for key, item in spec["sounds"].items():
        ext = ".mp3" if item["kind"] == "music" else ".wav"
        src = os.path.join(args.art, key + ext)
        if not os.path.exists(src):
            missing.append(key)
            continue
        old = sounds.get(key)
        out = os.path.join(args.client, item["path"])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if ext == ".mp3":
            shutil.copyfile(src, out)
            seconds = os.path.getsize(src) * 8.0 / 128000.0
            sr = 44100
        else:
            frames, sr = read_wav(src)
            frames = process(frames, sr, bool(item["loop"]), bool(item["spatial"]))
            if key.startswith("step_"):
                # One step per file: a take that holds a second footfall would
                # double the cadence, so keep only the first transient.
                cap = int((0.38 if "water" in key else 0.30) * sr)
                if len(frames) > cap:
                    frames = frames[:cap].copy()
                    fade = int(0.06 * sr)
                    frames[-fade:] *= np.linspace(1.0, 0.0, fade)[:, None]
            write_wav(out, frames, sr)
            seconds = len(frames) / sr
        if old is not None and old.get("path") != item["path"]:
            remove_asset(args.client, old["path"])
        sounds[key] = {
            "path": item["path"],
            "bus": item["bus"],
            "gain_db": item["gain_db"],
            "pitch_variation": item["pv"],
            "loop": bool(item["loop"]),
            "loop_mode": "forward" if item["loop"] else "disabled",
            "spatial": bool(item["spatial"]),
            "sample_rate": sr,
            "seconds": round(seconds, 3),
            "purpose": item["text"].split(", no music")[0].split(", seamless loop")[0],
            "source": "fal.ai %s; tools/audio/audio_spec.json" % (spec["music_model"] if ext == ".mp3" else spec["sfx_model"]),
        }
        if old is not None and old.get("variants"):
            sounds[key]["variants"] = old["variants"]
        done.append(key)
    retired = []
    if args.retire:
        # ui_levelup / ui_quest / ui_quest_complete are ElevenLabs takes kept
        # outside sfx_spec.json (art/audio_fal/*.wav).
        known = set(spec["sounds"].keys()) | fal_keys | {"ui_levelup", "ui_quest", "ui_quest_complete"}
        # Variant takes (import_music_variants.py, basic-cast takes) belong to their base key.
        known |= {v for entry in sounds.values() for v in entry.get("variants", [])}
        for key in list(sounds.keys()):
            if key not in known:
                remove_asset(args.client, sounds[key]["path"])
                del sounds[key]
                retired.append(key)
    library["generator"] = "client/tools/audio/import_audio_spec.py + import_fal_sfx.py"
    library["generated"] = "2026-10-19"
    # Only a fresh library gets the base text: notes appended since (Stable Audio 3) stay.
    library.setdefault("provenance", ("All sounds generated on fal.ai: spell, basic-attack and creature cues with ElevenLabs Sound Effects v2 "
        "(prompts art/audio_fal/sfx_spec.json, import_fal_sfx.py); ambience, footsteps, interface, broom and remaining creature "
        "cues with ElevenLabs Sound Effects v2 and the soundtrack with ElevenLabs Music v2.5 (prompts tools/audio/audio_spec.json, "
        "import_audio_spec.py)."))
    library.setdefault("license", "generated output, commercial use permitted under the ElevenLabs / fal.ai terms of the generating account")
    library["sounds"] = dict(sorted(sounds.items()))
    with open(lib_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(library, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("imported %d, waiting for source %d, retired %d" % (len(done), len(missing), len(retired)))
    if missing:
        print("missing:", " ".join(missing))
    if retired:
        print("retired:", " ".join(retired))


if __name__ == "__main__":
    main()
