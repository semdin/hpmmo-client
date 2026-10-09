extends Node

## Skill animation viewer - the live preview used while tuning spell VFX.
##
## `vfx_capture.gd` shoots fixed evidence frames; this is the interactive loop.
## It plays a spell's real stage sequence - cast, travel, impact, sustain, end -
## on the real world, from the real caster, then beats and moves on to the next
## spell. Slow motion, a free orbit camera and a human-sized reference at the
## impact point make scale, timing and readability judgeable by eye.
##
## Run windowed (a real renderer is required):
##
##   godot --path client res://scenes/test/vfx_viewer.tscn
##   godot --path client res://scenes/test/vfx_viewer.tscn -- --quality=high --spell=incendio
##
## Add `--shot` to save one PNG per stage into `res://tools/downloads` and exit,
## so the viewer doubles as the batch evidence run. `--speed=1.0` runs the batch
## at real time instead of the default slow motion; `--cam`, `--pitch`, `--dist`
## set the framing, and `--spell=<id>` picks the spell to start on.
##
## Controls
##   Space         pause / resume (freezes the effect, the camera keeps working)
##   Left / Right  previous / next spell
##   R             replay the current spell
##   - / =         slower / faster playback (0.05x .. 2x)
##   1 / 2 / 3     quality preset: low / medium / high
##   O             toggle the slow auto-orbit
##   T             toggle the scale reference at the impact point
##   C             save a PNG of the current frame
##   Esc / Q       quit
##   drag / wheel  orbit / zoom

const VFX = preload("res://scripts/spells/vfx_library.gd")
const SkillFX = preload("res://scripts/spells/skill_fx.gd")
const QualityPreset = preload("res://scripts/world/quality_preset.gd")

const STAGE_ORDER := ["cast", "travel", "impact", "sustain", "end"]
const BEAT := 0.9
const OUT_DIR := "res://tools/downloads"
const FALLBACK_SPEED := 30.0

@onready var world: Node3D = $GameWorld

var spell_ids: Array = []
var spell_index := 0
var spell_id := ""

var plan: Array = []
var plan_index := 0
var stage_clock := 0.0
var stage_duration := 0.1
var sequence_clock := 0.0
var sequence_total := 0.1

var speed := 0.35
var auto_orbit := true
## `--shot`: save one PNG mid-stage for every stage, then quit. Batch evidence
## without a human at the keyboard.
var shot_mode := false
## Fraction of a stage at which `--shot` takes its frame. Spell casts and
## impacts are front-loaded flashes, so those stages are sampled early while the
## continuous stages are sampled at their middle; `--shot-at=<f>` overrides.
var shot_at := -1.0
var _shot_done := {}
var _finished := false

var origin := Vector3(0.0, 0.15, -12.0)
## Into the open courtyard, away from the castle gate: the capture harness aims
## the same way, and nothing occludes the beam.
var aim := Vector3(0.0, 0.0, 1.0)
var flight_distance := 9.0

var _camera: Camera3D
var _dummy: Node3D
var _travel_target: Node3D
var _travel_effect: Node3D
var _spawned: Array = []
## Camera bearing measured from directly behind the caster, so the framing is
## expressed against the beam and works for any aim: 0 is down the beam, ~1.15
## is the three-quarter side view that keeps caster and target both in frame.
var _cam_angle := 1.5
var _pitch := 0.20
var _distance := 11.0
var _drag := false
var _show_dummy := true
var _label: Label
var _hint: Label
var _bar: ColorRect
var _bar_bg: ColorRect


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var wanted := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--quality="):
			QualityPreset.forced(arg.trim_prefix("--quality="))
		elif arg.begins_with("--spell="):
			wanted = arg.trim_prefix("--spell=")
		elif arg == "--shot":
			shot_mode = true
			auto_orbit = false
		elif arg.begins_with("--speed="):
			speed = clampf(float(arg.trim_prefix("--speed=")), 0.05, 2.0)
		elif arg.begins_with("--cam="):
			_cam_angle = float(arg.trim_prefix("--cam="))
		elif arg.begins_with("--pitch="):
			_pitch = float(arg.trim_prefix("--pitch="))
		elif arg.begins_with("--dist="):
			_distance = clampf(float(arg.trim_prefix("--dist=")), 2.0, 40.0)
		elif arg.begins_with("--shot-at="):
			shot_at = clampf(float(arg.trim_prefix("--shot-at=")), 0.02, 0.95)
	spell_ids = VFX.spell_ids()
	if wanted != "":
		var found := spell_ids.find(wanted)
		if found >= 0:
			spell_index = found
	# The world builds its castle, mobs and HUD over the first beat; wait it out.
	await get_tree().create_timer(1.4).timeout
	_hide_world_ui()
	_setup_camera()
	_setup_dummy()
	_setup_ui()
	_park_caster()
	Engine.time_scale = speed
	_start_spell(spell_index)


func _exit_tree() -> void:
	Engine.time_scale = 1.0


## ---------------------------------------------------------------- setup

func _hide_world_ui() -> void:
	for node in world.find_children("*", "CanvasLayer", true, false):
		(node as CanvasLayer).visible = false


func _setup_camera() -> void:
	_camera = Camera3D.new()
	_camera.name = "ViewerCamera"
	_camera.fov = 65.0
	_camera.near = 0.05
	_camera.far = 400.0
	world.add_child(_camera)
	_camera.current = true
	_update_camera()


## A human-sized stand-in at the impact point, so scale is judgeable: the
## caster's own body may be off-frame once the camera orbits.
func _setup_dummy() -> void:
	_dummy = Node3D.new()
	_dummy.name = "ScaleReference"
	var body := MeshInstance3D.new()
	var capsule := CapsuleMesh.new()
	capsule.height = 1.8
	capsule.radius = 0.32
	body.mesh = capsule
	body.position = Vector3(0.0, 0.9, 0.0)
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(0.16, 0.72, 0.78, 1.0)
	material.roughness = 0.55
	body.material_override = material
	_dummy.add_child(body)
	world.add_child(_dummy)
	_dummy.visible = _show_dummy


func _setup_ui() -> void:
	var layer := CanvasLayer.new()
	layer.name = "ViewerUI"
	add_child(layer)
	_label = Label.new()
	_label.position = Vector2(18.0, 14.0)
	_label.add_theme_font_size_override("font_size", 16)
	_label.add_theme_color_override("font_color", Color(0.95, 0.93, 0.86))
	_label.add_theme_color_override("font_shadow_color", Color(0.0, 0.0, 0.0, 0.8))
	_label.add_theme_constant_override("shadow_offset_x", 1)
	_label.add_theme_constant_override("shadow_offset_y", 1)
	_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(_label)
	_bar_bg = ColorRect.new()
	_bar_bg.color = Color(1.0, 1.0, 1.0, 0.16)
	_bar_bg.anchor_top = 1.0
	_bar_bg.anchor_bottom = 1.0
	_bar_bg.offset_left = 18.0
	_bar_bg.offset_top = -52.0
	_bar_bg.offset_right = 378.0
	_bar_bg.offset_bottom = -48.0
	_bar_bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(_bar_bg)
	_bar = ColorRect.new()
	_bar.color = Color(0.36, 0.85, 0.95, 0.95)
	_bar.size = Vector2(0.0, 4.0)
	_bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_bar_bg.add_child(_bar)
	_hint = Label.new()
	_hint.text = "Space pause · ←/→ spell · R replay · -/= speed · 1/2/3 quality · O orbit · T reference · C png · Esc quit · drag orbit · wheel zoom"
	_hint.add_theme_font_size_override("font_size", 13)
	_hint.add_theme_color_override("font_color", Color(0.72, 0.78, 0.85))
	_hint.anchor_top = 1.0
	_hint.anchor_bottom = 1.0
	_hint.offset_left = 18.0
	_hint.offset_top = -30.0
	_hint.offset_bottom = -10.0
	_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(_hint)


## The local player is the caster, so the character and the VFX are judged
## together. Movement and the input hotkeys are parked - a viewer key must not
## walk or jump the actor - but `_process` keeps running, because that is where
## the rig's animation graph is ticked (`hero_anim.tick`).
func _park_caster() -> void:
	var caster := _caster()
	if caster == null:
		return
	caster.set_physics_process(false)
	caster.set("is_local_player", false)


## ---------------------------------------------------------------- sequencing

func _start_spell(index: int) -> void:
	spell_index = wrapi(index, 0, spell_ids.size())
	spell_id = String(spell_ids[spell_index])
	_clear_spawned()
	_shot_done.clear()
	_finished = false
	_build_plan(spell_id)
	plan_index = 0
	stage_clock = 0.0
	stage_duration = float(plan[0]["duration"])
	sequence_clock = 0.0
	sequence_total = 0.0
	for entry in plan:
		sequence_total += float(entry["duration"])
	_place_actor()
	_enter_stage(String(plan[0]["stage"]))
	_update_ui()


## Canonical stage order, with only the stages the spell actually declares, so a
## new stage in `vfx_library.gd` shows up here without a second list to edit.
func _build_plan(id: String) -> void:
	plan = []
	var stages := VFX.stages_for(id)
	for stage in STAGE_ORDER:
		if not stages.has(stage):
			continue
		var duration := _flight_time(id) if stage == "travel" else maxf(0.25, VFX.stage_length(id, stage))
		plan.append({"stage": stage, "duration": duration})
	plan.append({"stage": "beat", "duration": BEAT})


func _enter_stage(stage: String) -> void:
	match stage:
		"cast":
			_play_caster_cast()
			SkillFX.play_cast(world, _caster(), spell_id, _spawn_point(), aim)
		"travel":
			_begin_travel()
		"impact":
			SkillFX.play_impact(world, _impact_point(), spell_id, null)
		"sustain":
			_begin_sustain()
		"end":
			_play_stage("end", _impact_point(), aim)


## Drive the rig's own cast pose so pose and effect are tuned against the same
## release beat. The player owns which clip reads as a cast; this only asks for
## it, exactly as a real cast does.
func _play_caster_cast() -> void:
	var caster := _caster()
	if caster != null and caster.has_method("_play_cast_animation"):
		caster.call("_play_cast_animation", "Spellcast_Shoot", _spawn_point() + aim * flight_distance, spell_id)


func _begin_travel() -> void:
	_travel_target = Node3D.new()
	_travel_target.name = "TravelProbe"
	world.add_child(_travel_target)
	_travel_target.global_position = _spawn_point()
	var effect := SkillFX.spawn_stage(world, spell_id, "travel", _spawn_point(), aim,
		_caster(), {"follow_target": _travel_target})
	if effect != null:
		_spawned.append(effect)
		_travel_effect = effect


## The flight is over: the probe owns the travel stage, so the stage is retired
## with the probe instead of leaving a bolt parked where the flight stopped.
func _end_travel() -> void:
	if is_instance_valid(_travel_effect) and _travel_effect.has_method("cancel"):
		_travel_effect.call("cancel", "viewer_stage_end")
	_travel_effect = null
	if is_instance_valid(_travel_target):
		_travel_target.queue_free()
	_travel_target = null


func _begin_sustain() -> void:
	match spell_id:
		"stupefy":
			SkillFX.play_stun_stars(world, _dummy)
		"incendio":
			SkillFX.play_burn(world, _dummy, VFX.stage_length(spell_id, "sustain"))
		_:
			_play_stage("sustain", _impact_point(), Vector3.UP)


func _play_stage(stage: String, position: Vector3, direction: Vector3) -> void:
	var effect := SkillFX.spawn_stage(world, spell_id, stage, position, direction)
	if effect != null:
		_spawned.append(effect)


func _process(delta: float) -> void:
	if auto_orbit and not get_tree().paused:
		_cam_angle += delta * 0.2
	_update_camera()
	if get_tree().paused or _finished or plan.is_empty():
		return
	stage_clock += delta
	sequence_clock += delta
	if String(plan[plan_index]["stage"]) == "travel" and is_instance_valid(_travel_target):
		var frac := clampf(stage_clock / maxf(0.001, stage_duration), 0.0, 1.0)
		_travel_target.global_position = _spawn_point().lerp(_impact_point(), frac)
	if shot_mode:
		_maybe_shoot()
	if stage_clock >= stage_duration:
		_advance()
		if _finished:
			return
	_update_ui()


## One PNG per stage, taken where the stage actually reads: a flash is gone
## before its stage length elapses, so it is sampled early.
func _maybe_shoot() -> void:
	var stage := String(plan[plan_index]["stage"])
	if stage == "beat" or _shot_done.has(stage):
		return
	var fraction := shot_at
	if fraction < 0.0:
		fraction = 0.5 if stage in ["travel", "sustain", "end"] else 0.2
	if stage_clock < stage_duration * fraction:
		return
	_shot_done[stage] = true
	_capture()


func _advance() -> void:
	if String(plan[plan_index]["stage"]) == "travel":
		_end_travel()
	plan_index += 1
	if plan_index >= plan.size():
		if shot_mode:
			_finished = true
			get_tree().quit()
			return
		_start_spell(spell_index + 1)
		return
	stage_clock = 0.0
	stage_duration = float(plan[plan_index]["duration"])
	_enter_stage(String(plan[plan_index]["stage"]))


## ---------------------------------------------------------------- geometry

func _caster() -> Node3D:
	if world != null and world.local_player != null and is_instance_valid(world.local_player):
		return world.local_player
	return null


func _place_actor() -> void:
	var caster := _caster()
	if caster == null:
		return
	caster.global_position = origin
	if caster is CharacterBody3D:
		(caster as CharacterBody3D).velocity = Vector3.ZERO
	var visuals := caster.get("visuals") as Node3D
	if visuals != null:
		visuals.rotation.y = atan2(aim.x, aim.z)
	_dummy.global_position = origin + aim * _beam_distance(spell_id)


## Chest height of the caster: where a cast flash leaves the wand.
func _spawn_point() -> Vector3:
	return origin + Vector3.UP * 1.25


## Chest height of the target: where an impact reads.
func _impact_point() -> Vector3:
	return origin + aim * _beam_distance(spell_id) + Vector3.UP * 1.0


func _beam_distance(id: String) -> float:
	return flight_distance if VFX.stages_for(id).has("travel") else 3.0


func _flight_time(id: String) -> float:
	var projectile_speed := FALLBACK_SPEED
	var game_data := get_node_or_null("/root/GameData")
	if game_data != null:
		var spells = game_data.get("SPELLS")
		if spells is Dictionary and spells.has(id):
			projectile_speed = float(spells[id].get("projectile_speed", FALLBACK_SPEED))
	return clampf(_beam_distance(id) / maxf(1.0, projectile_speed), 0.25, 3.0)


func _clear_spawned() -> void:
	for effect in _spawned:
		if is_instance_valid(effect) and effect.has_method("cancel"):
			effect.call("cancel", "viewer_reset")
	_spawned.clear()
	_end_travel()


## ---------------------------------------------------------------- camera

func _update_camera() -> void:
	if _camera == null:
		return
	var focus := origin + aim * (_beam_distance(spell_id) * 0.5) + Vector3.UP * 1.1
	var beam := aim.normalized()
	var back := -beam
	var side := Vector3.UP.cross(beam).normalized()
	var horizontal := (back * cos(_cam_angle) + side * sin(_cam_angle)).normalized()
	var offset := (horizontal * cos(_pitch) + Vector3.UP * sin(_pitch)) * _distance
	_camera.global_position = focus + offset
	_camera.look_at(focus)


## ---------------------------------------------------------------- hud

func _update_ui() -> void:
	if _label == null or plan.is_empty() or plan_index >= plan.size():
		return
	_label.text = "SKILL ANIMATION VIEWER\nspell %d/%d   %s\nstage %s   %.2f / %.2fs   speed %.2fx   quality %s   %s" % [
		spell_index + 1, spell_ids.size(), spell_id,
		String(plan[plan_index]["stage"]), stage_clock, stage_duration,
		speed, QualityPreset.current(), "PAUSED" if get_tree().paused else "playing"]
	_bar.size = Vector2(360.0 * clampf(sequence_clock / maxf(0.001, sequence_total), 0.0, 1.0), 4.0)


## ---------------------------------------------------------------- input

func _input(event: InputEvent) -> void:
	if event is InputEventKey and (event as InputEventKey).pressed and not (event as InputEventKey).echo:
		_handle_key((event as InputEventKey).keycode)
		get_viewport().set_input_as_handled()
		return
	if event is InputEventMouseButton:
		var button := event as InputEventMouseButton
		if button.button_index == MOUSE_BUTTON_LEFT:
			_drag = button.pressed
		elif button.pressed and button.button_index == MOUSE_BUTTON_WHEEL_UP:
			_distance = clampf(_distance * 0.88, 2.0, 40.0)
		elif button.pressed and button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_distance = clampf(_distance * 1.14, 2.0, 40.0)
		return
	if event is InputEventMouseMotion and _drag:
		var motion := event as InputEventMouseMotion
		_cam_angle -= motion.relative.x * 0.006
		_pitch = clampf(_pitch - motion.relative.y * 0.005, -0.45, 1.25)


func _handle_key(keycode: int) -> void:
	match keycode:
		KEY_SPACE:
			get_tree().paused = not get_tree().paused
		KEY_RIGHT, KEY_BRACKETRIGHT:
			_start_spell(spell_index + 1)
		KEY_LEFT, KEY_BRACKETLEFT:
			_start_spell(spell_index - 1)
		KEY_R:
			_start_spell(spell_index)
		KEY_MINUS, KEY_KP_SUBTRACT:
			_set_speed(speed / 1.35)
		KEY_EQUAL, KEY_PLUS, KEY_KP_ADD:
			_set_speed(speed * 1.35)
		KEY_1:
			_set_quality("low")
		KEY_2:
			_set_quality("medium")
		KEY_3:
			_set_quality("high")
		KEY_O:
			auto_orbit = not auto_orbit
		KEY_T:
			_show_dummy = not _show_dummy
			_dummy.visible = _show_dummy
		KEY_C:
			_capture()
		KEY_ESCAPE, KEY_Q:
			get_tree().quit()


func _set_speed(value: float) -> void:
	speed = clampf(value, 0.05, 2.0)
	Engine.time_scale = speed


func _set_quality(name: String) -> void:
	QualityPreset.forced(name)
	QualityPreset.apply(world)


func _capture() -> void:
	await RenderingServer.frame_post_draw
	var path := "%s/vfx-viewer-%s-%s.png" % [OUT_DIR, spell_id, String(plan[plan_index]["stage"])]
	var error := get_viewport().get_texture().get_image().save_png(path)
	print("VFX VIEWER capture: %s (%s)" % [path, error])
