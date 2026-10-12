extends Node

## Approach-flight probe: fly the REAL mounted player along the castle approach
## (x = 0, from the courtyard side toward the great doors at z = 5) at fixed
## heights above the ground, sampling every step. The castle is a shell entered
## on foot through the door portal, so a low line must reach the doors' porch
## and a high line must reach the facade - neither may stall on an invisible
## blocker in open air. A stall is reported as a measurement: where the body
## stopped, how fast it was going, and what the forward rays hit.
##
## Headless-safe: real world scene, real collision, real mounted movement rules.
##
## Run:
##   godot --headless --path client res://scenes/test/castle_approach_flight.tscn \
##     --fixed-fps 60 --quit-after 7200

## Start of the approach line (x, z) and the porch line a low flight must reach.
const START := Vector3(0.0, 0.0, 18.0)
const FINISH_Z := 9.0
## Facade of the entrance hall (world z) - the great doors stand against it.
const FACADE_Z := 5.0
const FLY_SECONDS := 7.0
const SAMPLE_EVERY := 0.1
const HOLD_BAND := 0.35

## One line of travel per run. The low run starts on the pad and lets the real
## take-off settle (the owner's profile: the hover band coasts the rider to
## ~1.7 m); the others hold a commanded altitude.
## start_y is metres above the approach ground (negative: real take-off).
const RUNS := [
	{"label": "takeoff-hover", "start_y": -1.0},
	{"label": "5m", "start_y": 5.0},
	{"label": "20m", "start_y": 20.0},
]

## Ground height on the approach (the terrain the castle threshold is flush with).
var base_y := 0.0

var checks := 0
var failures: Array[String] = []

@onready var world = $GameWorld

func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)

func _ready() -> void:
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false
	await get_tree().create_timer(0.6).timeout
	var player = world.local_player
	check(player != null, "World scene hosts a local player")
	if player == null:
		_finish()
		return
	base_y = GroundsTerrain.height_at(START.x, START.z)

	for run in RUNS:
		await _fly_line(player, run)
	await _wall_run(player)
	_scan_corridor(player)

	_finish()

## Is the collision surface on the approach the ground the player sees (the
## terrain, or the stone apron flush with it), and is the corridor clear at
## hover height?
func _scan_corridor(player) -> void:
	var space: PhysicsDirectSpaceState3D = player.get_world_3d().direct_space_state
	var worst_floor := 0.0
	var floor_rows: Array = []
	var blocked: Array = []
	# (off the 1 m vertex grid: a ray exactly through a heightfield vertex can slip
	# between its triangles in the physics engine)
	for x in [-3.93, -1.93, 0.07, 2.07, 3.93]:
		for z in [16.07, 13.07, 11.07, 9.57]:
			var ground := GroundsTerrain.height_at(x, z)
			var query := PhysicsRayQueryParameters3D.create(
				Vector3(x, ground + 12.0, z), Vector3(x, ground - 2.0, z), 1)
			var hit: Dictionary = space.intersect_ray(query)
			var dy := 999.0 if hit.is_empty() else float((hit["position"] as Vector3).y) - ground
			floor_rows.append("(%.0f,%.0f)->%+.2f" % [x, z, dy])
			if absf(dy) > absf(worst_floor):
				worst_floor = dy
			var fwd := PhysicsRayQueryParameters3D.create(
				Vector3(x, ground + 1.7, z), Vector3(x, ground + 1.7, z - 1.5), 1)
			var fhit: Dictionary = space.intersect_ray(fwd)
			if not fhit.is_empty() and float((fhit["position"] as Vector3).z) > FINISH_Z:
				blocked.append("(%.0f,%.0f)" % [x, z])
	print("FLIGHT corridor floors: %s" % " ".join(floor_rows))
	check(absf(worst_floor) <= 0.35,
		"the approach collision surface is the ground the player sees (worst %.2f m off the terrain)" % absf(worst_floor))
	check(blocked.is_empty(),
		"the approach corridor at hover height is clear of invisible blockers (%s)" % str(blocked))

## The reported "stuck" state, reproduced directly: hover into the castle's
## front wall beside the door, hold forward, then prove the rider can leave -
## back away and climb. A body that cannot do either is genuinely trapped.
func _wall_run(player) -> void:
	print("FLIGHT wall: hover into the front wall at x=8, then retreat and climb")
	if player.is_mounted:
		player._apply_mount_state(false)
	player.velocity = Vector3.ZERO
	player.camera_rot_y = 0.0
	player.global_position = Vector3(8.0, base_y + 0.6, START.z)
	await get_tree().create_timer(0.35).timeout
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	if not player.is_mounted:
		player.toggle_broom_mount()
	player.velocity = Vector3.ZERO
	player.global_position = Vector3(8.0, base_y + 1.7, START.z)
	player.camera_rot_y = 0.0
	await get_tree().create_timer(0.25).timeout

	# 1. Push into the wall for 4 s, sampling the raw state each step.
	Input.action_press("move_forward")
	var push: Array = []
	var next := 0.0
	var t := 0.0
	while t < 4.0:
		await get_tree().physics_frame
		t += 1.0 / 60.0
		if t >= next:
			next = t + 0.2
			push.append(_sample_line(player, t))
	Input.action_release("move_forward")
	var wall_z: float = player.global_position.z
	for sample in push:
		print("  FLIGHT-TICK wall-push %s" % JSON.stringify(sample))
	check(wall_z > FACADE_Z and wall_z < FACADE_Z + 2.5,
		"wall-push: the rider is stopped by the castle front wall (z=%.2f)" % wall_z)

	# 2. Retreat: a trapped body cannot back away from the wall.
	var before: Vector3 = player.global_position
	Input.action_press("move_backward")
	t = 0.0
	while t < 1.6:
		await get_tree().physics_frame
		t += 1.0 / 60.0
	Input.action_release("move_backward")
	var retreated: float = player.global_position.z - before.z
	check(retreated >= 2.0, "wall-push: the rider can back away from the wall (%.2f m)" % retreated)

	# 3. Climb: a trapped body cannot climb out either.
	var y_before: float = player.global_position.y
	Input.action_press("jump")
	t = 0.0
	while t < 1.6:
		await get_tree().physics_frame
		t += 1.0 / 60.0
	Input.action_release("jump")
	var climbed: float = player.global_position.y - y_before
	check(climbed >= 2.5, "wall-push: the rider can climb away from the wall (%.2f m)" % climbed)

func _sample_line(player, t: float) -> Dictionary:
	var pos: Vector3 = player.global_position
	return {
		"t": snappedf(t, 0.01),
		"pos": [snappedf(pos.x, 0.01), snappedf(pos.y, 0.01), snappedf(pos.z, 0.01)],
		"speed": snappedf(Vector2(player.velocity.x, player.velocity.z).length(), 0.01),
		"collisions": _collision_names(player),
	}

func _fly_line(player, run: Dictionary) -> void:
	var label := String(run["label"])
	# Reset: on foot on the pad centre, facing the castle (the approach line).
	if player.is_mounted:
		player._apply_mount_state(false)
	player.velocity = Vector3.ZERO
	player.camera_rot_y = 0.0
	player.global_position = Vector3(START.x, base_y + 0.6, START.z)
	await get_tree().create_timer(0.35).timeout
	# Mount through the real path (a direct `is_mounted = true` is overwritten by
	# the next authoritative stats push, which is why it cannot drive a flight).
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	if not player.is_mounted:
		player.toggle_broom_mount()
	await get_tree().physics_frame
	check(player.is_mounted, "%s: the rider is mounted%s" % [label,
		"" if player.is_mounted else " (%s)" % player.mount_block_reason()])

	player.velocity = Vector3.ZERO
	if float(run["start_y"]) >= 0.0:
		player.global_position = Vector3(START.x, base_y + float(run["start_y"]), START.z)
	else:
		player.velocity.y = 3.0   # the real take-off impulse
	await get_tree().create_timer(0.3).timeout

	Input.action_press("move_forward")
	var t := 0.0
	var next_sample := 0.0
	var samples: Array = []
	var reach_y := float(run["start_y"])
	var hold_y := base_y + reach_y
	var stalled := false
	var passed := false
	while t < FLY_SECONDS:
		await get_tree().physics_frame
		t += 1.0 / 60.0   # --fixed-fps 60 makes this the real step
		var pos: Vector3 = player.global_position
		if reach_y >= 0.0:
			# Hold the commanded altitude with the real rise/descend inputs.
			Input.action_release("jump")
			Input.action_release("flight_descend")
			if pos.y < hold_y - HOLD_BAND:
				Input.action_press("jump")
			elif pos.y > hold_y + HOLD_BAND:
				Input.action_press("flight_descend")
		if t >= next_sample:
			next_sample = t + SAMPLE_EVERY
			samples.append({
				"t": snappedf(t, 0.01),
				"pos": [snappedf(pos.x, 0.01), snappedf(pos.y, 0.01), snappedf(pos.z, 0.01)],
				"speed": snappedf(Vector2(player.velocity.x, player.velocity.z).length(), 0.01),
				"collisions": _collision_names(player),
			})
		if pos.z <= FINISH_Z:
			passed = true
			break
	Input.action_release("move_forward")
	Input.action_release("jump")
	Input.action_release("flight_descend")
	var final_pos: Vector3 = player.global_position
	var slow: Array = []
	for sample in samples:
		if float(sample["speed"]) < 1.0:
			slow.append(sample)
	if not passed:
		stalled = slow.size() >= 3

	var forward := _ray_hits(player, Vector3(0, 0, -1))
	var summary := "FLIGHT %s: %s, final=(%.1f, %.1f, %.1f) over %.1fs, %d slow samples%s" % [
		label, "PASSED" if passed else ("STALLED" if stalled else "STOPPED"),
		final_pos.x, final_pos.y, final_pos.z, t, slow.size(),
		("" if forward == "" else ", ahead: " + forward)]
	print(summary)
	for sample in samples:
		print("  FLIGHT-TICK %s %s" % [label, JSON.stringify(sample)])

	# What "passed" means per line: the porch in front of the doors is 6 m wide
	# and 9 m high, so the low lines must fly into it (FINISH_Z). The 20 m line
	# meets the facade above the porch - as geometry, not a movement-rule stall;
	# it must still reach the wall instead of hanging in open air.
	if label == "20m":
		check(final_pos.z <= FACADE_Z + 4.0 or passed,
			"%s: the rider advances to the facade, not an invisible blocker (%s)" % [label, summary])
	else:
		check(passed, "%s: the rider flies into the castle porch (%s)" % [label, summary])

## Colliders this body touched in the last physics step (empty when free). The
## body's own name is generic ("Body"), so its named parent is reported too.
func _collision_names(player) -> Array:
	var out: Array = []
	for i in range(player.get_slide_collision_count()):
		var collision = player.get_slide_collision(i)
		var collider = collision.get_collider()
		if collider is Node:
			var body := collider as Node
			var parent := body.get_parent()
			var name := String(parent.name) if parent is Node else String(body.name)
			if name.begins_with("@"):
				name = String(body.name)
			out.append(name)
	return out

## What a forward ray from the body at three heights hits, as "name@(x,y,z)".
func _ray_hits(player, dir: Vector3) -> String:
	var out: Array = []
	for dy in [-0.6, 0.2, 1.0]:
		var from: Vector3 = player.global_position + Vector3(0, dy, 0)
		var query := PhysicsRayQueryParameters3D.create(from, from + dir * 12.0, 1)
		var exclude: Array[RID] = [player.get_rid()]
		query.exclude = exclude
		var hit: Dictionary = player.get_world_3d().direct_space_state.intersect_ray(query)
		if hit.is_empty():
			out.append("clear@%.1f" % dy)
		else:
			var collider = hit.get("collider")
			var name := String((collider as Node).name) if collider is Node else "?"
			out.append("%s@y%+.1f at z=%.1f" % [name, dy, float((hit["position"] as Vector3).z)])
	return "; ".join(out)

func _finish() -> void:
	print("FLIGHT RESULT: %d checks, %d failures" % [checks, failures.size()])
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if failures.is_empty() else 1)
