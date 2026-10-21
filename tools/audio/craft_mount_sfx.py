"""Craft the broom take-off cue (`mount`) from the broom's own wind and swoosh.

The ElevenLabs take was a bright 6 kHz hiss that started at full level. This
one is built from sounds that already work in flight, so it belongs to them:
a low cloth/air "whomp" as the rider swings up (broom_swoosh_01), then a
swell of the broom wind that rises in pitch and opens up as the broom lifts,
low-passed so nothing is shrill. No generator, no cost.

Usage: python craft_mount_sfx.py [--client ../..] [--art ../../../art/audio_v2]
Writes assets/audio/character/mount.wav (mono 44.1 kHz) and, when the raw
art folder exists, the same take as its source so a re-import keeps it.
"""
import argparse
import os
import wave

import numpy as np

SR = 44100


def read(path):
    with wave.open(path) as w:
        n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    assert sr == SR, sr
    return a


def write(path, a):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def one_pole_lowpass(a, cutoff):
    """Cutoff may be an array (a sweeping filter)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), a.shape)
    k = 1.0 - np.exp(-2.0 * np.pi * cutoff / SR)
    out = np.empty_like(a)
    y = 0.0
    for i in range(len(a)):
        y += k[i] * (a[i] - y)
        out[i] = y
    return out


def varispeed(a, start_rate, end_rate, length):
    """Read `a` with a playback rate gliding start->end (a rising pitch)."""
    rate = np.linspace(start_rate, end_rate, length)
    pos = np.cumsum(rate)
    pos = pos[pos < len(a) - 1]
    return np.interp(pos, np.arange(len(a)), a)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=os.path.join(here, "..", ".."))
    ap.add_argument("--art", default=os.path.join(here, "..", "..", "..", "art", "audio_v2"))
    args = ap.parse_args()
    char = os.path.join(args.client, "assets", "audio", "character")
    wind = read(os.path.join(char, "broom_wind.wav"))
    whomp = read(os.path.join(char, "broom_swoosh_01.wav"))

    length = int(1.25 * SR)
    t = np.arange(length) / SR
    # The gust at 2.55-4.0 s of the wind bed, sped up as the broom climbs.
    gust = varispeed(wind[int(2.55 * SR):int(4.6 * SR)], 0.85, 1.35, length)
    gust = np.pad(gust, (0, length - len(gust)))
    gust = one_pole_lowpass(gust, 700.0 + 2600.0 * np.clip(t / 0.7, 0, 1) ** 1.5)
    swell = np.clip(t / 0.42, 0, 1) ** 1.6 * np.exp(-np.clip(t - 0.55, 0, None) * 3.2)
    gust *= swell / max(1e-6, np.abs(gust * swell).max())

    # The swing up: the low swoosh, a touch slower and darker.
    body = varispeed(whomp, 0.82, 0.82, int(len(whomp) / 0.82))
    body = one_pole_lowpass(body, 1800.0)
    body /= max(1e-6, np.abs(body).max())
    mix = gust * 0.8
    mix[: len(body)] += body[: length] * 0.55

    # Gentle fades and a level that sits with the other character cues.
    fade = int(0.012 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-int(0.25 * SR):] *= np.linspace(1, 0, int(0.25 * SR)) ** 2
    mix *= 0.6 / np.abs(mix).max()
    write(os.path.join(char, "mount.wav"), mix)
    if os.path.isdir(args.art):
        write(os.path.join(args.art, "mount.wav"), mix)
    print("mount.wav %.2f s, rms %.3f" % (length / SR, float(np.sqrt(np.mean(mix ** 2)))))


if __name__ == "__main__":
    main()
