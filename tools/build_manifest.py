#!/usr/bin/env python3
"""Build assets/manifest.json from the audit + curated provenance (plan.md Phase 2).

Inputs:
  tools/downloads/asset-audit.json   (run tools/asset_audit.py first — measured stats/hashes)
  tools/candidate_sources.json       (research-verified provenance, committed)
Output:
  assets/manifest.json

Every entry carries the fields plan.md Phase 2 requires: id, purpose, status,
author/source URL, license + license URL + local license copy, attribution,
local paths with sha256, scale, polygons, material slots, texture channels,
rig, animations, collision, LODs, acceptance evidence.
"""

import hashlib
import json
import os
import re
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, "tools", "downloads", "asset-audit.json")
SOURCES = os.path.join(ROOT, "tools", "candidate_sources.json")
OUT = os.path.join(ROOT, "assets", "manifest.json")

LICENSE_NAMES = ("license.txt", "license.html", "license", "licence.txt", "cc0-1.0-legalcode.txt")

# id -> curated local dir(s). Referenced-only packs stay in tools/downloads.
CURATED = {
    "quaternius-adventurer-male": ["assets/candidates/character/quaternius-adventurer-male"],
    "quaternius-hooded-adventurer": ["assets/candidates/character/quaternius-hooded-adventurer"],
    "quaternius-universal-animation-library": ["assets/candidates/character/quaternius-universal-animation-library"],
    "quaternius-universal-base-characters": ["assets/candidates/character/quaternius-universal-base-characters"],
    "quaternius-rpg-items-icons": ["assets/candidates/props/rpg-items-icons"],
    "quaternius-easy-enemies-spider-glb": ["assets/candidates/spider-creature/quaternius-easy-enemies-spider"],
    "stone-brick-wall-001": ["assets/candidates/pbr-textures/stone-brick-wall-001"],
    "para-animated-particle-fx-1": ["assets/candidates/vfx-fire-energy/para-flipbooks"],
    "mikodrak-spell-fx": ["assets/candidates/vfx-fire-energy/mikodrak-spell-fx"],
    "sinestesia-2d-explosions": ["assets/candidates/vfx-fire-energy/sinestesia-2d-explosions"],
    "calinou-lightning": ["assets/candidates/vfx-fire-energy/calinou-lightning"],
    "cethiel-angel-shield": ["assets/candidates/vfx-fire-energy/cethiel-angel-shield"],
    "codemanu-pixel-fx": ["assets/candidates/vfx-fire-energy/codemanu-pixel-fx"],
    "kenney-impact-sounds": ["assets/candidates/audio/kenney-impact-sounds"],
    "kenney-rpg-audio": ["assets/candidates/audio/kenney-rpg-audio"],
    "oga-wind-loop": ["assets/candidates/audio/oga-wind-loop"],
    "kaykit-dungeon-pack-1.1-gaps": ["assets/candidates/modular-kit/kaykit-dungeon-gaps"],
    "kaykit-furniture-bits-1.0": ["assets/candidates/modular-kit/kaykit-furniture-bits"],
    "kaykit-halloween-bits-1.0": ["assets/candidates/modular-kit/kaykit-halloween-bits"],
    "kenney-castle-kit": ["assets/candidates/modular-kit/kenney-castle-kit"],
    "kenney-furniture-kit": ["assets/candidates/modular-kit/kenney-furniture-kit"],
    "polyhaven-chandelier-lantern-01": ["assets/candidates/modular-kit/polyhaven-chandelier-lantern-01"],
    "polyhaven-potted-plant-04": ["assets/candidates/modular-kit/polyhaven-potted-plant-04"],
    # Verified but kept outside the repo (re-fetchable CC0; promote at Phase 10):
    "stone-tiles-02": ["tools/downloads/asset-candidates/stone-floor/stone-tiles-02"],
    "dark-wooden-planks": ["tools/downloads/asset-candidates/wood-planks/dark-wooden-planks"],
    "white-plaster-02": ["tools/downloads/asset-candidates/plaster/white-plaster-02"],
    "roof-slates-03": ["tools/downloads/asset-candidates/roof-slate/roof-slates-03"],
    "kenney-interface-sounds": ["tools/downloads/asset-candidates/audio/kenney-interface-sounds"],
    "kenney-music-jingles": ["tools/downloads/asset-candidates/audio/kenney-music-jingles"],
    "oga-fireplace-loop": ["tools/downloads/asset-candidates/audio/oga-fireplace-loop"],
}

PURPOSE = {
    "quaternius-adventurer-male": "taller clothed hero body candidate (Phase 9); untextured",
    "quaternius-hooded-adventurer": "hooded caster/rogue hero candidate (Phase 9); untextured",
    "quaternius-universal-animation-library": "7-head mannequin + spell-cast/attack clip library; hero + monster base (Phase 9/11)",
    "quaternius-universal-base-characters": "textured PBR base bodies (male/female) on the same rig family as the animation library (Phase 9)",
    "quaternius-rpg-items-icons": "UI icon library (107 icons: potions, weapons, loot, glyphs) for the HUD/inventory (Phase 13)",
    "quaternius-easy-enemies-spider-glb": "rigged animated spider candidate to replace the procedural acromantula (Phase 11)",
    "stone-brick-wall-001": "castle wall PBR set, physically scaled (Phase 10)",
    "stone-tiles-02": "flagstone floor PBR set (Phase 10)",
    "dark-wooden-planks": "interior wood floor PBR set (Phase 10)",
    "white-plaster-02": "interior plaster PBR set (Phase 10)",
    "roof-slates-03": "roof slate PBR set (Phase 10)",
    "para-animated-particle-fx-1": "coherent 64-frame flipbook library (fire/smoke/energy) (Phase 12)",
    "mikodrak-spell-fx": "per-spell frame sequences for cast/impact layers (Phase 12)",
    "sinestesia-2d-explosions": "explosion atlases for Bombarda/Ultimate impacts (Phase 12)",
    "calinou-lightning": "lightning bolt elements for the Ultimate (Phase 12)",
    "cethiel-angel-shield": "shield ripple frames for Protego (Phase 12)",
    "codemanu-pixel-fx": "compact pixel FX sheets (fallback/UI-scale effects)",
    "kenney-impact-sounds": "footsteps (5 surfaces), impacts, glass/metal (Phase 12.5)",
    "kenney-rpg-audio": "footsteps, cloth, doors, books, coins (Phase 12.5)",
    "oga-wind-loop": "exterior wind ambience loop (Phase 12.5)",
    "oga-fireplace-loop": "fireplace ambience loop (Phase 12.5)",
    "kenney-interface-sounds": "UI clicks/selects/errors (Phase 12.5)",
    "kenney-music-jingles": "quest/level-up jingles (Phase 12.5)",
    "kaykit-dungeon-pack-1.1-gaps": "stair/floor/railing gap pieces for the castle kit (Phase 8/10)",
    "kaykit-furniture-bits-1.0": "books, bookshelves, tables, seating, lamps (Phase 10)",
    "kaykit-halloween-bits-1.0": "candelabras, hanging lanterns, gothic arches, benches (Phase 10)",
    "kenney-castle-kit": "stone stairs + rail + tower arch pieces (Phase 8/10)",
    "kenney-furniture-kit": "potted plants, bookcases, benches, stairs (Phase 10)",
    "polyhaven-chandelier-lantern-01": "ornate lantern chandelier prop, 1k PBR (Phase 10)",
    "polyhaven-potted-plant-04": "potted plant prop, 1k PBR, metric scale (Phase 10)",
}

REJECTED = [
    {"id": "mixamo-motion-library", "reason": "Adobe Terms of Use; account required; not permissive-redistributable", "source": "mixamo.com"},
    {"id": "kenney-mini-characters", "reason": "0.67 m blocky characters, 7 bones — fails the art direction", "source": "kenney.nl"},
    {"id": "quaternius-animated-base-character", "reason": "Poly Pizza copy lists CC-BY 3.0 while the pack page says CC0 — license discrepancy; UAL (CC0) covers the same mannequin", "source": "poly.pizza"},
    {"id": "quaternius-rpg-character-pack", "reason": "textured wizard pack is Google-Drive quota-blocked for anonymous download; manual follow-up", "source": "quaternius.com"},
    {"id": "oga-*-spider (.blend)", "reason": "OGA spider downloads are .blend files and no Blender is installed; GLB spider candidate preferred", "source": "opengameart.org"},
    {"id": "spell-sounds-starter-pack", "reason": "CC-BY-SA/GPL (share-alike would infect the build)", "source": "opengameart.org"},
    {"id": "flare-magic-effects", "reason": "CC-BY-SA share-alike trap commonly mislabeled as free", "source": "opengameart.org"},
]

ATTRIBUTION_TEXT = {
    "oga-wind-loop": "Credit Jonathan Shaw (InspectorJ), https://freesound.org/people/InspectorJ/sounds/376415/ (OpenGameArt uploader AntumDeluge optional)",
}

IMPORT_NOTES = {
    "quaternius-easy-enemies-spider-glb": "Export carries x100 node scale: normalize to ~2 m leg span at import; the review capture shows it at production scale.",
    "stone-brick-wall-001": "nor_gl (OpenGL +Y) normal convention; import as Normal Map; physical capture scale 2.5 m - set uv scale per surface.",
    "stone-tiles-02": "nor_gl convention; physical scale 2 m.",
    "dark-wooden-planks": "nor_gl convention; physical scale 2 m (horizontal boards).",
    "white-plaster-02": "nor_gl convention; physical scale 1.5 m.",
    "roof-slates-03": "nor_gl convention; physical scale 3 m.",
    "polyhaven-chandelier-lantern-01": "1k PBR; root node scale 0.686 already applied in the measured size; arm-packed map (ao/rough/metal).",
    "polyhaven-potted-plant-04": "1k PBR; metric 0.17x0.27x0.18 m; arm-packed map.",
    "oga-wind-loop": "Ogg Vorbis 96 kbps; a lossless flac exists on the source page if reprocessing is needed.",
    "oga-fireplace-loop": "10 MB 32-bit WAV master; transcode to ogg for runtime.",
    "kenney-impact-sounds": "Ogg Vorbis 44.1 kHz; footsteps x5 surfaces + impacts.",
    "kenney-rpg-audio": "Ogg Vorbis 48 kHz.",
    "quaternius-universal-animation-library": "43 clips in the free Standard GLBs (itch advertises 120+ across paid tiers); 65-joint UE5-style rig with finger bones.",
    "quaternius-adventurer-male": "Untextured (flat materials, UVs present); 5 duplicated skins to merge at integration.",
    "quaternius-hooded-adventurer": "Untextured; sword is a separate non-skinned mesh to socket manually.",
    "quaternius-universal-base-characters": "Godot/UE glTF variant; PBR basecolor/normal/roughness in the same folder; hairstyles shipped in the pack are not curated yet.",
    "quaternius-rpg-items-icons": "2D PNG icons - usable directly; the pack's 106 .blend/.fbx/.obj props convert via Blender (installed, 5.2.2 LTS) at Phase 10.",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".godot",)]
        for name in sorted(filenames):
            if name.endswith(".import"):
                continue
            full = os.path.join(dirpath, name)
            out.append(os.path.relpath(full, ROOT).replace("\\", "/"))
    return out


def find_license(files):
    for f in files:
        base = os.path.basename(f).lower()
        if base in LICENSE_NAMES:
            return f
    for f in files:
        if "license" in os.path.basename(f).lower() or "licence" in os.path.basename(f).lower():
            return f
    return ""


def texture_channels(files):
    chans = set()
    for f in files:
        n = os.path.basename(f).lower()
        if n.endswith((".png", ".jpg", ".jpeg")):
            for tok, label in (("diff", "albedo"), ("albedo", "albedo"), ("nor", "normal"), ("rough", "roughness"), ("_ao", "ao"), ("arm", "arm"), ("disp", "displacement"), ("glass", "glass"), ("preview", "preview")):
                if tok in n:
                    chans.add(label)
                    break
    return sorted(chans)


def main():
    audit = json.load(open(AUDIT, encoding="utf-8"))
    sources = json.load(open(SOURCES, encoding="utf-8"))
    audit_by_path = {}
    for m in audit["models"]:
        audit_by_path[m["path"]] = m
    for t in audit["textures"]:
        audit_by_path[t["path"]] = t

    assets = []

    # --- existing in-repo assets -------------------------------------------------
    for m in audit["models"]:
        p = m["path"]
        if not p.startswith("assets/models/"):
            continue
        entry = {
            "id": "asset-" + os.path.basename(p).replace(".", "-"),
            "purpose": "", "status": "", "author": "KayKit (Kay Lousberg)" if "characters" in p else ("Quaternius" if "monsters" in p else "KayKit"),
            "source_url": "assets/ASSET_CREDITS.md", "license": "CC0 1.0",
            "license_url": "assets/ASSET_CREDITS.md", "license_file": "",
            "attribution_required": False,
            "local_paths": [p],
            "sha256": {p: m.get("sha256", "")},
            "scale_m": m.get("bbox_size_m"), "triangles": m.get("triangles"),
            "material_slots": len(m.get("materials", [])),
            "textures": {"channels": [], "note": "embedded" if m.get("images") else "none (flat materials)"},
            "rig": {"skinned": m.get("skins", 0) > 0, "joints": m.get("joints", 0), "clips": [a["name"] for a in m.get("animations", [])]},
            "collision": "none (scene/generated)", "lods": "none",
            "acceptance": "",
        }
        if "characters/wizard" in p:
            entry["purpose"] = "player hero (KayKit Mage, byte-identical to the shipped placeholder)"
            entry["status"] = "placeholder"
            entry["acceptance"] = "docs/baseline-captures/baseline-gameplay-hud.png, tools/downloads/asset-review-actors-neutral.png"
        elif "monsters/" in p:
            entry["purpose"] = "monster visual (used by mob scenes)"
            entry["status"] = "integrated"
            entry["acceptance"] = "docs/baseline-captures/baseline-enemy-assets.png"
        elif "props/" in p:
            entry["purpose"] = "unused wand/spellbook GLTF prop (broken texture reference)"
            entry["status"] = "candidate"
            entry["acceptance"] = ""
        elif "characters/" in p:
            entry["purpose"] = "unused character variant (dark wizard / inferi / knight)"
            entry["status"] = "candidate"
        else:
            entry["purpose"] = "modular environment piece (KayKit dungeon kit)"
            entry["status"] = "integrated"
            entry["acceptance"] = "docs/baseline-captures/baseline-castle-exterior.png"
        if "monsters/" in p:
            entry["license_file"] = "assets/models/monsters/License.txt"
        elif "characters/" in p:
            entry["license_file"] = "assets/models/KayKit-LICENSE.txt"
        elif "environment/" in p:
            entry["license_file"] = "assets/models/environment/KayKit-LICENSE.txt"
        if "props/" in p:
            prop_dir = os.path.dirname(p)
            stem = os.path.basename(p).rsplit(".", 1)[0]
            bp = f"{prop_dir}/{stem}.bin"
            if os.path.exists(os.path.join(ROOT, bp.replace("/", os.sep))):
                entry["local_paths"].append(bp)
                entry["sha256"][bp] = sha256(os.path.join(ROOT, bp.replace("/", os.sep)))
            entry["notes"] = "GLTF references mage_texture.png which is missing from the repo (pre-existing broken reference); unused by code (player.gd loads the wand inside wizard.glb)."
        assets.append(entry)

    # environment family entry summarizing the 44 KayKit modules
    env_files = [m["path"] for m in audit["models"] if m["path"].startswith("assets/models/environment/")]
    env_stats = [m for m in audit["models"] if m["path"].startswith("assets/models/environment/")]
    if env_files:
        assets.append({
            "id": "family-kaykit-dungeon-modules",
            "purpose": "modular castle/dungeon architecture family (walls, banners, pillars, torch, chest)",
            "status": "integrated", "author": "KayKit (Kay Lousberg)",
            "source_url": "assets/ASSET_CREDITS.md", "license": "CC0 1.0",
            "license_url": "assets/ASSET_CREDITS.md", "license_file": "assets/models/environment/KayKit-LICENSE.txt",
            "attribution_required": False,
            "local_paths": env_files,
            "sha256": {m["path"]: m.get("sha256", "") for m in env_stats},
            "scale_m": "4x4 grid modules (see per-file bbox)", "triangles": f"{min(m.get('triangles', 0) for m in env_stats)}-{max(m.get('triangles', 0) for m in env_stats)}",
            "material_slots": "1 shared atlas per family (walls share wall_dungeon_texture.png)",
            "textures": {"channels": ["albedo"], "note": "1024x1024 shared atlas"},
            "rig": {"skinned": False, "joints": 0, "clips": []},
            "collision": "none (generated in castle_builder)", "lods": "none",
            "acceptance": "docs/baseline-captures/baseline-castle-exterior.png, tools/downloads/asset-review-surfaces-neutral.png",
        })

    # loose asset files that would otherwise be in no entry
    char_tex = [t["path"] for t in audit["textures"] if t["path"].startswith("assets/models/characters/")
                and t["path"].endswith(".png") and ".import" not in t["path"]]
    if char_tex:
        assets.append({
            "id": "family-kaykit-character-textures", "purpose": "KayKit character texture atlases (mage and variant sprites)",
            "status": "candidate", "author": "KayKit (Kay Lousberg)", "source_url": "assets/ASSET_CREDITS.md",
            "license": "CC0 1.0", "license_url": "assets/ASSET_CREDITS.md", "license_file": "assets/models/KayKit-LICENSE.txt",
            "attribution_required": False, "local_paths": char_tex,
            "sha256": {t["path"]: t.get("sha256", "") for t in audit["textures"] if t["path"] in char_tex},
            "scale_m": "n/a", "triangles": "n/a", "material_slots": "n/a",
            "textures": {"channels": ["albedo"], "note": "; ".join(sorted({f"{t.get('width')}x{t.get('height')}" for t in audit['textures'] if t['path'] in char_tex}))},
            "rig": {}, "collision": "n/a", "lods": "n/a", "acceptance": "",
        })
    mon_tex = [t["path"] for t in audit["textures"] if t["path"].startswith("assets/models/monsters/") and t["path"].endswith(".png")]
    if mon_tex:
        assets.append({
            "id": "family-monster-atlases", "purpose": "Quaternius monster atlas textures (Godot glTF import extraction artifacts)",
            "status": "integrated", "author": "Quaternius", "source_url": "assets/models/monsters/License.txt",
            "license": "CC0 1.0", "license_url": "assets/models/monsters/License.txt", "license_file": "assets/models/monsters/License.txt",
            "attribution_required": False, "local_paths": mon_tex,
            "sha256": {t["path"]: t.get("sha256", "") for t in audit["textures"] if t["path"] in mon_tex},
            "scale_m": "n/a", "triangles": "n/a", "material_slots": "n/a",
            "textures": {"channels": ["albedo"], "note": "1024x1024; extracted from the source GLTFs at import"},
            "rig": {}, "collision": "n/a", "lods": "n/a", "acceptance": "",
        })
    brand = [t["path"] for t in audit["textures"] if t["path"].startswith("assets/branding/")]
    if brand:
        assets.append({
            "id": "family-branding", "purpose": "HPMMO banner and logo",
            "status": "integrated", "author": "original work", "source_url": "assets/ASSET_CREDITS.md",
            "license": "original work", "license_url": "assets/ASSET_CREDITS.md", "license_file": "",
            "attribution_required": False, "local_paths": brand,
            "sha256": {t["path"]: t.get("sha256", "") for t in audit["textures"] if t["path"] in brand},
            "scale_m": "n/a", "triangles": "n/a", "material_slots": "n/a",
            "textures": {"channels": ["albedo"], "note": "menu banner (used) + unused logo"},
            "rig": {}, "collision": "n/a", "lods": "n/a", "acceptance": "",
        })

    # texture families
    castle_tex = [t["path"] for t in audit["textures"] if t["path"].startswith("assets/textures/") and t["path"].endswith(".png")]
    if castle_tex:
        assets.append({
            "id": "family-castle-baked-textures", "purpose": "castle colour textures (256px)",
            "status": "placeholder", "author": "original (tools/generate_assets.gd)", "source_url": "tools/generate_assets.gd",
            "license": "original work", "license_url": "assets/ASSET_CREDITS.md", "license_file": "",
            "attribution_required": False, "local_paths": castle_tex,
            "sha256": {t["path"]: t.get("sha256", "") for t in audit["textures"] if t["path"] in castle_tex},
            "scale_m": "n/a", "triangles": "n/a", "material_slots": "n/a",
            "textures": {"channels": ["albedo"], "note": "256x256; referenced by no code (dead); replaced in Phase 10"},
            "rig": {"skinned": False, "joints": 0, "clips": []}, "collision": "n/a", "lods": "n/a",
            "acceptance": "docs/baseline-captures/baseline-castle-exterior.png (current look)",
        })
    env_palette = [t["path"] for t in audit["textures"] if "models/environment" in t["path"]]
    if env_palette:
        assets.append({
            "id": "family-environment-palette-textures", "purpose": "KayKit palette textures (all byte-identical 1024px swatches)",
            "status": "placeholder", "author": "KayKit", "source_url": "assets/ASSET_CREDITS.md",
            "license": "CC0 1.0", "license_url": "assets/ASSET_CREDITS.md", "license_file": "",
            "attribution_required": False, "local_paths": env_palette,
            "sha256": {t["path"]: t.get("sha256", "") for t in audit["textures"] if t["path"] in env_palette},
            "scale_m": "n/a", "triangles": "n/a", "material_slots": "n/a",
            "textures": {"channels": ["albedo"], "note": "44 files, single distinct MD5 (flat swatches)"},
            "rig": {"skinned": False, "joints": 0, "clips": []}, "collision": "n/a", "lods": "n/a",
            "acceptance": "",
        })
    vfx_stills = [t["path"] for t in audit["textures"] if t["path"].startswith("assets/vfx/")]
    if vfx_stills:
        assets.append({
            "id": "vfx-kenney-stills", "purpose": "shared particle stills (flame, spark)",
            "status": "integrated", "author": "Kenney", "source_url": "https://kenney.nl/assets/particle-pack",
            "license": "CC0 1.0", "license_url": "https://kenney.nl/assets/particle-pack",
            "license_file": "assets/vfx/Kenney-License.txt", "attribution_required": False,
            "local_paths": vfx_stills,
            "sha256": {t["path"]: t.get("sha256", "") for t in audit["textures"] if t["path"] in vfx_stills},
            "scale_m": "n/a", "triangles": "n/a", "material_slots": "n/a",
            "textures": {"channels": ["albedo (alpha)"], "note": "512x512 indexed PNG"},
            "rig": {"skinned": False, "joints": 0, "clips": []}, "collision": "n/a", "lods": "n/a",
            "acceptance": "tools/downloads/asset-review-neutral-fire-current.png",
        })

    # --- researched candidates ---------------------------------------------------
    ACCEPTANCE = {
        "quaternius-adventurer-male": ["tools/downloads/asset-review-neutral-hero-adventurer.png", "tools/downloads/asset-review-final-hero-adventurer.png"],
        "quaternius-hooded-adventurer": ["tools/downloads/asset-review-neutral-hero-hooded.png", "tools/downloads/asset-review-final-hero-hooded.png"],
        "quaternius-universal-animation-library": ["tools/downloads/asset-review-neutral-hero-mannequin.png"],
        "quaternius-easy-enemies-spider-glb": ["tools/downloads/asset-review-neutral-spider-candidate.png", "tools/downloads/asset-review-final-spider-candidate.png"],
        "stone-brick-wall-001": ["tools/downloads/asset-review-neutral-wall-pbr.png", "tools/downloads/asset-review-surfaces-final.png"],
        "para-animated-particle-fx-1": ["tools/downloads/asset-review-neutral-fire-flipbook.png"],
    }
    for cid, src in sorted(sources.items()):
        dirs = CURATED.get(cid, [])
        files = []
        for d in dirs:
            full = os.path.join(ROOT, d.replace("/", os.sep))
            if os.path.isdir(full):
                files.extend(walk_files(full))
        if not files:
            # Researched but not curated (rejected / blocked / manual): recorded
            # in tools/candidate_sources.json and the rejected list, not here.
            continue
        hashes = {}
        for f in files:
            fp = os.path.join(ROOT, f.replace("/", os.sep))
            try:
                hashes[f] = sha256(fp)
            except OSError:
                hashes[f] = ""
        glbs = [audit_by_path[f] for f in files if f in audit_by_path and f.endswith((".glb", ".gltf"))]
        pngs = [audit_by_path[f] for f in files if f in audit_by_path and f.endswith((".png", ".jpg"))]
        rig = {"skinned": False, "joints": 0, "clips": []}
        tris = None
        scale = None
        if glbs:
            g = glbs[0]
            rig = {"skinned": g.get("skins", 0) > 0, "joints": g.get("joints", 0), "clips": [a["name"] for a in g.get("animations", [])]}
            total_tris = sum(x.get("triangles", 0) for x in glbs)
            if len(glbs) > 1:
                mn = min(x.get("triangles", 0) for x in glbs)
                mx = max(x.get("triangles", 0) for x in glbs)
                tris = f"{total_tris} total across {len(glbs)} models (per-model {mn}-{mx})"
            else:
                tris = total_tris
            scale = g.get("bbox_size_m")
        audio_count = sum(1 for f in files if f.endswith((".ogg", ".wav", ".flac", ".mp3")))
        dims = None
        if pngs:
            dims = sorted({f"{t.get('width')}x{t.get('height')}" for t in pngs})
        assets.append({
            "id": cid,
            "purpose": PURPOSE.get(cid, src.get("stats", "")[:120]),
            "status": "candidate",
            "author": src.get("author", ""),
            "source_url": src.get("source_url", ""),
            "license": src.get("license", ""),
            "license_url": src.get("license_url", ""),
            "license_file": find_license(files),
            "attribution_required": bool(re.search(r"CC[-\s]?BY", src.get("license", "") or "", re.IGNORECASE)),
            "attribution_text": src.get("attribution_text", ATTRIBUTION_TEXT.get(cid, "")),
            "local_paths": files,
            "sha256": hashes,
            "scale_m": scale if scale else "n/a (textures/audio)" if not glbs else scale,
            "triangles": tris if tris is not None else "n/a",
            "material_slots": ("1 per model" if len(glbs) > 1 else len(glbs[0].get("materials", []))) if glbs else ("n/a (audio)" if audio_count and not pngs else "n/a"),
            "textures": {"channels": texture_channels(files),
                         "note": "; ".join(dims) if dims else ("audio files: %d" % audio_count if audio_count else "")},
            "rig": rig,
            "collision": "none", "lods": "none",
            "scale_source": "automated world AABB incl. headwear/props (tools/asset_audit.py); research-reported character heights are head-top only",
            "import_notes": IMPORT_NOTES.get(cid, ""),
            "verification": {"download_verified": src.get("download_status") == "downloaded",
                             "adversarially_verified": bool(src.get("verified")),
                             "note": src.get("verifier_note", "")},
            "gaps": src.get("gaps", ""),
            "acceptance": ", ".join(ACCEPTANCE.get(cid, [])),
        })

    # --- genuinely missing -------------------------------------------------------
    missing = [
        ("hero_final_art", "textured, clothed grounded-fantasy hero replacing the chibi placeholder", "Phase 9", "candidates: quaternius-adventurer-male, quaternius-universal-animation-library (both untextured); textured originals are manual-download (Google Drive quota / itch 122-280 MB)"),
        ("broom_model", "shaped broom (shaft, grip, bristles) with a seat socket", "Phase 9", "current broom is two cylinder primitives"),
        ("monster_variants_final", "grounded dark-wizard and inferi models matching the hero style", "Phase 11", "Quaternius set is the only existing option; spider candidate obtained"),
        ("vfx_trail_mesh", "camera-aware tapered ribbon mesh for broom/projectile trails", "Phase 12", "author procedurally or in Blender (not installed)"),
        ("vfx_distortion_flow", "distortion/flow data textures for heat haze and shields", "Phase 12", "no free verified source in this pass"),
        ("sfx_room_tone", "interior ambience/room-tone loops (Great Hall, library, dungeon)", "Phase 12.5", "Kenney/oGA candidate pass found no verified CC0 room tones"),
        ("music_beds", "music for menu/exploration/combat", "Phase 12.5", "Kenney jingles are stings only; no long-form beds secured"),
        ("ui_icons", "spell/item/status icons in one style", "Phase 13", "current UI uses text and emoji-ish glyphs"),
        ("character_equipment_variants", "robe/hat/house-colour clothing variants", "Phase 9/13", "requires the final hero first"),
        ("npc_variants", "distinct NPC bodies (professor, shopkeeper, groundskeeper)", "Phase 10+", "NPCs currently share the shared wizard rig"),
    ]
    for mid, purpose, phase, note in missing:
        assets.append({
            "id": mid, "purpose": purpose, "status": "missing", "author": "", "source_url": "",
            "license": "", "license_url": "", "license_file": "", "attribution_required": False,
            "local_paths": [], "sha256": {}, "scale_m": "", "triangles": "", "material_slots": "",
            "textures": {}, "rig": {}, "collision": "", "lods": "",
            "blocks": phase, "notes": note, "acceptance": "",
        })

    summary = {}
    for a in assets:
        summary[a["status"]] = summary.get(a["status"], 0) + 1

    manifest = {
        "schema": 1,
        "generated": str(date.today()),
        "project": "HPMMO",
        "notes": "Phase 2 manifest. Measured fields come from tools/asset_audit.py; license fields were download- and adversarially-verified during Phase 2 research (see docs/art-direction.md section 8). Candidate assets are review-stage: excluded from release packaging until promoted.",
        "summary": summary,
        "assets": assets,
        "rejected": REJECTED,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print(f"wrote {OUT}: {len(assets)} assets, summary={summary}, rejected={len(REJECTED)}")


if __name__ == "__main__":
    main()
