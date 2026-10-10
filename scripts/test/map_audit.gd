extends Node

## Map audit harness (evidence for the open-world repair pass).
##
## Runs the REAL game world and:
##   1. ray-probes the walkable surface at every reported spot and compares it
##      with the visual ground height (`OutdoorTerrain.ground_y`) - a mismatch
##      is exactly "there is elevation but we cannot get up there";
##   2. walks the player at the broken spots (terrace stair, village road, lake
##      shore) and measures the height actually gained / the surface landed on;
##   3. shoots the reported views (forest, lake, Hogsmeade gate and layout,
##      terrace stairs) plus the castle interior, when a renderer is present.
##
##   godot --path client res://scenes/test/map_audit.tscn
##   godot --headless --path client res://scenes/test/map_audit.tscn   (probes only)

const OUT_DIR := "res://tools/downloads"
const OutdoorTerrain = preload("res://scripts/world/outdoor_terrain.gd")

@onready var world = $GameWorld

var _camera: Camera3D
var _failures := 0

const PROBES := [
	# [label, x, z] - one ray down, mask 1 (terrain), from +60 to -40.
	["forest floor", -140.0, -100.0],
	["spider hollow", -180.0, -140.0],
	["lake centre", -220.0, 185.0],
	["lake north shore", -220.0, 118.0],
	["boathouse dock", -162.0, 148.0],
	["hagrid hollow", -118.0, 102.0],
	["west gate plaza", 36.0, 20.0],
	["lower town street", 75.0, 30.0],
	["tavern square", 88.0, 45.0],
	["terrace stair foot", 118.0, 34.0],
	["terrace stair mid", 125.0, 33.0],
	["terrace stair top", 132.0, 32.0],
	["upper terrace", 160.0, 35.0],
	["upper street", 165.0, 60.0],
	["highlands road", 230.0, 30.0],
	["quidditch pitch", 280.0, 20.0],
	["castle approach", 0.0, -45.0],
]

func _ready() -> void:
	await get_tree().create_timer(1.4).timeout
	var renderer := RenderingServer.get_video_adapter_name() != ""
	print("MAP AUDIT: renderer=%s quality=%s" % [
		renderer, load("res://scripts/world/quality_preset.gd").current()])
	_probe_surfaces()
	await _walk_terrace_stair()
	await _walk_lake_shore()
	# Outdoor shots first: entering the interior unloads the outdoor scenery.
	if renderer:
		await _shoot_views()
	await _check_interior(renderer)
	print("MAP AUDIT RESULT: %d failures" % _failures)
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if _failures == 0 else 1)

func check(ok: bool, message: String) -> void:
	if not ok:
		_failures += 1
	print(("PASS: " if ok else "FAIL: ") + message)

## ---------------------------------------------------------------- probes

func _probe_surfaces() -> void:
	var space: PhysicsDirectSpaceState3D = world.get_world_3d().direct_space_state
	for entry in PROBES:
		var label := String(entry[0])
		var x := float(entry[1])
		var z := float(entry[2])
		var query := PhysicsRayQueryParameters3D.create(Vector3(x, 60.0, z), Vector3(x, -40.0, z), 1)
		var hit: Dictionary = space.intersect_ray(query)
		var visual: float = OutdoorTerrain.ground_y(x, z)
		var walkable := float(hit.get("position", Vector3(0, -999, 0)).y)
		var delta := visual - walkable
		print("MAP AUDIT probe %-20s visual=%7.2f collider=%7.2f delta=%6.2f %s" % [
			label, visual, walkable, delta, "(air: no collider)" if hit.is_empty() else ""])

## ---------------------------------------------------------------- walking

## The terrace link from the lower town (0 m) to the upper plateau (5 m). The
## report is "there is elevation but we cannot get up there", so this walks it
## with the real controller and measures the gain.
func _walk_terrace_stair() -> void:
	var player = world.local_player
	player.global_position = Vector3(114.0, 0.6, 34.0)
	player.velocity = Vector3.ZERO
	# Face the flight: +x is camera yaw -90.
	player.camera_rot_y = -90.0
	await get_tree().physics_frame
	var start_y: float = player.global_position.y
	for i in range(240):
		Input.action_press("move_forward")
		await get_tree().physics_frame
	Input.action_release("move_forward")
	await get_tree().physics_frame
	var end: Vector3 = player.global_position
	var gained: float = end.y - start_y
	print("MAP AUDIT terrace walk: start_y=%.2f end=(%.1f, %.2f, %.1f) gained=%.2f" % [
		start_y, end.x, end.y, end.z, gained])
	check(gained > 4.0, "walking the terrace stair climbs to the upper plateau (gained %.2f m)" % gained)
	check(end.y < 6.0, "the terrace stair does not launch the walker off the top (%.2f m)" % end.y)

## The lake report: "there is a pitch-black thing and you fall through the
## moment you cross it". Walk into the water from the north shore and see what
## surface catches the body.
func _walk_lake_shore() -> void:
	var player = world.local_player
	player.global_position = Vector3(-220.0, -5.6, 106.0)
	player.velocity = Vector3.ZERO
	player.camera_rot_y = 180.0  # forward = +z (towards the water)
	await get_tree().physics_frame
	var start: Vector3 = player.global_position
	for i in range(420):
		Input.action_press("move_forward")
		await get_tree().physics_frame
	Input.action_release("move_forward")
	for i in range(60):
		await get_tree().physics_frame
	var end: Vector3 = player.global_position
	print("MAP AUDIT lake walk: start=(%.1f, %.2f, %.1f) end=(%.1f, %.2f, %.1f) swimming=%s" % [
		start.x, start.y, start.z, end.x, end.y, end.z, str(player.is_swimming)])
	check(end.z > 118.0, "the body can cross the waterline (z %.1f)" % end.z)
	check(end.y > -9.5, "the body stays on/at the water surface instead of sinking to the bed (y %.2f)" % end.y)

## ---------------------------------------------------------------- captures

func _setup_camera() -> void:
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	_camera = Camera3D.new()
	_camera.fov = 65.0
	world.add_child(_camera)
	_camera.current = true

func _shoot(name: String, pos: Vector3, target: Vector3) -> void:
	if _camera == null:
		_setup_camera()
	_camera.global_position = pos
	_camera.look_at(target)
	await get_tree().create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	var error := get_viewport().get_texture().get_image().save_png("%s/%s.png" % [OUT_DIR, name])
	print("MAP AUDIT shot %s: %s" % [name, error])

func _shoot_views() -> void:
	var env_node := world.get_node_or_null("WorldEnvironment")
	if env_node is WorldEnvironment:
		var env: Environment = (env_node as WorldEnvironment).environment
		print("MAP AUDIT fog: enabled=%s mode=%s density=%.5f begin=%.1f end=%.1f curve=%.2f aerial=%.2f sky=%.2f" % [
			str(env.fog_enabled), str(env.fog_mode), env.fog_density, env.fog_depth_begin,
			env.fog_depth_end, env.fog_depth_curve, env.fog_aerial_perspective, env.fog_sky_affect])
	# Camera positions ride the real ground: the terrain is shaped, so a fixed Y
	# either buries the camera (backfaces are culled: "nothing renders") or
	# floats it.
	var fg: float = OutdoorTerrain.ground_y(-120.0, -80.0)
	await _shoot("map-forest-ground", Vector3(-120, fg + 1.8, -80), Vector3(-180, fg + 2.4, -140))
	var fa: float = OutdoorTerrain.ground_y(-40.0, 40.0)
	await _shoot("map-forest-air", Vector3(-40, fa + 60.0, 40.0), Vector3(-200, 0.0, -180.0))
	var ls: float = OutdoorTerrain.ground_y(-190.0, 118.0)
	await _shoot("map-lake-shore", Vector3(-190, ls + 1.6, 118.0), Vector3(-230, -7.0, 175.0))
	await _shoot("map-lake-over", Vector3(-220, 6.0, 120.0), Vector3(-220, -7.0, 185.0))
	var gg: float = OutdoorTerrain.ground_y(30.0, 12.0)
	await _shoot("map-gate-ground", Vector3(30, gg + 1.8, 12.0), Vector3(48, gg + 0.6, 26.0))
	var va: float = OutdoorTerrain.ground_y(60.0, 95.0)
	await _shoot("map-village-air", Vector3(60, va + 55.0, 95.0), Vector3(90, 2.0, 38.0))
	var ts: float = OutdoorTerrain.ground_y(112.0, 40.0)
	await _shoot("map-terrace-stair", Vector3(112, ts + 2.4, 40.0), Vector3(132, ts + 3.4, 32.0))
	var hs: float = OutdoorTerrain.ground_y(-128.0, 126.0)
	await _shoot("map-hagrid-stair", Vector3(-128, hs + 2.0, 126.0), Vector3(-152, hs - 2.4, 143.0))

func _check_interior(render: bool) -> void:
	var controller := world.get_node_or_null("MapController")
	if controller == null:
		return
	controller._start_transfer("castle_interior", "vestibule", 0)
	var waited := 0.0
	while controller.busy and waited < 8.0:
		await get_tree().process_frame
		waited += get_process_delta_time()
	await get_tree().create_timer(0.8).timeout
	var player = world.local_player
	player.global_position = Vector3(0.0, 200.6, 30.0)
	await get_tree().physics_frame
	var stairs := _find_staircase()
	if stairs != null:
		await _check_staircase_ride(stairs, player)
	if not render:
		return
	player.global_position = Vector3(0.0, 200.6, 30.0)
	await get_tree().physics_frame
	await _shoot("map-interior-vestibule", Vector3(0, 202.0, 26.0), Vector3(0, 202.0, 10.0))
	player.global_position = Vector3(4.0, 200.6, 22.0)
	await get_tree().physics_frame
	await _shoot("map-interior-stairhall", Vector3(-4, 203.2, 30.0), Vector3(34, 203.0, 6.0))
	if stairs != null:
		var pos: Vector3 = (stairs as Node3D).global_position
		await _shoot("map-interior-staircase", pos + Vector3(16.0, 6.0, 12.0), pos + Vector3(4.0, 3.0, 5.0))
		print("MAP AUDIT staircase: state=%s entry_allowed=%s docks=%s" % [
			str(stairs.call("state_label")), str(stairs.call("entry_allowed")),
			str(stairs.call("dock_count"))])
	else:
		print("MAP AUDIT staircase: NOT PRESENT in the interior")
	# Great hall and a gallery: the "everything is missing" report.
	await _shoot("map-interior-greathall", Vector3(-46, 202.2, 18.0), Vector3(-40, 202.4, -14.0))
	await _shoot("map-interior-library", Vector3(-20, 207.6, -30.0), Vector3(-40, 208.4, -40.0))

func _find_staircase() -> Node:
	for child in world.find_children("*", "Node3D", true, false):
		if child.has_method("state_label") and child.has_method("platform_world_transform"):
			return child
	return null

## The ride: board the deck while it is docked and let the authority carry it.
## The report is "the magical staircase mechanic is broken", so this checks the
## body actually travels with the flight.
func _check_staircase_ride(stairs: Node, player: Node3D) -> void:
	var spec: Dictionary = stairs.get("spec")
	var flight: Dictionary = spec.get("flight", {})
	var run_v := float(flight.get("run", 12.0))
	# The authority collects riders only while the flight is docked, so board in
	# that state (boarding later is refused and the body is put back on a
	# landing - which is what the first version of this probe measured).
	var wait_deadline := Time.get_ticks_msec() + 30000
	while String(stairs.get("state")) != "docked" and Time.get_ticks_msec() < wait_deadline:
		await get_tree().physics_frame
	await get_tree().create_timer(0.2).timeout
	var z := run_v * 0.5
	var surface: float = stairs.call("deck_surface_y", z)
	var xform: Transform3D = stairs.call("platform_world_transform", SimAuthority.sim_tick)
	player.global_position = xform * Vector3(0.0, surface + 0.2, z)
	player.velocity = Vector3.ZERO
	await get_tree().physics_frame
	var record: Dictionary = SimAuthority.record_for(player)
	print("MAP AUDIT ride diag: authority=%s kind=%s uid=%s local=%s on_deck=%s" % [
		str(SimAuthority.is_authority()), str(record.get("kind")),
		str(record.get("uid")),
		str(stairs.call("to_deck_space", player.global_position, SimAuthority.sim_tick)),
		str(stairs.call("on_deck", player.global_position, SimAuthority.sim_tick))])
	var start: Vector3 = player.global_position
	var moved := 0.0
	var states := {}
	var deadline := Time.get_ticks_msec() + 30000
	while Time.get_ticks_msec() < deadline:
		await get_tree().physics_frame
		var state := String(stairs.get("state"))
		states[state] = true
		moved = maxf(moved, start.distance_to(player.global_position))
		if moved > 2.5 and states.has("moving"):
			break
	print("MAP AUDIT staircase ride: riders=%s states=%s travel=%.2f start=%s end=%s" % [
		str(stairs.call("rider_count")), str(states.keys()), moved,
		str(start), str(player.global_position)])
	check(moved > 2.0, "the body is carried by the moving staircase (%.2f m)" % moved)
	check(states.has("moving"), "the staircase reaches its moving state (states=%s)" % str(states.keys()))
