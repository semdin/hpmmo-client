extends Node

## Headless client probe for the Phase 5 multiplayer tests (test-only; not part
## of the world export and not part of the 93-check single-player harness).
##
## It is a REAL client: same transport, same intents, same reconciliation as the
## game. It only replaces the keyboard and the mouse with a script, and writes
## what it observed as JSON lines so the Python orchestrator can compare two
## independent clients.
##
## Usage:
##   godot --headless --path client res://scenes/test/net_client_probe.tscn -- \
##     --mode=agree|forged|protection|maintenance|transfer --port=7777 --name=Alice \
##     --out=<file> [--seconds=25] [--admin-port=8082] [--scenario=observer]
##
## The `maintenance` mode (Phase 6) joins, records every SimAuthority
## maintenance signal, polls the admin API for the published state, keeps trying
## to cast, and writes a transcript when the server disconnects it. Its token is
## read from HPMMO_SERVICE_TOKEN and is never recorded or printed.
##
## The `transfer` mode (Phase 8) drives the server-authorized map exchange with
## `--scenario=`:
##   observer   stay put and report the map plus every entity this client was
##              sent (cross-map invisibility needs two of these, one per map)
##   teleport   observer + a client-side teleport claim across maps + forged
##              transfer RPCs; the server must correct, not obey
##   happy      request the door the character stands at, let the real map
##              controller load and acknowledge, and report the commit
##   opposite   same as happy; the direction comes from the saved character
##   full       request a destination that is expected to refuse (capacity)
##   interrupt  request, then exit the process the moment the grant arrives
##   expire     request and never acknowledge; watch the reservation expire,
##              then prove the body can move and request again
##   mounted    mount, then request entry into a flight-prohibited map
##   roundtrips alternate between two maps N times
##   stand      enter the interior like happy, then hold still and sample the
##              server's height (`--stand-seconds`, default 4) and walk straight
##              ahead and sample again (`--walk-seconds`, default 3); the map's
##              collision must keep the body on the interior floor
##   local      in-process authority checks (dead, pending, bad token, ...)

const WORLD_SCENE = preload("res://scenes/world/game_world.tscn")

var mode := "agree"
var port := 7777
var probe_name := "Probe"
var out_path := ""
var duration := 25.0
var admin_port := 0

var world: Node3D = null
var player: Node3D = null
var _records: Array = []
var _t := 0.0
var _joined := false
var _target_uid := 0
var _pack_id := 0
var _pack_uids: Array = []
var _target_seen_hp: Array = []
var _target_death_tick := -1
var _target_initial_hp := -1
var _target_respawn_tick := -1
var _exp_start := -1
var _exp_now := -1
var _rewards: Array = []
var _casts_sent := 0
var _casts_accepted := 0
var _casts_rejected: Array = []
var _pos_samples: Array = []
var _max_step := 0.0
var _max_frame_dt := 0.0
var _last_pos := Vector3.ZERO
var _forged_mob_hp := -1
var _forged_mob_uid := 0
var _own_hp_before := -1
var _forged_mob_died := false
var _hack_until := 0.0
## Forged probe: what the AUTHORITY did with the forged input, measured on the
## server positions this client receives (its snapshots) and normalised by the
## server ticks they span. The rendered body's per-frame step also carries the
## frame duration and the client's reconciliation snap, so it cannot answer
## "did the 50x vector teleport the body?" on its own.
var _max_auth_step_per_tick := 0.0
var _auth_step_samples := 0
var _auth_step_ticks := 0
var _auth_last_tick := -1
var _auth_last_pos := Vector3.ZERO
var _done := false
var _intent_frames := 0
var _server_controlled_seen := false
var _corrections := 0
var _damage_events: Dictionary = {}
var _stuck_timer := 0.0
var _sidestep_timer := 0.0
## Phase 8 staircase probe (mode `staircase`, see _staircase_* below).
var stair_role := "observe"
var staircase: Node3D = null
var _stair_samples: Array = []
var _stair_notices: Array = []
var _stair_events: Array = []
var _stair_ride: Dictionary = {}
var _stair_walk: Dictionary = {}
var _stair_despawns: Array = []
var _walk_check_pos := Vector3.ZERO
var _walk_check_timer := 0.0

## Phase 8 map-transfer probe (mode `transfer`, see the transfer section below).
var scenario := "observer"
## The `--scenario=` argument as given; the encounter mode reads it too, so a
## caller does not have to know which mode's variable it lands in.
var scenario_arg := ""
var transfer_portal := ""
var roundtrips := 2
var teleport_at := 4.0
var _map_id := ""
var _phase := 0
var _phase_at := 0.0
var _transfer_token := 0
var _granted_map := ""
var _granted_spawn := ""
var _commit_map := ""
var _commit_pos := Vector3.ZERO
var _commit_spawn := ""
var _commit_at := -1.0
var _refusal := ""
var _expired := false
var _expiry_moved := -1.0
var _transfer_events: Array = []
var _notices: Array = []
var _transfers_done := 0
var _rt_failed := false
var _rt_state := 0
var _teleported := false
var _teleport_target := Vector3.ZERO
var _teleport_err := -1.0
var _forged_sent := false
var _mount_requested := false
var _mounted_seen := false
var _mount_at := 0.0
var _move_from := Vector3.ZERO
var _move_at := -1.0
var _move_distance := -1.0
var _samples: Array = []
var _local_samples: Array = []
var _auth_samples: Array = []
var _visibility_at := -1.0
## `stand` scenario (interior-collision regression): after the transfer commits,
## hold still and sample the authoritative height, then walk a few metres and
## sample again. Both halves can be disabled with `--stand-seconds` /
## `--walk-seconds` so the two claims are measured by their own run.
var stand_seconds := 4.0
var walk_seconds := 3.0
var _stand_started := false
var _stand_start := 0.0
var _stand_samples: Array = []
var _walk_started := false
var _walk_start := 0.0
var _walk_from := Vector3.ZERO
var _walk_samples: Array = []
var _next_sample_at := 0.0

func _ready() -> void:
	_parse_args()
	# `--scenario=` is shared with the transfer mode; in encounter mode it names
	# the encounter scenario (this is what a caller passes).
	if mode == "encounter" and scenario_arg != "":
		encounter_scenario = scenario_arg
	# Counted in every mode: the protection assertions are written in terms of
	# damage events actually delivered, so the counter must exist there too.
	SimAuthority.entity_damaged.connect(func(uid: int, _amount: int, _hp: int, _spell: String, _attacker: int):
		_damage_events[uid] = int(_damage_events.get(uid, 0)) + 1)
	var local_mode := mode in ["protection", "staircase_failure"] \
		or (mode == "transfer" and scenario == "local") \
		or (mode == "encounter" and scenario == "local")
	SimAuthority.configure(SimAuthority.Role.OFFLINE if local_mode else SimAuthority.Role.CLIENT)
	if mode == "protection":
		_run_protection.call_deferred()
		return
	if mode == "staircase_failure":
		_run_stair_failure.call_deferred()
		return
	if mode == "transfer" and scenario == "local":
		_run_transfer_local.call_deferred()
		return
	if mode == "encounter" and scenario == "local":
		_run_encounter_local.call_deferred()
		return
	player = null
	world = WORLD_SCENE.instantiate()
	add_child(world)
	await get_tree().process_frame
	player = world.get("local_player")
	SimNet.joined.connect(_on_joined)
	SimNet.disconnected.connect(func(reason: String):
		_disconnect_reason = reason
		_left_server = true
		_left_at = _t
		_record("disconnected", {"reason": reason}))
	if mode == "maintenance":
		_setup_maintenance()
	if mode == "transfer":
		_setup_transfer()
	if mode == "encounter":
		_setup_encounter()
	SimAuthority.entity_health.connect(_on_health)
	SimAuthority.entity_died.connect(_on_died)
	SimAuthority.entity_respawned.connect(_on_respawn)
	SimAuthority.stats_changed.connect(_on_stats)
	if not SimAuthority.reward_granted.is_connected(_on_reward):
		SimAuthority.reward_granted.connect(_on_reward)
	SimAuthority.cast_ack.connect(_on_cast_ack)
	SimAuthority.entity_moved.connect(func(uid: int, _pos: Vector3, _rot: float, _flags: int):
		if uid == SimAuthority.local_uid:
			_corrections += 1)
	SimAuthority.cast_landed.connect(func(cast_id: int, _caster: int, spell_id: String, hits: Array):
		if not hits.is_empty():
			_record("landed", {"cast_id": cast_id, "spell": spell_id, "hits": hits.size()}))
	var err := SimNet.join("127.0.0.1", port, probe_name)
	if err != OK:
		_record("error", {"message": "join_failed"})
		_finish(1)
		return
	_record("started", {"mode": mode, "name": probe_name, "port": port,
		"protocol": HPProtocol.PROTOCOL_VERSION})

func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--mode="):
			mode = arg.substr(7)
		elif arg.begins_with("--port="):
			port = int(arg.substr(7))
		elif arg.begins_with("--name="):
			probe_name = arg.substr(7)
		elif arg.begins_with("--out="):
			out_path = arg.substr(6)
		elif arg.begins_with("--seconds="):
			duration = float(arg.substr(10))
		elif arg.begins_with("--admin-port="):
			admin_port = int(arg.substr(13))
		elif arg.begins_with("--stair-role="):
			stair_role = arg.substr(13)
		elif arg.begins_with("--scenario="):
			scenario = arg.substr(11)
			scenario_arg = scenario
		elif arg.begins_with("--portal="):
			transfer_portal = arg.substr(9)
		elif arg.begins_with("--roundtrips="):
			roundtrips = int(arg.substr(13))
		elif arg.begins_with("--stand-seconds="):
			stand_seconds = float(arg.substr(16))
		elif arg.begins_with("--walk-seconds="):
			walk_seconds = float(arg.substr(15))
		elif arg.begins_with("--teleport-at="):
			teleport_at = float(arg.substr(14))
		elif arg.begins_with("--encounter="):
			encounter_scenario = arg.substr(12)
		elif arg.begins_with("--pack="):
			encounter_pack = int(arg.substr(7))
		elif arg.begins_with("--attack-at="):
			attack_at = float(arg.substr(12))

func _record(event: String, data: Dictionary) -> void:
	data["event"] = event
	data["t"] = _t
	data["tick"] = SimAuthority.sim_tick
	_records.append(data)

## Reward events, deduplicated by operation id: "exactly once" is the rule under
## test, so the transcript must not count the same grant twice.
var _reward_ops: Dictionary = {}

func _on_reward(_uid: int, character_id: int, exp: int, _galleons: int, _items: Array, op_id: String) -> void:
	if _reward_ops.has(op_id):
		return
	_reward_ops[op_id] = true
	_rewards.append({"character_id": character_id, "exp": exp, "op_id": op_id})

# ------------------------------------------------------------------ agreement

func _on_joined(ok: bool, reason: String, _character: Dictionary) -> void:
	_joined = ok
	_join_reason = reason
	_record("joined", {"ok": ok, "reason": reason, "uid": SimAuthority.local_uid})
	if not ok:
		if mode == "maintenance" and reason == "maintenance":
			# Expected in this mode: the world is closed for maintenance.
			_record("join_refused", {"reason": reason})
			_finish_maintenance(0)
			return
		_finish(1)
		return
	_exp_start = int(player.current_exp) if player != null else -1
	_last_pos = player.global_position if player != null else Vector3.ZERO
	_origin_pos = _last_pos
	if ok and mode == "staircase":
		_spawn_staircase()

func _on_health(uid: int, hp: int, max_hp: int, _flags: int) -> void:
	if uid == _target_uid:
		_target_seen_hp.append({"tick": SimAuthority.sim_tick, "hp": hp})
	if mode == "forged" and uid == _forged_mob_uid:
		_forged_mob_hp = hp

func _on_died(uid: int, _killer_uid: int) -> void:
	if uid == _forged_mob_uid:
		_forged_mob_died = true
	if uid == _target_uid and _target_death_tick < 0:
		_target_death_tick = SimAuthority.sim_tick
		_record("target_died", {"uid": uid, "tick": SimAuthority.sim_tick})

func _on_respawn(uid: int) -> void:
	if _pack_uids.has(uid) and _target_respawn_tick < 0:
		_target_respawn_tick = SimAuthority.sim_tick
		_record("pack_respawned", {"uid": uid, "tick": SimAuthority.sim_tick})

func _on_stats(uid: int, stats: Dictionary) -> void:
	if player == null:
		return
	if uid != int(SimAuthority.record_for(player).get("uid", -1)):
		return
	_exp_now = int(stats.get("exp", _exp_now))

func _on_cast_ack(cast_seq: int, _cast_id: int, ok: bool, reason: String) -> void:
	if ok:
		_casts_accepted += 1
	else:
		_casts_rejected.append(reason)
		_record("cast_rejected", {"reason": reason})
	if mode == "maintenance":
		_record_maintenance_cast(cast_seq, ok, reason)

func _physics_process(delta: float) -> void:
	_t += delta
	if mode == "protection" or _done:
		return
	if mode == "encounter":
		if player != null:
			_encounter_tick(delta)
		return
	if mode == "maintenance":
		_maintenance_tick(delta)
		return
	if not _joined:
		return
	if mode == "staircase":
		_staircase_tick(delta)
		return
	if mode == "transfer":
		_transfer_tick(delta)
		return
	_update_target()
	if mode == "agree":
		if _pack_wiped() and _target_respawn_tick < 0:
			# Retreat: a pack is not allowed to respawn on top of players, so the
			# spot has to be vacated before the respawn can be observed.
			_retreat()
		else:
			_drive_to_target()
			_attack_target()
		if _t >= duration:
			_finish_agree()
		return
	_drive_forged()
	_sample_position()
	if _t >= duration:
		_finish_forged()

const SPAWN_REFERENCE := Vector3(0.0, 0.5, 5.0)
## The clients are placed beside the pack, so engagement is immediate.
const ENGAGE_RANGE := 22.0

## Target choice has to be identical on both clients even though they stand a
## metre apart, so it is decided by PACK, not by whichever mob is nearest: the
## pack whose lowest-uid member is closest, then that pack's lowest-uid member.
## A whole pack is replicated together, so both clients compute the same answer.
func _update_target() -> void:
	if _pack_id == 0:
		var pack := _choose_pack()
		if pack == 0:
			return
		_pack_id = pack
		_pack_uids = _pack_members(pack)
		_record("pack_selected", {"pack_id": pack, "members": _pack_uids.duplicate()})
	# Keep the current target while it lives; otherwise take the next live member
	# of the same pack (a pack respawns together only when all of it is dead).
	if _target_uid != 0 and not _is_dead(_target_uid):
		return
	for uid in _pack_uids:
		if not _is_dead(uid):
			_set_target(uid)
			return
	# Whole pack down: watch it for the respawn.
	if _target_uid == 0 and not _pack_uids.is_empty():
		_set_target(int(_pack_uids[0]))

func _pack_wiped() -> bool:
	if _pack_uids.is_empty():
		return false
	for uid in _pack_uids:
		if not _is_dead(uid):
			return false
	return true

func _retreat() -> void:
	var away := player.global_position - SPAWN_REFERENCE
	away.y = 0.0
	if away.length() < 1.0:
		away = Vector3(0, 0, 1)
	_intent_frames += 1
	SimNet.forced_intent = {
		"move": Vector2(0, -1),
		"yaw": rad_to_deg(atan2(-away.x, -away.z)),
		"jump": false,
		"descend": false,
	}

func _set_target(uid: int) -> void:
	if uid == _target_uid:
		return
	_target_uid = uid
	_target_death_tick = -1
	_target_respawn_tick = -1
	_target_initial_hp = int(SimAuthority.entities.get(uid, {}).get("hp", -1))
	_record("target_acquired", {"uid": uid, "hp": _target_initial_hp, "pack_id": _pack_id})

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
	for pack_id in packs.keys():
		var distance := player.global_position.distance_to(packs[pack_id]["pos"])
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

## Walk toward the current target with the same intent message a player's
## keyboard would produce. The server does the actual moving.
func _drive_to_target() -> void:
	if _target_uid == 0 or player == null:
		SimNet.forced_intent = {}
		return
	var target: Vector3 = SimAuthority.entities[_target_uid].get("pos", Vector3.ZERO)
	var to_target := target - player.global_position
	to_target.y = 0.0
	if to_target.length() <= ENGAGE_RANGE:
		SimNet.forced_intent = {}
		return
	# Stuck against forest geometry? Sidestep for a moment, then resume.
	var moved := _last_pos.distance_to(player.global_position)
	if moved > 0.4:
		_stuck_timer = 0.0
	else:
		_stuck_timer += get_physics_process_delta_time()
	if _stuck_timer > 1.0:
		_sidestep_timer = 2.5
		_stuck_timer = 0.0
	var angle_offset := 0.0
	var jump := false
	if _sidestep_timer > 0.0:
		_sidestep_timer -= get_physics_process_delta_time()
		angle_offset = deg_to_rad(90.0)
		# A body pinned on a kerb or a fountain lip gets out the way a player
		# would: sideways and hopping.
		jump = fmod(_sidestep_timer, 0.5) > 0.25
	_last_pos = player.global_position
	var direction := to_target.rotated(Vector3.UP, angle_offset)
	_intent_frames += 1
	SimNet.forced_intent = {
		"move": Vector2(0, -1),
		"yaw": rad_to_deg(atan2(-direction.x, -direction.z)),
		"jump": jump,
		"descend": false,
	}

## Static geometry only (mask 1): mobs and players are not obstacles.
func _path_clear(from: Vector3, to: Vector3) -> bool:
	if world == null:
		return false
	var space := world.get_world_3d().direct_space_state
	if space == null:
		return false
	var query := PhysicsRayQueryParameters3D.create(from + Vector3.UP, to + Vector3.UP, 1)
	query.exclude = [player.get_rid()] if player != null else []
	return space.intersect_ray(query).is_empty()

func _attack_target() -> void:
	if _target_uid == 0 or player == null or _target_death_tick >= 0:
		return
	var record: Dictionary = SimAuthority.entities.get(_target_uid, {})
	if record.is_empty():
		return
	var pos: Vector3 = record.get("pos", Vector3.ZERO)
	if player.global_position.distance_to(pos) > ENGAGE_RANGE + 2.0:
		return
	if _casts_sent > 0 and int(SimAuthority.sim_tick) - _last_cast_tick < 10:  # 0.5s at 20Hz
		return
	_last_cast_tick = int(SimAuthority.sim_tick)
	_casts_sent += 1
	var aim := pos + Vector3.UP
	SimNet.submit_cast(player, "basic_cast", aim, _casts_sent)

var _last_cast_tick := -100

func _finish_agree() -> void:
	_done = true
	_record("final", {
		"uid": SimAuthority.local_uid,
		"target_uid": _target_uid,
		"pack_id": _pack_id,
		"pack_uids": _pack_uids,
		"target_initial_hp": _target_initial_hp,
		"target_hp_samples": _target_seen_hp,
		"target_death_tick": _target_death_tick,
		"target_respawn_tick": _target_respawn_tick,
		"casts_sent": _casts_sent,
		"casts_accepted": _casts_accepted,
		"casts_rejected": _casts_rejected,
		"exp_start": _exp_start,
		"exp_end": _exp_now,
		"rewards": _rewards,
		"visible_mobs": _mob_summary(),
		"player_pos": [player.global_position.x, player.global_position.y, player.global_position.z],
		"intent_frames": SimNet.input_frames_sent,
		"forced_intent_set": _intent_frames,
		"world_ready": world != null,
		"server_controlled": _server_controlled_seen,
		"local_uid": SimAuthority.local_uid,
		"corrections": _corrections,
		"replica_count": SimAuthority.entities.size(),
	})
	_finish(0)

func _mob_summary() -> Array:
	var out: Array = []
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) != HPProtocol.Kind.MOB:
			continue
		out.append({"uid": int(uid), "hp": int(record.get("hp", -1)), "pack": int(record.get("pack_id", 0)),
			"zone": String(record.get("zone_id", ""))})
	out.sort_custom(func(a, b): return int(a["uid"]) < int(b["uid"]))
	return out

# --------------------------------------------------------------------- forged

## Everything a tampered client can say to the server, in one place: the server
## must reject or ignore all of it.
func _drive_forged() -> void:
	if _forged_mob_uid == 0:
		_forged_mob_uid = _target_uid
		return
	if _hack_until > 0.0 and _t > _hack_until:
		# The hack phase is bounded: walking the whole map with a junk vector
		# would eventually walk off it, and the fall rescue is a legitimate
		# teleport that has nothing to do with the input claim under test.
		SimNet.forced_intent = {}
	if _own_hp_before < 0:
		_own_hp_before = int(player.current_hp)
		# 1. A damage claim: the server-side damage entry point is authority-only.
		rpc_id(1, "sim_damage_event", _forged_mob_uid, 99999, 0, "test", SimAuthority.local_uid)
		_record("forged_damage_sent", {"mob": _forged_mob_uid})
		# 2. A hostile cast the client cannot afford (ultimate costs 90 mana).
		SimNet.submit_cast(player, "imperio", player.global_position + Vector3(0, 0, 30), 900)
		# 3. A teleport RPC that does not exist.
		rpc_id(1, "sim_teleport", Vector3(0, 0, 0))
		# 4. A death claim about ourselves.
		rpc_id(1, "sim_death_event", SimAuthority.local_uid, 0)
		# 5. A speed hack: an input vector far outside the unit circle.
		SimNet.forced_intent = {"move": Vector2(50, 50), "yaw": 0.0, "jump": false, "descend": false}
		_hack_until = _t + 2.0
		# Measure from here: the first authority correction also moves this body
		# (it starts at the scene default and is placed by the server), and that
		# placement is not what "did the hack teleport me" is asking about.
		_last_pos = player.global_position
		_origin_pos = _last_pos
		_max_step = 0.0
		_pos_samples.clear()
		_auth_last_tick = -1
		_max_auth_step_per_tick = 0.0
		_auth_step_samples = 0
		_auth_step_ticks = 0
		_sample_hp_call_deferred()

func _data_refresh() -> void:
	_target_uid = 0
	_update_target()

## The forged damage has to be judged while the mob is still in view: this probe
## then walks away (that is the speed-hack part), which legitimately drops it
## from the interest set.
func _sample_hp_call_deferred() -> void:
	await get_tree().create_timer(1.5).timeout
	if _forged_mob_uid != 0 and SimAuthority.entities.has(_forged_mob_uid):
		_forged_mob_hp = int(SimAuthority.entities[_forged_mob_uid].get("hp", -1))
		_forged_mob_died = bool(SimAuthority.entities[_forged_mob_uid].get("dead", false))

func _sample_position() -> void:
	if player == null:
		return
	# The step is measured once per physics frame, so the frame's own duration is
	# part of the measurement: the orchestrator needs it to tell a slow frame on a
	# loaded machine from a teleport.
	var frame_dt := get_physics_process_delta_time()
	if frame_dt > _max_frame_dt:
		_max_frame_dt = frame_dt
	var pos: Vector3 = player.global_position
	var step := _last_pos.distance_to(pos)
	if step > _max_step:
		_max_step = step
	_last_pos = pos
	_pos_samples.append({"tick": SimAuthority.sim_tick, "x": pos.x, "z": pos.z})
	# The authoritative half: only the server's positions for this body, keyed by
	# the server tick each snapshot carried. A reconciliation snap never enters
	# this number, and dividing by the ticks spanned keeps snapshot spacing (or a
	# lossy profile) from looking like a bigger step.
	var tick := int(SimAuthority.sim_tick)
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var authority_pos: Variant = record.get("pos", null)
	if authority_pos is Vector3 and tick > _auth_last_tick:
		var auth_pos: Vector3 = authority_pos
		if _auth_last_tick >= 0:
			var ticks := tick - _auth_last_tick
			_max_auth_step_per_tick = maxf(_max_auth_step_per_tick,
				_auth_last_pos.distance_to(auth_pos) / float(ticks))
			_auth_step_ticks += ticks
			_auth_step_samples += 1
		_auth_last_tick = tick
		_auth_last_pos = auth_pos

func _finish_forged() -> void:
	_done = true
	var mob_hp := -1
	if _forged_mob_uid != 0 and SimAuthority.entities.has(_forged_mob_uid):
		mob_hp = int(SimAuthority.entities[_forged_mob_uid].get("hp", -1))
	_record("final", {
		"uid": SimAuthority.local_uid,
		"mob_uid": _forged_mob_uid,
		"mob_hp_after_forged_damage": _forged_mob_hp if _forged_mob_hp >= 0 else mob_hp,
		"forged_mob_died": _forged_mob_died,
		"own_hp_before": _own_hp_before,
		"own_hp_after": int(player.current_hp) if player != null else -1,
		"casts_rejected": _casts_rejected,
		"casts_accepted": _casts_accepted,
		"max_position_step": _max_step,
		"max_frame_dt": _max_frame_dt,
		"position_samples": _pos_samples.size(),
		"distance_travelled": _origin_pos.distance_to(_last_pos),
		"speed_limit_per_tick": HPRules.max_travel_distance(HPProtocol.SIM_DT),
		"max_auth_step_per_tick": _max_auth_step_per_tick,
		"auth_step_samples": _auth_step_samples,
		"auth_step_ticks": _auth_step_ticks,
		"sim_dt": HPProtocol.SIM_DT,
		"walk_speed": HPRules.WALK_SPEED,
		"mounted_speed": HPRules.MOUNTED_SPEED,
	})
	_finish(0)

var _origin_pos := Vector3.ZERO

# ---------------------------------------------------------------- maintenance

## Phase 6 probe: stay connected through a maintenance cycle and record what the
## client is told, what the admin API publishes, and whether the freeze is real.
## The service token comes from HPMMO_SERVICE_TOKEN and is never recorded.
var _maint_events: Array = []
var _maint_states: Array = []
var _maint_status: Dictionary = {}
var _maint_attempts: Array = []
var _maint_attempt_by_seq: Dictionary = {}
var _maint_poll_accum := 0.0
var _maint_cast_accum := 0.0
var _maint_cast_seq := 900000
var _maint_http: HTTPRequest = null
var _maint_http_pending := false
var _maint_token := ""
var _maint_unreachable := 0
var _disconnect_reason := ""
var _left_server := false
var _left_at := -1.0
var _join_reason := ""
var _maint_finish_at := -1.0
var _maint_flush_accum := 0.0

## Rewrite the transcript so far (maintenance mode only; the file is small).
func _flush_transcript() -> void:
	if out_path == "" or _records.is_empty():
		return
	var file := FileAccess.open(out_path, FileAccess.WRITE)
	if file == null:
		return
	for record in _records:
		file.store_line(JSON.stringify(record))
	file.close()

func _setup_maintenance() -> void:
	_maint_token = OS.get_environment("HPMMO_SERVICE_TOKEN").strip_edges()
	SimAuthority.maintenance_event.connect(func(state: String, reason: String, seconds_remaining: int):
		_maint_events.append({
			"state": state, "reason": reason, "seconds_remaining": seconds_remaining,
			"t": _t, "tick": SimAuthority.sim_tick,
		})
		_record("maintenance_event", {"state": state, "reason": reason,
			"seconds_remaining": seconds_remaining})
		if state == "DISCONNECTING" and _maint_finish_at < 0.0:
			# The peers are about to be closed. Give the transport a moment to
			# report it, then write the transcript even if it never does - the
			# notice itself is the client-visible end of the session.
			_maint_finish_at = _t + 2.5)
	_maint_http = HTTPRequest.new()
	add_child(_maint_http)
	_maint_http.request_completed.connect(_on_admin_response)
	_record("maintenance_probe", {"admin_port": admin_port, "token_present": _maint_token != ""})

func _maintenance_tick(delta: float) -> void:
	_poll_admin(delta)
	# Maintenance mode rewrites its transcript while it runs, so the Python
	# orchestrator can follow the probe (the other modes keep the single write
	# at exit). This never touches _record/_finish.
	_maint_flush_accum += delta
	if _maint_flush_accum >= 0.5:
		_maint_flush_accum = 0.0
		_flush_transcript()
	if _left_server and _left_at >= 0.0 and _t - _left_at >= 1.5:
		_finish_maintenance(0)
		return
	if _maint_finish_at >= 0.0 and _t >= _maint_finish_at:
		_finish_maintenance(0)
		return
	if _joined and not _left_server:
		_maint_cast_accum += delta
		if _maint_cast_accum >= 0.5:
			_maint_cast_accum = 0.0
			_attempt_maintenance_cast()
	if _t >= duration:
		_finish_maintenance(0)

## The point of the mode: a cast attempted inside the frozen window must be
## refused and must not cost mana. One attempt per half second covers every
## state the cycle passes through.
func _attempt_maintenance_cast() -> void:
	if player == null or not is_instance_valid(player):
		return
	if not SimNet.is_client:
		# The link is gone (the server disconnected us): there is nobody to ask,
		# and the local authority must not be asked to adjudicate a cast.
		return
	_maint_cast_seq += 1
	# A spell that actually costs mana (stupefy, 25), so "costs no mana" is a
	# real measurement rather than a zero-cost no-op.
	var attempt := {
		"seq": _maint_cast_seq,
		"spell": "stupefy",
		"t": _t,
		"state": String(_maint_status.get("state", "")),
		"mana_before": int(player.current_mana),
		"ok": null,
		"reason": "",
	}
	_maint_attempts.append(attempt)
	_maint_attempt_by_seq[_maint_cast_seq] = attempt
	SimNet.submit_cast(player, "stupefy", player.global_position + Vector3(0, 1.0, -4.0), _maint_cast_seq)

func _record_maintenance_cast(cast_seq: int, ok: bool, reason: String) -> void:
	var attempt: Dictionary = _maint_attempt_by_seq.get(cast_seq, {})
	if attempt.is_empty():
		return
	attempt["ok"] = ok
	attempt["reason"] = reason
	attempt["state_at_ack"] = String(_maint_status.get("state", ""))
	# A mana cost would be pushed on the same reliable channel just before this
	# answer, so the value is already authoritative here.
	attempt["mana_after"] = int(player.current_mana) if player != null and is_instance_valid(player) else -1

func _poll_admin(delta: float) -> void:
	if _maint_http == null or admin_port <= 0 or _maint_token == "":
		return
	_maint_poll_accum += delta
	if _maint_poll_accum < 0.1 or _maint_http_pending:
		return
	_maint_poll_accum = 0.0
	var url := "http://127.0.0.1:%d/admin/state" % admin_port
	var error := _maint_http.request(url, PackedStringArray(["X-Service-Token: " + _maint_token]))
	if error == OK:
		_maint_http_pending = true

func _on_admin_response(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_maint_http_pending = false
	if code != 200:
		_maint_unreachable += 1
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not (parsed is Dictionary):
		return
	_maint_status = parsed
	var state := String(parsed.get("state", ""))
	if state == "" or (not _maint_states.is_empty() and String(_maint_states[-1]["state"]) == state):
		return
	_maint_states.append({
		"state": state,
		"t": _t,
		"tick": SimAuthority.sim_tick,
		"server_tick": int(parsed.get("tick", -1)),
		"players": int(parsed.get("players", -1)),
		"deadline_ms": int(parsed.get("deadline_ms", 0)),
	})
	_record("admin_state", {"state": state, "reason": parsed.get("reason", ""),
		"players": parsed.get("players", -1), "deadline_ms": parsed.get("deadline_ms", 0)})

func _finish_maintenance(code: int) -> void:
	_done = true
	var mana := -1
	if player != null and is_instance_valid(player):
		mana = int(player.current_mana)
	var status := _maint_status.duplicate()
	status.erase("history")
	_record("final", {
		"uid": SimAuthority.local_uid,
		"joined": _joined,
		"join_reason": _join_reason,
		"admin_port": admin_port,
		"token_present": _maint_token != "",
		"states": _maint_states,
		"events": _maint_events,
		"casts": _maint_attempts,
		"mana_at_finish": mana,
		"admin_unreachable": _maint_unreachable,
		"disconnect_reason": _disconnect_reason,
		"duration": _t,
		"last_status": status,
	})
	_finish(code)

# ----------------------------------------------------------------- protection

## Exit check: a protected target cannot be damaged by a delayed projectile, a
## burn tick, or a boss AoE. Runs the authority in-process and drives the exact
## entry points the network uses.
func _run_protection() -> void:
	world = WORLD_SCENE.instantiate()
	add_child(world)
	await get_tree().create_timer(0.8).timeout
	player = world.get("local_player")
	var courtyard := Vector3(0, 0.5, 5)
	var outside := Vector3(60, 0.5, 60)
	var mob := _nearest_mob()
	if mob == null or player == null:
		_record("error", {"message": "no mob or player"})
		_finish(1)
		return
	player.global_position = courtyard
	var record := SimAuthority.record_for(player)
	var results := {}
	var hp_before := int(player.current_hp)

	# Geometry: the attacker stands just outside the courtyard edge so every
	# attack below is comfortably in range; protection is the only variable.
	var attacker_pos := Vector3(38.0, 0.5, 5.0)
	var inside_pos := Vector3(4.0, 0.5, 5.0)
	var outside_pos := Vector3(24.0, 0.5, 5.0)
	mob.global_position = attacker_pos
	_revive_attacker(mob)

	# --- (1) a projectile that reaches a victim INSIDE the zone: the victim walks
	# in while the bolt is in flight - the "delayed projectile" case.
	player.global_position = outside_pos
	record["hp"] = hp_before
	player.set("current_hp", hp_before)
	SimAuthority.mob_projectile(mob, "stupefy", (outside_pos - attacker_pos).normalized(), 120)
	await get_tree().create_timer(0.25).timeout
	player.global_position = inside_pos
	await get_tree().create_timer(1.0).timeout
	results["projectile_into_zone"] = {"before": hp_before, "after": int(player.current_hp)}

	# The same shot with the victim outside protection: proof the shot was real.
	# Attacker and victim stand 8 m apart on open ground, so the control turns on
	# protection alone - not on whether a long ray happened to clear the terrain.
	var yard_mob := Vector3(34.0, 0.5, 32.0)
	var yard_victim := Vector3(26.0, 0.5, 32.0)
	_revive_attacker(mob)
	mob.global_position = yard_mob
	player.global_position = yard_victim
	record["hp"] = hp_before
	player.set("current_hp", hp_before)
	SimAuthority.mob_projectile(mob, "stupefy", (yard_victim - yard_mob).normalized(), 120)
	await get_tree().create_timer(1.2).timeout
	results["projectile_outside_zone"] = {"before": hp_before, "after": int(player.current_hp)}

	# --- (2) burn ticks: a REAL incendio hit (damage + burn) on the mob, which
	# then walks into the zone while the burn is still ticking.
	player.global_position = outside_pos
	mob.global_position = Vector3(28.0, 0.5, 5.0)
	var mob_record := SimAuthority.record_for(mob)
	mob_record["hp"] = int(mob.max_hp)
	mob.set("current_hp", int(mob.max_hp))
	SimAuthority.apply_spell_hit(mob, "incendio", player)
	var burn_started := int(mob_record.get("burn_until_tick", 0)) > 0
	var burn_before := int(mob.current_hp)
	mob.global_position = inside_pos
	mob.set_physics_process(false)
	var uid_in := int(SimAuthority.record_for(mob).get("uid", 0))
	var events_before_in := int(_damage_events.get(uid_in, 0))
	await get_tree().create_timer(2.4).timeout
	results["burn_inside_zone"] = {"before": burn_before, "after": int(mob.current_hp),
		"burn_started": burn_started,
		"events": int(_damage_events.get(uid_in, 0)) - events_before_in}
	mob.set_physics_process(true)

	# Burn control: the same hit, the mob left outside, must tick.
	_revive_attacker(mob)
	mob.global_position = yard_mob
	mob_record["hp"] = int(mob.max_hp)
	mob.set("current_hp", int(mob.max_hp))
	SimAuthority.apply_spell_hit(mob, "incendio", player)
	var burn_out_before := int(mob.current_hp)
	var uid_out := int(SimAuthority.record_for(mob).get("uid", 0))
	var events_before_out := int(_damage_events.get(uid_out, 0))
	await get_tree().create_timer(3.4).timeout
	results["burn_outside_zone"] = {"before": burn_out_before, "after": int(mob.current_hp),
		"burn_started": int(SimAuthority.record_for(mob).get("burn_until_tick", 0)) > 0,
		"events": int(_damage_events.get(uid_out, 0)) - events_before_out,
		"diag": {"burn_until": int(SimAuthority.record_for(mob).get("burn_until_tick", -1)),
			"burn_next": int(SimAuthority.record_for(mob).get("burn_next_tick", -1)),
			"sim_tick": SimAuthority.sim_tick, "dead": bool(SimAuthority.record_for(mob).get("dead", false)),
			"record_uid": int(SimAuthority.record_for(mob).get("uid", 0)), "counted_uid": uid_out}}

	# --- (3) boss AoE centred outside whose circle covers a player inside.
	player.global_position = inside_pos
	_revive_attacker(mob)
	mob.global_position = Vector3(25.0, 0.5, 5.0)
	record["hp"] = hp_before
	player.set("current_hp", hp_before)
	var hits: Array = SimAuthority.mob_area_attack(mob, Vector3(25.0, 0.5, 5.0), 30.0, 800, "boss_slam")
	results["boss_aoe_over_zone"] = {"hits": hits.size(), "before": hp_before, "after": int(player.current_hp)}

	# Same slam, same radius: the player simply stands outside the circle.
	_revive_attacker(mob)
	_revive_attacker(mob)
	mob.global_position = yard_mob
	player.global_position = yard_victim
	record["hp"] = hp_before
	player.set("current_hp", hp_before)
	var hits_out: Array = SimAuthority.mob_area_attack(mob, yard_victim, 30.0, 800, "boss_slam")
	results["boss_aoe_outside_zone"] = {"hits": hits_out.size(), "before": hp_before, "after": int(player.current_hp)}

	_record("protection", results)
	_done = true
	_finish(0)

## A dead mob cannot attack: every protection case starts from a live attacker,
## otherwise the "positive control" would silently test nothing.
func _revive_attacker(mob: Node3D) -> void:
	if mob == null or not is_instance_valid(mob):
		return
	SimAuthority.refresh_mob(mob)
	mob.set("state", 0)
	SimAuthority.unregister_node(mob)
	SimAuthority.register_mob(mob, 1, "probe")
	mob_record = SimAuthority.record_for(mob)
	# A big pool on purpose: if the probe's own incendio killed the attacker, the
	# burn cases would measure nothing (a dead mob's burn never ticks), and the
	# "inside the zone" case would pass for the wrong reason.
	mob_record["max_hp"] = 100000
	mob_record["hp"] = 100000
	mob.set("max_hp", 100000)
	mob.set("current_hp", 100000)

var mob_record: Dictionary = {}

func _nearest_mob() -> Node3D:
	var best: Node3D = null
	var best_distance := 1e9
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) != HPProtocol.Kind.MOB:
			continue
		var node = record.get("node")
		if node == null or not is_instance_valid(node):
			continue
		var distance: float = (node as Node3D).global_position.distance_to(player.global_position)
		if distance < best_distance:
			best_distance = distance
			best = node
	return best

# ------------------------------------------------------- staircase (Phase 8)

## Exit check: two independent clients must see the same staircase position and
## state at the same tick. This probe is a real client: it joins, loads the
## ordinary world, instances `staircase.tscn` where the dev hook put the
## authority's copy, and records what the scene shows every tick.
##
## Roles:
##   observe       stand still and record the staircase
##   ride          board while docked and stay aboard while it travels
##   board_busy    try to board while it is moving (must be refused, with feedback)
##   fallback      walk the conventional staircase while the platform is away
##   rider_logout  ride, then drop the connection mid-flight

const STAIRCASE_SCENE = preload("res://scenes/world/castle/staircase.tscn")
## Inside the Phase 10 flat core and clear of the encounter regions. The old
## (150, 0, 120) is in the hill ring the terrain pass raises, and the hillside
## there intersects the upper flight and the landings.
const STAIR_DEV_ORIGIN := Vector3(90.0, 0.0, -15.0)

func _staircase_origin() -> Vector3:
	var raw := OS.get_environment("HPMMO_DEV_STAIRCASE")
	if raw == "":
		return STAIR_DEV_ORIGIN
	var parts := raw.split(",")
	if parts.size() != 3:
		return STAIR_DEV_ORIGIN
	return Vector3(float(parts[0]), float(parts[1]), float(parts[2]))

func _spawn_staircase() -> void:
	if world == null:
		_record("stair_error", {"message": "no world"})
		_finish(1)
		return
	staircase = STAIRCASE_SCENE.instantiate()
	staircase.name = "MagicalStaircase"
	world.add_child(staircase)
	staircase.global_position = _staircase_origin()
	SimAuthority.notice.connect(_on_stair_notice)
	SimAuthority.entity_despawned.connect(func(uid: int):
		_stair_despawns.append({"tick": SimAuthority.sim_tick, "uid": uid}))
	_record("stair_ready", {
		"role": stair_role,
		"origin": staircase.global_position,
		"docks": staircase.dock_count(),
		"dock_ids": [staircase.dock_id(0), staircase.dock_id(1), staircase.dock_id(2)],
		"rise": staircase.rise(),
		"run": staircase.run_length(),
		"timing": staircase.timing,
	})

func _on_stair_notice(text: String, _color: Color) -> void:
	if text.begins_with("staircase_locked"):
		_stair_notices.append({"tick": SimAuthority.sim_tick, "t": _t, "text": text})

func _walk_toward(goal: Vector3) -> void:
	var to_goal := goal - player.global_position
	to_goal.y = 0.0
	if to_goal.length() <= 0.4:
		SimNet.forced_intent = {}
		return
	# Stuck detection has to measure over *time*, not per frame: the physics rate
	# is not the simulation rate, and a body walking normally covers only a few
	# centimetres per frame at 60 Hz. Measuring per frame would sidestep forever.
	var delta := get_physics_process_delta_time()
	_walk_check_timer += delta
	if _walk_check_timer >= 0.5:
		if _walk_check_pos.distance_to(player.global_position) < 0.6:
			_sidestep_timer = 1.2
		_walk_check_timer = 0.0
		_walk_check_pos = player.global_position
	var angle_offset := 0.0
	var jump := false
	if _sidestep_timer > 0.0:
		_sidestep_timer -= get_physics_process_delta_time()
		angle_offset = deg_to_rad(90.0)
		jump = fmod(_sidestep_timer, 0.5) > 0.25
	_last_pos = player.global_position
	var direction := to_goal.rotated(Vector3.UP, angle_offset)
	_intent_frames += 1
	SimNet.forced_intent = {
		"move": Vector2(0, -1),
		"yaw": rad_to_deg(atan2(-direction.x, -direction.z)),
		"jump": jump,
		"descend": false,
	}

func _staircase_tick(_delta: float) -> void:
	if staircase == null or player == null or not is_instance_valid(player):
		return
	_sample_stair()
	match stair_role:
		"ride", "rider_logout":
			_stair_ride_tick()
		"board_busy":
			_stair_busy_tick()
		"fallback":
			_stair_fallback_tick()
		_:
			SimNet.forced_intent = {}
	if _t >= duration:
		_finish_staircase()

func _sample_stair() -> void:
	if not staircase.replica_active:
		# No authoritative state has arrived yet: sampling now would report the
		# replica's default `docked` as fact, and a client whose first publish
		# lands after another's would "disagree" with it for a heartbeat.
		return
	var tick := int(SimAuthority.sim_tick)
	if not _stair_samples.is_empty() and int(_stair_samples[-1]["tick"]) == tick:
		return
	var origin: Vector3 = staircase.platform_world_transform(tick).origin
	var body := player.global_position
	_stair_samples.append({
		"tick": tick, "state": staircase.state, "from": staircase.from_index,
		"to": staircase.to_index, "dock": staircase.dock_index, "cycle": staircase.cycle,
		"nav": staircase.navigation_open(), "entry": staircase.entry_allowed(),
		"platform": [origin.x, origin.y, origin.z],
		"player": [body.x, body.y, body.z],
	})
	if _stair_samples.size() > 6000:
		_stair_samples.pop_front()
	if _stair_events.is_empty() or String(_stair_events[-1]["state"]) != staircase.state:
		_stair_events.append({"state": staircase.state, "tick": tick, "t": _t})

## A point ON the deck surface (not the deck's origin plane), `along` of the way
## up the run, in world space for the current tick.
func _deck_point(tick: int, along: float) -> Vector3:
	var z: float = staircase.run_length() * along
	return staircase.platform_world_transform(tick) * Vector3(0.0, z * staircase.slope() + 0.05, z)

## The waiting spot in front of the ground dock's foot, on the ground: inside
## the authority's boarding-approach volume (deck space z in [-3, 1.5]) but
## outside `on_deck` (which starts at z = 0.2), so a rider can wait "at the
## gate" without ever standing on a locked deck.
func _dock_wait_point() -> Vector3:
	return staircase.global_transform * (staircase.dock_origin(0) + Vector3(0.0, 0.05, -1.0))

func _stair_ride_tick() -> void:
	var tick := int(SimAuthority.sim_tick)
	if not bool(_stair_ride.get("aboard", false)):
		if not staircase.replica_active:
			# No authoritative state yet: walk to the waiting spot, decide nothing.
			_walk_toward(_dock_wait_point())
			return
		# Boarding decisions use the AUTHORITY's position, not the prediction: the
		# client body runs ahead of the server body, and stopping on the deck one
		# or two ticks early leaves the server body off it when the platform
		# leaves - the rider then falls through with it (the bug this replaces:
		# the probe boarded on the prediction, the server never collected it).
		# The walk-in point (1.2 m up the run) is a margin over the collection
		# edge (0.2 m), so by the time the client stops the server body is aboard.
		var docked_here: bool = staircase.entry_allowed() and staircase.dock_index == 0
		var auth := _auth_pos()
		if docked_here and staircase.on_deck(auth, tick, 2.4, 0.8) \
				and staircase.to_deck_space(auth, tick).z >= 1.2:
			_stair_ride["aboard"] = true
			_stair_ride["boarded_tick"] = tick
			_stair_ride["board_y"] = player.global_position.y
			_stair_ride["min_y"] = player.global_position.y
			_stair_ride["max_y"] = player.global_position.y
			_stair_ride["min_above_deck"] = 99.0
			_stair_ride["max_above_deck"] = -99.0
			SimNet.forced_intent = {}
			return
		# Wait at the foot while the platform is elsewhere or locked; walk up the
		# deck only once it is docked here. The old route sprinted for a point on
		# the moving deck from 12 m away the moment the gates opened and lost the
		# race against the scaled dwell every time.
		_walk_toward(_deck_point(tick, 0.35) if docked_here else _dock_wait_point())
		return
	# Aboard: stand still and let the platform carry the body.
	SimNet.forced_intent = {}
	var y := player.global_position.y
	_stair_ride["min_y"] = minf(float(_stair_ride.get("min_y", y)), y)
	_stair_ride["max_y"] = maxf(float(_stair_ride.get("max_y", y)), y)
	var deck_y: float = staircase.platform_world_transform(tick).origin.y
	_stair_ride["min_above_deck"] = minf(float(_stair_ride.get("min_above_deck", 99.0)), y - deck_y)
	_stair_ride["max_above_deck"] = maxf(float(_stair_ride.get("max_above_deck", -99.0)), y - deck_y)
	var on: bool = staircase.on_deck(player.global_position, tick, 3.2, 0.9)
	_stair_ride["on_deck_at_end"] = on
	if not on and int(_stair_ride.get("left_at", -1)) < 0 and staircase.state != HPStaircase.STATE_DOCKED:
		_stair_ride["left_at"] = tick
		_stair_ride["left_pos"] = [player.global_position.x, player.global_position.y, player.global_position.z]
	if stair_role == "rider_logout" and staircase.state == HPStaircase.STATE_MOVING:
		# Hard disconnect, mid-flight, with the body on the deck.
		_stair_ride["logout_tick"] = tick
		_finish_staircase()

func _stair_busy_tick() -> void:
	var tick := int(SimAuthority.sim_tick)
	if staircase.entry_allowed():
		SimNet.forced_intent = {}
		return
	if int(_stair_walk.get("last_locked_tick", -1)) != tick:
		_stair_walk["last_locked_tick"] = tick
		_stair_walk["locked_ticks"] = int(_stair_walk.get("locked_ticks", 0)) + 1
	# Walk to the boarding edge at the ground dock and press against the closed
	# gate. Chasing the current deck point instead (the old route) walked the
	# body to the flat spot under a raised deck, where the boarding volume does
	# not reach, so the authority never had a reason to send the "locked"
	# notice this check is about.
	_walk_toward(_dock_wait_point())
	_stair_walk["tried"] = true
	if staircase.on_deck(player.global_position, tick):
		_stair_walk["ever_on_deck_while_locked"] = true
		_stair_walk["on_deck_at"] = [player.global_position.x, player.global_position.y, player.global_position.z]
	_stair_walk["end_pos"] = [player.global_position.x, player.global_position.y, player.global_position.z]

## The conventional route: ground -> first -> second, while the magical
## staircase is somewhere else.
func _stair_fallback_waypoints() -> Array:
	var t := staircase.global_transform
	return [
		t * Vector3(-8.0, 0.1, -10.0),
		t * Vector3(-8.0, 3.6, 1.0),
		t * Vector3(-8.0, 6.1, 10.0),
		t * Vector3(14.0, 6.1, 10.0),
		t * Vector3(20.0, 6.1, 10.0),
		t * Vector3(20.0, 6.1, -10.0),
		t * Vector3(16.0, 6.1, -10.0),
		t * Vector3(16.0, 9.6, 1.0),
		t * Vector3(16.0, 12.1, 10.0),
	]

func _stair_fallback_tick() -> void:
	var tick := int(SimAuthority.sim_tick)
	if staircase.state == HPStaircase.STATE_DOCKED and staircase.dock_index == 0:
		# The platform is still at the ground dock: wait until it is away, so the
		# walk proves the fallback route while the connection is absent.
		SimNet.forced_intent = {}
		return
	var waypoints := _stair_fallback_waypoints()
	var index := int(_stair_walk.get("waypoint", 0))
	_stair_walk["started_tick"] = int(_stair_walk.get("started_tick", tick))
	if index >= waypoints.size():
		SimNet.forced_intent = {}
		_stair_walk["finished_tick"] = tick
		_stair_walk["end_pos"] = [player.global_position.x, player.global_position.y, player.global_position.z]
		return
	var goal: Vector3 = waypoints[index]
	var flat := goal - player.global_position
	flat.y = 0.0
	if flat.length() < 1.8 and absf(goal.y - player.global_position.y) < 2.2:
		_stair_walk["waypoint"] = index + 1
		_stair_walk["reached_%d" % index] = [player.global_position.x, player.global_position.y, player.global_position.z]
		return
	_walk_toward(goal)

func _finish_staircase() -> void:
	if _done:
		return
	_done = true
	SimNet.forced_intent = {}
	_record("final", {
		"uid": SimAuthority.local_uid,
		"role": stair_role,
		"stairs_present": staircase != null,
		"duration": _t,
		"samples": _stair_samples,
		"events": _stair_events,
		"notices": _stair_notices,
		"despawns": _stair_despawns,
		"ride": _stair_ride,
		"walk": _stair_walk,
		"player_pos": [player.global_position.x, player.global_position.y, player.global_position.z] if player != null else [],
		"intent_frames": SimNet.input_frames_sent,
	})
	_finish(0)

# --------------------------------------------- staircase failure cases (Phase 8)

## Death, disconnect/logout and a map transfer while a rider is between floors
## must land the body on a valid landing. Runs the authority in process and
## drives the real entry points (lethal damage through `apply_damage`, the
## resolver the authority calls when a body leaves).
func _run_stair_failure() -> void:
	stair_role = "failure"
	SimAuthority.configure(SimAuthority.Role.OFFLINE)
	world = WORLD_SCENE.instantiate()
	add_child(world)
	await get_tree().create_timer(1.0).timeout
	player = world.get("local_player")
	var results := {}
	if player == null:
		_record("error", {"message": "no local player"})
		_finish(1)
		return
	staircase = STAIRCASE_SCENE.instantiate()
	staircase.name = "MagicalStaircase"
	world.add_child(staircase)
	staircase.global_position = _staircase_origin()
	results["authority"] = staircase.is_authority_runtime
	var record := SimAuthority.record_for(player)
	results["docks"] = staircase.dock_count()

	# --- death while riding: board while docked, ride, then die in flight
	if not await _board_and_wait_for_flight(results, 20.0):
		_record("error", {"message": "could not board the staircase"})
		_finish(1)
		return
	results["death_on_deck"] = staircase.on_deck(player.global_position, SimAuthority.sim_tick)
	results["death_state"] = staircase.state
	results["death_rider"] = staircase.is_riding(int(record.get("uid", 0)))
	var attacker := _nearest_mob()
	SimAuthority.apply_damage(player, 999999, "test_fall", attacker)
	results["dead"] = bool(SimAuthority.record_for(player).get("dead", false))
	results["death_pos"] = _pos_array(player.global_position)
	var waited := 0.0
	while waited < 8.0 and bool(SimAuthority.record_for(player).get("dead", false)):
		await get_tree().create_timer(0.25).timeout
		waited += 0.25
	results["respawn_pos"] = _pos_array(player.global_position)
	results["respawn_is_landing"] = _stair_contains(player.global_position) == false
	results["respawn_matches_map"] = (player.global_position - HPRules.respawn_position()).length() < 0.6

	# --- map transfer while riding: the resolver the authority calls
	SimAuthority.record_for(player)["dead"] = false
	player.global_position = Vector3.ZERO
	if not await _board_and_wait_for_flight(results, 20.0):
		_record("error", {"message": "could not board for the transfer case"})
		_finish(1)
		return
	results["transfer_state"] = staircase.state
	results["transfer_rider"] = staircase.is_riding(int(record.get("uid", 0)))
	var landing: Vector3 = staircase.resolve_departing_player(SimAuthority.record_for(player), "map_transfer")
	results["transfer_landing"] = _pos_array(landing)
	results["transfer_pos"] = _pos_array(player.global_position)
	results["transfer_on_authored_landing"] = false
	for index in range(staircase.dock_count()):
		for top in [false, true]:
			if (landing - (staircase.global_transform * staircase.dock_landing(index, top))).length() < 0.05:
				results["transfer_on_authored_landing"] = true
	results["transfer_moved_body"] = (player.global_position - landing).length() < 0.01
	results["transfer_safe_spawn"] = _pos_array(SimAuthority.record_for(player).get("safe_spawn", Vector3.ZERO))

	_record("stair_failure", results)
	_done = true
	_finish(0)

## Board the deck while the authority says boarding is open, then wait until the
## platform is moving with the body registered as a rider.
func _board_and_wait_for_flight(results: Dictionary, timeout: float) -> bool:
	if not await _await_state(HPStaircase.STATE_DOCKED, timeout):
		return false
	var record := SimAuthority.record_for(player)
	player.global_position = _deck_point(SimAuthority.sim_tick, 0.35)
	await get_tree().physics_frame
	await get_tree().physics_frame
	results["rider_registered"] = staircase.is_riding(int(record.get("uid", 0)))
	results["riders_on_deck"] = staircase.rider_count()
	return await _await_state(HPStaircase.STATE_MOVING, timeout)

func _await_state(wanted: String, timeout: float) -> bool:
	var waited := 0.0
	while waited < timeout:
		if staircase != null and staircase.state == wanted:
			return true
		await get_tree().physics_frame
		waited += get_physics_process_delta_time()
	return false

func _pos_array(point: Vector3) -> Array:
	return [point.x, point.y, point.z]

## Is this point inside the staircase's deck volume (i.e. between floors)?
func _stair_contains(point: Vector3) -> bool:
	return staircase.on_deck(point, SimAuthority.sim_tick, 2.4)

# ------------------------------------------------------------------- transfer
##
## Phase 8 map transfer (plan.md): drives the real client API
## (`SimNet.request_transfer` / `mark_transfer_ready`) and records every
## transfer/map signal the server emits. The map controller that ships with the
## client performs the load and the readiness acknowledgement; this probe
## replaces only input, exactly like the other modes.

func _setup_transfer() -> void:
	SimAuthority.transfer_granted.connect(_on_transfer_granted)
	SimAuthority.transfer_committed.connect(_on_transfer_committed)
	SimAuthority.transfer_refused.connect(_on_transfer_refused)
	SimAuthority.transfer_expired.connect(_on_transfer_expired)
	SimAuthority.map_state.connect(_on_probe_map_state)
	SimAuthority.notice.connect(func(text: String, _color: Color):
		_notices.append({"t": _t, "text": text}))
	# The expire scenario must never acknowledge - the real controller would. It
	# is removed there so the server's side of the contract is what gets tested.
	if scenario == "expire" and world != null and world.has_node("MapController"):
		world.get_node("MapController").queue_free()
	_record("transfer_probe", {"scenario": scenario, "portal": transfer_portal,
		"roundtrips": roundtrips, "server_api": SimNet.has_method("request_transfer")})

func _on_transfer_granted(peer_id: int, token: int, map_id: String, spawn_id: String) -> void:
	if peer_id != SimNet.local_peer_id:
		return
	_transfer_token = token
	_granted_map = map_id
	_granted_spawn = spawn_id
	_phase = 1
	_phase_at = _t
	var controller := world.get_node_or_null("MapController") if world != null else null
	_transfer_events.append({"event": "granted", "t": _t, "token": token,
		"map_id": map_id, "spawn_id": spawn_id,
		"controller_busy": bool(controller.get("busy")) if controller != null else null})
	if scenario == "interrupt":
		# The client dies with the transfer in flight: the server must cancel the
		# reservation and persist a valid location, never a half transfer.
		_record("interrupting", {"token": token, "map_id": map_id, "spawn_id": spawn_id})
		_finish_transfer()
		return
	if scenario == "expire" and _expired:
		# This is the retry after the expiry: acknowledging proves the stale
		# reservation was really released.
		SimNet.mark_transfer_ready(token)

func _on_transfer_committed(peer_id: int, token: int, map_id: String, pos: Vector3, spawn_id: String) -> void:
	if peer_id != SimNet.local_peer_id:
		return
	_commit_map = map_id
	_commit_pos = pos
	_commit_spawn = spawn_id
	_commit_at = _t
	_phase = 2
	_transfer_events.append({"event": "committed", "t": _t, "token": token,
		"map_id": map_id, "pos": _pos_array(pos), "spawn_id": spawn_id})
	if scenario == "roundtrips":
		_transfers_done += 1
		_phase = 0

func _on_transfer_refused(peer_id: int, reason: String) -> void:
	if peer_id != SimNet.local_peer_id:
		return
	_refusal = reason
	_phase = 3
	if scenario == "roundtrips":
		_rt_failed = true
	_transfer_events.append({"event": "refused", "t": _t, "reason": reason})

func _on_transfer_expired(peer_id: int, token: int, map_id: String, pos: Vector3) -> void:
	if peer_id != SimNet.local_peer_id:
		return
	_expired = true
	_phase = 4
	_transfer_events.append({"event": "expired", "t": _t, "token": token,
		"map_id": map_id, "pos": _pos_array(pos)})

func _on_probe_map_state(map_id: String, pos: Vector3, spawn_id: String) -> void:
	var changed := map_id != _map_id
	_map_id = map_id
	_transfer_events.append({"event": "map_state", "t": _t, "map_id": map_id,
		"pos": _pos_array(pos), "spawn_id": spawn_id, "changed": changed})

# ----------------------------------------------------------------- transfer tick

func _transfer_tick(_delta: float) -> void:
	if scenario == "teleport":
		_sample_transfer_positions()
	if _map_id == "":
		return   # the server has not said which map this body is on yet
	# One mid-flight snapshot per run: the fair instant for comparing what two
	# clients saw (finals are recorded at different times).
	if _visibility_at < 0.0 and _t >= 6.0:
		_visibility_at = _t
		var summary := _visible_summary()
		_record("visibility", {"map": _map_id, "uids": summary["uids"],
			"players": summary["players"], "mobs": summary["mobs"]})
	match scenario:
		"observer":
			pass
		"teleport":
			_teleport_tick()
		"happy", "opposite", "full", "interrupt", "expire":
			if scenario == "expire":
				_expire_tick()
			else:
				_single_transfer_tick()
		"mounted":
			_mounted_tick()
		"roundtrips":
			_roundtrip_tick()
		"stand":
			_stand_tick()
		_:
			_single_transfer_tick()
	if _t >= duration:
		_finish_transfer()

func _single_transfer_tick() -> void:
	if _phase != 0 or _t < 1.0:
		return
	var portal := _default_portal()
	if portal == "":
		_record("error", {"message": "no portal on map %s" % _map_id})
		_phase = 9
		return
	if not _in_portal(portal):
		_walk_toward(_portal_center(portal))
		return
	SimNet.forced_intent = {}
	_send_transfer_request(portal)

## Interior-collision regression (bug: entering the castle must not drop the body
## to the outdoor ground). Enters through the door with the real handshake, then
## holds still and samples the SERVER's height for `stand_seconds`, then walks
## straight ahead for `walk_seconds` and samples again. The authority must keep
## the body on the interior floor in both halves; maps_sim.py asserts the samples.
func _stand_tick() -> void:
	if _phase == 0:
		_single_transfer_tick()
		return
	if _phase != 2 or _commit_at < 0.0:
		return   # refused, expired, or the commit has not landed yet
	if not _stand_started:
		# The commit message and the first reconciliation snapshot are a few
		# frames apart; the window starts once the body is really in the
		# destination's y-band, so the sample set is about standing, not about
		# the transfer's own placement frame.
		var local_y := player.global_position.y if player != null and is_instance_valid(player) else 0.0
		if (_auth_pos().y < 185.0 or local_y < 185.0) and _t - _commit_at < 3.0:
			return
		_stand_started = true
		_stand_start = _t
		SimNet.forced_intent = {}
	if stand_seconds > 0.0 and not _walk_started and _t - _stand_start < stand_seconds:
		_sample_hold(_stand_samples)
		return
	if not _walk_started:
		_walk_started = true
		_walk_start = _t
		_walk_from = player.global_position if player != null and is_instance_valid(player) else _auth_pos()
		SimNet.forced_intent = {"move": Vector2(0, -1), "yaw": 0.0, "jump": false, "descend": false}
	if walk_seconds <= 0.0 or _t - _walk_start >= walk_seconds:
		SimNet.forced_intent = {}
		_finish_stand()
		return
	_sample_hold(_walk_samples)

## One (t, server position, local position, on-floor) sample, throttled so the
## transcript stays small while a fall cannot hide between samples.
func _sample_hold(into: Array) -> void:
	if _t < _next_sample_at:
		return
	_next_sample_at = _t + 0.1
	var local: Array = []
	var on_floor := false
	if player != null and is_instance_valid(player):
		local = _pos_array(player.global_position)
		on_floor = bool(player.is_on_floor())
	into.append({"t": snappedf(_t, 0.01), "auth": _pos_array(_auth_pos()),
		"local": local, "floor": on_floor})

func _finish_stand() -> void:
	var moved := 0.0
	if player != null and is_instance_valid(player):
		moved = Vector2(player.global_position.x - _walk_from.x,
			player.global_position.z - _walk_from.z).length()
	_record("stand_report", {
		"stand_seconds": stand_seconds,
		"walk_seconds": walk_seconds,
		"commit_pos": _pos_array(_commit_pos),
		"stand_samples": _stand_samples,
		"walk_samples": _walk_samples,
		"walk_distance": moved,
	})
	_finish_transfer()

func _expire_tick() -> void:
	if _phase == 0:
		_single_transfer_tick()
		return
	if _phase == 4 and _move_at < 0.0:
		# The reservation is gone and the body is back at its safe spawn: input
		# must work again (a pending transfer would silently eat it).
		_move_at = _t
		_move_from = _auth_pos()
		SimNet.forced_intent = {"move": Vector2(0, -1), "yaw": 180.0, "jump": false, "descend": false}
		_record("post_expiry_move_start", {"map": _map_id, "auth_pos": _pos_array(_move_from)})
		return
	if _phase == 4 and _move_distance < 0.0 and _t - _move_at >= 1.0:
		SimNet.forced_intent = {}
		_move_distance = _move_from.distance_to(_auth_pos())
		_record("post_expiry_move", {"distance": _move_distance, "map": _map_id})
		# Walk back to the door: a second request must be possible, which proves
		# the stale reservation was released instead of shadowing the player.
		_phase = 5
		return
	if _phase == 5:
		var portal := _default_portal()
		if portal == "":
			return
		if not _in_portal(portal):
			_walk_toward(_portal_center(portal))
			return
		SimNet.forced_intent = {}
		_send_transfer_request(portal)

func _mounted_tick() -> void:
	if not _mount_requested and _t >= 1.5:
		_mount_requested = true
		_mount_at = _t
		SimNet.submit_mount(player, true)
		_record("mount_requested", {})
		return
	if _mount_requested and not _mounted_seen:
		var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
		if bool(record.get("mounted", false)):
			_mounted_seen = true
			_record("mounted_seen", {"t": _t})
		return
	if _mounted_seen and _phase == 0 and _t >= _mount_at + 1.0:
		var portal := _default_portal()
		if portal == "":
			return
		if not _in_portal(portal):
			_walk_toward(_portal_center(portal))
			return
		SimNet.forced_intent = {}
		_send_transfer_request(portal)

func _teleport_tick() -> void:
	if not _teleported and _t >= teleport_at:
		_teleported = true
		_teleport_target = HPMaps.default_spawn("castle_interior")
		_record("teleport_claim", {"map": _map_id, "from": _pos_array(_auth_pos()),
			"to": _pos_array(_teleport_target)})
		player.global_position = _teleport_target   # the cheat: move my own body
		return
	if _teleported and not _forged_sent and _t >= teleport_at + 0.5:
		_forged_sent = true
		# Forged protocol claims: an acknowledgement for a reservation this
		# client never received, and a door that does not exist. The RPCs live on
		# the SimNet autoload, so they are addressed there (the probe node has no
		# such RPC surface).
		SimNet.rpc_id(1, "sim_transfer_ready", 999999)
		SimNet.request_transfer(player, "no_such_portal", "castle_interior")
	if _teleported and _teleport_err < 0.0 and _t >= teleport_at + 5.0:
		_teleport_err = player.global_position.distance_to(_auth_pos())
		_record("teleport_after", {"map": _map_id, "local": _pos_array(player.global_position),
			"auth": _pos_array(_auth_pos()), "error": _teleport_err})

func _roundtrip_tick() -> void:
	if _rt_failed or _transfers_done >= roundtrips:
		return
	if _phase != 0:
		return
	var portal := _default_portal()
	if portal == "":
		return
	if not _in_portal(portal):
		_walk_toward(_portal_center(portal))
		return
	SimNet.forced_intent = {}
	_send_transfer_request(portal)

# ------------------------------------------------------------- transfer helpers

func _send_transfer_request(portal_id: String) -> bool:
	if player == null or not is_instance_valid(player):
		return false
	if _controller_busy():
		return false   # the map controller is still finishing a transition
	_phase = 1
	_phase_at = _t
	_record("request_sent", {"portal": portal_id, "map": _map_id, "auth_pos": _pos_array(_auth_pos())})
	SimNet.request_transfer(player, portal_id, _portal_destination(portal_id))
	return true

## True while the client's map controller is mid-transition (it ignores a
## request then, exactly as it ignores the door prompt). A player would wait and
## press again; the probe waits and asks again.
func _controller_busy() -> bool:
	if world == null or not is_instance_valid(world):
		return false
	var controller := world.get_node_or_null("MapController")
	if controller == null:
		return false
	return bool(controller.get("busy"))

func _default_portal() -> String:
	if transfer_portal != "":
		return transfer_portal
	for entry in HPMaps.portals_for_map(_map_id):
		if entry is Dictionary and String(entry.get("id", "")) != "":
			return String(entry.get("id", ""))
	return ""

func _portal_destination(portal_id: String) -> String:
	return String(HPMaps.portal(portal_id).get("to_map", ""))

func _portal_center(portal_id: String) -> Vector3:
	var trigger: Dictionary = HPMaps.portal(portal_id).get("trigger", {})
	var centre: Array = trigger.get("center", [])
	if centre.size() != 3:
		return _auth_pos()
	return Vector3(float(centre[0]), float(centre[1]) - 0.5, float(centre[2]))

func _in_portal(portal_id: String) -> bool:
	var entry := HPMaps.portal(portal_id)
	if entry.is_empty():
		return false
	return HPMaps.portal_contains(entry, _auth_pos())

## Walking uses the shared `_walk_toward` above (it also handles a body stuck on
## scenery). The transfer scenarios only ask for it while the authoritative
## position is outside the portal volume, which is the real stop condition.

## The position the SERVER last sent for this body. The local body is predicted;
## only this one is authoritative.
func _auth_pos() -> Vector3:
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var pos: Variant = record.get("pos", null)
	if pos is Vector3:
		return pos
	if player != null and is_instance_valid(player):
		return player.global_position
	return Vector3.ZERO

func _sample_transfer_positions() -> void:
	if player == null or not is_instance_valid(player):
		return
	var local: Vector3 = player.global_position
	var auth := _auth_pos()
	_local_samples.append(_pos_array(local))
	_auth_samples.append(_pos_array(auth))
	var step := _last_pos.distance_to(local)
	if step > _max_step:
		_max_step = step
	_last_pos = local

func _visible_summary() -> Dictionary:
	var uids: Array = []
	var mobs: Array = []
	var players: Array = []
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		uids.append(int(uid))
		match int(record.get("kind", 0)):
			HPProtocol.Kind.MOB:
				mobs.append(int(uid))
			HPProtocol.Kind.PLAYER:
				players.append(int(uid))
	uids.sort()
	mobs.sort()
	players.sort()
	return {"uids": uids, "mobs": mobs, "players": players}

func _finish_transfer() -> void:
	_done = true
	var visible := _visible_summary()
	var uids: Array = visible["uids"]
	var mobs: Array = visible["mobs"]
	var players: Array = visible["players"]
	_record("final", {
		"uid": SimAuthority.local_uid,
		"scenario": scenario,
		"map_id": _map_id,
		"granted_map": _granted_map,
		"granted_spawn": _granted_spawn,
		"commit_map": _commit_map,
		"commit_pos": _pos_array(_commit_pos),
		"commit_spawn": _commit_spawn,
		"commit_at": _commit_at,
		"refusal": _refusal,
		"expired": _expired,
		"post_expiry_move": _move_distance,
		"transfers_done": _transfers_done,
		"roundtrip_failed": _rt_failed,
		"teleport_error": _teleport_err,
		"mounted_requested": _mount_requested,
		"mounted_seen": _mounted_seen,
		"transfer_events": _transfer_events,
		"notices": _notices,
		"local_pos": _pos_array(player.global_position) if player != null and is_instance_valid(player) else [],
		"authoritative_pos": _pos_array(_auth_pos()),
		"replica_count": SimAuthority.entities.size(),
		"visible_uids": uids,
		"visible_mobs": mobs,
		"visible_players": players,
		"corrections": _corrections,
		"max_position_step": _max_step,
		"local_samples": _local_samples,
		"auth_samples": _auth_samples,
	})
	_finish(0)

# ------------------------------------------------- in-process transfer checks

## Runs the authority in this process and drives the exact entry points the
## network uses. Everything a two-client test cannot command cheaply - death,
## a missing reservation, a forged token, an out-of-range claim, the interest
## filter across maps - is checked here against the same engine.
func _run_transfer_local() -> void:
	world = WORLD_SCENE.instantiate()
	add_child(world)
	await get_tree().create_timer(0.8).timeout
	player = world.get("local_player")
	if player == null:
		_record("error", {"message": "no local player"})
		_finish(1)
		return
	var peer: int = SimNet.local_peer_id
	var door := _trigger_stand("castle_door")
	var results: Dictionary = {}
	player.global_position = door
	await get_tree().physics_frame

	# 1) a dead player cannot transfer
	SimAuthority.apply_damage(player, 999999, "melee", null)
	results["dead_refused"] = String(SimAuthority.request_transfer(peer, "castle_door", "castle_interior").get("reason", ""))
	SimAuthority.submit_respawn(peer)
	player.global_position = Vector3(0, 0.6, 5)
	for _i in range(20):
		await get_tree().physics_frame

	# 2) a mounted player is refused entry into a flight-prohibited map
	var mount_result := SimAuthority.submit_mount(peer, true)
	results["mount_ok"] = bool(mount_result.get("ok", false))
	player.global_position = door
	await get_tree().physics_frame
	results["mounted_refused"] = String(SimAuthority.request_transfer(peer, "castle_door", "castle_interior").get("reason", ""))
	SimAuthority.submit_mount(peer, false)

	# 3) a request from outside the portal volume is refused
	player.global_position = Vector3(0, 0.6, 20)
	results["range_refused"] = String(SimAuthority.request_transfer(peer, "castle_door", "castle_interior").get("reason", ""))
	player.global_position = door

	# 4) unknown portal, a destination that is not the door's, unknown map
	results["unknown_portal"] = String(SimAuthority.request_transfer(peer, "no_such_portal", "").get("reason", ""))
	results["wrong_map"] = String(SimAuthority.request_transfer(peer, "castle_door", "grounds").get("reason", ""))
	var portals: Array = HPMaps.data().get("portals", [])
	portals.append({"id": "dev_void", "map_id": "grounds", "to_map": "nowhere", "to_spawn": "default",
		"trigger": HPMaps.portal("castle_door").get("trigger", {})})
	results["unknown_destination"] = String(SimAuthority.request_transfer(peer, "dev_void", "").get("reason", ""))
	portals.pop_back()

	# 5) the happy path, one step at a time
	var grant := SimAuthority.request_transfer(peer, "castle_door", "castle_interior")
	results["grant_ok"] = bool(grant.get("ok", false))
	var token := int(grant.get("token", 0))
	results["pending_refused"] = String(SimAuthority.request_transfer(peer, "castle_door", "castle_interior").get("reason", ""))
	results["bad_token"] = String(SimAuthority.transfer_ready(peer, 987654).get("reason", ""))
	var ready := SimAuthority.transfer_ready(peer, token)
	results["ready_ok"] = bool(ready.get("ok", false))
	var record := SimAuthority.record_for(player)
	results["map_after_commit"] = String(record.get("map_id", ""))
	results["pos_after_commit"] = _pos_array((record.get("node") as Node3D).global_position)
	results["spawn_after_commit"] = _pos_array(HPMaps.spawn_point("castle_interior", "vestibule"))

	# 6) the interest filter is map-scoped: another player standing 2 m away is
	# invisible while it belongs to another map, in BOTH directions.
	results["filter"] = _filter_check(peer, (record.get("node") as Node3D).global_position)
	_record("transfer_local", results)
	_done = true
	_finish(0)

func _trigger_stand(portal_id: String) -> Vector3:
	var trigger: Dictionary = HPMaps.portal(portal_id).get("trigger", {})
	var centre: Array = trigger.get("center", [])
	if centre.size() != 3:
		return Vector3.ZERO
	# Inside the volume, on the court side of the arch.
	return Vector3(float(centre[0]), float(centre[1]) - 0.5, float(centre[2]) + 1.5)

func _filter_check(peer: int, centre: Vector3) -> Dictionary:
	var out: Dictionary = {}
	var scene: PackedScene = load("res://scenes/entities/player/player.tscn")
	var other: Node3D = scene.instantiate()
	other.name = "FilterProbe"
	world.get_node("Players").add_child(other)
	other.global_position = centre + Vector3(2.0, 0.0, 0.0)
	var other_uid := SimAuthority.register_player(other, 0, 77)
	var other_record: Dictionary = SimAuthority.record_by_uid(other_uid)
	var local_record := SimAuthority.record_for(player)
	var local_uid := int(local_record.get("uid", 0))
	var local_map := String(local_record.get("map_id", ""))
	var other_map := "castle_interior" if local_map != "castle_interior" else "grounds"
	# Same map: 2 m away, inside the interest radius -> must be replicated.
	other_record["map_id"] = local_map
	out["same_map_visible"] = HPSnapshots.interest_set(SimAuthority, peer, centre).has(other_uid)
	# Other map: the same node at the same distance - only the map differs.
	other_record["map_id"] = other_map
	out["cross_map_hidden"] = not HPSnapshots.interest_set(SimAuthority, peer, centre).has(other_uid)
	# Reverse direction: the other peer is on `other_map`, so the local body
	# standing on top of it must not be sent either.
	out["reverse_hidden"] = not HPSnapshots.interest_set(SimAuthority, 77, centre).has(local_uid)
	other_record["map_id"] = local_map
	out["reverse_same_visible"] = HPSnapshots.interest_set(SimAuthority, 77, centre).has(local_uid)
	SimAuthority.unregister_node(other)
	other.queue_free()
	return out

# ------------------------------------------------------- encounters (Phase 11)

## Real-server scenarios (`--mode=encounter --scenario=...`):
##   reactive   stand beside an ordinary pack: proximity alone must not aggro;
##              a valid hit must, and only for the attacked pack (positive
##              control). Records the state every pack ever reached.
##   boss       pull a boss: every telegraph (start/release tick and shape),
##              every damage event on this player, the member/escort count and
##              the recovery windows between attacks.
##   lifecycle  kill a pack: exactly-once rewards per player, the corpse
##              finishing its death animation and then fading, a dead mob never
##              moving or attacking again, and the respawn anchor validated
##              clear of the player camping the old one.
##   local      in-process authority checks: template data, placement rules for
##              every formation member, respawn cycles at different valid
##              anchors, camped-respawn deferral, leash reset cancelling the
##              pending reward, attack slots/separation, corpse and pool reset.
var encounter_scenario := "reactive"
var encounter_pack := 0
var attack_at := 6.0
var _engaged := false
var _telegraphs: Array = []
var _telegraph_ends: Dictionary = {}
var _mob_damage: Array = []
var _pack_seen: Dictionary = {}
var _corpses: Dictionary = {}
## Per-telegraph: what the CLIENT rendered from the server's timing/shape.
var _telegraph_visuals: Dictionary = {}
var _respawns: Array = []
var _wiped_at := -1.0
var _local_results: Dictionary = {}

func _setup_encounter() -> void:
	SimAuthority.mob_telegraph.connect(func(uid: int, data: Dictionary):
		_telegraphs.append({"uid": uid, "tick": SimAuthority.sim_tick, "data": data}))
	SimAuthority.mob_telegraph_end.connect(func(uid: int):
		_telegraph_ends[uid] = int(_telegraph_ends.get(uid, 0)) + 1)
	SimAuthority.encounter_reset.connect(func(pack_id: int, reason: String):
		_record("encounter_reset", {"pack_id": pack_id, "reason": reason}))
	if not SimAuthority.reward_granted.is_connected(_on_reward):
		SimAuthority.reward_granted.connect(_on_reward)
	SimAuthority.entity_damaged.connect(func(uid: int, amount: int, hp: int, spell_id: String, _attacker: int):
		if uid == SimAuthority.local_uid:
			_mob_damage.append({"tick": SimAuthority.sim_tick, "amount": amount, "hp": hp, "spell": spell_id}))

func _encounter_tick(delta: float) -> void:
	_sample_encounter()
	match encounter_scenario:
		"reactive":
			if _t >= attack_at and not _engaged:
				_engaged = true
				_select_encounter_pack()
				_attack_target()
				_record("engage", {"tick": SimAuthority.sim_tick, "pack_id": _pack_id,
					"player_pos": _pos_array(player.global_position)})
			elif _engaged:
				_attack_target()
		"boss":
			if _pack_id == 0:
				_select_encounter_pack()
			else:
				_update_target()
				_drive_to_target()
				_attack_target()
		"lifecycle":
			if _pack_id == 0:
				_select_encounter_pack()
			elif _pack_wiped():
				if _wiped_at < 0.0:
					_wiped_at = _t
					_record("pack_wiped", {"tick": SimAuthority.sim_tick, "pack_id": _pack_id,
						"player_pos": _pos_array(player.global_position)})
				_retreat_from_pack()
			else:
				_update_target()
				_drive_to_target()
				_attack_target()
	if _t >= duration:
		_finish_encounter()

func _select_encounter_pack() -> void:
	if encounter_pack > 0:
		var members := _pack_members(encounter_pack)
		if members.is_empty():
			return   # not replicated to this client yet; try again next tick
		_pack_id = encounter_pack
		_pack_uids = members
		_record("pack_selected", {"pack_id": _pack_id, "members": _pack_uids.duplicate()})
	else:
		_update_target()
	if _pack_id != 0 and _target_uid == 0 and not _pack_uids.is_empty():
		_set_target(int(_pack_uids[0]))

## One sample per tick: the highest AI state every pack has reached, the view
## node's position drift after death (a dead mob must not act again) and the
## respawn anchor of a pack that came back.
func _sample_encounter() -> void:
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) != HPProtocol.Kind.MOB:
			continue
		var pack := int(record.get("pack_id", 0))
		var state := int(record.get("state", 0))
		var seen: Dictionary = _pack_seen.get(pack, {"states": {}, "chase_tick": -1, "attack_tick": -1,
			"anticipation_tick": -1, "recovery_tick": -1, "boss": 0, "members": 0})
		(seen["states"] as Dictionary)[state] = true
		if state == HPProtocol.MobState.CHASE and int(seen["chase_tick"]) < 0:
			seen["chase_tick"] = SimAuthority.sim_tick
		if state == HPProtocol.MobState.ATTACK and int(seen["attack_tick"]) < 0:
			seen["attack_tick"] = SimAuthority.sim_tick
		if state == HPProtocol.MobState.ANTICIPATION and int(seen["anticipation_tick"]) < 0:
			seen["anticipation_tick"] = SimAuthority.sim_tick
		if state == HPProtocol.MobState.RECOVERY and int(seen["recovery_tick"]) < 0:
			seen["recovery_tick"] = SimAuthority.sim_tick
		if (int(record.get("flags", 0)) & HPProtocol.FLAG_BOSS) != 0:
			seen["boss"] = int(uid)
		seen["members"] = maxi(int(seen["members"]), _pack_members(pack).size())
		_pack_seen[pack] = seen
		var telegraph: Dictionary = record.get("telegraph", {})
		if not telegraph.is_empty():
			var view = record.get("node")
			var warning = view.get("_warning") if view != null and is_instance_valid(view) else null
			var entry: Dictionary = _telegraph_visuals.get(uid, {})
			entry["start_tick"] = int(telegraph.get("start_tick", 0))
			entry["release_tick"] = int(telegraph.get("release_tick", 0))
			entry["kind"] = String(telegraph.get("kind", ""))
			entry["mesh"] = warning != null
			if warning != null and warning is MeshInstance3D:
				var mesh := (warning as MeshInstance3D).mesh
				entry["radius"] = float(mesh.top_radius) if mesh is CylinderMesh else -1.0
				entry["at_center"] = (warning as MeshInstance3D).global_position.distance_to(
					telegraph.get("center", Vector3.ZERO)) < 0.5
			_telegraph_visuals[uid] = entry
		var dead := bool(record.get("dead", false))
		if dead and not _corpses.has(uid):
			var node = record.get("node")
			var anim := ""
			var anim_len := 0.0
			if node != null and is_instance_valid(node) and node.get("anim_player") != null:
				anim = String(node.anim_player.current_animation)
				if node.anim_player.has_animation(anim):
					anim_len = node.anim_player.get_animation(anim).length
			_corpses[uid] = {"death_tick": SimAuthority.sim_tick, "drift": 0.0, "hidden_tick": -1,
				"anim": anim, "anim_len": anim_len, "playing_after": 0, "anims": [anim] if anim != "" else [],
				"last_pos": record.get("pos", Vector3.ZERO)}
		elif _corpses.has(uid):
			var corpse: Dictionary = _corpses[uid]
			var pos: Vector3 = record.get("pos", Vector3.ZERO)
			# Drift is measured while the body is a corpse: a dead mob must not
			# move. Once the pack respawns, the record stops accumulating.
			# The first few samples cover the view catching up with the last
			# replicated step; after that a corpse that moves is a bug.
			corpse["settle"] = int(corpse.get("settle", 0)) + 1
			if dead and int(corpse["settle"]) > 5 and not bool(corpse.get("revived", false)):
				corpse["drift"] = float(corpse["drift"]) + (pos - (corpse["last_pos"] as Vector3)).length()
			elif not dead:
				corpse["revived"] = true
			corpse["last_pos"] = pos
			var node = record.get("node")
			if node != null and is_instance_valid(node):
				if not node.visible and int(corpse["hidden_tick"]) < 0:
					corpse["hidden_tick"] = SimAuthority.sim_tick
				if node.get("anim_player") != null and node.anim_player.is_playing():
					corpse["playing_after"] = SimAuthority.sim_tick - int(corpse["death_tick"])
					var playing := String(node.anim_player.current_animation)
					var seen_anims: Array = corpse["anims"]
					if playing != "" and not seen_anims.has(playing):
						seen_anims.append(playing)
						if playing.ends_with("Death"):
							corpse["anim"] = playing
	# A pack that was wiped and now has a live member again respawned: record the
	# new anchor and where the player was standing at that moment.
	if _pack_id != 0 and not _pack_uids.is_empty() and _wiped_at >= 0.0:
		var alive: Array = []
		for uid in _pack_uids:
			if not _is_dead(int(uid)):
				alive.append(int(uid))
		if alive.size() > 0:
			var anchor := Vector3.ZERO
			for uid in alive:
				anchor += SimAuthority.entities[uid].get("pos", Vector3.ZERO) as Vector3
			anchor /= float(alive.size())
			_respawns.append({"pack_id": _pack_id, "tick": SimAuthority.sim_tick,
				"respawn_index": _respawns.size(),
				"anchor": _pos_array(anchor),
				"member_count": alive.size(),
				"player_pos": _pos_array(player.global_position)})
			_wiped_at = -1.0

func _finish_encounter() -> void:
	_done = true
	_record("encounter", {
		"scenario": encounter_scenario,
		"pack_id": _pack_id,
		"pack_uids": _pack_uids.duplicate(),
		"packs_seen": _pack_seen,
		"telegraphs": _telegraphs,
		"telegraph_ends": _telegraph_ends,
		"telegraph_visuals": _telegraph_visuals,
		"damage_taken": _mob_damage,
		"corpses": _corpses,
		"respawns": _respawns,
		"rewards": _rewards,
		"casts_sent": _casts_sent,
		"casts_accepted": _casts_accepted,
		"player_hp": int(player.current_hp) if player != null else -1,
		"player_pos": _pos_array(player.global_position) if player != null else [],
		"visible_mobs": _mob_summary(),
	})
	_finish(0)

## In-process Phase 11 checks. Drives the real authority and the real director;
## the Python suite asserts on the recorded facts.
func _run_encounter_local() -> void:
	world = WORLD_SCENE.instantiate()
	add_child(world)
	await get_tree().create_timer(0.9).timeout
	player = world.get("local_player")
	var director = world.get_node_or_null("EncounterDirector")
	if director == null or player == null:
		_record("error", {"message": "no director or player"})
		_finish(1)
		return
	_setup_encounter()
	var results := {"data": HPRules.validate_encounters(), "templates": {},
		"regions": {}, "cycles": {}, "cycle_valid": {}, "member_spread": [],
		"refusals": {}, "camped": {}, "leash": {}, "slots": {}, "corpse": {}, "pool": {}}
	# -- template data -------------------------------------------------------
	for pack in director.packs:
		results["templates"][String(pack.get("encounter_id", ""))] = {
			"template": String(pack.get("template_id", "")),
			"count": int(pack.get("count", 0)),
			"escorts": int(pack.get("escorts", 0)),
			"max_alive": int(pack.get("max_alive", 0)),
			"boss": bool(pack.get("boss", false)),
			"pack_id": int(pack.get("pack_id", 0)),
		}
	results["regions"] = {
		"forest_w_count": HPRules.region_pack_count("forest_w"),
		"forest_w_active": HPRules.active_encounters_for("forest_w").size(),
		"authored": HPRules.encounter_list().size(),
		"dormant": director.dormant.size(),
	}
	# Weighted region choice: the dormant encounter lists two weighted regions;
	# 400 seeded draws must reach both of them.
	var weighted: Dictionary = HPRules.encounter_by_id("enc_forest_w_acromantula_b")
	var drawn: Dictionary = {}
	if not weighted.is_empty():
		for i in range(400):
			var rng := RandomNumberGenerator.new()
			rng.seed = 1000 + i
			drawn[HPRules.resolve_encounter_zone(weighted, rng)] = true
	results["weighted_zones"] = drawn.keys()
	# -- placement refusals --------------------------------------------------
	var pack0: Dictionary = director.packs[0]
	results["refusals"]["hub"] = director._placement_refusal(Vector3(0.0, 0.1, 0.0), pack0)
	# A point inside a Great Hall wall: the formation member must not be placed
	# inside solid geometry (the harness proves this wall blocks movement).
	results["refusals"]["wall"] = director._placement_refusal(Vector3(18.0, 0.1, -57.0), pack0)
	results["refusals"]["lake"] = director._placement_refusal(Vector3(-38.0, 0.1, 30.0), pack0)
	results["refusals"]["portal"] = director._placement_refusal(Vector3(0.0, 0.1, -40.0), pack0)
	player.global_position = Vector3(60.0, 0.1, 55.0)
	await get_tree().physics_frame
	results["refusals"]["player"] = director._placement_refusal(Vector3(60.0, 0.1, 55.0), pack0)
	player.global_position = Vector3(0.0, 0.5, 5.0)
	await get_tree().physics_frame
	# -- respawn cycles: 3- and 5-member packs, several cycles each -----------
	for target_index in [0, 2]:
		var ids: Array = []
		for cycle in range(3):
			var pack: Dictionary = director.packs[target_index]
			var members: Array = pack["members"]
			for member in members:
				if is_instance_valid(member):
					member.take_damage(1000000, "test", player)
			await get_tree().physics_frame
			pack["timer"] = 0.01
			await get_tree().create_timer(0.25).timeout
			var anchor: Vector3 = pack.get("anchor", Vector3.INF)
			ids.append({"anchor": anchor, "spawns": int(pack.get("spawns", 0))})
			var valid := anchor.is_finite() and not HPRules.is_spawn_blocked(anchor)
			var spread := 999.0
			var points: Array = []
			for member in pack["members"]:
				if not is_instance_valid(member):
					continue
				points.append(member.global_position)
				valid = valid and not HPRules.is_spawn_blocked(member.global_position)
				valid = valid and HPRules.exclusion_at(member.global_position) == ""
			for i in range(points.size()):
				for j in range(i + 1, points.size()):
					spread = minf(spread, (points[i] as Vector3).distance_to(points[j]))
			results["cycle_valid"]["%d_%d" % [target_index, cycle]] = valid
			results["member_spread"].append(spread)
		results["cycles"][str(target_index)] = ids
	# -- camped respawn defers ----------------------------------------------
	var camp_pack: Dictionary = director.packs[0]
	var camp_members: Array = camp_pack["members"]
	for member in camp_members:
		if is_instance_valid(member):
			member.take_damage(1000000, "test", player)
	await get_tree().physics_frame
	var saved_area: Rect2 = camp_pack["area"]
	camp_pack["area"] = Rect2(-2.0, -2.0, 4.0, 4.0)
	player.global_position = Vector3(0.0, 0.1, 0.0)
	await get_tree().physics_frame
	camp_pack["timer"] = 0.01
	await get_tree().create_timer(0.25).timeout
	var alive := 0
	for member in camp_members:
		if is_instance_valid(member) and member.state != member.State.DEAD:
			alive += 1
	results["camped"] = {"alive": alive, "deferred": bool(camp_pack.get("deferred", false)),
		"timer": float(camp_pack.get("timer", -1.0))}
	camp_pack["area"] = saved_area
	player.global_position = Vector3(0.0, 0.5, 5.0)
	camp_pack["timer"] = 0.01
	await get_tree().create_timer(0.3).timeout
	# -- leash reset cancels the pending reward ------------------------------
	# Open ground well outside every safe zone and exclusion: the player and the
	# mob must both be in a place where combat is legal.
	var leash_pack: Dictionary = director.packs[1]
	var leash_mob = leash_pack["members"][0]
	var ground := Vector3(60.0, 0.1, 60.0)
	player.current_hp = player.max_hp
	player.global_position = ground
	for member in leash_pack["members"]:
		if is_instance_valid(member):
			member.global_position = ground
			member.pack_anchor = ground
			member.spawn_point = ground
	await get_tree().physics_frame
	leash_mob.aggro_on(player)
	leash_mob.take_damage(10, "basic_cast", player)
	await get_tree().physics_frame
	var log_before: int = (SimAuthority.record_for(leash_mob).get("damage_log", []) as Array).size()
	var chasing: bool = leash_mob.state in [leash_mob.State.CHASE, leash_mob.State.ATTACK]
	# Break the leash: the pack anchor jumps 40 m away, past the 26 m leash.
	leash_mob.pack_anchor = ground + Vector3(40.0, 0.0, 0.0)
	var went_home := false
	var leash_trace: Array = []
	for _i in range(90):
		await get_tree().physics_frame
		if _i % 10 == 0:
			leash_trace.append({"state": int(leash_mob.state), "phase": int(leash_mob.attack_phase),
				"dist": leash_mob.global_position.distance_to(leash_mob.pack_anchor),
				"leash": leash_mob.leash_distance,
				"has_target": leash_mob.target_player != null,
				"valid": leash_mob._valid_target(),
				"hp": int(leash_mob.current_hp)})
		if leash_mob.state == leash_mob.State.RETURN:
			went_home = true
			break
	var log_after: int = (SimAuthority.record_for(leash_mob).get("damage_log", []) as Array).size()
	var resets := 0
	for record in _records:
		if String(record.get("event", "")) == "encounter_reset":
			resets += 1
	# Now finish the mob off with NO eligible attacker: if the leash reset really
	# cancelled the player's earlier contribution, this kill pays nobody.
	leash_mob.pack_anchor = ground
	leash_mob.spawn_point = ground
	leash_mob.global_position = ground
	await get_tree().create_timer(0.2).timeout
	var rewards_before := _rewards.size()
	SimAuthority.apply_damage(leash_mob, 1000000, "test", null)
	await get_tree().physics_frame
	results["leash_trace"] = leash_trace
	results["leash"] = {"pack_id": int(leash_pack.get("pack_id", 0)),
		"log_before": log_before, "log_after": log_after, "chasing": chasing, "went_home": went_home,
		"resets": resets, "rewards_before": rewards_before, "rewards_after": _rewards.size(),
		"new_rewards": _rewards.slice(rewards_before)}
	player.global_position = Vector3(0.0, 0.5, 5.0)
	await get_tree().physics_frame
	# Positive control: the same kill WITH the player's contribution on the log
	# does pay (proving the check above is not passing because rewards are off).
	var control_pack: Dictionary = director.packs[3]
	var control_mob = control_pack["members"][0]
	player.global_position = control_mob.global_position + Vector3(1, 0, 0)
	await get_tree().physics_frame
	SimAuthority.apply_damage(control_mob, 5, "basic_cast", player)
	await get_tree().physics_frame
	var rewards_control := _rewards.size()
	SimAuthority.apply_damage(control_mob, 1000000, "test", null)
	await get_tree().physics_frame
	results["leash"]["control_paid"] = _rewards.size() > rewards_control
	# -- attack slots and separation ----------------------------------------
	var slot_pack: Dictionary = director.packs[2]
	player.global_position = Vector3(-68.0, 0.1, -40.0)
	var slot_index := 0
	for member in slot_pack["members"]:
		if is_instance_valid(member):
			member._respawn()
			var i := slot_index
			slot_index += 1
			member.global_position = Vector3(-68.0, 0.1, -40.0) + Vector3(cos(TAU * float(i) / 5.0), 0.0, sin(TAU * float(i) / 5.0)) * 6.0
			member.pack_anchor = Vector3(-68.0, 0.1, -40.0)
			member.spawn_point = Vector3(-68.0, 0.1, -40.0)
			member.aggro_on(player)
	var max_in_range := 0
	var min_gap := 999.0
	var samples := 0
	for _i in range(180):
		await get_tree().physics_frame
		var in_range := 0
		var positions: Array = []
		for member in slot_pack["members"]:
			if not is_instance_valid(member):
				continue
			positions.append(member.global_position)
			if member.global_position.distance_to(player.global_position) <= member.attack_range + 0.5:
				in_range += 1
		max_in_range = maxi(max_in_range, in_range)
		for i in range(positions.size()):
			for j in range(i + 1, positions.size()):
				min_gap = minf(min_gap, (positions[i] as Vector3).distance_to(positions[j]))
		samples += 1
	results["slots"] = {"max_in_range": max_in_range, "members": slot_pack["members"].size(),
		"min_gap": min_gap, "samples": samples,
		"attack_slots": int(HPRules.pack_tuning("attack_slots", 3.0))}
	# -- corpse + pool reset -------------------------------------------------
	var corpse_pack: Dictionary = director.packs[0]
	var victim = corpse_pack["members"][0]
	player.global_position = Vector3(0.0, 0.5, 5.0)
	await get_tree().create_timer(0.2).timeout
	var death_pos: Vector3 = victim.global_position
	victim.take_damage(1000000, "test", player)
	await get_tree().physics_frame
	var death_tick := SimAuthority.sim_tick
	var max_drift := 0.0
	var attacked_after_death := false
	var anim_after_death := String(victim.anim_player.current_animation) if is_instance_valid(victim) and victim.anim_player else ""
	# Long enough to cover the death clip AND the fade that follows it.
	for _i in range(260):
		await get_tree().physics_frame
		if is_instance_valid(victim) and victim.state != victim.State.DEAD:
			attacked_after_death = true
		if is_instance_valid(victim):
			max_drift = maxf(max_drift, victim.global_position.distance_to(death_pos))
	results["corpse"] = {"max_drift": max_drift, "acted_after_death": attacked_after_death,
		"state_dead": int(victim.state) == int(victim.State.DEAD) if is_instance_valid(victim) else false,
		"corpse_lifetime": float(victim._corpse_lifetime) if is_instance_valid(victim) else -1.0,
		"hidden": not victim.visible if is_instance_valid(victim) else false,
		"anim": anim_after_death,
		"has_player": is_instance_valid(victim) and victim.anim_player != null,
		"clips": victim.anim_player.get_animation_list() if is_instance_valid(victim) and victim.anim_player else [],
		"death_clip_len": victim.anim_player.get_animation("Death").length if is_instance_valid(victim) and victim.anim_player and victim.anim_player.has_animation("Death") else -1.0,
		"anim_len": float(victim.anim_player.get_animation(victim.anim_player.current_animation).length) if is_instance_valid(victim) and victim.anim_player and victim.anim_player.current_animation != "" else -1.0,
		"ticks_observed": SimAuthority.sim_tick - death_tick}
	victim._respawn()
	for _i in range(6):
		await get_tree().physics_frame
	var record := SimAuthority.record_for(victim)
	results["pool"] = {"hp": int(victim.current_hp), "max_hp": int(victim.max_hp),
		"hp_full": int(victim.current_hp) == int(victim.max_hp),
		"state_idle": int(victim.state) == int(victim.State.IDLE),
		"target_cleared": victim.target_player == null,
		"attack_cleared": victim.attack_phase == 0 and victim._windup == 0.0,
		"telegraph_cleared": not record.has("telegraph"),
		"log_cleared": (record.get("damage_log", []) as Array).is_empty(),
		"targetable": victim.is_in_group("targetable"),
		"warning_cleared": victim._warning == null}
	_local_results = results
	_record("encounter_local", results)
	_done = true
	_finish(0)

## Walk away from the pack under test (the lifecycle scenario vacates the old
## anchor so a respawn is allowed to happen somewhere clear of the corpse).
func _retreat_from_pack() -> void:
	var reference: Vector3 = SimAuthority.entities.get(_target_uid, {}).get("pos", SPAWN_REFERENCE)
	var away := player.global_position - reference
	away.y = 0.0
	if away.length() < 1.0:
		away = Vector3(0, 0, 1)
	_intent_frames += 1
	SimNet.forced_intent = {
		"move": Vector2(0, -1),
		"yaw": rad_to_deg(atan2(-away.x, -away.z)),
		"jump": false,
		"descend": false,
	}

# ---------------------------------------------------------------------- common

func _finish(code: int) -> void:
	if not _records.is_empty() and out_path != "":
		var file := FileAccess.open(out_path, FileAccess.WRITE)
		if file:
			for record in _records:
				file.store_line(JSON.stringify(record))
			file.close()
	get_tree().quit(code)
