"""Synthesise a seamless rain loop (assets/audio/ambience/rain.wav): a soft hiss
of filtered noise, a low patter band and thousands of tiny drop ticks, cross-
faded at the seam so it loops cleanly. No generator, no licence question.

    python client/tools/audio/make_rain_loop.py
"""
import os
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "assets", "audio", "ambience", "rain.wav"))
RATE = 44100
SECONDS = 18.0
FADE = 1.5


def one_pole(x, a):
    """y[n] = (1-a) x[n] + a y[n-1] (low-pass), vectorised in blocks."""
    y = np.empty_like(x)
    acc = 0.0
    for i in range(0, len(x), 4096):
        block = x[i:i + 4096]
        out = np.empty_like(block)
        for j, v in enumerate(block):
            acc = (1.0 - a) * v + a * acc
            out[j] = acc
        y[i:i + 4096] = out
    return y


def main():
    rng = np.random.default_rng(1977)
    n = int((SECONDS + FADE) * RATE)
    white = rng.standard_normal(n).astype(np.float64)
    # hiss: white minus its low part (high-passed), patter: a band around ~1 kHz
    low = one_pole(white, 0.985)
    hiss = (white - low) * 0.16
    band = one_pole(white, 0.86) - one_pole(white, 0.97)
    patter = band * 0.55
    # slow swell so the shower breathes
    t = np.arange(n) / RATE
    swell = 0.82 + 0.18 * np.sin(2 * np.pi * t / 7.3) * np.sin(2 * np.pi * t / 3.1 + 1.0)
    signal = (hiss + patter) * swell
    # drop ticks: short decaying clicks, random pitch
    drops = np.zeros(n)
    for _ in range(int(SECONDS * 260)):
        at = rng.integers(0, n - 800)
        length = rng.integers(120, 600)
        env = np.exp(-np.arange(length) / (length / 5.0))
        freq = rng.uniform(1800, 5200)
        tick = np.sin(2 * np.pi * freq * np.arange(length) / RATE) * env * rng.uniform(0.02, 0.09)
        drops[at:at + length] += tick
    signal += drops
    # seamless loop: cross-fade the tail into the head
    body = int(SECONDS * RATE)
    fade = int(FADE * RATE)
    k = np.linspace(0.0, 1.0, fade)
    loop = signal[:body].copy()
    loop[:fade] = signal[:fade] * k + signal[body:body + fade] * (1.0 - k)
    loop /= np.max(np.abs(loop)) / 0.6
    pcm = (loop * 32767).astype(np.int16)
    with wave.open(OUT, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    print("rain loop ->", OUT, "%.1f s" % (len(pcm) / RATE))


if __name__ == "__main__":
    main()
