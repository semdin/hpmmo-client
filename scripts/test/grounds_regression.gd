extends Node

## Grounds terrain regression: the built Terrain3D data, its collision as the
## dedicated server sees it (headless => FULL_GAME), and the painted ground.
##
##   godot --headless --path . res://scenes/test/grounds_regression.tscn
##
## Expected heights come from the map design (art/map/layout.json; lake surface
## is y = 0). If a deliberate layout change moves one, update it here too.

const EXPECTED_HEIGHTS := {
	"courtyard": [Vector3(0, 0, 65), 58.0],
	"castle_door": [Vector3(0, 0, 5), 58.0],
	"hogsmeade": [Vector3(680, 0, -140), 38.0],
	"hagrid": [Vector3(-280, 0, -20), 22.0],
	"quidditch": [Vector3(330, 0, -330), 32.0],
	"highlands": [Vector3(280, 0, -760), 121.0],
	"station": [Vector3(610, 0, 260), 3.0],
}
const HEIGHT_TOLERANCE := 2.0
## Texture slots (contract with art/map/scripts/control.py and build_grounds.gd).
const COBBLE := 6
const SAND := 3
const GRAVEL := 4
const ROCK := 1

var checks := 0
var failures: Array[String] = []
var terrain: GroundsTerrain


func check(ok: bool, what: String) -> void:
	checks += 1
	if not ok:
		failures.append(what)
		print("FAIL: ", what)


func _ready() -> void:
	terrain = preload("res://scenes/world/grounds_terrain.tscn").instantiate()
	add_child(terrain)
	for i in 3:
		await get_tree().physics_frame
	_check_data()
	_check_paint()
	await _check_collision()
	await _check_walk()
	print("GROUNDS RESULT: %d checks, %d failures" % [checks, failures.size()])
	terrain.queue_free()
	await get_tree().process_frame
	get_tree().quit(1 if failures.size() > 0 else 0)


func _check_data() -> void:
	check(terrain.data != null, "terrain data loaded")
	check(terrain.data.get_region_count() == 4, "4 regions of 1024 m (got %d)" % terrain.data.get_region_count())
	check(GroundsTerrain.active() == terrain, "GroundsTerrain.active() is the loaded terrain")
	if DisplayServer.get_name() == "headless":
		check(terrain.collision.mode == Terrain3DCollision.FULL_GAME, "headless uses full collision (server simulates every body)")
	for key in EXPECTED_HEIGHTS:
		var p: Vector3 = EXPECTED_HEIGHTS[key][0]
		var want: float = EXPECTED_HEIGHTS[key][1]
		var got := GroundsTerrain.height_at(p.x, p.z)
		check(absf(got - want) <= HEIGHT_TOLERANCE, "%s at %.0f m (got %.1f)" % [key, want, got])
	var lake := GroundsTerrain.height_at(0, 330)
	check(lake < -10.0, "lake bed is deep under the y=0 surface (got %.1f)" % lake)
	# The mountain ring closes the map: every edge point is high ground.
	var low_edge := INF
	for i in 64:
		var t := -1000.0 + i * 2000.0 / 63.0
		for p in [Vector2(t, -1000), Vector2(t, 1000), Vector2(-1000, t), Vector2(1000, t)]:
			low_edge = minf(low_edge, GroundsTerrain.height_at(p.x, p.y))
	check(low_edge > 60.0, "map edge is mountains, lowest %.1f m" % low_edge)
	check(is_nan(GroundsTerrain.height_at(1500, 0)), "outside the map has no height")


func _check_paint() -> void:
	var court := terrain.data.get_texture_id(Vector3(0, 0, 65))
	check(int(court.x) == COBBLE, "courtyard is paved (base %d)" % int(court.x))
	var bed := terrain.data.get_texture_id(Vector3(0, 0, 330))
	check(int(bed.x) == GRAVEL, "lake bed is gravel (base %d)" % int(bed.x))
	# Beaches: gentle ground just above the water line is mostly sand (cliffs into
	# the lake are rock, the flat station shore is meadow).
	var rng := RandomNumberGenerator.new()
	rng.seed = 3
	var shore := 0
	var sandy := 0
	for i in 6000:
		var p := Vector3(rng.randf_range(-700, 700), 0, rng.randf_range(0, 700))
		var h := terrain.data.get_height(p)
		if h > 1.8 and h < 3.0 and terrain.data.get_normal(p).y > cos(deg_to_rad(15)):
			shore += 1
			if int(terrain.data.get_texture_id(p).x) == SAND:
				sandy += 1
	check(shore > 25 and sandy >= shore * 0.7, "beaches are sand (%d / %d)" % [sandy, shore])
	# Steep cliffs show rock: sample the promontory's flank toward the lake.
	var rock_hits := 0
	var steep := 0
	for i in 400:
		var a := TAU * i / 400.0
		var p := Vector3(cos(a) * 165.0, 0, 20 + sin(a) * 165.0)
		var n := terrain.data.get_normal(p)
		if n.y < cos(deg_to_rad(40)):
			steep += 1
			if int(terrain.data.get_texture_id(p).x) == ROCK:
				rock_hits += 1
	check(steep > 20 and rock_hits >= steep * 0.8, "steep castle cliffs are rock (%d / %d)" % [rock_hits, steep])


func _check_collision() -> void:
	await get_tree().physics_frame
	var space := get_viewport().world_3d.direct_space_state
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var missed := 0
	var worst := 0.0
	for i in 300:
		var x := rng.randf_range(-1000, 1000)
		var z := rng.randf_range(-1000, 1000)
		var q := PhysicsRayQueryParameters3D.create(Vector3(x, 400, z), Vector3(x, -100, z), 1)
		var hit := space.intersect_ray(q)
		if hit.is_empty():
			missed += 1
			continue
		worst = maxf(worst, absf(hit.position.y - GroundsTerrain.height_at(x, z)))
	check(missed == 0, "every ray hits the ground collider (%d missed)" % missed)
	check(worst < 0.25, "collider matches the rendered height (worst %.2f m)" % worst)


## A player-sized body dropped on the courtyard lands, then walks the castle
## east road downhill toward Hogsmeade without snagging or falling through.
func _check_walk() -> void:
	var body := CharacterBody3D.new()
	var shape := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.35
	cap.height = 1.75
	shape.shape = cap
	shape.position.y = 0.875
	body.add_child(shape)
	body.collision_mask = 1
	body.floor_max_angle = deg_to_rad(46)
	add_child(body)
	var start := Vector3(0, GroundsTerrain.height_at(0, 65) + 2.0, 65)
	body.global_position = start
	for i in 120:
		body.velocity.y -= 22.0 / 60.0
		body.move_and_slide()
		await get_tree().physics_frame
	var ground := GroundsTerrain.height_at(body.global_position.x, body.global_position.z)
	check(body.is_on_floor() and absf(body.global_position.y - ground) < 0.2,
		"body lands on the courtyard (%.2f above ground)" % (body.global_position.y - ground))
	# 8 s east at walking pace along the first leg of the castle_east road.
	var dir := (Vector3(95, 0, 45) - Vector3(0, 0, 65)).normalized()
	var on_floor_frames := 0
	for i in 480:
		body.velocity = Vector3(dir.x * 6.0, body.velocity.y - 22.0 / 60.0, dir.z * 6.0)
		body.move_and_slide()
		if body.is_on_floor():
			on_floor_frames += 1
			body.velocity.y = 0.0
		await get_tree().physics_frame
	var travelled := Vector2(body.global_position.x, body.global_position.z).distance_to(Vector2(0, 65))
	ground = GroundsTerrain.height_at(body.global_position.x, body.global_position.z)
	check(travelled > 35.0, "walking the east road makes progress (%.1f m)" % travelled)
	check(body.global_position.y > ground - 0.3, "body stays above the ground (%.2f)" % (body.global_position.y - ground))
	check(on_floor_frames > 400, "body stays grounded on the road (%d / 480 frames)" % on_floor_frames)
	body.queue_free()
