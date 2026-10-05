#!/usr/bin/env python3
"""Phase 14 D14-2, step 2: cache-eviction proof and fix A/B in the scratch tree.

Applied ON TOP of phase14_instr_patch.py (which adds the XINSTR timings).

  --pre   print ResourceLoader.has_cached() *before* each texture load, so the
          question "is the cache cold, or is a cached load just slow?" is
          answered by the engine itself rather than by inference
  --fix   hold every loaded VFX texture (and mesh scene) in a static dictionary
          for the process lifetime - the candidate fix, measured in the scratch
          copy only, never in the live tree

Usage: python client/tools/phase14_instr_patch2.py --pre|--fix
"""
import sys
from pathlib import Path

TREE = Path(r"C:/Users/mehme/hpmmo-measure/client-instr")
SPELL_EFFECT = TREE / "scripts/spells/spell_effect.gd"

mode = sys.argv[1] if len(sys.argv) > 1 else "--pre"
text = SPELL_EFFECT.read_text(encoding="utf-8")
if "XINSTR2" in text:
    raise SystemExit("already patched with step 2")

if mode == "--pre":
    old = """	if texture_path != "":
		var texture: Texture2D = load(texture_path)"""
    new = """	if texture_path != "":
		var x_cached_before := ResourceLoader.has_cached(texture_path) # XINSTR2
		var texture: Texture2D = load(texture_path)
		print("XCACHE f=%d path=%s before=%s after=%s us=%d" % [Engine.get_process_frames(), texture_path, str(x_cached_before), str(ResourceLoader.has_cached(texture_path)), Time.get_ticks_usec() - x_m1]) # XINSTR2"""
elif mode == "--fix":
    old = """	if texture_path != "":
		var texture: Texture2D = load(texture_path)"""
    new = """	if texture_path != "":
		var texture: Texture2D # XINSTR2
		if _x_tex_cache.has(texture_path): # XINSTR2
			texture = _x_tex_cache[texture_path] # XINSTR2
		else: # XINSTR2
			texture = load(texture_path) # XINSTR2
			_x_tex_cache[texture_path] = texture # XINSTR2"""
else:
    raise SystemExit("pick --pre or --fix")

if old not in text:
    raise SystemExit("anchor not found / step 1 not applied")
text = text.replace(old, new, 1)

# The static caches (declared once, above _ready).
anchor = "var _layers: Array = []"
if anchor not in text:
    raise SystemExit("cache anchor not found")
text = text.replace(anchor,
    "var _layers: Array = []\n"
    "static var _x_tex_cache := {} # XINSTR2\n"
    "static var _x_scene_cache := {} # XINSTR2", 1)

# The mesh-path load too, so the A/B covers every load() in the spawn.
old_mesh = """	var scene: PackedScene = load(VFX.asset_path(String(layer.get("mesh", ""))))"""
new_mesh = """	var x_mpath := VFX.asset_path(String(layer.get("mesh", ""))) # XINSTR2
	var scene: PackedScene # XINSTR2
	if _x_scene_cache.has(x_mpath): # XINSTR2
		scene = _x_scene_cache[x_mpath] # XINSTR2
	else: # XINSTR2
		scene = load(x_mpath) # XINSTR2
		_x_scene_cache[x_mpath] = scene # XINSTR2"""
if old_mesh not in text:
    raise SystemExit("mesh anchor not found")
text = text.replace(old_mesh, new_mesh, 1)

SPELL_EFFECT.write_text(text, encoding="utf-8")
print(f"step 2 ({mode}) applied to {SPELL_EFFECT}")
