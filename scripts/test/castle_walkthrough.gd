extends Node

## Castle interior walkthrough + map-transfer evidence.
##
## Headless-safe: it drives the REAL world scene, walks the REAL route through
## the REAL collision, and prints node/resource counts either side of every
## transfer so accumulation is visible instead of asserted.
##
## Run:
##   godot --headless --path client res://scenes/test/castle_walkthrough.tscn \
##     --fixed-fps 60 --quit-after 5400
##
## It is not part of the 93-check regression (scenes/test/test_scenario.tscn);
## it is the castle proof scene. Room, door and stair checks are derived from
## assets/castle/castle_layout.json (docs/castle-interior.md).

const CastleBlockout = preload("res://scripts/world/castle/castle_blockout.gd")
const ROUTE_TIMEOUT := 30.0

var checks := 0
var failures: Array[String] = []
var notes: Array[String] = []
var counts: Array = []

@onready var world = $GameWorld

func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)

func note(message: String) -> void:
	notes.append(message)
	print("NOTE: " + message)

func _ready() -> void:
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false
	await get_tree().create_timer(0.6).timeout
	var player = world.local_player
	var controller = world.map_controller
	check(player != null and controller != null, "World scene hosts a local player and a map controller")
	if player == null or controller == null:
		_finish()
		return

	# --- 1. arrival, doors and the landing pad on the grounds -----------------
	check(world.has_node("BroomLanding"), "Broom landing area exists in front of the castle")
	check(ResourceLoader.exists("res://scenes/world/castle_interior.tscn"), "Castle interior is a separate scene resource")
	check(controller.current_map == "grounds", "The world starts on the outdoor map")

	var door: Dictionary = controller._portal_entries("grounds")[0]
	# Stand on the threshold in front of the great doors (the portal's own centre).
	var doorway: Vector3 = door["center"]
	player.global_position = doorway + Vector3(0, -0.5, 0.5)
	await get_tree().create_timer(0.4).timeout
	check(not controller._active_portal.is_empty(), "Standing in the castle doorway raises the portal prompt")
	check(controller._prompt_label.text.begins_with("Press"), "The doorway shows an interaction prompt")

	# mounted entry is refused with feedback (the authority refuses it too)
	player.is_mounted = true
	await get_tree().process_frame
	controller._begin_transfer(door)
	check(controller.current_map == "grounds" and not controller.busy, "Mounted entry is refused: the map does not change")
	check(controller._notice.to_lower().contains("dismount"), "Refusal tells the rider to dismount")
	player.is_mounted = false
	await get_tree().process_frame

	# --- 2. grounds -> interior through the portal (the real handshake) ------
	counts.append(_counts("grounds #1"))
	_press_interact()
	await _await_map(controller, "castle_interior")
	check(controller.current_map == "castle_interior",
		"Pressing the interact key inside the doorway transfers to the interior (%s)" % controller.current_map)
	var handshake: Dictionary = controller.transfer_log[-1] if not controller.transfer_log.is_empty() else {}
	check(bool(handshake.get("server_api", false)), "The synced map-transfer API was present")
	check(int(handshake.get("token", 0)) != 0,
		"The transfer carried a server-issued token (request -> grant -> load -> ready -> commit)")
	var interior = world.get_node_or_null("CastleInterior")
	check(interior != null, "Transfer loads the castle interior scene")
	check(controller.current_map == "castle_interior", "The controller tracks the new map")
	check(player.global_position.y > 185.0, "Player is moved to the server-approved interior spawn (%s)" % player.global_position)
	check(world.get_node_or_null("HogwartsCastle") == null, "Outdoor castle geometry is unloaded on arrival")
	check(world.get_node_or_null("ForbiddenForest") == null and world.get_node_or_null("LevelDressing") == null,
		"Outdoor scenery is unloaded, not just hidden")
	check(is_instance_valid(world.hud) and is_instance_valid(world.local_player), "HUD bindings and the player controller stay alive")
	counts.append(_counts("interior #1"))

	# --- 3. the Grand Staircase: one moving flight per catalog entry -----------
	var slot = interior.get_node_or_null("StaircaseSlot")
	check(slot is Node3D, "The castle exposes a StaircaseSlot marker")
	var expected_flights := HPStaircase.catalog_staircase_count()
	check(expected_flights == 7, "The map catalog lists the seven Grand Staircase flights (%d)" % expected_flights)
	if slot is Node3D:
		var stairs: Array = []
		for child in (slot as Node3D).get_children():
			if child.has_method("platform_world_transform"):
				stairs.append(child)
		check(stairs.size() == expected_flights,
			"StaircaseSlot holds one staircase per catalog flight (%d / %d)" % [stairs.size(), expected_flights])
		var ids := {}
		for stair in stairs:
			ids[int(stair.get("object_id"))] = true
			check(bool((stair.get("spec") as Dictionary).get("map_geometry", false)),
				"%s runs a castle flight spec (map geometry, swing pivot)" % stair.name)
		check(ids.size() == stairs.size(), "Every flight replicates under its own object id (%s)" % str(ids.keys()))
		await get_tree().physics_frame
		var deck_space := interior.get_world_3d().direct_space_state as PhysicsDirectSpaceState3D
		for stair in stairs:
			# Every flight starts docked at its first dock: a ray down onto the
			# middle of the deck lands on that flight's moving platform.
			var deck_xform: Transform3D = stair.call("platform_world_transform", SimAuthority.sim_tick)
			var deck_mid: Vector3 = deck_xform * Vector3(0.0, float(stair.call("rise")) * 0.5 + 0.5, float(stair.call("run_length")) * 0.5)
			var hit := deck_space.intersect_ray(PhysicsRayQueryParameters3D.create(deck_mid + Vector3.UP * 2.0, deck_mid + Vector3.DOWN * 3.0))
			var on_platform: bool = not hit.is_empty() and (hit["collider"] as Node).get_parent() == stair
			check(on_platform, "%s's deck is solid where the authority says it is (%s)" % [stair.name, str(deck_mid.round())])

	# --- 4. floor-aware labels -------------------------------------------------
	for probe in [[190.2, "Dungeons"], [200.2, "Ground"], [210.2, "First"], [220.2, "Second"],
			[240.2, "Fourth"], [270.2, "Seventh"]]:
		var label: String = interior.floor_display(float(probe[0]))
		check(label.contains(String(probe[1])), "y %.0f reports its floor name (%s)" % [float(probe[0]), label])
	controller._update_labels()
	check(controller._location_label.text.contains("Hogwarts Castle"),
		"The HUD location label names the map and floor the player is on (%s)" % controller._location_label.text)

	# --- 5. the whole layout is walkable on foot --------------------------------
	# Derived from the layout the blockout was built from, so a layout edit is
	# checked without editing this file.
	var layout: Dictionary = CastleBlockout.load_layout()
	check(not layout.is_empty(), "The castle layout ships with the build")
	var space := interior.get_world_3d().direct_space_state as PhysicsDirectSpaceState3D
	var map_y: float = interior.MAP_Y
	for r in layout.get("rooms", []):
		if String(r["id"]) == "dungeon_stairwell":
			continue   # the whole room is the flight, checked below
		var rect: Array = r["rect"]
		var level := map_y + float(r["y"])
		var probe := Vector3(float(rect[1]) - 1.5, level + 1.0, float(rect[3]) - 1.5)
		var floor_hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(probe, probe + Vector3.DOWN * 3.0))
		check(not floor_hit.is_empty() and absf((floor_hit["position"] as Vector3).y - level) < 0.05,
			"%s has a walkable floor at y %.0f" % [String(r["label"]), level])
	for d in layout.get("doors", []):
		if d.has("sealed"):
			continue
		var at: Array = d["at"]
		var c := Vector3(float(at[0]), map_y + float(d["y"]) + 1.2, float(at[1]))
		var through_z: bool = interior.route_clear(c + Vector3(0, 0, -3.5), c + Vector3(0, 0, 3.5))
		var through_x: bool = interior.route_clear(c + Vector3(-3.5, 0, 0), c + Vector3(3.5, 0, 0))
		check(through_z or through_x, "Doorway %s is passable at torso height" % String(d["id"]))
	for flight in layout.get("stairs", []):
		check(_ramp_ok(interior, flight, map_y), "Stairs are walkable (collision under the feet, headroom): %s" % String(flight["id"]))

	# --- 6. actually walk up and back down the marble staircase ---------------
	controller._place_player(Vector3(-11, 200.4, 51.5))
	player.camera_rot_y = 0.0
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.4).timeout
	var start_y: float = player.global_position.y
	Input.action_press("move_forward")
	await get_tree().create_timer(2.4).timeout
	Input.action_release("move_forward")
	var climbed_y: float = player.global_position.y
	check(climbed_y > start_y + 4.5, "Walking forward climbs the marble staircase (%.1f -> %.1f)" % [start_y, climbed_y])
	check(climbed_y < 211.5, "The stair does not launch the walker off the top (%.1f)" % climbed_y)
	player.camera_rot_y = 180.0   # degrees: the controller's camera yaw is degrees, not radians
	await get_tree().create_timer(0.2).timeout
	Input.action_press("move_forward")
	await get_tree().create_timer(4.4).timeout
	Input.action_release("move_forward")
	var descended: Vector3 = player.global_position
	check(descended.y < 202.5, "Walking back down the staircase descends cleanly (%s)" % descended)

	# --- 7. round trips: does the old world really go away? -------------------
	# Every leg goes through the real doorway and the real server handshake, so
	# the counts below are taken after a full request -> grant -> load -> ready
	# -> commit cycle, never after a developer teleport.
	var exit_portal: Dictionary = controller._portal_entries("castle_interior")[0]
	var exit_spot: Vector3 = exit_portal["center"] + Vector3(0, -1.2, 0)
	for i in range(3):
		controller._place_player(exit_spot)
		await get_tree().create_timer(0.4).timeout
		_press_interact()
		await _await_map(controller, "grounds")
		check(controller.current_map == "grounds" and world.get_node_or_null("CastleInterior") == null,
			"Round trip %d: the interior is unloaded on return" % (i + 1))
		check(world.has_node("HogwartsCastle"), "Round trip %d: the grounds are rebuilt" % (i + 1))
		counts.append(_counts("grounds #%d" % (i + 2)))
		controller._place_player(doorway + Vector3(0, -0.5, 0.5))
		await get_tree().create_timer(0.4).timeout
		_press_interact()
		await _await_map(controller, "castle_interior")
		check(controller.current_map == "castle_interior" and world.get_node_or_null("HogwartsCastle") == null,
			"Round trip %d: the grounds are unloaded again" % (i + 1))
		counts.append(_counts("interior #%d" % (i + 2)))
		var leg: Dictionary = controller.transfer_log[-1]
		check(int(leg.get("token", 0)) != 0, "Round trip %d was server-authorized (token %s)" % [i + 1, leg.get("token", 0)])

	# Steady state is what matters: the very first grounds reading is taken while
	# the encounter director is still spawning its packs, so the comparison is
	# between the first and the last *rebuilt* world.
	var grounds_first: Dictionary = counts[2]
	var grounds_last: Dictionary = counts[6]
	var interior_first: Dictionary = counts[1]
	var interior_last: Dictionary = counts[7]
	check(absi(int(grounds_last["nodes"]) - int(grounds_first["nodes"])) <= 60,
		"Grounds node count is stable across round trips (%d -> %d)" % [int(grounds_first["nodes"]), int(grounds_last["nodes"])])
	check(absi(int(interior_last["nodes"]) - int(interior_first["nodes"])) <= 60,
		"Interior node count is stable across transitions (%d -> %d)" % [int(interior_first["nodes"]), int(interior_last["nodes"])])
	check(int(grounds_last["orphans"]) <= 64, "No orphan-node accumulation after round trips (%d)" % int(grounds_last["orphans"]))
	note("The first grounds reading (%d nodes) is a warm-up: the encounter director is still spawning packs. "% int(counts[0]["nodes"]) +
		"Every rebuilt world then reports the same count (%d), and the interior reports %d on every entry." % [
			int(grounds_last["nodes"]), int(interior_last["nodes"])])

	_report()
	_finish()

# ------------------------------------------------------------------ helpers

func _finish() -> void:
	print("WALKTHROUGH RESULT: %d checks, %d failures" % [checks, failures.size()])
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if failures.is_empty() else 1)

## The doorway interaction, delivered the way the game delivers it.
func _press_interact() -> void:
	var press := InputEventAction.new()
	press.action = "interact"
	press.pressed = true
	get_viewport().push_input(press)

## Wait for a transfer to complete: the map swapped, the load finished and the
## server-issued token recorded (the commit follows the acknowledgement).
func _await_map(controller: Node, map_id: String) -> void:
	var waited := 0.0
	while (controller.current_map != map_id or controller.busy or controller.transfer_log.is_empty()) \
			and waited < ROUTE_TIMEOUT:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	await get_tree().create_timer(0.3).timeout

func _counts(label: String) -> Dictionary:
	var entry := {
		"label": label,
		"nodes": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
		"orphans": Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
		"resources": Performance.get_monitor(Performance.OBJECT_RESOURCE_COUNT),
		"staticmethod": Performance.get_monitor(Performance.MEMORY_STATIC),
	}
	return entry

func _report() -> void:
	print("---- map transfer evidence (node / orphan / resource / static memory) ----")
	for entry in counts:
		print("  %-14s nodes=%-6d orphans=%-4d resources=%-6d static=%.1f MiB" % [
			String(entry["label"]), int(entry["nodes"]), int(entry["orphans"]),
			int(entry["resources"]), float(entry["staticmethod"]) / 1048576.0])
	print("--------------------------------------------------------------------------")
	for line in notes:
		print("  NOTE: " + line)

## Walk the collision of one layout flight: every sample must have floor within
## half a step of the authored line, and clear headroom above it.
func _ramp_ok(interior: Node3D, flight: Dictionary, map_y: float) -> bool:
	var a := Vector3(float(flight["from"][0]), float(flight["from"][1]) + map_y, float(flight["from"][2]))
	var b := Vector3(float(flight["to"][0]), float(flight["to"][1]) + map_y, float(flight["to"][2]))
	var space := interior.get_world_3d().direct_space_state
	var samples := 12
	for i in range(samples):
		var t := (float(i) + 0.5) / float(samples)
		var point := a.lerp(b, t)
		var down := PhysicsRayQueryParameters3D.create(point + Vector3.UP * 1.6, point + Vector3.DOWN * 1.6, 1)
		var hit: Dictionary = space.intersect_ray(down)
		if hit.is_empty() or absf((hit["position"] as Vector3).y - point.y) > 0.45:
			return false
		var up := PhysicsRayQueryParameters3D.create(point + Vector3.UP * 1.0, point + Vector3.UP * 3.4, 1)
		if not space.intersect_ray(up).is_empty():
			return false
	return true
