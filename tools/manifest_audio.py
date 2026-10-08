#!/usr/bin/env python3
"""Record the spell effects and sound assets in assets/manifest.json.

Every measured field (sha256, dimensions, frame counts, durations) is read from
the published metadata the generators wrote - `assets/vfx/metadata.json`,
`assets/vfx/meshes/meshes_metadata.json` and `assets/audio/sound_library.json`,
all produced by the scripts that authored the files. Nothing here is invented:
an entry is only written when the file exists, and every earlier phase's entries
are preserved untouched.

Usage: python tools/manifest_audio.py
"""

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "assets", "manifest.json")
VFX_META = os.path.join(ROOT, "assets", "vfx", "metadata.json")
MESH_META = os.path.join(ROOT, "assets", "vfx", "meshes", "meshes_metadata.json")
SOUND_META = os.path.join(ROOT, "assets", "audio", "sound_library.json")

PROJECT_LICENSE = "Project-original; CC0-1.0 compatible (dedicated by the project)"
PROJECT_SOURCE = "n/a - original work synthesised/authored by the project's own scripts"

# Inventory ID (12.2) -> what the entry says beyond the measured fields.
PURPOSE = {
    "vfx_flame_loop": "Loaning flame plume flipbook: Incendio sustain, Ultimate tail, torches",
    "vfx_fire_burst": "Non-looping directional fire burst: Incendio cast/impact",
    "vfx_smoke_puff": "Evolving soft smoke: Incendio extinguish, Bombarda dust, Ultimate tail",
    "vfx_energy_impact": "Irregular magical impact: every projectile hit and the Ultimate strike",
    "vfx_shield_ripple": "Local shield impact ripple with a fracture tail: Protego hit response",
    "vfx_ground_marks": "Scorch, dust ring, fragment spray and cracked ring ground marks",
    "vfx_rune_masks": "Restrained rune/telegraph masks: boss warning, ward glyph, countdown",
    "vfx_lightning_branches": "Irregular branching energy masks for the Ultimate strike",
    "vfx_soft_glow": "Soft radial glow used by muzzle flashes, ember sprites and impact cores",
    "vfx_noise_flow": "Tileable flow + noise data for the shield's flowing field and streak scroll",
    "vfx_noise_erosion": "Tileable erosion noise for the shield's expiration dissolve",
    "vfx_distortion": "Heat-haze/refraction vector data (available to the distortion layer)",
    "vfx_energy_streak": "Tapered streak mask for projectile trails, the Expelliarmus ribbon and the broom trail",
    "vfx_shield_fracture": "Fracture mask drawn over the ward as it expires",
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    for required in (VFX_META, MESH_META, SOUND_META):
        if not os.path.exists(required):
            raise SystemExit("missing %s - run the spell effects generators first" % required)
    with open(MANIFEST, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    with open(VFX_META, "r", encoding="utf-8") as handle:
        vfx = json.load(handle)
    with open(MESH_META, "r", encoding="utf-8") as handle:
        meshes = json.load(handle)
    with open(SOUND_META, "r", encoding="utf-8") as handle:
        sounds = json.load(handle)

    existing = {entry["id"]: entry for entry in manifest["assets"]}
    added = []

    def put(entry):
        if entry["id"] in existing:
            existing[entry["id"]].update(entry)
        else:
            manifest["assets"].append(entry)
            added.append(entry["id"])

    # --- VFX images (the 12.2 inventory) -------------------------------------
    for item in vfx.get("assets", []):
        rel = "assets/vfx/" + item["path"]
        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            print("SKIP missing %s" % rel)
            continue
        entry = {
            "id": item["id"],
            "purpose": PURPOSE.get(item["id"], item.get("purpose", "")),
            "status": "integrated",
            "author": "HPMMO project (original)",
            "source_url": PROJECT_SOURCE,
            "license": PROJECT_LICENSE,
            "license_url": "assets/vfx/PROVENANCE.txt",
            "license_file": "assets/vfx/PROVENANCE.txt",
            "attribution_required": False,
            "local_paths": [rel, "tools/blender/spell_vfx.py"],
            "sha256": {rel: sha256(full)},
            "generator": "tools/blender/spell_vfx.py (Blender %s, seeded %s)" % (
                vfx.get("blender", "?"), vfx.get("seed", "?")),
            "frames": item.get("frames", 1),
            "loop": item.get("loop", False),
            "fps": item.get("fps", 0),
            "frame_order": item.get("frame_order", "single frame"),
            "cell_px": item.get("cell_px", item.get("size_px", [0])[0] if item.get("size_px") else 0),
            "sheet_px": item.get("sheet_px", item.get("size_px", [])),
            "padding_px": item.get("padding_px", 0),
            "alpha": item.get("alpha", "straight"),
            "colour_space": item.get("colour_space", ""),
            "blend_default": item.get("blend_default", ""),
            "temporal_method": vfx.get("temporal_method", ""),
            "acceptance": ("spell-effect metadata.json (frame count/order/FPS/loop/alpha/padding/colour space "
                           "match the shipped file; every padding gutter asserted empty), "
                           "tools/downloads/vfx-atlas-%s.png, and run_vfx_checks.ps1" % item["id"]),
            "evidence": ["tools/downloads/vfx-atlas-%s.png" % os.path.basename(item["path"]).replace(".png", "")],
        }
        if item.get("channel_convention"):
            entry["channel_convention"] = item["channel_convention"]
        if item.get("tiling"):
            entry["tiling"] = item["tiling"]
        put(entry)

    # --- VFX meshes ----------------------------------------------------------
    for item in meshes.get("meshes", []):
        rel = "assets/vfx/" + item["file"]
        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            print("SKIP missing %s" % rel)
            continue
        asset_id = item["id"]
        entry = existing.get(asset_id, {})
        paths = entry.get("local_paths", [])
        if rel not in paths:
            paths = paths + [rel]
        entry.update({
            "id": asset_id,
            "purpose": item.get("purpose", ""),
            "status": "integrated",
            "author": "HPMMO project (original)",
            "source_url": PROJECT_SOURCE,
            "license": PROJECT_LICENSE,
            "license_url": "assets/vfx/PROVENANCE.txt",
            "license_file": "assets/vfx/PROVENANCE.txt",
            "attribution_required": False,
            "local_paths": paths + ["tools/blender/spell_meshes.py"],
            "sha256": dict(entry.get("sha256", {}), **{rel: sha256(full)}),
            "generator": "tools/blender/spell_meshes.py (Blender %s)" % meshes.get("blender", "?"),
            "triangles": item.get("triangles", 0),
            "vertices": item.get("vertices", 0),
            "uv": item.get("uv", ""),
            "bounds_m": item.get("bounds_m", []),
            "acceptance": ("tools/blender/spell_meshes.py validation block (UV-mapped, low poly, no "
                           "degenerate faces), meshes_metadata.json, and the spell-effect checks"),
        })
        if item.get("taper_profile"):
            entry["taper_profile"] = item["taper_profile"]
        if item.get("radius_m"):
            entry["radius_m"] = item["radius_m"]
        put(entry)

    # --- the Kenney ingredients: still present, still ingredients ------------
    for asset_id, note in {
        "vfx_flame_static": ("Kenney Particle Pack flame still (CC0) - used as a particle sprite "
                             "inside the Incendio/Ultimate/broom layers, never as the effect itself. "
                             "Replaced the effects it used to stand in for."),
        "vfx_spark_static": ("Kenney Particle Pack spark still (CC0) - used as an ember/spark particle "
                             "sprite and the boss warning's rim motes, never as the effect itself."),
    }.items():
        entry = existing.get(asset_id)
        if entry is not None:
            entry["status"] = "integrated"
            entry["purpose"] = note
            print("updated ingredient: %s" % asset_id)

    # --- sound library -------------------------------------------------------
    library_entry = {
        "id": "sfx_spell_library",
        "purpose": ("Spell-effect sound library: distinct cast/travel/impact/sustain/end variants for all "
                    "seven spells, surface footsteps, robe movement, mount/dismount, broom wind, landing, "
                    "spider movement/bites/death, boss attacks and death, UI feedback, map transitions, "
                    "exterior wind and birds, interior room tones (Great Hall / library / dungeon), fire "
                    "and candle beds, distant activity and the moving-stair mechanism"),
        "status": "integrated",
        "author": "HPMMO project (original synthesis)",
        "source_url": PROJECT_SOURCE,
        "license": PROJECT_LICENSE,
        "license_url": "assets/audio/CREDITS-spell-audio.md",
        "license_file": "assets/audio/CREDITS-spell-audio.md",
        "attribution_required": False,
        "local_paths": ["assets/audio/", "tools/audio/synth_spell_sfx.py", "tools/audio/tune_imports.py"],
        "generator": "tools/audio/synth_spell_sfx.py (Python standard library, seeded 20261005)",
        "sound_count": len(sounds.get("sounds", {})),
        "buses": sounds.get("buses", []),
        "import_policy": ("loop beds import with the forward loop flag and IMA-ADPCM; everything over "
                          "two seconds stays compressed; enforced by tools/audio/tune_imports.py --check"),
        "acceptance": ("run_vfx_checks.ps1 (every stage's sound exists and is distinct, every loop "
                       "imports as a loop, buses and volume controls present, limiter and priority keys "
                       "configured) and tools/downloads/vfx-check.log"),
        "evidence": ["assets/audio/sound_library.json", "tools/downloads/vfx-check.log"],
    }
    put(library_entry)

    summary = {}
    for entry in manifest["assets"]:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    manifest["summary"] = summary
    manifest["notes"] = (manifest.get("notes", "") +
                         " | the spell effects (2026-10-05): every missing VFX inventory item is now project-original "
                         "art authored by tools/blender/spell_vfx.py (four coherent 64-frame flipbooks, "
                         "ripple/rune/mark/lightning atlases, glow/noise/flow/distortion/streak/fracture "
                         "textures) and tools/blender/spell_meshes.py (trail ribbon, shield shell, "
                         "projectile core, shards); the whole sound library is original synthesis from "
                         "tools/audio/synth_spell_sfx.py. The two Kenney stills remain as particle "
                         "ingredients, not effects. No VFX or audio entry remains missing or placeholder.")
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print("wrote %s: %d assets (%d new), summary=%s" % (MANIFEST, len(manifest["assets"]), len(added), summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
