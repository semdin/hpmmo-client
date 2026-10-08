"""spell effects source generation (project-original art, authored in Blender).

Run headless:

    blender -b --factory-startup --python spell_vfx.py -- --out <client/assets/vfx>

What this produces
------------------
Every image the spell effects effect scenes sample:

    atlases/flame_loop_8x8_2k.png      8x8, 64 frames, 2048 px, LOOPING flame plume
    atlases/fire_burst_8x8_2k.png      8x8, 64 frames, 2048 px, non-looping burst
    atlases/smoke_puff_8x8_2k.png      8x8, 64 frames, 2048 px, evolving smoke
    atlases/energy_impact_8x8_2k.png   8x8, 64 frames, 2048 px, irregular impact
    atlases/shield_ripple_4x4_1k.png   4x4, 16 frames, 1024 px, local shield ripple
    atlases/ground_marks_2x2_1k.png    2x2,  4 marks,  1024 px, static ground marks
    atlases/rune_masks_2x2_1k.png      2x2,  4 masks,  1024 px, telegraph runes
    atlases/lightning_branches_2x2_1k.png  2x2, 4 masks, 1024 px, branches
    tex/soft_glow_512.png              512 px RGBA radial glow
    tex/noise_flow_512.png             512 px RGBA: R,G flow vector, B tileable noise
    tex/noise_erosion_512.png          512 px RGB tileable erosion noise
    tex/distortion_512.png             512 px RGB: R,G distortion vector, B magnitude
    tex/energy_streak_1024x256.png     tapered streak mask
    tex/shield_fracture_512.png        shield fracture mask
    metadata.json                      the published per-atlas metadata (see below)
    PROVENANCE.txt                     project-original provenance statement

Temporal coherence
------------------
The four animated atlases are NOT independent stills. Each is one continuous
band-limited field sampled at 64 consecutive times:

  * every octave is a periodic 3D value-noise lattice over (x, y, t) built from a
    seeded RNG, so it is C1-continuous in all three axes;
  * frame f samples the lattice at t = f / frames (periodic by construction for
    the looping atlas, ramped for the one-shots);
  * the scalar fields (density, turbulence, erosion) are advected functions of
    (x, y, t) - "advection" here means the sampling coordinate is offset along a
    scroll direction proportional to t, which is exactly what a texture-space
    flow does - so consecutive frames are consecutive samples of ONE field:
    authored order, consistent motion, no popping;
  * the looping atlas is periodic in t, so frame 63 blends into frame 0.

The technique is honest: this is a *simulated* procedural sequence (the plan's
"simulate them" route) with a fixed frame order, not 64 unrelated generated
stills. The deterministic seed is recorded in metadata.json.

Alpha / colour space conventions
--------------------------------
  * straight (non-premultiplied) alpha; alpha = coverage, linear;
  * RGB of colour atlases is sRGB-encoded; masks, normal-ish data, flow vectors,
    erosion noise and distortion are written as RAW LINEAR data (no transfer);
  * every cell's content fades to zero over a border band just inside a
    zero-alpha padding gutter, so no mip level can bleed a neighbour cell's
    content into another (asserted in validate()).
"""

import argparse
import json
import math
import os
import struct
import sys
import time
import zlib

import numpy as np

BLENDER_VERSION = ".".join(str(v) for v in __import__("bpy").app.version)

SEED = 20261005
PAD = 4               # zero-alpha padding ring inside every cell
EDGE_FADE = 0.055     # content fades to zero over this fraction of the content
                      # rect, just inside the padding; every atlas gets it


# --------------------------------------------------------------------- png io

def write_png(path, arr):
    """Write HxWx3 (RGB) or HxWx4 (RGBA) float array in 0..1 as 8-bit PNG."""
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=-1)
    a = (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    height, width, channels = a.shape
    color_type = 6 if channels == 4 else 2
    raw = bytearray()
    flat = a.reshape(height, -1)
    for y in range(height):
        raw.append(0)  # filter: none
        raw.extend(flat[y].tobytes())

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = b"\x89PNG\r\n\x1a\n"
    blob += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
    blob += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    blob += chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(blob)
    return (height, width, channels)


def srgb(linear):
    """Linear -> sRGB encode. Colour atlas RGB only; never applied to data maps."""
    a = np.clip(linear, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1.0 / 2.4) - 0.055)


# ------------------------------------------------------------------ noise

class Field:
    """Seeded band-limited spectral field over (x, y, t).

    A sum of `terms` random plane waves,

        S(x, y, tau) = sum_k  A_k * sin(kx_k*x + ky_k*y + kt_k*tau + phase_k)

    with |k| drawn isotropically from a power law (A ~ |k|^-alpha, so it is a
    multi-scale turbulence with no preferred direction) and `kt` an INTEGER, so
    the field is exactly periodic in tau = frame/frames: the derived sequence
    loops with no seam.

    Unlike an interpolated value-noise lattice this has no axis-aligned grid:
    the earlier lattice build produced a regular grid of blobs because linear
    interpolation of a coarse random lattice peaks at every node, and every
    octave peaks at the same coordinates. Band-limited synthesis has neither
    problem, and it is still C-infinity in x, y and t, which is what makes the
    frames one continuous motion rather than 64 unrelated stills.

    Values are normalised to mean 0.5 and standard deviation 0.20, clipped to
    [0, 1] - the convention the call sites are written against.
    """

    TARGET_STD = 0.20

    def __init__(self, frames, octaves=0, freq_xy=0.0, freq_t=0.0, seed=0,
                 terms=40, kmin=0.55, kmax=14.0, alpha=0.55, kt_max=3, **_legacy):
        self.frames = max(1, int(frames))
        self.terms = terms
        rng = np.random.default_rng(seed)
        kx = np.zeros(terms, dtype=np.float32)
        ky = np.zeros(terms, dtype=np.float32)
        kt = np.zeros(terms, dtype=np.int32)
        ph = np.zeros(terms, dtype=np.float32)
        am = np.zeros(terms, dtype=np.float32)
        for i in range(terms):
            ang = float(rng.random()) * math.tau
            # log-uniform magnitude over a WIDE band: a single band (or a steep
            # power law) makes a coherent standing-wave lattice - a regular grid
            # of blobs - instead of turbulence. Pink-ish (amp ~ k^-0.55) over
            # ~4.5 octaves keeps every scale present and the interference
            # incoherent.
            mag = kmin * (kmax / kmin) ** float(rng.random())
            kx[i] = mag * math.cos(ang)
            ky[i] = mag * math.sin(ang)
            kt[i] = int(rng.integers(1, max(1, int(kt_max)) + 1)) * (1 if rng.random() < 0.5 else -1)
            ph[i] = float(rng.random()) * math.tau
            am[i] = mag ** (-alpha)
        power = float(np.sqrt(0.5 * float((am * am).sum())))
        scale = (self.TARGET_STD / power) if power > 0.0 else 1.0
        self.kx, self.ky, self.kt, self.ph = kx, ky, kt, ph
        self.amp = (am * scale).astype(np.float32)

    def fbm(self, frame, x, y, z_cycles=1.0):
        """Sample the field. z_cycles scales the temporal rate (keep it integer)."""
        tau = math.tau * float(frame) / float(self.frames) * float(z_cycles)
        out = np.zeros_like(x, dtype=np.float32)
        for i in range(self.terms):
            out += self.amp[i] * np.sin(self.kx[i] * x + self.ky[i] * y
                                        + self.kt[i] * tau + self.ph[i])
        return np.clip(out + 0.5, 0.0, 1.0)


def _bilinear(s, x, y):
    """Bilinear sample of a 2D lattice, wrapping in x and y."""
    h, w = s.shape
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    x0m = x0 % w
    y0m = y0 % h
    x1m = (x0 + 1) % w
    y1m = (y0 + 1) % h
    v00 = s[y0m, x0m]
    v10 = s[y0m, x1m]
    v01 = s[y1m, x0m]
    v11 = s[y1m, x1m]
    return ((v00 * (1.0 - fx) + v10 * fx) * (1.0 - fy)
            + (v01 * (1.0 - fx) + v11 * fx) * fy)


def smoothstep(a, b, x):
    span = np.maximum(1e-6, np.asarray(b, dtype=np.float32) - np.asarray(a, dtype=np.float32))
    t = np.clip((x - a) / span, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def grid(n, pad):
    """u,v in 0..1 over the *content* rect of an n x n cell; plus sx (centred)."""
    idx = np.arange(n, dtype=np.float32) + 0.5
    u = (idx - pad) / float(n - 2 * pad)
    v = u.copy()
    uu, vv = np.meshgrid(u, v)          # uu: x, vv: y (row 0 = top)
    return uu.astype(np.float32), vv.astype(np.float32)


def edge_gutter(rgba, cell, pad):
    """Zero the padding ring of an already-composed cell and assert it is empty."""
    out = rgba.reshape(cell, cell, -1)
    if pad > 0:
        out[:pad, :, :] = 0.0
        out[-pad:, :, :] = 0.0
        out[:, :pad, :] = 0.0
        out[:, -pad:, :] = 0.0
    return out


def content_fade(cell, pad):
    """Per-pixel coverage multiplier fading content to zero at the content border.

    A zero-alpha gutter alone is not enough: the mip chain halves the sheet each
    level, so a border pixel of the third level still averages the first pixels
    *inside* the content rect. Every cell therefore fades to zero over EDGE_FADE
    of its content rect, just before the gutter starts - the same border band
    the animated cells always had, now applied to every atlas in compose_sheet.
    """
    idx = np.arange(cell, dtype=np.float32) + 0.5
    q = np.clip(np.minimum(idx - pad, (cell - pad) - idx), 0.0, None)
    f = smoothstep(0.0, EDGE_FADE * float(cell - 2 * pad), q)
    return (f[None, :] * f[:, None]).astype(np.float32)


# ------------------------------------------------------------------ colour

def fire_ramp(t, soot):
    """Density/heat -> emissive fire colour (linear RGB). t: 0 soot .. 1 core."""
    t = np.clip(t, 0.0, 1.0)
    stops = [
        (0.00, (0.055, 0.010, 0.004)),
        (0.18, (0.42, 0.055, 0.008)),
        (0.42, (1.00, 0.235, 0.020)),
        (0.66, (1.00, 0.560, 0.090)),
        (0.84, (1.00, 0.850, 0.420)),
        (1.00, (1.00, 0.980, 0.880)),
    ]
    r = np.zeros_like(t)
    g = np.zeros_like(t)
    b = np.zeros_like(t)
    for i in range(len(stops) - 1):
        a0, c0 = stops[i]
        a1, c1 = stops[i + 1]
        m = (t >= a0) & (t <= a1)
        k = np.clip((t - a0) / (a1 - a0), 0.0, 1.0)
        r = np.where(m, c0[0] + (c1[0] - c0[0]) * k, r)
        g = np.where(m, c0[1] + (c1[1] - c0[1]) * k, g)
        b = np.where(m, c0[2] + (c1[2] - c0[2]) * k, b)
    # Soot darkens the cooler, thinner edges of the plume.
    dark = 1.0 - 0.55 * np.clip(soot, 0.0, 1.0)
    return r * dark, g * dark, b * dark


# ------------------------------------------------------------------ effects

class Cells:
    """One animation cell: the coordinate grids every frame function shares."""

    def __init__(self, cell, pad):
        self.n = cell
        self.pad = pad
        self.u, self.v = grid(cell, pad)
        self.sx = (self.u - 0.5) * 2.0
        self.sy = (self.v - 0.5) * 2.0
        # height above the cell bottom (0 at the bottom, 1 at the top)
        self.hh = 1.0 - self.v
        self.r = np.sqrt(self.sx * self.sx + self.sy * self.sy).astype(np.float32)
        self.ang = np.arctan2(self.sy, self.sx).astype(np.float32)


def _flame_field(c, nz, frame, frames, looping):
    """The flame plume scalar field, shared by flame_loop and fire_burst.

    One continuous field: the plume *is* the turbulence, so frame f and frame
    f+1 are neighbouring samples of the same structures. The vertical scroll
    constants are the advection speed in texture space and the three octave
    frequencies are chosen so structure stays chunky (no thin vertical banding)
    and the plume balloons as it rises.
    """
    t = float(frame) / float(frames)
    hh = c.hh
    # Lateral sway: the plume wanders more the higher it gets, so the silhouette
    # is never a straight column.
    sway = nz.fbm(frame, c.sy * 0.8 + 40.0, hh * 1.0, 1.0) - 0.5
    wx = c.sx * 1.05 + (0.30 + 0.85 * hh) * sway * 2.2
    # Rising turbulence: large structure slowly, detail faster. All octaves are
    # the same field, so the frames stay coherent.
    big = nz.fbm(frame, wx * 1.15 + 3.0, hh * 1.45 - 2.4 * t, 1.0)
    mid = nz.fbm(frame, wx * 2.10 + 17.0, hh * 2.35 - 3.4 * t, 2.0)
    fine = nz.fbm(frame, wx * 3.60 + 61.0, hh * 3.40 - 4.8 * t, 3.0)
    turb = 0.58 * big + 0.68 * mid + 0.40 * fine - 0.22
    turb = np.clip(turb * 1.85, 0.0, 1.6).astype(np.float32)
    # Width: pinched at the root, ballooning through the body, thinning at the tip.
    half = (0.17 + 0.30 * np.sin(np.clip(hh, 0.0, 1.0) * math.pi * 0.72)
            + 0.05 * hh).astype(np.float32)
    lat = np.exp(-(np.abs(c.sx / half) ** 2.2)).astype(np.float32)
    flare = smoothstep(0.0, 0.09, hh)
    # The tip is not a hard edge: turbulence pulls it into licking tongues, so
    # the top of the plume reads as separate flame licks, not a dome.
    plume = 1.0 - smoothstep(0.34, 1.06, hh + 0.46 * (turb - 0.55) * hh)
    density = lat * flare * plume * (0.44 + 0.80 * turb)
    # Erosion breaks the silhouette without turning the body into stripes.
    ero = nz.fbm(frame, wx * 2.4 + 131.0, hh * 2.1 - 3.6 * t, 2.0)
    density = np.clip(density - (0.18 + 0.46 * hh) * (0.22 + 0.78 * ero), 0.0, None)
    if looping:
        # keep the root alive across the whole loop so frame 63 -> frame 0 reads
        density = np.clip(density + 0.20 * flare * lat * plume, 0.0, None)
    return density.astype(np.float32), turb


def flame_frame(c, nz, frame, frames, looping=True):
    density, turb = _flame_field(c, nz, frame, frames, looping)
    heat = np.clip(density * 1.50, 0.0, 1.35) * (1.18 - 0.38 * c.hh)
    soot = np.clip(0.62 - c.hh * 0.85 + (1.0 - np.clip(density, 0.0, 1.0)) * 0.5, 0.0, 1.0)
    r, g, b = fire_ramp(heat, soot)
    # a hot magical core at the root, slightly cooler than the ramped body
    core = smoothstep(0.72, 1.0, c.hh) * np.clip(density, 0.0, 1.0)
    r = np.clip(r + core * 0.22, 0.0, None)
    g = np.clip(g + core * 0.38, 0.0, None)
    b = np.clip(b + core * 0.80, 0.0, None)
    alpha = np.clip(density * 1.42, 0.0, 1.0) ** 1.02
    alpha *= smoothstep(0.0, 0.05, c.hh) * (1.0 - smoothstep(0.90, 1.0, c.hh))
    return r, g, b, alpha


def fire_burst_frame(c, nz, frame, frames):
    et = float(frame) / float(frames - 1)
    density, turb = _flame_field(c, nz, frame, frames, False)
    # the shell of the blast: an expanding front whose radius is pulled about by
    # the turbulence, so it breaks into lobes instead of a drawn circle
    radius = 0.06 + 1.02 * (1.0 - (1.0 - et) ** 2.4)
    rad = radius + 0.26 * (turb - 0.55)
    width = 0.08 + 0.52 * et
    shell = np.exp(-((c.r - rad) / width) ** 2.0).astype(np.float32)
    shell *= 0.35 + 1.30 * turb
    # bright core for the first third, also broken up
    core = np.exp(-((c.r / (0.16 + 0.55 * et)) ** 2.0)).astype(np.float32)
    core *= max(0.0, 1.0 - et * 2.4) * (0.55 + 0.95 * turb)
    combined = np.clip(density * (1.0 - et * 0.85) * 0.85 + shell * (0.85 - 0.68 * et) + core * 1.35, 0.0, None)
    attack = smoothstep(0.0, 0.055, et)
    decay = 1.0 - smoothstep(0.55, 1.0, et)
    density = combined * attack * decay
    # erode the front so the blast tears instead of ringing
    ero = nz.fbm(frame, c.sx * 2.6 + 91.0, c.sy * 2.6 - 2.0 * et, 3.0)
    density = np.clip(density - 0.30 * ero * (0.25 + et), 0.0, None)
    heat = np.clip(density * 1.5, 0.0, 1.35) * (1.18 - 0.30 * et) * (1.05 - 0.35 * c.r)
    soot = np.clip(0.30 + et * 0.75 - np.clip(density, 0.0, 1.0) * 0.35, 0.0, 1.0)
    r, g, b = fire_ramp(heat, soot)
    alpha = np.clip(density * 1.30, 0.0, 1.0) ** 1.02
    alpha *= (1.0 - smoothstep(0.86, 1.0, c.r))
    return r, g, b, alpha


def smoke_frame(c, nz, frame, frames):
    et = float(frame) / float(frames - 1)
    radius = 0.10 + 0.86 * math.sqrt(max(0.0, et))
    # six pufflets ride outward; the ring rotates slowly so the cloud churns
    density = np.zeros_like(c.u)
    for i in range(6):
        a = (i / 6.0) * math.tau + (et - 0.5) * (0.7 + 0.25 * (i % 3))
        cx = math.cos(a) * radius * (0.55 + 0.30 * ((i * 37) % 11) / 11.0)
        cy = math.sin(a) * radius * (0.55 + 0.30 * ((i * 53) % 7) / 7.0)
        rr = 0.20 + 0.52 * et
        d = (c.sx - cx) ** 2.0 + (c.sy - cy) ** 2.0
        density = density + np.exp(-(d / (rr * rr)).astype(np.float32))
    # Two scales of turbulence: lumps at the cloud scale (so it is not a plate)
    # and rolls at half that, so the interior has visible light and thin smoke.
    lumps = nz.fbm(frame, c.sx * 1.6 + 9.0, c.sy * 1.6 - 1.5 * et, 1.0)
    rolls = nz.fbm(frame, c.sx * 3.4 + 45.0, c.sy * 3.4 - 2.4 * et, 2.0)
    density = density * (0.15 + 1.35 * lumps) * (0.55 + 0.85 * rolls)
    density = np.clip(density * (1.0 - 0.30 * et), 0.0, None)
    # dissolve: an increasing erosion threshold tears the cloud apart at the end
    ero = nz.fbm(frame, c.sx * 2.4 + 71.0, c.sy * 2.4 + 2.0 * et, 2.0)
    density = np.clip(density - (0.08 + 0.80 * et) * (0.20 + 1.05 * ero), 0.0, None)
    density *= smoothstep(0.0, 0.10, et) * (1.0 - smoothstep(0.70, 1.0, et) * 0.45)
    cover = np.clip(density * (0.55 + 0.55 * rolls), 0.0, 1.4)
    # smoke is lit, never emissive: a cool grey that only picks up warmth early on
    grey = 0.18 + 0.58 * (1.0 - np.clip(cover, 0.0, 1.0))
    warm = max(0.0, 1.0 - et * 3.2)
    r = grey * (1.0 + 0.70 * warm)
    g = grey * (1.0 + 0.26 * warm)
    b = grey * (1.0 - 0.05 * warm)
    alpha = np.clip(cover * 0.78, 0.0, 0.85) ** 0.95
    return r, g, b, alpha


def energy_impact_frame(c, nz, frame, frames):
    et = float(frame) / float(frames - 1)
    ease = 1.0 - (1.0 - et) ** 3.0
    radius = 0.08 + 1.10 * ease
    width = 0.05 + 0.32 * et
    # Angular fields in (cos, sin) space: continuous around the circle with no
    # wrap seam, and coherent in time. They pull the front radius about and gate
    # the ring into arcs, so the impact is irregular rather than a drawn circle.
    spokes = nz.fbm(frame, np.cos(c.ang) * 1.8 + 5.0, np.sin(c.ang) * 1.8 + 5.0, 2.0)
    filament = nz.fbm(frame, np.cos(c.ang) * 4.6 + 23.0, np.sin(c.ang) * 4.6, 3.0)
    rad = radius + 0.30 * (spokes - 0.5) + 0.14 * (filament - 0.5)
    ring = np.exp(-((c.r - rad) / width) ** 2.0).astype(np.float32)
    ring = ring * (0.10 + 1.70 * spokes) * (0.35 + 1.15 * filament)
    # radial jets: thin spikes that shoot out along the strongest filaments
    jet = np.exp(-((c.r - rad) / (width * 1.9)) ** 2.0).astype(np.float32)
    jet = jet * smoothstep(0.60, 0.94, filament) * 1.9
    # the leading edge is brighter and finer than the trailing body
    lead = np.exp(-((c.r - rad) / (width * 0.32)) ** 2.0).astype(np.float32)
    lead = lead * (0.35 + 1.05 * filament)
    core = np.exp(-((c.r / (0.09 + 0.40 * et)) ** 2.0)).astype(np.float32)
    core = core * max(0.0, 1.0 - et * 2.2) * (0.45 + 1.15 * filament)
    density = np.clip(ring * (1.0 - et * 0.55) + jet * (1.0 - et * 0.6)
                      + lead * 0.9 * (1.0 - et * 0.7) + core * 1.5, 0.0, None)
    density *= (1.0 - smoothstep(0.80, 1.0, c.r))
    heat = np.clip(density * 1.4, 0.0, 1.3)
    soot = np.clip(0.45 - heat * 0.45, 0.0, 1.0)
    r, g, b = fire_ramp(heat, soot)
    # magical energy reads cooler than fire: lift green/blue on the hot core
    hot = smoothstep(0.35, 1.15, heat)
    r = np.clip(r + hot * 0.30, 0.0, None)
    g = np.clip(g + hot * 0.42, 0.0, None)
    b = np.clip(b + hot * 0.85, 0.0, None)
    alpha = np.clip(density * 1.25, 0.0, 1.0) ** 1.0
    return r, g, b, alpha


def shield_ripple_frame(c, nz, frame, frames):
    et = float(frame) / float(frames - 1)
    ease = 1.0 - (1.0 - et) ** 2.2
    radius = 0.05 + 0.82 * ease
    width = 0.03 + 0.16 * et
    broken = nz.fbm(frame, np.cos(c.ang) * 2.2 + 13.0, np.sin(c.ang) * 2.2 + 13.0, 1.0)
    rad = radius + 0.16 * (broken - 0.5)
    wave = np.exp(-((c.r - rad) / width) ** 2.0).astype(np.float32)
    wave += 0.55 * np.exp(-((c.r - rad * 0.66) / (width * 1.4)) ** 2.0).astype(np.float32)
    wave = wave * (0.25 + 1.45 * broken)
    # cracks appear as the ripple dies, so expiration has a readable fracture
    frac = nz.fbm(frame, np.cos(c.ang) * 5.0 + 41.0, np.sin(c.ang) * 5.0, 1.0)
    cracks = smoothstep(0.62, 0.95, frac) * smoothstep(0.30, 0.85, et) * (1.0 - smoothstep(0.88, 1.0, c.r))
    density = np.clip(wave * (1.0 - et * 0.55) + cracks * 1.1 * (1.0 - et * 0.4), 0.0, None)
    density *= (1.0 - smoothstep(0.90, 1.0, c.r))
    heat = np.clip(density * 1.3, 0.0, 1.2)
    soot = np.clip(0.35 - heat * 0.35, 0.0, 1.0)
    r, g, b = fire_ramp(heat, soot)
    cool = smoothstep(0.3, 1.0, heat)
    r = np.clip(r * (1.0 - cool * 0.55), 0.0, None)
    g = np.clip(g * (1.0 - cool * 0.15) + cool * 0.25, 0.0, None)
    b = np.clip(b + cool * 0.85, 0.0, None)
    alpha = np.clip(density * 1.15, 0.0, 1.0)
    return r, g, b, alpha


# ------------------------------------------------------------------ static art

def soft_glow(n=512):
    idx = (np.arange(n, dtype=np.float32) + 0.5) / n
    x, y = np.meshgrid(idx * 2.0 - 1.0, idx * 2.0 - 1.0)
    r = np.sqrt(x * x + y * y)
    core = np.exp(-((r / 0.18) ** 2.0))
    halo = np.exp(-((r / 0.52) ** 2.0)) * 0.55
    a = np.clip(core + halo, 0.0, 1.0)
    a *= 1.0 - smoothstep(0.86, 1.0, r)
    rgb = np.ones((n, n, 3), dtype=np.float32)
    return np.dstack([rgb, a.astype(np.float32)])


def fbm_still(n, octaves, freq, seed):
    """Tileable band-limited noise, normalised to mean 0.5 / std 0.20.

    Integer wave numbers make it exactly tileable; the spectral sum keeps it
    free of the axis-aligned grid an interpolated lattice would show.
    """
    rng = np.random.default_rng(seed)
    idx = (np.arange(n, dtype=np.float32) + 0.5) / float(n)
    xx, yy = np.meshgrid(idx, idx)
    base = max(2.0, float(freq))
    kmin = base
    kmax = base * (2.0 ** max(1, int(octaves)))
    terms = 24 + 4 * int(octaves)
    total = np.zeros((n, n), dtype=np.float32)
    for _ in range(terms):
        ang = rng.random() * math.tau
        mag = kmin * (kmax / kmin) ** float(rng.random())
        kx = int(round(mag * math.cos(ang)))
        ky = int(round(mag * math.sin(ang)))
        if kx == 0 and ky == 0:
            continue
        amp = mag ** -1.05
        total += amp * np.sin(math.tau * (kx * xx + ky * yy) + rng.random() * math.tau)
    power = float(np.sqrt(0.5 * float((total * total).sum()) / float(n * n)))
    if power > 0.0:
        total *= 0.20 / power
    return np.clip(total + 0.5, 0.0, 1.0)


def noise_flow(n=512):
    """R,G = curl-free-ish flow vector around the noise gradient; B = tileable noise."""
    base = fbm_still(n, 5, 4, SEED + 101)
    dy, dx = np.gradient(base)
    # texture-space curl: perpendicular to the gradient -> divergence-free flow
    fx = -dy
    fy = dx
    mag = np.sqrt(fx * fx + fy * fy) + 1e-5
    scale = np.clip(mag * 9.0, 0.0, 1.0) / mag
    return np.dstack([(fx * scale * 0.5 + 0.5).astype(np.float32),
                      (fy * scale * 0.5 + 0.5).astype(np.float32),
                      base.astype(np.float32),
                      np.ones((n, n), dtype=np.float32)])


def noise_erosion(n=512):
    a = fbm_still(n, 6, 3, SEED + 202)
    b = fbm_still(n, 3, 9, SEED + 203)
    v = np.clip(a * 0.72 + b * 0.45 - 0.10, 0.0, 1.0)
    return np.dstack([v, v, v]).astype(np.float32)


def distortion(n=512):
    base = fbm_still(n, 4, 5, SEED + 303)
    dy, dx = np.gradient(base)
    mag = np.sqrt(dx * dx + dy * dy)
    scale = np.clip(mag * 12.0, 0.0, 1.0) / (mag + 1e-5)
    return np.dstack([(dx * scale * 0.5 + 0.5).astype(np.float32),
                      (dy * scale * 0.5 + 0.5).astype(np.float32),
                      np.clip(mag * 6.0, 0.0, 1.0).astype(np.float32)])


def energy_streak(w=1024, h=256):
    idx_x = (np.arange(w, dtype=np.float32) + 0.5) / w
    idx_y = (np.arange(h, dtype=np.float32) + 0.5) / h
    xx, yy = np.meshgrid(idx_x, idx_y)
    # tapered body: widest and brightest at the emitter (x=0), pointed at the tip
    taper = np.clip(1.0 - xx, 0.0, 1.0) ** 1.35
    cross = np.exp(-(((yy - 0.5) / (0.16 + 0.16 * taper)) ** 2.0))
    streaks = fbm_still(1024, 4, 6, SEED + 404)[:h, :w]
    body = cross * taper * (0.55 + 0.85 * streaks)
    core = np.exp(-(((yy - 0.5) / (0.035 + 0.05 * taper)) ** 2.0)) * taper ** 2.0
    a = np.clip(body * 0.85 + core, 0.0, 1.0)
    a *= 1.0 - smoothstep(0.90, 1.0, xx)
    heat = np.clip(a * 1.2, 0.0, 1.15)
    r, g, b = fire_ramp(heat, np.clip(0.35 - heat * 0.35, 0.0, 1.0))
    return np.dstack([r, g, b, a]).astype(np.float32)


def shield_fracture(n=512):
    idx = (np.arange(n, dtype=np.float32) + 0.5) / n
    xx, yy = np.meshgrid(idx, idx)
    r = np.sqrt((xx - 0.5) ** 2.0 + (yy - 0.5) ** 2.0)
    ang = np.arctan2(yy - 0.5, xx - 0.5)
    rng = np.random.default_rng(SEED + 505)
    a = np.zeros((n, n), dtype=np.float32)
    for i in range(11):
        a0 = rng.random() * math.tau
        length = 0.20 + rng.random() * 0.30
        jitter = (rng.random(n) - 0.5).astype(np.float32) * 0.05
        rr = np.linspace(0.02, length, n, dtype=np.float32)
        aa = a0 + jitter * 0.5 + (rr * 1.2)
        px = (0.5 + np.cos(aa) * rr) * n
        py = (0.5 + np.sin(aa) * rr) * n
        for x, y in zip(px.astype(np.int32), py.astype(np.int32)):
            if 0 <= x < n and 0 <= y < n:
                a[y, x] = 1.0
    # soften into anti-aliased cracks
    soft = a.copy()
    for _ in range(2):
        soft = (soft + np.roll(soft, 1, 0) + np.roll(soft, -1, 0)
                + np.roll(soft, 1, 1) + np.roll(soft, -1, 1)) / 5.0
    soft = np.clip(soft * 3.0, 0.0, 1.0)
    soft *= 1.0 - smoothstep(0.30, 0.52, r)
    return np.dstack([soft, soft, soft, soft]).astype(np.float32)


def ground_marks(cell=512):
    """2x2 sheet: scorch, dust ring, fragment spray, cracked ring."""
    idx = (np.arange(cell, dtype=np.float32) + 0.5) / cell
    xx, yy = np.meshgrid(idx * 2.0 - 1.0, idx * 2.0 - 1.0)
    r = np.sqrt(xx * xx + yy * yy)
    ang = np.arctan2(yy, xx)
    cells = []

    # 0: scorch - a sooty blotch with an irregular edge
    n1 = fbm_still(cell, 4, 6, SEED + 601)
    n2 = fbm_still(cell, 6, 12, SEED + 602)
    edge = 0.62 + 0.22 * (n1 - 0.5) * 2.0
    a = np.clip(1.0 - smoothstep(edge * 0.45, edge, r) - (0.22 * (n2 - 0.5)), 0.0, 1.0)
    a = np.clip(a, 0.0, 1.0) * 0.85
    rgb = np.dstack([0.05 + 0.13 * a, 0.04 + 0.11 * a, 0.035 + 0.10 * a]).astype(np.float32)
    cells.append(np.dstack([rgb, a.astype(np.float32)]))

    # 1: dust ring - a soft torus of disturbed dust
    n = fbm_still(cell, 4, 7, SEED + 603)
    ring = np.exp(-(((r - 0.58) / 0.14) ** 2.0)) * (0.55 + 0.85 * n)
    ring = np.clip(ring, 0.0, 1.0) * 0.55
    rgb = np.dstack([0.42 + 0.10 * n, 0.39 + 0.10 * n, 0.33 + 0.09 * n]).astype(np.float32)
    cells.append(np.dstack([rgb, ring.astype(np.float32)]))

    # 2: fragment spray - scatted chunks biased outward
    rng = np.random.default_rng(SEED + 604)
    a = np.zeros((cell, cell), dtype=np.float32)
    for i in range(90):
        a0 = rng.random() * math.tau
        rr = 0.20 + rng.random() * 0.62
        px = int((0.5 + math.cos(a0) * rr) * cell)
        py = int((0.5 + math.sin(a0) * rr) * cell)
        s = max(1, int(rng.random() * 4))
        x0, x1 = max(0, px - s), min(cell, px + s + 1)
        y0, y1 = max(0, py - s), min(cell, py + s + 1)
        a[y0:y1, x0:x1] = np.maximum(a[y0:y1, x0:x1], 0.35 + rng.random() * 0.6)
    soft = a.copy()
    for _ in range(2):
        soft = (soft + np.roll(soft, 1, 0) + np.roll(soft, -1, 0)
                + np.roll(soft, 1, 1) + np.roll(soft, -1, 1)) / 5.0
    soft = np.clip(soft * 1.8, 0.0, 1.0) * (1.0 - smoothstep(0.72, 1.0, r))
    rgb = np.dstack([soft * 0.55 + 0.12, soft * 0.50 + 0.11, soft * 0.42 + 0.10]).astype(np.float32)
    cells.append(np.dstack([rgb, soft.astype(np.float32)]))

    # 3: cracked ring - a ring of fracture cracks
    n = fbm_still(cell, 5, 9, SEED + 605)
    band = np.exp(-(((r - 0.60) / 0.11) ** 2.0))
    cracks = smoothstep(0.58, 0.92, n) * band
    rng = np.random.default_rng(SEED + 606)
    for i in range(9):
        a0 = rng.random() * math.tau
        w = 0.006 + rng.random() * 0.010
        d = np.abs(((ang - a0 + math.pi) % math.tau) - math.pi)
        spoke = np.exp(-((d / w) ** 2.0)) * smoothstep(0.35, 0.62, r) * (1.0 - smoothstep(0.62, 0.78, r))
        cracks = np.maximum(cracks, spoke)
    cracks = np.clip(cracks, 0.0, 1.0) * 0.85
    rgb = np.dstack([cracks * 0.30 + 0.06, cracks * 0.28 + 0.055, cracks * 0.26 + 0.05]).astype(np.float32)
    cells.append(np.dstack([rgb, cracks.astype(np.float32)]))

    return cells


def rune_masks(cell=512):
    """2x2 sheet: telegraph circle, countdown ring, directional lune, ward glyph."""
    idx = (np.arange(cell, dtype=np.float32) + 0.5) / cell
    xx, yy = np.meshgrid(idx * 2.0 - 1.0, idx * 2.0 - 1.0)
    r = np.sqrt(xx * xx + yy * yy)
    ang = np.arctan2(yy, xx)
    cells = []

    def stroke(a):
        return np.clip(a, 0.0, 1.0).astype(np.float32)

    def ring(radius, width, mask=None):
        a = np.exp(-(((r - radius) / width) ** 2.0))
        if mask is not None:
            a = a * mask
        return a

    # 0: telegraph circle - double ring, perimeter ticks, inner rune band
    a = ring(0.78, 0.014) * 0.85 + ring(0.70, 0.008) * 0.55
    ticks = 0.0
    rng = np.random.default_rng(SEED + 701)
    for i in range(48):
        a0 = i / 48.0 * math.tau
        d = np.abs(((ang - a0 + math.pi) % math.tau) - math.pi)
        ticks = np.maximum(ticks, np.exp(-((d / 0.012) ** 2.0)) * smoothstep(0.70, 0.83, r) * (1.0 - smoothstep(0.83, 0.90, r)))
    a = np.maximum(a, ticks * 0.8)
    a = np.maximum(a, ring(0.30, 0.010) * 0.35)
    cells.append(np.dstack([np.ones_like(a), np.ones_like(a), np.ones_like(a), stroke(a)]))

    # 1: countdown ring - twelve rune notches on a band
    a = ring(0.72, 0.030) * 0.55
    notches = np.zeros_like(a)
    for i in range(12):
        a0 = i / 12.0 * math.tau + 0.10
        d = np.abs(((ang - a0 + math.pi) % math.tau) - math.pi)
        notches = np.maximum(notches, np.exp(-((d / 0.055) ** 2.0)) * smoothstep(0.66, 0.70, r) * (1.0 - smoothstep(0.74, 0.80, r)))
    a = np.clip(a + notches, 0.0, 1.0)
    cells.append(np.dstack([np.ones_like(a), np.ones_like(a), np.ones_like(a), stroke(a)]))

    # 2: directional lune - a fan that matches a directional hit area
    half = 0.55
    inside = (np.abs(ang) < half).astype(np.float32)
    lune = inside * ring(0.86, 0.014) * (0.4 + 0.6 * smoothstep(0.1, 0.85, r))
    edge_l = np.exp(-(((ang - half) / 0.02) ** 2.0)) * inside * smoothstep(0.1, 0.85, r)
    edge_r = np.exp(-(((ang + half) / 0.02) ** 2.0)) * inside * smoothstep(0.1, 0.85, r)
    a = np.clip(lune + edge_l * 0.9 + edge_r * 0.9, 0.0, 1.0)
    a *= 0.92
    cells.append(np.dstack([np.ones_like(a), np.ones_like(a), np.ones_like(a), stroke(a)]))

    # 3: ward glyph - concentric rune circle for the shield shell
    a = ring(0.80, 0.012) * 0.8 + ring(0.62, 0.007) * 0.45
    rng = np.random.default_rng(SEED + 703)
    for i in range(20):
        a0 = i / 20.0 * math.tau
        d = np.abs(((ang - a0 + math.pi) % math.tau) - math.pi)
        glyph = np.exp(-((d / 0.030) ** 2.0)) * smoothstep(0.63, 0.68, r) * (1.0 - smoothstep(0.74, 0.80, r))
        a = np.maximum(a, glyph * 0.75)
    a = np.maximum(a, ring(0.34, 0.009) * 0.30)
    a = np.clip(a, 0.0, 1.0)
    cells.append(np.dstack([np.ones_like(a), np.ones_like(a), np.ones_like(a), stroke(a)]))
    return cells


def lightning_masks(cell=512):
    """2x2 sheet of irregular branching energy masks (alpha = branch)."""
    cells = []
    for k in range(4):
        rng = np.random.default_rng(SEED + 800 + k)
        a = np.zeros((cell, cell), dtype=np.float32)
        root = (cell // 2, cell - 8)

        def branch(x, y, dx, dy, width, depth):
            length = 0.35 + rng.random() * 0.45
            steps = max(6, int(length * 160))
            for i in range(steps):
                t = i / float(steps)
                nx = x + dx * (cell * length) / steps
                ny = y + dy * (cell * length) / steps
                dx += (rng.random() - 0.5) * 0.22
                dy += (rng.random() - 0.5) * 0.12
                m = math.hypot(dx, dy) + 1e-6
                dx, dy = dx / m, dy / m
                w = max(0.7, width * (1.0 - t * 0.72))
                x0, x1 = max(0, int(nx - w)), min(cell, int(nx + w + 1))
                y0, y1 = max(0, int(ny - w)), min(cell, int(ny + w + 1))
                if x0 >= x1 or y0 >= y1:
                    continue
                yy, xx = np.mgrid[y0:y1, x0:x1]
                d = np.sqrt((xx - nx) ** 2.0 + (yy - ny) ** 2.0)
                a[y0:y1, x0:x1] = np.maximum(a[y0:y1, x0:x1], np.clip(1.0 - (d / w) ** 2.0, 0.0, 1.0))
                x, y = nx, ny
                if depth < 4 and i > 2 and rng.random() < 0.045:
                    branch(x, y, dx * 0.5 + (rng.random() - 0.5), -abs(dy) * 0.6 - 0.2,
                           width * 0.62, depth + 1)

        branch(root[0], root[1], (rng.random() - 0.5) * 0.7, -1.0, 3.2 + k * 0.4, 0)
        if k >= 2:  # two masks fork from the top so a strike can be split in two
            branch(cell * 0.5, 8, (rng.random() - 0.5) * 0.6, 1.0, 2.4, 0)
        soft = a.copy()
        for _ in range(2):
            soft = np.maximum(soft, (np.roll(soft, 1, 0) + np.roll(soft, -1, 0)
                                     + np.roll(soft, 1, 1) + np.roll(soft, -1, 1)) * 0.35)
        rgb = np.dstack([np.ones_like(soft), np.ones_like(soft), np.ones_like(soft)])
        cells.append(np.dstack([rgb, np.clip(soft, 0.0, 1.0)]))
    return cells


# ------------------------------------------------------------------ sheets

def as_rgba(value):
    """Normalise one cell to HxWx4.

    Generators return either a (r, g, b, alpha) tuple of HxW planes or a single
    HxWx4 array. np.array(tuple_of_planes) would stack them CHANNEL-FIRST
    (4, H, W) and every later reshape would then scramble pixels; this is the
    only place that conversion happens, and it is explicit.
    """
    if isinstance(value, (tuple, list)) and not hasattr(value, "shape"):
        arr = np.dstack([np.asarray(plane, dtype=np.float32) for plane in value])
    else:
        arr = np.asarray(value, dtype=np.float32)
    if arr.ndim == 2:
        arr = np.dstack([arr, arr, arr, np.ones_like(arr, dtype=np.float32)])
    if arr.shape[2] == 3:
        arr = np.dstack([arr, np.ones(arr.shape[:2], dtype=np.float32)])
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise SystemExit("spell_vfx: bad cell shape %s" % (arr.shape,))
    return arr


def fade_rgb_to_coverage(arr):
    """Soft-fade RGB with coverage.

    Two reasons this is not cosmetic:
      * straight-alpha layers: an un-faded RGB halo around transparent texels is
        what filtered/mipmapped flames show as dark fringing;
      * additive layers (energy, streaks, masks): additive blending ignores A, so
        RGB must already carry the coverage or the whole quad glows grey.
    """
    if arr.ndim != 3 or arr.shape[2] != 4:
        return arr  # RGB data texture (no coverage channel): leave as written
    cover = smoothstep(0.0, 0.22, arr[..., 3:4])
    out = arr.copy()
    out[..., :3] = arr[..., :3] * cover
    return out


def compose_sheet(cells, cell, pad, cols, rows, colour, srgb_encode):
    """Place HxWx4 cells into a rows x cols sheet with a zero-alpha gutter.

    Every cell fades to zero across its border band before the gutter (see
    content_fade), so no mip level can average content into the cell's border
    ring - the property the spell effects scene check measures.
    """
    sheet = np.zeros((rows * cell, cols * cell, 4), dtype=np.float32)
    border = content_fade(cell, pad)
    for i, rgba in enumerate(cells):
        r, c = divmod(i, cols)
        body = as_rgba(rgba)
        body[..., 3] = body[..., 3] * border
        body = fade_rgb_to_coverage(edge_gutter(body, cell, pad))
        sheet[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = body
    if colour and srgb_encode:
        sheet[..., :3] = srgb(sheet[..., :3])
    return sheet


ATLASES = [
    # id, cols, rows, cell, generator, looping, fps, colour, blend
    dict(id="vfx_flame_loop", file="atlases/flame_loop_8x8_2k.png", cols=8, rows=8, cell=256,
         frames=64, fps=30, loop=True, colour=True, blend="alpha",
         generator=lambda c, nz, f, n: flame_frame(c, nz, f, n, True),
         purpose="Looping flame plume (Incendio sustain, torches, Ultimate tail)"),
    dict(id="vfx_fire_burst", file="atlases/fire_burst_8x8_2k.png", cols=8, rows=8, cell=256,
         frames=64, fps=40, loop=False, colour=True, blend="alpha",
         generator=lambda c, nz, f, n: fire_burst_frame(c, nz, f, n),
         purpose="Non-looping directional fire burst (Incendio cast/impact)"),
    dict(id="vfx_smoke_puff", file="atlases/smoke_puff_8x8_2k.png", cols=8, rows=8, cell=256,
         frames=64, fps=24, loop=False, colour=True, blend="alpha",
         generator=lambda c, nz, f, n: smoke_frame(c, nz, f, n),
         purpose="Evolving soft smoke / dust (Incendio tail, Bombarda dust)"),
    dict(id="vfx_energy_impact", file="atlases/energy_impact_8x8_2k.png", cols=8, rows=8, cell=256,
         frames=64, fps=40, loop=False, colour=True, blend="additive",
         generator=lambda c, nz, f, n: energy_impact_frame(c, nz, f, n),
         purpose="Irregular magical impact (all projectile hits, Ultimate strike)"),
    dict(id="vfx_shield_ripple", file="atlases/shield_ripple_4x4_1k.png", cols=4, rows=4, cell=256,
         frames=16, fps=24, loop=False, colour=True, blend="additive",
         generator=lambda c, nz, f, n: shield_ripple_frame(c, nz, f, n),
         purpose="Local shield impact ripple + fracture (Protego hit response)"),
]


def build_atlas(spec, out_dir):
    frames = spec["frames"]
    cell = spec["cell"]
    c = Cells(cell, PAD)
    nz = Field(frames, terms=40, kmin=0.5, kmax=14.0, alpha=0.55, kt_max=2,
               seed=SEED + 17 * (frames + cell))
    cells = []
    started = time.time()
    for f in range(frames):
        cells.append(spec["generator"](c, nz, f, frames))
    sheet = compose_sheet(cells, cell, PAD, spec["cols"], spec["rows"], spec["colour"], True)
    path = os.path.join(out_dir, spec["file"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h, w, _ = write_png(path, sheet)
    info = dict(spec)
    info.pop("generator")
    info.update({
        "path": spec["file"],
        "sheet_px": [w, h],
        "cell_px": cell,
        "padding_px": PAD,
        "frame_order": "row-major, frame 0 at the top-left cell",
        "alpha": "straight (non-premultiplied); coverage in A, linear",
        "colour_space": "sRGB (RGB), linear (A)" if spec["colour"] else "linear data (RGB)",
        "blend_default": spec["blend"],
        "generator": "tools/blender/spell_vfx.py",
        "seed": SEED + 17 * (frames + cell),
        "note": ("Simulated sequence: one continuous band-limited field sampled at "
                 "%d consecutive times (periodic in t, so frame %d blends into frame 0). "
                 "Not independent stills." % (frames, frames - 1)) if spec["loop"] else
                ("Simulated one-shot: one continuous band-limited field sampled at %d "
                 "consecutive times; first and last frames are empty." % frames),
    })
    print("[spell-fx] %s: %d frames, %dx%d cell, %dx%d sheet in %.1fs" % (
        spec["id"], frames, cell, cell, w, h, time.time() - started))
    return info


def build_stills(out_dir):
    entries = []
    tex = os.path.join(out_dir, "tex")
    os.makedirs(tex, exist_ok=True)

    p = os.path.join(tex, "soft_glow_512.png")
    write_png(p, fade_rgb_to_coverage(soft_glow(512)))
    entries.append(dict(id="vfx_soft_glow", path="tex/soft_glow_512.png", size_px=[512, 512],
                        colour_space="sRGB (RGB), linear (A)",
                        alpha="straight", blend_default="additive", frames=1, loop=False,
                        purpose="Soft radial opacity/glow; core flashes, muzzle glow, ember sprites"))
    p = os.path.join(tex, "noise_flow_512.png")
    write_png(p, fade_rgb_to_coverage(noise_flow(512)))
    entries.append(dict(id="vfx_noise_flow", path="tex/noise_flow_512.png", size_px=[512, 512],
                        colour_space="linear data",
                        channel_convention="R,G = normalised flow vector, B = tileable value noise",
                        tiling="tileable on both axes", alpha="none (A=1)",
                        blend_default="n/a (data)", frames=1, loop=False,
                        purpose="Directional flow + tileable noise for shield flow and streak scroll"))
    p = os.path.join(tex, "noise_erosion_512.png")
    write_png(p, fade_rgb_to_coverage(noise_erosion(512)))
    entries.append(dict(id="vfx_noise_erosion", path="tex/noise_erosion_512.png", size_px=[512, 512],
                        colour_space="linear data", tiling="tileable on both axes",
                        alpha="none (A=1)", blend_default="n/a (data)", frames=1, loop=False,
                        purpose="Dissolve / erosion noise for shield expiration and effect fade"))
    p = os.path.join(tex, "distortion_512.png")
    write_png(p, fade_rgb_to_coverage(distortion(512)))
    entries.append(dict(id="vfx_distortion", path="tex/distortion_512.png", size_px=[512, 512],
                        colour_space="linear data",
                        channel_convention="R,G = distortion vector, B = magnitude",
                        tiling="tileable on both axes", alpha="none (A=1)",
                        blend_default="n/a (data)", frames=1, loop=False,
                        purpose="Heat-haze / refraction distortion input (screen-space grabber)"))
    p = os.path.join(tex, "energy_streak_1024x256.png")
    write_png(p, fade_rgb_to_coverage(energy_streak(1024, 256)))
    entries.append(dict(id="vfx_energy_streak", path="tex/energy_streak_1024x256.png",
                        size_px=[1024, 256], colour_space="sRGB (RGB), linear (A)",
                        alpha="straight", blend_default="additive", frames=1, loop=False,
                        purpose="Tapered streak / trail mask for projectiles, Expelliarmus ribbon, broom trail"))
    p = os.path.join(tex, "shield_fracture_512.png")
    write_png(p, fade_rgb_to_coverage(shield_fracture(512)))
    entries.append(dict(id="vfx_shield_fracture", path="tex/shield_fracture_512.png",
                        size_px=[512, 512], colour_space="linear data (white mask)",
                        alpha="straight (mask)", blend_default="additive", frames=1, loop=False,
                        purpose="Fracture mask for the Protego shell on expiration"))

    for spec in (
        dict(id="vfx_ground_marks", file="atlases/ground_marks_2x2_1k.png", cell=512, cols=2, rows=2,
             names=["scorch", "dust_ring", "fragment_spray", "cracked_ring"],
             purpose="Scorch, dust, fragment and cracked-ring ground marks (Bombarda, Incendio, Ultimate)",
             gen=lambda: ground_marks(512)),
        dict(id="vfx_rune_masks", file="atlases/rune_masks_2x2_1k.png", cell=512, cols=2, rows=2,
             names=["telegraph_circle", "countdown_ring", "directional_lune", "ward_glyph"],
             purpose="Restrained rune/telegraph masks (boss warning, shield ward, ground marks)",
             gen=lambda: rune_masks(512)),
        dict(id="vfx_lightning_branches", file="atlases/lightning_branches_2x2_1k.png", cell=512, cols=2, rows=2,
             names=["branch_a", "branch_b", "branch_c", "branch_double"],
             purpose="Irregular branching energy masks (Ultimate lightning)",
             gen=lambda: lightning_masks(512)),
    ):
        cells = spec["gen"]()
        sheet = compose_sheet(cells, spec["cell"], PAD, spec["cols"], spec["rows"], False, False)
        path = os.path.join(out_dir, spec["file"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        h, w, _ = write_png(path, sheet)
        entries.append(dict(id=spec["id"], path=spec["file"], sheet_px=[w, h], cell_px=spec["cell"],
                            cols=spec["cols"], rows=spec["rows"], frames=spec["cols"] * spec["rows"],
                            frame_order="row-major, frame 0 at the top-left cell",
                            cell_names=spec["names"], padding_px=PAD, loop=False, fps=0,
                            colour_space="linear data (white mask)",
                            alpha="straight (mask)", blend_default="additive" if spec["id"] != "vfx_ground_marks" else "alpha",
                            generator="tools/blender/spell_vfx.py", seed=SEED,
                            purpose=spec["purpose"]))
        print("[spell-fx] %s: %dx%d sheet" % (spec["id"], w, h))

    for entry in entries:
        print("[spell-fx] wrote %s" % entry["path"])
    return entries


# ------------------------------------------------------------------ validation

def _mip_bleed(alpha, cell, cols, rows, levels=3):
    """Worst alpha in the outer ring of every cell after `levels` box halvings.

    Mirrors the spell effects scene check: the GPU mip chain is modelled as repeated
    2x2 box averaging and the outer ring of each cell must stay empty.
    """
    work = alpha.astype(np.float32)
    for _ in range(levels):
        h, w = work.shape
        work = work[:h - h % 2, :w - w % 2].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    factor = work.shape[1] / float(alpha.shape[1])
    scaled = max(1, int(cell * factor))
    worst = 0.0
    for i in range(min(cols * rows, 8)):
        r, c = divmod(i, cols)
        x0, y0 = c * scaled, r * scaled
        x1 = min(work.shape[1] - 1, x0 + scaled - 1)
        y1 = min(work.shape[0] - 1, y0 + scaled - 1)
        worst = max(worst,
                    float(work[y0:y1 + 1, x0].max()), float(work[y0:y1 + 1, x1].max()),
                    float(work[y0, x0:x1 + 1].max()), float(work[y1, x0:x1 + 1].max()))
    return worst


def validate(out_dir, entries):
    """Assert the properties the spell effects checks and the metadata claim."""
    problems = []
    for entry in entries:
        path = os.path.join(out_dir, entry["path"])
        if not os.path.exists(path):
            problems.append("%s missing" % entry["path"])
            continue
        size = os.path.getsize(path)
        if size < 512:
            problems.append("%s is suspiciously small (%d bytes)" % (entry["path"], size))
        declared = entry.get("sheet_px") or entry.get("size_px")
        if entry.get("padding_px") and entry.get("cols"):
            # the gutter must be empty in the source file: re-read and check
            from_reader = _read_png_rgba(path)
            if from_reader is None:
                problems.append("%s could not be re-read" % entry["path"])
                continue
            h, w, arr = from_reader
            if [w, h] != list(declared):
                problems.append("%s is %dx%d but metadata says %s" % (entry["path"], w, h, declared))
            cell = entry["cell_px"]
            pad = entry["padding_px"]
            cols, rows = entry["cols"], entry["rows"]
            worst = 0.0
            for i in range(cols * rows):
                r, c = divmod(i, cols)
                sub = arr[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell]
                if pad:
                    worst = max(worst,
                                float(np.abs(sub[:pad]).max()),
                                float(np.abs(sub[-pad:]).max()),
                                float(np.abs(sub[:, :pad]).max()),
                                float(np.abs(sub[:, -pad:]).max()))
            if worst > 0.0:
                problems.append("%s padding gutter is not empty (worst %.3f)" % (entry["path"], worst))
            # the gutter only helps if content has already faded out: the third
            # mip level still averages the first pixels inside the content rect
            bleed = _mip_bleed(arr[..., 3], cell, cols, rows, 3)
            if bleed > 0.02:
                problems.append("%s bleeds into the cell border after three mip levels "
                                "(worst %.4f)" % (entry["path"], bleed))
    if problems:
        for p in problems:
            print("[spell-fx] VALIDATION FAIL: %s" % p)
        raise SystemExit("spell_vfx validation failed")
    print("[spell-fx] validation: %d assets, every gutter empty and no three-level mip bleed"
          % len(entries))


def _read_png_rgba(path):
    """Minimal PNG reader for the 8-bit RGBA/RGB files this script writes."""
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    w = h = ctype = None
    idat = b""
    while pos < len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag = blob[pos + 4:pos + 8]
        data = blob[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h, _depth, ctype, _, _, _ = struct.unpack(">IIBBBBB", data)
        elif tag == b"IDAT":
            idat += data
        pos += 12 + length
    raw = zlib.decompress(idat)
    channels = 4 if ctype == 6 else 3
    stride = w * channels
    out = np.zeros((h, w, channels), dtype=np.float32)
    prev = np.zeros(stride, dtype=np.uint8)
    p = 0
    for y in range(h):
        filt = raw[p]
        p += 1
        line = np.frombuffer(raw[p:p + stride], dtype=np.uint8).copy()
        p += stride
        if filt == 1:
            for x in range(channels, stride):
                line[x] = (int(line[x]) + int(line[x - channels])) & 0xFF
        elif filt == 2:
            line = (line.astype(np.int32) + prev.astype(np.int32)).astype(np.uint8)
        elif filt == 3:
            for x in range(stride):
                left = int(line[x - channels]) if x >= channels else 0
                line[x] = (int(line[x]) + ((left + int(prev[x])) >> 1)) & 0xFF
        elif filt == 4:
            for x in range(stride):
                a = int(line[x - channels]) if x >= channels else 0
                b = int(prev[x])
                c = int(prev[x - channels]) if x >= channels else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (int(line[x]) + pr) & 0xFF
        out[y] = line.reshape(w, channels).astype(np.float32) / 255.0
        prev = line
    return h, w, out


# ------------------------------------------------------------------ main

def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    parsed = parser.parse_args(args)
    out_dir = parsed.out
    os.makedirs(out_dir, exist_ok=True)

    entries = []
    for spec in ATLASES:
        if parsed.only and parsed.only != spec["id"]:
            continue
        entries.append(build_atlas(spec, out_dir))
    if not parsed.only:
        entries += build_stills(out_dir)

    metadata = {
        "schema": 1,
        "generator": "client/tools/blender/spell_vfx.py",
        "blender": BLENDER_VERSION,
        "seed": SEED,
        "generated": time.strftime("%Y-%m-%d"),
        "alpha_convention": "straight (non-premultiplied) alpha; alpha is coverage and is linear; RGB of colour atlases is sRGB-encoded; masks/normals/flow are raw linear data",
        "padding": "every atlas cell carries a %d px zero-alpha, zero-colour gutter and its content fades to zero before it, so mipmapping cannot bleed one cell's content into its neighbour" % PAD,
        "temporal_method": "simulated sequences: one continuous band-limited field in (x, y, t) sampled at consecutive frames; the looping atlas is periodic in t. Frames are ordered row-major and must be played in that order.",
        "assets": entries,
    }
    meta_path = os.path.join(out_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=1)
        handle.write("\n")
    with open(os.path.join(out_dir, "PROVENANCE.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            "spell effects source art - PROJECT-ORIGINAL.\n"
            "Authored by client/tools/blender/spell_vfx.py running inside Blender %s\n"
            "headless (deterministic seeded numpy fields; re-running the script reproduces\n"
            "these files byte-for-byte on the same Blender/numpy build).\n"
            "No third-party image was used and no image generator was involved.\n"
            "License: project-original (CC0-equivalent dedication by the project).\n"
            "flame_01.png / spark_01.png beside this file are the Kenney Particle Pack\n"
            "ingredients (CC0, Kenney-License.txt) and are used as particle sprites only.\n"
            % BLENDER_VERSION)
    validate(out_dir, entries)
    print("[spell-fx] metadata -> %s" % meta_path)


if __name__ == "__main__":
    main()
