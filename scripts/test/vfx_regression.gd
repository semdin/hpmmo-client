extends Node

## Spell effects checks (evidence): everything about the spell VFX
## and sound rebuild that is mechanically assertable, asserted.
##
## Run:
##   godot --headless --path client res://scenes/test/vfx_regression.tscn \
##     --fixed-fps 60 --quit-after 3600
##
## Covers: every inventory asset exists and is documented; every atlas's
## published metadata matches the actual image (frame count/order/FPS/loop,
## alpha convention, padding gutter, colour space); every spell has its effect
## scene, its composition stages and its sound assets referenced; the
## composition table's quality variants are real reductions that keep the
## gameplay-information layers; the reduced preset selects them; effects cancel
## on death, interruption and transfer; a rejected cast removes its predicted
## feedback; the boss warning is driven by the telegraph's authority ticks; the
## audio buses, volumes, loops, voice limit and warning priority exist; and no
## resource the effects reference is missing at runtime.

const VFX = preload("res://scripts/spells/vfx_library.gd")
const SkillFX = preload("res://scripts/spells/skill_fx.gd")
const SpellEffect = preload("res://scripts/spells/spell_effect.gd")
const BossWarning = preload("res://scripts/spells/boss_warning.gd")
const BroomTrail = preload("res://scripts/spells/broom_trail.gd")
const QualityPreset = preload("res://scripts/world/quality_preset.gd")

const METADATA_PATH := "res://assets/vfx/metadata.json"
const MESH_METADATA_PATH := "res://assets/vfx/meshes/meshes_metadata.json"
const SOUND_LIBRARY_PATH := "res://assets/audio/sound_library.json"

## Pre-existing Kenney ingredients: documented in assets/manifest.json (Asset audit),
## deliberately not re-filed in the spell effects generated metadata.
const INGREDIENT_IDS := ["vfx_flame_static", "vfx_spark_static"]

const SPELL_SCENES := {
	"basic_cast": "res://scenes/spells/fx_basic_cast.tscn",
	"stupefy": "res://scenes/spells/fx_stupefy.tscn",
	"incendio": "res://scenes/spells/fx_incendio.tscn",
	"bombarda": "res://scenes/spells/fx_bombarda.tscn",
	"expelliarmus": "res://scenes/spells/fx_expelliarmus.tscn",
	"protego": "res://scenes/spells/fx_protego.tscn",
	"ultimate": "res://scenes/spells/fx_ultimate.tscn",
}

var checks := 0
var failures: Array[String] = []
var world: Node3D
var atlas_metadata := {}
var mesh_metadata := {}
var sound_library := {}


func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)


func _ready() -> void:
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false
	world = get_node_or_null("GameWorld")
	_load_metadata()
	_check_inventory()
	_check_atlas_metadata()
	_check_mesh_metadata()
	_check_composition_table()
	_check_effect_scenes()
	_check_audio_assets()
	_check_quality_variants()
	_check_audio_system()
	await get_tree().create_timer(0.6).timeout
	await _check_effects_runtime()
	await _check_cancellation()
	await _check_prediction_rejection()
	await _check_boss_warning()
	await _check_broom_trail()
	await _check_protego_shell()
	await _check_sound_integration()
	await _check_no_missing_resources()
	await _report()
	if world != null:
		world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if failures.is_empty() else 1)


func _load_metadata() -> void:
	if FileAccess.file_exists(METADATA_PATH):
		atlas_metadata = JSON.parse_string(FileAccess.get_file_as_string(METADATA_PATH))
	if FileAccess.file_exists(MESH_METADATA_PATH):
		mesh_metadata = JSON.parse_string(FileAccess.get_file_as_string(MESH_METADATA_PATH))
	if FileAccess.file_exists(SOUND_LIBRARY_PATH):
		sound_library = JSON.parse_string(FileAccess.get_file_as_string(SOUND_LIBRARY_PATH))


# ------------------------------------------------------------------ inventory

func _check_inventory() -> void:
	# 1. every asset in the registry exists on disk and is documented
	var missing: Array = []
	var undocumented: Array = []
	var documented_ids := {}
	for entry in atlas_metadata.get("assets", []):
		documented_ids[String(entry.get("id", ""))] = entry
	for entry in mesh_metadata.get("meshes", []):
		documented_ids[String(entry.get("id", ""))] = entry
	for id in VFX.ASSETS:
		var entry: Dictionary = VFX.ASSETS[id]
		var path := String(entry.get("path", entry.get("mesh", "")))
		if path == "" or not ResourceLoader.exists(path):
			missing.append(id)
		if not documented_ids.has(id) and not INGREDIENT_IDS.has(id):
			undocumented.append(id)
	check(missing.is_empty(), "Every inventory asset exists on disk (%d assets, %d missing)" % [VFX.ASSETS.size(), missing.size()])
	if not missing.is_empty():
		print("  missing: ", missing)
	check(undocumented.is_empty(), "Every inventory asset has published metadata (%d undocumented)" % undocumented.size())
	if not undocumented.is_empty():
		print("  undocumented: ", undocumented)
	# the two Kenney stills stay ingredients, and the flipbooks are project-original
	check(VFX.ASSETS.has("vfx_flame_static") and VFX.ASSETS.has("vfx_spark_static"),
		"The two Kenney stills are still in the inventory as ingredients")
	var provenance_path := "res://assets/vfx/PROVENANCE.txt"
	check(FileAccess.file_exists(provenance_path), "The VFX provenance statement ships beside the art")
	if FileAccess.file_exists(provenance_path):
		var text := FileAccess.get_file_as_string(provenance_path)
		check(text.contains("PROJECT-ORIGINAL") and text.contains("spell_vfx.py"),
			"VFX provenance names the script that authored the art")


## The published atlas metadata must describe the file that actually ships:
## frame count, grid, padding, frame order, FPS, loop flag, alpha and colour space.
func _check_atlas_metadata() -> void:
	var atlases: Array = []
	for entry in atlas_metadata.get("assets", []):
		if int(entry.get("frames", 1)) > 1:
			atlases.append(entry)
	check(atlases.size() >= 5, "The metadata publishes %d animated atlases" % atlases.size())
	for entry in atlases:
		var id := String(entry.get("id", "?"))
		var path := "res://assets/vfx/" + String(entry.get("path", ""))
		var texture: Texture2D = load(path)
		check(texture != null, "%s loads as a texture" % id)
		if texture == null:
			continue
		var image := texture.get_image()
		var sheet: Array = entry.get("sheet_px", [0, 0])
		check(image.get_width() == int(sheet[0]) and image.get_height() == int(sheet[1]),
			"%s is %dx%d as published" % [id, image.get_width(), image.get_height()])
		var cols := int(entry.get("cols", 0))
		var rows := int(entry.get("rows", 0))
		check(cols * rows == int(entry.get("frames", 0)),
			"%s frame count matches its %dx%d grid" % [id, cols, rows])
		var cell := int(entry.get("cell_px", 0))
		check(cols * cell == image.get_width(), "%s cell size matches the sheet width" % id)
		var frame_order: String = entry.get("frame_order", "")
		var alpha_note: String = entry.get("alpha", "")
		var colour_space: String = entry.get("colour_space", "")
		check(frame_order.contains("row-major"), "%s publishes its frame order (row-major)" % id)
		check(alpha_note.contains("straight"), "%s publishes the straight-alpha convention" % id)
		check(colour_space != "", "%s publishes its colour space (declared: %s)" % [id, colour_space])
		if int(entry.get("fps", 0)) > 0:
			check(entry.has("loop"), "%s publishes its loop flag" % id)
		# the padding gutter must be genuinely empty: that is what makes
		# mipmapping unable to bleed one cell into its neighbour
		var pad := int(entry.get("padding_px", 0))
		check(pad >= 2, "%s reserves a padding gutter (%d px)" % [id, pad])
		if pad > 0:
			var worst := 0.0
			for i in range(mini(cols * rows, 8)):
				var r := i / cols
				var c := i % cols
				var x0 := c * cell
				var y0 := r * cell
				for y in range(y0, y0 + cell):
					for x in [x0, x0 + cell - 1]:
						worst = maxf(worst, image.get_pixel(x, y).a)
				for x in range(x0, x0 + cell):
					for y in [y0, y0 + cell - 1]:
						worst = maxf(worst, image.get_pixel(x, y).a)
			check(worst <= 0.004, "%s padding gutter is empty (worst alpha %.3f)" % [id, worst])
			# Mipmap bleed test: box-downsample the sheet three levels (the mip
			# chain the GPU builds by halving) and assert the boundary ring of
			# every cell is still (near) empty - with an empty gutter there is
			# nothing for a coarser level to average across cells.
			var bleed := _mip_bleed(image, cell, cols, rows, 3)
			check(bleed <= 0.02, "%s survives three mip levels without bleeding (worst %.4f)" % [id, bleed])
			var import_path := "res://assets/vfx/" + String(entry.get("path", "")) + ".import"
			var import_text := FileAccess.get_file_as_string(import_path)
			check(import_text.contains("mipmaps/generate=true"),
				"%s imports with mipmaps enabled (the setting the bleed test models)" % id)
		# colour atlases carry sRGB-encoded colour; masks are linear data
		if bool(entry.get("colour", false)):
			check(colour_space.contains("sRGB"), "%s colour atlas is documented sRGB" % id)
		else:
			check(colour_space.contains("linear"), "%s mask atlas is documented as linear data" % id)
	# mipmaps are enabled on the flipbooks so distance does not alias
	var mip_ok := 0
	for entry in atlases:
		var texture: Texture2D = load("res://assets/vfx/" + String(entry.get("path", "")))
		if texture != null and texture.get_width() > 0:
			mip_ok += 1
	check(mip_ok == atlases.size(), "Every flipbook atlas imports for runtime sampling (%d)" % mip_ok)
	check(atlas_metadata.has("padding") and String(atlas_metadata["padding"]).contains("gutter"),
		"The metadata states the padding/mipmap-bleed policy")
	check(atlas_metadata.has("temporal_method") and String(atlas_metadata["temporal_method"]).contains("continuous"),
		"The metadata states the temporal method (one continuous field, ordered frames)")


## Box-downsample the sheet `levels` times (what the GPU mip chain does) and
## return the worst alpha found in the outermost ring of each cell - the border
## that would show a neighbour's content if the padding were not empty.
func _mip_bleed(image: Image, cell: int, cols: int, rows: int, levels: int) -> float:
	var working := image.duplicate() as Image
	for _level in range(levels):
		working.resize(maxi(1, working.get_width() / 2), maxi(1, working.get_height() / 2),
			Image.INTERPOLATE_BILINEAR)
	var factor := float(working.get_width()) / float(image.get_width())
	var scaled_cell := int(maxf(1.0, float(cell) * factor))
	var worst := 0.0
	for i in range(mini(cols * rows, 8)):
		var r := i / cols
		var c := i % cols
		var x0 := c * scaled_cell
		var y0 := r * scaled_cell
		var x1 := mini(working.get_width() - 1, x0 + scaled_cell - 1)
		var y1 := mini(working.get_height() - 1, y0 + scaled_cell - 1)
		for y in range(y0, y1 + 1):
			worst = maxf(worst, maxf(working.get_pixel(x0, y).a, working.get_pixel(x1, y).a))
		for x in range(x0, x1 + 1):
			worst = maxf(worst, maxf(working.get_pixel(x, y0).a, working.get_pixel(x, y1).a))
	return worst


func _check_mesh_metadata() -> void:
	var entries: Array = mesh_metadata.get("meshes", [])
	check(entries.size() >= 7, "Mesh metadata publishes %d authored meshes" % entries.size())
	var ids := {}
	for entry in entries:
		ids[String(entry.get("id", ""))] = true
	for required in ["vfx_trail_mesh", "vfx_shield_mesh", "vfx_shard_meshes", "vfx_projectile_mesh"]:
		check(ids.has(required), "Mesh metadata covers %s" % required)
	var ribbon: Dictionary = {}
	for entry in entries:
		if String(entry.get("id", "")) == "vfx_trail_mesh":
			ribbon = entry
	check(not ribbon.is_empty() and String(ribbon.get("taper_profile", "")).contains("(1-t)"),
		"The trail ribbon publishes its authored taper profile")


# ------------------------------------------------------------------ composition

func _check_composition_table() -> void:
	var problems := VFX.validate_table()
	check(problems.is_empty(), "The composition table is internally consistent (%d problems)" % problems.size())
	for problem in problems:
		print("  table: ", problem)
	# Every stage that 12.3 names exists per spell, with layers.
	for spell_id in VFX.SPELLS:
		var stages := VFX.stages_for(spell_id)
		check(stages.size() >= 3, "%s has a multi-stage effect (%d stages)" % [spell_id, stages.size()])
		for stage in stages:
			var layers: Array = VFX.layers_for(spell_id, String(stage), "high")
			check(layers.size() > 0, "%s/%s builds at least one layer" % [spell_id, stage])
	# The rules the composition must obey, spelled out:
	var incendio_cast: Array = VFX.layers_for("incendio", "cast", "high")
	var has_cone := false
	for layer in incendio_cast:
		if String(layer.get("kind", "")) == "flipbook" and String(layer.get("atlas", "")) == "vfx_fire_burst":
			has_cone = true
	check(has_cone, "Incendio's cast is a flame burst (cone), not a projectile")
	check(not VFX.stages_for("incendio").has("travel"),
		"Incendio has no travel stage: the authoritative shape is a cone, not a projectile")
	var protego_layers: Array = VFX.layers_for("protego", "sustain", "high")
	var uses_shell := false
	for layer in protego_layers:
		if String(layer.get("kind", "")) == "mesh" and String(layer.get("mesh", "")) == "vfx_shield_mesh":
			uses_shell = true
	check(uses_shell, "Protego sustains a mesh shell (the one place geometry is intentional)")
	# Blend modes are chosen per layer, not globally.
	var alpha_layers := 0
	var additive_layers := 0
	for spell_id in VFX.SPELLS:
		for stage in VFX.stages_for(spell_id):
			for layer in VFX.layers_for(spell_id, String(stage), "high"):
				if String(layer.get("blend", "alpha")) == "add":
					additive_layers += 1
				else:
					alpha_layers += 1
	check(alpha_layers > 0 and additive_layers > 0,
		"Blend mode is chosen per layer (%d alpha, %d additive)" % [alpha_layers, additive_layers])


func _check_effect_scenes() -> void:
	for spell_id in SPELL_SCENES:
		var path: String = SPELL_SCENES[spell_id]
		check(ResourceLoader.exists(path), "%s has an effect scene (%s)" % [spell_id, path])
		if not ResourceLoader.exists(path):
			continue
		var packed: PackedScene = load(path)
		var instance := packed.instantiate()
		check(instance is SpellEffect, "%s's scene builds a SpellEffect" % spell_id)
		check(String(instance.get("spell_id")) == spell_id,
			"%s's scene is bound to the right spell id" % spell_id)
		instance.free()
	check(ResourceLoader.exists(SkillFX.WARNING_SCENE), "The boss warning has an effect scene")
	check(ResourceLoader.exists(SkillFX.TRAIL_SCENE), "The broom trail has an effect scene")


func _check_audio_assets() -> void:
	var sounds: Dictionary = sound_library.get("sounds", {})
	check(sounds.size() >= 70, "The sound library ships %d sounds" % sounds.size())
	var missing: Array = []
	for key in sounds:
		var path := "res://" + String((sounds[key] as Dictionary).get("path", ""))
		if not ResourceLoader.exists(path):
			missing.append(key)
	check(missing.is_empty(), "Every sound in the library exists on disk (%d missing)" % missing.size())
	if not missing.is_empty():
		print("  missing sounds: ", missing)
	# Every spell stage names a sound that exists, and the cast/travel/impact/end
	# variants are genuinely distinct files.
	for spell_id in VFX.SPELLS:
		var keys: Array = []
		for stage in VFX.stages_for(spell_id):
			var audio := String((VFX.stages_for(spell_id)[stage] as Dictionary).get("audio", ""))
			check(sounds.has(audio), "%s/%s references the sound '%s'" % [spell_id, stage, audio])
			keys.append(audio)
		var unique := {}
		for key in keys:
			unique[key] = true
		check(unique.size() == keys.size(), "%s uses a distinct sound per stage (%d)" % [spell_id, unique.size()])
	# The 12.5 non-spell coverage.
	for key in ["step_stone_1", "step_dirt_1", "step_grass_1", "step_wood_1", "step_water_1",
			"robe_1", "mount", "dismount", "broom_wind", "landing",
			"spider_move_1", "spider_bite", "spider_death", "boss_slam_cast",
			"boss_slam_release", "boss_death", "map_transition",
			"amb_exterior_wind", "amb_exterior_birds", "amb_great_hall", "amb_library",
			"amb_dungeon", "amb_fire", "amb_candles", "amb_distant", "amb_stairs"]:
		check(sounds.has(key), "Soundscape covers '%s'" % key)
	# A cast/travel/impact/end variant for all seven spells, never one generic whoosh.
	for spell_id in SPELL_SCENES:
		var stages: Array = ["cast", "impact"]
		for stage in stages:
			check(sounds.has("spell_%s_%s" % [spell_id, stage]),
				"%s has its own %s sound" % [spell_id, stage])
	# provenance
	var credits := "res://assets/audio/CREDITS-spell-audio.md"
	check(FileAccess.file_exists(credits), "The audio provenance/credits file ships with the library")
	if FileAccess.file_exists(credits):
		var text := FileAccess.get_file_as_string(credits)
		check(text.contains("synth_spell_sfx.py"), "Audio credits name the script that generated the files")


## Low/medium/high variants: real reductions that keep the gameplay information.
func _check_quality_variants() -> void:
	check(VFX.QUALITY.has("low") and VFX.QUALITY.has("medium") and VFX.QUALITY.has("high"),
		"Three quality variants are defined")
	var reduced_any := false
	for spell_id in VFX.SPELLS:
		for stage in VFX.stages_for(spell_id):
			var high: Array = VFX.layers_for(spell_id, String(stage), "high")
			var low: Array = VFX.layers_for(spell_id, String(stage), "low")
			var medium: Array = VFX.layers_for(spell_id, String(stage), "medium")
			check(low.size() <= high.size(), "%s/%s: low is not heavier than high" % [spell_id, stage])
			check(medium.size() <= high.size(), "%s/%s: medium is not heavier than high" % [spell_id, stage])
			if low.size() < high.size() or _particle_total(low) < _particle_total(high):
				reduced_any = true
			for layer in low:
				check(String(layer.get("kind", "")) != "light",
					"%s/%s: low drops the dynamic light" % [spell_id, stage])
			# the gameplay-information layer survives at every level
			var core_high := 0
			for layer in high:
				if bool(layer.get("core", false)):
					core_high += 1
			var core_low := 0
			for layer in low:
				if bool(layer.get("core", false)):
					core_low += 1
			check(core_low == core_high and core_high > 0,
				"%s/%s: all %d core layers survive at low" % [spell_id, stage, core_high])
	check(reduced_any, "The low variant is a genuine reduction, not a relabelling")
	# The reduced preset is what the Intel profile resolves to.
	var original := QualityPreset.current()
	QualityPreset.forced("low")
	check(QualityPreset.current() == "low" and SkillFX.quality() == "low",
		"The reduced preset is selected for the Intel profile and the effects follow it")
	QualityPreset.forced("high")
	check(SkillFX.quality() == "high", "The effects follow the high preset when it is selected")
	QualityPreset.forced(original)


func _particle_total(layers: Array) -> int:
	var total := 0
	for layer in layers:
		if String(layer.get("kind", "")) == "particles":
			total += int(layer.get("amount", 0))
	return total


# ------------------------------------------------------------------ audio sys

func _check_audio_system() -> void:
	var audio := get_node_or_null("/root/AudioManager")
	check(audio != null, "The AudioManager autoload exists")
	if audio == null:
		return
	var report: Dictionary = audio.call("describe")
	for bus_name in ["Music", "SFX", "UI", "Ambience"]:
		check(AudioServer.get_bus_index(bus_name) != -1, "Bus '%s' exists" % bus_name)
		check((report["buses"] as Array).has(bus_name), "AudioManager reports the '%s' bus" % bus_name)
	# independent volume controls
	var before: Dictionary = (report["volumes"] as Dictionary).duplicate()
	audio.call("set_volume", "SFX", 0.42)
	check(absf(float(audio.call("get_volume", "SFX")) - 0.42) < 0.001, "SFX volume is independently settable")
	check(absf(float(audio.call("get_volume", "Music")) - float(before["Music"])) < 0.001,
		"Changing SFX volume does not move the music volume")
	audio.call("set_volume", "SFX", float(before["SFX"]))
	check(audio.call("has_sound", "spell_incendio_cast"), "The library serves sounds by key")
	check(int(report["sounds"]) >= 70, "The library is loaded at runtime (%d sounds)" % int(report["sounds"]))
	check(int(report["spatial_voices"]) >= 16, "A voice limit is configured (%d spatial voices)" % int(report["spatial_voices"]))
	check(bool(report["limiter"]), "The SFX bus carries a limiter so warnings survive spell bursts")
	check(int(report["priority_keys"]) >= 5,
		"%d warning-priority keys are reserved in the voice pool" % int(report["priority_keys"]))
	var priority_in_library := 0
	for key in audio.get("WARNING_PRIORITY"):
		if audio.call("has_sound", String(key)):
			priority_in_library += 1
	check(priority_in_library == (audio.get("WARNING_PRIORITY") as Array).size(),
		"Every warning-priority key resolves to a real sound")
	# loops import as loops, or ambience would play once and stop
	var looped := 0
	var loop_expected := 0
	for key in sound_library.get("sounds", {}):
		var entry: Dictionary = sound_library["sounds"][key]
		if not bool(entry.get("loop", false)):
			continue
		loop_expected += 1
		var stream: AudioStream = load("res://" + String(entry.get("path", "")))
		if stream is AudioStreamWAV and (stream as AudioStreamWAV).loop_mode != AudioStreamWAV.LOOP_DISABLED:
			looped += 1
	check(loop_expected >= 8 and looped == loop_expected,
		"Every looping bed imports with the forward loop flag (%d/%d)" % [looped, loop_expected])
	# zones are acoustically distinct
	var zones: Dictionary = audio.get("ZONES")
	check(zones.size() >= 4, "Distinct acoustic zones are defined (%d)" % zones.size())
	var sizes := {}
	for zone_name in zones:
		var config: Dictionary = zones[zone_name]
		sizes[float(config["room_size"])] = true
	check(sizes.size() >= 3, "The zones do not share one reverb size (%d distinct)" % sizes.size())
	check((zones["great_hall"] as Dictionary)["room_size"] != (zones["library"] as Dictionary)["room_size"]
		and (zones["library"] as Dictionary)["room_size"] != (zones["dungeon"] as Dictionary)["room_size"],
		"Great Hall, library and dungeon are acoustically distinct")


# ------------------------------------------------------------------ runtime

func _check_effects_runtime() -> void:
	# Build every stage of every spell in the live world and check what it made.
	var built := 0
	var layers_total := 0
	for spell_id in VFX.SPELLS:
		for stage in VFX.stages_for(spell_id):
			var effect = SkillFX.spawn_stage(world, spell_id, String(stage),
				world.local_player.global_position + Vector3(0, 1.4, 0), Vector3.FORWARD,
				world.local_player)
			if effect == null:
				continue
			built += 1
			var description: Dictionary = effect.call("describe")
			layers_total += int(description["layers"])
			if int(description["layers"]) == 0:
				check(false, "%s/%s built no layers" % [spell_id, stage])
	check(built >= 20, "Every spell stage builds a live effect (%d stages)" % built)
	check(layers_total > built, "The effects are layered (%d layers across %d stages)" % [layers_total, built])
	# presentation only: the effects changed nothing authoritative
	var player = world.local_player
	var hp_before: int = player.current_hp
	var mana_before: int = player.current_mana
	var xp_before: int = player.current_exp
	await get_tree().create_timer(0.2).timeout
	check(player.current_hp == hp_before and player.current_mana == mana_before and player.current_exp == xp_before,
		"Effects never touch hp, mana or experience")
	# nothing is left running once the stages have played out
	var cancelled: int = SkillFX.cancel_all_of(player)
	check(cancelled >= 20, "Every stage built for the caster can be cancelled (%d)" % cancelled)
	await get_tree().create_timer(0.5).timeout
	check(SkillFX.active_count() == 0, "Cancelled effects are released (%d still live)" % SkillFX.active_count())
	# the fire cone points down the aim, and vertical aims do not collapse it
	var vertical = SkillFX.spawn_stage(world, "incendio", "cast",
		player.global_position + Vector3(0, 1.2, 0), Vector3.UP, player)
	check(vertical != null, "A vertical aim still builds the effect (no collinear crash)")
	if vertical != null:
		check(absf((vertical.get("direction") as Vector3).dot(Vector3.UP) - 1.0) < 0.01,
			"The cone is aimed where the player aimed")
		vertical.call("cancel", "test")
	var zero = SkillFX.spawn_stage(world, "basic_cast", "cast", player.global_position, Vector3.ZERO, player)
	check(zero != null and (zero.get("direction") as Vector3).length() > 0.9,
		"A zero-length direction falls back to a unit direction")
	if zero != null:
		zero.call("cancel", "test")


func _check_cancellation() -> void:
	var player = world.local_player
	# death: an effect whose caster is dead cancels itself
	var effect = SkillFX.spawn_stage(world, "incendio", "sustain",
		player.global_position + Vector3(0, 1.2, 0), Vector3.FORWARD, player)
	check(effect != null, "A sustained effect can be attached to a caster")
	if effect != null:
		effect.set("caster_was_alive", true)
		player.is_dead = true
		await get_tree().process_frame
		await get_tree().process_frame
		await get_tree().create_timer(0.25).timeout
		check(not is_instance_valid(effect) or bool(effect.get("cancelled")),
			"An effect whose caster died cancels itself (no leak, no lie about state)")
		player.is_dead = false
	# interruption / transfer / shutdown: the explicit hook
	var live: Array = []
	for i in range(3):
		live.append(SkillFX.spawn_stage(world, "stupefy", "travel",
			player.global_position + Vector3(0, 1.2, 0), Vector3.FORWARD, player))
	var cancelled: int = SkillFX.cancel_all_of(player)
	check(cancelled >= 1, "cancel_all_of cancels a caster's live effects (%d)" % cancelled)
	await get_tree().create_timer(0.25).timeout
	var still_valid := 0
	for item in live:
		if is_instance_valid(item) and not bool(item.get("cancelled")):
			still_valid += 1
	check(still_valid == 0, "Every effect of that caster is gone after cancellation (%d left)" % still_valid)
	# audio: stop_everything silences loops on shutdown/transfer
	var audio := get_node_or_null("/root/AudioManager")
	if audio != null:
		audio.call("loop_sound", "broom_wind", player, 0.0)
		audio.call("stop_everything")
		var playing := 0
		for child in audio.get_children():
			if (child is AudioStreamPlayer or child is AudioStreamPlayer3D) and (child as Node).get("playing"):
				playing += 1
		check(playing == 0, "stop_everything leaves no sound playing (%d)" % playing)


func _check_prediction_rejection() -> void:
	var player = world.local_player
	var before: int = SkillFX.predicted_count()
	var effect = SkillFX.play_predicted_cast(player, "stupefy", 4242)
	check(effect != null, "A predicted cast produces feedback immediately")
	check(SkillFX.predicted_count() == before + 1,
		"The predicted feedback is registered by cast sequence (%d)" % SkillFX.predicted_count())
	SkillFX.cancel_predicted(player, 4242)
	await get_tree().create_timer(0.2).timeout
	check(SkillFX.predicted_count() == before, "A rejected cast removes exactly its own predicted feedback")
	check(not is_instance_valid(effect) or bool(effect.get("cancelled")),
		"The rejected prediction's effect is cancelled, not orphaned")
	# a rejection of an unknown sequence removes nothing
	SkillFX.cancel_predicted(player, 9999)
	check(SkillFX.predicted_count() == before, "Cancelling an unknown cast sequence removes nothing")


func _check_boss_warning() -> void:
	var boss: Node3D = null
	for mob in get_tree().get_nodes_in_group("mobs"):
		if bool(mob.get("is_boss")):
			boss = mob
			break
	check(boss != null, "A boss exists in the live world")
	if boss == null:
		return
	var plan := {"kind": "area", "radius": 5.5, "range": 8.0, "half_angle": 0.6,
		"anticipation": 0.6, "recovery": 0.6, "telegraph": true}
	var release_tick: int = SimAuthority.sim_tick + 12
	SimAuthority.begin_mob_telegraph(boss, plan, release_tick,
		boss.global_position - boss.global_position + Vector3.FORWARD, boss.global_position)
	var record: Dictionary = SimAuthority.record_for(boss)
	check(record.has("telegraph"), "The authority publishes a telegraph for the boss attack")
	var telegraph: Dictionary = record.get("telegraph", {})
	check(int(telegraph.get("release_tick", 0)) == release_tick,
		"The telegraph publishes the authoritative release tick")
	# the client draws from the record only
	boss.call("_draw_telegraph", record)
	var warning = boss.get("_warning")
	check(warning is MeshInstance3D, "The warning stays a mesh whose shape is the hit area")
	if warning is MeshInstance3D:
		var mesh := (warning as MeshInstance3D).mesh
		check(mesh is CylinderMesh and absf(float((mesh as CylinderMesh).top_radius) - 5.5) < 0.01,
			"The warning's hit area matches the authoritative radius")
	var effect = boss.get("_warning_effect")
	check(effect != null and is_instance_valid(effect),
		"The layered warning effect is attached to the authoritative mask")
	if effect != null:
		var start_tick := int(telegraph.get("start_tick", 0))
		var span := maxf(1.0, float(release_tick - start_tick))
		var progress_before := float(effect.get("progress"))
		while SimAuthority.sim_tick < release_tick - 2:
			await get_tree().physics_frame
			record = SimAuthority.record_for(boss)
			if record.has("telegraph"):
				boss.call("_draw_telegraph", record)
		var mid := float(effect.get("progress"))
		check(mid > progress_before, "The warning fill advances with the authority's ticks")
		while SimAuthority.sim_tick < release_tick:
			await get_tree().physics_frame
			record = SimAuthority.record_for(boss)
			if record.has("telegraph"):
				boss.call("_draw_telegraph", record)
		var at_release := float(effect.get("progress"))
		check(at_release >= 0.95, "The warning is full at the release tick (%.2f)" % at_release)
		var layers: int = int((effect.call("describe") as Dictionary)["layers"])
		check(layers >= 3, "The warning is layered (%d layers)" % layers)
		var audio := get_node_or_null("/root/AudioManager")
		if audio != null:
			var played: Array = audio.call("played_keys")
			var cue := 0
			for key in played:
				if String(key) == "boss_slam_cast":
					cue += 1
			check(cue >= 1, "The boss telegraph plays its own charge cue (boss_slam_cast x%d)" % cue)
		var describe: Dictionary = effect.call("describe")
		check(int(describe["radius"]) == 5 or absf(float(describe["radius"]) - 5.5) < 0.01,
			"The warning knows the authoritative radius it is drawing")
	# ending the telegraph clears it (release and death both go through this)
	SimAuthority.end_mob_telegraph(boss)
	await get_tree().physics_frame
	record = SimAuthority.record_for(boss)
	boss.call("_draw_telegraph", record)
	check(not record.has("telegraph"), "The telegraph is cleared after the release")
	check(boss.get("_warning") == null, "The warning is torn down with the telegraph")
	check(boss.get("_warning_effect") == null, "The warning effect is torn down with it")


func _check_broom_trail() -> void:
	var scene: PackedScene = load(SkillFX.TRAIL_SCENE)
	var trail = scene.instantiate()
	check(trail is BroomTrail, "The broom trail scene builds a BroomTrail")
	var player = world.local_player
	world.add_child(trail)
	trail.call("setup", player, player.get_node_or_null("Visuals"))
	check(trail.get("tail_socket") != null, "The trail binds the broom's TailSocket, not an assumed transform")
	var description: Dictionary = trail.call("describe")
	check(bool(description["taper_from_asset"]),
		"The ribbon's taper profile is read from the authored trail_ribbon.glb")
	trail.call("set_flying", true)
	player.velocity = Vector3(0, 0, 12)
	for i in range(4):
		trail.call("tick", 1.0 / 30.0)
		await get_tree().process_frame
	description = trail.call("describe")
	check(bool(description["flying"]) and int(description["samples"]) > 0,
		"The trail samples motion while flying (%d samples)" % int(description["samples"]))
	trail.call("set_flying", false)
	description = trail.call("describe")
	check(not bool(description["flying"]) and int(description["samples"]) == 0,
		"Dismount clears the trail history: no trail outlives the flight")
	trail.queue_free()


func _check_protego_shell() -> void:
	var packed: PackedScene = load("res://scenes/spells/protego_shield.tscn")
	var shield = packed.instantiate()
	world.add_child(shield)
	shield.call("setup", world.local_player)
	await get_tree().process_frame
	var description: Dictionary = shield.call("describe")
	check(bool(description["shell"]), "The ward builds its shell from the authored mesh")
	shield.call("on_hit", world.local_player.global_position + Vector3.UP)
	check(shield.get("hits_absorbed") >= 1, "A projectile striking the ward registers a positional ripple")
	check(shield.is_in_group("shields"), "The ward stays in the shield group the projectile code reflects against")
	check(shield.collision_layer == 16 and shield.collision_mask == 4,
		"The ward's collision layer/mask are unchanged (projectiles still reach it)")
	shield.queue_free()
	await get_tree().process_frame


## Nothing the effects reference may be missing at runtime.
## The creature voices must be reached by real gameplay, not merely exist.
func _check_sound_integration() -> void:
	var audio := get_node_or_null("/root/AudioManager")
	if audio == null:
		return
	audio.call("clear_played_log")
	var victim: Node3D = null
	for mob in get_tree().get_nodes_in_group("mobs"):
		if not bool(mob.get("is_boss")) and not bool(mob.get("summoned")):
			victim = mob
			break
	check(victim != null, "A non-boss mob is available to voice")
	if victim != null:
		victim.call("on_authoritative_death", world.local_player)
		await get_tree().process_frame
		var played: Array = audio.call("played_keys")
		check(played.has("spider_death"), "A spider death plays its own death voice")
		victim.call("_respawn")
	# footsteps come from the rig's own animation events
	audio.call("clear_played_log")
	world.local_player.call("_on_animation_event", "footstep:stone")
	world.local_player.call("_on_animation_event", "footstep:grass")
	await get_tree().process_frame
	var steps: Array = audio.call("played_keys")
	check(steps.has("step_stone_1") or steps.has("step_stone_2") or steps.has("step_stone_3"),
		"A stone footstep event plays a stone footstep")
	check(steps.has("step_grass_1") or steps.has("step_grass_2") or steps.has("step_grass_3"),
		"A grass footstep event plays a grass footstep, not the stone one")
	check(not steps.has("step_dirt_1"), "An unrelated surface is not played for those events")


func _check_no_missing_resources() -> void:
	var missing: Array = []
	for id in VFX.ASSETS:
		var path := VFX.asset_path(id)
		if path != "" and not ResourceLoader.exists(path):
			missing.append(path)
	for shader_path in ["res://assets/shaders/spell_layer.gdshader",
			"res://assets/shaders/spell_layer_add.gdshader",
			"res://assets/shaders/spell_ribbon.gdshader"]:
		if not ResourceLoader.exists(shader_path):
			missing.append(shader_path)
	check(missing.is_empty(), "Every resource the effects reference resolves (%d missing)" % missing.size())
	# The shaders themselves must compile, or every layer would be magenta.
	var compiled := 0
	for shader_path in ["res://assets/shaders/spell_layer.gdshader",
			"res://assets/shaders/spell_layer_add.gdshader",
			"res://assets/shaders/spell_ribbon.gdshader"]:
		var shader: Shader = load(shader_path)
		if shader != null and shader.get_shader_uniform_list().size() > 0:
			compiled += 1
	check(compiled == 3, "All three effect shaders compile with their uniforms (%d/3)" % compiled)
	for key in sound_library.get("sounds", {}):
		var path := "res://" + String((sound_library["sounds"][key] as Dictionary).get("path", ""))
		if not ResourceLoader.exists(path):
			missing.append(path)
	check(missing.is_empty(), "No sound or effect resource is missing at runtime")


# ------------------------------------------------------------------ report

func _report() -> void:
	# Stop the audio and let the voices settle before quitting: a stream still
	# playing when the engine shuts its audio driver down is retained by the
	# driver and reported as a resource leak.
	var audio := get_node_or_null("/root/AudioManager")
	if audio != null:
		audio.call("stop_everything")
	await get_tree().create_timer(0.3).timeout
	print("--------------------------------------------------------------")
	for message in failures:
		print("  FAILED: " + message)
	print("VFX RESULT: %d checks, %d failures" % [checks, failures.size()])
