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
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
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
    # Footsteps: Physical materials (stone, dirt, grass, wood, water)
    # ----------------------------------------------------------------
    surfaces = {
        "stone": {"heel_f": 3200.0, "res_f": 1150.0, "thud_w": 0.35, "crisp_w": 0.85, "len": 0.21},
        "dirt":  {"heel_f": 1800.0, "res_f": 450.0,  "thud_w": 0.65, "crisp_w": 0.55, "len": 0.23},
        "grass": {"heel_f": 2600.0, "res_f": 650.0,  "thud_w": 0.25, "crisp_w": 0.75, "len": 0.24},
        "wood":  {"heel_f": 2200.0, "res_f": 380.0,  "thud_w": 0.75, "crisp_w": 0.70, "len": 0.23},
        "water": {"heel_f": 1900.0, "res_f": 850.0,  "thud_w": 0.45, "crisp_w": 1.10, "len": 0.28},
    }
    for surface, cfg in surfaces.items():
        for variant in range(3):
            n = int(RATE_SFX * cfg["len"])
            t = np.arange(n) / RATE_SFX
            # Heel strike transient
            h_len = int(RATE_SFX * 0.04)
            heel = np.zeros(n)
            heel_noise = butter_bandpass(rng.normal(0, 1, h_len), cfg["heel_f"] * 0.8, cfg["heel_f"] * 1.5, RATE_SFX)
            heel[:h_len] = heel_noise * np.exp(-np.linspace(0, 1, h_len) / 0.015) * cfg["crisp_w"]
            # Material resonance
            res_noise = butter_bandpass(rng.normal(0, 1, n), cfg["res_f"] * 0.7, cfg["res_f"] * 1.4, RATE_SFX)
            res = res_noise * np.exp(-t / 0.045) * 0.7
            # Foot mass thud
            thud = np.sin(2.0 * np.pi * 95.0 * t) * np.exp(-t / 0.035) * cfg["thud_w"]
            sig = soft_clip(heel + res + thud, drive=1.1)
            add("step_%s_%d" % (surface, variant + 1), "footsteps/%s_%02d.wav" % (surface, variant + 1),
                normalize(sig, 0.78), gain_db=-9.0, pitch_var=0.08,
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
    # UI Sounds (Tactile, modern, clear, gratifying)
    # ----------------------------------------------------------------
    def ui_snd(key, freq, seconds, decay, partials=((1.0, 1.0), (2.0, 0.35), (3.01, 0.15))):
        sig = ping(RATE_SFX, freq, seconds, decay, partials)
        add("ui_" + key, "ui/%s.wav" % key, normalize(sig, 0.75), bus="ui", gain_db=-9.0,
            spatial=False, purpose="UI %s" % key)

    ui_snd("button", 650, 0.09, 0.05)
    ui_snd("hover", 920, 0.06, 0.035, ((1.0, 1.0), (2.0, 0.2)))
    ui_snd("confirm", 700, 0.22, 0.09, ((1.0, 1.0), (1.5, 0.5), (2.0, 0.3)))
    ui_snd("cancel", 400, 0.2, 0.08, ((1.0, 1.0), (0.75, 0.6)))
    ui_snd("deny", 250, 0.3, 0.12, ((1.0, 1.0), (1.41, 0.5)))
    ui_snd("chat", 1250, 0.07, 0.03)
    ui_snd("quest", 540, 0.45, 0.18, ((1.0, 1.0), (1.5, 0.6), (2.0, 0.3)))
    ui_snd("levelup", 440, 0.75, 0.3, ((1.0, 1.0), (1.5, 0.7), (2.0, 0.5), (3.0, 0.25)))
    ui_snd("loot", 1050, 0.22, 0.07, ((1.0, 1.0), (2.02, 0.35)))
    ui_snd("upgrade_success", 550, 0.55, 0.2, ((1.0, 1.0), (1.5, 0.7), (2.0, 0.4), (2.5, 0.2)))
    ui_snd("upgrade_fail", 360, 0.5, 0.18, ((1.0, 1.0), (1.32, 0.6), (0.66, 0.4)))
    ui_snd("open", 720, 0.14, 0.06, ((1.0, 1.0), (1.48, 0.3)))
    ui_snd("close", 480, 0.14, 0.06, ((1.0, 1.0), (0.7, 0.3)))

    # ui_hit (Combat hit feedback: punchy, tactile hit indicator!)
    n = int(RATE_SFX * 0.18)
    t = np.arange(n) / RATE_SFX
    hit_click = butter_bandpass(rng.normal(0, 1, n), 2200, 6800, RATE_SFX) * exp_decay(n, 0.025) * 1.2
    hit_punch = np.sin(2.0 * np.pi * np.cumsum(180 * np.exp(-t / 0.03) + 70) / RATE_SFX) * exp_decay(n, 0.04) * 0.9
    add("ui_hit", "ui/hit.wav", normalize(soft_clip(hit_click + hit_punch, drive=1.2), 0.85),
        bus="ui", gain_db=-8.0, spatial=False, pitch_var=0.07, purpose="combat damage hit marker tick")

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

    return out


# ------------------------------------------------------------------ Validation

def validate(library):
    problems = []
    total_bytes = 0
    for key, entry in library.items():
        sig = entry["sig"]
        if len(sig) == 0:
            problems.append("%s is empty" % key)
            continue
        peak = float(np.max(np.abs(sig)))
        if peak > 1.0:
            problems.append("%s clips (peak %.3f)" % (key, peak))
        if peak < 0.01:
            problems.append("%s is silent (peak %.4f)" % (key, peak))
        if entry["loop"]:
            steps = sorted(abs(sig[i + 1] - sig[i]) for i in range(0, len(sig) - 1, 4))
            worst = steps[int(len(steps) * 0.999)] if steps else 0.0
            seam = abs(sig[0] - sig[-1])
            if seam > max(0.06, 1.6 * worst):
                problems.append("%s loop seam jumps (%.3f -> %.3f, worst inner step %.3f)"
                                % (key, sig[-1], sig[0], worst))
        seconds = len(sig) / float(entry["rate"])
        if seconds > 12.0:
            problems.append("%s is %.1f s (loops should stay short <= 12s)" % (key, seconds))
    if problems:
        for p in problems:
            print("[spell-sfx] VALIDATION FAIL: %s" % p)
        raise SystemExit("synth_spell_sfx validation failed")
    return total_bytes


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

    manifest = {
        "schema": 1,
        "generator": "client/tools/audio/synth_spell_sfx.py",
        "generated": time.strftime("%Y-%m-%d"),
        "provenance": "project-original synthesis (deterministic seeded DSP, Python NumPy/SciPy); no downloaded or third-party audio",
        "license": "project-original (CC0-equivalent dedication by the project)",
        "buses": ["Music", "SFX", "UI", "Ambience"],
        "notes": "Per-file bus, base gain, pitch variation and loop mode. Spatial entries are played on an AudioStreamPlayer3D with attenuation; UI and bed entries play on a non-positional player. Long loops import as IMA-ADPCM with the forward loop flag (see tools/audio/tune_imports.py).",
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
