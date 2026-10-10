#!/usr/bin/env python3
"""Spell effects sound library - HIGH-FIDELITY PROJECT-ORIGINAL synthesis.

    python client/tools/audio/synth_spell_sfx.py --out client/assets/audio

Every sound is synthesized here deterministically with high-quality DSP
using Python, NumPy and SciPy. Re-running the script reproduces the audio
files byte-for-byte.

Coverage:
    spells/<spell>/cast|travel|impact|sustain|end.wav
        all seven spells with their own cast/travel/impact/end variants plus
        attack/impact micro-variations.
    footsteps/<surface>_<n>.wav          five surfaces, three variants each
    character/                           robe movement, mount/dismount, broom
                                         wind (loop), landing
    monsters/                            spider move/bite/death, boss attacks,
                                         boss death
    ui/                                  button, confirm, cancel, error, loot,
                                         level up, quest, upgrade, chat, hit
    transitions/                         map transfer, door open/close
    ambience/                            exterior wind + birds, fire, candles,
                                         distant activity, Great Hall, library,
                                         dungeon room tones, moving-stair mechanism,
                                         plus ambient scatter events (bird chirps,
                                         wind gusts, leaf rustles, dungeon drips,
                                         hall settlement creaks, library page flips).

All loops are seam-continuous using crossfade_loop.
"""

import argparse
import array
import json
import math
import os
import struct
import sys
import time
import wave
import numpy as np
import scipy.signal as sp

RATE_SFX = 44100
RATE_AMB = 22050


# ------------------------------------------------------------------ DSP Primitives

def clamp(value, lo, hi):
    return np.clip(value, lo, hi)


def normalize(sig, target_peak=0.92):
    peak = float(np.max(np.abs(sig)))
    if peak > 1e-6:
        return sig * (target_peak / peak)
    return sig


def soft_clip(sig, drive=1.2):
    """Tube-like tanh saturation that adds warm punchy harmonics and prevents harsh clipping."""
    d = max(0.1, float(drive))
    return np.tanh(sig * d) / np.tanh(d)


def butter_lowpass(sig, cutoff, rate, order=2):
    nyq = 0.5 * rate
    norm = float(np.clip(cutoff / nyq, 0.001, 0.96))
    b, a = sp.butter(order, norm, btype='low')
    return sp.lfilter(b, a, sig)


def butter_highpass(sig, cutoff, rate, order=2):
    nyq = 0.5 * rate
    norm = float(np.clip(cutoff / nyq, 0.001, 0.96))
    b, a = sp.butter(order, norm, btype='high')
    return sp.lfilter(b, a, sig)


def butter_bandpass(sig, low, high, rate, order=2):
    nyq = 0.5 * rate
    low_norm = float(np.clip(low / nyq, 0.001, 0.94))
    high_norm = float(np.clip(high / nyq, low_norm + 0.01, 0.96))
    b, a = sp.butter(order, [low_norm, high_norm], btype='band')
    return sp.lfilter(b, a, sig)


def resonator(sig, center, q, rate):
    """Bandpass resonator with normalized peak gain."""
    w0 = 2.0 * math.pi * float(np.clip(center, 20.0, rate * 0.45)) / rate
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2.0 * max(0.1, q))
    b0 = alpha
    b1 = 0.0
    b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * cw
    a2 = 1.0 - alpha
    b = [b0 / a0, b1 / a0, b2 / a0]
    a = [1.0, a1 / a0, a2 / a0]
    return sp.lfilter(b, a, sig)


def multi_resonator(sig, partials, rate):
    """partials is a list of (freq, q, amp)."""
    out = np.zeros(len(sig))
    for freq, q, amp in partials:
        out += resonator(sig, freq, q, rate) * amp
    return out


def sine(n, freq, rate, phase=0.0, amp=1.0):
    t = np.arange(n) / float(rate)
    if isinstance(freq, (int, float)):
        return amp * np.sin(2.0 * np.pi * freq * t + phase)
    elif isinstance(freq, np.ndarray):
        ph = 2.0 * np.pi * np.cumsum(freq) / float(rate) + phase
        return amp * np.sin(ph)
    elif callable(freq):
        p = np.linspace(0, 1, n)
        f_arr = np.array([freq(x) for x in p])
        ph = 2.0 * np.pi * np.cumsum(f_arr) / float(rate) + phase
        return amp * np.sin(ph)
    return np.zeros(n)


def sine_sweep(n, f0, f1, rate, shape="exp"):
    t = np.linspace(0, 1, n)
    if shape == "exp":
        ratio = max(1e-6, f1 / max(1e-6, f0))
        freqs = f0 * (ratio ** t)
    else:
        freqs = f0 + (f1 - f0) * t
    phases = 2.0 * np.pi * np.cumsum(freqs) / float(rate)
    return np.sin(phases)


def exp_decay(n, tau):
    t = np.linspace(0, 1, n)
    return np.exp(-t / max(1e-4, tau))


def env_shape(n, points):
    """Piecewise-linear envelope from [(t, v), ...] with t in 0..1."""
    t_pts = [p[0] for p in points]
    v_pts = [p[1] for p in points]
    t = np.linspace(0, 1, n)
    return np.interp(t, t_pts, v_pts)


def adsr(n, attack, decay, sustain, release):
    a = max(1, int(attack * n))
    d = max(1, int(decay * n))
    r = max(1, int(release * n))
    s = max(0, n - a - d - r)
    pts = [(0.0, 0.0), (a / float(n), 1.0), ((a + d) / float(n), sustain)]
    if s > 0:
        pts.append(((a + d + s) / float(n), sustain))
    pts.append((1.0, 0.0))
    return env_shape(n, pts)


def white_noise(n, rng):
    return rng.uniform(-1.0, 1.0, n)


def pink_noise(n, rng):
    """Paul Kellet filter for authentic pink noise."""
    w = white_noise(n, rng)
    b = [0.0] * 7
    out = np.zeros(n)
    for i in range(n):
        x = w[i]
        b[0] = 0.99886 * b[0] + x * 0.0555179
        b[1] = 0.99332 * b[1] + x * 0.0750759
        b[2] = 0.96900 * b[2] + x * 0.1538520
        b[3] = 0.86650 * b[3] + x * 0.3104856
        b[4] = 0.55000 * b[4] + x * 0.5329522
        b[5] = -0.7616 * b[5] - x * 0.0168980
        out[i] = (b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + x * 0.5362) * 0.11
        b[6] = x * 0.115926
    return out


def brown_noise(n, rng):
    w = white_noise(n, rng)
    out = np.zeros(n)
    acc = 0.0
    for i in range(n):
        acc = np.clip(acc + w[i] * 0.02, -1.0, 1.0) * 0.995
        out[i] = acc
    return out


def crossfade_loop(sig, fade_samples):
    """Cut a mathematically seamless loop out of a longer bed."""
    n = len(sig)
    fade = min(fade_samples, n // 4)
    if fade <= 1:
        return sig
    length = n - fade
    out = np.copy(sig[:length])
    t = np.linspace(0, 1, fade)
    out[:fade] = sig[:fade] * t + sig[length:length + fade] * (1.0 - t)
    return out


def reverb(sig, rate, decay=1.6, mix_amount=0.3, damp=4200.0, size=1.0):
    """Schroeder reverb: four comb filters + two allpass filters."""
    combs = [1116, 1188, 1277, 1356]
    wet = np.zeros(len(sig))
    for delay_ms, fb in ((combs[0], 0.78), (combs[1], 0.74), (combs[2], 0.71), (combs[3], 0.68)):
        d = max(8, int(rate * delay_ms / 1000.0 * size))
        buf = np.zeros(d)
        idx = 0
        g = float(np.clip(fb * (0.5 + 0.5 * decay / 2.0), 0.0, 0.94))
        for i in range(len(sig)):
            y = buf[idx]
            wet[i] += y * 0.25
            buf[idx] = sig[i] + y * g
            idx = (idx + 1) % d
    wet = butter_lowpass(wet, damp, rate)
    return sig * (1.0 - mix_amount) + wet * mix_amount


def crackles(rng, rate, seconds, density=14.0, bright=5200.0, level=0.5):
    """Fire / ember crackle bed with sparse natural micro-pops."""
    n = int(rate * seconds)
    out = np.zeros(n)
    t = 0.0
    while t < seconds:
        gap = rng.uniform(0.35, 1.6) / density
        t += gap
        start = int(t * rate)
        if start >= n - 64:
            break
        length = rng.randint(24, 110)
        length = min(length, n - start)
        decay = exp_decay(length, rng.uniform(0.06, 0.22))
        rand_vals = rng.uniform(-1.0, 1.0, length)
        out[start:start + length] += rand_vals * decay * level
        t += length / float(rate) + gap
    out = butter_highpass(out, 500.0, rate)
    return butter_lowpass(out, bright, rate)


def ping(rate, freq, seconds, decay=0.25, partials=((1.0, 1.0), (2.01, 0.45), (3.02, 0.22), (4.9, 0.12))):
    n = int(rate * seconds)
    out = np.zeros(n)
    env = exp_decay(n, decay)
    for ratio, amp in partials:
        out += sine(n, freq * ratio, rate, amp=amp) * env
    return out


def write_wav(path, sig, rate):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    clamped = np.clip(sig, -1.0, 1.0)
    data = (clamped * 32767.0).astype(np.int16)
    channels = 1 if data.ndim == 1 else int(data.shape[1])
    with wave.open(path, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())


# ------------------------------------------------------------------ Spell Synthesis

def spell_library(rng):
    """Synthesizes high-fidelity spell sounds with visceral weight and magical identity."""
    out = {}

    def add(spell, stage, sig, rate=RATE_SFX, loop=False, gain_db=-4.0,
            pitch_var=0.03, spatial=True, purpose=""):
        out["spell_%s_%s" % (spell, stage)] = dict(
            path="spells/%s/%s.wav" % (spell, stage), sig=sig, rate=rate,
            loop=loop, bus="sfx", gain_db=gain_db, pitch_var=pitch_var,
            spatial=spatial, purpose=purpose,
            loop_mode="forward" if loop else "disabled")

    # ----------------------------------------------------------------
    # 1. basic_cast (The primary attack! Snappy, crisp, punchy, satisfying)
    # ----------------------------------------------------------------
    def synth_basic_cast(sub_f=140.0, flick_f=2800.0, body_f=580.0):
        n = int(RATE_SFX * 0.26)
        t = np.arange(n) / RATE_SFX
        
        # Whip-crack transient (wand slicing through air)
        w_len = int(RATE_SFX * 0.05)
        crack_noise = rng.normal(0, 1, w_len)
        crack_filt = butter_bandpass(crack_noise, flick_f * 0.8, flick_f * 2.2, RATE_SFX)
        crack = np.zeros(n)
        crack[:w_len] = crack_filt * np.exp(-np.linspace(0, 1, w_len) / 0.035) * 1.3

        # Sub-harmonic punch (air displacement weight)
        p_len = int(RATE_SFX * 0.10)
        t_p = np.arange(p_len) / RATE_SFX
        freq_p = sub_f * np.exp(-t_p / 0.03) + 45.0
        phases_p = 2.0 * np.pi * np.cumsum(freq_p) / RATE_SFX
        punch = np.zeros(n)
        punch[:p_len] = np.sin(phases_p) * np.exp(-t_p / 0.03) * 0.85

        # Arcane resonant body (warm magical core)
        f_body = body_f * np.exp(-t / 0.12) + 200.0
        ph_body = 2.0 * np.pi * np.cumsum(f_body) / RATE_SFX
        body = (np.sin(ph_body) + 0.45 * np.sin(ph_body * 2.02) + 0.2 * np.sin(ph_body * 3.01))
        body = body * np.exp(-t / 0.075) * 0.65

        # Sparkle motes (high-frequency fizzle)
        s_len = int(RATE_SFX * 0.18)
        spark = np.zeros(n)
        spark_noise = butter_bandpass(rng.normal(0, 1, s_len), 4500, 9200, RATE_SFX)
        spark[:s_len] = spark_noise * np.exp(-np.linspace(0, 1, s_len) / 0.08) * 0.4

        sig = crack + punch + body + spark
        sig = soft_clip(sig, drive=1.3)
        return normalize(sig, 0.92)

    add("basic_cast", "cast", synth_basic_cast(140.0, 3100.0, 620.0), gain_db=-5.0,
        pitch_var=0.06, purpose="wand flick: snappy whip crack + sub-punch + arcane fizzle")
    
    # Variations for basic cast to avoid machine-gunning
    out["spell_basic_cast_cast_2"] = dict(
        path="spells/basic_cast/cast_02.wav", sig=synth_basic_cast(155.0, 3400.0, 660.0),
        rate=RATE_SFX, loop=False, bus="sfx", gain_db=-5.0, pitch_var=0.06, spatial=True,
        purpose="basic cast variation 2", loop_mode="disabled")
    out["spell_basic_cast_cast_3"] = dict(
        path="spells/basic_cast/cast_03.wav", sig=synth_basic_cast(128.0, 2800.0, 580.0),
        rate=RATE_SFX, loop=False, bus="sfx", gain_db=-5.0, pitch_var=0.06, spatial=True,
        purpose="basic cast variation 3", loop_mode="disabled")

    # Basic cast travel (aerodynamic slipstream whoosh with subtle phase spin)
    n = int(RATE_SFX * 0.75)
    t = np.arange(n) / RATE_SFX
    wh_noise = butter_bandpass(pink_noise(n, rng), 900, 3600, RATE_SFX)
    swirl = 0.7 + 0.3 * np.sin(2.0 * np.pi * 5.0 * t)
    wh_hum = sine(n, 280, RATE_SFX, amp=0.25) * np.sin(2.0 * np.pi * 3.5 * t)
    travel = (wh_noise * swirl + wh_hum) * 0.7
    add("basic_cast", "travel", normalize(crossfade_loop(travel, int(RATE_SFX * 0.2)), 0.65),
        gain_db=-12.0, loop=True, purpose="aerodynamic slipstream whoosh while bolt is in flight")

    # Basic cast impact (visceral thud + sharp dispersion crack + sparkling flecks)
    def synth_basic_impact(thud_f=95.0, crack_f=3400.0):
        n = int(RATE_SFX * 0.35)
        t = np.arange(n) / RATE_SFX
        # Thump
        thump_f = thud_f * np.exp(-t / 0.04) + 40.0
        thump = np.sin(2.0 * np.pi * np.cumsum(thump_f) / RATE_SFX) * np.exp(-t / 0.045) * 1.1
        # Crack
        c_len = int(RATE_SFX * 0.08)
        crack_w = butter_bandpass(rng.normal(0, 1, c_len), crack_f * 0.8, crack_f * 1.8, RATE_SFX)
        crack = np.zeros(n)
        crack[:c_len] = crack_w * np.exp(-np.linspace(0, 1, c_len) / 0.025) * 1.2
        # Crystalline fleck dispersion
        fleck = ping(RATE_SFX, 2800, 0.35, decay=0.08, partials=((1.0, 1.0), (1.42, 0.5), (2.1, 0.3))) * 0.4
        sig = soft_clip(thump + crack + fleck, drive=1.3)
        return normalize(sig, 0.94)

    add("basic_cast", "impact", synth_basic_impact(105.0, 3600.0), gain_db=-4.5,
        pitch_var=0.08, purpose="impact: punchy body thud + dispersion crack + sparkling flecks")
    out["spell_basic_cast_impact_2"] = dict(
        path="spells/basic_cast/impact_02.wav", sig=synth_basic_impact(90.0, 3200.0),
        rate=RATE_SFX, loop=False, bus="sfx", gain_db=-4.5, pitch_var=0.08, spatial=True,
        purpose="basic impact variation 2", loop_mode="disabled")

    # Basic cast end (gentle magical dissipate)
    n = int(RATE_SFX * 0.28)
    diss = butter_bandpass(pink_noise(n, rng), 1400, 4800, RATE_SFX) * exp_decay(n, 0.16)
    add("basic_cast", "end", normalize(diss, 0.6), gain_db=-13.0, purpose="subtle dissipate tail")

    # ----------------------------------------------------------------
    # 2. stupefy (Stun bolt: deep rising charge, Doppler hum, stun blast)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 0.36)
    t = np.arange(n) / RATE_SFX
    rise_f = 120.0 + 440.0 * (t / t[-1]) ** 1.8
    charge = np.sin(2.0 * np.pi * np.cumsum(rise_f) / RATE_SFX)
    charge += 0.4 * np.sin(2.0 * np.pi * np.cumsum(rise_f * 1.98) / RATE_SFX)
    charge = charge * adsr(n, 0.01, 0.1, 0.6, 0.29)
    crack = butter_bandpass(rng.normal(0, 1, n), 800, 2800, RATE_SFX) * adsr(n, 0.01, 0.15, 0.4, 0.44)
    add("stupefy", "cast", normalize(soft_clip(charge * 0.9 + crack * 0.7, drive=1.2), 0.92),
        gain_db=-4.5, pitch_var=0.05, purpose="stupefy cast: rising resonant charge with crisp release")

    n = int(RATE_SFX * 0.8)
    t = np.arange(n) / RATE_SFX
    dop = sine(n, 340 + 60 * np.sin(2.0 * np.pi * 7.0 * t), RATE_SFX, amp=0.5)
    noise_dop = butter_bandpass(pink_noise(n, rng), 600, 2200, RATE_SFX) * (0.7 + 0.3 * np.sin(2.0 * np.pi * 7.0 * t))
    add("stupefy", "travel", normalize(crossfade_loop(dop + noise_dop, int(RATE_SFX * 0.2)), 0.75),
        gain_db=-10.0, loop=True, purpose="pulsing reverberant stun energy travel hum")

    n = int(RATE_SFX * 0.55)
    t = np.arange(n) / RATE_SFX
    sub_stun = np.sin(2.0 * np.pi * np.cumsum(75 * np.exp(-t / 0.05) + 35) / RATE_SFX) * np.exp(-t / 0.06) * 1.2
    bell = ping(RATE_SFX, 480, 0.55, decay=0.18, partials=((1.0, 1.0), (1.45, 0.6), (2.2, 0.4), (3.15, 0.2)))
    burst = butter_bandpass(rng.normal(0, 1, n), 1200, 5200, RATE_SFX) * exp_decay(n, 0.07) * 1.1
    add("stupefy", "impact", normalize(soft_clip(sub_stun + bell * 0.8 + burst * 0.9, drive=1.3), 0.96),
        gain_db=-3.0, pitch_var=0.05, purpose="stupefy impact: concussive shockwave + resonant bell ring")

    n = int(RATE_SFX * 0.65)
    halo = ping(RATE_SFX, 587, 0.65, decay=0.25, partials=((1.0, 1.0), (1.5, 0.5), (2.0, 0.3))) * 0.6
    add("stupefy", "end", normalize(halo, 0.65), gain_db=-12.0, purpose="ringing stun halo")

    # ----------------------------------------------------------------
    # 3. incendio (Fire spell: roaring ignition, fiery splash, burning hearth)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 0.55)
    t = np.arange(n) / RATE_SFX
    ignition_sub = np.sin(2.0 * np.pi * np.cumsum(120 * np.exp(-t / 0.06) + 40) / RATE_SFX) * np.exp(-t / 0.08) * 0.9
    flame_whoosh = butter_bandpass(pink_noise(n, rng), 250, 1600, RATE_SFX) * adsr(n, 0.04, 0.2, 0.5, 0.26) * 1.2
    spark_snap = butter_bandpass(rng.normal(0, 1, n), 2400, 8000, RATE_SFX) * exp_decay(n, 0.05) * 0.8
    add("incendio", "cast", normalize(soft_clip(ignition_sub + flame_whoosh + spark_snap, drive=1.2), 0.94),
        gain_db=-4.0, pitch_var=0.05, purpose="incendio cast: explosive flame ignition + turbulent whoosh")

    n = int(RATE_SFX * 0.6)
    splash_roar = butter_bandpass(brown_noise(n, rng) + pink_noise(n, rng), 180, 2200, RATE_SFX) * exp_decay(n, 0.15)
    sizzle_hiss = butter_highpass(rng.normal(0, 1, n), 2800, RATE_SFX) * exp_decay(n, 0.22) * 0.7
    add("incendio", "impact", normalize(soft_clip(splash_roar * 1.1 + sizzle_hiss, drive=1.2), 0.94),
        gain_db=-4.0, pitch_var=0.06, purpose="incendio impact: fiery eruption splash and sizzling heat")

    n = int(RATE_AMB * 3.5)
    t = np.arange(n) / RATE_AMB
    flame_drone = butter_bandpass(brown_noise(n, rng), 60, 380, RATE_AMB) * 0.85
    flame_crackle = crackles(rng, RATE_AMB, 3.5, density=18.0, bright=4800.0, level=0.7)
    heat_flutter = 0.8 + 0.2 * np.sin(2.0 * np.pi * 4.2 * t)
    sustain_flame = (flame_drone * heat_flutter + flame_crackle) * 0.8
    add("incendio", "sustain", normalize(crossfade_loop(sustain_flame, int(RATE_AMB * 0.4)), 0.75),
        rate=RATE_AMB, loop=True, gain_db=-12.0, spatial=True, purpose="rich roaring flame loop with wood pops")

    n = int(RATE_SFX * 0.7)
    embers = crackles(rng, RATE_SFX, 0.7, density=12.0, bright=5400.0, level=0.6) * exp_decay(n, 0.35)
    smoke = butter_bandpass(pink_noise(n, rng), 600, 2400, RATE_SFX) * exp_decay(n, 0.28) * 0.5
    add("incendio", "end", normalize(embers + smoke, 0.7), gain_db=-12.0, purpose="dying flame embers")

    # ----------------------------------------------------------------
    # 4. bombarda (Explosive Blasting Curse: heavy volatile charge, MASSIVE BOOM)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 0.42)
    t = np.arange(n) / RATE_SFX
    volt_hum = sine(n, 90 + 280 * (t / t[-1]) ** 2, RATE_SFX, amp=0.7) * adsr(n, 0.05, 0.2, 0.6, 0.15)
    volt_snap = butter_bandpass(rng.normal(0, 1, n), 1800, 6500, RATE_SFX) * exp_decay(n, 0.06) * 0.9
    add("bombarda", "cast", normalize(volt_hum + volt_snap, 0.92), gain_db=-4.0,
        pitch_var=0.04, purpose="bombarda cast: volatile electrical build-up + concussive snap")

    n = int(RATE_SFX * 0.75)
    t = np.arange(n) / RATE_SFX
    vortex = butter_bandpass(brown_noise(n, rng), 140, 900, RATE_SFX) * (0.8 + 0.2 * np.sin(2.0 * np.pi * 9.0 * t))
    add("bombarda", "travel", normalize(crossfade_loop(vortex, int(RATE_SFX * 0.2)), 0.8),
        gain_db=-9.0, loop=True, purpose="heavy rushing vortex slicing through air")

    # Bombarda Impact - Cinematic explosion (sub-bass boom, shattered debris, cavernous roll)
    n = int(RATE_SFX * 1.45)
    t = np.arange(n) / RATE_SFX
    # Sub-bass detonation (40-90Hz shockwave)
    sub_exp = np.sin(2.0 * np.pi * np.cumsum(95 * np.exp(-t / 0.12) + 38) / RATE_SFX) * np.exp(-t / 0.22) * 1.5
    # Blast fragmentation crunch
    crunch_len = int(RATE_SFX * 0.35)
    crunch = np.zeros(n)
    crunch_noise = butter_bandpass(rng.normal(0, 1, crunch_len), 300, 3800, RATE_SFX)
    crunch[:crunch_len] = crunch_noise * np.exp(-np.linspace(0, 1, crunch_len) / 0.08) * 1.3
    # Rolling reverberant decay
    rumble = butter_lowpass(brown_noise(n, rng), 240, RATE_SFX) * exp_decay(n, 0.45) * 1.1
    exp_mix = soft_clip(sub_exp + crunch + rumble, drive=1.4)
    add("bombarda", "impact", normalize(exp_mix, 0.98), gain_db=-0.5,
        pitch_var=0.04, purpose="bombarda impact: cinematic explosion with sub-bass boom and debris")

    n = int(RATE_SFX * 1.1)
    debris = butter_bandpass(rng.normal(0, 1, n), 400, 2800, RATE_SFX) * exp_decay(n, 0.35) * 0.7
    add("bombarda", "end", normalize(debris, 0.65), gain_db=-10.0, purpose="falling debris and dust")

    # ----------------------------------------------------------------
    # 5. expelliarmus (Disarming charm: whip-crack, ribbon whistle, kinetic clash)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 0.32)
    t = np.arange(n) / RATE_SFX
    whip_f = 2400 * np.exp(-t / 0.04) + 600
    whip = np.sin(2.0 * np.pi * np.cumsum(whip_f) / RATE_SFX) * np.exp(-t / 0.05) * 0.8
    whip_snap = butter_bandpass(rng.normal(0, 1, n), 2200, 7200, RATE_SFX) * exp_decay(n, 0.03) * 1.2
    add("expelliarmus", "cast", normalize(soft_clip(whip + whip_snap, drive=1.2), 0.92),
        gain_db=-4.5, pitch_var=0.05, purpose="expelliarmus cast: fast whip-crack with energetic swirl")

    n = int(RATE_SFX * 0.65)
    t = np.arange(n) / RATE_SFX
    whistle = sine(n, 980 + 120 * np.sin(2.0 * np.pi * 8.0 * t), RATE_SFX, amp=0.5)
    add("expelliarmus", "travel", normalize(crossfade_loop(whistle, int(RATE_SFX * 0.2)), 0.7),
        gain_db=-11.0, loop=True, purpose="whistling high-speed ribbon trail")

    n = int(RATE_SFX * 0.52)
    t = np.arange(n) / RATE_SFX
    # Metal/wood clash
    clash_ring = ping(RATE_SFX, 1150, 0.52, decay=0.12, partials=((1.0, 1.0), (1.68, 0.7), (2.85, 0.4))) * 0.9
    clash_trans = butter_bandpass(rng.normal(0, 1, n), 1800, 5600, RATE_SFX) * exp_decay(n, 0.03) * 1.1
    clash_sub = np.sin(2.0 * np.pi * np.cumsum(140 * np.exp(-t / 0.04) + 50) / RATE_SFX) * np.exp(-t / 0.05) * 0.8
    add("expelliarmus", "impact", normalize(soft_clip(clash_ring + clash_trans + clash_sub, drive=1.2), 0.95),
        gain_db=-3.5, pitch_var=0.05, purpose="expelliarmus impact: forceful kinetic wand clash and ring")

    n = int(RATE_SFX * 0.4)
    recoil = butter_lowpass(pink_noise(n, rng), 600, RATE_SFX) * exp_decay(n, 0.15) * 0.6
    add("expelliarmus", "end", normalize(recoil, 0.6), gain_db=-13.0, purpose="kinetic recoil tail")

    # ----------------------------------------------------------------
    # 6. protego (Shield charm: crystal chime, harmonic hum, glass deflection)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 0.55)
    chime = ping(RATE_SFX, 523, 0.55, decay=0.22, partials=((1.0, 1.0), (1.5, 0.6), (2.0, 0.4), (2.67, 0.25))) * 0.8
    swell = butter_lowpass(brown_noise(n, rng), 400, RATE_SFX) * adsr(n, 0.1, 0.2, 0.5, 0.2) * 0.7
    add("protego", "cast", normalize(chime + swell, 0.9), gain_db=-5.0,
        pitch_var=0.03, purpose="protego cast: crystal barrier summon chime + deep hum")

    n = int(RATE_AMB * 3.2)
    t = np.arange(n) / RATE_AMB
    # Detuned dual harmonics for ethereal barrier hum
    hum1 = np.sin(2.0 * np.pi * 110.0 * t)
    hum2 = np.sin(2.0 * np.pi * 110.8 * t)
    hum3 = np.sin(2.0 * np.pi * 165.2 * t) * 0.5
    ward_bed = butter_lowpass(pink_noise(n, rng), 500, RATE_AMB) * 0.3
    ward_hum = (hum1 * 0.4 + hum2 * 0.4 + hum3 + ward_bed) * (0.85 + 0.15 * np.sin(2.0 * np.pi * 0.3 * t))
    add("protego", "sustain", normalize(crossfade_loop(ward_hum, int(RATE_AMB * 0.4)), 0.65),
        rate=RATE_AMB, loop=True, gain_db=-13.0, spatial=False, purpose="sustained shimmering ward hum")

    n = int(RATE_SFX * 0.45)
    t = np.arange(n) / RATE_SFX
    ping_glass = ping(RATE_SFX, 1580, 0.45, decay=0.14, partials=((1.0, 1.0), (2.1, 0.5), (3.4, 0.3), (4.8, 0.15))) * 1.0
    deflect_sub = np.sin(2.0 * np.pi * np.cumsum(130 * np.exp(-t / 0.03) + 60) / RATE_SFX) * np.exp(-t / 0.05) * 0.8
    add("protego", "impact", normalize(soft_clip(ping_glass + deflect_sub, drive=1.2), 0.94),
        gain_db=-4.5, pitch_var=0.06, purpose="protego impact: crystalline deflection ping + bass displacement")

    n = int(RATE_SFX * 0.65)
    collapse_crack = butter_bandpass(rng.normal(0, 1, n), 2200, 6500, RATE_SFX) * exp_decay(n, 0.08) * 0.8
    collapse_tone = ping(RATE_SFX, 392, 0.65, decay=0.22) * 0.6
    add("protego", "end", normalize(collapse_crack + collapse_tone, 0.8), gain_db=-8.0,
        purpose="ward collapse: crystalline shatter and harmonic fade")

    # ----------------------------------------------------------------
    # 7. ultimate (Ultimate Arcane Strike: thunderous crescendo, cataclysmic blast)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 1.25)
    t = np.arange(n) / RATE_SFX
    drone_f = 50.0 + 90.0 * (t / t[-1]) ** 1.5
    drone = np.sin(2.0 * np.pi * np.cumsum(drone_f) / RATE_SFX) * adsr(n, 0.05, 0.3, 0.8, 0.1) * 0.9
    pulse_freq = 3.0 + 8.0 * (t / t[-1])
    drone *= (0.6 + 0.4 * np.sin(2.0 * np.pi * pulse_freq * t))
    choral = (sine(n, 220, RATE_SFX, amp=0.3) + sine(n, 277, RATE_SFX, amp=0.25) + sine(n, 330, RATE_SFX, amp=0.2)) * adsr(n, 0.1, 0.3, 0.85, 0.15)
    add("ultimate", "cast", normalize(soft_clip(drone + choral, drive=1.2), 0.96), gain_db=-2.5,
        pitch_var=0.02, purpose="ultimate cast: gathering catastrophic arcane drone and quickening pulse")

    n = int(RATE_SFX * 0.95)
    t = np.arange(n) / RATE_SFX
    roar = butter_bandpass(brown_noise(n, rng) + pink_noise(n, rng), 100, 1800, RATE_SFX) * (0.8 + 0.2 * np.sin(2.0 * np.pi * 12.0 * t))
    add("ultimate", "travel", normalize(crossfade_loop(roar, int(RATE_SFX * 0.2)), 0.85),
        gain_db=-5.0, loop=True, purpose="raging plasma roar in flight")

    # Cataclysmic Thunderblast Impact
    n = int(RATE_SFX * 1.7)
    t = np.arange(n) / RATE_SFX
    # Earth-shattering 40Hz bass drop
    sub_seismic = np.sin(2.0 * np.pi * np.cumsum(110 * np.exp(-t / 0.14) + 36) / RATE_SFX) * np.exp(-t / 0.28) * 1.6
    # Lightning crack
    l_len = int(RATE_SFX * 0.12)
    l_crack = np.zeros(n)
    l_crack[:l_len] = butter_bandpass(rng.normal(0, 1, l_len), 1200, 8500, RATE_SFX) * np.exp(-np.linspace(0, 1, l_len) / 0.03) * 1.5
    # Cavernous thunder rumble
    t_rumble = butter_lowpass(brown_noise(n, rng), 260, RATE_SFX) * exp_decay(n, 0.55) * 1.2
    add("ultimate", "impact", normalize(soft_clip(sub_seismic + l_crack + t_rumble, drive=1.5), 0.99),
        gain_db=0.0, pitch_var=0.02, purpose="ultimate impact: colossal thunder strike detonation and rolling shockwave")

    n = int(RATE_SFX * 1.35)
    sparks = butter_highpass(rng.normal(0, 1, n), 3200, RATE_SFX) * exp_decay(n, 0.25) * 0.6
    deep_tail = butter_lowpass(brown_noise(n, rng), 200, RATE_SFX) * exp_decay(n, 0.45) * 0.8
    add("ultimate", "end", normalize(sparks + deep_tail, 0.75), gain_db=-6.5, purpose="residual arcane sparks and rolling tremor")

    return out


# ------------------------------------------------------------------ World & Ambience Synthesis

def world_library(rng):
    """Synthesizes rich world, creature, UI, footstep and ambient audio."""
    out = {}

    def add(key, path, sig, rate=RATE_SFX, loop=False, bus="sfx", gain_db=-6.0,
            pitch_var=0.05, spatial=True, purpose="", loop_mode=None):
        out[key] = dict(path=path, sig=sig, rate=rate, loop=loop, bus=bus,
                        gain_db=gain_db, pitch_var=pitch_var, spatial=spatial,
                        purpose=purpose,
                        loop_mode=loop_mode or ("forward" if loop else "disabled"))

    # ----------------------------------------------------------------
    # Footsteps: physical materials (stone, dirt, grass, wood, water).
    # Five layers - impact tick, foot mass, ground resonance, scuff tail and a
    # surface flourish - so a step reads as a place, not as a sample.
    # ----------------------------------------------------------------
    surfaces = {
        "stone": {"tick_f": (2800.0, 6200.0), "tick_s": 0.02, "body_f": 165.0, "body_s": 0.05,
                  "res": ((1150.0, 12.0, 0.35), (2350.0, 14.0, 0.18)), "scuff": (1400.0, 4200.0),
                  "len": 0.26, "weight": 0.4},
        "dirt":  {"tick_f": (1100.0, 2800.0), "tick_s": 0.025, "body_f": 110.0, "body_s": 0.07,
                  "res": ((420.0, 9.0, 0.5), (900.0, 11.0, 0.2)), "scuff": (500.0, 1900.0),
                  "len": 0.30, "weight": 0.75},
        "grass": {"tick_f": (2200.0, 5200.0), "tick_s": 0.018, "body_f": 95.0, "body_s": 0.045,
                  "res": ((650.0, 10.0, 0.28), (1500.0, 12.0, 0.14)), "scuff": (2200.0, 6800.0),
                  "len": 0.32, "weight": 0.3},
        "wood":  {"tick_f": (1900.0, 4400.0), "tick_s": 0.02, "body_f": 135.0, "body_s": 0.06,
                  "res": ((360.0, 16.0, 0.6), (760.0, 18.0, 0.25)), "scuff": (900.0, 2600.0),
                  "len": 0.30, "weight": 0.85},
        "water": {"tick_f": (1500.0, 3800.0), "tick_s": 0.03, "body_f": 120.0, "body_s": 0.08,
                  "res": ((780.0, 8.0, 0.45), (1600.0, 10.0, 0.2)), "scuff": (900.0, 3400.0),
                  "len": 0.36, "weight": 0.5},
    }
    for surface, cfg in surfaces.items():
        for variant in range(3):
            n = int(RATE_SFX * cfg["len"])
            t = np.arange(n) / RATE_SFX
            level = 0.8 + 0.2 * variant
            tick_len = min(n, int(RATE_SFX * cfg["tick_s"] * (1.0 + 0.18 * variant)))
            tick = np.zeros(n)
            tick[:tick_len] = butter_bandpass(rng.normal(0, 1, tick_len), cfg["tick_f"][0], cfg["tick_f"][1], RATE_SFX) \
                * np.exp(-np.linspace(0.0, 1.0, tick_len) / 0.2)
            body_f = cfg["body_f"] * (1.0 + rng.uniform(-0.06, 0.06))
            body = np.sin(2.0 * np.pi * np.cumsum(body_f * np.exp(-t / cfg["body_s"]) + body_f * 0.55) / RATE_SFX) \
                * np.exp(-t / (cfg["body_s"] * 1.4)) * cfg["weight"]
            res = multi_resonator(
                rng.normal(0, 1, n),
                [(f * (1.0 + rng.uniform(-0.05, 0.05)), q, a) for f, q, a in cfg["res"]],
                RATE_SFX) * np.exp(-t / 0.06)
            scuff_len = int(n * 0.6)
            scuff = np.zeros(n)
            scuff[:scuff_len] = butter_bandpass(pink_noise(scuff_len, rng), cfg["scuff"][0], cfg["scuff"][1], RATE_SFX) \
                * env_shape(scuff_len, [(0.0, 0.4), (0.25, 1.0), (1.0, 0.0)])
            sig = tick * 0.95 * level + body * 0.9 + res * 1.1 + scuff * 0.35
            if surface == "water":
                drop = ping(RATE_SFX, rng.uniform(700.0, 980.0), cfg["len"], decay=0.07,
                            partials=((1.0, 1.0), (2.2, 0.3)))
                sig = sig + np.pad(drop, (int(0.06 * RATE_SFX), 0))[:n] * 0.3
            if surface == "wood":
                creak = resonator(rng.normal(0, 1, n), rng.uniform(240.0, 330.0), 18.0, RATE_SFX) \
                    * exp_decay(n, 0.3) * 0.12
                sig = sig + creak
            add("step_%s_%d" % (surface, variant + 1), "footsteps/%s_%02d.wav" % (surface, variant + 1),
                soft_clip(sig, drive=1.15), gain_db=-9.0, pitch_var=0.08,
                purpose="%s footstep variant %d" % (surface, variant + 1))

    # ----------------------------------------------------------------
    # Character sounds (robes, mount, dismount, landing, broom flight)
    # ----------------------------------------------------------------
    for variant in range(3):
        n = int(RATE_SFX * 0.5)
        cloth_w = butter_bandpass(pink_noise(n, rng), 900, 3200, RATE_SFX)
        cloth_env = env_shape(n, [(0, 0.0), (0.25, 0.8), (0.6, 0.4), (1.0, 0.0)])
        add("robe_%d" % (variant + 1), "character/robe_move_%02d.wav" % (variant + 1),
            normalize(cloth_w * cloth_env, 0.6), gain_db=-14.0, pitch_var=0.07, purpose="robe movement %d" % (variant + 1))

    n = int(RATE_SFX * 0.5)
    whoosh = butter_bandpass(pink_noise(n, rng), 350, 1800, RATE_SFX) * env_shape(n, [(0, 0.0), (0.25, 1.0), (1.0, 0.0)])
    hop = np.sin(2.0 * np.pi * 140.0 * (np.arange(n) / RATE_SFX)) * exp_decay(n, 0.1) * 0.6
    add("mount", "character/mount.wav", normalize(whoosh * 0.85 + hop * 0.6, 0.85),
        gain_db=-7.0, purpose="mount: broom whoosh and hop")

    n = int(RATE_SFX * 0.45)
    drop = np.sin(2.0 * np.pi * 120.0 * (np.arange(n) / RATE_SFX)) * exp_decay(n, 0.12) * 0.7
    cloth_d = butter_bandpass(pink_noise(n, rng), 800, 2600, RATE_SFX) * exp_decay(n, 0.15) * 0.6
    add("dismount", "character/dismount.wav", normalize(drop + cloth_d, 0.85),
        gain_db=-7.0, purpose="dismount: footstep settle and cloth rustle")

    # Broom flight wind loop
    n = int(RATE_AMB * 3.5)
    t = np.arange(n) / RATE_AMB
    flight_wind = butter_bandpass(brown_noise(n, rng) + pink_noise(n, rng), 80, 1400, RATE_AMB)
    flight_flutter = 0.85 + 0.15 * np.sin(2.0 * np.pi * 2.8 * t)
    add("broom_wind", "character/broom_wind.wav",
        normalize(crossfade_loop(flight_wind * flight_flutter, int(RATE_AMB * 0.35)), 0.78),
        rate=RATE_AMB, loop=True, gain_db=-11.0, spatial=False, purpose="broom flight wind bed")

    n = int(RATE_SFX * 0.42)
    t = np.arange(n) / RATE_SFX
    land_thud = np.sin(2.0 * np.pi * 110.0 * t) * exp_decay(n, 0.08) * 0.9
    land_crunch = butter_bandpass(rng.normal(0, 1, n), 400, 2400, RATE_SFX) * exp_decay(n, 0.06) * 0.7
    add("landing", "character/landing.wav", normalize(land_thud + land_crunch, 0.88),
        gain_db=-6.5, purpose="landing impact")

    # ----------------------------------------------------------------
    # Monsters & Boss (Spiders, Boss Slam, Boss Death)
    # ----------------------------------------------------------------
    for variant in range(3):
        n = int(RATE_SFX * 0.32)
        taps = np.zeros(n)
        for _ in range(6):
            off = rng.randint(0, max(1, n - 400))
            tap = butter_bandpass(rng.normal(0, 1, 400), rng.uniform(2200, 4800), rng.uniform(5000, 8000), RATE_SFX) * exp_decay(400, 0.03)
            taps[off:off + 400] += tap * 0.8
        add("spider_move_%d" % (variant + 1), "monsters/spider_move_%02d.wav" % (variant + 1),
            normalize(taps, 0.65), gain_db=-15.0, purpose="spider chitin movement %d" % (variant + 1))

    n = int(RATE_SFX * 0.36)
    t = np.arange(n) / RATE_SFX
    bite_snap = butter_bandpass(rng.normal(0, 1, n), 1600, 4800, RATE_SFX) * exp_decay(n, 0.04) * 1.2
    bite_hiss = butter_highpass(rng.normal(0, 1, n), 3200, RATE_SFX) * exp_decay(n, 0.12) * 0.6
    add("spider_bite", "monsters/spider_bite.wav", normalize(bite_snap + bite_hiss, 0.92),
        gain_db=-5.0, pitch_var=0.06, purpose="spider bite snap and venomous hiss")

    n = int(RATE_SFX * 1.2)
    crunch = butter_bandpass(rng.normal(0, 1, n), 800, 2600, RATE_SFX) * exp_decay(n, 0.22) * 1.1
    hiss = butter_bandpass(pink_noise(n, rng), 1800, 6000, RATE_SFX) * exp_decay(n, 0.45) * 0.7
    add("spider_death", "monsters/spider_death.wav", normalize(crunch + hiss, 0.9),
        gain_db=-4.5, purpose="spider death: chitin crunch and expiring hiss")

    # Boss slam cast (menacing low monster roar + ground tremor)
    n = int(RATE_SFX * 1.05)
    t = np.arange(n) / RATE_SFX
    growl_f = 65.0 + 110.0 * (t / t[-1])
    growl = np.sin(2.0 * np.pi * np.cumsum(growl_f) / RATE_SFX) * adsr(n, 0.05, 0.3, 0.7, 0.2) * 0.8
    growl += butter_lowpass(brown_noise(n, rng), 350, RATE_SFX) * adsr(n, 0.1, 0.2, 0.6, 0.25) * 0.7
    add("boss_slam_cast", "monsters/boss_slam_cast.wav", normalize(soft_clip(growl, drive=1.2), 0.92),
        gain_db=-3.5, purpose="boss attack telegraph: deep guttural charge")

    # Boss slam release (earth-shattering impact)
    n = int(RATE_SFX * 1.45)
    t = np.arange(n) / RATE_SFX
    slam_sub = np.sin(2.0 * np.pi * np.cumsum(85 * np.exp(-t / 0.12) + 32) / RATE_SFX) * np.exp(-t / 0.22) * 1.4
    slam_stone = butter_bandpass(rng.normal(0, 1, n), 250, 3200, RATE_SFX) * exp_decay(n, 0.09) * 1.2
    slam_roll = butter_lowpass(brown_noise(n, rng), 220, RATE_SFX) * exp_decay(n, 0.4) * 0.9
    add("boss_slam_release", "monsters/boss_slam_release.wav",
        normalize(soft_clip(slam_sub + slam_stone + slam_roll, drive=1.3), 0.98),
        gain_db=-1.5, purpose="boss slam release: massive ground impact detonation")

    # Boss death (catastrophic creature death roar and collapse)
    n = int(RATE_SFX * 2.3)
    t = np.arange(n) / RATE_SFX
    roar_d = np.sin(2.0 * np.pi * np.cumsum(120 * np.exp(-t / 0.8) + 40) / RATE_SFX) * exp_decay(n, 0.65) * 0.8
    collapse_rumble = butter_lowpass(brown_noise(n, rng), 280, RATE_SFX) * adsr(n, 0.05, 0.3, 0.5, 0.45) * 1.1
    add("boss_death", "monsters/boss_death.wav",
        normalize(soft_clip(roar_d + collapse_rumble, drive=1.3), 0.95),
        gain_db=-3.0, purpose="boss death: long bellow and heavy collapse")

    # ----------------------------------------------------------------
    # UI Sounds: one enchanted material - struck-bell partials plus a soft
    # wand tick and a small room halo, tuned to A minor pentatonic (the
    # colour the spells already speak). Confirms rise, cancels fall, so the
    # interface says what happened without a word.
    # ----------------------------------------------------------------
    BELL_PARTIALS = ((1.0, 1.0, 1.0), (2.01, 0.5, 0.72), (3.03, 0.28, 0.5), (4.19, 0.14, 0.32))

    def ui_tone(freq, seconds, decay, tick_level=0.22):
        n = int(RATE_SFX * seconds)
        t = np.arange(n) / RATE_SFX
        body = np.zeros(n)
        for ratio, weight, tau_scale in BELL_PARTIALS:
            partial = freq * ratio
            if partial > RATE_SFX * 0.45:
                continue
            body += np.sin(2.0 * np.pi * partial * t) * np.exp(-t / (decay * tau_scale)) * weight
        tick_len = min(n, int(0.012 * RATE_SFX))
        tick = np.zeros(n)
        tick[:tick_len] = butter_bandpass(rng.normal(0, 1, tick_len), 2200.0, 6800.0, RATE_SFX) \
            * np.exp(-np.linspace(0.0, 1.0, tick_len)) * tick_level
        halo = reverb(body * 0.5, RATE_SFX, decay=0.6, mix_amount=0.35, damp=5200.0, size=0.5)
        return soft_clip(body + tick + halo * 0.4, drive=1.05)

    def ui_notes(notes, seconds, decay, spacing=0.07, tick_level=0.22):
        n = int(RATE_SFX * seconds)
        sig = np.zeros(n)
        for index, note in enumerate(notes):
            start = int(index * spacing * RATE_SFX)
            if start >= n:
                break
            tone = ui_tone(note, seconds - index * spacing, decay,
                           tick_level if index == 0 else tick_level * 0.6)
            end = min(n, start + len(tone))
            sig[start:end] += tone[:end - start]
        return sig

    def ui_add(key, sig):
        add("ui_" + key, "ui/%s.wav" % key, sig, bus="ui", gain_db=-9.0,
            spatial=False, purpose="UI %s" % key)

    ui_add("button", ui_tone(659.26, 0.15, 0.055))
    ui_add("hover", ui_tone(987.77, 0.09, 0.03, tick_level=0.12))
    ui_add("confirm", ui_notes((659.26, 880.0), 0.4, 0.12, spacing=0.055))
    ui_add("cancel", ui_notes((440.0, 329.63), 0.34, 0.1, spacing=0.06))
    ui_add("deny", ui_notes((220.0, 233.08), 0.45, 0.16, spacing=0.0, tick_level=0.12))
    ui_add("chat", ui_tone(1318.51, 0.08, 0.028, tick_level=0.14))
    ui_add("quest", ui_notes((659.26, 783.99, 1046.5), 0.6, 0.16, spacing=0.075))
    ui_add("levelup", ui_notes((523.25, 659.26, 783.99, 1046.5), 1.0, 0.3, spacing=0.105))
    ui_add("loot", ui_notes((987.77, 1318.51), 0.32, 0.08, spacing=0.07))
    ui_add("upgrade_success", ui_notes((440.0, 554.37, 659.26), 0.7, 0.22, spacing=0.09))
    ui_add("upgrade_fail", ui_notes((392.0, 311.13), 0.55, 0.16, spacing=0.08))

    swoosh_n = int(RATE_SFX * 0.22)
    swoosh_up = butter_bandpass(pink_noise(swoosh_n, rng), 500.0, 3400.0, RATE_SFX) \
        * env_shape(swoosh_n, [(0.0, 0.0), (0.4, 0.9), (1.0, 0.0)])
    open_sig = ui_notes((659.26,), 0.24, 0.07)
    open_sig[:swoosh_n] += swoosh_up * 0.5
    ui_add("open", open_sig)

    swoosh_down = butter_bandpass(pink_noise(swoosh_n, rng), 350.0, 2400.0, RATE_SFX) \
        * env_shape(swoosh_n, [(0.0, 0.0), (0.35, 0.9), (1.0, 0.0)])
    close_sig = ui_notes((440.0,), 0.24, 0.07)
    close_sig[:swoosh_n] += swoosh_down * 0.5
    ui_add("close", close_sig)

    # ui_hit (Combat hit feedback: punchy, tactile hit indicator!)
    n = int(RATE_SFX * 0.18)
    t = np.arange(n) / RATE_SFX
    hit_click = butter_bandpass(rng.normal(0, 1, n), 2200, 6800, RATE_SFX) * exp_decay(n, 0.025) * 1.2
    hit_punch = np.sin(2.0 * np.pi * np.cumsum(180 * np.exp(-t / 0.03) + 70) / RATE_SFX) * exp_decay(n, 0.04) * 0.9
    add("ui_hit", "ui/hit.wav", normalize(soft_clip(hit_click + hit_punch, drive=1.2), 0.85),
        bus="ui", gain_db=-8.0, spatial=False, pitch_var=0.07, purpose="combat damage hit marker tick")

    # ui_equip (Crisp leather & metallic buckle clasp)
    n = int(RATE_SFX * 0.20)
    t = np.arange(n) / RATE_SFX
    eq_leather = butter_bandpass(rng.normal(0, 1, n), 1200, 3800, RATE_SFX) * exp_decay(n, 0.05) * 0.9
    eq_click = butter_highpass(rng.normal(0, 1, n), 4200, RATE_SFX) * exp_decay(n, 0.02) * 1.2
    eq_buckle = ping(RATE_SFX, 580, 0.20, decay=0.06, partials=((1.0, 1.0), (1.8, 0.4), (2.5, 0.2))) * 0.7
    add("ui_equip", "ui/equip.wav", normalize(soft_clip(eq_leather + eq_click + eq_buckle, drive=1.2), 0.88),
        bus="ui", gain_db=-8.0, spatial=False, purpose="UI equip armor/gear")

    # ui_unequip (Soft leather slide / cloth rustle)
    n = int(RATE_SFX * 0.22)
    t = np.arange(n) / RATE_SFX
    uneq_leather = butter_bandpass(rng.normal(0, 1, n), 700, 2600, RATE_SFX) * exp_decay(n, 0.08) * 1.0
    uneq_soft = ping(RATE_SFX, 360, 0.22, decay=0.07, partials=((1.0, 1.0), (1.4, 0.3))) * 0.4
    add("ui_unequip", "ui/unequip.wav", normalize(uneq_leather + uneq_soft, 0.85),
        bus="ui", gain_db=-8.5, spatial=False, purpose="UI unequip gear")

    # ui_potion (Cork uncork pop + magical elixir glug + sparkle)
    n = int(RATE_SFX * 0.38)
    t = np.arange(n) / RATE_SFX
    pop_len = int(RATE_SFX * 0.06)
    t_pop = np.arange(pop_len) / RATE_SFX
    pop_freq = 750.0 * np.exp(-t_pop / 0.012) + 160.0
    pop = np.zeros(n)
    pop[:pop_len] = np.sin(2.0 * np.pi * np.cumsum(pop_freq) / RATE_SFX) * np.exp(-t_pop / 0.015) * 1.3
    bub1 = ping(RATE_SFX, 480, 0.25, decay=0.07, partials=((1.0, 1.0), (1.6, 0.4))) * 0.6
    bub2 = ping(RATE_SFX, 620, 0.20, decay=0.06, partials=((1.0, 1.0), (1.3, 0.3))) * 0.5
    liquid = np.zeros(n)
    liquid[int(RATE_SFX * 0.05):int(RATE_SFX * 0.05) + len(bub1)] += bub1
    liquid[int(RATE_SFX * 0.14):int(RATE_SFX * 0.14) + len(bub2)] += bub2
    fizz = butter_bandpass(rng.normal(0, 1, n), 3500, 8500, RATE_SFX) * adsr(n, 0.05, 0.1, 0.3, 0.2) * 0.35
    add("ui_potion", "ui/potion.wav", normalize(soft_clip(pop + liquid + fizz, drive=1.1), 0.90),
        bus="ui", gain_db=-7.5, spatial=False, purpose="UI drink potion")

    # ----------------------------------------------------------------
    # Transitions (portal transfer, doors)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 1.15)
    t = np.arange(n) / RATE_SFX
    trans_whoosh = butter_bandpass(pink_noise(n, rng), 400, 2200, RATE_SFX) * env_shape(n, [(0, 0.0), (0.45, 1.0), (1.0, 0.0)])
    trans_chime = (sine(n, 880, RATE_SFX, amp=0.3) + sine(n, 1320, RATE_SFX, amp=0.25)) * env_shape(n, [(0, 0.0), (0.5, 0.8), (1.0, 0.0)])
    add("map_transition", "transitions/map_transfer.wav", normalize(trans_whoosh * 0.9 + trans_chime, 0.9),
        bus="ui", gain_db=-7.0, spatial=False, purpose="map transition ethereal swell")

    n = int(RATE_SFX * 0.85)
    door_creak = multi_resonator(rng.normal(0, 1, n), [(220, 14.0, 1.0), (380, 16.0, 0.5), (610, 18.0, 0.3)], RATE_SFX) * adsr(n, 0.05, 0.3, 0.4, 0.5)
    add("door_open", "transitions/door_open.wav", normalize(door_creak, 0.7), gain_db=-10.0,
        spatial=True, purpose="heavy medieval door opening creak")

    door_thud = butter_lowpass(rng.normal(0, 1, int(RATE_SFX * 0.28)), 320, RATE_SFX) * exp_decay(int(RATE_SFX * 0.28), 0.08) * 1.1
    door_c_sig = np.copy(door_creak * 0.6)
    door_c_sig[-len(door_thud):] += door_thud * 0.9
    add("door_close", "transitions/door_close.wav", normalize(door_c_sig, 0.8), gain_db=-9.0,
        spatial=True, purpose="heavy medieval door closing latch thud")

    # ----------------------------------------------------------------
    # Continuous Ambient Beds (Lush, non-repetitive, seamless)
    # ----------------------------------------------------------------
    # 1. Exterior Wind Bed (11.5s seamless loop: layered atmospheric gusts)
    n = int(RATE_AMB * 11.5)
    t = np.arange(n) / RATE_AMB
    air_deep = butter_lowpass(brown_noise(n, rng), 220, RATE_AMB) * 0.8
    air_mid = butter_bandpass(pink_noise(n, rng), 400, 1600, RATE_AMB) * 0.6
    # Non-synchronous coprime gust modulations (0.09Hz and 0.14Hz)
    gust_mod = 0.65 + 0.35 * np.sin(2.0 * np.pi * 0.09 * t) * np.sin(2.0 * np.pi * 0.14 * t + 0.8)
    wind_bed = (air_deep + air_mid * gust_mod) * 0.75
    add("amb_exterior_wind", "ambience/exterior_wind.wav",
        normalize(crossfade_loop(wind_bed, int(RATE_AMB * 0.8)), 0.68),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-15.0, spatial=False,
        purpose="exterior wind bed with lush undulating gusts")

    # 2. Exterior Birds / Nature Bed (11.5s seamless loop: serene meadow atmosphere)
    # (Individual calls are handled by dynamic scatter events!)
    birds_bed = butter_bandpass(pink_noise(n, rng), 900, 3200, RATE_AMB) * 0.18
    # Gentle subtle distant calls embedded into bed
    for off_s in (2.2, 5.8, 9.1):
        idx = int(off_s * RATE_AMB)
        call_len = int(RATE_AMB * 0.25)
        if idx + call_len < n:
            call = ping(RATE_AMB, rng.uniform(2800, 3600), 0.25, decay=0.1) * 0.22
            birds_bed[idx:idx + call_len] += call
    add("amb_exterior_birds", "ambience/exterior_birds.wav",
        normalize(crossfade_loop(birds_bed, int(RATE_AMB * 0.6)), 0.45),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-21.0, spatial=False,
        purpose="serene woodland meadow ambient bed")

    # 3. Fireplace Loop (10.0s seamless loop: warm hearth combustion + crackles)
    n = int(RATE_AMB * 10.0)
    t = np.arange(n) / RATE_AMB
    fire_drone = butter_bandpass(brown_noise(n, rng), 60, 340, RATE_AMB) * 0.75
    fire_crack = crackles(rng, RATE_AMB, 10.0, density=14.0, bright=4800.0, level=0.7)
    fire_flame = fire_drone * (0.8 + 0.2 * np.sin(2.0 * np.pi * 1.5 * t)) + fire_crack
    add("amb_fire", "ambience/fire_loop.wav",
        normalize(crossfade_loop(fire_flame, int(RATE_AMB * 0.6)), 0.65),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-16.0,
        purpose="hearth/fire loop with warm low body and authentic wood pops")

    # 4. Candles Loop (8.0s seamless loop)
    n = int(RATE_AMB * 8.0)
    t = np.arange(n) / RATE_AMB
    candle_hiss = butter_highpass(rng.normal(0, 1, n), 4500, RATE_AMB) * 0.2
    candle_pop = crackles(rng, RATE_AMB, 8.0, density=4.0, bright=6500.0, level=0.35)
    candle = (candle_hiss + candle_pop) * (0.75 + 0.25 * np.sin(2.0 * np.pi * 0.8 * t))
    add("amb_candles", "ambience/candle_loop.wav",
        normalize(crossfade_loop(candle, int(RATE_AMB * 0.5)), 0.42),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-23.0,
        purpose="candle flicker sizzle for interior fixtures")

    # 5. Distant Castle Activity (11.0s seamless loop)
    n = int(RATE_AMB * 11.0)
    distant = np.zeros(n)
    t_step = 0.8
    while t_step < 10.2:
        ev_len = int(RATE_AMB * 0.45)
        ev = butter_lowpass(rng.normal(0, 1, ev_len), rng.uniform(180, 400), RATE_AMB) * adsr(ev_len, 0.02, 0.15, 0.2, 0.6)
        st = int(t_step * RATE_AMB)
        if st + ev_len < n:
            distant[st:st + ev_len] += ev * rng.uniform(0.3, 0.65)
        t_step += rng.uniform(1.2, 2.6)
    add("amb_distant", "ambience/distant_activity.wav",
        normalize(crossfade_loop(distant, int(RATE_AMB * 0.6)), 0.45),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-22.0, spatial=False,
        purpose="muffled distant castle presence beyond room walls")

    # 6. Great Hall Room Tone (11.0s seamless loop)
    n = int(RATE_AMB * 11.0)
    hall_air = butter_lowpass(brown_noise(n, rng) + pink_noise(n, rng), 600, RATE_AMB) * 0.6
    hall_rev = reverb(hall_air, RATE_AMB, decay=2.5, mix_amount=0.45, damp=2800.0, size=1.8)
    add("amb_great_hall", "ambience/great_hall.wav",
        normalize(crossfade_loop(hall_rev, int(RATE_AMB * 0.8)), 0.55),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-18.0, spatial=False,
        purpose="Great Hall: large reverberant hall room tone with deep acoustic space")

    # 7. Library Room Tone (10.5s seamless loop)
    n = int(RATE_AMB * 10.5)
    lib_air = butter_lowpass(pink_noise(n, rng), 900, RATE_AMB) * 0.45
    lib_rev = reverb(lib_air, RATE_AMB, decay=0.5, mix_amount=0.15, damp=4800.0, size=0.5)
    add("amb_library", "ambience/library.wav",
        normalize(crossfade_loop(lib_rev, int(RATE_AMB * 0.6)), 0.48),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-20.0, spatial=False,
        purpose="Library: tight dry room tone with gentle scholarly calm")

    # 8. Dungeon Room Tone (11.0s seamless loop)
    n = int(RATE_AMB * 11.0)
    dun_sub = butter_lowpass(brown_noise(n, rng), 240, RATE_AMB) * 0.6
    dun_rev = reverb(dun_sub, RATE_AMB, decay=2.4, mix_amount=0.5, damp=1400.0, size=1.6)
    add("amb_dungeon", "ambience/dungeon.wav",
        normalize(crossfade_loop(dun_rev, int(RATE_AMB * 0.8)), 0.52),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-18.0, spatial=False,
        purpose="Dungeon: dark subterranean stone cellar drone")

    # 9. Moving Stair Mechanism (9.0s seamless loop)
    n = int(RATE_AMB * 9.0)
    grind = multi_resonator(rng.normal(0, 1, n), [(75, 9.0, 1.0), (150, 12.0, 0.6), (320, 15.0, 0.35)], RATE_AMB) * 0.6
    clunks = np.zeros(n)
    for beat in range(8):
        st = int((0.5 + beat * 1.05) * RATE_AMB)
        clunk = multi_resonator(rng.normal(0, 1, int(RATE_AMB * 0.25)), [(180, 12.0, 1.0), (420, 15.0, 0.5)], RATE_AMB) * exp_decay(int(RATE_AMB * 0.25), 0.08)
        if st + len(clunk) < n:
            clunks[st:st + len(clunk)] += clunk * 0.75
    add("amb_stairs", "ambience/stair_mechanism.wav",
        normalize(crossfade_loop(grind + clunks, int(RATE_AMB * 0.6)), 0.6),
        rate=RATE_AMB, loop=True, bus="ambience", gain_db=-17.0, spatial=True,
        purpose="moving-stair mechanism: stone grind with mechanical clunks")

    # ----------------------------------------------------------------
    # Procedural Ambient Scatter Events (The solution to "çevre sesleri repeat ediyor"!)
    # ----------------------------------------------------------------
    # Exterior Bird Chirps (Different species / calls for 3D positional scatter)
    def synth_bird(f0, f1, f2, dur):
        n = int(RATE_SFX * dur)
        t = np.arange(n) / RATE_SFX
        freqs = f0 + (f1 - f0) * np.sin(np.pi * t / dur) + (f2 - f0) * (t / dur)
        ph = 2.0 * np.pi * np.cumsum(freqs) / RATE_SFX
        sig = (np.sin(ph) + 0.35 * np.sin(ph * 2.01)) * adsr(n, 0.08, 0.2, 0.5, 0.22)
        return normalize(sig, 0.8)

    add("amb_bird_chirp_1", "ambience/birds/bird_chirp_01.wav", synth_bird(2800, 3600, 2900, 0.32),
        gain_db=-16.0, pitch_var=0.08, spatial=True, purpose="scatter: robin double-chirp")
    add("amb_bird_chirp_2", "ambience/birds/bird_chirp_02.wav", synth_bird(3200, 4200, 3100, 0.42),
        gain_db=-17.0, pitch_var=0.08, spatial=True, purpose="scatter: warbler melodic trill")
    add("amb_bird_chirp_3", "ambience/birds/bird_chirp_03.wav", synth_bird(2400, 3100, 2200, 0.48),
        gain_db=-16.0, pitch_var=0.08, spatial=True, purpose="scatter: blackbird flute call")
    add("amb_bird_chirp_4", "ambience/birds/bird_chirp_04.wav", synth_bird(1800, 2400, 1900, 0.58),
        gain_db=-18.0, pitch_var=0.06, spatial=True, purpose="scatter: distant wood pigeon coo")

    # Exterior Wind Gusts & Foliage Rustles
    n = int(RATE_SFX * 1.8)
    gust1 = butter_bandpass(brown_noise(n, rng), 120, 900, RATE_SFX) * env_shape(n, [(0, 0.0), (0.4, 1.0), (0.8, 0.6), (1.0, 0.0)])
    add("amb_wind_gust_1", "ambience/wind/wind_gust_01.wav", normalize(gust1, 0.75),
        gain_db=-15.0, pitch_var=0.05, spatial=False, purpose="scatter: gentle rolling breeze gust")
    n = int(RATE_SFX * 2.4)
    gust2 = butter_bandpass(pink_noise(n, rng), 180, 1400, RATE_SFX) * env_shape(n, [(0, 0.0), (0.35, 1.0), (0.7, 0.5), (1.0, 0.0)])
    add("amb_wind_gust_2", "ambience/wind/wind_gust_02.wav", normalize(gust2, 0.75),
        gain_db=-16.0, pitch_var=0.05, spatial=False, purpose="scatter: rolling meadow wind swell")

    n = int(RATE_SFX * 0.85)
    rustle1 = butter_bandpass(pink_noise(n, rng), 800, 3400, RATE_SFX) * adsr(n, 0.1, 0.3, 0.4, 0.2)
    add("amb_leaf_rustle_1", "ambience/nature/leaf_rustle_01.wav", normalize(rustle1, 0.65),
        gain_db=-18.0, pitch_var=0.08, spatial=True, purpose="scatter: gentle leaf rustle in trees")
    n = int(RATE_SFX * 0.95)
    rustle2 = butter_bandpass(pink_noise(n, rng), 600, 2800, RATE_SFX) * adsr(n, 0.12, 0.25, 0.45, 0.18)
    add("amb_leaf_rustle_2", "ambience/nature/leaf_rustle_02.wav", normalize(rustle2, 0.65),
        gain_db=-18.0, pitch_var=0.08, spatial=True, purpose="scatter: branch foliage brushing")

    # Dungeon Water Drops & Cavern Moan
    def synth_drip(f_start, f_end, dur):
        n = int(RATE_SFX * dur)
        t = np.arange(n) / RATE_SFX
        freqs = f_start * np.exp(-t / 0.04) + f_end
        ph = 2.0 * np.pi * np.cumsum(freqs) / RATE_SFX
        sig = np.sin(ph) * exp_decay(n, 0.06)
        rev = reverb(sig, RATE_SFX, decay=1.8, mix_amount=0.45, damp=3200.0, size=1.4)
        return normalize(rev, 0.8)

    add("amb_dungeon_drip_1", "ambience/dungeon/water_drip_01.wav", synth_drip(1450, 780, 0.45),
        gain_db=-14.0, pitch_var=0.09, spatial=True, purpose="scatter: clear cavern water drop")
    add("amb_dungeon_drip_2", "ambience/dungeon/water_drip_02.wav", synth_drip(1200, 620, 0.5),
        gain_db=-14.0, pitch_var=0.09, spatial=True, purpose="scatter: deeper resonance water drip")
    add("amb_dungeon_drip_3", "ambience/dungeon/water_drip_03.wav", synth_drip(1700, 920, 0.55),
        gain_db=-15.0, pitch_var=0.09, spatial=True, purpose="scatter: high-pitched water drop echo")

    n = int(RATE_SFX * 2.6)
    dun_rumble = butter_lowpass(brown_noise(n, rng), 160, RATE_SFX) * env_shape(n, [(0, 0.0), (0.4, 0.85), (0.8, 0.5), (1.0, 0.0)])
    add("amb_dungeon_rumble", "ambience/dungeon/cavern_rumble.wav", normalize(dun_rumble, 0.7),
        gain_db=-16.0, pitch_var=0.04, spatial=False, purpose="scatter: subterranean stone shift")

    # Great Hall & Castle Interior Settlement
    n = int(RATE_SFX * 1.1)
    settle1 = multi_resonator(rng.normal(0, 1, n), [(140, 15.0, 1.0), (320, 18.0, 0.5)], RATE_SFX) * exp_decay(n, 0.18)
    add("amb_hall_settle_1", "ambience/castle/hall_settle_01.wav", normalize(settle1, 0.65),
        gain_db=-18.0, pitch_var=0.07, spatial=True, purpose="scatter: timber settlement creak")
    n = int(RATE_SFX * 0.8)
    settle2 = multi_resonator(rng.normal(0, 1, n), [(220, 18.0, 1.0), (480, 20.0, 0.4)], RATE_SFX) * exp_decay(n, 0.14)
    add("amb_hall_settle_2", "ambience/castle/hall_settle_02.wav", normalize(settle2, 0.65),
        gain_db=-19.0, pitch_var=0.07, spatial=True, purpose="scatter: distant stone click")

    # Library Page Flips
    n = int(RATE_SFX * 0.72)
    page1 = butter_bandpass(pink_noise(n, rng), 1800, 5600, RATE_SFX) * adsr(n, 0.08, 0.25, 0.35, 0.32)
    add("amb_library_page_1", "ambience/library/page_flip_01.wav", normalize(page1, 0.6),
        gain_db=-18.0, pitch_var=0.08, spatial=True, purpose="scatter: parchment page flip")
    n = int(RATE_SFX * 0.85)
    page2 = butter_bandpass(pink_noise(n, rng), 1400, 4800, RATE_SFX) * adsr(n, 0.1, 0.28, 0.4, 0.22)
    add("amb_library_page_2", "ambience/library/page_flip_02.wav", normalize(page2, 0.6),
        gain_db=-18.0, pitch_var=0.08, spatial=True, purpose="scatter: delicate book rustle")

    # Dungeon whispers (ghostly scatter events for the deep stone)
    def synth_whisper(formants, dur):
        n = int(RATE_SFX * dur)
        breath = rng.normal(0, 1, n)
        voiced = np.zeros(n)
        for center, q, gain in formants:
            voiced += resonator(breath, center, q, RATE_SFX) * gain
        syllables = np.zeros(n)
        pos = 0.05
        while pos < dur - 0.18:
            length = rng.uniform(0.14, 0.3)
            start = int(pos * RATE_SFX)
            end = min(n, start + int(length * RATE_SFX))
            if end > start:
                shape = np.sin(np.linspace(0.0, np.pi, end - start)) ** 1.6
                syllables[start:end] = np.maximum(syllables[start:end], shape)
            pos += length + rng.uniform(0.1, 0.28)
        whisper = voiced * (0.25 + 0.75 * syllables)
        whisper = reverb(whisper, RATE_SFX, decay=2.2, mix_amount=0.5, damp=2600.0, size=1.6)
        return normalize(whisper, 0.55)

    add("amb_dungeon_whisper_1", "ambience/dungeon/whisper_01.wav",
        synth_whisper([(520.0, 8.0, 1.0), (1400.0, 10.0, 0.55), (2500.0, 12.0, 0.3)], 1.9),
        gain_db=-20.0, pitch_var=0.09, spatial=True, purpose="scatter: ghostly dungeon whisper")
    add("amb_dungeon_whisper_2", "ambience/dungeon/whisper_02.wav",
        synth_whisper([(430.0, 7.0, 1.0), (1150.0, 9.0, 0.6), (2100.0, 11.0, 0.35)], 2.3),
        gain_db=-21.0, pitch_var=0.09, spatial=True, purpose="scatter: distant sighing draft")

    # ----------------------------------------------------------------
    # Creature voice families (one per species: move / alert / attack / death)
    # ----------------------------------------------------------------
    for variant in range(3):
        n = int(RATE_SFX * 0.55)
        t = np.arange(n) / RATE_SFX
        rasp = butter_bandpass(brown_noise(n, rng), 130.0, 720.0, RATE_SFX)
        rasp *= 0.6 + 0.4 * np.sin(2.0 * np.pi * rng.uniform(6.0, 9.0) * t + rng.uniform(0.0, 6.28))
        gravel = crackles(rng, RATE_SFX, 0.55, density=30.0, bright=3200.0, level=0.3)
        add("snatcher_move_%d" % (variant + 1), "monsters/snatcher_move_%02d.wav" % (variant + 1),
            normalize(soft_clip(rasp * 0.9 + gravel, drive=1.2), 0.72),
            gain_db=-14.0, pitch_var=0.07, purpose="snatcher rasping breath %d" % (variant + 1))

        n = int(RATE_SFX * 0.9)
        t = np.arange(n) / RATE_SFX
        groan_f = rng.uniform(85.0, 105.0) * (1.0 + 0.16 * np.sin(2.0 * np.pi * 0.7 * t))
        groan = _phase_sin(groan_f, RATE_SFX) * adsr(n, 0.12, 0.25, 0.6, 0.3)
        wet = butter_bandpass(brown_noise(n, rng), 200.0, 1300.0, RATE_SFX) * adsr(n, 0.15, 0.2, 0.5, 0.35)
        add("inferi_move_%d" % (variant + 1), "monsters/inferi_move_%02d.wav" % (variant + 1),
            normalize(soft_clip(groan * 0.8 + wet * 0.6, drive=1.15), 0.68),
            gain_db=-14.5, pitch_var=0.07, purpose="inferi ghoul moan %d" % (variant + 1))

    n = int(RATE_SFX * 0.5)
    t = np.arange(n) / RATE_SFX
    hiss = butter_bandpass(rng.normal(0, 1, n), 3000.0, 9400.0, RATE_SFX) * adsr(n, 0.05, 0.2, 0.55, 0.3) * 0.9
    hiss *= 0.7 + 0.3 * np.sin(2.0 * np.pi * 26.0 * t)
    rattle = np.zeros(n)
    for _ in range(7):
        off = rng.randint(0, max(1, n - 900))
        tap = butter_bandpass(rng.normal(0, 1, 900), 2400.0, 6400.0, RATE_SFX) * exp_decay(900, 0.05)
        rattle[off:off + 900] += tap * 0.5
    add("spider_alert", "monsters/spider_alert.wav", normalize(hiss + rattle, 0.85),
        gain_db=-6.0, pitch_var=0.05, purpose="spider alert: agitated hiss and chitin rattle")

    n = int(RATE_SFX * 1.1)
    t = np.arange(n) / RATE_SFX
    growl_f = 72.0 + 130.0 * (t / t[-1]) ** 1.4
    snarl = _phase_sin(growl_f, RATE_SFX) * adsr(n, 0.04, 0.25, 0.75, 0.2)
    snarl *= 0.75 + 0.25 * np.sin(2.0 * np.pi * 11.0 * t)
    snarl_hiss = butter_bandpass(rng.normal(0, 1, n), 1600.0, 6200.0, RATE_SFX) * adsr(n, 0.06, 0.2, 0.5, 0.35) * 0.5
    add("snatcher_alert", "monsters/snatcher_alert.wav",
        normalize(soft_clip(snarl * 1.1 + snarl_hiss, drive=1.3), 0.9),
        gain_db=-5.5, pitch_var=0.04, purpose="snatcher alert: rising hooded snarl")

    n = int(RATE_SFX * 1.4)
    t = np.arange(n) / RATE_SFX
    moan_f = 190.0 + 240.0 * (t / t[-1]) ** 1.6
    moan = _phase_sin(moan_f, RATE_SFX) * adsr(n, 0.1, 0.3, 0.7, 0.25)
    moan = multi_resonator(moan, [(420.0, 9.0, 0.7), (1180.0, 11.0, 0.5)], RATE_SFX) + moan * 0.5
    breath = butter_bandpass(pink_noise(n, rng), 500.0, 2600.0, RATE_SFX) * adsr(n, 0.15, 0.25, 0.55, 0.3) * 0.5
    add("inferi_alert", "monsters/inferi_alert.wav",
        normalize(soft_clip(moan + breath, drive=1.15), 0.88),
        bus="sfx", gain_db=-6.0, pitch_var=0.04, purpose="inferi alert: rising hollow moan")

    n = int(RATE_SFX * 0.55)
    t = np.arange(n) / RATE_SFX
    lunge = _phase_sin(160.0 * (1.0 + 0.5 * (t / t[-1])), RATE_SFX) * exp_decay(n, 0.12) * 0.8
    lunge_snap = butter_bandpass(rng.normal(0, 1, n), 1400.0, 5200.0, RATE_SFX) * exp_decay(n, 0.035) * 1.1
    curse_hiss = butter_bandpass(rng.normal(0, 1, n), 500.0, 2600.0, RATE_SFX) * adsr(n, 0.02, 0.15, 0.4, 0.4) * 0.6
    add("snatcher_attack", "monsters/snatcher_attack.wav",
        normalize(soft_clip(lunge + lunge_snap + curse_hiss, drive=1.25), 0.92),
        gain_db=-5.5, pitch_var=0.05, purpose="snatcher attack: lunging curse release")

    n = int(RATE_SFX * 0.6)
    t = np.arange(n) / RATE_SFX
    bite = butter_bandpass(rng.normal(0, 1, n), 900.0, 3600.0, RATE_SFX) * exp_decay(n, 0.05) * 1.15
    bite_thud = _phase_sin(110.0 * np.exp(-t / 0.05) + 45.0, RATE_SFX) * exp_decay(n, 0.07) * 0.9
    add("inferi_attack", "monsters/inferi_attack.wav",
        normalize(soft_clip(bite + bite_thud, drive=1.2), 0.9),
        gain_db=-5.5, pitch_var=0.06, purpose="inferi attack: grasping bite")

    n = int(RATE_SFX * 1.7)
    t = np.arange(n) / RATE_SFX
    rasp_fall = butter_bandpass(brown_noise(n, rng), 120.0, 700.0, RATE_SFX) * exp_decay(n, 0.5) * 1.1
    choke = _phase_sin(90.0 * np.exp(-t / 0.35) + 42.0, RATE_SFX) * exp_decay(n, 0.6) * 0.7
    collapse = butter_lowpass(rng.normal(0, 1, n), 260.0, RATE_SFX) * exp_decay(n, 0.25) * 0.8
    add("snatcher_death", "monsters/snatcher_death.wav",
        normalize(soft_clip(rasp_fall + choke + collapse, drive=1.25), 0.9),
        gain_db=-5.0, pitch_var=0.04, purpose="snatcher death: choked rasp and collapse")

    n = int(RATE_SFX * 1.9)
    t = np.arange(n) / RATE_SFX
    exhale_f = 260.0 * np.exp(-t / 0.8) + 95.0
    exhale = _phase_sin(exhale_f, RATE_SFX) * exp_decay(n, 0.7) * 0.8
    exhale = multi_resonator(exhale, [(480.0, 10.0, 0.6), (1250.0, 12.0, 0.4)], RATE_SFX) + exhale * 0.4
    ash = butter_lowpass(rng.normal(0, 1, n), 380.0, RATE_SFX) * exp_decay(n, 0.4) * 0.7
    add("inferi_death", "monsters/inferi_death.wav",
        normalize(soft_clip(exhale + ash, drive=1.2), 0.88),
        gain_db=-5.0, pitch_var=0.04, purpose="inferi death: long collapsing exhale")

    n = int(RATE_SFX * 2.1)
    t = np.arange(n) / RATE_SFX
    stone = multi_resonator(rng.normal(0, 1, n), [(58.0, 9.0, 1.0), (118.0, 11.0, 0.6), (240.0, 13.0, 0.35)], RATE_SFX)
    stone *= adsr(n, 0.1, 0.3, 0.8, 0.3)
    roar_f = 62.0 + 90.0 * (t / t[-1]) ** 1.2
    roar = _phase_sin(roar_f, RATE_SFX) * adsr(n, 0.08, 0.3, 0.8, 0.25)
    add("boss_alert", "monsters/boss_alert.wav",
        normalize(soft_clip(stone * 0.9 + roar * 0.8, drive=1.35), 0.94),
        gain_db=-4.0, pitch_var=0.03, purpose="boss alert: monolith-stone awakening roar")

    # ----------------------------------------------------------------
    # Player cues (death, respawn, coin)
    # ----------------------------------------------------------------
    n = int(RATE_SFX * 1.9)
    t = np.arange(n) / RATE_SFX
    death_sub = _phase_sin(120.0 * np.exp(-t / 0.5) + 38.0, RATE_SFX) * exp_decay(n, 0.75) * 1.2
    death_bells = ping(RATE_SFX, 220, 1.9, decay=0.8,
                       partials=((1.0, 1.0), (1.06, 0.8), (2.02, 0.4), (2.98, 0.22)))
    death_swell = butter_lowpass(brown_noise(n, rng), 500.0, RATE_SFX) * adsr(n, 0.2, 0.3, 0.5, 0.4) * 0.7
    add("ui_death", "ui/death.wav",
        normalize(soft_clip(death_sub + death_bells * 0.8 + death_swell, drive=1.2), 0.92),
        bus="ui", gain_db=-5.0, spatial=False, purpose="player death: low gong and dark swell")

    n = int(RATE_SFX * 1.25)
    respawn_swell = butter_bandpass(pink_noise(n, rng), 700.0, 4200.0, RATE_SFX) \
        * adsr(n, 0.25, 0.25, 0.6, 0.3) * 0.8
    respawn_arp = np.zeros(n)
    for index, semitones in enumerate((0, 4, 7, 12)):
        start = int((0.12 + 0.16 * index) * RATE_SFX)
        tone = ping(RATE_SFX, 523.25 * (2.0 ** (semitones / 12.0)), 1.0, decay=0.28) * 0.7
        end = min(n, start + len(tone))
        respawn_arp[start:end] += tone[:end - start]
    add("ui_respawn", "ui/respawn.wav", normalize(respawn_swell + respawn_arp, 0.85),
        bus="ui", gain_db=-7.0, spatial=False, purpose="respawn: warm rising shimmer and chime arpeggio")

    n = int(RATE_SFX * 0.28)
    t = np.arange(n) / RATE_SFX
    clink1 = ping(RATE_SFX, 2650, 0.16, decay=0.045,
                  partials=((1.0, 1.0), (2.87, 0.4), (5.4, 0.18))) * 1.0
    clink2 = ping(RATE_SFX, 3550, 0.22, decay=0.08,
                  partials=((1.0, 1.0), (3.1, 0.35), (5.9, 0.15))) * 0.8
    coin = np.zeros(n)
    coin[:len(clink1)] += clink1
    offset = int(0.055 * RATE_SFX)
    end = min(n, offset + len(clink2))
    coin[offset:end] += clink2[:end - offset]
    add("ui_coin", "ui/coin.wav", normalize(coin, 0.8),
        bus="ui", gain_db=-9.0, spatial=False, pitch_var=0.05, purpose="UI galleons added")

    return out


# ------------------------------------------------------------------ Classical Music Beds
#
# Original synthesised arrangements of public-domain classical material
# (Grieg, Pachelbel, Bach, Beethoven and Satie wrote these ideas before 1925;
# nothing here is derived from a recording). A small built-in sequencer places
# notes into instrument models and renders stereo, seam-continuous beds sized
# for a game loop.

RATE_MUSIC = 44100

_COMB_TUNING = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
_ALLPASS_TUNING = (556, 441, 341, 225)
_STEREO_SPREAD = 23

_NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def n(name):
    """'C4', 'Eb3', 'F#2' -> MIDI note number (C4 = 60)."""
    letter = name[0].upper()
    index = 1
    accidental = 0
    while index < len(name) and name[index] in "#b":
        accidental += 1 if name[index] == "#" else -1
        index += 1
    return 12 * (int(name[index:]) + 1) + _NOTE_BASE[letter] + accidental


def _lowpass_axis0(sig, cutoff, rate, order=2):
    nyq = 0.5 * rate
    norm = float(np.clip(cutoff / nyq, 0.001, 0.96))
    b, a = sp.butter(order, norm, btype='low')
    return sp.lfilter(b, a, sig, axis=0)


def _bandpass_axis0(sig, low, high, rate, order=2):
    nyq = 0.5 * rate
    low_norm = float(np.clip(low / nyq, 0.001, 0.94))
    high_norm = float(np.clip(high / nyq, low_norm + 0.01, 0.96))
    b, a = sp.butter(order, [low_norm, high_norm], btype='band')
    return sp.lfilter(b, a, sig, axis=0)


def _pan(mono, pan):
    """Equal-power pan of a mono signal into an (n, 2) stereo pair."""
    theta = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * (math.pi / 4.0)
    out = np.zeros((len(mono), 2))
    out[:, 0] = mono * math.cos(theta)
    out[:, 1] = mono * math.sin(theta)
    return out


def crossfade_loop_stereo(sig, fade_samples):
    """Stereo-aware version of crossfade_loop."""
    total = len(sig)
    fade = min(fade_samples, total // 4)
    if fade <= 1:
        return sig
    length = total - fade
    out = np.copy(sig[:length])
    t = np.linspace(0.0, 1.0, fade)[:, None]
    out[:fade] = sig[:fade] * t + sig[length:length + fade] * (1.0 - t)
    return out


def reverb_stereo(sig, rate, room=0.84, damp=0.38, mix_amount=0.32):
    """Send-style stereo reverb: 8 damped combs + 4 allpasses per side."""
    scale = rate / 44100.0
    total = len(sig)
    src = 0.5 * (sig[:, 0] + sig[:, 1])
    wet = np.zeros((total, 2))
    for channel, offset in ((0, 0), (1, _STEREO_SPREAD)):
        acc = np.zeros(total)
        for tuning in _COMB_TUNING:
            delay = max(8, int((tuning + offset) * scale))
            a = np.zeros(delay + 2)
            a[0] = 1.0
            a[delay] += -room * (1.0 - damp)
            a[delay + 1] += -room * damp
            acc += sp.lfilter([1.0], a, src)
        for tuning in _ALLPASS_TUNING:
            delay = max(4, int((tuning + offset) * scale))
            b = np.zeros(delay + 1)
            b[0] = -1.0
            b[delay] = 1.0
            a = np.zeros(delay + 1)
            a[0] = 1.0
            a[delay] = -0.5
            acc = sp.lfilter(b, a, acc)
        wet[:, channel] = acc
    src_rms = float(np.sqrt(np.mean(src ** 2))) + 1e-9
    wet_rms = float(np.sqrt(np.mean(wet ** 2))) + 1e-9
    wet *= (src_rms * 1.25) / wet_rms
    return sig + wet * mix_amount


def note_env(n, rate, attack_s, release_s):
    """Per-note envelope in seconds, not fractions of the buffer."""
    env = np.ones(n)
    attack = max(1, min(n // 2, int(attack_s * rate)))
    release = max(1, min(n // 2, int(release_s * rate)))
    env[:attack] = np.linspace(0.0, 1.0, attack) ** 1.4
    env[-release:] = np.linspace(1.0, 0.0, release) ** 1.3
    return env


def _phase_sin(freqs, rate, phase=0.0):
    return np.sin(2.0 * np.pi * np.cumsum(freqs) / float(rate) + phase)


def _phase_saw(freqs, rate, phase=0.0):
    return sp.sawtooth(2.0 * np.pi * np.cumsum(freqs) / float(rate) + phase)


# ------------------------------------------------------------- instrument models

def instr_strings(freq, seconds, rate, rng, amp=0.5, attack=0.22, release=0.45,
                  vibrato=5.2, brightness=1.0):
    n = int(seconds * rate) + int(release * rate)
    t = np.arange(n) / float(rate)
    depth = 0.0035
    f = freq * (1.0 + depth * np.sin(2.0 * np.pi * vibrato * t + rng.uniform(0.0, 6.28)))
    ph = 2.0 * np.pi * np.cumsum(f) / rate
    acc = np.zeros(n)
    for cents, weight in ((-6.5, 0.5), (0.0, 0.58), (5.5, 0.46)):
        acc += sp.sawtooth(ph * (2.0 ** (cents / 1200.0)) + rng.uniform(0.0, 6.28)) * weight
    cutoff = min(rate * 0.45, (1500.0 + 2.4 * freq) * brightness)
    acc = _lowpass_axis0(acc, cutoff, rate)
    acc *= note_env(n, rate, attack, release)
    acc *= 1.0 + 0.08 * np.sin(2.0 * np.pi * 0.45 * t + 1.1)  # slow swell
    return acc * amp


def instr_choir(freq, seconds, rate, rng, amp=0.4, attack=0.5, release=0.7):
    n = int(seconds * rate) + int(release * rate)
    t = np.arange(n) / float(rate)
    f = freq * (1.0 + 0.004 * np.sin(2.0 * np.pi * 4.4 * t + rng.uniform(0.0, 6.28)))
    ph = 2.0 * np.pi * np.cumsum(f) / rate
    src = sp.sawtooth(ph) * 0.7 + sp.sawtooth(ph * 1.006 + 1.3) * 0.5
    voiced = np.zeros(n)
    for center, q, gain in ((760.0, 7.0, 1.0), (1180.0, 9.0, 0.66), (2650.0, 12.0, 0.34), (3400.0, 14.0, 0.12)):
        voiced += resonator(src, min(center, rate * 0.44), q, rate) * gain
    voiced = _lowpass_axis0(voiced, 4200.0, rate)
    voiced *= note_env(n, rate, attack, release)
    return voiced * amp


def instr_piano(freq, seconds, rate, rng, amp=0.55, release=0.3):
    n = int(seconds * rate)
    t = np.arange(n) / float(rate)
    out = np.zeros(n)
    inharm = 0.0004
    for k in range(1, 13):
        partial = freq * k * math.sqrt(1.0 + inharm * k * k)
        if partial > rate * 0.45:
            break
        tau = (2.8 / (1.0 + 0.5 * (k - 1))) * (220.0 / max(55.0, freq)) ** 0.35
        decay = np.exp(-t / max(0.05, tau))
        pair = np.sin(2.0 * np.pi * partial * t + rng.uniform(0.0, 6.28))
        pair += np.sin(2.0 * np.pi * (partial + 0.6) * t) * 0.35  # string pair beating
        out += pair * decay * (1.0 / (k ** 1.55))
    hammer = min(n, int(0.025 * rate))
    out[:hammer] += butter_bandpass(rng.normal(0, 1, hammer), 900.0, 6500.0, rate) \
        * np.exp(-np.linspace(0.0, 1.0, hammer) / 0.2) * 0.22
    out *= note_env(n, rate, 0.004, min(release, seconds * 0.5))
    return out * amp


def instr_organ(freq, seconds, rate, rng, amp=0.5, attack=0.06, release=0.25):
    n = int(seconds * rate) + int(release * rate)
    t = np.arange(n) / float(rate)
    out = np.zeros(n)
    for ratio, weight in ((1.0, 1.0), (2.0, 0.6), (3.0, 0.45), (4.0, 0.3), (6.0, 0.18), (8.0, 0.12)):
        partial = freq * ratio
        if partial > rate * 0.45:
            continue
        out += np.sin(2.0 * np.pi * partial * t) * weight
        out += np.sin(2.0 * np.pi * (partial * 1.002) * t) * weight * 0.5  # chorus rank
    click = min(n, int(0.012 * rate))
    out[:click] += rng.normal(0, 1, click) * np.exp(-np.linspace(0.0, 1.0, click)) * 0.25
    out *= note_env(n, rate, attack, release)
    return out * amp


def instr_harp(freq, seconds, rate, rng, amp=0.5):
    n = int(seconds * rate)
    t = np.arange(n) / float(rate)
    out = np.zeros(n)
    for k in range(1, 9):
        partial = freq * k
        if partial > rate * 0.45:
            break
        tau = 1.6 / (1.0 + 0.8 * (k - 1))
        out += np.sin(2.0 * np.pi * partial * t + rng.uniform(0.0, 6.28)) \
            * np.exp(-t / tau) * (1.0 / (k ** 1.7))
    pluck = min(n, int(0.02 * rate))
    out[:pluck] += butter_bandpass(rng.normal(0, 1, pluck), 1500.0, 6000.0, rate) \
        * np.exp(-np.linspace(0.0, 1.0, pluck) / 0.3) * 0.3
    out *= note_env(n, rate, 0.003, min(0.25, seconds * 0.5))
    return out * amp


def instr_bell(freq, seconds, rate, rng, amp=0.4):
    n = int(seconds * rate)
    t = np.arange(n) / float(rate)
    out = np.zeros(n)
    for ratio, weight, tau in ((1.0, 1.0, 3.4), (2.01, 0.62, 2.4), (2.98, 0.4, 1.7),
                               (4.16, 0.26, 1.1), (5.43, 0.16, 0.8), (8.21, 0.08, 0.5)):
        partial = freq * ratio
        if partial > rate * 0.45:
            continue
        beat = np.sin(2.0 * np.pi * partial * t) + np.sin(2.0 * np.pi * (partial + 0.45) * t) * 0.8
        out += beat * np.exp(-t / tau) * weight
    strike = min(n, int(0.01 * rate))
    out[:strike] += rng.normal(0, 1, strike) * np.exp(-np.linspace(0.0, 1.0, strike)) * 0.3
    out *= note_env(n, rate, 0.002, min(0.4, seconds * 0.5))
    return out * amp


def instr_flute(freq, seconds, rate, rng, amp=0.42, attack=0.07, release=0.25):
    n = int(seconds * rate) + int(release * rate)
    t = np.arange(n) / float(rate)
    f = freq * (1.0 + 0.005 * np.sin(2.0 * np.pi * 5.0 * t + rng.uniform(0.0, 6.28)))
    out = _phase_sin(f, rate) + 0.22 * _phase_sin(f * 2.0, rate) * np.exp(-t / 0.5)
    breath = butter_bandpass(rng.normal(0, 1, n), 1800.0, 7200.0, rate) * 0.045
    chiff = min(n, int(0.05 * rate))
    breath[:chiff] += rng.normal(0, 1, chiff) * np.exp(-np.linspace(0.0, 1.0, chiff) / 0.25) * 0.2
    out *= note_env(n, rate, attack, release)
    return (out + breath * note_env(n, rate, attack, release)) * amp


def instr_oboe(freq, seconds, rate, rng, amp=0.4, attack=0.09, release=0.28):
    n = int(seconds * rate) + int(release * rate)
    t = np.arange(n) / float(rate)
    f = freq * (1.0 + 0.006 * np.sin(2.0 * np.pi * 5.6 * t + rng.uniform(0.0, 6.28)))
    out = np.zeros(n)
    for k, weight in ((1, 1.0), (2, 0.28), (3, 0.62), (4, 0.16), (5, 0.34), (6, 0.1), (7, 0.18), (8, 0.06)):
        partial = f * k
        if partial[-1] > rate * 0.45:
            continue
        out += _phase_sin(partial, rate) * weight
    out = resonator(out, 1480.0, 4.0, rate) + out * 0.35
    out *= note_env(n, rate, attack, release)
    return out * amp


def instr_horn(freq, seconds, rate, rng, amp=0.42, attack=0.12, release=0.4):
    n = int(seconds * rate) + int(release * rate)
    t = np.arange(n) / float(rate)
    f = freq * (1.0 + 0.003 * np.sin(2.0 * np.pi * 4.6 * t))
    out = _phase_saw(f, rate) * 0.6 + _phase_sin(f, rate) * 0.7
    out = butter_bandpass(out, max(180.0, freq * 0.5), min(rate * 0.42, 2200.0), rate)
    env = note_env(n, rate, attack, release)
    env *= 1.0 + 0.18 * np.sin(2.0 * np.pi * (0.8 / max(0.25, seconds)) * t)  # noble swell
    out = soft_clip(out * env * 2.1, drive=1.6)
    return out * amp


def instr_timpani(freq, seconds, rate, rng, amp=0.6):
    n = int(seconds * rate)
    t = np.arange(n) / float(rate)
    drop = freq * 1.05 * np.exp(-t / 0.09) + freq * 0.97
    body = _phase_sin(drop, rate) * np.exp(-t / (seconds * 0.45))
    body += _phase_sin(drop * 1.98, rate) * np.exp(-t / (seconds * 0.22)) * 0.25
    mallet = butter_lowpass(rng.normal(0, 1, n), 420.0, rate) * np.exp(-t / 0.035) * 0.8
    out = soft_clip(body * 1.4 + mallet, drive=1.4)
    return out * amp


def instr_bass_pizz(freq, seconds, rate, rng, amp=0.5):
    n = int(seconds * rate)
    t = np.arange(n) / float(rate)
    out = np.sin(2.0 * np.pi * freq * t) * np.exp(-t / 0.32)
    out += np.sin(2.0 * np.pi * freq * 2.0 * t) * np.exp(-t / 0.18) * 0.35
    thump = butter_lowpass(rng.normal(0, 1, n), 300.0, rate) * np.exp(-t / 0.025) * 0.7
    return soft_clip(out + thump, drive=1.3) * amp


class Score:
    """A tiny note sequencer: beats in, stereo audio out."""

    def __init__(self, bpm, beats_per_bar=4, rng=None):
        self.bpm = float(bpm)
        self.beats_per_bar = int(beats_per_bar)
        self.beat_s = 60.0 / self.bpm
        self.rng = rng if rng is not None else np.random.RandomState(1)
        self.events = []

    def add(self, beat, dur_beats, instrument, midi_note, amp=0.5, pan=0.0):
        frequency = 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))
        self.events.append((beat * self.beat_s, max(0.06, dur_beats * self.beat_s),
                            instrument, frequency, float(amp), float(pan)))

    def chord(self, beat, dur, instrument, notes, amp=0.4, spread=0.4):
        count = len(notes)
        for index, midi_note in enumerate(notes):
            pan = 0.0 if count < 2 else (-spread + 2.0 * spread * index / (count - 1))
            self.add(beat, dur, instrument, midi_note, amp, pan)

    def render(self, bars, tail_bars=1):
        total = int((bars + tail_bars) * self.beats_per_bar * self.beat_s * RATE_MUSIC)
        buffer = np.zeros((total, 2))
        for start_s, dur_s, instrument, frequency, amp, pan in self.events:
            start = int(start_s * RATE_MUSIC)
            if start >= total:
                continue
            sig = instrument(frequency, dur_s, RATE_MUSIC, self.rng, amp)
            end = min(total, start + len(sig))
            buffer[start:end] += _pan(sig[:end - start], pan)
        return buffer


# ------------------------------------------------------------- the five tracks

def _music_menu(rng):
    """'Wistful Waltz' - Satie's Gymnopedie mood: slow 3/4, sparse, floating."""
    score = Score(57.0, 3, rng)
    bar = score.beats_per_bar

    bass = ["G2", "D3", "G2", "Eb3", "G2", "D3", "Eb3", "Bb2", "C3", "D3", "G2", "D3"]
    for index, note in enumerate(bass):
        score.add(index * bar, 2.6, instr_piano, n(note), 0.30, -0.25)
    chords = [["Bb3", "D4", "G4"], ["A3", "D4", "F4"], ["Bb3", "D4", "G4"], ["Bb3", "Eb4", "G4"],
              ["C4", "Eb4", "G4"], ["A3", "D4", "F#4"], ["Bb3", "Eb4", "G4"], ["D4", "F4", "Bb4"],
              ["C4", "Eb4", "G4"], ["A3", "D4", "F#4"], ["Bb3", "D4", "G4"], ["Bb3", "D4", "G4"]]
    for index, voicing in enumerate(chords):
        score.chord(index * bar, 2.4, instr_strings, [n(x) for x in voicing], amp=0.12, spread=0.5)

    melody = [
        (0.0, 2.0, "D5"), (2.0, 1.0, "Bb4"),        # bar 1
        (3.0, 2.0, "A4"), (5.0, 1.0, "F4"),         # bar 2
        (6.0, 2.0, "G4"), (8.0, 1.0, "Bb4"),        # bar 3
        (9.0, 2.0, "Eb5"), (11.0, 1.0, "D5"),       # bar 4
        (12.0, 2.0, "C5"), (14.0, 1.0, "G4"),       # bar 5
        (15.0, 2.0, "F#4"), (17.0, 1.0, "A4"),      # bar 6
        (18.0, 2.0, "Bb4"), (20.0, 1.0, "G4"),      # bar 7
        (21.0, 2.5, "F4"), (23.5, 1.5, "D5"),       # bar 8
        (24.0, 2.0, "Eb5"), (26.0, 1.0, "C5"),      # bar 9
        (27.0, 2.0, "A4"), (29.0, 1.0, "D5"),       # bar 10
        (30.0, 2.0, "Bb4"), (32.0, 1.0, "G4"),      # bar 11
        (33.0, 3.0, "D4"),                          # bar 12
    ]
    for beat, dur, note in melody:
        score.add(beat, dur, instr_piano, n(note), 0.34, 0.18)

    for beat, note in ((0.0, "D5"), (9.0, "G5"), (21.0, "Bb4"), (30.0, "Eb5")):
        score.add(beat, 6.0, instr_bell, n(note), 0.10, 0.35)

    rendered = score.render(bars=12, tail_bars=1)
    rendered = reverb_stereo(rendered, RATE_MUSIC, room=0.78, damp=0.42, mix_amount=0.30)
    bar_s = bar * score.beat_s
    return crossfade_loop_stereo(rendered, int(bar_s * RATE_MUSIC))


def _music_map(rng):
    """'Pastoral Dawn' - Grieg's Morning Mood mood: bright pastoral 4/4."""
    score = Score(96.0, 4, rng)
    bar = score.beats_per_bar

    progression = [("G", ["G2"]), ("D", ["D3"]), ("Em", ["E2"]), ("C", ["C3"]),
                   ("G", ["G2"]), ("D", ["D3"]), ("C", ["C3"]), ("D", ["D3"]),
                   ("Em", ["E2"]), ("C", ["C3"]), ("G", ["G2"]), ("D", ["D3"]),
                   ("Am", ["A2"]), ("C", ["C3"]), ("D", ["D3"]), ("G", ["G2"])]
    voicings = {
        "G": ["G3", "B3", "D4"], "D": ["F#3", "A3", "D4"], "Em": ["G3", "B3", "E4"],
        "C": ["E3", "G3", "C4"], "Am": ["A3", "C4", "E4"],
    }
    for index, (chord_name, root) in enumerate(progression):
        score.add(index * bar, 3.6, instr_bass_pizz, n(root[0]), 0.30, 0.0)
        score.chord(index * bar, 3.8, instr_strings, [n(x) for x in voicings[chord_name]],
                    amp=0.10, spread=0.55)

    melody = [
        (0.0, 1.0, "B4"), (1.0, 1.0, "D5"), (2.0, 2.0, "E5"),
        (4.0, 1.0, "D5"), (5.0, 1.0, "B4"), (6.0, 2.0, "G4"),
        (8.0, 1.0, "A4"), (9.0, 1.0, "B4"), (10.0, 2.0, "C5"),
        (12.0, 1.0, "B4"), (13.0, 1.0, "A4"), (14.0, 2.0, "G4"),
        (16.0, 1.0, "G4"), (17.0, 1.0, "A4"), (18.0, 1.0, "B4"), (19.0, 1.0, "D5"),
        (20.0, 1.0, "C5"), (21.0, 1.0, "B4"), (22.0, 2.0, "A4"),
        (24.0, 1.0, "B4"), (25.0, 1.0, "D5"), (26.0, 2.0, "E5"),
        (28.0, 2.0, "D5"), (30.0, 1.0, "B4"), (31.5, 0.5, "D5"),
        (32.0, 1.0, "E5"), (33.0, 1.0, "D5"), (34.0, 2.0, "B4"),
        (36.0, 1.0, "A4"), (37.0, 1.0, "B4"), (38.0, 2.0, "G4"),
        (40.0, 0.5, "G4"), (40.5, 0.5, "A4"), (41.0, 1.0, "B4"), (42.0, 2.0, "D5"),
        (44.0, 2.0, "E5"), (46.0, 1.0, "D5"), (47.0, 1.0, "B4"),
        (48.0, 2.0, "A4"), (50.0, 2.0, "C5"),
        (52.0, 2.0, "B4"), (54.0, 2.0, "A4"),
        (56.0, 1.0, "G4"), (57.0, 1.0, "B4"), (58.0, 2.0, "D5"),
        (60.0, 4.0, "G4"),
    ]
    for beat, dur, note in melody:
        score.add(beat, dur, instr_flute, n(note), 0.30, -0.28)

    echoes = [(16.0, 4.0, "D4"), (24.0, 2.0, "E4"), (28.0, 2.0, "B3"),
              (40.0, 4.0, "D4"), (48.0, 2.0, "C4"), (52.0, 2.0, "A3"), (56.0, 4.0, "B3")]
    for beat, dur, note in echoes:
        score.add(beat, dur, instr_oboe, n(note), 0.14, 0.38)

    arp_shapes = {"G": ["G3", "B3", "D4", "G4"], "D": ["D3", "F#3", "A3", "D4"],
                  "Em": ["E3", "G3", "B3", "E4"], "C": ["C3", "E3", "G3", "C4"],
                  "Am": ["A2", "C3", "E3", "A3"]}
    for index, (chord_name, _root) in enumerate(progression):
        shape = arp_shapes[chord_name]
        for step in range(8):
            if (index + step) % 4 == 3:
                continue
            note = shape[step % len(shape)] if step < 4 else shape[3 - (step - 4)]
            score.add(index * bar + step * 0.5, 0.9, instr_harp, n(note), 0.075, -0.42)

    score.add(0.0, 2.0, instr_timpani, n("G2"), 0.16, 0.0)
    score.add(32.0, 2.0, instr_timpani, n("G2"), 0.18, 0.0)
    score.add(62.0, 2.0, instr_timpani, n("D2"), 0.14, 0.0)

    rendered = score.render(bars=16, tail_bars=1)
    rendered = reverb_stereo(rendered, RATE_MUSIC, room=0.72, damp=0.45, mix_amount=0.26)
    bar_s = bar * score.beat_s
    return crossfade_loop_stereo(rendered, int(bar_s * RATE_MUSIC))


def _music_castle(rng):
    """'Canon of the Halls' - the Pachelbel progression with bells and choir."""
    score = Score(64.0, 4, rng)
    bar = score.beats_per_bar

    bass_line = ["D3", "A2", "B2", "F#2", "G2", "D3", "G2", "A2"]
    chord_line = [["D4", "F#4", "A4"], ["A3", "C#4", "E4"], ["B3", "D4", "F#4"],
                  ["F#3", "A3", "C#4"], ["G3", "B3", "D4"], ["D4", "F#4", "A4"],
                  ["G3", "B3", "D4"], ["A3", "C#4", "E4"]]
    bell_line = ["D5", "A4", "B4", "F#4", "G4", "D5", "G4", "A4"]

    for repeat in range(3):
        base = repeat * 4 * bar
        for step in range(8):
            start = base + step * 2.0
            root = bass_line[step]
            if repeat == 2:
                score.add(start, 1.9, instr_bass_pizz, n(root), 0.34, 0.0)
            score.chord(start, 1.9, instr_strings, [n(x) for x in chord_line[step]],
                        amp=0.115, spread=0.6)
            score.add(start, 3.2, instr_bell, n(bell_line[step]),
                      0.085 if repeat < 2 else 0.10, 0.45)
            shape = chord_line[step]
            for step8 in range(4):
                note = shape[step8] if step8 < 3 else shape[2]
                score.add(start + step8 * 0.5, 0.8, instr_harp, n(note), 0.08, -0.45)

    for repeat in range(3):
        base = repeat * 4 * bar
        for step in range(4):
            score.add(base + step * bar, 3.8, instr_choir, n(bass_line[step * 2]), 0.075, -0.2)
            score.add(base + step * bar, 3.8, instr_choir, n(chord_line[step * 2][2]), 0.055, 0.25)
            score.add(base + step * bar, 3.8, instr_organ, n(bass_line[step * 2]) - 12, 0.16, 0.0)

    counter = [
        (16.0, 2.0, "A5"), (18.0, 2.0, "G5"), (20.0, 4.0, "F#5"),
        (24.0, 2.0, "G5"), (26.0, 2.0, "A5"), (28.0, 4.0, "B5"),
        (32.0, 2.0, "A5"), (34.0, 2.0, "F#5"), (36.0, 2.0, "G5"), (38.0, 2.0, "E5"),
        (40.0, 2.0, "F#5"), (42.0, 2.0, "G5"), (44.0, 4.0, "A5"),
    ]
    for beat, dur, note in counter:
        score.add(beat, dur, instr_strings, n(note), 0.15, 0.12)
    score.add(44.0, 3.0, instr_timpani, n("D2"), 0.22, 0.0)

    rendered = score.render(bars=12, tail_bars=1)
    rendered = reverb_stereo(rendered, RATE_MUSIC, room=0.90, damp=0.34, mix_amount=0.34)
    bar_s = bar * score.beat_s
    return crossfade_loop_stereo(rendered, int(bar_s * RATE_MUSIC))


def _music_dungeon(rng):
    """'Toccata of the Depths' - Bach's D-minor toccata, slowed into a loop."""
    score = Score(58.0, 4, rng)
    bar = score.beats_per_bar

    score.add(0.0, 48.0, instr_strings, n("D2"), 0.10, -0.5)
    score.add(0.0, 48.0, instr_strings, n("A2"), 0.08, 0.5)

    for bar_index in range(12):
        base = bar_index * bar
        score.add(base, 3.6, instr_organ, n("D2"), 0.30, 0.0)
        if bar_index % 2 == 1:
            score.add(base + 2.0, 1.6, instr_organ, n("A2"), 0.22, 0.0)

    run = ["A4", "G4", "A4", "F4", "E4", "D4", "E4", "C#4"]
    run_low = ["A3", "G3", "A3", "F3", "E3", "D3", "E3", "C#3"]
    for bar_index in (0, 1):
        base = bar_index * bar
        for step, note in enumerate(run + run_low):
            score.add(base + step * 0.5, 0.55, instr_organ, n(note), 0.16, -0.3)
    for bar_index in (8, 9):
        base = bar_index * bar
        for step, note in enumerate(run):
            score.add(base + step * 0.5, 0.55, instr_organ, n(note), 0.17, -0.3)

    swell_chords = [(4 * bar, ["D3", "F3", "A3"]), (5 * bar, ["G3", "Bb3", "D4"]),
                    (6 * bar, ["A3", "C#4", "E4"])]
    for start, notes in swell_chords:
        score.chord(start, 3.8, instr_strings, [n(x) for x in notes], amp=0.16, spread=0.6)
        score.chord(start, 3.8, instr_choir, [n(x) + 12 for x in notes], amp=0.05, spread=0.7)
    score.chord(7 * bar, 3.8, instr_strings, [n("Eb3"), n("Gb3"), n("Bb3")], amp=0.17, spread=0.6)

    for beat, note in ((0.0, "D4"), (7 * bar, "D4"), (11 * bar, "D4")):
        score.add(beat, 8.0, instr_bell, n(note), 0.14, 0.4)
    for hit in (0.0, 4 * bar, 7 * bar, 8 * bar, 10 * bar):
        score.add(hit, 2.0, instr_timpani, n("D2"), 0.30, 0.0)
    score.add(7 * bar + 2.0, 0.4, instr_timpani, n("D2"), 0.22, 0.0)
    score.add(7 * bar + 2.5, 0.4, instr_timpani, n("D2"), 0.26, 0.0)
    score.add(7 * bar + 3.0, 0.9, instr_timpani, n("D2"), 0.32, 0.0)

    score.chord(10 * bar, 6.0, instr_strings, [n("D3"), n("A3"), n("D4")], amp=0.17, spread=0.6)

    rendered = score.render(bars=12, tail_bars=1)
    rendered = reverb_stereo(rendered, RATE_MUSIC, room=0.92, damp=0.24, mix_amount=0.38)
    bar_s = bar * score.beat_s
    return crossfade_loop_stereo(rendered, int(bar_s * RATE_MUSIC))


def _music_combat(rng):
    """'Fate's Onslaught' - the Beethoven fifth motif as a relentless fight loop."""
    score = Score(144.0, 4, rng)
    bar = score.beats_per_bar

    def motif(base, first, second, amp=0.30):
        for offset in (0.0, 0.5, 1.0):
            score.add(base + offset, 0.42, instr_strings, n(first), amp, -0.15)
            score.add(base + offset, 0.42, instr_strings, n(first) - 12, amp * 0.75, 0.15)
        score.add(base + 1.5, 2.4, instr_strings, n(second), amp * 1.05, -0.15)
        score.add(base + 1.5, 2.4, instr_strings, n(second) - 12, amp * 0.8, 0.15)

    motif(0 * bar, "G4", "Eb4")
    motif(2 * bar, "F4", "D4")
    motif(4 * bar, "G4", "Eb4")
    motif(6 * bar, "F4", "D4", amp=0.32)

    for beat in range(16, 64):
        if beat % 4 == 3:
            continue
        note = "C2" if beat % 8 in (0, 1, 2, 3) else "G2"
        score.add(beat, 0.5, instr_strings, n(note), 0.10, 0.0)
        if beat % 2 == 0:
            score.add(beat, 0.4, instr_bass_pizz, n(note), 0.16, 0.0)

    motif(8 * bar, "G5", "Eb5", amp=0.34)
    motif(10 * bar, "F5", "D5", amp=0.34)
    motif(12 * bar, "G5", "Eb5", amp=0.36)
    motif(14 * bar, "F5", "D5", amp=0.36)

    for base, notes in ((13 * bar, ["Ab3", "C4", "Eb4"]), (14 * bar, ["Bb3", "D4", "F4"]),
                        (15 * bar, ["C4", "Eb4", "G4"])):
        score.chord(base, 3.6, instr_horn, [n(x) for x in notes], amp=0.16, spread=0.5)
    score.add(15.5 * bar, 2.0, instr_horn, n("D5"), 0.18, 0.0)
    for base in (0 * bar, 4 * bar, 8 * bar, 12 * bar, 14 * bar):
        for offset in (0.0, 0.5, 1.0):
            score.add(base + offset, 0.5, instr_timpani, n("C2"), 0.30, 0.0)
        score.add(base + 1.5, 2.0, instr_timpani, n("G1"), 0.30, 0.0)
    score.add(15 * bar + 3.0, 1.0, instr_timpani, n("G1"), 0.30, 0.0)

    rendered = score.render(bars=16, tail_bars=1)
    rendered = reverb_stereo(rendered, RATE_MUSIC, room=0.60, damp=0.40, mix_amount=0.20)
    bar_s = bar * score.beat_s
    return crossfade_loop_stereo(rendered, int(bar_s * RATE_MUSIC))


def _master_music(sig, rms_target_db=-18.5):
    """Whole-track loudness match with a peak ceiling, so crossfades sit even."""
    rms = float(np.sqrt(np.mean(sig ** 2))) + 1e-9
    sig = sig * ((10.0 ** (rms_target_db / 20.0)) / rms)
    peak = float(np.max(np.abs(sig)))
    if peak > 0.95:
        sig = sig * (0.95 / peak)
    return sig.astype(np.float64)


def music_library(rng):
    """The classical beds: menu, overworld map, castle halls, dungeon, combat."""
    out = {}

    def add(key, path, sig, gain_db, purpose):
        out[key] = dict(
            path=path, sig=_master_music(sig), rate=RATE_MUSIC, loop=True,
            bus="music", gain_db=gain_db, pitch_var=0.0, spatial=False,
            purpose=purpose, loop_mode="forward")

    add("music_menu", "music/menu_gymnopedie.wav", _music_menu(rng), -11.0,
        "menu: Gymnopedie-flavoured waltz for the front-end")
    add("music_map", "music/map_pastoral.wav", _music_map(rng), -10.0,
        "grounds: Morning Mood pastoral for the open map")
    add("music_castle", "music/castle_canon.wav", _music_castle(rng), -10.0,
        "castle interior: Pachelbel canon for the halls")
    add("music_dungeon", "music/dungeon_toccata.wav", _music_dungeon(rng), -10.5,
        "dungeon: Bach toccata mood for the deep stone")
    add("music_combat", "music/combat_fate.wav", _music_combat(rng), -8.5,
        "combat: Beethoven fifth motif battle loop")
    return out


# ------------------------------------------------------------------ Validation

def _channel_views(sig):
    if sig.ndim == 1:
        return [sig]
    return [sig[:, index] for index in range(sig.shape[1])]


def validate(library):
    problems = []
    total_bytes = 0
    for key, entry in library.items():
        sig = entry["sig"]
        is_music = str(entry.get("bus", "")) == "music"
        if len(sig) == 0:
            problems.append("%s is empty" % key)
            continue
        peak = float(np.max(np.abs(sig)))
        if peak > 1.0:
            problems.append("%s clips (peak %.3f)" % (key, peak))
        if peak < 0.01:
            problems.append("%s is silent (peak %.4f)" % (key, peak))
        if entry["loop"]:
            worst = 0.0
            seam = 0.0
            for channel in _channel_views(sig):
                steps = sorted(abs(channel[i + 1] - channel[i]) for i in range(0, len(channel) - 1, 4))
                worst = max(worst, steps[int(len(steps) * 0.999)] if steps else 0.0)
                seam = max(seam, abs(float(channel[0]) - float(channel[-1])))
            if seam > max(0.06, 1.6 * worst):
                problems.append("%s loop seam jumps (%.3f -> %.3f, worst inner step %.3f)"
                                % (key, float(np.max(sig[-1])), float(np.max(sig[0])), worst))
        seconds = len(sig) / float(entry["rate"])
        limit = 75.0 if is_music else 12.0
        if seconds > limit:
            problems.append("%s is %.1f s (limit %.0fs)" % (key, seconds, limit))
    if problems:
        for p in problems:
            print("[spell-sfx] VALIDATION FAIL: %s" % p)
        raise SystemExit("synth_spell_sfx validation failed")
    return total_bytes


def master_oneshot(sig, rms_target_db, peak_ceiling=0.97):
    """Loudness-match one sample set: RMS to target, gentle peak ceiling.

    Peak-only normalisation leaves clicks much quieter than booms; matching the
    RMS first (and only then guaranteeing headroom) is what a mix engineer
    would do, and keeps the authored `gain_db` relationships meaningful.
    """
    rms = float(np.sqrt(np.mean(sig ** 2))) + 1e-9
    sig = sig * ((10.0 ** (rms_target_db / 20.0)) / rms)
    peak = float(np.max(np.abs(sig)))
    if peak > peak_ceiling:
        sig = sig * (peak_ceiling / peak)
    return sig


def master_library(library):
    """One loudness pass over every generated sound (music handles its own)."""
    for key, entry in library.items():
        if str(entry.get("bus", "")) == "music":
            continue
        target = -20.0 if entry.get("loop", False) else -17.0
        entry["sig"] = master_oneshot(entry["sig"], target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parsed = parser.parse_args()
    out_dir = parsed.out
    os.makedirs(out_dir, exist_ok=True)

    rng = np.random.RandomState(20261005)
    library = {}
    library.update(spell_library(rng))
    library.update(world_library(rng))
    library.update(music_library(rng))
    master_library(library)

    manifest = {
        "schema": 1,
        "generator": "client/tools/audio/synth_spell_sfx.py",
        "generated": time.strftime("%Y-%m-%d"),
        "provenance": "project-original synthesis (deterministic seeded DSP, Python NumPy/SciPy); no sampled, downloaded or third-party recordings. The music beds are original synthesised arrangements of public-domain classical works (Grieg, Pachelbel, Bach, Beethoven, Satie - all d. 1925 or earlier).",
        "license": "project-original (CC0-equivalent dedication by the project); the classical compositions referenced by the music beds are public domain",
        "buses": ["Music", "SFX", "UI", "Ambience"],
        "notes": "Per-file bus, base gain, pitch variation and loop mode. Spatial entries are played on an AudioStreamPlayer3D with attenuation; UI, bed and music entries play on a non-positional player. Long loops import as IMA-ADPCM with the forward loop flag; stereo music keeps PCM (see tools/audio/tune_imports.py).",
        "sounds": {},
    }
    written = 0
    for key in sorted(library):
        entry = library[key]
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
    print("[spell-sfx] successfully synthesized %d audio assets into %s" % (written, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
