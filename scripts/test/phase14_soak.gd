extends Node

## Phase 14 soak (plan.md Phase 14: "Run a minimum one-hour representative soak
## plus repeated map entry/exit, mass casts, pack deaths/respawns, and mount
## cycles. Memory must not grow continually after expected caches warm up.").
##
## It is a REAL client: the ordinary world scene, the ordinary transport, the
## ordinary intents and reconciliation. Only the keyboard is replaced by a
## script (the same `SimNet.forced_intent` hook `net_client_probe.gd` uses).
##
## Loop: mass cast in the courtyard -> kill the nearest pack -> mount, fly and
## land -> walk through the castle door into the interior and back out -> repeat.
##
## Every SAMPLE_INTERVAL seconds it writes one JSON line to `--out=`:
##
##   {"t": 123.4, "phase": "fight", "static_mib": ..., "tex_mib": ...,
##    "nodes": ..., "orphans": ..., "resources": ..., "objects": ...,
##    "entities": ..., "draw_calls": ..., "prims": ..., "fps": ...,
##    "casts": ..., "kills": ..., "transfers": ..., "mounts": ...}
##
## and prints the same line on stdout so a detached run's log carries the curve.
##
## Usage (client process; the server is a separate process):
##   godot --path client res://scenes/test/phase14_soak.tscn -- \
##     --port=7777 --name=Soak --seconds=3900 --out=soak.jsonl --spawn="0,0.6,5"

const WORLD_SCENE = preload("res://scenes/world/game_world.tscn")
const HPStaircase = preload("res://addons/hpmmo_sim/staircase.gd")

const SAMPLE_INTERVAL := 20.0
const ENGAGE_RANGE := 22.0
const CAST_SPELLS := ["basic_cast", "stupefy", "incendio", "bombarda", "expelliarmus", "protego", "ultimate"]
## Watchdog: no phase may stall the loop. A phase that hits its ceiling is
## abandoned and the next one starts, so one bad step cannot eat the whole soak.
const PHASE_MAX := {
	"cast": 30.0, "fight": 60.0, "mount": 34.0, "map": 150.0, "walk_back": 15.0,
}
const PHASE_ORDER := ["cast", "fight", "mount", "map", "walk_back"]
const HEARTBEAT_INTERVAL := 30.0
const COURTYARD := Vector3(0.0, 0.6, 5.0)

var port := 7777
var probe_name := "Soak"
var out_path := ""
var duration := 3900.0
var dev_spawn := ""

var world: Node3D = null
var player: Node3D = null
var map_controller: Node = null
var staircase: Node3D = null

var _t := 0.0
var _joined := false
var _done := false
var _phase := "boot"
var _phase_t := 0.0
var _sample_t := 0.0
var _heartbeat_t := 0.0

# counters
var _casts_sent := 0
var _casts_accepted := 0
var _kills := 0
var _respawns := 0
var _transfers := 0
var _mounts := 0
var _deaths := 0
var _rewards := 0
var _phase_runs := {}

# per-phase state
var _cast_index := 0
var _cast_timer := 0.0
var _target_pack := 0
var _target_uid := 0
var _pack_uids: Array = []
var _fight_started := 0.0
var _mount_state := 0
var _mount_timer := 0.0
var _deck_ride := false
var _stair_done := false
var _deck_min_y := 0.0
var _deck_max_y := 0.0
var _last_pos := Vector3.ZERO
var _stuck_timer := 0.0
var _sidestep_timer := 0.0
var _transfer_requested := false
var _sample_file: FileAccess = null
var _errors: Array = []

func _ready() -> void:
	_parse_args()
	if out_path != "":
		_sample_file = FileAccess.open(out_path, FileAccess.WRITE)
	SimAuthority.configure(SimAuthority.Role.CLIENT)
	world = WORLD_SCENE.instantiate()
	add_child(world)
	await get_tree().process_frame
	player = world.get("local_player")
	map_controller = world.get("map_controller")
	SimNet.joined.connect(_on_joined)
	SimAuthority.entity_died.connect(_on_died)
	SimAuthority.entity_respawned.connect(_on_respawn)
	SimAuthority.reward_granted.connect(func(_uid: int, _character_id: int, _exp: int, _g: int, _items: Array, _op: String):
		_rewards += 1)
	var err := SimNet.join("127.0.0.1", port, probe_name)
	if err != OK:
		_fail("join failed: %d" % err)
		return
	print("[Soak] joining 127.0.0.1:%d as %s, %.0f s" % [port, probe_name, duration])

func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--port="):
			port = int(arg.substr(7))
		elif arg.begins_with("--name="):
			probe_name = arg.substr(7)
		elif arg.begins_with("--seconds="):
			duration = float(arg.substr(10))
		elif arg.begins_with("--out="):
			out_path = arg.substr(6)
		elif arg.begins_with("--spawn="):
			dev_spawn = arg.substr(8)

func _fail(message: String) -> void:
	_errors.append(message)
	print("SOAK ERROR: " + message)
	_finish(1)

func _on_joined(ok: bool, reason: String, _character: Dictionary) -> void:
	_joined = ok
	print("[Soak] joined=%s reason=%s uid=%d" % [ok, reason, SimAuthority.local_uid])
	if not ok:
		_fail("join refused: " + reason)
		return
	_last_pos = player.global_position if player != null else Vector3.ZERO
	_set_phase("cast")

func _on_died(uid: int, _killer: int) -> void:
	if SimAuthority.entities.has(uid) and int(SimAuthority.entities[uid].get("kind", 0)) == HPProtocol.Kind.MOB:
		_kills += 1
	elif uid == SimAuthority.local_uid:
		_deaths += 1

func _on_respawn(uid: int) -> void:
	if SimAuthority.entities.has(uid) and int(SimAuthority.entities[uid].get("kind", 0)) == HPProtocol.Kind.MOB:
		_respawns += 1

func _set_phase(name: String) -> void:
	_phase = name
	_phase_t = _t
	_phase_runs[name] = int(_phase_runs.get(name, 0)) + 1
	match name:
		"cast":
			_cast_index = 0
			_cast_timer = 0.0
		"fight":
			_fight_started = _t
			_target_pack = 0
			_target_uid = 0
			_pack_uids.clear()
		"mount":
			_mount_state = 0
			_mount_timer = 0.0
		"map":
			_transfer_requested = false
			_deck_ride = false
			_stair_done = false
			_find_staircase()
		"walk_back":
			_transfer_requested = false
	print("[Soak] phase -> %s (t=%.1f)" % [name, _t])

func _physics_process(delta: float) -> void:
	if _done:
		return
	_t += delta
	if not _joined:
		return
	_sample_t += delta
	if _sample_t >= SAMPLE_INTERVAL:
		_sample_t = 0.0
		_sample()
	_heartbeat_t += delta
	if _heartbeat_t >= HEARTBEAT_INTERVAL:
		_heartbeat_t = 0.0
		var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
		print("[Soak] HB t=%.0f phase=%s pos=%s hp=%s map=%s" % [
			_t, _phase, str(_auth_pos().round()), str(record.get("hp", -1)),
			str(record.get("map_id", "?"))])

	# Watchdog: never let one phase eat the run.
	var ceiling: float = float(PHASE_MAX.get(_phase, 60.0))
	if _t - _phase_t > ceiling:
		var index := PHASE_ORDER.find(_phase)
		var next: String = String(PHASE_ORDER[(index + 1) % PHASE_ORDER.size()]) if index >= 0 else "cast"
		print("[Soak] watchdog: %s exceeded %.0f s, moving to %s" % [_phase, ceiling, next])
		_set_phase(next)

	match _phase:
		"cast":
			_cast_tick(delta)
		"fight":
			_fight_tick(delta)
		"mount":
			_mount_tick(delta)
		"map":
			_map_tick(delta)
		"walk_back":
			_walk_back_tick(delta)

	if _t >= duration:
		_finish(0)

# ------------------------------------------------------------------ movement

func _walk_toward(goal: Vector3) -> bool:
	if player == null or not is_instance_valid(player):
		return false
	var flat := goal - player.global_position
	flat.y = 0.0
	if flat.length() <= 1.2 and absf(goal.y - player.global_position.y) < 2.5:
		SimNet.forced_intent = {}
		return true
	var moved := _last_pos.distance_to(player.global_position)
	if moved > 0.05:
		_stuck_timer = 0.0
	else:
		_stuck_timer += get_physics_process_delta_time()
	if _stuck_timer > 1.0:
		_sidestep_timer = 2.0
		_stuck_timer = 0.0
	var angle_offset := 0.0
	var jump := false
	if _sidestep_timer > 0.0:
		_sidestep_timer -= get_physics_process_delta_time()
		angle_offset = deg_to_rad(90.0)
		jump = fmod(_sidestep_timer, 0.5) > 0.25
	_last_pos = player.global_position
	var direction := flat.rotated(Vector3.UP, angle_offset)
	# A mounted walk that is still above its goal keeps descending: a rider left
	# hovering by a refused dismount would otherwise never reach the ground
	# (dismount needs level ground within 3 m).
	var mounted := bool(SimAuthority.entities.get(SimAuthority.local_uid, {}).get("mounted", false))
	var descend := mounted and (player.global_position.y - goal.y) > 2.5
	SimNet.forced_intent = {
		"move": Vector2(0, -1),
		"yaw": rad_to_deg(atan2(-direction.x, -direction.z)),
		"jump": jump,
		"descend": descend,
	}
	return false

func _auth_pos() -> Vector3:
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var pos: Variant = record.get("pos", null)
	if pos is Vector3:
		return pos
	if player != null and is_instance_valid(player):
		return player.global_position
	return Vector3.ZERO

# ---------------------------------------------------------------------- cast

func _cast_tick(_delta: float) -> void:
	# Stand in the courtyard and cycle every spell. Rejected casts (cooldown,
	# mana) are normal play, not failures; the counters record both.
	if player == null or not is_instance_valid(player):
		_set_phase("fight")
		return
	SimNet.forced_intent = {}
	_cast_timer -= get_physics_process_delta_time()
	if _cast_timer <= 0.0:
		_cast_timer = 0.45
		var spell: String = CAST_SPELLS[_cast_index % CAST_SPELLS.size()]
		_cast_index += 1
		_casts_sent += 1
		var aim := player.global_position + Vector3(0, 1.0, -8.0)
		var result := SimNet.submit_cast(player, spell, aim, _casts_sent)
		if bool(result.get("ok", false)):
			_casts_accepted += 1
	if _t - _phase_t >= 14.0:
		_set_phase("fight")

# --------------------------------------------------------------------- fight

## Nearest live pack (deterministic: the pack whose lowest-uid member is
## closest), then the lowest-uid live member.
func _choose_pack() -> int:
	var packs: Dictionary = {}
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) != HPProtocol.Kind.MOB:
			continue
		var pack_id := int(record.get("pack_id", 0))
		if pack_id == 0:
			continue
		if not packs.has(pack_id) or int(uid) < int(packs[pack_id]["uid"]):
			packs[pack_id] = {"uid": int(uid), "pos": record.get("pos", Vector3.ZERO)}
	var best := 0
	var best_distance := 1e9
	var from := _auth_pos()
	for pack_id in packs.keys():
		var distance: float = from.distance_to(packs[pack_id]["pos"])
		if distance < best_distance:
			best_distance = distance
			best = int(pack_id)
	return best

func _pack_members(pack_id: int) -> Array:
	var members: Array = []
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) == HPProtocol.Kind.MOB and int(record.get("pack_id", 0)) == pack_id:
			members.append(int(uid))
	members.sort()
	return members

func _is_dead(uid: int) -> bool:
	var record: Dictionary = SimAuthority.entities.get(uid, {})
	if record.is_empty():
		return true
	return bool(record.get("dead", false)) or int(record.get("hp", 0)) <= 0

## Dead is a normal state in a soak: the authority respawns the body on its own
## timer, and the phase loop simply waits it out rather than pressing on.
func _alive() -> bool:
	if player == null or not is_instance_valid(player):
		return false
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	if bool(record.get("dead", false)):
		return false
	return float(record.get("hp", 1)) > 0.0

func _fight_tick(_delta: float) -> void:
	if player == null or not is_instance_valid(player):
		_set_phase("mount")
		return
	if not _alive():
		SimNet.forced_intent = {}
		if _t - _fight_started > 50.0:
			_set_phase("mount")
		return
	if _target_pack == 0:
		_target_pack = _choose_pack()
		if _target_pack == 0:
			_set_phase("mount")
			return
		_pack_uids = _pack_members(_target_pack)
	if _pack_uids.is_empty():
		_set_phase("mount")
		return
	# Keep a live target in this pack.
	if _target_uid != 0 and not _is_dead(_target_uid):
		pass
	else:
		_target_uid = 0
		for uid in _pack_uids:
			if not _is_dead(uid):
				_target_uid = int(uid)
				break
	if _target_uid == 0:
		# Whole pack down (or all removed): the loop moves on; the respawn is
		# observed through the authority signal whenever it happens in range.
		_set_phase("mount")
		return
	var target: Vector3 = SimAuthority.entities[_target_uid].get("pos", Vector3.ZERO)
	var flat := target - (_auth_pos() + Vector3(0, -0.1, 0))
	flat.y = 0.0
	if flat.length() > ENGAGE_RANGE * 0.8:
		_walk_toward(target)
		return
	SimNet.forced_intent = {}
	if _t - _phase_t > 0.5 and int(SimAuthority.sim_tick) % 10 == 0:
		_casts_sent += 1
		var result := SimNet.submit_cast(player, "basic_cast", target + Vector3.UP, _casts_sent)
		if bool(result.get("ok", false)):
			_casts_accepted += 1
	if _t - _fight_started > 50.0:
		_set_phase("mount")

# --------------------------------------------------------------------- mount

## Bounded mount cycle: request, fly (climb, cruise toward the castle, descend),
## request dismount, move on - whatever the server answered. Repeated by the
## phase cycle, so a refused mount costs one cycle, not the soak.
func _mount_tick(_delta: float) -> void:
	if player == null or not is_instance_valid(player):
		_set_phase("map")
		return
	if not _alive():
		SimNet.forced_intent = {}
		if _t - _phase_t > 8.0:
			_set_phase("map")
		return
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var mounted: bool = bool(record.get("mounted", false))
	_mount_timer -= get_physics_process_delta_time()
	var elapsed := _t - _phase_t
	var to_yard := COURTYARD - _auth_pos()
	to_yard.y = 0.0
	var yaw := rad_to_deg(atan2(-to_yard.x, -to_yard.z))
	match _mount_state:
		0:
			# Ask once, then wait: a repeat asks the server a question it has
			# already answered.
			if _mount_timer <= 0.0:
				SimNet.submit_mount(player, true)
				_mount_timer = 6.0
				_mount_state = 1
		1:
			if mounted:
				_mounts += 1
				_mount_state = 2
			elif _mount_timer <= 0.0:
				_mount_state = 3   # refused (not on the ground / no flight here)
		2:
			# Climb, cruise toward the courtyard, then descend to landing height.
			if elapsed < 12.0:
				SimNet.forced_intent = {"move": Vector2(0, -1), "yaw": yaw, "jump": true, "descend": false}
			elif elapsed < 18.0:
				SimNet.forced_intent = {"move": Vector2(0, -1), "yaw": yaw, "jump": false, "descend": false}
			else:
				SimNet.forced_intent = {"move": Vector2.ZERO, "yaw": yaw, "jump": false, "descend": true}
				if elapsed >= 22.0:
					_mount_state = 3
		3:
			# Dismount needs level ground within 3 m, so keep descending and keep
			# asking until the server agrees (or the phase watchdog ends it).
			if not mounted:
				_set_phase("map")
				return
			SimNet.forced_intent = {"move": Vector2.ZERO, "yaw": yaw, "jump": false, "descend": true}
			if _mount_timer <= 0.0:
				_mount_timer = 1.2
				SimNet.submit_mount(player, false)

# ----------------------------------------------------------------------- map

func _find_staircase() -> void:
	staircase = null
	for node in get_tree().get_nodes_in_group("staircases"):
		staircase = node
		return
	var root := get_tree().current_scene if get_tree().current_scene != null else self
	var found := _find_by_method(world)
	if found != null:
		staircase = found

func _find_by_method(node: Node) -> Node3D:
	if node.has_method("platform_world_transform") and node.has_method("entry_allowed"):
		return node as Node3D
	for child in node.get_children():
		var hit := _find_by_method(child)
		if hit != null:
			return hit
	return null

func _map_tick(_delta: float) -> void:
	if player == null or not is_instance_valid(player):
		_set_phase("cast")
		return
	if not _alive():
		SimNet.forced_intent = {}
		if _t - _phase_t > 8.0:
			_set_phase("cast")
		return
	var map_id := String(SimAuthority.entities.get(SimAuthority.local_uid, {}).get("map_id", "grounds"))
	var busy := map_controller != null and bool(map_controller.get("busy"))
	if map_id == "grounds":
		if busy:
			return
		var door := HPMaps.portal("castle_door")
		var centre := _portal_center(door)
		if SimAuthority.entities.get(SimAuthority.local_uid, {}).get("mounted", false):
			SimNet.submit_mount(player, false)
			return
		if _auth_pos().distance_to(centre) > 2.0:
			_walk_toward(centre)
			return
		SimNet.forced_intent = {}
		if not _transfer_requested:
			_transfer_requested = true
			var result := SimNet.request_transfer(player, "castle_door", "castle_interior")
			print("[Soak] transfer requested: %s" % JSON.stringify(result.get("reason", "ok")))
		if _t - _phase_t > 25.0:
			_set_phase("cast")
		return
	# Inside the castle: try the moving staircase once (bounded), then leave.
	if staircase == null:
		_find_staircase()
	if staircase != null and not _stair_done:
		if _t - _phase_t > 35.0:
			_stair_done = true
			print("[Soak] staircase: giving up this cycle")
		else:
			_deck_tick()
			return
	if _t - _phase_t > 8.0 or _stair_done:
		var exit_portal := HPMaps.portal("vestibule_exit")
		var exit_centre := _portal_center(exit_portal)
		if _auth_pos().distance_to(exit_centre) > 2.0:
			_walk_toward(exit_centre)
			return
		SimNet.forced_intent = {}
		if not _transfer_requested:
			_transfer_requested = true
			_transfers += 1
			SimNet.request_transfer(player, "vestibule_exit", "grounds")
		if _t - _phase_t > 30.0:
			_set_phase("cast")
		return

## Board the magical staircase while it is docked, ride it, and step off.
func _deck_tick() -> void:
	var tick := int(SimAuthority.sim_tick)
	if staircase == null or not is_instance_valid(staircase):
		return
	if not bool(staircase.get("is_authority_runtime")) and staircase.has_method("entry_allowed") == false:
		return
	if not _deck_ride and staircase.get("entry_allowed") and int(staircase.get("dock_index")) == 0:
		var deck := _deck_point(tick, 0.35)
		if _auth_pos().distance_to(deck) > 1.5:
			_walk_toward(deck)
			return
		SimNet.forced_intent = {}
		_deck_ride = true
		_deck_min_y = _auth_pos().y
		_deck_max_y = _auth_pos().y
		return
	if _deck_ride:
		SimNet.forced_intent = {}
		var y := _auth_pos().y
		_deck_min_y = minf(_deck_min_y, y)
		_deck_max_y = maxf(_deck_max_y, y)
		if String(staircase.get("state")) == "docked" and int(staircase.get("dock_index")) > 0:
			# Rode it up: done with the floors for this cycle.
			_deck_ride = false
			_stair_done = true
			_transfers += 1
			print("[Soak] staircase ride: y %.1f -> %.1f" % [_deck_min_y, _deck_max_y])
			_set_phase("walk_back")

func _deck_point(tick: int, along: float) -> Vector3:
	var run: float = staircase.call("run_length")
	var slope: float = staircase.call("slope")
	var transform: Transform3D = staircase.call("platform_world_transform", tick)
	return transform * Vector3(0.0, run * along * slope + 0.05, run * along)

func _portal_center(entry: Dictionary) -> Vector3:
	var trigger: Dictionary = entry.get("trigger", {})
	var centre: Array = trigger.get("center", [])
	if centre.size() != 3:
		return _auth_pos()
	return Vector3(float(centre[0]), float(centre[1]) - 0.5, float(centre[2]))

func _walk_back_tick(_delta: float) -> void:
	if _t - _phase_t > 3.0:
		_set_phase("cast")

# ------------------------------------------------------------------ sampling

func _sample() -> void:
	var line := {
		"t": snappedf(_t, 0.1),
		"phase": _phase,
		"static_mib": OS.get_static_memory_usage() / 1048576.0,
		"mem_mib": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"tex_mib": Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED) / 1048576.0,
		"vid_mib": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"nodes": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
		"orphans": Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
		"resources": Performance.get_monitor(Performance.OBJECT_RESOURCE_COUNT),
		"objects": Performance.get_monitor(Performance.OBJECT_COUNT),
		"entities": SimAuthority.entities.size(),
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		"prims": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME),
		"fps": Engine.get_frames_per_second(),
		"casts_sent": _casts_sent,
		"casts_ok": _casts_accepted,
		"kills": _kills,
		"respawns": _respawns,
		"transfers": _transfers,
		"mounts": _mounts,
		"deaths": _deaths,
		"rewards": _rewards,
	}
	var text := "SOAK " + JSON.stringify(line)
	print(text)
	if _sample_file != null:
		_sample_file.store_line(JSON.stringify(line))
		_sample_file.flush()

func _finish(code: int) -> void:
	if _done:
		return
	_done = true
	_sample()
	var summary := {
		"event": "final",
		"seconds": snappedf(_t, 0.1),
		"phases": _phase_runs,
		"casts_sent": _casts_sent,
		"casts_ok": _casts_accepted,
		"kills": _kills,
		"respawns": _respawns,
		"transfers": _transfers,
		"mounts": _mounts,
		"deaths": _deaths,
		"rewards": _rewards,
		"orphans": Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
		"errors": _errors,
	}
	print("SOAK RESULT " + JSON.stringify(summary))
	if _sample_file != null:
		_sample_file.store_line(JSON.stringify(summary))
		_sample_file.close()
	SimNet.leave()
	get_tree().quit(code)
