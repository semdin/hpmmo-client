extends Node

## Phase 14 performance capture (plan.md Phase 14: "measure frame-time
## percentiles and publish exceptions", "inspect visible draw calls, transparent
## overdraw, dynamic lights, texture memory, animation cost, navigation and
## physics separately").
##
## Same fixed camera stops as the Phase 10 route so the numbers are comparable
## with the greybox run, plus a combat stop where the real spell path is driven
## so spell VFX cost is inside the measurement instead of outside it.
##
## Per stop it samples every rendered frame for SAMPLE_SECONDS and reports
## p50/p95/p99 of the FRAME TIME (not fps averages: the p99 is the stutter the
## player feels), plus the engine monitors for draw calls, primitives, texture
## and video memory, dynamic light count, particle count, and the separate
## process/physics/navigation times.
##
## Animation cost is measured by an A/B on one stop: the same camera, once with
## the scene's AnimationPlayers/AnimationTrees processing and once with them
## disabled. The difference is the animation cost; both halves are printed so
## the number cannot be read without its control.
##
## Run windowed (a real renderer is the point):
##   godot --path client res://scenes/test/phase14_perf.tscn --quit-after 20000 \
##     -- --out=perf.jsonl [--quality=low|high]

const STOPS := [
	# [label, interior, camera pos, target]
	["out-approach", false, Vector3(0, 3.4, -16), Vector3(0, 9.5, -70)],
	["out-courtyard", false, Vector3(13, 6.5, 27), Vector3(-2, 2, -12)],
	["out-terrain", false, Vector3(-30, 16, 30), Vector3(-70, 2, -24)],
	["in-great-hall", true, Vector3(-52, 203.4, 2), Vector3(-16, 204.5, -2)],
	["in-stair-hall", true, Vector3(8, 202.2, -16), Vector3(42, 205.0, -14)],
	["in-library", true, Vector3(-24, 207.6, -33), Vector3(-52, 208.2, -44)],
]

var _sample_seconds := 6.0
const WARMUP_SECONDS := 0.6

const QualityPreset = preload("res://scripts/world/quality_preset.gd")
const SkillFX = preload("res://scripts/spells/skill_fx.gd")

@onready var world: Node3D = $GameWorld

var _camera: Camera3D = null
var _interior: Node3D = null
var _out_path := ""
var _file: FileAccess = null
var _rows: Array = []
var _samples: Array = []
var _sampling := false
var _quality := ""
var _novsync := false

func _ready() -> void:
	_parse_args()
	if _out_path != "":
		_file = FileAccess.open(_out_path, FileAccess.WRITE)
	await get_tree().create_timer(1.2).timeout
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	_quality = QualityPreset.current()
	_camera = Camera3D.new()
	_camera.fov = 65
	world.add_child(_camera)
	_camera.current = true
	if _novsync:
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	print("PERF START quality=%s vsync=%s device=%s driver=%s window=%dx%d" % [
		_quality, str(DisplayServer.window_get_vsync_mode()),
		RenderingServer.get_video_adapter_name(), RenderingServer.get_video_adapter_api_version(),
		int(get_viewport().get_visible_rect().size.x), int(get_viewport().get_visible_rect().size.y)])
	for stop in STOPS:
		var label := String(stop[0])
		var wants_interior: bool = stop[1]
		if wants_interior and _interior == null:
			_interior = load("res://scenes/world/castle_interior.tscn").instantiate()
			_interior.name = "Phase14Interior"
			world.add_child(_interior)
			await get_tree().create_timer(0.8).timeout
		_camera.global_position = stop[2]
		_camera.look_at(stop[3])
		await get_tree().create_timer(WARMUP_SECONDS).timeout
		await _sample_stop(label)
	# Combat stop twice: the first pass carries any first-use cost (shader and
	# particle compilation) that a player only pays once per session; the second
	# separates that from the steady-state cost of a spell fight.
	await _combat_stop("combat-1")
	await _combat_stop("combat-2")
	# Animation A/B on the courtyard stop (the busiest outdoor view).
	await _animation_ab()
	_report()
	if _file != null:
		_file.close()
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			_out_path = arg.substr(6)
		elif arg == "--novsync":
			_novsync = true
		elif arg.begins_with("--seconds="):
			_sample_seconds = float(arg.substr(10))

func _process(delta: float) -> void:
	if _sampling:
		_samples.append(delta)

## One stop: sample every frame for SAMPLE_SECONDS, then fold the samples and
## the engine monitors into one row.
func _sample_stop(label: String, extra: Dictionary = {}) -> void:
	_samples.clear()
	_sampling = true
	await get_tree().create_timer(_sample_seconds).timeout
	_sampling = false
	var row := _fold(label, extra)
	_rows.append(row)
	_emit(row)

func _fold(label: String, extra: Dictionary) -> Dictionary:
	var times: Array = _samples.duplicate()
	times.sort()
	var count := times.size()
	var p50 := _percentile(times, 0.50)
	var p95 := _percentile(times, 0.95)
	var p99 := _percentile(times, 0.99)
	var row := {
		"label": label,
		"frames": count,
		"p50_ms": p50 * 1000.0,
		"p95_ms": p95 * 1000.0,
		"p99_ms": p99 * 1000.0,
		"max_ms": (float(times[-1]) if count > 0 else 0.0) * 1000.0,
		"fps_from_p50": (1.0 / p50) if p50 > 0.0 else 0.0,
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		"prims": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME),
		"objects_in_frame": Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME),
		"tex_mib": Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED) / 1048576.0,
		"vid_mib": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"static_mib": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"process_ms": Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0,
		"physics_ms": Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0,
		"nav_ms": Performance.get_monitor(Performance.TIME_NAVIGATION_PROCESS) * 1000.0,
		"phys_objects": Performance.get_monitor(Performance.PHYSICS_3D_ACTIVE_OBJECTS),
		"phys_pairs": Performance.get_monitor(Performance.PHYSICS_3D_COLLISION_PAIRS),
		"nav_regions": Performance.get_monitor(Performance.NAVIGATION_REGION_COUNT),
		"nav_agents": Performance.get_monitor(Performance.NAVIGATION_AGENT_COUNT),
		"nav_polygons": Performance.get_monitor(Performance.NAVIGATION_POLYGON_COUNT),
		"lights": _count_lights(),
		"particles": _count_particles(),
		"quality": _quality,
	}
	for key in extra.keys():
		row[key] = extra[key]
	return row

func _percentile(sorted_times: Array, fraction: float) -> float:
	if sorted_times.is_empty():
		return 0.0
	var index := int(clampf(floorf(fraction * float(sorted_times.size())), 0.0, float(sorted_times.size() - 1)))
	return float(sorted_times[index])

## Visible lights that can shade the current view: omni/spot lights that are
## visible and enabled, plus the sun. This is the count of dynamic emitters the
## renderer must consider, not a claim about clustering cost.
func _count_lights() -> int:
	var count := 0
	for node in world.find_children("*", "OmniLight3D", true, false):
		if (node as OmniLight3D).visible:
			count += 1
	for node in world.find_children("*", "SpotLight3D", true, false):
		if (node as SpotLight3D).visible:
			count += 1
	return count

func _count_particles() -> int:
	var count := 0
	for node in world.find_children("*", "GPUParticles3D", true, false):
		if (node as GPUParticles3D).emitting:
			count += 1
	for node in world.find_children("*", "CPUParticles3D", true, false):
		if (node as CPUParticles3D).emitting:
			count += 1
	return count

## Combat: the real spell path against a real pack, camera on the fight.
## VFX are driven through SkillFX/the spell scenes exactly as play does.
func _combat_stop(label: String = "combat-1") -> void:
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
	var focus := Vector3(0, 1.5, 5)
	var target: Node3D = null
	if mob != null:
		# Bring the pack to the courtyard edge so the fight is in frame and the
		# camera does not need to travel; the mob is the authority's own node.
		mob.global_position = Vector3(10, 0.5, 2)
		target = mob
		focus = mob.global_position + Vector3(0, 1.0, 0)
	_camera.global_position = Vector3(-3, 4.0, 12)
	_camera.look_at(focus)
	await get_tree().create_timer(0.5).timeout
	_samples.clear()
	_sampling = true
	var spells := ["incendio", "bombarda", "stupefy", "ultimate", "expelliarmus", "basic_cast"]
	var index := 0
	var until := _now() + _sample_seconds
	while _now() < until:
		var spell: String = spells[index % spells.size()]
		index += 1
		if target != null and is_instance_valid(target) and int(target.get("current_hp")) <= 0:
			target.set("current_hp", int(target.get("max_hp")))
			SimAuthority.refresh_mob(target)
		if player != null and is_instance_valid(player):
			var aim: Vector3 = focus
			# The real presentation path, same calls SpellProjectile makes.
			SkillFX.play_cast(world, player, spell, player.global_position + Vector3(0, 1.2, 0), (aim - player.global_position).normalized())
			SkillFX.play_impact(world, aim, spell)
			if target != null and is_instance_valid(target):
				SimAuthority.apply_spell_hit(player, spell, target)
		await get_tree().create_timer(0.35).timeout
	_sampling = false
	var row := _fold(label, {"note": "incendio/bombarda/stupefy/ultimate/expelliarmus/basic_cast on a live pack"})
	_rows.append(row)
	_emit(row)

func _now() -> float:
	return float(Time.get_ticks_msec()) / 1000.0

## Animation cost A/B: same camera, same scene, animations on then off.
func _animation_ab() -> void:
	_camera.global_position = Vector3(13, 6.5, 27)
	_camera.look_at(Vector3(-2, 2, -12))
	await get_tree().create_timer(WARMUP_SECONDS).timeout
	await _sample_stop("anim-on")
	var players := world.find_children("*", "AnimationPlayer", true, false)
	var trees := world.find_children("*", "AnimationTree", true, false)
	var restores: Array = []
	for node in players:
		restores.append([node, node.process_mode])
		node.process_mode = Node.PROCESS_MODE_DISABLED
	for node in trees:
		restores.append([node, node.process_mode])
		node.process_mode = Node.PROCESS_MODE_DISABLED
	await get_tree().create_timer(0.4).timeout
	await _sample_stop("anim-off", {"animation_players_disabled": players.size(), "animation_trees_disabled": trees.size()})
	for entry in restores:
		entry[0].process_mode = entry[1]

func _emit(row: Dictionary) -> void:
	var text := "PERF " + JSON.stringify(row)
	print(text)
	if _file != null:
		_file.store_line(JSON.stringify(row))
		_file.flush()

func _report() -> void:
	var worst := 0.0
	var worst_label := ""
	for row in _rows:
		if String(row["label"]) == "anim-off":
			continue
		if float(row["p95_ms"]) > worst:
			worst = float(row["p95_ms"])
			worst_label = String(row["label"])
	print("PERF RESULT stops=%d worst_p95_ms=%.1f at=%s quality=%s" % [
		_rows.size(), worst, worst_label, _quality])
