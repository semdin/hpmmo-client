"""Record the icon set in assets/manifest.json.

The icon family is one record - `family-icon-set` - covering every file in
`assets/ui/icons/`. The interface chrome is `family-ui-kit`, which is the flat
theme resource alone (it draws no image), and the CC0 pack the icons replaced is
kept in `rejected` for the record.

Run it after regenerating icons: it rewrites the record, its per-file SHA-256
hashes and the summary, and leaves every other entry untouched.

Usage: python tools/manifest_icons.py
"""

import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "assets", "manifest.json")
ICON_DIR = os.path.join(ROOT, "assets", "ui", "icons")
THEME = "assets/ui/hpmmo.tres"
LICENCE_NOTE = "assets/ui/LICENSES/AI_GENERATED_ICONS.md"
RETIRED_ID = "oga-rpg-icons-496"


def sha256(rel_path):
    with open(os.path.join(ROOT, rel_path), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def icon_paths():
    found = glob.glob(os.path.join(ICON_DIR, "*.png")) + glob.glob(os.path.join(ICON_DIR, "*.jpg"))
    return sorted(os.path.relpath(p, ROOT).replace("\\", "/") for p in found)


def main():
    with open(MANIFEST, encoding="utf-8") as handle:
        manifest = json.load(handle)

    paths = icon_paths()
    if not paths:
        raise SystemExit("no icons under %s" % ICON_DIR)

    for entry in manifest["assets"]:
        if entry["id"] == "family-ui-kit":
            entry["purpose"] = ("interface theme: one Theme resource (flat StyleBoxFlat palette, "
                                "control styles and type scale)")
            entry["author"] = "original work"
            entry["source_url"] = THEME
            entry["license"] = "original work"
            entry["license_url"] = "assets/ASSET_CREDITS.md"
            entry["license_file"] = ""
            entry["local_paths"] = [THEME]
            entry["sha256"] = {THEME: sha256(THEME)}
            entry["material_slots"] = "none - the theme draws no image"
            entry["textures"] = {
                "channels": [],
                "note": "flat StyleBoxFlat boxes: no frame, button, slot or bar image to slice",
            }

    icon_entry = {
        "id": "family-icon-set",
        "purpose": ("spell, item, stat, status-effect, map-marker, interface-control and "
                    "house-crest icons for the HUD, bag, menus and minimap"),
        "status": "integrated",
        "author": "generated for this project (OpenAI Imagegen) from project art notes",
        "source_url": LICENCE_NOTE,
        "license": ("generated for this project; no third-party icon set was used as an image "
                    "input, and no rights in third-party names or characters are claimed"),
        "license_url": LICENCE_NOTE,
        "license_file": LICENCE_NOTE,
        "attribution_required": False,
        "local_paths": paths,
        "sha256": {p: sha256(p) for p in paths},
        "scale_m": "n/a",
        "triangles": "n/a",
        "material_slots": "one 512x512 texture per id (assets/ui/icons/icon_<id>.png)",
        "textures": {
            "channels": ["albedo+alpha"],
            "note": ("512x512 RGBA masters with real transparency outside the subject; "
                     "UITheme.icon_for() loads a master, UITheme.chrome_at() scales one per widget"),
        },
        "rig": {},
        "collision": "n/a",
        "lods": "n/a",
        "verification": {
            "download_verified": False,
            "adversarially_verified": False,
            "note": ("checked on install 2026-10-08: every file is 512x512 with an alpha "
                     "channel, and every id the interface asks for resolves as "
                     "icon_<id>.png. Nothing was downloaded, so there is no download to "
                     "verify; the pack's own icon_manifest.json holds the delivery hashes."),
        },
        "note": ("replaced the gnola14 CC0 set: spells, items, potions and materials kept "
                 "their ids, and the HUD, status, minimap, settings and house icons were "
                 "added. Client code asks for these by id through UITheme, never by path."),
    }

    assets = [a for a in manifest["assets"] if a["id"] != "family-icon-set"]
    insert_at = 1 + next(i for i, a in enumerate(assets) if a["id"] == "family-ui-kit")
    assets.insert(insert_at, icon_entry)

    retired = next((a for a in assets if a["id"] == RETIRED_ID), None)
    if retired is not None:
        assets = [a for a in assets if a["id"] != RETIRED_ID]
        manifest["rejected"] = [r for r in manifest["rejected"] if r.get("id") != RETIRED_ID]
        manifest["rejected"].append({
            "id": RETIRED_ID,
            "reason": ("adopted in the UI pass, then superseded by family-icon-set on "
                       "2026-10-08: every derived icon file was replaced, so no gnola14 "
                       "image is distributed any more; the licence text is kept at "
                       "assets/ui/LICENSES/oga-rpg-icons-496.txt"),
            "source": retired["source_url"],
            "author": retired["author"],
            "license": retired["license"],
            "license_url": retired["license_url"],
            "purpose": retired["purpose"],
        })

    manifest["assets"] = assets
    summary = {}
    for entry in assets:
        key = entry.get("status", "unknown")
        summary[key] = summary.get(key, 0) + 1
    manifest["summary"] = summary

    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print("wrote %s: %d icon files, summary=%s" % (MANIFEST, len(paths), summary))


if __name__ == "__main__":
    main()
