#!/usr/bin/env python3
"""Record the tiered broom models in assets/manifest.json.

One entry per `assets/models/props/brooms/broom_<id>.glb`. The measured fields
(sha256, triangles, bounds, material slots) are read straight from the GLB, so
nothing is copied by hand; every other entry is left untouched.

The models come from the item pipeline in art/pipeline/ITEM_3D_PIPELINE.md:
gpt-image-2.5 concept views -> Meshy 7.1 multi-image-to-3d ->
art/pipeline/scripts/broom_postprocess.py (axes, sockets, 1024 px textures).

Usage: python tools/manifest_brooms.py
"""

import glob
import hashlib
import json
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "assets", "manifest.json")
BROOMS = os.path.join(ROOT, "assets", "models", "props", "brooms")

TIERS = {
    "ashwood": 1,
    "runebound": 2,
    "silverthorn": 3,
    "emberwing": 4,
    "moonveil": 5,
}


def read_glb(path: str) -> dict:
    with open(path, "rb") as fh:
        data = fh.read()
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


def measure(gltf: dict) -> dict:
    tris = 0
    lo, hi = [1e9] * 3, [-1e9] * 3
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if "indices" in prim:
                tris += gltf["accessors"][prim["indices"]]["count"] // 3
            pos = gltf["accessors"][prim["attributes"]["POSITION"]]
            lo = [min(a, b) for a, b in zip(lo, pos["min"])]
            hi = [max(a, b) for a, b in zip(hi, pos["max"])]
    # Mesh-local bounds; the parts share one frame under BroomRoot (identity).
    return {"triangles": tris, "scale_m": [round(h - l, 3) for l, h in zip(lo, hi)],
            "material_slots": len(gltf.get("materials", []))}


def entry(path: str) -> dict:
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    name = os.path.splitext(os.path.basename(path))[0][len("broom_"):]
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    stats = measure(read_glb(path))
    return {
        "id": "asset-broom_%s-glb" % name,
        "purpose": "tier %d flight broom (items.json broom_%s `model`)" % (TIERS.get(name, 0), name),
        "status": "integrated",
        "author": "project (AI-assisted: openai/gpt-image-2.5 concept, meshy/v7.1 mesh)",
        "source_url": "art/pipeline/ITEM_3D_PIPELINE.md",
        "license": "Project-original (generated for this project)",
        "license_url": "art/pipeline/ITEM_3D_PIPELINE.md",
        "license_file": "",
        "attribution_required": False,
        "local_paths": [rel],
        "sha256": {rel: digest},
        "scale_m": stats["scale_m"],
        "triangles": stats["triangles"],
        "material_slots": stats["material_slots"],
        "textures": {"channels": ["base_color", "metallic_roughness", "normal"], "note": "embedded, 1024 px"},
        "rig": {"skinned": False, "joints": 0, "clips": []},
        "collision": "none (the broom never collides; the rider's capsule does)",
        "lods": "Godot import-generated",
    }


def main() -> None:
    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)
    fresh = [entry(p) for p in sorted(glob.glob(os.path.join(BROOMS, "broom_*.glb")))]
    ids = {e["id"] for e in fresh}
    manifest["assets"] = [a for a in manifest["assets"] if a.get("id") not in ids] + fresh
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    for e in fresh:
        print(e["id"], e["triangles"], "tris", e["scale_m"])


if __name__ == "__main__":
    main()
