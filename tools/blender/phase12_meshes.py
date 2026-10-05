"""Phase 12 spell VFX meshes (project-original, authored in Blender).

Run headless:

    blender -b --factory-startup --python phase12_meshes.py -- --out <client/assets/vfx/meshes>

Outputs (GLB, +Y up, metres, one material-free mesh per file so the game assigns
its own shader):

    trail_ribbon.glb     camera-aware tapered strip: UV.x runs 0 (emitter) -> 1
                         (tip), UV.y 0..1 across; the authored taper profile is
                         also written into vertex colour alpha and into
                         meshes_metadata.json, so the game can rebuild the strip
                         along a motion history and keep the authored UV layout
    shield_shell.glb     smooth low-cost shell for Protego (the one spell where
                         a solid surface is correct), 1 m radius, UV sphere
    projectile_core.glb  subtle carrier core for projectiles (elongated faceted
                         teardrop) replacing the placeholder sphere
    shards.glb           four irregular debris shards (Shard_A..Shard_D), flat
                         facets, for Bombarda debris

Everything here is authored geometry - no imported mesh, no third-party model.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

BLENDER_VERSION = ".".join(str(v) for v in bpy.app.version)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_mesh(name, verts, faces, uvs):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vi = mesh.loops[loop_index].vertex_index
            uv.data[loop_index].uv = uvs(vi, loop_index % len(poly.loop_indices))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    mesh.validate()
    return obj


def export(objs, path, selection=True):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    kwargs = dict(filepath=path, export_format="GLB", export_yup=True,
                  export_apply=True, use_selection=selection, export_animations=False)
    try:
        bpy.ops.export_scene.gltf(**kwargs)
    except TypeError:
        kwargs.pop("export_animations", None)
        bpy.ops.export_scene.gltf(**kwargs)
    return os.path.getsize(path)


# ------------------------------------------------------------------ ribbon

RIBBON_SEGMENTS = 24
RIBBON_LENGTH = 1.0


def taper(t):
    """Authored taper: full width at the emitter, a point at the tip.

    Kept as a plain function so the game and the validation block read the same
    profile that the vertices were built from.
    """
    return max(0.02, (1.0 - t) ** 1.35)


def build_trail_ribbon():
    verts, faces = [], []
    half_width = 0.5
    sag = 0.06
    for i in range(RIBBON_SEGMENTS + 1):
        t = i / float(RIBBON_SEGMENTS)
        z = t * RIBBON_LENGTH
        w = taper(t) * half_width
        y = -sag * math.sin(t * math.pi)  # authored sag so the strip is not flat
        verts.append((-w, y, z))
        verts.append((w, y, z))
    for i in range(RIBBON_SEGMENTS):
        a = i * 2
        faces.append((a, a + 1, a + 3, a + 2))

    def uv(vi, _k):
        i, side = divmod(vi, 2)
        return (i / float(RIBBON_SEGMENTS), float(side))

    obj = make_mesh("TrailRibbon", verts, faces, uv)
    colour = obj.data.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(obj.data.vertices):
        t = (i // 2) / float(RIBBON_SEGMENTS)
        colour.data[i].color = (1.0, 1.0, 1.0, taper(t))
    return obj


# ------------------------------------------------------------------ shield

def build_shield_shell(radius=1.0, segments=28, rings=18):
    verts, faces = [], []
    verts.append((0.0, radius, 0.0))
    for r in range(1, rings):
        phi = math.pi * r / rings
        y = radius * math.cos(phi)
        rr = radius * math.sin(phi)
        for s in range(segments):
            theta = math.tau * s / segments
            verts.append((rr * math.cos(theta), y, rr * math.sin(theta)))
    verts.append((0.0, -radius, 0.0))
    top = 0
    bottom = len(verts) - 1
    for s in range(segments):
        faces.append((top, 1 + (s + 1) % segments, 1 + s))
    for r in range(rings - 2):
        row = 1 + r * segments
        nxt = row + segments
        for s in range(segments):
            a = row + s
            b = row + (s + 1) % segments
            c = nxt + (s + 1) % segments
            d = nxt + s
            faces.append((a, b, c, d))
    row = 1 + (rings - 2) * segments
    for s in range(segments):
        faces.append((bottom, row + s, row + (s + 1) % segments))

    def uv(vi, _k):
        if vi == top or vi == bottom:
            return (0.5, 0.0 if vi == top else 1.0)
        idx = vi - 1
        r = idx // segments
        s = idx % segments
        return (s / float(segments), (r + 1) / float(rings))

    return make_mesh("ShieldShell", verts, faces, uv)


# ------------------------------------------------------------------ core

def build_projectile_core(radius=0.5, length=1.6):
    """Faceted teardrop aimed down +Z: the carrier the energy rides on."""
    ring_n = 8
    verts = [(0.0, 0.0, -length * 0.34)]
    profile = [(0.30, 0.0), (0.50, 0.20), (0.36, 0.55), (0.14, 0.80)]
    for r, z in profile:
        for i in range(ring_n):
            a = math.tau * i / ring_n
            verts.append((r * radius * math.cos(a), r * radius * math.sin(a), z * length))
    verts.append((0.0, 0.0, length * 1.05))
    faces = []
    for i in range(ring_n):
        faces.append((0, 1 + (i + 1) % ring_n, 1 + i))
    for band in range(len(profile) - 1):
        row = 1 + band * ring_n
        nxt = row + ring_n
        for i in range(ring_n):
            a = row + i
            b = row + (i + 1) % ring_n
            c = nxt + (i + 1) % ring_n
            d = nxt + i
            faces.append((a, b, c, d))
    tip = len(verts) - 1
    row = 1 + (len(profile) - 1) * ring_n
    for i in range(ring_n):
        faces.append((tip, row + i, row + (i + 1) % ring_n))

    def uv(vi, _k):
        return (0.5 + 0.5 * ((vi * 0.37) % 1.0), min(1.0, 0.02 * vi))

    return make_mesh("ProjectileCore", verts, faces, uv)


# ------------------------------------------------------------------ shards

def build_shards(seed=20261005):
    import random
    rng = random.Random(seed)
    objs = []
    for k in range(4):
        # irregular convex chip: a stretched, jittered octahedron
        base = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        verts = []
        for vx, vy, vz in base:
            j = lambda s: 1.0 + (rng.random() - 0.5) * 0.75 * s
            verts.append((vx * j(1.2) * 0.06, vy * j(1.0) * 0.05, vz * j(1.4) * 0.10))
        faces = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
                 (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]

        def uv(vi, _k, _verts=verts):
            v = _verts[vi]
            return (0.5 + v[0] * 4.0, 0.5 + v[1] * 4.0)

        objs.append(make_mesh("Shard_%s" % "ABCD"[k], verts, faces, uv))
    return objs


# ------------------------------------------------------------------ report

def mesh_stats(obj):
    mesh = obj.data
    tris = 0
    for poly in mesh.polygons:
        tris += max(1, len(poly.vertices) - 2)
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    return {
        "name": obj.name,
        "vertices": len(mesh.vertices),
        "triangles": tris,
        "has_uv": len(mesh.uv_layers) > 0,
        "bounds_m": [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4), round(max(zs) - min(zs), 4)],
    }


def validate(objs):
    problems = []
    for obj in objs:
        stats = mesh_stats(obj)
        if stats["triangles"] > 1600:
            problems.append("%s is above the low-poly budget (%d tris)" % (obj.name, stats["triangles"]))
        if not stats["has_uv"]:
            problems.append("%s has no UV layer" % obj.name)
        for poly in obj.data.polygons:
            if len(poly.vertices) < 3:
                problems.append("%s has a degenerate face" % obj.name)
    if problems:
        for p in problems:
            print("[phase12] MESH VALIDATION FAIL: %s" % p)
        raise SystemExit("phase12_meshes validation failed")
    print("[phase12] mesh validation: %d meshes, all UV-mapped and low poly" % len(objs))


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parsed = parser.parse_args(args)
    out_dir = parsed.out
    os.makedirs(out_dir, exist_ok=True)

    entries = []

    clear_scene()
    ribbon = build_trail_ribbon()
    size = export([ribbon], os.path.join(out_dir, "trail_ribbon.glb"))
    stats = mesh_stats(ribbon)
    stats.update({
        "id": "vfx_trail_mesh", "file": "meshes/trail_ribbon.glb", "bytes": size,
        "uv": "U along the length (0 emitter -> 1 tip), V across (0..1)",
        "taper_profile": "alpha = max(0.02, (1-t)^1.35), authored into vertex colour alpha",
        "forward": "+Z (length), width in X, authored sag -Y",
        "authored": "tools/blender/phase12_meshes.py",
        "purpose": "camera-aware tapered strip driven by a sample history (broom trail, projectile ribbon, Expelliarmus)",
    })
    entries.append(stats)
    validate([ribbon])

    clear_scene()
    shield = build_shield_shell()
    size = export([shield], os.path.join(out_dir, "shield_shell.glb"))
    stats = mesh_stats(shield)
    stats.update({
        "id": "vfx_shield_mesh", "file": "meshes/shield_shell.glb", "bytes": size,
        "uv": "spherical (u around, v top to bottom)",
        "radius_m": 1.0,
        "authored": "tools/blender/phase12_meshes.py",
        "purpose": "Protego shell - the one effect where a solid surface is intentional; scaled to the 1.8 m ward radius at runtime",
    })
    entries.append(stats)
    validate([shield])

    clear_scene()
    core = build_projectile_core()
    size = export([core], os.path.join(out_dir, "projectile_core.glb"))
    stats = mesh_stats(core)
    stats.update({
        "id": "vfx_projectile_mesh", "file": "meshes/projectile_core.glb", "bytes": size,
        "uv": "cylindrical wrap",
        "forward": "+Z",
        "authored": "tools/blender/phase12_meshes.py",
        "purpose": "subtle carrier core inside projectile streaks (replaces the placeholder sphere)",
    })
    entries.append(stats)
    validate([core])

    clear_scene()
    shards = build_shards()
    size = export(shards, os.path.join(out_dir, "shards.glb"))
    for obj in shards:
        stats = mesh_stats(obj)
        stats.update({
            "id": "vfx_shard_meshes", "file": "meshes/shards.glb", "bytes": size,
            "authored": "tools/blender/phase12_meshes.py",
            "purpose": "irregular debris shards for Bombarda (four variants in one GLB)",
        })
        entries.append(stats)
    validate(shards)

    meta = {
        "schema": 1,
        "generator": "client/tools/blender/phase12_meshes.py",
        "blender": BLENDER_VERSION,
        "generated": time.strftime("%Y-%m-%d"),
        "units": "metres; glTF +Y up; untextured (the game assigns materials)",
        "provenance": "project-original authored geometry; no imported or third-party mesh",
        "meshes": entries,
    }
    with open(os.path.join(out_dir, "meshes_metadata.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=1)
        handle.write("\n")
    for entry in entries:
        print("[phase12] %s: %d tris, %s" % (entry["file"], entry["triangles"], entry["bounds_m"]))


if __name__ == "__main__":
    main()
