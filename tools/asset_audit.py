#!/usr/bin/env python3
"""HPMMO asset audit — extract real stats from GLB/GLTF and PNG/JPEG files.

Feeds assets/manifest.json. Pure stdlib.
Usage: python tools/asset_audit.py

scale_m fields are WORLD-SPACE AABBs: every node's TRS (or matrix) is applied
along the scene hierarchy before unioning mesh bounds, so FBX2glTF exports
that carry x100 node scales report true meters. Skinned meshes are approximate
(bind-pose node transforms, no skin deformation) and flagged as such.
"""

import hashlib
import json
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "downloads", "asset-audit.json")


def read_glb_json(path):
    """Return the glTF JSON dict from a .glb (binary) or .gltf (text) file."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] == b"glTF":
            length = struct.unpack("<I", head[8:12])[0]
            rest = f.read(length)
            clen, ctype = struct.unpack("<II", rest[:8])
            if ctype != 0x4E4F534A:  # 'JSON'
                raise ValueError("first GLB chunk is not JSON")
            return json.loads(rest[8:8 + clen].decode("utf-8", "replace"))
        f.seek(0)
        return json.loads(f.read().decode("utf-8-sig", "replace"))


# --- 4x4 row-major matrix helpers (point = column vector) ---------------------

def mat_identity():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def mat_mul(a, b):
    return [sum(a[i * 4 + k] * b[k * 4 + j] for k in range(4)) for i in range(4) for j in range(4)]


def mat_from_trs(t, r, s):
    x, y, z, w = r
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        (1 - 2 * (yy + zz)) * s[0], 2 * (xy - wz) * s[1], 2 * (xz + wy) * s[2], 0.0,
        2 * (xy + wz) * s[0], (1 - 2 * (xx + zz)) * s[1], 2 * (yz - wx) * s[2], 0.0,
        2 * (xz - wy) * s[0], 2 * (yz + wx) * s[1], (1 - 2 * (xx + yy)) * s[2], 0.0,
        t[0], t[1], t[2], 1.0,
    ]


def gltf_stats(doc):
    stats = {}
    stats["generator"] = doc.get("asset", {}).get("generator", "?")
    stats["nodes"] = len(doc.get("nodes", []))
    stats["meshes"] = len(doc.get("meshes", []))
    accessors = doc.get("accessors", [])

    def acc(index):
        if isinstance(index, int) and 0 <= index < len(accessors):
            return accessors[index]
        return {}

    triangles = 0
    prims = 0
    has_normals = True
    has_tangents = False
    has_uv = True
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            prims += 1
            attrs = prim.get("attributes", {})
            if "indices" in prim:
                triangles += acc(prim["indices"]).get("count", 0) // 3
            else:
                triangles += acc(attrs.get("POSITION")).get("count", 0) // 3
            has_normals = has_normals and "NORMAL" in attrs
            has_tangents = has_tangents or "TANGENT" in attrs
            has_uv = has_uv and "TEXCOORD_0" in attrs
    stats["primitives"] = prims
    stats["triangles"] = triangles
    stats["has_normals"] = has_normals
    stats["has_tangents"] = has_tangents
    stats["has_uv"] = has_uv

    # --- world-space AABB (node transforms applied) ---
    nodes = doc.get("nodes", [])
    parents = set()
    for n in nodes:
        for c in n.get("children", []):
            parents.add(c)
    roots = [i for i in range(len(nodes)) if i not in parents]

    def node_matrix(n):
        if "matrix" in n:
            cm = n["matrix"]  # glTF matrix is column-major
            return [cm[0], cm[4], cm[8], cm[12],
                    cm[1], cm[5], cm[9], cm[13],
                    cm[2], cm[6], cm[10], cm[14],
                    cm[3], cm[7], cm[11], cm[15]]
        return mat_from_trs(n.get("translation", [0, 0, 0]),
                            n.get("rotation", [0, 0, 0, 1]),
                            n.get("scale", [1, 1, 1]))

    bbox_min = [None, None, None]
    bbox_max = [None, None, None]
    stack = [(i, mat_identity()) for i in roots]
    while stack:
        idx, parent_m = stack.pop()
        node = nodes[idx]
        world_m = mat_mul(parent_m, node_matrix(node))
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]].get("primitives", []):
                pos = acc(prim.get("attributes", {}).get("POSITION"))
                if pos and "min" in pos and "max" in pos:
                    for cx in (pos["min"][0], pos["max"][0]):
                        for cy in (pos["min"][1], pos["max"][1]):
                            for cz in (pos["min"][2], pos["max"][2]):
                                p = (cx, cy, cz, 1.0)
                                wp = [sum(world_m[i * 4 + k] * p[k] for k in range(4)) for i in range(4)]
                                for i in range(3):
                                    if bbox_min[i] is None or wp[i] < bbox_min[i]:
                                        bbox_min[i] = wp[i]
                                    if bbox_max[i] is None or wp[i] > bbox_max[i]:
                                        bbox_max[i] = wp[i]
        for c in node.get("children", []):
            stack.append((c, world_m))
    if bbox_min[0] is not None:
        stats["bbox_size_m"] = [round(bbox_max[i] - bbox_min[i], 3) for i in range(3)]
        stats["bbox_min"] = [round(v, 3) for v in bbox_min]
        stats["bbox_max"] = [round(v, 3) for v in bbox_max]
        stats["bbox_space"] = "world (node transforms applied)"
        if doc.get("skins"):
            stats["bbox_note"] = "skinned mesh: bind-pose approximation, no skin deformation"

    stats["materials"] = [m.get("name", "?") for m in doc.get("materials", [])]
    stats["images"] = len(doc.get("images", []))
    skins = doc.get("skins", [])
    stats["skins"] = len(skins)
    stats["joints"] = len(skins[0]["joints"]) if skins else 0
    anims = []
    for anim in doc.get("animations", []):
        duration = 0.0
        for sampler in anim.get("samplers", []):
            input_acc = acc(sampler.get("input")) if "input" in sampler else None
            if input_acc and "max" in input_acc and input_acc["max"]:
                duration = max(duration, float(input_acc["max"][0]))
        anims.append({"name": anim.get("name", "?"), "seconds": round(duration, 3)})
    stats["animations"] = anims
    return stats


def png_info(path):
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    bitdepth = head[24]
    colortype = head[25]
    types = {0: "gray", 2: "rgb", 3: "indexed", 4: "gray+a", 6: "rgba"}
    return {"width": w, "height": h, "depth": bitdepth, "color": types.get(colortype, str(colortype))}


JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_info(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in JPEG_SOF:
            h = (data[i + 5] << 8) | data[i + 6]
            w = (data[i + 7] << 8) | data[i + 8]
            return {"width": w, "height": h, "depth": data[i + 4], "color": "jpeg"}
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = (data[i + 2] << 8) | data[i + 3]
        i += 2 + seg_len
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    models = []
    textures = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        pruned = []
        for d in dirnames:
            full = os.path.join(dirpath, d).replace("\\", "/")
            if d in (".git", ".godot"):
                continue
            # tools/ is build machinery EXCEPT the downloaded candidate tree,
            # which must be measured too (referenced-not-curated packs).
            if "/tools" in full and "asset-candidates" not in full:
                continue
            pruned.append(d)
        dirnames[:] = pruned
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if name.endswith((".glb", ".gltf")):
                entry = {"path": rel, "bytes": os.path.getsize(path)}
                try:
                    entry.update(gltf_stats(read_glb_json(path)))
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = str(exc)
                entry["sha256"] = sha256(path)
                models.append(entry)
            elif name.endswith(".png"):
                info = png_info(path)
                if info:
                    info.update({"path": rel, "bytes": os.path.getsize(path), "sha256": sha256(path)})
                    textures.append(info)
            elif name.endswith((".jpg", ".jpeg")):
                info = jpeg_info(path)
                if info:
                    info.update({"path": rel, "bytes": os.path.getsize(path), "sha256": sha256(path)})
                    textures.append(info)
    report = {"models": models, "textures": textures}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"wrote {OUT}")
    print(f"{len(models)} models, {len(textures)} textures")
    print(f"{'path':<64} {'tris':>7} {'joints':>6} {'anims':>5} {'size_m (world)':>22}")
    for m in models:
        if "assets/candidates" in m["path"] or "characters" in m["path"] or "monsters" in m["path"]:
            size = m.get("bbox_size_m", ["?", "?", "?"])
            print(f"{m['path']:<64} {m.get('triangles', '?'):>7} {m.get('joints', 0):>6} {len(m.get('animations', [])):>5} {str(size):>22}")


if __name__ == "__main__":
    main()
