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
##     --mode=agree|forged|protection --port=7777 --name=Alice --out=<file> [--seconds=25]

const WORLD_SCENE = preload("res://scenes/world/game_world.tscn")

var mode := "agree"
var port := 7777
var probe_name := "Probe"
var out_path := ""
var duration := 25.0

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
var _stuck_timer := 0.0
var _sidestep_timer := 0.0

func _ready() -> void:
	_parse_args()
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
		_record("disconnected", {"reason": reason}))
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

func _record(event: String, data: Dictionary) -> void:
	data["event"] = event
	data["t"] = _t
	data["tick"] = SimAuthority.sim_tick
	_records.append(data)

# ------------------------------------------------------------------ agreement

func _on_joined(ok: bool, reason: String, _character: Dictionary) -> void:
	_joined = ok
	_record("joined", {"ok": ok, "reason": reason, "uid": SimAuthority.local_uid})
	if not ok:
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

func _on_cast_ack(_cast_seq: int, _cast_id: int, ok: bool, reason: String) -> void:
	if ok:
		_casts_accepted += 1
	else:
		_casts_rejected.append(reason)
		_record("cast_rejected", {"reason": reason})

func _physics_process(delta: float) -> void:
	_t += delta
	if mode == "protection" or _done:
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

	# --- (1) delayed projectile from a mob into the courtyard.
	var hp_before := int(player.current_hp)
	record["hp"] = hp_before
	var dir := (courtyard - mob.global_position).normalized()
	mob.global_position = outside + Vector3(0, 0, 0)
	SimAuthority.mob_projectile(mob, "stupefy", (courtyard - mob.global_position).normalized(), 500)
	await get_tree().create_timer(1.2).timeout
	results["projectile_into_zone"] = {"before": hp_before, "after": int(player.current_hp)}
	player.current_hp = hp_before

	# --- (2) the same projectile with the target OUTSIDE the zone (positive
	# control): protection must be the only reason nothing landed above.
	player.global_position = outside + Vector3(10, 0, 10)
	record["hp"] = hp_before
	SimAuthority.mob_projectile(mob, "stupefy", (player.global_position - mob.global_position).normalized(), 500)
	await get_tree().create_timer(1.2).timeout
	results["projectile_outside_zone"] = {"before": hp_before, "after": int(player.current_hp)}

	# --- (3) burn ticks while the victim is inside a safe volume. The burn is
	# applied to the mob while it stands outside, then the mob walks into the
	# zone: the ticks that land inside must deal nothing.
	mob.global_position = outside
	record["hp"] = hp_before
	SimAuthority.apply_damage(mob, 1, "incendio", player)     # starts the burn
	var burn_before := int(mob.current_hp)
	mob.global_position = courtyard
	# Hold the mob still: its AI walks a displaced mob home (Phase 1), which
	# would move it back out of the zone mid-measurement and make the assertion
	# about pathing instead of about protection.
	mob.set_physics_process(false)
	await get_tree().create_timer(3.5).timeout
	results["burn_inside_zone"] = {"before": burn_before, "after": int(mob.current_hp)}
	mob.set_physics_process(true)

	# --- (4) boss AoE from OUTSIDE whose circle covers a player standing INSIDE
	# the zone: the attacker is legal, the victim is protected.
	mob.global_position = outside
	player.global_position = courtyard
	record["hp"] = hp_before
	player.set("current_hp", hp_before)
	var hits: Array = SimAuthority.mob_area_attack(mob, courtyard, 6.0, 800, "boss_slam")
	await get_tree().process_frame
	results["boss_aoe_over_zone"] = {"hits": hits.size(), "before": hp_before, "after": int(player.current_hp)}

	# --- (5) positive control: the same slam, everything outside protection.
	var far := Vector3(70, 0.5, 70)
	player.global_position = far
	record["hp"] = hp_before
	player.set("current_hp", hp_before)
	var hits_out: Array = SimAuthority.mob_area_attack(mob, far, 6.0, 800, "boss_slam")
	await get_tree().process_frame
	results["boss_aoe_outside_zone"] = {"hits": hits_out.size(), "before": hp_before, "after": int(player.current_hp)}

	_record("protection", results)
	_done = true
	_finish(0)

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
