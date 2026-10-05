#!/usr/bin/env python3
"""Phase 14 D14-2 diagnosis: instrument a SCRATCH COPY of the client tree.

The live tree must not be edited for this task, so the instrumentation lives in
a throwaway copy of the client (default C:/Users/mehme/hpmmo-measure/client-instr).
This script patches spell_effect.gd / skill_fx.gd there to print the wall time of
each step of an effect spawn when a step exceeds a threshold, so the ~100 ms
`play_cast` hitch can be attributed to a line instead of guessed at.

Every print carries `f=<Engine.get_process_frames()>`, the same frame counter the
spike probe records, so a print and a spike frame line up exactly.

Idempotent: refuses to patch a file twice (looks for the marker XINSTR).

Usage: python client/tools/phase14_instr_patch.py [tree]
"""
import sys
from pathlib import Path

TREE = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/mehme/hpmmo-measure/client-instr")
SPELL_EFFECT = TREE / "scripts/spells/spell_effect.gd"
SKILL_FX = TREE / "scripts/spells/skill_fx.gd"


def patch(path: Path, edits):
    text = path.read_text(encoding="utf-8")
    if "XINSTR" in text:
        print(f"already patched: {path}")
        return
    for old, new in edits:
        if old not in text:
            raise SystemExit(f"anchor not found in {path}:\n{old[:120]}")
        if text.count(old) != 1:
            raise SystemExit(f"anchor not unique ({text.count(old)}) in {path}:\n{old[:120]}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print(f"patched: {path}")


patch(SPELL_EFFECT, [
    # --- setup(): time the whole build and each layer -----------------------
    (
        """	var offset := 0.0
	for layer in layers:
		var node := _build_layer(layer, colour)
		if node == null:
			continue""",
        """	var offset := 0.0
	var x_total0 := Time.get_ticks_usec() # XINSTR
	for layer in layers:
		var x_l0 := Time.get_ticks_usec() # XINSTR
		var node := _build_layer(layer, colour)
		var x_ld := Time.get_ticks_usec() - x_l0 # XINSTR
		if x_ld > 2000: # XINSTR
			print("XLAYER f=%d spell=%s stage=%s kind=%s us=%d" % [Engine.get_process_frames(), spell_id, stage, String(layer.get("kind", "")), x_ld]) # XINSTR
		if node == null:
			continue""",
    ),
    (
        """	if follow_target == null and bool(_stage_data().get("loop_audio", false)) == false:
		# a travel stage without a follow target still needs an owner: keep it
		# alive for the projectile's flight estimate instead of one frame
		if stage == "travel":
			_duration = maxf(_duration, 2.5)""",
        """	if follow_target == null and bool(_stage_data().get("loop_audio", false)) == false:
		# a travel stage without a follow target still needs an owner: keep it
		# alive for the projectile's flight estimate instead of one frame
		if stage == "travel":
			_duration = maxf(_duration, 2.5)
	var x_total := Time.get_ticks_usec() - x_total0 # XINSTR
	if x_total > 2000: # XINSTR
		print("XSETUP f=%d spell=%s stage=%s layers=%d us=%d" % [Engine.get_process_frames(), spell_id, stage, layers.size(), x_total]) # XINSTR""",
    ),
    # --- _material_for(): shader load vs texture load -----------------------
    (
        """	var additive := String(layer.get("blend", "alpha")) == "add"
	var material := ShaderMaterial.new()
	material.shader = load(SHADER_ADD if additive else SHADER_ALPHA)""",
        """	var additive := String(layer.get("blend", "alpha")) == "add"
	var x_m0 := Time.get_ticks_usec() # XINSTR
	var material := ShaderMaterial.new()
	material.shader = load(SHADER_ADD if additive else SHADER_ALPHA)
	var x_m1 := Time.get_ticks_usec() # XINSTR""",
    ),
    (
        """	if texture_path != "":
		var texture: Texture2D = load(texture_path)
		material.set_shader_parameter("atlas", texture)""",
        """	if texture_path != "":
		var texture: Texture2D = load(texture_path)
		var x_m2 := Time.get_ticks_usec() # XINSTR
		if x_m2 - x_m1 > 1000: # XINSTR
			print("XLOADTEX f=%d path=%s us=%d" % [Engine.get_process_frames(), texture_path, x_m2 - x_m1]) # XINSTR
		material.set_shader_parameter("atlas", texture)""",
    ),
    # --- _build_particles(): process/draw material and buffer creation ------
    (
        """func _build_particles(layer: Dictionary, colour: Color) -> Node3D:
	var particles := GPUParticles3D.new()""",
        """func _build_particles(layer: Dictionary, colour: Color) -> Node3D:
	var x_p0 := Time.get_ticks_usec() # XINSTR
	var particles := GPUParticles3D.new()""",
    ),
    (
        """	particles.process_material = process
	add_child(particles)""",
        """	particles.process_material = process
	var x_p1 := Time.get_ticks_usec() # XINSTR
	add_child(particles)""",
    ),
    (
        """	particles.emitting = true
	return particles""",
        """	particles.emitting = true
	var x_p2 := Time.get_ticks_usec() # XINSTR
	if x_p2 - x_p0 > 2000: # XINSTR
		print("XPARTICLES f=%d tex=%s amount=%d build_us=%d add_us=%d emit_us=%d" % [Engine.get_process_frames(), String(layer.get("tex", "")), particles.amount, x_p1 - x_p0, x_p2 - x_p1, Time.get_ticks_usec() - x_p2]) # XINSTR
	return particles""",
    ),
    # --- _build_mesh_layer(): scene load vs instantiate ---------------------
    (
        """func _build_mesh_layer(layer: Dictionary, colour: Color) -> Node3D:
	var scene: PackedScene = load(VFX.asset_path(String(layer.get("mesh", ""))))""",
        """func _build_mesh_layer(layer: Dictionary, colour: Color) -> Node3D:
	var x_mesh0 := Time.get_ticks_usec() # XINSTR
	var scene: PackedScene = load(VFX.asset_path(String(layer.get("mesh", ""))))
	var x_meshload := Time.get_ticks_usec() - x_mesh0 # XINSTR""",
    ),
    (
        """	if bool(layer.get("follow", false)) and follow_target != null:
		root.top_level = false
		global_position = follow_target.global_position
	return root""",
        """	if bool(layer.get("follow", false)) and follow_target != null:
		root.top_level = false
		global_position = follow_target.global_position
	var x_meshtotal := Time.get_ticks_usec() - x_mesh0 # XINSTR
	if x_meshtotal > 2000: # XINSTR
		print("XMESH f=%d mesh=%s amount=%d load_us=%d total_us=%d" % [Engine.get_process_frames(), String(layer.get("mesh", "")), amount, x_meshload, x_meshtotal]) # XINSTR
	return root""",
    ),
    # --- _ready(): the audio start -----------------------------------------
    (
        """	_audio_key = _resolve_audio()
	if _audio_key != "" and has_node("/root/AudioManager"):""",
        """	_audio_key = _resolve_audio()
	var x_a0 := Time.get_ticks_usec() # XINSTR
	if _audio_key != "" and has_node("/root/AudioManager"):""",
    ),
    (
        """		_audio_started.append(_audio_key)""",
        """		_audio_started.append(_audio_key)
	var x_ad := Time.get_ticks_usec() - x_a0 # XINSTR
	if x_ad > 2000: # XINSTR
		print("XAUDIO f=%d key=%s us=%d" % [Engine.get_process_frames(), _audio_key, x_ad]) # XINSTR""",
    ),
])

patch(SKILL_FX, [
    (
        """	var effect: Node3D = SpellEffect.new()
	world.add_child(effect)
	effect.call("setup", spell_id, stage, quality(), origin, safe_direction(dir), caster, opts)""",
        """	var x_s0 := Time.get_ticks_usec() # XINSTR
	var effect: Node3D = SpellEffect.new()
	var x_s1 := Time.get_ticks_usec() # XINSTR
	world.add_child(effect)
	var x_s2 := Time.get_ticks_usec() # XINSTR
	effect.call("setup", spell_id, stage, quality(), origin, safe_direction(dir), caster, opts)
	var x_s3 := Time.get_ticks_usec() # XINSTR
	if x_s3 - x_s0 > 2000: # XINSTR
		print("XSPAWN f=%d spell=%s stage=%s new_us=%d add_us=%d setup_us=%d total_us=%d" % [Engine.get_process_frames(), spell_id, stage, x_s1 - x_s0, x_s2 - x_s1, x_s3 - x_s2, x_s3 - x_s0]) # XINSTR""",
    ),
])
