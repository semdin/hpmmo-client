extends Node

## Release gates combat-hitch attribution probe (diagnosis, not a fix).
##
## The perf scene reports only folded percentiles per stop, so the
## 116-143 ms combat hitch it found could not be attributed. This probe reproduces
## the same combat stop (same camera, same live pack, same call sequence through
## SkillFX.play_cast / play_impact and SimAuthority.apply_spell_hit) but records
## EVERY frame instead of an average, together with:
##
##   * the frame split into script time (all nodes' `_process`, bracketed by two
##     zero-work marker nodes at priority -10000 / +10000) and the rest of the
##     frame (physics, render submission, GPU sync);
##   * the engine monitors for the same frame (object/resource counts, memory,
##     texture/video memory, draw calls, process/physics time);
##   * an event log: which spell was spawned, which stage, whether it was the
##     first use of that (spell, stage) in this process, and how long the probe's
##     own call took in microseconds.
##
## Every frame is written to a jsonl file, plus one summary line listing the
## spikes. Run it the way the perf scene runs (windowed, vsync off, low preset):
##
##   godot --path client res://scenes/test/perf_hitch_probe.tscn -- \
##     --mode=full --passes=2 --out=client/tools/downloads/perf-hitch-full.jsonl
##
## Modes (each A/Bs one candidate of the combat path):
##   full    cast + impact + hit, exactly as the perf scene calls them
##   cast    SkillFX.play_cast only
##   impact  SkillFX.play_impact only
##   hit     SimAuthority.apply_spell_hit only, no VFX at all
##   correct full, but the hit is aimed at the mob (the perf scene's arguments
##           are swapped, so its "live pack" is actually the player being hit)
##   hud     no VFX and no sim: the presentation hooks a damage event would run
##           (floating text, hit anim, HUD stats emit) at the loop's cadence
##   none    the loop timing without any call (control)
##
## Extra A/B switches:
##   --prewarm=1   spawn every (spell, stage) once in view before the loop, so
##                 first-use shader/pipeline compilation is paid outside it
##   --spells=a,b  restrict the spell cycle
##   --interval=N  seconds between casts (default 0.35, the perf scene's)

const SkillFX = preload("res://scripts/spells/skill_fx.gd")
const QualityPreset = preload("res://scripts/world/quality_preset.gd")
const MarkerScript = preload("res://scripts/test/perf_hitch_marker.gd")

const ALL_SPELLS := ["incendio", "bombarda", "stupefy", "ultimate", "expelliarmus", "basic_cast"]
const STAGES := ["cast", "impact", "sustain", "travel"]

@onready var world: Node3D = $GameWorld

# --- command line
var _mode := "full"
var _out_path := ""
var _seconds := 6.0
var _interval := 0.35
var _passes := 2
var _prewarm := false
var _spells: Array = ALL_SPELLS.duplicate()
var _novsync := false
var _interior := true
var _spike_ms := 25.0

# --- frame recording
var _monitors := {}
var _probe_us := {}          # frame -> probe _process timestamp
var _start_us := {}          # frame -> first marker timestamp
var _end_us := {}            # frame -> last marker timestamp
var _delta_ms := {}          # frame -> engine delta
var _mon := {}               # frame -> monitor values
var _events: Array = []      # [{frame, kind, detail, us}]
var _cast_index := 0
var _spawned_once := {}      # "spell:stage" -> true after first spawn
var _pass_rows: Array = []
var _frame_seq: Array = []   # ordered frame numbers, for report generation

var _camera: Camera3D = null
var _file: FileAccess = null
var _recording := false
var _t_origin_us := 0


func _ready() -> void:
	_parse_args()
	# Markers are children of this node with extreme process priorities: the
	# SceneTree processes nodes in global priority order, so the -10000 marker
	# runs before every other node in the tree (autoloads included) and the
	# +10000 marker runs after every one of them. Adding them to the tree root
	# from `_ready` is refused ("parent is busy"), and a child of this node is
	# enough - priorities are global, not depth-scoped.
	var m_start := MarkerScript.new()
	m_start.role = "start"
	m_start.probe = self
	m_start.process_priority = -10000
	add_child(m_start)
	var m_end := MarkerScript.new()
	m_end.role = "end"
	m_end.probe = self
	m_end.process_priority = 10000
	add_child(m_end)
	var loop := Engine.get_main_loop() as SceneTree
	if _out_path != "":
		_file = FileAccess.open(_out_path, FileAccess.WRITE)
	_monitors = {
		"proc": Performance.TIME_PROCESS, "phys": Performance.TIME_PHYSICS_PROCESS,
		"nav": Performance.TIME_NAVIGATION_PROCESS, "mem": Performance.MEMORY_STATIC,
		"objs": Performance.OBJECT_COUNT, "res": Performance.OBJECT_RESOURCE_COUNT,
		"orph": Performance.OBJECT_ORPHAN_NODE_COUNT, "nodes": Performance.OBJECT_NODE_COUNT,
		"rof": Performance.RENDER_TOTAL_OBJECTS_IN_FRAME,
		"draw": Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME,
		"prims": Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME,
		"tex": Performance.RENDER_TEXTURE_MEM_USED, "vid": Performance.RENDER_VIDEO_MEM_USED,
		"pobjs": Performance.PHYSICS_3D_ACTIVE_OBJECTS,
	}
	await loop.create_timer(1.2).timeout
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	_camera = Camera3D.new()
	_camera.fov = 65
	world.add_child(_camera)
	_camera.current = true
	if _novsync:
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	if _interior:
		var interior: Node3D = load("res://scenes/world/castle_interior.tscn").instantiate()
		interior.name = "InteriorLightRig"
		world.add_child(interior)
		await loop.create_timer(0.8).timeout
	print("SPIKE START mode=%s quality=%s vsync=%s device=%s user_dir=%s" % [
		_mode, QualityPreset.current(), str(DisplayServer.window_get_vsync_mode()),
		RenderingServer.get_video_adapter_name(), OS.get_user_data_dir()])
	if _prewarm:
		await _prewarm_effects()
	_t_origin_us = Time.get_ticks_usec()
	_recording = true
	if _mode in ["full", "cast", "impact", "hit", "hud", "correct", "none"]:
		for p in range(_passes):
			await _combat_pass(p)
	elif _mode == "idle":
		await _idle_seconds(_seconds)
	_recording = false
	await loop.process_frame
	_write_frames()
	_report()
	if _file != null:
		_file.close()
	get_tree().quit()


func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			_out_path = arg.substr(6)
		elif arg.begins_with("--mode="):
			_mode = arg.substr(7)
		elif arg.begins_with("--seconds="):
			_seconds = float(arg.substr(10))
		elif arg.begins_with("--interval="):
			_interval = float(arg.substr(11))
		elif arg.begins_with("--passes="):
			_passes = int(arg.substr(9))
		elif arg.begins_with("--spells="):
			_spells = arg.substr(9).split(",")
		elif arg.begins_with("--spike-ms="):
			_spike_ms = float(arg.substr(11))
		elif arg == "--prewarm":
			_prewarm = true
		elif arg == "--novsync":
			_novsync = true
		elif arg == "--no-interior":
			_interior = false


# ------------------------------------------------------------------ recording

func note_marker(role: String, stamp: int) -> void:
	var frame := Engine.get_process_frames()
	if role == "start":
		_start_us[frame] = stamp
	else:
		_end_us[frame] = stamp


func _process(delta: float) -> void:
	if not _recording:
		return
	var frame := Engine.get_process_frames()
	_probe_us[frame] = Time.get_ticks_usec()
	_delta_ms[frame] = delta * 1000.0
	var row := {}
	for key in _monitors.keys():
		row[key] = Performance.get_monitor(_monitors[key])
	row["vfx"] = SkillFX.active_count()
	_mon[frame] = row


func _event(kind: String, detail: String, us: int) -> void:
	_events.append({"frame": Engine.get_process_frames(), "kind": kind,
		"detail": detail, "us": us})


# ------------------------------------------------------------------ the loop

func _combat_setup() -> Array:
	var player: Node3D = world.get("local_player")
	var mob: Node3D = null
	var best := 1e9
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) != HPProtocol.Kind.MOB:
			continue
		var node = record.get("node")
		if node == null or not is_instance_valid(node):
			continue
		var distance: float = (node as Node3D).global_position.distance_to(Vector3(0, 0, 5))
		if distance < best:
			best = distance
			mob = node
	if mob != null:
		mob.global_position = Vector3(10, 0.5, 2)
	_camera.global_position = Vector3(-3, 4.0, 12)
	var focus := Vector3(0, 1.5, 5)
	if mob != null:
		focus = mob.global_position + Vector3(0, 1.0, 0)
	_camera.look_at(focus)
	return [player, mob, focus]


func _combat_pass(pass_index: int) -> void:
	var setup: Array = _combat_setup()
	var player: Node3D = setup[0]
	var mob: Node3D = setup[1]
	var focus: Vector3 = setup[2]
	await get_tree().create_timer(0.5).timeout
	var start_frame := Engine.get_process_frames()
	var until := float(Time.get_ticks_msec()) / 1000.0 + _seconds
	var casts := 0
	var hp0 := 0
	if player != null and is_instance_valid(player):
		hp0 = int(player.get("current_hp"))
	while float(Time.get_ticks_msec()) / 1000.0 < until:
		var spell: String = _spells[_cast_index % _spells.size()]
		_cast_index += 1
		if mob != null and is_instance_valid(mob) and int(mob.get("current_hp")) <= 0:
			mob.set("current_hp", int(mob.get("max_hp")))
			SimAuthority.refresh_mob(mob)
		if player != null and is_instance_valid(player):
			var aim: Vector3 = focus
			if _mode in ["full", "correct"]:
				var t0 := Time.get_ticks_usec()
				SkillFX.play_cast(world, player, spell, player.global_position + Vector3(0, 1.2, 0), (aim - player.global_position).normalized())
				var t1 := Time.get_ticks_usec()
				SkillFX.play_impact(world, aim, spell)
				var t2 := Time.get_ticks_usec()
				_event("cast", spell, int(t1 - t0))
				_event("impact", spell, int(t2 - t1))
				_note_spawn(spell, "cast")
				_note_spawn(spell, "impact")
				var t3 := Time.get_ticks_usec()
				if _mode == "correct" and mob != null and is_instance_valid(mob):
					SimAuthority.apply_spell_hit(mob, spell, player)
				else:
					# Replicates the perf scene's argument order exactly.
					SimAuthority.apply_spell_hit(player, spell, mob)
				_event("hit", spell, int(Time.get_ticks_usec() - t3))
			elif _mode == "cast":
				var t0 := Time.get_ticks_usec()
				_note_spawn(spell, "cast")
				SkillFX.play_cast(world, player, spell, player.global_position + Vector3(0, 1.2, 0), (aim - player.global_position).normalized())
				_event("cast", spell, int(Time.get_ticks_usec() - t0))
			elif _mode == "impact":
				var t0 := Time.get_ticks_usec()
				_note_spawn(spell, "impact")
				SkillFX.play_impact(world, aim, spell)
				_event("impact", spell, int(Time.get_ticks_usec() - t0))
			elif _mode == "hit":
				var t0 := Time.get_ticks_usec()
				SimAuthority.apply_spell_hit(player, spell, mob)
				_event("hit", spell, int(Time.get_ticks_usec() - t0))
			elif _mode == "hud":
				# The presentation half of a damage event, driven directly: the
				# harness's own apply_spell_hit call is refused by the courtyard's
				# safe zone, so this is the only way to charge the floating-text /
				# HUD path inside the loop.
				var t0 := Time.get_ticks_usec()
				if player.has_method("on_authoritative_damage"):
					player.call("on_authoritative_damage", spell, mob, 0, 0)
				if player.has_method("apply_authoritative_stats"):
					player.call("apply_authoritative_stats", {"hp": 400, "max_hp": 500, "mana": 100,
						"max_mana": 100, "exp": 12, "max_exp": 100, "level": 1, "galleons": 3,
						"mounted": false, "dead": false})
				_event("hud", spell, int(Time.get_ticks_usec() - t0))
		casts += 1
		await get_tree().create_timer(_interval).timeout
	var hp1 := 0
	var mob_hp := 0
	if player != null and is_instance_valid(player):
		hp1 = int(player.get("current_hp"))
	if mob != null and is_instance_valid(mob):
		mob_hp = int(mob.get("current_hp"))
	_pass_rows.append({"pass": pass_index, "start_frame": start_frame,
		"casts": casts, "player_hp_0": hp0, "player_hp_1": hp1,
		"mob_hp_1": mob_hp, "player_dead": bool(player.get("is_dead")) if player != null and is_instance_valid(player) else false})


func _note_spawn(spell: String, stage: String) -> void:
	var key := "%s:%s" % [spell, stage]
	if not _spawned_once.has(key):
		_spawned_once[key] = true
		_event("first_use", key, 0)


func _idle_seconds(seconds: float) -> void:
	_camera.global_position = Vector3(-3, 4.0, 12)
	_camera.look_at(Vector3(0, 1.5, 5))
	await get_tree().create_timer(seconds).timeout


## Pay every first-use cost inside the probe, in front of the camera, so the
## measured loop cannot be charged for them.
func _prewarm_effects() -> void:
	var player: Node3D = world.get("local_player")
	if player == null or not is_instance_valid(player):
		return
	var view := _camera.global_position + (-_camera.global_transform.basis.z) * 6.0
	for spell in ALL_SPELLS:
		for stage in STAGES:
			var effect: Node3D = SkillFX.spawn_stage(world, spell, stage, view, Vector3.FORWARD, null, {})
			_note_spawn(spell, stage)
			await get_tree().process_frame
			await get_tree().process_frame
			if effect != null and is_instance_valid(effect):
				effect.call("cancel", "prewarm")
			await get_tree().process_frame
	print("SPIKE PREWARM done spells=%d stages=%d" % [ALL_SPELLS.size(), STAGES.size()])


# ------------------------------------------------------------------ output

func _frame_list() -> Array:
	var frames: Array = []
	for frame in _probe_us.keys():
		frames.append(int(frame))
	frames.sort()
	return frames


func _write_frames() -> void:
	if _file == null:
		return
	var frames := _frame_list()
	var prev_us := 0
	for frame in frames:
		var us: int = _probe_us[frame]
		var script_us := 0
		if _start_us.has(frame) and _end_us.has(frame):
			script_us = int(_end_us[frame]) - int(_start_us[frame])
		var row := {
			"f": frame,
			"t_ms": (us - _t_origin_us) / 1000.0,
			"dt_ms": _delta_ms.get(frame, 0.0),
			"script_us": script_us,
			"probe_us": (us - _start_us.get(frame, us)) if _start_us.has(frame) else 0,
			"tail_us": (int(_end_us[frame]) - us) if _end_us.has(frame) else 0,
			"outside_us": int(_delta_ms.get(frame, 0.0) * 1000.0) - script_us,
		}
		var mon: Dictionary = _mon.get(frame, {})
		for key in mon.keys():
			row[key] = mon[key]
		_file.store_line(JSON.stringify(row))
		prev_us = us
	_file.flush()


func _report() -> void:
	var frames := _frame_list()
	var spikes: Array = []
	var hist := {"<15": 0, "15-25": 0, "25-50": 0, "50-100": 0, ">100": 0}
	var worst := 0.0
	var worst_frame := -1
	for frame in frames:
		var dt: float = _delta_ms.get(frame, 0.0)
		if dt > worst:
			worst = dt
			worst_frame = frame
		if dt < 15.0:
			hist["<15"] += 1
		elif dt < 25.0:
			hist["15-25"] += 1
		elif dt < 50.0:
			hist["25-50"] += 1
		elif dt < 100.0:
			hist["50-100"] += 1
		else:
			hist[">100"] += 1
		if dt >= _spike_ms:
			spikes.append(int(frame))
	print("SPIKE HIST %s frames=%d worst_ms=%.2f at_frame=%d spikes=%d" % [
		JSON.stringify(hist), frames.size(), worst, worst_frame, spikes.size()])
	for pass_row in _pass_rows:
		print("SPIKE PASS %s" % JSON.stringify(pass_row))
	# The 15 worst frames with their script/outside split and the last event
	# that happened at or before them: this is the attribution.
	var sorted := frames.duplicate()
	sorted.sort_custom(func(a, b): return _delta_ms.get(a, 0.0) > _delta_ms.get(b, 0.0))
	for i in range(mini(15, sorted.size())):
		var frame: int = sorted[i]
		var dt: float = _delta_ms[frame]
		if dt < _spike_ms and i > 0:
			break
		var script_us: int = 0
		if _start_us.has(frame) and _end_us.has(frame):
			script_us = int(_end_us[frame]) - int(_start_us[frame])
		var mon: Dictionary = _mon.get(frame, {})
		var last_events: Array = []
		for e in _events:
			if int(e["frame"]) <= frame and int(e["frame"]) >= frame - 4:
				last_events.append("%s:%s(%dus)@%d" % [e["kind"], e["detail"], e["us"], e["frame"]])
		print("SPIKE FRAME %d dt=%.1f script=%.2f outside=%.2f proc=%.1f phys=%.1f vfx=%s events=[%s]" % [
			frame, dt, script_us / 1000.0, dt - script_us / 1000.0,
			float(mon.get("proc", 0.0)) * 1000.0, float(mon.get("phys", 0.0)) * 1000.0,
			str(mon.get("vfx", -1)), ", ".join(last_events.slice(maxi(0, last_events.size() - 4), last_events.size()))])
	print("SPIKE RESULT mode=%s passes=%d frames=%d spikes=%d worst_ms=%.2f" % [
		_mode, _passes, frames.size(), spikes.size(), worst])
