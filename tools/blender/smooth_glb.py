"""Shade Auto Smooth for finished GLBs: smooth shading, with edges sharper than
ANGLE kept hard (Blender's "Smooth by Angle", applied to the mesh data so the
glTF export carries it). For models exported flat-shaded, whose curved
surfaces showed as facets in the game (rocks, a balustrade's turned posts, a
tower cap, the flight broom). No vertex or triangle is added; the split
normals are what change.

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup \
        --python tools/blender/smooth_glb.py -- [--angle 35] <in.glb> [<in.glb> ...]

Each mesh is welded first (Merge by Distance, 1e-6 m) and its imported custom
normals cleared: a flat export comes in with every face apart, which leaves
nothing to smooth. A file whose welding would drop more than its zero-area
triangles (overlapping or double-sided shells: tower_cap_7, broom_flight) is
skipped untouched.

Each file is rewritten in place (the original kept beside it as .glb.bak
unless --no-backup). Prints per file: meshes, materials, triangles, actions
before and after, so a round trip that lost something shows at once.
"""
import math
import os
import sys

import bmesh
import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
angle = 35.0
weld = 1e-6
backup = True
files = []
i = 0
while i < len(args):
    if args[i] == "--angle":
        angle = float(args[i + 1])
        i += 2
        continue
    if args[i] == "--no-backup":
        backup = False
    else:
        files.append(args[i])
    i += 1


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions, bpy.data.armatures):
        for d in list(coll):
            coll.remove(d)


def stats():
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
    # zero-area faces: welding drops them, and nothing is lost on screen
    degenerate = sum(sum(1 for p in o.data.polygons if p.area < 1e-10) for o in meshes)
    return {"objects": sorted(o.name for o in bpy.data.objects), "materials": sorted(m.name for m in bpy.data.materials),
            "tris": tris, "degenerate": degenerate, "actions": len(bpy.data.actions), "images": len(bpy.data.images)}


for path in files:
    clear()
    bpy.ops.import_scene.gltf(filepath=path)
    before = stats()
    # Welded (Merge by Distance) and without the file's own normals: a model
    # exported flat comes in with every face apart and its normals as custom
    # split normals, either of which leaves nothing for smoothing to act on.
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        mesh = o.data
        with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
            if mesh.has_custom_normals:
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)
        bm.to_mesh(mesh)
        bm.free()
        mesh.shade_smooth()
        mesh.set_sharp_from_angle(angle=math.radians(angle))
    if stats()["tris"] < before["tris"] - before["degenerate"] or stats()["tris"] > before["tris"]:
        # welding collapsed faces (overlapping shells): leave the file as it is
        print("SMOOTHED SKIP %s | welding changed the triangles %d -> %d" % (os.path.basename(path), before["tris"], stats()["tris"]))
        continue
    if backup and not os.path.exists(path + ".bak"):
        os.replace(path, path + ".bak")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False, export_yup=True,
                              export_image_format="AUTO", export_normals=True, export_animations=before["actions"] > 0)
    clear()
    bpy.ops.import_scene.gltf(filepath=path)
    after = stats()
    same = all(before[k] == after[k] for k in ("objects", "materials", "actions", "images")) and \
        before["tris"] - before["degenerate"] <= after["tris"] <= before["tris"]
    print("SMOOTHED %s %s | objects %d materials %d tris %d actions %d images %d -> tris %d%s" % (
        "ok  " if same else "DIFF", os.path.basename(path), len(before["objects"]), len(before["materials"]),
        before["tris"], before["actions"], before["images"], after["tris"],
        "" if same else " | before %s | after %s" % (before, after)))
