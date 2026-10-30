extends SceneTree

## Performance probe (a measuring tool, not a test). It joins a local dev world
## server through the real login path (main_menu --dev-join) and measures what a
## player feels: frame times and the frames that hitch, GPU time, pipelines
## compiled in play, downstream bytes, snapshot arrivals, ping, and how evenly
## the other bodies move on screen.
##
##   .\dev.ps1 perf [-Bots 8] [-Char 30]        server + walking bots + this probe
##
## Run by hand against a server started with HPMMO_ALLOW_DEV_JOIN=1:
##   godot --path client -s res://tools/capture/perf_probe.gd --dev-join=Probe --port 7793 [--out=file.json]
##   ... --walker      a bot instead (run it --headless): walks a stop-and-go
##                     circle for --seconds (default 150) so the probe has
##                     moving bodies to watch.
## The --dev-join/--port arguments go BEFORE any `--`: main_menu reads them
## from the engine's own argument list.
##
## Phases (seconds): idle 10, turn 10 (camera sweep), run 15 (circle), ab 24
## (standing; every 2 s it switches between everything on, the other wizards'
## cloak springs off, their animation trees off, and the other wizards hidden
## - the same run, so heat drift cancels out: the PERF ab lines give each
## variant's mean frame, process and GPU time), combat 30 (targets the nearest creature and casts the
## hotbar spells in turn). Section timers (HPProf) are on, and each phase
## prints its `prof` line.
## Every phase prints one PERF line; frames over 33 ms are listed with what
## happened in them (pipelines compiled, nodes added, physics/process time).
## VSync is off so the frame times are the real cost, not the monitor's; the
## game's own frame cap (Settings, 60 by default) stays unless --max-fps=N
## (0 = uncapped) overrides it.

const SETTLE_S := 10.0
const JOIN_TIMEOUT_MS := 180000
const PHASES := [["idle", 10.0], ["turn", 10.0], ["run", 15.0], ["ab", 24.0], ["combat", 30.0]]
const AB_VARIANTS := ["all_on", "cloaks_off", "all_on", "anim_off", "all_on", "hidden"]
const AB_WINDOW_S := 2.0
const SPELLS := ["basic_cast", "stupefy", "incendio", "basic_cast", "bombarda", "expelliarmus", "basic_cast", "ultimate"]
const PIPELINE_INFOS := [
	RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_CANVAS,
	RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_MESH,
	RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_SURFACE,
	RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_DRAW,
	RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_SPECIALIZATION,
]

var _walker := false
var _walker_s := 150.0
var _out := ""
var _max_fps := -1
var _player: Node3D = null
var _settle := 0.0
var _phase := -1
var _phase_t := 0.0
var _last_us := 0
var _results: Array = []

# per-phase samples
var _frames: Array = []
var _spikes: Array = []
var _gpu := 0.0
var _pipe0 := 0
var _last_pipe := 0
var _last_nodes := 0
var _pings: Array = []
var _snaps := 0
var _last_snap := -1
var _in_bytes := 0
var _judder: Array = []
var _prev_pos: Dictionary = {}
var _prev_speed: Dictionary = {}
var _cast_wait := 0.0
var _cast_i := 0
var _ab: Dictionary = {}          # variant -> [frames, frame ms sum, process ms sum, gpu ms sum]
var _ab_variant := ""


func _initialize() -> void:
	for arg in OS.get_cmdline_args() + OS.get_cmdline_user_args():
		if arg == "--walker":
			_walker = true
		elif arg.begins_with("--seconds="):
			_walker_s = float(arg.substr(10))
		elif arg.begins_with("--out="):
			_out = arg.substr(6)
		elif arg.begins_with("--max-fps="):
			_max_fps = int(arg.substr(10))
	change_scene_to_file.call_deferred("res://scenes/main/main_menu.tscn")


func _process(delta: float) -> bool:
	var now := Time.get_ticks_usec()
	var dt_ms := float(now - _last_us) / 1000.0 if _last_us != 0 else 0.0
	_last_us = now
	var auth = root.get_node_or_null("SimAuthority")
	if auth == null:
		return false
	if _player == null or not is_instance_valid(_player):
		var p = auth.local_player_node()
		if p == null or not is_instance_valid(p) or not (p as Node).is_inside_tree():
			if Time.get_ticks_msec() > JOIN_TIMEOUT_MS:
				printerr("PERF failed: no player in the world after %d s" % (JOIN_TIMEOUT_MS / 1000))
				quit(1)
			return false
		_player = p
	if _walker:
		_walk(delta)
		return false
	if _phase < 0:
		_settle += delta
		if _settle >= SETTLE_S:
			DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
			if _max_fps >= 0:
				Engine.max_fps = _max_fps
			RenderingServer.viewport_set_measure_render_time(root.get_viewport_rid(), true)
			for n in root.find_children("*", "", true, false):
				var script = n.get_script()
				if script != null and String(script.resource_path).ends_with("hud_skill_pick.gd"):
					n.queue_free()
			HPProf.enabled = true
			_start_phase(0)
		return false
	_sample(dt_ms, now, auth)
	_drive(dt_ms / 1000.0)
	_phase_t += dt_ms / 1000.0
	if _phase_t >= float(PHASES[_phase][1]):
		_finish_phase()
		if _phase + 1 < PHASES.size():
			_start_phase(_phase + 1)
		else:
			_finish()
	return false


## Bot: a stop-and-go circle (5.5 s walking, 1.5 s standing) - the stops are
## where a remote body overshoots or jerks if its interpolation is off.
func _walk(delta: float) -> void:
	_settle += delta
	_player.set("camera_rot_y", float(_player.get("camera_rot_y")) + 40.0 * delta)
	var stop := fmod(_settle, 7.0) > 5.5
	root.get_node("SimNet").forced_intent = {"move": Vector2.ZERO if stop else Vector2(0, -1),
		"yaw": float(_player.get("camera_rot_y")), "jump": false, "descend": false}
	if _settle >= _walker_s:
		quit(0)


func _start_phase(index: int) -> void:
	_phase = index
	_phase_t = 0.0
	_frames.clear()
	_spikes.clear()
	_pings.clear()
	_judder.clear()
	_prev_pos.clear()
	_prev_speed.clear()
	_gpu = 0.0
	_snaps = 0
	_in_bytes = 0
	_pipe0 = _pipeline_count()
	_last_pipe = _pipe0
	_last_nodes = int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	var host = _host()
	if host != null:
		host.pop_statistic(ENetConnection.HOST_TOTAL_RECEIVED_DATA)
	root.get_node("SimNet").forced_intent = {}
	HPProf.report()   # a fresh window per phase
	_ab.clear()
	_ab_variant = ""


func _sample(dt_ms: float, now_us: int, auth) -> void:
	_frames.append(dt_ms)
	_gpu += RenderingServer.viewport_get_measured_render_time_gpu(root.get_viewport_rid())
	var pipes := _pipeline_count()
	var nodes := int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	if dt_ms > 33.0:
		_spikes.append("%.0fms@%.1fs pipelines+%d nodes%+d process=%.1f physics=%.1f" % [dt_ms, _phase_t,
			pipes - _last_pipe, nodes - _last_nodes,
			Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0,
			Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0])
	_last_pipe = pipes
	_last_nodes = nodes
	if int(auth.snapshot_tick) != _last_snap:
		_last_snap = int(auth.snapshot_tick)
		_snaps += 1
	if _frames.size() % 15 == 0:
		_pings.append(root.get_node("SimNet").ping_ms())
	var host = _host()
	if host != null:
		_in_bytes += int(host.pop_statistic(ENetConnection.HOST_TOTAL_RECEIVED_DATA))
	# Judder: how much a moving remote body's on-screen speed changes from one
	# frame to the next (0 = perfectly even). Bodies under 1 m/s are skipped.
	var dt_s := maxf(dt_ms / 1000.0, 0.001)
	for body in get_nodes_in_group("players") + get_nodes_in_group("mobs"):
		if not (body is Node3D) or not body.get("sim_puppet"):
			continue
		var id: int = body.get_instance_id()
		var pos := (body as Node3D).global_position
		if _prev_pos.has(id):
			var speed := (pos - (_prev_pos[id] as Vector3)).length() / dt_s
			if _prev_speed.has(id) and float(_prev_speed[id]) > 1.0:
				_judder.append(absf(speed - float(_prev_speed[id])) / float(_prev_speed[id]))
			_prev_speed[id] = speed
		_prev_pos[id] = pos


func _drive(dt_s: float) -> void:
	var name: String = PHASES[_phase][0]
	var net = root.get_node("SimNet")
	match name:
		"turn":
			_player.set("camera_rot_y", float(_player.get("camera_rot_y")) + 36.0 * dt_s)
		"run":
			_player.set("camera_rot_y", float(_player.get("camera_rot_y")) + 12.0 * dt_s)
			net.forced_intent = {"move": Vector2(0, -1), "yaw": float(_player.get("camera_rot_y")),
				"jump": false, "descend": false}
		"combat":
			_fight(dt_s, net)
		"ab":
			var variant: String = AB_VARIANTS[int(_phase_t / AB_WINDOW_S) % AB_VARIANTS.size()]
			if variant != _ab_variant:
				_ab_variant = variant
				_set_remote_heroes(variant != "cloaks_off", variant != "anim_off", variant != "hidden")
			elif fmod(_phase_t, AB_WINDOW_S) > 0.3:   # skip the switch's own frames
				var row: Array = _ab.get_or_add(variant, [0, 0.0, 0.0, 0.0])
				row[0] += 1
				row[1] += dt_s * 1000.0
				row[2] += Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0
				row[3] += RenderingServer.viewport_get_measured_render_time_gpu(root.get_viewport_rid())


## The other wizards' cloak springs, animation trees and visibility (ab phase).
func _set_remote_heroes(cloaks: bool, anim: bool, shown := true) -> void:
	for body in get_nodes_in_group("players"):
		if not body.get("sim_puppet"):
			continue
		(body as Node3D).visible = shown
		for deformer in (body as Node).find_children("*", "", true, false):
			var script = deformer.get_script()
			if script != null and String(script.resource_path).ends_with("cloak_deformer.gd"):
				deformer.set_process(cloaks)
				var springs = deformer.get("springs")
				if springs != null:
					springs.active = cloaks
		var hero_anim = body.get("hero_anim")
		if hero_anim != null and hero_anim.get("tree") != null:
			(hero_anim.get("tree") as AnimationTree).active = anim


## Target the nearest live creature; close in to casting range, then cast the
## hotbar spells in turn (whatever is on cooldown is simply refused).
func _fight(dt_s: float, net) -> void:
	var target: Node3D = null
	var best := 45.0
	for mob in get_nodes_in_group("mobs"):
		if not (mob is Node3D) or int(mob.get("current_hp")) <= 0:
			continue
		var d := (mob as Node3D).global_position.distance_to(_player.global_position)
		if d < best:
			best = d
			target = mob
	if target == null:
		net.forced_intent = {}
		return
	if _player.get("current_target") != target:
		_player.call("set_target", target)
	var to := target.global_position - _player.global_position
	var yaw := rad_to_deg(atan2(-to.x, -to.z))
	_player.set("camera_rot_y", yaw)
	net.forced_intent = {"move": Vector2(0, -1) if best > 16.0 else Vector2.ZERO, "yaw": yaw,
		"jump": false, "descend": false}
	_cast_wait -= dt_s
	if best <= 20.0 and _cast_wait <= 0.0:
		_cast_wait = 0.6
		_player.call("cast_spell", SPELLS[_cast_i % SPELLS.size()])
		_cast_i += 1


func _finish_phase() -> void:
	var sorted := _frames.duplicate()
	sorted.sort()
	var count := sorted.size()
	var total := 0.0
	var over33 := 0
	var over50 := 0
	for f in sorted:
		total += f
		over33 += 1 if f > 33.0 else 0
		over50 += 1 if f > 50.0 else 0
	var pings := _pings.filter(func(p): return p >= 0)
	pings.sort()
	var judder := _judder.duplicate()
	judder.sort()
	var result := {
		"phase": PHASES[_phase][0], "frames": count,
		"mean_ms": total / maxf(1, count), "p50_ms": _pick(sorted, 0.5), "p95_ms": _pick(sorted, 0.95),
		"p99_ms": _pick(sorted, 0.99), "max_ms": _pick(sorted, 1.0), "over33": over33, "over50": over50,
		"gpu_ms": _gpu / maxf(1, count), "pipelines": _pipeline_count() - _pipe0,
		"in_kBps": _in_bytes / 1024.0 / maxf(0.001, _phase_t), "snaps_s": _snaps / maxf(0.001, _phase_t),
		"ping_avg": _mean(pings), "ping_max": _pick(pings, 1.0),
		"judder_p50": _pick(judder, 0.5), "judder_p90": _pick(judder, 0.9),
		"replicas": _replica_count(), "nodes": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)),
		"draws": int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
		"primitives": int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),
		"spikes": _spikes.slice(0, 10),
	}
	_results.append(result)
	print("PERF %-7s frames=%d mean=%.2f p50=%.2f p95=%.2f p99=%.2f max=%.1f >33ms=%d >50ms=%d gpu=%.2f pipelines=%d in=%.1fKB/s snaps=%.1f/s ping=%.0f/%.0f judder=%.3f/%.3f replicas=%d nodes=%d draws=%d prims=%d" % [
		result.phase, count, result.mean_ms, result.p50_ms, result.p95_ms, result.p99_ms, result.max_ms,
		over33, over50, result.gpu_ms, result.pipelines, result.in_kBps, result.snaps_s,
		result.ping_avg, result.ping_max, result.judder_p50, result.judder_p90, result.replicas,
		result.nodes, result.draws, result.primitives])
	for spike in result.spikes:
		print("PERF   spike ", spike)
	print("PERF   prof ", HPProf.report())
	if PHASES[_phase][0] == "ab":
		_set_remote_heroes(true, true)
		for variant in _ab:
			var row: Array = _ab[variant]
			print("PERF   ab %-10s frames=%d frame=%.2f ms process=%.2f ms gpu=%.2f ms" % [variant, row[0],
				row[1] / maxf(1, row[0]), row[2] / maxf(1, row[0]), row[3] / maxf(1, row[0])])


func _finish() -> void:
	root.get_node("SimNet").forced_intent = {}
	if _out != "":
		var file := FileAccess.open(_out, FileAccess.WRITE)
		if file != null:
			file.store_string(JSON.stringify({"gpu": RenderingServer.get_video_adapter_name(),
				"phases": _results}, "  "))
	print("PERF done")
	quit(0)


func _replica_count() -> int:
	var count := 0
	for body in get_nodes_in_group("players") + get_nodes_in_group("mobs"):
		if body.get("sim_puppet"):
			count += 1
	return count


func _host():
	var peer = root.get_node("SimNet").multiplayer.multiplayer_peer
	return (peer as ENetMultiplayerPeer).host if peer is ENetMultiplayerPeer else null


static func _pick(sorted: Array, q: float) -> float:
	if sorted.is_empty():
		return -1.0
	return float(sorted[mini(sorted.size() - 1, int(sorted.size() * q))])


static func _mean(values: Array) -> float:
	if values.is_empty():
		return -1.0
	var total := 0.0
	for v in values:
		total += float(v)
	return total / values.size()


static func _pipeline_count() -> int:
	var total := 0
	for info in PIPELINE_INFOS:
		total += int(RenderingServer.get_rendering_info(info))
	return total
