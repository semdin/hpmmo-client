"""Build the spell-effect textures from the generated sources and register them.

Sources (art/vfx/source/, generated with fal.ai - see art/vfx/README.md):
  *.mp4  Wan 3.0 text-to-video clips on a black background -> flipbook atlases
  *.png  Z-Image Turbo stills on black -> single sprites
Procedural stills (hex lattice, scorch decal, energy streak) come from
procedural_textures.py.

For every entry this packs the texture (pack_flipbook.py rules: luminance key,
4 px zero gutter, straight alpha, row-major), installs it under
client/assets/vfx/, rewrites its entry in assets/vfx/metadata.json, and - when
Godot has already imported the file - switches the import to VRAM-compressed
with mipmaps (an uncompressed 2048 sheet is ~21 MB of video memory; the user's
target is an integrated GPU).

  python build_spell_vfx.py --art ../art/vfx --client .
then re-import (godot --headless --path client --import) and run it once more
so the .import tweaks land on the freshly generated .import files.
"""
import argparse, json, os, re, subprocess, sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pack_flipbook as pf
import procedural_textures as pt

# id, source, out (relative to assets/vfx), kind, options, purpose
ATLASES = [
    ("vfx_fire_burst", "fire_burst.mp4", "atlases/fire_burst_8x8_2k.png", {"cell": 256}, "add",
     "Rolling fire burst (Incendio cone, fire impacts)"),
    ("vfx_flame_loop", "flame_loop.mp4", "atlases/flame_loop_8x8_1k.png", {"cell": 128, "loop": True, "inner": 0.95}, "add",
     "Looping flame column (Incendio burn sustain)"),
    ("vfx_smoke_puff", "smoke.mp4", "atlases/smoke_puff_8x8_1k.png", {"cell": 128, "mono": True, "gain": 1.0}, "alpha",
     "White smoke puff, tinted at runtime (ends of fire and blasts)"),
    ("vfx_explosion", "explosion.mp4", "atlases/explosion_8x8_2k.png", {"cell": 256}, "add",
     "Fireball explosion with embers (Bombarda impact)"),
    ("vfx_burst_gold", "gold_burst.mp4", "atlases/burst_gold_8x8_1k.png", {"cell": 128}, "add",
     "Golden sparkle burst (basic attack impact)"),
    ("vfx_burst_red", "red_burst.mp4", "atlases/burst_red_8x8_1k.png", {"cell": 128, "inner": 0.62}, "add",
     "Crimson electric burst (Stupefy impact)"),
    ("vfx_burst_crimson", "crimson_burst.mp4", "atlases/burst_crimson_8x8_1k.png", {"cell": 128, "inner": 0.62}, "add",
     "Magenta spiral vortex (Expelliarmus impact)"),
    ("vfx_burst_green", "green_burst.mp4", "atlases/burst_green_8x8_2k.png", {"cell": 256, "inner": 0.62}, "add",
     "Emerald lightning explosion (Avada Arcana impact)"),
    ("vfx_ripple_blue", "blue_ripple.mp4", "atlases/ripple_blue_8x8_1k.png", {"cell": 128, "inner": 0.7}, "add",
     "Blue force-field ripple ring (Protego cast and deflection)"),
    ("vfx_shockwave", "shockwave.mp4", "atlases/shockwave_8x8_1k.png", {"cell": 128, "mono": True, "inner": 0.85}, "add",
     "Expanding ground shockwave ring, white, tinted and laid flat (blast impacts)"),
    ("vfx_wand_flash", "wand_flash.mp4", "atlases/wand_flash_8x8_1k.png", {"cell": 128, "mono": True, "end": 40}, "add",
     "Muzzle starburst at the wand tip, white, tinted per spell (cast flash)"),
    ("vfx_spark_burst", "spark_burst.mp4", "atlases/spark_burst_8x8_1k.png", {"cell": 128, "mono": True}, "add",
     "Radial spark spray, white, tinted per spell (impact detail)"),
    ("vfx_energy_orb", "energy_orb.mp4", "atlases/energy_orb_8x8_1k.png", {"cell": 128, "mono": True, "loop": True, "start": 0, "end": 44}, "add",
     "Crackling energy orb loop, white, tinted per spell (bolt cores)"),
    ("vfx_fire_orb", "fire_orb.mp4", "atlases/fire_orb_8x8_1k.png", {"cell": 128, "loop": True, "start": 0, "end": 40}, "add",
     "Churning fireball loop (Bombarda bolt core)"),
]

STILLS = [
    ("vfx_rune_seal", "rune_b.png", "tex/rune_seal_512.png", {"size": 512, "mono": True, "inner": 0.95}, "add",
     "Rune seal, white, tinted (stun indicator, ground seals)"),
    ("vfx_star_flare", "flare_a.png", "tex/star_flare_256.png", {"size": 256, "mono": True, "inner": 0.9}, "add",
     "Four-point star sparkle (particle sprite)"),
    ("vfx_lightning_strands", "lightning_a.png", "tex/lightning_strands_512.png", {"size": 512, "mono": True, "inner": 0.92}, "add",
     "Branching lightning strands, white, tinted (Stupefy / Avada Arcana crackle)"),
]

PROCEDURAL = [
    ("vfx_hex_shield", "hex_shield_512.png", "tex/hex_shield_512.png", "add",
     "Tileable hex lattice in alpha (Protego shell)", pt.hex_shield),
    ("vfx_scorch_decal", "scorch_decal_512.png", "tex/scorch_decal_512.png", "alpha",
     "Ground scorch decal (blast aftermath)", pt.scorch),
    ("vfx_energy_streak", "energy_streak_1024x256.png", "tex/energy_streak_1024x256.png", "add",
     "Tapered energy streak (bolt ribbons, broom trail)", pt.streak),
]

GENERATOR = "client/tools/vfx/build_spell_vfx.py"


def pack_args(mode, src, out, opts):
    return SimpleNamespace(mode=mode, src=src, out=out, grid=[8, 8], cell=int(opts.get("cell", 128)),
                           size=int(opts.get("size", 512)), start=opts.get("start"), end=opts.get("end"),
                           fps=opts.get("fps"), loop=bool(opts.get("loop", False)), gain=float(opts.get("gain", 1.25)),
                           floor=float(opts.get("floor", 0.06)), inner=float(opts.get("inner", 0.72)),
                           mono=bool(opts.get("mono", False)), tile=bool(opts.get("tile", False)))


def entry_for(vid, rel, packed, blend, purpose, source, method):
    cols, rows, cell = packed["cols"], packed["rows"], packed["cell"]
    from PIL import Image
    return {
        "id": vid, "file": rel, "path": rel,
        "cols": cols, "rows": rows, "cell": cell, "frames": packed["frames"],
        "fps": packed.get("fps", 0), "loop": packed["loop"], "colour": True,
        "blend": blend, "blend_default": blend, "purpose": purpose,
        "sheet_px": [cols * cell, rows * cell], "cell_px": cell, "padding_px": pf.PAD,
        "frame_order": "row-major, frame 0 at the top-left cell",
        "alpha": "straight (non-premultiplied); coverage in A, linear",
        "colour_space": "sRGB (RGB), linear (A)",
        "generator": GENERATOR, "source": source, "method": method,
        "note": ("Generated on a pure black background; luminance is the coverage, colour is un-premultiplied. "
                 + ("White colour: tinted per spell at runtime. " if packed.get("colour") is False else "")
                 + ("Loop: the tail crossfades into the head." if packed["loop"] else "One-shot: ends on an empty frame.")),
    }


def tune_import(path):
    imp = path + ".import"
    if not os.path.exists(imp):
        return False
    text = open(imp, encoding="utf-8").read()
    new = re.sub(r"compress/mode=\d", "compress/mode=2", text)
    new = re.sub(r"mipmaps/generate=\w+", "mipmaps/generate=true", new)
    if new != text:
        open(imp, "w", encoding="utf-8", newline="\n").write(new)
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", required=True)
    ap.add_argument("--client", required=True)
    args = ap.parse_args()
    src_dir = os.path.join(args.art, "source")
    vfx_dir = os.path.join(args.client, "assets", "vfx")
    meta_path = os.path.join(vfx_dir, "metadata.json")
    meta = json.load(open(meta_path, encoding="utf-8"))
    by_id = {e["id"]: e for e in meta.get("assets", [])}
    tuned = 0
    for vid, src, rel, opts, blend, purpose in ATLASES:
        out = os.path.join(vfx_dir, rel)
        packed = pf.pack_video(pack_args("video", os.path.join(src_dir, src), out, opts))
        packed["colour"] = not opts.get("mono", False)
        by_id[vid] = entry_for(vid, rel, packed, blend, purpose,
                               "fal.ai alibaba/wan-3.0/text-to-video -> art/vfx/source/" + src, "generated video, packed")
        tuned += tune_import(out)
        print("atlas", vid, rel, packed["fps"], "fps")
    for vid, src, rel, opts, blend, purpose in STILLS:
        out = os.path.join(vfx_dir, rel)
        packed = pf.pack_still(pack_args("still", os.path.join(src_dir, src), out, opts))
        packed["colour"] = not opts.get("mono", False)
        by_id[vid] = entry_for(vid, rel, packed, blend, purpose,
                               "fal.ai fal-ai/z-image/turbo -> art/vfx/source/" + src, "generated still, packed")
        tuned += tune_import(out)
        print("still", vid, rel)
    for vid, name, rel, blend, purpose, fn in PROCEDURAL:
        out = os.path.join(vfx_dir, rel)
        img = fn()
        pt.save(img, out)
        h, w = img.shape[:2]
        packed = {"cols": 1, "rows": 1, "cell": w, "frames": 1, "loop": False}
        e = entry_for(vid, rel, packed, blend, purpose, "procedural", "client/tools/vfx/procedural_textures.py (seeded)")
        e["sheet_px"] = [w, h]
        by_id[vid] = e
        tuned += tune_import(out)
        print("procedural", vid, rel)
    meta["assets"] = list(by_id.values())
    meta["generator"] = GENERATOR + " (spell effects); tools/blender/spell_vfx.py (noise fields, legacy masks)"
    meta["generated"] = "2026-10-16"
    meta["temporal_method"] = ("generated clips: consecutive frames of one continuous video sampled evenly over the "
                               "effect's active span (no independent stills); looping atlases crossfade their tail into "
                               "their head. Frames are ordered row-major and must be played in that order.")
    with open(meta_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1)
        fh.write("\n")
    print("metadata: %d assets; %d import files switched to VRAM compression" % (len(meta["assets"]), tuned))


if __name__ == "__main__":
    main()
