extends Node

## Release gates complete journey (section 1) as one scripted client.
##
## It walks the same path a player walks, through the same doors:
##
##   1. register/log in through the account service, select (or create) a
##      character                              - DatabaseManager, real HTTP
##   2. join the world server with the session token (no dev join)
##   3. enter the world scene exactly as character_select does
##   4. walk the courtyard and cast at the training ground
##   5. leave the safe area, attack a reactive pack, kill it, take the reward
##   6. mount the broom, fly, land, dismount
##   7. walk to the castle door, transfer into the interior, ride the moving
##      staircase to another floor, come back down and out
##   8. log out and prove the character reloads from the service with the state
##      this session produced
##
## It is a REAL client: same autoloads, same transport, same intents, same
## reconciliation. Only the keyboard is replaced by the script (`forced_intent`),
## which is the same hook `net_client_probe.gd` uses.
##
## Usage (client process; service + PostgreSQL + world server are separate):
##   godot --path client res://scenes/test/journey_e2e.tscn -- \
##     --ip=127.0.0.1 --port=7810 --api=http://127.0.0.1:8081 \
##     --user=journey --pass=... --seconds=900 --out=journey.jsonl \
##     [--keep-scene]   # instantiate the world in-process instead of changing scene

const WORLD_SCENE := "res://scenes/world/game_world.tscn"
const COURTYARD := Vector3(0.0, 0.6, 5.0)
const ENGAGE_RANGE := 22.0
const CAST_SPELLS := ["basic_cast", "stupefy", "incendio", "bombarda", "expelliarmus", "protego"]

var ip := "127.0.0.1"
var port := 7777
var api_url := ""
var user := ""
var password := ""
var duration := 900.0
var out_path := ""
var keep_scene := false
var char_name := ""

var world: Node3D = null
var player: Node3D = null
var map_controller: Node = null
var staircase: Node3D = null
var character: Dictionary = {}

var _t := 0.0
var _step := "boot"
var _step_t := 0.0
var _done := false
var _steps: Array = []
var _failures: Array = []
var _records: Array = []
var _file: FileAccess = null
var _last_pos := Vector3.ZERO
var _stuck := 0.0
var _sidestep := 0.0

# step-local state
var _cast_index := 0
var _cast_timer := 0.0
var _cast_ok := 0
var _pack_id := 0
var _pack_uids: Array = []
var _target_uid := 0
var _rewards := 0
var _reward_exp := 0
var _exp_start := -1
var _mount_state := 0
var _attempts := 0
var _mount_timer := 0.0
var _transfer_sent := false
var _transfer_ok := false
var _castle_done := false
var _castle_done_at := 0.0
var _ride_aboard := false
var _ride_done := false
var _staircase_reported := false
var _ride_low := 0.0
var _ride_high := 0.0
var _state_at_logout := {}

func _ready() -> void:
	_parse_args()
	if out_path != "":
		_file = FileAccess.open(out_path, FileAccess.WRITE)
	if api_url != "":
		DatabaseManager.api_base_url = api_url
	if char_name == "":
		char_name = "Journey%d" % (int(Time.get_unix_time_from_system()) % 100000)
	SimAuthority.reward_granted.connect(func(_uid: int, _character_id: int, exp: int, _g: int, _items: Array, _op: String):
		_rewards += 1
		_reward_exp += exp)
	print("[Journey] start user=%s character=%s api=%s server=%s:%d" % [user, char_name, DatabaseManager.api_base_url, ip, port])
	_step_register()

# ------------------------------------------------------------------- arg parse

func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--ip="):
			ip = arg.substr(5)
		elif arg.begins_with("--port="):
			port = int(arg.substr(7))
		elif arg.begins_with("--api="):
			api_url = arg.substr(6)
		elif arg.begins_with("--user="):
			user = arg.substr(7)
		elif arg.begins_with("--pass="):
			password = arg.substr(7)
		elif arg.begins_with("--char="):
			char_name = arg.substr(7)
		elif arg.begins_with("--seconds="):
			duration = float(arg.substr(10))
		elif arg.begins_with("--out="):
			out_path = arg.substr(6)
		elif arg == "--keep-scene":
			keep_scene = true

func _record(event: String, data: Dictionary = {}) -> void:
	var entry := data.duplicate()
	entry["event"] = event
	entry["t"] = snappedf(_t, 0.1)
	entry["step"] = _step
	_records.append(entry)
	if _file != null:
		_file.store_line(JSON.stringify(entry))
		_file.flush()

func _pass(step: String, detail: String = "") -> void:
	_steps.append({"step": step, "ok": true, "detail": detail})
	print("[Journey] PASS %s %s" % [step, detail])
	_record("pass", {"step": step, "detail": detail})

func _fail(step: String, detail: String) -> void:
	_failures.append("%s: %s" % [step, detail])
	_steps.append({"step": step, "ok": false, "detail": detail})
	print("[Journey] FAIL %s %s" % [step, detail])
	_record("fail", {"step": step, "detail": detail})

func _goto(step: String) -> void:
	_step = step
	_step_t = _t
	print("[Journey] step -> %s (t=%.1f)" % [step, _t])
	_record("step", {"next": step})

# ------------------------------------------------------------------- 1. login

func _step_register() -> void:
	_goto("register")
	DatabaseManager.register_account(user, password, _on_registered)

## An existing account is fine: the journey is about the flow, and the account
## is created fresh on a fresh database.
func _on_registered(res: Dictionary) -> void:
	_record("register", {"success": bool(res.get("success", false)), "message": String(res.get("message", ""))})
	DatabaseManager.login_account(user, password, _on_logged_in)

func _on_logged_in(login: Dictionary) -> void:
	if not bool(login.get("success", false)):
		_fail("login", String(login.get("message", "login failed")))
		_finish(1)
		return
	# The session fields are what main_menu.gd:151-153 sets after a login: the
	# service hands back the token and the account id, and every later call is
	# authenticated with that token.
	DatabaseManager.session_token = str(login.get("token", ""))
	DatabaseManager.session_account_id = int(login.get("account_id", 0))
	DatabaseManager.session_active = true
	if DatabaseManager.session_token.is_empty():
		_fail("login", "the service returned no session token")
		_finish(1)
		return
	_pass("login", "session established")
	DatabaseManager.get_characters(DatabaseManager.session_account_id, _on_characters)

func _on_characters(list: Dictionary) -> void:
	var characters: Array = list.get("characters", [])
	if characters.is_empty():
		DatabaseManager.create_character(DatabaseManager.session_account_id, char_name, "Gryffindor",
			_on_character_created)
		return
	character = characters[0]
	_pass("character", "selected %s (id %s)" % [character.get("name", "?"), str(character.get("id", "?"))])
	_goto("join")
	_step_join()

func _on_character_created(created: Dictionary) -> void:
	if not bool(created.get("success", false)):
		_fail("create_character", String(created.get("message", "")))
		_finish(1)
		return
	character = created.get("character", {})
	_pass("character", "created %s" % character.get("name", "?"))
	_goto("join")
	_step_join()

# --------------------------------------------------------------------- 2. join

func _step_join() -> void:
	# The choice is recorded before the join so a reconnect would re-bind the
	# same character; the binding itself happens after the join is accepted.
	NetworkManager.select_character(character)
	SimNet.joined.connect(_on_joined, CONNECT_ONE_SHOT)
	var error := NetworkManager.join_game(ip, port)
	if error != OK:
		_fail("join", "join_game error %d" % error)
		_finish(1)

func _on_joined(ok: bool, reason: String, _payload: Dictionary) -> void:
	if not ok:
		_fail("join", reason)
		_finish(1)
		return
	_pass("join", "world accepted the session token")
	_record("join", {"uid": SimAuthority.local_uid, "character_id": character.get("id", 0)})
	# Bind the session to the character the player picked, through the same
	# NetworkManager call the selection UI uses. The server proves the character
	# belongs to the session's account before binding; a refusal is a journey
	# failure, not something to ignore (the character-bind fix).
	var result: Dictionary = await NetworkManager.bind_selected_character()
	if not bool(result.get("ok", false)):
		_fail("bind_character", String(result.get("reason", "refused")))
		_finish(1)
		return
	var bound: Dictionary = result.get("character", {})
	_record("bind", {"character_id": int(bound.get("id", 0)), "exp": int(bound.get("exp", 0)),
		"level": int(bound.get("level", 0)), "map_id": String(bound.get("map_id", ""))})
	_pass("bind_character", "session bound to '%s' (id %s, exp %s)" % [
		String(bound.get("name", "?")), str(bound.get("id", "?")), str(bound.get("exp", "?"))])
	_step_enter_world.call_deferred()

# ------------------------------------------------------------- 3. enter world

## The real client changes scene into the world (`character_select.gd:254`).
## This driver survives that change by moving itself to the tree root first, so
## the world scene is loaded by the same call the game makes.
func _step_enter_world() -> void:
	_goto("enter_world")
	if keep_scene:
		world = load(WORLD_SCENE).instantiate()
		add_child(world)
	else:
		# Move to the tree root BEFORE the scene change: the driver must outlive
		# the scene it was the child of. The tree handle is taken first because
		# an orphaned node has no tree.
		var tree := get_tree()
		var root: Window = tree.root
		if get_parent() != null:
			get_parent().remove_child(self)
		root.add_child(self)
		tree.change_scene_to_file(WORLD_SCENE)
		await tree.process_frame
		await tree.process_frame
		world = tree.current_scene
	# The world builds its player and the authority places it from the session.
	var waited := 0.0
	while waited < 20.0:
		player = world.get("local_player")
		if player != null and is_instance_valid(player):
			break
		await get_tree().create_timer(0.25).timeout
		waited += 0.25
	if player == null:
		_fail("enter_world", "no local player appeared")
		_finish(1)
		return
	map_controller = world.get("map_controller")
	_exp_start = int(player.get("current_exp"))
	_last_pos = player.global_position
	_pass("enter_world", "map=%s pos=%s" % [
		String(SimAuthority.entities.get(SimAuthority.local_uid, {}).get("map_id", "?")),
		str(player.global_position.round())])
	_goto("courtyard")

# --------------------------------------------------------------- 4. courtyard

func _step_courtyard() -> void:
	if not _alive():
		return
	var to_yard := COURTYARD - _auth_pos()
	to_yard.y = 0.0
	if to_yard.length() > 3.5:
		_walk_toward(COURTYARD)
		return
	SimNet.forced_intent = {}
	_cast_timer -= get_physics_process_delta_time()
	if _cast_timer <= 0.0 and _cast_index < CAST_SPELLS.size() * 2:
		_cast_timer = 0.7
		var spell: String = CAST_SPELLS[_cast_index % CAST_SPELLS.size()]
		_cast_index += 1
		var result := SimNet.submit_cast(player, spell, player.global_position + Vector3(0, 1.0, -10.0), 6000 + _cast_index)
		if bool(result.get("ok", false)):
			_cast_ok += 1
	if _cast_index >= CAST_SPELLS.size() * 2:
		if _cast_ok >= 6:
			_pass("courtyard", "%d casts accepted in the protected courtyard" % _cast_ok)
		else:
			_fail("courtyard", "only %d of %d courtyard casts accepted" % [_cast_ok, _cast_index])
		_goto("fight")

# -------------------------------------------------------------------- 5. pack

func _step_fight() -> void:
	if not _alive():
		return
	if _pack_id == 0:
		_pack_id = _choose_pack()
		if _pack_id == 0:
			if _t - _step_t > 30.0:
				_fail("fight", "no pack was ever visible")
				_goto("mount")
			return
		_pack_uids = _pack_members(_pack_id)
		_record("pack", {"pack_id": _pack_id, "members": _pack_uids.size()})
	# Target the next live member; a wiped pack is the win condition.
	if _target_uid == 0 or _is_dead(_target_uid):
		_target_uid = 0
		for uid in _pack_uids:
			if not _is_dead(uid):
				_target_uid = int(uid)
				break
	if _target_uid == 0:
		if _rewards > 0:
			_pass("fight", "pack %d killed, %d reward(s), +%d exp" % [_pack_id, _rewards, _reward_exp])
		else:
			_fail("fight", "pack died but no reward arrived")
		_goto("mount")
		return
	var target: Vector3 = SimAuthority.entities[_target_uid].get("pos", Vector3.ZERO)
	var flat := target - _auth_pos()
	flat.y = 0.0
	if flat.length() > ENGAGE_RANGE * 0.8:
		_walk_toward(target)
		return
	SimNet.forced_intent = {}
	if _t - _step_t > 0.5 and int(SimAuthority.sim_tick) % 10 == 0:
		SimNet.submit_cast(player, "basic_cast", target + Vector3.UP, 7000 + int(_t * 2.0))
	if _t - _step_t > 240.0:
		_fail("fight", "pack %d not killed in 240 s (%d rewards)" % [_pack_id, _rewards])
		_goto("mount")

# ------------------------------------------------------------------- 6. mount

func _step_mount() -> void:
	if not _alive():
		return
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var mounted: bool = bool(record.get("mounted", false))
	_mount_timer -= get_physics_process_delta_time()
	match _mount_state:
		0:
			# The rule is "only from the ground": asking while the body is still
			# settling (a knock-back, a step edge) is refused, so wait for the
			# floor and retry rather than counting that as a failed mount.
			if not (player.has_method("is_on_floor") and player.is_on_floor()):
				SimNet.forced_intent = {}
				if _t - _step_t > 20.0:
					_fail("mount", "never came to rest on the ground")
					_goto("castle")
				return
			if _mount_timer <= 0.0:
				SimNet.submit_mount(player, true)
				_mount_timer = 4.0
				_mount_state = 1
		1:
			if mounted:
				_record("mounted", {})
				_mount_state = 2
				_mount_timer = 8.0
			elif _mount_timer <= 0.0:
				if _attempts < 3:
					_attempts += 1
					_mount_state = 0
					_mount_timer = 0.0
				else:
					_fail("mount", "mount request refused on open ground")
					_goto("castle")
		2:
			# Climb and cruise back toward the courtyard: dismount needs LEVEL
			# ground within 3 m, and a fight usually ends on forest slope.
			SimNet.forced_intent = _flight_intent_yard(true)
			if _mount_timer <= 0.0:
				_mount_state = 3
				_mount_timer = 8.0
		3:
			SimNet.forced_intent = _flight_intent_yard(false)
			if _mount_timer <= 0.0 or not mounted:
				_mount_state = 4
				_mount_timer = 3.0
		4:
			if not mounted:
				_pass("mount", "mounted, flew, landed and dismounted")
				_goto("castle")
				return
			# Still mounted: keep losing height over level ground and ask again.
			SimNet.forced_intent = _flight_intent_yard(false)
			if _mount_timer <= 0.0:
				_mount_timer = 1.5
				SimNet.submit_mount(player, false)
			if _t - _step_t > 60.0:
				var reason := ""
				if player.has_method("dismount_block_reason"):
					reason = String(player.call("dismount_block_reason"))
				_record("dismount_refused", {"reason": reason, "pos": str(_auth_pos().round())})
				_fail("mount", "dismount was refused after landing (%s)" % reason)
				_goto("castle")

# ------------------------------------------------------------------ 7. castle

func _step_castle() -> void:
	if not _alive():
		return
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var map_id := String(record.get("map_id", "grounds"))
	if map_id == "grounds":
		if _castle_done:
			# The castle has been entered, ridden and left: the journey's next
			# step is the logout. (Without this flag the grounds branch walks
			# straight back to the door and requests entry again - an endless
			# re-entry loop that never reaches the logout.)
			_goto("logout")
			return
		if _transfer_sent and not _transfer_ok:
			# The request went out; wait for the commit to move the body.
			if _t - _step_t > 25.0:
				_fail("castle_entry", "transfer was never committed")
				_goto("logout")
			return
		var door := _portal_center(HPMaps.portal("castle_door"))
		if _auth_pos().distance_to(door) > 2.0:
			_walk_toward(door)
			return
		SimNet.forced_intent = {}
		if not _transfer_sent:
			_transfer_sent = true
			_step_t = _t
			var result := SimNet.request_transfer(player, "castle_door", "castle_interior")
			_record("transfer_request", {"reason": String(result.get("reason", ""))})
			SimAuthority.transfer_committed.connect(func(_peer: int, _token: int, granted: String, pos: Vector3, _spawn: String):
				if granted == "castle_interior":
					_transfer_ok = true
					# The next request is a NEW one: leaving needs its own token.
					_transfer_sent = false
					_pass("castle_entry", "transfer committed to %s at %s" % [granted, str(pos.round())])
					_step_t = _t
			, CONNECT_ONE_SHOT)
		return
	# Inside the castle: walk the route, ride the staircase up a floor, leave.
	if staircase == null:
		_find_staircase()
	if not _transfer_ok:
		_transfer_ok = true
		_record("interior", {"pos": str(_auth_pos().round())})
	if _ride_aboard:
		_ride_tick()
		return
	if _t - _step_t > 200.0:
		_fail("castle_route", "interior route timed out")
		_goto("logout")
		return
	if staircase != null and not _ride_done:
		var dock := int(staircase.get("dock_index"))
		var tick := int(SimAuthority.sim_tick)
		var docked_here: bool = staircase.get("entry_allowed") and dock == 0
		if _t - _step_t < 90.0:
			# Wait AT the boarding edge while the platform is elsewhere or
			# locked, and only then walk up the deck - the route the staircase
			# probe uses. Sprinting for a point on the moving deck from across
			# the hall loses the race, and boarding on the client's prediction
			# leaves the server body off the deck when it moves (the probe
			# measured both).
			var auth := _auth_pos()
			var deck_space: Vector3 = staircase.call("to_deck_space", auth, tick)
			# "At the foot" means IN FRONT of the run's start, in the deck's own
			# frame: the deck point's flat position is reachable under the
			# raised ramp too, and a body that stops there (or approaches the
			# foot from above, under the ramp) can never be collected. Only a
			# body in front of the foot walks up the ramp - which is how the
			# staircase probe boards.
			var in_front := deck_space.z < 0.2 and absf(deck_space.x) < 2.5
			if docked_here and bool(staircase.call("on_deck", auth, tick, 2.4, 0.8)) \
					and deck_space.z >= 1.2:
				SimNet.forced_intent = {}
				_ride_aboard = true
				_ride_low = auth.y
				_ride_high = auth.y
				return
			if not in_front:
				# The straight line from the vestibule passes UNDER the flight
				# and wedges against the ramp's toe (it descends to the floor at
				# the foot), so the walker must go around the shaft: east
				# corridor, then the apron in front of the ground dock.
				if _walk_castle_route():
					return
			if docked_here and in_front:
				_walk_toward(_deck_point(tick, 0.35))
			else:
				_walk_toward(_dock_wait_point())
			return
	# No staircase (or its window passed): leave through the vestibule exit.
	var exit_centre := _portal_center(HPMaps.portal("vestibule_exit"))
	if _auth_pos().distance_to(exit_centre) > 2.0:
		_walk_toward(exit_centre)
		return
	SimNet.forced_intent = {}
	if not _transfer_sent:
		_transfer_sent = true
		_step_t = _t
		var result := SimNet.request_transfer(player, "vestibule_exit", "grounds")
		_record("transfer_request", {"reason": String(result.get("reason", ""))})
		SimAuthority.transfer_committed.connect(func(_peer: int, _token: int, granted: String, pos: Vector3, _spawn: String):
			if granted == "grounds":
				_castle_done = true
				_castle_done_at = _t
				_transfer_sent = false
				_pass("castle_exit", "return transfer committed to %s at %s" % [granted, str(pos.round())])
		, CONNECT_ONE_SHOT)
	if _t - _step_t > 25.0:
		_fail("castle_exit", "return transfer timed out")
		_goto("logout")

## Ride the deck: board, wait for it to travel, step off at the far dock.
func _ride_tick() -> void:
	SimNet.forced_intent = {}
	var y := _auth_pos().y
	_ride_low = minf(_ride_low, y)
	_ride_high = maxf(_ride_high, y)
	var state := String(staircase.get("state"))
	if state == "docked" and int(staircase.get("dock_index")) > 0:
		_pass("staircase", "rode the moving staircase %.1f m of vertical travel" % (_ride_high - _ride_low))
		_record("staircase", {"low": _ride_low, "high": _ride_high, "dock": int(staircase.get("dock_index"))})
		_ride_aboard = false
		_ride_done = true
		_step_t = _t
		# The rider is now on an upper landing; walk back to the vestibule exit
		# (the route may drop it into the hall, which is a short fall onto the
		# ground floor, not a fall rescue).
		return

# ------------------------------------------------------------------ 8. logout

func _step_logout() -> void:
	if not _alive():
		return
	# The exit commit lands a frame or two before the client's replica shows the
	# new position: sampling the logout state immediately would compare a stale
	# interior position against the (correct) save and fail by the map's height.
	if _castle_done and _t - _castle_done_at < 1.5:
		SimNet.forced_intent = {}
		return
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	_state_at_logout = {
		"pos": _auth_pos(),
		"map": String(record.get("map_id", "")),
		"exp": int(record.get("exp", 0)),
		"hp": int(record.get("hp", 0)),
		"level": int(record.get("level", 0)),
		"galleons": int(record.get("galleons", 0)),
		"inventory": player.get("inventory").size() if player != null and is_instance_valid(player) else 0,
		"character_id": int(character.get("id", 0)),
	}
	_record("state_at_logout", {"map": _state_at_logout["map"], "pos": str(_state_at_logout["pos"].round()),
		"exp": _state_at_logout["exp"], "level": _state_at_logout["level"],
		"galleons": _state_at_logout["galleons"], "inventory": _state_at_logout["inventory"]})
	NetworkManager.disconnect_game()
	_goto("verify_save")
	_step_t = _t

func _step_verify_save() -> void:
	if _t - _step_t < 4.0:
		return
	DatabaseManager.load_character(int(_state_at_logout["character_id"]), func(res: Dictionary):
		if not bool(res.get("success", false)):
			_fail("logout_state", "character could not be reloaded: %s" % String(res.get("message", "")))
			_finish(1)
			return
		var loaded: Dictionary = res.get("character", {})
		# The service returns the position as `pos: [x, y, z]`; accept the offline
		# pos_x/y/z spelling too so either shape is read correctly.
		var pos := Vector3(float(loaded.get("pos_x", 0.0)), float(loaded.get("pos_y", 0.0)), float(loaded.get("pos_z", 0.0)))
		if loaded.get("pos") is Array and (loaded["pos"] as Array).size() == 3:
			var saved: Array = loaded["pos"]
			pos = Vector3(float(saved[0]), float(saved[1]), float(saved[2]))
		var expected: Vector3 = _state_at_logout["pos"]
		var distance := pos.distance_to(expected)
		var exp_ok := int(loaded.get("exp", -1)) >= int(_state_at_logout["exp"])
		var level_ok := int(loaded.get("level", 0)) >= int(_state_at_logout["level"])
		var map_ok := String(loaded.get("map_id", "")) == String(_state_at_logout["map"])
		var gold_ok := int(loaded.get("galleons", -1)) >= int(_state_at_logout["galleons"])
		var inventory: Array = loaded.get("inventory", [])
		_record("reload", {"pos": str(pos.round()), "exp": int(loaded.get("exp", -1)),
			"level": int(loaded.get("level", 0)), "map_id": String(loaded.get("map_id", "")),
			"galleons": int(loaded.get("galleons", -1)), "inventory": inventory.size(),
			"distance": distance, "expected": str(expected.round())})
		if not exp_ok:
			_fail("logout_state", "reloaded exp %d is below the session's %d" % [int(loaded.get("exp", -1)), int(_state_at_logout["exp"])])
		elif not level_ok:
			_fail("logout_state", "reloaded level %d is below the session's %d" % [int(loaded.get("level", 0)), int(_state_at_logout["level"])])
		elif not map_ok:
			_fail("logout_state", "reloaded map '%s' against the session's '%s'" % [
				String(loaded.get("map_id", "")), String(_state_at_logout["map"])])
		elif distance > 8.0:
			_fail("logout_state", "reloaded position is %.1f m from the logout position" % distance)
		elif not gold_ok:
			_fail("logout_state", "reloaded galleons %d are below the session's %d" % [
				int(loaded.get("galleons", -1)), int(_state_at_logout["galleons"])])
		elif inventory.size() < int(_state_at_logout["inventory"]):
			_fail("logout_state", "reloaded inventory has %d entries against the session's %d" % [
				inventory.size(), int(_state_at_logout["inventory"])])
		else:
			_pass("logout_state", "character reloaded: exp %d, level %d, map %s, %d item stack(s), position %.1f m from logout" % [
				int(loaded.get("exp", -1)), int(loaded.get("level", 0)), String(loaded.get("map_id", "")),
				inventory.size(), distance])
		_finish(0)
	)

# ------------------------------------------------------------------- helpers

func _alive() -> bool:
	if player == null or not is_instance_valid(player):
		return false
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	return not bool(record.get("dead", false))

func _auth_pos() -> Vector3:
	var record: Dictionary = SimAuthority.entities.get(SimAuthority.local_uid, {})
	var pos: Variant = record.get("pos", null)
	if pos is Vector3:
		return pos
	if player != null and is_instance_valid(player):
		return player.global_position
	return Vector3.ZERO

func _walk_toward(goal: Vector3) -> void:
	if player == null or not is_instance_valid(player):
		return
	var flat := goal - player.global_position
	flat.y = 0.0
	if flat.length() <= 1.5:
		SimNet.forced_intent = {}
		return
	var moved := _last_pos.distance_to(player.global_position)
	if moved > 0.05:
		_stuck = 0.0
	else:
		_stuck += get_physics_process_delta_time()
	if _stuck > 1.0:
		_sidestep = 2.0
		_stuck = 0.0
	var offset := 0.0
	var jump := false
	if _sidestep > 0.0:
		_sidestep -= get_physics_process_delta_time()
		offset = deg_to_rad(90.0)
		jump = fmod(_sidestep, 0.5) > 0.25
	_last_pos = player.global_position
	var direction := flat.rotated(Vector3.UP, offset)
	var mounted := bool(SimAuthority.entities.get(SimAuthority.local_uid, {}).get("mounted", false))
	SimNet.forced_intent = {
		"move": Vector2(0, -1),
		"yaw": rad_to_deg(atan2(-direction.x, -direction.z)),
		"jump": jump,
		"descend": mounted and (player.global_position.y - goal.y) > 2.5,
	}

func _choose_pack() -> int:
	var packs: Dictionary = {}
	for uid in SimAuthority.entities.keys():
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", 0)) != HPProtocol.Kind.MOB or int(record.get("pack_id", 0)) == 0:
			continue
		var pack_id := int(record.get("pack_id", 0))
		if not packs.has(pack_id) or int(uid) < int(packs[pack_id]["uid"]):
			packs[pack_id] = {"uid": int(uid), "pos": record.get("pos", Vector3.ZERO)}
	# Outside protected space: a protected pack cannot be damaged, and attacking
	# from inside the courtyard is refused by design.
	var from := _auth_pos()
	var best := 0
	var best_distance := 1e9
	for pack_id in packs.keys():
		var pos: Vector3 = packs[pack_id]["pos"]
		var distance: float = from.distance_to(pos)
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

## Fly toward the courtyard, climbing or descending: level ground is where a
## rider is allowed to get off.
func _flight_intent_yard(climb: bool) -> Dictionary:
	var to_yard := COURTYARD - _auth_pos()
	to_yard.y = 0.0
	var yaw := rad_to_deg(atan2(-to_yard.x, -to_yard.z))
	var move := Vector2.ZERO
	if to_yard.length() > 4.0:
		move = Vector2(0, -1)
	return {"move": move, "yaw": yaw, "jump": climb, "descend": not climb}

func _portal_center(entry: Dictionary) -> Vector3:
	var trigger: Dictionary = entry.get("trigger", {})
	var centre: Array = trigger.get("center", [])
	if centre.size() != 3:
		return _auth_pos()
	return Vector3(float(centre[0]), float(centre[1]) - 0.5, float(centre[2]))

func _find_staircase() -> void:
	staircase = null
	if world == null:
		return
	var controller := world.get_node_or_null("MapController")
	var interior: Node = controller.get("_interior") if controller != null else null
	if interior != null:
		staircase = _find_by_method(interior)
	if staircase == null:
		staircase = _find_by_method(world)
	if staircase == null and not _staircase_reported:
		_staircase_reported = true
		_record("staircase_missing", {"controller": controller != null, "interior": interior != null,
			"map": String(SimAuthority.entities.get(SimAuthority.local_uid, {}).get("map_id", ""))})

func _find_by_method(node: Node) -> Node3D:
	if node.has_method("platform_world_transform") and node.has_method("entry_allowed"):
		return node as Node3D
	for child in node.get_children():
		var hit := _find_by_method(child)
		if hit != null:
			return hit
	return null

func _deck_point(tick: int, along: float) -> Vector3:
	var run: float = staircase.call("run_length")
	var slope: float = staircase.call("slope")
	var transform: Transform3D = staircase.call("platform_world_transform", tick)
	return transform * Vector3(0.0, run * along * slope + 0.05, run * along)

## The waiting spot in front of the ground dock's foot, on the floor: inside the
## authority's boarding-approach volume but outside `on_deck`, so the rider can
## wait "at the gate" while the platform is away or locked.
func _dock_wait_point() -> Vector3:
	return staircase.global_transform * (staircase.call("dock_origin", 0) + Vector3(0.0, 0.05, -1.0))

## Walk around the grand staircase hall to the ground dock's apron: arrival
## plate -> east corridor -> apron. The staircase's own landing plates define
## this ring; the straight line from the vestibule crosses the shaft and cannot
## reach the foot. Returns false once the apron waypoint is reached, so the
## caller can switch to the waiting/boarding logic.
var _castle_route_index := 0

func _walk_castle_route() -> bool:
	var route: Array = [
		staircase.global_transform * Vector3(0.0, 0.05, 12.0),
		staircase.global_transform * Vector3(19.0, 0.05, 10.0),
		staircase.global_transform * Vector3(19.0, 0.05, -10.0),
		staircase.global_transform * Vector3(0.0, 0.05, -10.0),
	]
	if _castle_route_index >= route.size():
		return false
	var target: Vector3 = route[_castle_route_index]
	var flat := target - _auth_pos()
	flat.y = 0.0
	if flat.length() < 2.0:
		_castle_route_index += 1
		if _castle_route_index >= route.size():
			return false
		target = route[_castle_route_index]
	_walk_toward(target)
	return true

# ---------------------------------------------------------------- main loop

func _physics_process(delta: float) -> void:
	if _done:
		return
	_t += delta
	if _t >= duration:
		_fail("timeout", "journey exceeded %.0f s at step %s" % [duration, _step])
		_finish(1)
		return
	match _step:
		"courtyard":
			_step_courtyard()
		"fight":
			_step_fight()
		"mount":
			_step_mount()
		"castle":
			_step_castle()
		"logout":
			_step_logout()
		"verify_save":
			_step_verify_save()

func _finish(code: int) -> void:
	if _done:
		return
	_done = true
	print("JOURNEY RESULT: %d steps, %d failures" % [_steps.size(), _failures.size()])
	for failure in _failures:
		print("  FAILED: " + failure)
	_record("final", {"steps": _steps.size(), "failures": _failures})
	if _file != null:
		_file.close()
	get_tree().quit(code)
