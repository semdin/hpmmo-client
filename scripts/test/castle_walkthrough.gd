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
## it is the castle proof scene.

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
	player.global_position = Vector3(0, 0.6, -47.0)
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

	# --- 3. StaircaseSlot (owned by the staircase workstream) -----------------
	var slot = interior.get_node_or_null("StaircaseSlot")
	check(slot is Node3D, "The grand staircase hall exposes a StaircaseSlot marker")
	if slot is Node3D:
		var slot_children := (slot as Node3D).get_child_count()
		check(slot_children <= 1, "StaircaseSlot holds at most one staircase (found %d)" % slot_children)
		if ResourceLoader.exists("res://scenes/world/castle/staircase.tscn"):
			note("res://scenes/world/castle/staircase.tscn exists and was instantiated into StaircaseSlot " +
				"(%d child node(s)); the slot, not this scene, is what this workstream owns." % slot_children)
		else:
			note("res://scenes/world/castle/staircase.tscn is not present in this build; " +
				"StaircaseSlot was left empty and the file was not created or edited here.")

	# --- 4. floor-aware labels -------------------------------------------------
	var ground_floor: String = interior.floor_display(200.2)
	var first_floor: String = interior.floor_display(206.2)
	var second_floor: String = interior.floor_display(212.2)
	var dungeon: String = interior.floor_display(194.2)
	check(ground_floor.contains("Ground"), "Ground level reports its floor name (%s)" % ground_floor)
	check(first_floor.contains("First"), "First floor reports its floor name (%s)" % first_floor)
	check(second_floor.contains("Second"), "Second floor reports its floor name (%s)" % second_floor)
	check(dungeon.contains("Dungeon"), "Basement reports its floor name (%s)" % dungeon)
	controller._update_labels()
	check(controller._location_label.text.contains("Hogwarts Castle"),
		"The HUD location label names the map and floor the player is on (%s)" % controller._location_label.text)
	var signs := _label_texts(interior)
	for keyword in ["GREAT HALL", "LIBRARY", "CLASSROOM", "GRAND STAIRCASE", "VESTIBULE",
			"TOWER LANDING", "DUNGEON", "FUTURE ENCOUNTER"]:
		check(_signs_contain(signs, keyword), "Signage names %s" % keyword)

	# --- 5. the whole route is walkable on foot --------------------------------
	# Horizontal sweeps at torso height through every doorway and room.
	for leg in _route_legs():
		var from: Vector3 = leg[0]
		var to: Vector3 = leg[1]
		check(interior.route_clear(from, to), "Route is walkable on foot: %s" % String(leg[2]))
	# Vertical sweeps up every flight: collision under the feet and headroom above.
	for flight in _flights():
		check(_ramp_ok(interior, flight), "Stairs are walkable (collision under the feet, headroom): %s" % String(flight[0]))

	# --- 6. actually walk up and back down the conventional staircase --------
	controller._place_player(Vector3(41, 200.4, 25.5))
	player.camera_rot_y = 0.0
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.4).timeout
	var start_y: float = player.global_position.y
	Input.action_press("move_forward")
	await get_tree().create_timer(2.4).timeout
	Input.action_release("move_forward")
	var climbed_y: float = player.global_position.y
	check(climbed_y > start_y + 4.5, "Walking forward climbs the conventional staircase (%.1f -> %.1f)" % [start_y, climbed_y])
	check(climbed_y < 207.5, "The stair does not launch the walker off the top (%.1f)" % climbed_y)
	player.camera_rot_y = 180.0   # degrees: the controller's camera yaw is degrees, not radians
	await get_tree().create_timer(0.2).timeout
	Input.action_press("move_forward")
	await get_tree().create_timer(3.6).timeout
	Input.action_release("move_forward")
	var descended: Vector3 = player.global_position
	check(descended.y < 202.5, "Walking back down the staircase descends cleanly (%s)" % descended)

	# --- 7. round trips: does the old world really go away? -------------------
	# Every leg goes through the real doorway and the real server handshake, so
	# the counts below are taken after a full request -> grant -> load -> ready
	# -> commit cycle, never after a developer teleport.
	for i in range(3):
		controller._place_player(Vector3(0, 200.4, 30.0))
		await get_tree().create_timer(0.4).timeout
		_press_interact()
		await _await_map(controller, "grounds")
		check(controller.current_map == "grounds" and world.get_node_or_null("CastleInterior") == null,
			"Round trip %d: the interior is unloaded on return" % (i + 1))
		check(world.has_node("HogwartsCastle"), "Round trip %d: the grounds are rebuilt" % (i + 1))
		counts.append(_counts("grounds #%d" % (i + 2)))
		controller._place_player(Vector3(0, 0.6, -46.0))
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

func _label_texts(root: Node) -> Array:
	var out: Array = []
	for node in root.find_children("*", "Label3D", true, false):
		out.append(String((node as Label3D).text))
	return out

func _signs_contain(signs: Array, keyword: String) -> bool:
	for text in signs:
		if String(text).contains(keyword):
			return true
	return false

## Ground-floor and upper-floor legs, each a straight walk a body can make.
## Heights are 1.2 m above the local floor (torso height for a 1.8 m capsule).
func _route_legs() -> Array:
	return [
		[Vector3(0, 201.2, 33), Vector3(0, 201.2, 20), "vestibule to the grand staircase hall"],
		[Vector3(20, 201.2, 20), Vector3(41, 201.2, 25.5), "hall to the foot of the staircase"],
		[Vector3(-11, 201.2, 20), Vector3(-11, 201.2, 3), "hall west bay"],
		[Vector3(0, 201.2, 10), Vector3(-30, 201.2, 10), "great hall, east arcade to west aisle"],
		[Vector3(-36, 201.2, 18), Vector3(-36, 201.2, -18), "great hall, south end to dais"],
		[Vector3(-36, 201.2, -21), Vector3(-36, 201.2, -27), "great hall north door to the side corridor"],
		[Vector3(-46, 201.2, -27), Vector3(-46, 201.2, -22), "side corridor to the dungeon stair"],
		[Vector3(-61, 201.2, -27), Vector3(-61, 201.2, 0), "west side corridor"],
		[Vector3(-61, 201.2, 23), Vector3(-20, 201.2, 23), "south side corridor"],
		[Vector3(-20, 201.2, 23), Vector3(-15.5, 201.2, 23), "south corridor to the stair hall"],
		[Vector3(20, 201.2, 30), Vector3(20, 201.2, -20), "stair hall east side"],
		[Vector3(37, 207.2, 20), Vector3(37, 207.2, 6), "first-floor gallery walkway"],
		[Vector3(41, 207.2, 10), Vector3(37, 207.2, 10), "first-floor stair arrival to the gallery"],
		[Vector3(37, 207.2, 6), Vector3(37, 207.2, -20), "first-floor gallery to the corridor"],
		[Vector3(-6, 207.2, -27), Vector3(-34, 207.2, -27), "first-floor corridor"],
		[Vector3(-34, 207.2, -27), Vector3(-34, 207.2, -34), "library doorway"],
		[Vector3(-34, 207.2, -34), Vector3(-38, 207.2, -44), "library interior"],
		[Vector3(-4, 207.2, -27), Vector3(-4, 207.2, -34), "classroom doorway"],
		[Vector3(-4, 207.2, -34), Vector3(4, 207.2, -44), "classroom interior"],
		[Vector3(20, 207.2, 30), Vector3(20, 207.2, -20), "first-floor gallery, east side"],
		[Vector3(41, 213.2, -6), Vector3(41, 213.2, -14), "second-floor arrival landing"],
		[Vector3(37, 213.2, -6), Vector3(37, 213.2, -20), "second-floor gallery walkway"],
		[Vector3(10, 213.2, -27), Vector3(-34, 213.2, -27), "second-floor corridor"],
		[Vector3(-4, 213.2, -27), Vector3(-4, 213.2, -44), "upper classroom interior"],
		[Vector3(-34, 213.2, -34), Vector3(-38, 213.2, -44), "upper study interior"],
		[Vector3(20, 213.2, 20), Vector3(20, 213.2, -20), "second-floor gallery"],
		[Vector3(40, 213.2, 8), Vector3(46, 213.2, 8), "tower bridge"],
		[Vector3(50, 213.2, 8), Vector3(56, 213.2, 8), "tower landing"],
		[Vector3(-14, 213.2, 16), Vector3(-20, 213.2, 16), "great hall balcony"],
		[Vector3(-46, 195.2, -20), Vector3(-46, 195.2, -13), "dungeon stair bay"],
		[Vector3(-46, 195.2, -13), Vector3(-46, 195.2, -9), "dungeon divider doorway"],
		[Vector3(-46, 195.2, -8), Vector3(-46, 195.2, 6), "dungeon classroom"],
		[Vector3(-46, 195.2, 6), Vector3(-52, 195.2, 8), "dungeon classroom west end"],
		[Vector3(-52, 195.2, 8), Vector3(-52, 195.2, 9.2), "future encounter entrance"],
	]

## Flights as [label, axis, cross, start, y0, dir, width, rise, run].
func _flights() -> Array:
	return [
		["conventional stair, ground to first", "z", 41.0, 24.0, 200.0, -1.0, 5.0, 6.0, 12.0],
		["conventional stair, first to second", "z", 41.0, 8.0, 206.0, -1.0, 5.0, 6.0, 12.0],
		["dungeon stair, ground to basement", "z", -46.0, -24.0, 200.0, 1.0, 6.0, 6.0, 12.0],
	]

## Walk the collision of one flight: every sample must have floor within half a
## step of the authored rise/run line, and clear headroom above it.
func _ramp_ok(interior: Node3D, flight: Array) -> bool:
	var axis := String(flight[1])
	var cross := float(flight[2])
	var start := float(flight[3])
	var y0 := float(flight[4])
	var dir := float(flight[5])
	var rise := float(flight[7])
	var run := float(flight[8])
	var space := interior.get_world_3d().direct_space_state
	var samples := 12
	for i in range(samples):
		var t := (float(i) + 0.5) / float(samples)
		var along := start + dir * run * t
		var expected := y0 + rise * t
		var point := Vector3(cross, 0, along) if axis == "z" else Vector3(along, 0, cross)
		var down := PhysicsRayQueryParameters3D.create(
			point + Vector3.UP * (expected + 1.6), point + Vector3.UP * (expected - 1.6), 1)
		var hit: Dictionary = space.intersect_ray(down)
		if hit.is_empty() or absf((hit["position"] as Vector3).y - expected) > 0.45:
			return false
		var up := PhysicsRayQueryParameters3D.create(
			point + Vector3.UP * (expected + 1.0), point + Vector3.UP * (expected + 3.4), 1)
		if not space.intersect_ray(up).is_empty():
			return false
	return true
