extends Node3D
## Slope regressions on a heightmap like the grounds terrain:
##   godot --headless --path client res://scenes/test/slope_regression.tscn
## A walkable slope must be climbed without ever entering the air/fall states
## (the "jumping in place" jitter), standing on it must not move, a too-steep
## bank must not be climbable (the old step-up hopped up it, fell and slid back)
## and resting on one must slide down smoothly.
var player: CharacterBody3D
var graph
var checks := 0
var failures := 0
var results := {}

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok:
		failures += 1
	print("%s: %s" % ["PASS" if ok else "FAIL", message])

func _height(x: float, z: float) -> float:
	# z in [0, 60]: flat until 10, then 35 deg ramp with bumps, plateau, 62 deg bank at x>20
	var h := 0.0
	var t := clampf(z - 10.0, 0.0, 30.0)
	h = t * tan(deg_to_rad(33.0)) + sin(z * 2.1) * 0.06 + sin(x * 1.7 + z * 0.9) * 0.05
	if x > 20.0:
		var u := clampf(z - 10.0, 0.0, 12.0)
		h = u * tan(deg_to_rad(62.0))
	return h

func _ready() -> void:
	QuestManager.persistence_enabled = false
	var body := StaticBody3D.new()
	var cs := CollisionShape3D.new()
	var hm := HeightMapShape3D.new()
	var w := 81
	hm.map_width = w
	hm.map_depth = w
	var data := PackedFloat32Array()
	data.resize(w * w)
	for zi in range(w):
		for xi in range(w):
			data[zi * w + xi] = _height(float(xi) - 0.0, float(zi))
	hm.map_data = data
	cs.shape = hm
	body.add_child(cs)
	body.position = Vector3(40, 0, 40)  # heightmap centred: x,z in [0,80]
	add_child(body)
	player = preload("res://scenes/entities/player/player.tscn").instantiate()
	player.is_local_player = false
	player.sim_server_controlled = true
	add_child(player)
	graph = player.hero_anim
	await _case("walk up 33deg", Vector3(5, _height(5, 4) + 0.2, 4), Vector2(0, 1), 3.5, 180.0)
	await _case("stand on 33deg", Vector3(5, _height(5, 25) + 0.3, 25), Vector2.ZERO, 3.0, 0.0)
	await _case("walk down 33deg", Vector3(5, _height(5, 38) + 0.3, 38), Vector2(0, 1), 3.0, 0.0)
	await _case("walk into 62deg bank", Vector3(30, 0.3, 6), Vector2(0, 1), 4.0, 180.0)
	await _case("stand on 62deg bank", Vector3(30, _height(30, 15) + 0.4, 15), Vector2.ZERO, 3.0, 0.0)
	var up: Dictionary = results["walk up 33deg"]
	check(up.air == 0, "Walking up a 33 degree slope never enters the air states (%d frames)" % up.air)
	check(up.rise > 8.0, "The body actually climbs the walkable slope (%.1f m)" % up.rise)
	var stand: Dictionary = results["stand on 33deg"]
	check(stand.moved < 0.02 and stand.air == 0, "Standing on a walkable slope does not move or flicker (%.3f m)" % stand.moved)
	var down: Dictionary = results["walk down 33deg"]
	check(down.air == 0, "Running down a walkable slope stays grounded (%d air frames)" % down.air)
	var bank: Dictionary = results["walk into 62deg bank"]
	check(bank.maxrise < 0.3, "A 62 degree bank cannot be climbed (max rise %.2f m)" % bank.maxrise)
	var slide: Dictionary = results["stand on 62deg bank"]
	check(slide.rise < -4.0, "A body on a too-steep bank slides down it (%.1f m)" % slide.rise)
	check(slide.flips <= 2, "The slide does not flicker between ground and air (%d flips)" % slide.flips)
	print("SLOPE RESULT: %d checks, %d failures" % [checks, failures])
	get_tree().quit(1 if failures > 0 else 0)

func _case(name: String, at: Vector3, move: Vector2, seconds: float, yaw: float) -> void:
	player.global_position = at
	player.velocity = Vector3.ZERO
	player.sim_input = {}
	await get_tree().create_timer(0.6).timeout
	player.sim_input = {"move": Vector2(0, -1) if move.y > 0 else (Vector2(0, 1) if move.y < 0 else Vector2.ZERO), "yaw": yaw}
	var frames := 0
	var air_frames := 0
	var flips := 0
	var prev_air := false
	var lands := 0
	var ys: Array[float] = []
	var start := player.global_position
	var max_y := -999.0
	var t := 0.0
	while t < seconds:
		await get_tree().physics_frame
		t += 1.0 / 60.0
		frames += 1
		var air: bool = String(graph.current_state).begins_with("air")
		if air: air_frames += 1
		if air != prev_air: flips += 1
		prev_air = air
		if graph.has_oneshot() and String(graph.get("_oneshot_clip") if "_oneshot_clip" in graph else "") == "Land":
			lands += 1
		ys.append(player.global_position.y)
		max_y = maxf(max_y, player.global_position.y)
	# vertical jitter: count sign changes of dy beyond 2mm
	var sign_changes := 0
	var prev_sign := 0
	for i in range(1, ys.size()):
		var dy := ys[i] - ys[i - 1]
		var sg := 0 if absf(dy) < 0.002 else (1 if dy > 0 else -1)
		if sg != 0 and prev_sign != 0 and sg != prev_sign: sign_changes += 1
		if sg != 0: prev_sign = sg
	print("  %-22s frames=%d air=%d flips=%d dy_reversals=%d moved=%.2f rise=%.2f maxrise=%.2f" % [name, frames, air_frames, flips, sign_changes, player.global_position.distance_to(start), player.global_position.y - start.y, max_y - start.y])
	results[name] = {"air": air_frames, "flips": flips, "moved": player.global_position.distance_to(start), "rise": player.global_position.y - start.y, "maxrise": max_y - start.y}
