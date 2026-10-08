#!/usr/bin/env python3
"""Record the creature assets in assets/manifest.json.

Measured fields (sha256, triangles, joints, clips, bbox, materials, images) come
from tools/downloads/asset-audit.json - run tools/asset_audit.py first. Nothing
here is invented: an entry is only written when the file exists and the audit
has a row for it, and the earlier rig and art entries are preserved untouched.

Usage: python tools/manifest_creatures.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, "tools", "downloads", "asset-audit.json")
MANIFEST = os.path.join(ROOT, "assets", "manifest.json")

PROJECT_LICENSE = "Project-original (no third-party asset); CC0-1.0 compatible"
PROJECT_SOURCE = "n/a - original work, no third-party asset"

ENTRIES = {
    "acromantula": {
        "purpose": ("Ordinary monster: anatomically readable eight-legged giant spider - "
                    "cephalothorax, segmented abdomen, 8 articulated five-segment leg chains (coxa/femur/"
                    "patella/tibia/tarsus), chelicerae with fangs, pedipalps and eight eyes - rigged, "
                    "animated and textured for gameplay"),
        "paths": ["assets/models/monsters/acromantula.glb", "tools/blender/build_spider.py"],
        "script": "tools/blender/build_spider.py",
        "materials_note": "chitin / membrane / eyes (emissive) / fangs",
        "collision": ("authored capsule proxies in scenes/entities/mobs/mob_acromantula.tscn "
                      "(r 0.95 h 1.9, plus a boss proxy r 1.5 h 3.0); render meshes are never colliders"),
        "lods": ("LOD1 = 4,992 tris (50%) shipped as a second skinned mesh in the same GLB; "
                 "mob_base._apply_lod sets visibility_range 26 m at runtime"),
        "clips_note": ("Idle/Walk loop, Turn, Bite_Anticipation, Bite_Attack, Hit, Stun loop, Death "
                       "(1.79 s collapse; a dead spider holds the corpse pose instead of walking)"),
        "acceptance": ("build_spider.py validation block (8 leg chains, 48 bones, 0 overlapping texels "
                       "outside the mirrored leg islands, bind-pose min y 0.000 m), pose renders "
                       "tools/downloads/spider-{idle,walk,death,detail}.png, and the pack/boss/corpse "
                       "behaviour asserted by server/tests/encounters_sim.py"),
        "evidence": ["tools/downloads/spider-idle.png", "tools/downloads/spider-walk.png",
                     "tools/downloads/spider-death.png", "tools/downloads/spider-detail.png"],
    },
    "boss-matriarch": {
        "purpose": ("Solo boss (Acromantula Matriarch): a distinct giant-spider composition - "
                    "spiked carapace crown, barbed legs, egg sac, glowing eye cluster - with its own "
                    "directional (Spit) and area (Slam) attack animations alongside the shared clips"),
        "paths": ["assets/models/monsters/boss_matriarch.glb", "tools/blender/build_boss_matriarch.py"],
        "script": "tools/blender/build_boss_matriarch.py",
        "materials_note": "armoured chitin / membrane / eyes (emissive) / fangs + egg sac",
        "collision": ("the boss proxy capsule in mob_acromantula.tscn (r 1.5 h 3.0) is selected by "
                      "mob_base._apply_boss_visual when FLAG_BOSS arrives"),
        "lods": "LOD1 = 14,044 tris (50%) in the same GLB; visibility_range set at runtime",
        "clips_note": ("Idle/Walk/Stun loop, Hit, Death (2.2 s), Slam_Anticipation/Attack and "
                       "Spit_Anticipation/Attack - the anticipation clips are the telegraph the client "
                       "renders from the authority's release tick"),
        "acceptance": ("build_boss_matriarch.py validation block (49 bones, 9 clips, span 3.25 m, "
                       "frame-swept ground contact, IK residual 0.000 m, deterministic rebuild), renders "
                       "tools/downloads/matriarch-*.png, and the solo-boss checks in encounters_sim.py"),
        "evidence": ["tools/downloads/matriarch-idle.png", "tools/downloads/matriarch-slam.png",
                     "tools/downloads/matriarch-dead.png"],
    },
    "boss-commander": {
        "purpose": ("Escorted boss (Dark Snatcher Commander): a hooded dark wizard with a banded "
                    "staff and a hard silhouette, replacing the scaled Orc_Skull placeholder, with its own "
                    "directional (Cast_Directional) and area (Cast_Area) attack animations"),
        "paths": ["assets/models/monsters/boss_commander.glb", "tools/blender/build_boss_commander.py"],
        "script": "tools/blender/build_boss_commander.py",
        "materials_note": "robe cloth / leather+metal trim / staff wood+metal / glowing eyes",
        "collision": ("the boss proxy capsule in mob_darksnatcher.tscn (r 0.62 h 2.24); the ordinary "
                      "body keeps its own capsule and the two are swapped by mob_base"),
        "lods": "LOD1 = 13,650 tris (53%) in the same GLB; visibility_range set at runtime",
        "clips_note": ("Idle/Walk/Stun loop, Hit, Death (2.0 s), Cast_Directional_Anticipation/Attack and "
                       "Cast_Area_Anticipation/Attack (the area telegraph is a two-handed overhead slam)"),
        "acceptance": ("build_boss_commander.py validation block (19 bones, 9 clips, 2.20 m, staff "
                       "orientation measured per combat key frame, deterministic rebuild), renders "
                       "tools/downloads/commander-*.png, and the escorted-boss (exactly two escorts) checks "
                       "in encounters_sim.py"),
        "evidence": ["tools/downloads/commander-idle.png", "tools/downloads/commander-area.png",
                     "tools/downloads/commander-directional.png", "tools/downloads/commander-dead.png"],
    },
}

# The ordinary Quaternius minions are still placeholders after the creature pass: say so
# where the manifest already lists them.
PLACEHOLDER_NOTE = {
    "asset-Demon-gltf": ("Placeholder after the creature pass: the spider and both bosses are authored "
                         "(boss-*), this Quaternius ghoul body is not. Still shipped as the ordinary "
                         "Inferi visual."),
    "asset-Ninja-gltf": ("Placeholder after the creature pass: the spider and both bosses are authored "
                         "(boss-*), this Quaternius ninja body is not. Still shipped as the ordinary "
                         "Dark Snatcher visual (the boss uses boss_commander.glb)."),
}

MISSING_UPDATE = {
    "monster_variants_final": ("Delivered the spider (acromantula) and both boss bodies "
                               "(boss-matriarch, boss-commander). Still missing: authored "
                               "ordinary minion bodies to replace the Quaternius placeholders "
                               "(asset-Demon-gltf = Inferi, asset-Ninja-gltf = Dark Snatcher)."),
}


def main():
    with open(AUDIT, encoding="utf-8") as handle:
        audit = json.load(handle)
    by_path = {m["path"]: m for m in audit.get("models", [])}
    with open(MANIFEST, encoding="utf-8") as handle:
        manifest = json.load(handle)

    def find(asset_id):
        for entry in manifest["assets"]:
            if entry["id"] == asset_id:
                return entry
        return None

    added = 0
    for asset_id, spec in ENTRIES.items():
        path = spec["paths"][0]
        if not os.path.isfile(os.path.join(ROOT, path)):
            print("SKIP %s: %s is not on disk" % (asset_id, path))
            continue
        row = by_path.get(path)
        if row is None:
            print("SKIP %s: no audit row for %s (run tools/asset_audit.py)" % (asset_id, path))
            continue
        # LOD0/LOD1 are two skinned meshes in one file: the audit sums them, so
        # both numbers are stated rather than one being passed off as the other.
        entry = {
            "id": asset_id,
            "purpose": spec["purpose"],
            "status": "integrated",
            "author": "Authored for this project (%s); procedural textures packed in the GLB" % spec["script"],
            "source_url": PROJECT_SOURCE,
            "license": PROJECT_LICENSE,
            "license_url": "",
            "license_file": "",
            "attribution_required": False,
            "local_paths": spec["paths"],
            "sha256": {path: row.get("sha256", "")},
            "scale_m": row.get("bbox_size_m"),
            "triangles": ("%d across LOD0 + LOD1 (one GLB, two skinned meshes)" % int(row.get("triangles", 0))),
            "material_slots": len(row.get("materials", [])),
            "textures": {
                "channels": ["albedo", "normal", "rough"],
                "note": ("%d images packed in the GLB (albedo sRGB, normal OpenGL +Y Non-Color, "
                         "roughness Non-Color)" % int(row.get("images", 0))),
            },
            "rig": {
                "skinned": int(row.get("skins", 0)) > 0,
                "joints": int(row.get("joints", 0)),
                "clips": [a["name"] for a in row.get("animations", [])],
                "clips_note": spec["clips_note"],
                "root_motion": "none (all clips authored in place)",
            },
            "collision": spec["collision"],
            "lods": spec["lods"],
            "materials": row.get("materials", []),
            "materials_note": spec["materials_note"],
            "acceptance": spec["acceptance"],
            "evidence": spec["evidence"],
            "scale_source": "tools/asset_audit.py world-space bind-pose AABB (metres)",
        }
        existing = find(asset_id)
        if existing is None:
            manifest["assets"].append(entry)
            added += 1
        else:
            existing.update(entry)
        print("%s %s: %d tris, %d joints, %d clips"
              % ("added" if existing is None else "updated", asset_id,
                 int(row.get("triangles", 0)), int(row.get("joints", 0)), len(row.get("animations", []))))

    for asset_id, note in PLACEHOLDER_NOTE.items():
        entry = find(asset_id)
        if entry is not None:
            entry["status"] = "placeholder"
            entry["placeholder_reason"] = note
            print("marked placeholder: %s" % asset_id)

    for asset_id, note in MISSING_UPDATE.items():
        entry = find(asset_id)
        if entry is not None:
            entry["notes"] = note
            print("updated gap note: %s" % asset_id)

    summary = {}
    for entry in manifest["assets"]:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    manifest["summary"] = summary
    manifest["notes"] = (manifest.get("notes", "") +
                         " | the creature pass (2026-10-05): authored spider (acromantula) and both boss bodies "
                         "(boss-matriarch, boss-commander) recorded with measured tris/joints/"
                         "clips/LODs; the Quaternius Inferi and Dark Snatcher minions are marked placeholders.")
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1, ensure_ascii=False)
    print("wrote %s: %d assets, summary=%s" % (MANIFEST, len(manifest["assets"]), summary))


if __name__ == "__main__":
    sys.exit(main())
