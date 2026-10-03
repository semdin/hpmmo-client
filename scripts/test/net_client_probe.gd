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
##     --mode=agree|forged|protection|maintenance --port=7777 --name=Alice \
##     --out=<file> [--seconds=25] [--admin-port=8082]
##
## The `maintenance` mode (Phase 6) joins, records every SimAuthority
## maintenance signal, polls the admin API for the published state, keeps trying
## to cast, and writes a transcript when the server disconnects it. Its token is
## read from HPMMO_SERVICE_TOKEN and is never recorded or printed.

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
var _last_pos := Vector3.ZERO
var _forged_mob_hp := -1
var _forged_mob_uid := 0
var _own_hp_before := -1
var _forged_mob_died := false
var _hack_until := 0.0
var _done := false
var _intent_frames := 0
var _server_controlled_seen := false
var _corrections := 0
var _damage_events: Dictionary = {}
var _stuck_timer := 0.0
var _sidestep_timer := 0.0

func _ready() -> void:
	_parse_args()
	# Counted in every mode: the protection assertions are written in terms of
	# damage events actually delivered, so the counter must exist there too.
	SimAuthority.entity_damaged.connect(func(uid: int, _amount: int, _hp: int, _spell: String, _attacker: int):
		_damage_events[uid] = int(_damage_events.get(uid, 0)) + 1)
	SimAuthority.configure(SimAuthority.Role.CLIENT if mode != "protection" else SimAuthority.Role.OFFLINE)
	if mode == "protection":
		_run_protection.call_deferred()
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
	SimAuthority.entity_health.connect(_on_health)
	SimAuthority.entity_died.connect(_on_died)
	SimAuthority.entity_respawned.connect(_on_respawn)
	SimAuthority.stats_changed.connect(_on_stats)
	SimAuthority.reward_granted.connect(func(_uid: int, character_id: int, exp: int, _galleons: int, _items: Array, op_id: String):
		_rewards.append({"character_id": character_id, "exp": exp, "op_id": op_id}))
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

func _record(event: String, data: Dictionary) -> void:
	data["event"] = event
	data["t"] = _t
	data["tick"] = SimAuthority.sim_tick
	_records.append(data)

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
	if mode == "maintenance":
		_maintenance_tick(delta)
		return
	if not _joined:
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
	var pos: Vector3 = player.global_position
	var step := _last_pos.distance_to(pos)
	if step > _max_step:
		_max_step = step
	_last_pos = pos
	_pos_samples.append({"tick": SimAuthority.sim_tick, "x": pos.x, "z": pos.z})

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
		"position_samples": _pos_samples.size(),
		"distance_travelled": _origin_pos.distance_to(_last_pos),
		"speed_limit_per_tick": HPRules.max_travel_distance(HPProtocol.SIM_DT),
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

# ---------------------------------------------------------------------- common

func _finish(code: int) -> void:
	if not _records.is_empty() and out_path != "":
		var file := FileAccess.open(out_path, FileAccess.WRITE)
		if file:
			for record in _records:
				file.store_line(JSON.stringify(record))
			file.close()
	get_tree().quit(code)
