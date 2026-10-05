#!/usr/bin/env python3
"""Phase 12 sound library - PROJECT-ORIGINAL synthesis.

    python client/tools/audio/synth_phase12.py --out client/assets/audio

Everything the game plays is generated here from deterministic seeded DSP (the
standard library `wave` module, no external audio library, no download, no
third-party sample). Re-running the script reproduces the files byte-for-byte.

Coverage (plan.md 12.5):

    spells/<spell>/cast|travel|impact|sustain|end.wav
        all seven spells with their own cast/travel/impact/end variants - never
        one generic whoosh for everything
    footsteps/<surface>_<n>.wav          five surfaces, three variants each
    character/                           robe movement, mount/dismount, broom
                                         wind (loop), landing
    monsters/                            spider move/bite/death, boss attacks,
                                         boss death
    ui/                                  button, confirm, cancel, error, loot,
                                         level up, quest, upgrade, chat
    transitions/                         map transfer, door open/close
    ambience/                            exterior wind + birds, fire, candles,
                                         distant activity, Great Hall, library,
                                         dungeon room tones, moving-stair mechanism

The Great Hall, library and dungeon are acoustically distinct: different
reverb character (large hall / tight dry room / wet stone basement), different
beds and different incident sounds. Loops are seam-continuous (the tail is
crossfaded into the head and the seam continuity is asserted).

Provenance is recorded in assets/audio/CREDITS-phase12.md and per-file in the
manifest: all project-original, synthesised by this script.
"""

import argparse
import array
import json
import math
import os
import random
import struct
import sys
import time
import wave

RATE_SFX = 44100
RATE_AMB = 22050


# ------------------------------------------------------------------ primitives

def zeros(n):
    return array.array("d", bytes(8 * n))


def clamp(value, lo, hi):
    return lo if value < lo else (hi if value > hi else value)


class Rng:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def uni(self, a, b):
        return a + (b - a) * self.r.random()

    def sym(self, amount):
        return (self.r.random() * 2.0 - 1.0) * amount

    def int(self, a, b):
        return self.r.randint(a, b)

    def pick(self, seq):
        return seq[self.r.randrange(len(seq))]


def white(rng, n):
    r = rng.r
    return array.array("d", [r.random() * 2.0 - 1.0 for _ in range(n)])


def sine(n, freq, rate, phase=0.0, amp=1.0):
    """freq may be a float or a callable(progress 0..1) -> Hz."""
    out = zeros(n)
    ph = phase
    if callable(freq):
        for i in range(n):
            f = freq(i / float(max(1, n - 1)))
            ph += math.tau * f / rate
            out[i] = amp * math.sin(ph)
    else:
        step = math.tau * freq / rate
        for i in range(n):
            ph += step
            out[i] = amp * math.sin(ph)
    return out


def _sweep_freq(f0, f1, shape):
    if shape == "lin":
        return lambda p: f0 + (f1 - f0) * p
    if shape == "exp":
        ratio = max(1e-6, f1 / max(1e-6, f0))
        return lambda p: f0 * (ratio ** p)
    return lambda p: f0


# ---------------------------------------------------------------- biquads

def biquad(sig, b0, b1, b2, a1, a2):
    out = zeros(len(sig))
    x1 = x2 = y1 = y2 = 0.0
    for i, x0 in enumerate(sig):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def _rbj(kind, cutoff, q, rate):
    w0 = math.tau * clamp(cutoff, 10.0, rate * 0.45) / rate
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2.0 * max(0.05, q))
    if kind == "lp":
        b0 = (1.0 - cw) / 2.0
        b1 = 1.0 - cw
        b2 = b0
        a0 = 1.0 + alpha
        a1 = -2.0 * cw
        a2 = 1.0 - alpha
    elif kind == "hp":
        b0 = (1.0 + cw) / 2.0
        b1 = -(1.0 + cw)
        b2 = b0
        a0 = 1.0 + alpha
        a1 = -2.0 * cw
        a2 = 1.0 - alpha
    else:  # bandpass (constant peak gain)
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cw
        a2 = 1.0 - alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def lowpass(sig, cutoff, q=0.707, rate=RATE_SFX):
    return biquad(sig, *_rbj("lp", cutoff, q, rate))


def highpass(sig, cutoff, q=0.707, rate=RATE_SFX):
    return biquad(sig, *_rbj("hp", cutoff, q, rate))


def bandpass(sig, center, q=1.0, rate=RATE_SFX):
    return biquad(sig, *_rbj("bp", center, q, rate))


def resonators(sig, partials, rate=RATE_SFX):
    """Sum of bandpasses - inharmonic metal/wood/glass bodies."""
    out = zeros(len(sig))
    for freq, q, amp in partials:
        band = bandpass(sig, freq, q, rate)
        for i in range(len(out)):
            out[i] += band[i] * amp
    return out


def pink(rng, n):
    """Paul Kellet's economical pink filter over white noise."""
    w = white(rng, n)
    out = zeros(n)
    b = [0.0] * 7
    for i, x in enumerate(w):
        b[0] = 0.99886 * b[0] + x * 0.0555179
        b[1] = 0.99332 * b[1] + x * 0.0750759
        b[2] = 0.96900 * b[2] + x * 0.1538520
        b[3] = 0.86650 * b[3] + x * 0.3104856
        b[4] = 0.55000 * b[4] + x * 0.5329522
        b[5] = -0.7616 * b[5] - x * 0.0168980
        out[i] = (b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + x * 0.5362) * 0.11
        b[6] = x * 0.115926
    return out


def brown(rng, n):
    w = white(rng, n)
    out = zeros(n)
    acc = 0.0
    for i, x in enumerate(w):
        acc = clamp(acc + x * 0.02, -1.0, 1.0) * 0.995
        out[i] = acc
    return out


# ---------------------------------------------------------------- envelopes

def env_shape(n, points):
    """Piecewise-linear envelope from [(t, v), ...] with t in 0..1."""
    out = zeros(n)
    if not points:
        return out
    for i in range(n):
        t = i / float(max(1, n - 1))
        v = points[-1][1]
        for k in range(len(points) - 1):
            t0, v0 = points[k]
            t1, v1 = points[k + 1]
            if t <= t1:
                k2 = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
                v = v0 + (v1 - v0) * k2
                break
        out[i] = v
    return out


def adsr(n, attack, decay, sustain, release):
    a = max(1, int(attack * n))
    d = max(1, int(decay * n))
    r = max(1, int(release * n))
    s = max(0, n - a - d - r)
    pts = []
    if a:
        pts.append((0.0, 0.0))
        pts.append((a / float(n), 1.0))
    if d:
        pts.append(((a + d) / float(n), sustain))
    if s:
        pts.append(((a + d + s) / float(n), sustain))
    pts.append((1.0, 0.0))
    return env_shape(n, pts)


def expdecay(n, tau):
    out = zeros(n)
    for i in range(n):
        out[i] = math.exp(-(i / float(max(1, n - 1))) / max(1e-4, tau))
    return out


def smoothstep(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# ---------------------------------------------------------------- mixing

def mix(*sigs):
    n = max(len(s) for s in sigs)
    out = zeros(n)
    for s in sigs:
        for i, v in enumerate(s):
            out[i] += v
    return out


def gain(sig, g):
    return array.array("d", [v * g for v in sig])


def apply_env(sig, env):
    return array.array("d", [sig[i] * env[i] for i in range(len(sig))])


def delay(sig, samples):
    out = zeros(len(sig) + samples)
    for i, v in enumerate(sig):
        out[i + samples] += v
    return out


def soft_clip(sig, drive=1.0):
    return array.array("d", [math.tanh(v * drive) for v in sig])


def normalize(sig, peak=0.89):
    top = 0.0
    for v in sig:
        av = abs(v)
        if av > top:
            top = av
    if top < 1e-9:
        return sig
    g = peak / top
    return array.array("d", [v * g for v in sig])


def fade_edges(sig, samples):
    n = len(sig)
    samples = min(samples, n // 3)
    for i in range(samples):
        g = i / float(samples)
        sig[i] *= g
        sig[n - 1 - i] *= g
    return sig


def crossfade_loop(sig, fade_samples):
    """Cut a seamless loop out of a longer bed.

    The loop occupies sig[0:L] with L = n - fade. Its head is blended with
    sig[L:L+fade] - the samples that naturally CONTINUE the end of the loop -
    so the wrap L-1 -> 0 is continuous in both value and slope rather than a
    jump. Blending the head with the tail instead (a common mistake) leaves a
    step at the seam, which is exactly what the validation check catches.
    """
    n = len(sig)
    fade = min(fade_samples, n // 4)
    if fade <= 1:
        return sig
    length = n - fade
    out = array.array("d", sig[:length])
    for i in range(fade):
        t = i / float(fade)
        out[i] = sig[i] * t + sig[length + i] * (1.0 - t)
    return out


def reverb(sig, rate, decay=1.6, mix_amount=0.3, damp=4200.0, size=1.0):
    """Schroeder reverb: four combs into two allpasses.

    The comb delays are scaled by `size` so a hall, a room and a stone basement
    are genuinely different spaces rather than the same tail at one gain.
    """
    combs = [1116, 1188, 1277, 1356]
    wet = zeros(len(sig))
    for delay_ms, fb in ((combs[0], 0.78), (combs[1], 0.74), (combs[2], 0.71), (combs[3], 0.68)):
        d = max(8, int(rate * delay_ms / 1000.0 * size))
        buf = zeros(d)
        idx = 0
        length = int(decay * 1.6)
        g = clamp(fb * (0.5 + 0.5 * decay / 2.0), 0.0, 0.94)
        for i in range(len(sig)):
            y = buf[idx]
            wet[i] += y * 0.25
            buf[idx] = sig[i] + y * g
            idx += 1
            if idx >= d:
                idx = 0
    wet = lowpass(wet, damp, 0.7, rate)
    out = zeros(len(sig))
    for i in range(len(sig)):
        out[i] = sig[i] * (1.0 - mix_amount) + wet[i] * mix_amount
    return out


def clip_offsets(sig, offsets, body):
    """Sparse events (drips, birds, distant thumps) placed at offsets."""
    n = len(sig)
    out = array.array("d", sig)
    for off in offsets:
        if off + len(body) <= n:
            for i, v in enumerate(body):
                out[off + i] += v
    return out


def noise_burst(rng, rate, seconds, lo=400.0, hi=6000.0, q=0.9):
    n = int(rate * seconds)
    w = white(rng, n)
    band = bandpass(w, math.sqrt(lo * hi), q, rate)
    return apply_env(band, expdecay(n, 0.28))


def crackles(rng, rate, seconds, density=14.0, bright=5200.0, level=0.5):
    """Fire/ember crackle bed: sparse filtered clicks."""
    n = int(rate * seconds)
    out = zeros(n)
    t = 0.0
    while t < seconds:
        gap = rng.uni(0.35, 1.6) / density
        t += gap
        start = int(t * rate)
        if start >= n - 64:
            break
        length = rng.int(24, 110)
        length = min(length, n - start)
        decay = expdecay(length, rng.uni(0.06, 0.22))
        for i in range(length):
            out[start + i] += (rng.uni(-1.0, 1.0)) * decay[i] * level
        t += length / float(rate) + gap
    return lowpass(highpass(out, 500.0, 0.7, rate), bright, 0.7, rate)


def ping(rate, freq, seconds, decay=0.25, partials=((1.0, 1.0), (2.01, 0.45), (3.02, 0.22), (4.9, 0.12))):
    n = int(rate * seconds)
    out = zeros(n)
    env = expdecay(n, decay)
    for ratio, amp in partials:
        tone = sine(n, freq * ratio, rate, amp=amp)
        for i in range(n):
            out[i] += tone[i] * env[i]
    return out


# ------------------------------------------------------------------ writing

def write_wav(path, sig, rate):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = array.array("h", [int(clamp(v, -1.0, 1.0) * 32767.0) for v in sig])
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())


# ------------------------------------------------------------------ spells

def spell_library(rng):
    """Every spell gets its own voice: cast, travel, impact and end."""
    out = {}

    def add(spell, stage, sig, rate=RATE_SFX, loop=False, gain_db=-4.0,
            pitch_var=0.03, spatial=True, purpose=""):
        out["spell_%s_%s" % (spell, stage)] = dict(
            path="spells/%s/%s.wav" % (spell, stage), sig=sig, rate=rate,
            loop=loop, bus="sfx", gain_db=gain_db, pitch_var=pitch_var,
            spatial=spatial, purpose=purpose,
            loop_mode="forward" if loop else "disabled")

    # --- basic_cast: a small bright flick, light hiss, tiny fizz
    n = int(RATE_SFX * 0.16)
    snap = apply_env(bandpass(white(rng, n), 2600, 1.1, RATE_SFX), adsr(n, 0.004, 0.05, 0.10, 0.5))
    flick = apply_env(gain(sine(n, _sweep_freq(1900, 1250, "exp"), RATE_SFX), 0.55), expdecay(n, 0.18))
    add("basic_cast", "cast", normalize(mix(snap, flick), 0.8), gain_db=-7.0,
        pitch_var=0.05, purpose="wand flick: bright noise snap + short downward chirp")
    n = int(RATE_SFX * 0.5)
    hiss = bandpass(white(rng, n), 3200, 0.7, RATE_SFX)
    add("basic_cast", "travel", normalize(apply_env(hiss, env_shape(n, [(0, 0.0), (0.1, 0.9), (0.85, 0.8), (1.0, 0.0)])), 0.5),
        gain_db=-13.0, loop=True, purpose="light airy hiss while the bolt is in flight")
    n = int(RATE_SFX * 0.3)
    tick = apply_env(bandpass(white(rng, n), 3400, 1.4, RATE_SFX), adsr(n, 0.002, 0.03, 0.05, 0.7))
    sparkle = ping(RATE_SFX, 3100, 0.3, 0.09)
    add("basic_cast", "impact", normalize(mix(gain(tick, 1.0), gain(sparkle, 0.35)), 0.85),
        gain_db=-6.0, pitch_var=0.07, purpose="irregular fleck impact: tick plus a brief sparkle")
    add("basic_cast", "end", normalize(gain(apply_env(bandpass(white(rng, int(RATE_SFX * 0.22)), 2200, 0.8, RATE_SFX),
                                                          expdecay(int(RATE_SFX * 0.22), 0.22)), 0.5), 0.7),
        gain_db=-14.0, purpose="small glow decay after the hit")

    # --- stupefy: red stun - low-mid rise, wobbling travel, heavy hit, shimmer end
    n = int(RATE_SFX * 0.32)
    rise = apply_env(gain(sine(n, _sweep_freq(170, 520, "exp"), RATE_SFX), 0.8), env_shape(n, [(0, 0.1), (0.5, 1.0), (0.75, 0.9), (1.0, 0.0)]))
    body = apply_env(bandpass(white(rng, n), 900, 1.2, RATE_SFX), adsr(n, 0.01, 0.1, 0.5, 0.4))
    add("stupefy", "cast", normalize(mix(rise, gain(body, 0.6)), 0.9), gain_db=-5.0,
        pitch_var=0.04, purpose="charge-up: rising tone with a resonant edge")
    n = int(RATE_SFX * 0.6)
    wob = zeros(n)
    for i in range(n):
        wob[i] = math.sin(math.tau * 7.0 * i / RATE_SFX) * 0.5 + 0.5
    air = bandpass(white(rng, n), 1500, 1.1, RATE_SFX)
    air = array.array("d", [air[i] * (0.55 + 0.45 * wob[i]) for i in range(n)])
    add("stupefy", "travel", normalize(apply_env(air, env_shape(n, [(0, 0.0), (0.12, 0.95), (0.85, 0.85), (1.0, 0.0)])), 0.55),
        gain_db=-11.0, loop=True, purpose="wobbling mid-band whoosh in flight")
    n = int(RATE_SFX * 0.42)
    thump = apply_env(gain(sine(n, _sweep_freq(150, 60, "exp"), RATE_SFX), 0.9), expdecay(n, 0.16))
    hit = apply_env(bandpass(white(rng, n), 700, 0.9, RATE_SFX), adsr(n, 0.002, 0.05, 0.2, 0.7))
    ring = ping(RATE_SFX, 880, 0.42, 0.22, partials=((1.0, 1.0), (2.35, 0.4), (3.9, 0.18)))
    add("stupefy", "impact", normalize(mix(gain(thump, 1.0), gain(hit, 0.7), gain(ring, 0.35)), 0.95),
        gain_db=-3.0, pitch_var=0.03, purpose="body hit + stun ring (the ring matches the stun status)")
    shimmer = ping(RATE_SFX, 1180, 0.6, 0.4, partials=((1.0, 1.0), (1.48, 0.5), (2.7, 0.25)))
    n2 = len(shimmer)
    trem = array.array("d", [0.55 + 0.45 * math.sin(math.tau * 5.0 * i / RATE_SFX) for i in range(n2)])
    add("stupefy", "end", normalize(apply_env(shimmer, apply_env(expdecay(n2, 0.35), trem)), 0.6),
        gain_db=-12.0, purpose="distinct stun end cue as the status expires")

    # --- incendio: fire onset, roaring sustain, burst, extinguish
    n = int(RATE_SFX * 0.45)
    roar = apply_env(lowpass(white(rng, n), 1800, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.16, 1.0), (0.6, 0.85), (1.0, 0.15)]))
    blast = apply_env(gain(sine(n, _sweep_freq(120, 55, "exp"), RATE_SFX), 0.8), expdecay(n, 0.18))
    add("incendio", "cast", normalize(mix(crackles(rng, RATE_SFX, 0.45, 26.0), gain(roar, 0.9), gain(blast, 0.8)), 0.95),
        gain_db=-3.0, pitch_var=0.03, purpose="fire onset: roar + crackle + low thump")
    n = int(RATE_AMB * 2.0)
    bed = lowpass(pink(rng, n), 2400, 0.8, RATE_AMB)
    bed = array.array("d", [v * (0.72 + 0.28 * math.sin(math.tau * 0.7 * i / RATE_AMB)) for i, v in enumerate(bed)])
    bed = mix(bed, gain(crackles(rng, RATE_AMB, 2.0, 9.0, 5200.0, 0.55), 0.9))
    add("incendio", "sustain", normalize(crossfade_loop(bed, int(RATE_AMB * 0.25)), 0.7), rate=RATE_AMB,
        loop=True, gain_db=-11.0, spatial=False, purpose="burn loop while the server burn ticks run")
    n = int(RATE_SFX * 0.5)
    burst = apply_env(lowpass(white(rng, n), 3200, 0.9, RATE_SFX), env_shape(n, [(0, 0.0), (0.05, 1.0), (0.4, 0.7), (1.0, 0.05)]))
    add("incendio", "impact", normalize(mix(gain(burst, 1.0), crackles(rng, RATE_SFX, 0.5, 34.0), gain(apply_env(gain(sine(n, _sweep_freq(180, 70, "exp"), RATE_SFX), 0.7), expdecay(n, 0.2)), 0.6)), 0.95),
        gain_db=-3.0, pitch_var=0.04, purpose="cone burst on the confirmed hit")
    n = int(RATE_SFX * 0.85)
    hiss = apply_env(gain(highpass(white(rng, n), 1200, 0.7, RATE_SFX), 0.8),
                     env_shape(n, [(0, 0.0), (0.08, 1.0), (0.5, 0.5), (1.0, 0.0)]))
    swell = lowpass(hiss, 3000, 0.7, RATE_SFX)
    add("incendio", "end", normalize(mix(gain(swell, 1.0), gain(apply_env(gain(sine(n, _sweep_freq(400, 120, "exp"), RATE_SFX), 0.3), expdecay(n, 0.3)), 0.7)), 0.8),
        gain_db=-8.0, purpose="extinguish: steam hiss over a falling body")

    # --- bombarda: heavy charge, rumble travel, weighted blast, debris tail
    n = int(RATE_SFX * 0.42)
    charge = apply_env(gain(sine(n, _sweep_freq(90, 240, "lin"), RATE_SFX), 0.9), env_shape(n, [(0, 0.0), (0.7, 0.9), (1.0, 1.0)]))
    click = apply_env(bandpass(white(rng, n), 1800, 1.6, RATE_SFX), adsr(n, 0.002, 0.02, 0.02, 0.9))
    add("bombarda", "cast", normalize(mix(charge, gain(click, 0.5)), 0.9), gain_db=-4.0,
        pitch_var=0.03, purpose="charge-up with a latch click")
    n = int(RATE_SFX * 0.7)
    rumble = apply_env(lowpass(white(rng, n), 700, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.15, 0.95), (0.8, 0.8), (1.0, 0.0)]))
    add("bombarda", "travel", normalize(gain(mix(rumble, gain(sine(n, 70, RATE_SFX), 0.35)), 0.7), 0.75),
        gain_db=-10.0, loop=True, purpose="low rushing rumble in flight")
    n = int(RATE_SFX * 1.25)
    boom = apply_env(gain(sine(n, _sweep_freq(130, 34, "exp"), RATE_SFX), 1.0), expdecay(n, 0.22))
    crack = apply_env(lowpass(white(rng, n), 2400, 0.7, RATE_SFX), adsr(n, 0.001, 0.04, 0.05, 0.9))
    tail = apply_env(lowpass(pink(rng, n), 600, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.05, 1.0), (0.4, 0.45), (1.0, 0.0)]))
    add("bombarda", "impact", normalize(mix(gain(boom, 1.0), gain(crack, 0.8), gain(tail, 0.6)), 0.98),
        gain_db=-1.0, pitch_var=0.02, purpose="weighted blast with controlled low-frequency content")
    n = int(RATE_SFX * 1.1)
    debris = zeros(n)
    t = 0.0
    while t < 1.0:
        t += rng.uni(0.03, 0.18)
        start = int(t * RATE_SFX)
        if start >= n - 200:
            break
        chip = ping(RATE_SFX, rng.uni(900, 2600), 0.12, 0.05, partials=((1.0, 1.0), (2.7, 0.4)))
        for i, v in enumerate(chip):
            if start + i < n:
                debris[start + i] += v * rng.uni(0.4, 1.0) * 0.5
    rumble2 = apply_env(lowpass(white(rng, n), 420, 0.8, RATE_SFX), expdecay(n, 0.5))
    add("bombarda", "end", normalize(mix(debris, gain(rumble2, 0.7)), 0.7), gain_db=-9.0,
        purpose="debris and settling rumble after the blast")

    # --- expelliarmus: whip crack, whistle, disarm clang, wind-down
    n = int(RATE_SFX * 0.22)
    whip = apply_env(bandpass(white(rng, n), 4000, 1.5, RATE_SFX), adsr(n, 0.001, 0.02, 0.02, 0.95))
    fall = apply_env(gain(sine(n, _sweep_freq(1700, 480, "exp"), RATE_SFX), 0.5), expdecay(n, 0.12))
    add("expelliarmus", "cast", normalize(mix(whip, fall), 0.9), gain_db=-5.0,
        pitch_var=0.05, purpose="whip-snap cast matching the wand sweep")
    n = int(RATE_SFX * 0.6)
    whistle = zeros(n)
    phase = 0.0
    for i in range(n):
        # frequency-modulated carrier: integrate the instantaneous frequency so
        # the phase stays continuous (multiplying an absolute time by a varying
        # frequency produces a waveform that cannot loop)
        freq = 2400.0 * (1.0 + 0.04 * math.sin(math.tau * 11.0 * i / RATE_SFX))
        phase += math.tau * freq / RATE_SFX
        whistle[i] = math.sin(phase)
    add("expelliarmus", "travel", normalize(apply_env(gain(whistle, 0.7), env_shape(n, [(0, 0.0), (0.12, 0.9), (0.85, 0.8), (1.0, 0.0)])), 0.5),
        gain_db=-12.0, loop=True, purpose="high whistle with vibrato")
    n = int(RATE_SFX * 0.5)
    clang = apply_env(resonators(white(rng, n), [(1180, 9.0, 1.0), (1780, 11.0, 0.7), (2630, 13.0, 0.4)], RATE_SFX),
                      expdecay(n, 0.16))
    rattle = zeros(n)
    for _ in range(6):
        off = rng.int(0, max(1, n - 900))
        short = apply_env(bandpass(white(rng, 800), rng.uni(1500, 3600), 2.0, RATE_SFX), expdecay(800, 0.06))
        for i, v in enumerate(short):
            rattle[off + i] += v * 0.5
    add("expelliarmus", "impact", normalize(mix(gain(clang, 1.0), gain(rattle, 0.7)), 0.95),
        gain_db=-4.0, pitch_var=0.04, purpose="knocked-away wand clang + rattle")
    n = int(RATE_SFX * 0.4)
    down = apply_env(gain(sine(n, _sweep_freq(900, 260, "exp"), RATE_SFX), 0.5), expdecay(n, 0.25))
    add("expelliarmus", "end", normalize(down, 0.6), gain_db=-14.0, purpose="recoil tail")

    # --- protego: raise, sustained hum, positional ping, collapse
    n = int(RATE_SFX * 0.55)
    swell = apply_env(gain(sine(n, _sweep_freq(220, 520, "exp"), RATE_SFX), 0.7), env_shape(n, [(0, 0.0), (0.45, 1.0), (0.8, 0.85), (1.0, 0.2)]))
    choral = mix(sine(n, 328, RATE_SFX, amp=0.4), sine(n, 331, RATE_SFX, amp=0.4), sine(n, 494, RATE_SFX, amp=0.25))
    choral = apply_env(gain(choral, 0.5), adsr(n, 0.15, 0.2, 0.6, 0.3))
    add("protego", "cast", normalize(mix(swell, choral), 0.85), gain_db=-6.0,
        pitch_var=0.02, purpose="shield raise: rising swell + shimmer")
    n = int(RATE_AMB * 2.5)
    beat = mix(sine(n, 110, RATE_AMB, amp=0.5), sine(n, 110.7, RATE_AMB, amp=0.5), sine(n, 165.2, RATE_AMB, amp=0.3))
    bed = lowpass(white(rng, n), 700, 0.8, RATE_AMB)
    hum = mix(gain(beat, 0.7), gain(bed, 0.25))
    hum = array.array("d", [v * (0.85 + 0.15 * math.sin(math.tau * 0.35 * i / RATE_AMB)) for i, v in enumerate(hum)])
    add("protego", "sustain", normalize(crossfade_loop(hum, int(RATE_AMB * 0.3)), 0.55), rate=RATE_AMB,
        loop=True, gain_db=-14.0, spatial=False, purpose="low sustained ward hum for the 3.5 s ward")
    n = int(RATE_SFX * 0.45)
    glass = ping(RATE_SFX, 1450, 0.45, 0.2, partials=((1.0, 1.0), (2.4, 0.5), (3.6, 0.3), (5.1, 0.15)))
    thud = apply_env(lowpass(white(rng, n), 500, 0.9, RATE_SFX), adsr(n, 0.001, 0.03, 0.05, 0.9))
    add("protego", "impact", normalize(mix(gain(glass, 1.0), gain(thud, 0.6)), 0.9),
        gain_db=-6.0, pitch_var=0.06, purpose="positional impact ping on the shell (per hit)")
    n = int(RATE_SFX * 0.7)
    crack = apply_env(bandpass(white(rng, n), 2600, 1.2, RATE_SFX), adsr(n, 0.002, 0.05, 0.1, 0.85))
    fall = apply_env(gain(sine(n, _sweep_freq(620, 140, "exp"), RATE_SFX), 0.6), expdecay(n, 0.3))
    add("protego", "end", normalize(mix(gain(crack, 0.8), fall), 0.85), gain_db=-8.0,
        purpose="ward collapse: bright crack over a falling swell")

    # --- ultimate: long charge, heavy roar, lightning strike, residual sizzle
    n = int(RATE_SFX * 1.1)
    drone = mix(gain(sine(n, _sweep_freq(55, 92, "lin"), RATE_SFX), 0.9), gain(sine(n, _sweep_freq(110, 184, "lin"), RATE_SFX), 0.35))
    pulse = zeros(n)
    for i in range(n):
        pulse[i] = 0.6 + 0.4 * math.sin(math.tau * (3.0 + 6.0 * i / n) * i / RATE_SFX)
    drone = array.array("d", [drone[i] * pulse[i] for i in range(n)])
    chorald = apply_env(gain(mix(sine(n, 220, RATE_SFX, amp=0.3), sine(n, 277, RATE_SFX, amp=0.28), sine(n, 330, RATE_SFX, amp=0.22)), 0.6),
                        env_shape(n, [(0, 0.0), (0.5, 0.9), (0.85, 1.0), (1.0, 0.4)]))
    add("ultimate", "cast", normalize(mix(drone, chorald), 0.95), gain_db=-3.0,
        pitch_var=0.02, purpose="readable warning: rising dark drone with a quickening pulse")
    n = int(RATE_SFX * 0.9)
    roar = apply_env(lowpass(white(rng, n), 1400, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.2, 1.0), (0.8, 0.85), (1.0, 0.1)]))
    add("ultimate", "travel", normalize(mix(roar, gain(sine(n, 82, RATE_SFX), 0.5)), 0.85),
        gain_db=-6.0, loop=True, purpose="heavy roar in flight")
    n = int(RATE_SFX * 1.6)
    strike = apply_env(bandpass(white(rng, n), 5200, 0.8, RATE_SFX), adsr(n, 0.001, 0.03, 0.03, 0.95))
    det = apply_env(gain(sine(n, _sweep_freq(150, 30, "exp"), RATE_SFX), 1.0), expdecay(n, 0.28))
    tail = apply_env(lowpass(pink(rng, n), 900, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.03, 1.0), (0.35, 0.4), (1.0, 0.0)]))
    add("ultimate", "impact", normalize(mix(gain(strike, 0.95), gain(det, 1.0), gain(tail, 0.55)), 0.99),
        gain_db=0.0, pitch_var=0.02, purpose="distinct strike: lightning crack over a low detonation")
    n = int(RATE_SFX * 1.3)
    sizzle = apply_env(gain(highpass(white(rng, n), 3600, 0.7, RATE_SFX), 0.5), env_shape(n, [(0, 0.0), (0.05, 0.8), (0.4, 0.45), (1.0, 0.0)]))
    rumble = apply_env(lowpass(pink(rng, n), 300, 0.8, RATE_SFX), expdecay(n, 0.55))
    add("ultimate", "end", normalize(mix(gain(sizzle, 0.7), gain(rumble, 0.8)), 0.75), gain_db=-7.0,
        purpose="residual sparks and rolling tail")
    return out


# ------------------------------------------------------------------ rest

def world_library(rng):
    out = {}

    def add(key, path, sig, rate=RATE_SFX, loop=False, bus="sfx", gain_db=-6.0,
            pitch_var=0.05, spatial=True, purpose="", loop_mode=None):
        out[key] = dict(path=path, sig=sig, rate=rate, loop=loop, bus=bus,
                        gain_db=gain_db, pitch_var=pitch_var, spatial=spatial,
                        purpose=purpose,
                        loop_mode=loop_mode or ("forward" if loop else "disabled"))

    # --- footsteps, five surfaces x three variants
    surfaces = {
        "stone": (1900.0, 0.045, 0.10, 0.30),
        "dirt": (700.0, 0.06, 0.05, 0.45),
        "grass": (3600.0, 0.09, 0.02, 0.55),
        "wood": (1200.0, 0.07, 0.06, 0.40),
        "water": (2600.0, 0.14, 0.03, 0.60),
    }
    for surface, (centre, length, thud, rustle) in surfaces.items():
        for variant in range(3):
            n = int(RATE_SFX * (0.16 + length))
            click = apply_env(bandpass(white(rng, n), centre * rng.uni(0.9, 1.1), 1.4, RATE_SFX),
                              adsr(n, 0.001, 0.02, 0.03, 0.9))
            body = apply_env(lowpass(white(rng, n), 300, 0.8, RATE_SFX), adsr(n, 0.002, 0.04, 0.08, 0.85))
            extra = apply_env(highpass(white(rng, n), 4000, 0.7, RATE_SFX), expdecay(n, 0.05))
            sig = mix(gain(click, 1.0), gain(body, thud * 2.2), gain(extra, rustle * 0.55))
            add("step_%s_%d" % (surface, variant + 1), "footsteps/%s_%02d.wav" % (surface, variant + 1),
                normalize(sig, 0.7), gain_db=-9.0, pitch_var=0.09,
                purpose="%s footstep variant %d" % (surface, variant + 1))

    # --- character
    for variant in range(3):
        n = int(RATE_SFX * 0.5)
        cloth = apply_env(bandpass(white(rng, n), 2400, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.3, 0.7), (0.7, 0.4), (1.0, 0.0)]))
        cloth = mix(gain(cloth, 1.0), gain(apply_env(bandpass(white(rng, n), 900, 0.9, RATE_SFX), expdecay(n, 0.2)), 0.4))
        add("robe_%d" % (variant + 1), "character/robe_move_%02d.wav" % (variant + 1),
            normalize(cloth, 0.55), gain_db=-15.0, pitch_var=0.07, purpose="robe movement %d" % (variant + 1))
    n = int(RATE_SFX * 0.5)
    whoosh = apply_env(bandpass(white(rng, n), 900, 0.7, RATE_SFX), env_shape(n, [(0, 0.0), (0.25, 1.0), (1.0, 0.0)]))
    hop = apply_env(gain(sine(n, _sweep_freq(220, 90, "exp"), RATE_SFX), 0.5), expdecay(n, 0.12))
    add("mount", "character/mount.wav", normalize(mix(gain(whoosh, 0.9), gain(hop, 0.6)), 0.85),
        gain_db=-7.0, purpose="mount: broom whoosh + settling thud")
    n = int(RATE_SFX * 0.45)
    drop = apply_env(gain(sine(n, _sweep_freq(160, 70, "exp"), RATE_SFX), 0.6), expdecay(n, 0.14))
    cloth = apply_env(bandpass(white(rng, n), 1800, 0.8, RATE_SFX), adsr(n, 0.005, 0.05, 0.1, 0.8))
    add("dismount", "character/dismount.wav", normalize(mix(gain(drop, 0.9), gain(cloth, 0.7)), 0.85),
        gain_db=-7.0, purpose="dismount: hop-down thud with a cloth settle")
    n = int(RATE_AMB * 3.0)
    wind = lowpass(white(rng, n), 900, 0.8, RATE_AMB)
    wind = mix(gain(wind, 0.8), gain(lowpass(white(rng, n), 260, 0.7, RATE_AMB), 0.5))
    wind = array.array("d", [v * (0.7 + 0.3 * math.sin(math.tau * 0.31 * i / RATE_AMB)) for i, v in enumerate(wind)])
    add("broom_wind", "character/broom_wind.wav", normalize(crossfade_loop(wind, int(RATE_AMB * 0.3)), 0.75),
        rate=RATE_AMB, loop=True, gain_db=-12.0, spatial=False, purpose="broom wind bed (pitch follows speed)")
    n = int(RATE_SFX * 0.4)
    land = apply_env(lowpass(white(rng, n), 420, 0.8, RATE_SFX), adsr(n, 0.001, 0.05, 0.1, 0.8))
    body = gain(sine(n, _sweep_freq(160, 70, "exp"), RATE_SFX), 0.7)
    dust = apply_env(highpass(white(rng, n), 3200, 0.7, RATE_SFX), expdecay(n, 0.06))
    add("landing", "character/landing.wav",
        normalize(mix(gain(land, 1.0), apply_env(body, expdecay(n, 0.12)), gain(dust, 0.4)), 0.9),
        gain_db=-7.0, purpose="landing impact")

    # --- monsters
    for variant in range(3):
        n = int(RATE_SFX * 0.3)
        taps = zeros(n)
        for _ in range(5):
            off = rng.int(0, max(1, n - 420))
            tap = apply_env(bandpass(white(rng, 420), rng.uni(2200, 4600), 3.0, RATE_SFX), expdecay(420, 0.03))
            for i, v in enumerate(tap):
                taps[off + i] += v
        add("spider_move_%d" % (variant + 1), "monsters/spider_move_%02d.wav" % (variant + 1),
            normalize(taps, 0.5), gain_db=-16.0, purpose="chitin taps as the spider walks")
    n = int(RATE_SFX * 0.35)
    bite = mix(gain(apply_env(bandpass(white(rng, n), 1800, 1.6, RATE_SFX), adsr(n, 0.001, 0.02, 0.03, 0.95)), 1.0),
               gain(apply_env(gain(sine(n, _sweep_freq(420, 120, "exp"), RATE_SFX), 0.6), expdecay(n, 0.1)), 0.7))
    add("spider_bite", "monsters/spider_bite.wav", normalize(bite, 0.9), gain_db=-6.0, pitch_var=0.06,
        purpose="bite anticipation/release snap")
    n = int(RATE_SFX * 1.2)
    crunch = apply_env(bandpass(white(rng, n), 1300, 1.1, RATE_SFX), adsr(n, 0.002, 0.08, 0.15, 0.9))
    hiss = apply_env(gain(highpass(white(rng, n), 3000, 0.7, RATE_SFX), 0.5), env_shape(n, [(0, 0.0), (0.15, 0.7), (0.7, 0.3), (1.0, 0.0)]))
    add("spider_death", "monsters/spider_death.wav", normalize(mix(gain(crunch, 1.0), hiss), 0.9),
        gain_db=-5.0, purpose="death curl: wet crunch and expiring hiss")
    n = int(RATE_SFX * 1.0)
    charge = apply_env(gain(sine(n, _sweep_freq(70, 190, "lin"), RATE_SFX), 0.8), env_shape(n, [(0, 0.0), (0.75, 1.0), (1.0, 0.6)]))
    add("boss_slam_cast", "monsters/boss_slam_cast.wav", normalize(mix(charge, gain(apply_env(bandpass(white(rng, n), 900, 0.9, RATE_SFX), adsr(n, 0.05, 0.2, 0.5, 0.4)), 0.5)), 0.9),
        gain_db=-4.0, purpose="boss attack telegraph/charge")
    n = int(RATE_SFX * 1.4)
    slam = mix(gain(apply_env(gain(sine(n, _sweep_freq(90, 28, "exp"), RATE_SFX), 1.0), expdecay(n, 0.25)), 1.0),
               gain(apply_env(lowpass(white(rng, n), 900, 0.7, RATE_SFX), adsr(n, 0.001, 0.05, 0.08, 0.9)), 0.9))
    add("boss_slam_release", "monsters/boss_slam_release.wav", normalize(slam, 0.98), gain_db=-2.0,
        purpose="boss area attack release (matches the telegraph release tick)")
    n = int(RATE_SFX * 2.2)
    collapse = mix(gain(apply_env(lowpass(white(rng, n), 260, 0.8, RATE_SFX), adsr(n, 0.01, 0.3, 0.4, 0.5)), 1.0),
                   gain(apply_env(lowpass(pink(rng, n), 700, 0.8, RATE_SFX), env_shape(n, [(0, 0.0), (0.1, 1.0), (0.6, 0.4), (1.0, 0.0)])), 0.6))
    add("boss_death", "monsters/boss_death.wav", normalize(collapse, 0.95), gain_db=-4.0,
        purpose="boss death: long collapse with a rolling tail")

    # --- UI
    def ui(key, freq, seconds, decay, partials=((1.0, 1.0), (2.0, 0.35), (3.01, 0.15)), shape=None):
        n = int(RATE_SFX * seconds)
        sig = ping(RATE_SFX, freq, seconds, decay, partials)
        if shape:
            sig = apply_env(sig, shape)
        add("ui_" + key, "ui/%s.wav" % key, normalize(sig, 0.62), bus="ui", gain_db=-10.0,
            spatial=False, purpose="UI %s" % key)
    ui("button", 620, 0.09, 0.05)
    ui("hover", 880, 0.06, 0.035, ((1.0, 1.0), (2.0, 0.2)))
    ui("confirm", 660, 0.22, 0.09, ((1.0, 1.0), (1.5, 0.5), (2.0, 0.3)))
    ui("cancel", 420, 0.2, 0.08, ((1.0, 1.0), (0.75, 0.6)))
    ui("deny", 240, 0.3, 0.12, ((1.0, 1.0), (1.41, 0.5)))
    ui("chat", 1200, 0.07, 0.03)
    ui("quest", 523, 0.45, 0.16, ((1.0, 1.0), (1.5, 0.6), (2.0, 0.3)))
    ui("levelup", 440, 0.7, 0.28, ((1.0, 1.0), (1.5, 0.7), (2.0, 0.45), (3.0, 0.2)))
    ui("loot", 980, 0.2, 0.06, ((1.0, 1.0), (2.02, 0.3)))
    ui("upgrade_success", 520, 0.55, 0.2, ((1.0, 1.0), (1.5, 0.7), (2.0, 0.4), (2.5, 0.2)))
    ui("upgrade_fail", 380, 0.5, 0.18, ((1.0, 1.0), (1.32, 0.6), (0.66, 0.4)))
    ui("open", 700, 0.14, 0.06, ((1.0, 1.0), (1.48, 0.3)))
    ui("close", 500, 0.14, 0.06, ((1.0, 1.0), (0.7, 0.3)))
    n = int(RATE_SFX * 0.2)
    hit = mix(gain(apply_env(bandpass(white(rng, n), 1500, 1.0, RATE_SFX), adsr(n, 0.001, 0.02, 0.04, 0.9)), 1.0),
              gain(apply_env(gain(sine(n, _sweep_freq(300, 140, "exp"), RATE_SFX), 0.6), expdecay(n, 0.08)), 0.7))
    add("ui_hit", "ui/hit.wav", normalize(hit, 0.7), bus="ui", gain_db=-11.0, spatial=False,
        pitch_var=0.07, purpose="damage feedback tick")

    # --- transitions
    n = int(RATE_SFX * 1.1)
    whoosh = apply_env(bandpass(white(rng, n), 700, 0.7, RATE_SFX), env_shape(n, [(0, 0.0), (0.4, 1.0), (1.0, 0.0)]))
    shimmer = apply_env(gain(mix(sine(n, 880, RATE_SFX, amp=0.4), sine(n, 1320, RATE_SFX, amp=0.3)), 0.5),
                        env_shape(n, [(0, 0.0), (0.55, 0.8), (1.0, 0.0)]))
    add("map_transition", "transitions/map_transfer.wav", normalize(mix(gain(whoosh, 1.0), shimmer), 0.85),
        bus="ui", gain_db=-8.0, spatial=False, purpose="map transfer swell")
    n = int(RATE_SFX * 0.8)
    creak = apply_env(resonators(white(rng, n), [(220, 14.0, 1.0), (380, 16.0, 0.5), (610, 18.0, 0.3)], RATE_SFX),
                      adsr(n, 0.05, 0.3, 0.4, 0.5))
    add("door_open", "transitions/door_open.wav", normalize(creak, 0.6), gain_db=-12.0, spatial=True,
        purpose="heavy door opening")
    add("door_close", "transitions/door_close.wav", normalize(mix(gain(creak, 0.7), gain(
        apply_env(lowpass(white(rng, int(RATE_SFX * 0.25)), 400, 0.8, RATE_SFX), adsr(int(RATE_SFX * 0.25), 0.001, 0.03, 0.05, 0.9)), 0.8)), 0.7),
        gain_db=-11.0, spatial=True, purpose="heavy door closing")

    # --- ambience, one acoustic identity per room
    def bed(seconds, lo, hi, q=0.8, rate=RATE_AMB):
        n = int(rate * seconds)
        return lowpass(bandpass(pink(rng, n), math.sqrt(lo * hi), q, rate), hi, 0.8, rate)

    # exterior: wind with gusts, plus sparse birds
    n = int(RATE_AMB * 6.0)
    wind = mix(gain(bed(6.0, 200, 1400), 1.0), gain(brown(rng, n), 0.35))
    gust = zeros(n)
    for i in range(n):
        gust[i] = 0.55 + 0.45 * math.sin(math.tau * 0.13 * i / RATE_AMB) * math.sin(math.tau * 0.041 * i / RATE_AMB)
    wind = array.array("d", [wind[i] * gust[i] for i in range(n)])
    add("amb_exterior_wind", "ambience/exterior_wind.wav", normalize(crossfade_loop(wind, int(RATE_AMB * 0.6)), 0.62),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-16.0, spatial=False,
        purpose="exterior wind bed with gusts")
    bird_offsets = [int(RATE_AMB * t) for t in (0.8, 1.9, 3.4, 4.6)]
    birds = zeros(n)
    for off in bird_offsets:
        for chirp in range(rng.int(2, 4)):
            length = rng.int(int(RATE_AMB * 0.05), int(RATE_AMB * 0.12))
            c = apply_env(gain(sine(length, _sweep_freq(rng.uni(2600, 3600), rng.uni(1900, 2600), "exp"), RATE_AMB), 0.35),
                          adsr(length, 0.1, 0.2, 0.4, 0.4))
            start = off + chirp * rng.int(600, 1800)
            for i, v in enumerate(c):
                if start + i < n:
                    birds[start + i] += v
    add("amb_exterior_birds", "ambience/exterior_birds.wav", normalize(crossfade_loop(birds, int(RATE_AMB * 0.5)), 0.4),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-22.0, spatial=False,
        purpose="sparse bird calls for the grounds")
    # fire / candle beds used by both exterior props and interior rooms
    n = int(RATE_AMB * 5.0)
    fire = mix(gain(lowpass(pink(rng, n), 1500, 0.7, RATE_AMB), 0.9), gain(crackles(rng, RATE_AMB, 5.0, 11.0, 5400.0, 0.6), 1.0))
    add("amb_fire", "ambience/fire_loop.wav", normalize(crossfade_loop(fire, int(RATE_AMB * 0.5)), 0.6),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-17.0,
        purpose="hearth/fire loop (Great Hall, common rooms, braziers)")
    n = int(RATE_AMB * 4.0)
    candle = mix(gain(highpass(white(rng, n), 5000, 0.7, RATE_AMB), 0.25), gain(crackles(rng, RATE_AMB, 4.0, 5.0, 6800.0, 0.35), 1.0))
    candle = array.array("d", [v * (0.7 + 0.3 * math.sin(math.tau * 0.9 * i / RATE_AMB)) for i, v in enumerate(candle)])
    add("amb_candles", "ambience/candle_loop.wav", normalize(crossfade_loop(candle, int(RATE_AMB * 0.4)), 0.42),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-24.0,
        purpose="candle flicker sizzle for interior fixtures")
    # distant activity: muffled footfalls and doors beyond the walls
    n = int(RATE_AMB * 8.0)
    distant = zeros(n)
    t = 0.6
    while t < 7.4:
        length = int(RATE_AMB * 0.5)
        ev = apply_env(lowpass(white(rng, length), rng.uni(180, 420), 0.8, RATE_AMB), adsr(length, 0.02, 0.15, 0.2, 0.6))
        start = int(t * RATE_AMB)
        for i, v in enumerate(ev):
            if start + i < n:
                distant[start + i] += v * rng.uni(0.25, 0.6)
        t += rng.uni(0.7, 1.6)
    add("amb_distant", "ambience/distant_activity.wav", normalize(crossfade_loop(distant, int(RATE_AMB * 0.5)), 0.45),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-23.0, spatial=False,
        purpose="muffled distant activity beyond the room walls")
    # Great Hall: big hall reverb, deep bed, occasional fire swell
    n = int(RATE_AMB * 6.0)
    hall_bed = mix(gain(brown(rng, n), 0.5), gain(lowpass(pink(rng, n), 700, 0.7, RATE_AMB), 0.7))
    hall_bed = reverb(hall_bed, RATE_AMB, decay=2.6, mix_amount=0.5, damp=2600.0, size=1.9)
    hall_bed = crossfade_loop(hall_bed, int(RATE_AMB * 0.8))
    add("amb_great_hall", "ambience/great_hall.wav", normalize(hall_bed, 0.5), rate=RATE_AMB, loop=True,
        bus="ambience", gain_db=-19.0, spatial=False,
        purpose="Great Hall: large reverberant room tone with a deep bed")
    # Library: tight dry room, clock tick, paper rustle
    n = int(RATE_AMB * 6.0)
    lib = mix(gain(lowpass(pink(rng, n), 1200, 0.8, RATE_AMB), 0.55), gain(highpass(white(rng, n), 6000, 0.7, RATE_AMB), 0.06))
    lib = reverb(lib, RATE_AMB, decay=0.55, mix_amount=0.16, damp=5200.0, size=0.55)
    ticks = zeros(n)
    t = 0.4
    while t < 5.6:
        start = int(t * RATE_AMB)
        tick = apply_env(bandpass(white(rng, 400), 4200, 4.0, RATE_AMB), expdecay(400, 0.02))
        for i, v in enumerate(tick):
            if start + i < n:
                ticks[start + i] += v * 0.35
        t += 1.0
    rustles = zeros(n)
    for _ in range(4):
        start = rng.int(0, n - RATE_AMB)
        length = int(RATE_AMB * rng.uni(0.25, 0.6))
        rust = apply_env(bandpass(white(rng, length), rng.uni(3000, 6000), 0.8, RATE_AMB), adsr(length, 0.1, 0.2, 0.35, 0.5))
        for i, v in enumerate(rust):
            rustles[start + i] += v * 0.3
    lib = mix(lib, gain(ticks, 0.5), gain(rustles, 0.7))
    add("amb_library", "ambience/library.wav", normalize(crossfade_loop(lib, int(RATE_AMB * 0.7)), 0.5),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-20.0, spatial=False,
        purpose="Library: tight dry tone, clock tick and paper rustle")
    # Dungeon: wet stone, drips, low drone, no birds
    n = int(RATE_AMB * 6.0)
    dun = mix(gain(brown(rng, n), 0.6), gain(lowpass(pink(rng, n), 400, 0.7, RATE_AMB), 0.5))
    dun = reverb(dun, RATE_AMB, decay=2.2, mix_amount=0.55, damp=1500.0, size=1.5)
    drips = zeros(n)
    t = 0.3
    while t < 5.7:
        start = int(t * RATE_AMB)
        length = int(RATE_AMB * 0.22)
        drop = apply_env(gain(sine(length, _sweep_freq(rng.uni(900, 1500), rng.uni(380, 620), "exp"), RATE_AMB), 0.5),
                         adsr(length, 0.01, 0.2, 0.25, 0.5))
        for i, v in enumerate(drop):
            if start + i < n:
                drips[start + i] += v * rng.uni(0.4, 0.9)
        t += rng.uni(0.6, 1.4)
    dun = mix(crossfade_loop(dun, int(RATE_AMB * 0.8)), drips)
    add("amb_dungeon", "ambience/dungeon.wav", normalize(crossfade_loop(dun, int(RATE_AMB * 0.8)), 0.55),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-19.0, spatial=False,
        purpose="Dungeon: wet stone drone with water drips")
    # Moving-stair mechanism
    n = int(RATE_AMB * 5.0)
    grind = apply_env(resonators(white(rng, n), [(70, 9.0, 1.0), (140, 12.0, 0.6), (310, 15.0, 0.35)], RATE_AMB),
                      env_shape(n, [(0, 0.0), (0.15, 0.9), (0.85, 0.85), (1.0, 0.0)]))
    clunks = zeros(n)
    for beat in range(6):
        start = int((0.4 + beat * 0.75) * RATE_AMB)
        clunk = apply_env(resonators(white(rng, int(RATE_AMB * 0.3)), [(180, 12.0, 1.0), (420, 15.0, 0.5)], RATE_AMB),
                          expdecay(int(RATE_AMB * 0.3), 0.08))
        for i, v in enumerate(clunk):
            if start + i < n:
                clunks[start + i] += v * 0.8
    stair = mix(gain(grind, 0.8), clunks)
    add("amb_stairs", "ambience/stair_mechanism.wav", normalize(crossfade_loop(stair, int(RATE_AMB * 0.5)), 0.6),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-18.0, spatial=True,
        purpose="moving-stair mechanism: stone grind with docking clunks")
    return out


# ------------------------------------------------------------------ validation

def validate(library):
    problems = []
    total_bytes = 0
    for key, entry in library.items():
        sig = entry["sig"]
        if len(sig) == 0:
            problems.append("%s is empty" % key)
            continue
        peak = max(abs(v) for v in sig)
        if peak > 1.0:
            problems.append("%s clips (peak %.3f)" % (key, peak))
        if peak < 0.01:
            problems.append("%s is silent (peak %.4f)" % (key, peak))
        if entry["loop"]:
            # A seamless loop means the seam step is no worse than the worst
            # ordinary step-to-step step inside the loop: a bright 2.4 kHz tone
            # legitimately moves up to ~0.33 between neighbours, so absolutes
            # would be meaningless.
            steps = sorted(abs(sig[i + 1] - sig[i]) for i in range(0, len(sig) - 1, 4))
            worst = steps[int(len(steps) * 0.999)] if steps else 0.0
            seam = abs(sig[0] - sig[-1])
            if seam > max(0.06, 1.6 * worst):
                problems.append("%s loop seam jumps (%.3f -> %.3f, worst inner step %.3f)"
                                % (key, sig[-1], sig[0], worst))
        seconds = len(sig) / float(entry["rate"])
        if seconds > 12.0:
            problems.append("%s is %.1f s (loops should stay short)" % (key, seconds))
    if problems:
        for p in problems:
            print("[phase12-audio] VALIDATION FAIL: %s" % p)
        raise SystemExit("synth_phase12 validation failed")
    return total_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parsed = parser.parse_args()
    out_dir = parsed.out
    os.makedirs(out_dir, exist_ok=True)

    rng = Rng(20261005)
    library = {}
    library.update(spell_library(rng))
    library.update(world_library(rng))

    manifest = {
        "schema": 1,
        "generator": "client/tools/audio/synth_phase12.py",
        "generated": time.strftime("%Y-%m-%d"),
        "provenance": "project-original synthesis (deterministic seeded DSP, Python standard library only); no downloaded or third-party audio",
        "license": "project-original (CC0-equivalent dedication by the project)",
        "buses": ["Music", "SFX", "UI", "Ambience"],
        "notes": "Per-file bus, base gain, pitch variation and loop mode. Spatial entries are played on an AudioStreamPlayer3D with attenuation; UI and bed entries play on a non-positional player. Long loops import as IMA-ADPCM with the forward loop flag (see tools/audio/tune_imports.py).",
        "sounds": {},
    }
    written = 0
    for key in sorted(library):
        entry = library[key]
        if entry["loop"]:
            # one uniform seam-continuous loop pass over every looping bed
            entry["sig"] = crossfade_loop(entry["sig"], int(entry["rate"] * 0.3))
        path = os.path.join(out_dir, entry["path"])
        write_wav(path, entry["sig"], entry["rate"])
        written += 1
        manifest["sounds"][key] = {
            "path": "assets/audio/" + entry["path"],
            "bus": entry["bus"],
            "gain_db": entry["gain_db"],
            "pitch_variation": entry["pitch_var"],
            "loop": entry["loop"],
            "loop_mode": entry["loop_mode"],
            "spatial": entry["spatial"],
            "sample_rate": entry["rate"],
            "seconds": round(len(entry["sig"]) / float(entry["rate"]), 3),
            "purpose": entry["purpose"],
        }
    validate(library)
    manifest_path = os.path.join(out_dir, "sound_library.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1)
        handle.write("\n")
    print("[phase12-audio] wrote %d sounds -> %s" % (written, out_dir))
    print("[phase12-audio] manifest -> %s" % manifest_path)


if __name__ == "__main__":
    main()
