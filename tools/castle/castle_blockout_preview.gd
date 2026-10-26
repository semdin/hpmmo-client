extends Node3D

## Walk / fly preview of the castle interior blockout (F1), outside the game.
##
## Source: art/castle/layout.json -> art/castle/scripts/build_blockout.py (Blender)
## -> assets/castle/castle_blockout.glb. See docs/castle-interior.md.
##
## Open tools/castle/castle_blockout_preview.tscn and press F6.
##   Mouse look (click to capture, Esc to release)
##   WASD move, Space jump / up, C down (fly), Shift fast, Tab walk <-> fly,
##   1..9 / 0 jump to a room, P pause the moving staircases, F3 stats line.
## Headless-free review runs (they open a window and quit by themselves):
##   godot --path . tools/castle/castle_blockout_preview.tscn -- --shots <out_dir>
##   godot --path . tools/castle/castle_blockout_preview.tscn -- --check
##   add --grey to any of these for the F1 grey blockout instead of the Gothic build

const QualityPreset = preload("res://scripts/world/quality_preset.gd")
const Blockout = preload("res://scripts/world/castle/castle_blockout.gd")
const Decor = preload("res://scripts/world/castle/castle_decor.gd")
const CastleAtmosphere = preload("res://scripts/world/castle/castle_atmosphere.gd")
## The interior map's vertical datum: layout L0 sits at world y 200.
const MAP_Y := 200.0

const LANDMARKS := [
	["Giriş Salonu", Vector3(0, 0, 58)], ["Büyük Salon", Vector3(-30, 0, 56)],
	["Düello Kulübü", Vector3(24, 0, 44)], ["Büyük Merdiven (zemin)", Vector3(0, 0, 14)],
	["Büyük Merdiven (3. kat)", Vector3(20, 30, 10)], ["Kütüphane", Vector3(-28, 30, -15)],
	["Sınıflar (2. kat)", Vector3(30, 20, -8)], ["Zindan", Vector3(0, -10, 14)],
	["7. kat koridoru", Vector3(30, 70, -8)], ["Baykuşhane çatısı", Vector3(6, 75, -70)],
]
## [name, eye (local), look target (local)] for --shots; eye at 1.7 m.
const SHOTS := [
	["entrance_from_doors", Vector3(0, 1.7, 61), Vector3(0, 9, 20)],
	["entrance_from_balcony", Vector3(-10, 11.7, 28), Vector3(6, 0, 60)],
	["entrance_to_great_hall", Vector3(8, 1.7, 61), Vector3(-21, 4, 56)],
	["great_hall_from_door", Vector3(-23, 1.7, 56), Vector3(-105, 9, 56)],
	["hourglasses", Vector3(15.0, 2.2, 53), Vector3(16.8, 3.2, 40)],
	["staff_table", Vector3(-86, 2.4, 50), Vector3(-101, 2.0, 57)],
	["feast_house_table", Vector3(-58, 1.9, 50.0), Vector3(-63, 0.85, 47.0)],
	["feast_staff_table", Vector3(-98.2, 2.9, 53.5), Vector3(-100.6, 1.9, 56.5)],
	["banners", Vector3(-30, 3.0, 56), Vector3(-66, 15, 50)],
	["owl_lectern", Vector3(-90.5, 2.6, 58.5), Vector3(-96.2, 1.8, 56)],
	["corridor_portraits", Vector3(53, 21.7, -5), Vector3(47, 23.2, -12)],
	["dungeon_portraits", Vector3(-38, -8.3, -8), Vector3(-60, -8.0, -4)],
	["armour_and_portraits", Vector3(-11, 2.0, 57), Vector3(-17.5, 3.5, 47)],
	["compass_rose", Vector3(0, 7.0, 62.5), Vector3(0, 0, 54)],
	["tower_portraits", Vector3(0, 21.7, -20), Vector3(-5.5, 23.5, -29)],
	["great_hall_from_dais", Vector3(-100, 2.7, 56), Vector3(-21, 7, 56)],
	["dueling_club", Vector3(23, 1.7, 43), Vector3(54, 1, 69)],
	["tower_from_floor", Vector3(-14, 1.7, 14), Vector3(4, 40, -20)],
	["tower_gallery_L3", Vector3(19, 31.7, 14), Vector3(-10, 22, -20)],
	["tower_from_top", Vector3(12, 76, 6), Vector3(-4, 0, -14)],
	["library_from_door", Vector3(-27, 31.7, -15), Vector3(-80, 38, -30)],
	["corridor_L2", Vector3(27, 21.7, -8), Vector3(86, 21, -8)],
	["dungeon_west", Vector3(-19, -8.3, -7), Vector3(-90, -8, -7)],
	["potions", Vector3(-38, -7.6, -15.5), Vector3(-38, -9.2, -36)],
	["kitchens", Vector3(26, -8.0, -15.5), Vector3(31, -8.5, -39)],
	["feast_kitchen_table", Vector3(27.4, -8.1, -22.0), Vector3(25.5, -9.1, -25.5)],
	["library_aisle", Vector3(-55, 31.7, -13.5), Vector3(-55, 32.5, -40)],
	["library_mezzanine", Vector3(-28.5, 41.7, -6.5), Vector3(-72, 38, -32)],
	["tower_chandelier", Vector3(14, 61.7, 9), Vector3(0, 75, -6)],
	["transfiguration", Vector3(41, 11.8, -16.5), Vector3(41, 10.5, -40)],
	["charms", Vector3(70, 21.8, -16.5), Vector3(70, 20.5, -40)],
	["gryffindor", Vector3(48, 71.8, -18), Vector3(29, 71.0, -28.5)],
	["ravenclaw", Vector3(-28, 51.7, -30), Vector3(-41, 53.5, -10)],
	["slytherin", Vector3(-62, -8.2, -16), Vector3(-72, -7.5, -38)],
	["hufflepuff", Vector3(56, -8.2, -15), Vector3(56, -8.5, -38)],
	["dueling_stands", Vector3(24, 3.5, 46), Vector3(48, 1.5, 62)],
	["room_of_requirement", Vector3(70, 71.8, -16.5), Vector3(70, 71.0, -40)],
	["ror_tapestry", Vector3(70, 71.8, -10.5), Vector3(70, 72.6, -4)],
	["owlery_owls", Vector3(0, 61.7, -66), Vector3(-6, 67, -80)],
	["owlery_bridge", Vector3(0, 61.7, -31), Vector3(0, 66, -74)],
]

const WALK_SPEED := 6.0
const FLY_SPEED := 20.0
const FAST := 3.0
const GRAVITY := 22.0

var _layout: Dictionary = {}
var _cam: Camera3D
var _body: CharacterBody3D
var _flying := false
var _yaw := PI
var _pitch := -0.05
var _hud: Label
var _stairs: Node3D


func _ready() -> void:
	_layout = Blockout.load_layout()
	_build_environment()
	var blockout := Blockout.instantiate(OS.get_cmdline_user_args().has("--grey"))
	blockout.name = "Blockout"
	blockout.position.y = MAP_Y
	add_child(blockout)
	if not ",".join(OS.get_cmdline_user_args()).contains("pbr"):
		Blockout.restyle(blockout)
	else:
		for n in blockout.find_children("*", "MeshInstance3D", true, false):
			(n as MeshInstance3D).material_override = Blockout.grid_material(Color(0.7, 0.68, 0.64))
	Blockout.add_room_lights(self, _layout, MAP_Y, 1.6 if OS.get_cmdline_user_args().has("--grey") else 0.55)
	if not ",".join(OS.get_cmdline_user_args()).contains("occl"):
		print("occluders: %d" % Blockout.add_occluders(blockout))
	if not OS.get_cmdline_user_args().has("--grey"):
		# The live map's dressing: atmosphere, floating candles, chandeliers,
		# moonlight (the preview's own sun goes out).
		var we := get_node("WorldEnvironment") as WorldEnvironment
		var perf_off := ",".join(OS.get_cmdline_user_args())
		if not perf_off.contains("atmo"):
			CastleAtmosphere.apply(we.environment)
		if not perf_off.contains("decor"):
			Decor.build(self, MAP_Y)
		for n in get_children():
			if n is DirectionalLight3D:
				n.visible = false
	_add_moving_stairs()
	_make_player()
	_teleport(LANDMARKS[0][1])
	var args := OS.get_cmdline_user_args()
	if args.has("--check"):
		_hud.visible = false
		_run_checks.call_deferred()
	elif args.has("--perf"):
		_hud.visible = false
		_measure_perf.call_deferred()
	elif args.has("--shots"):
		_hud.visible = false
		var i := args.find("--shots")
		_render_shots(args[i + 1] if i + 1 < args.size() else "user://castle_shots")


# ------------------------------------------------------------------ building

func _build_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.30, 0.42, 0.58)
	sky_mat.sky_horizon_color = Color(0.62, 0.68, 0.74)
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	env.sky.sky_material = sky_mat
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.62, 0.62, 0.68)
	env.ambient_light_energy = 0.55
	env.tonemap_mode = Environment.TONE_MAPPER_ACES
	env.tonemap_exposure = 1.0
	env.ssao_enabled = true
	var we := WorldEnvironment.new()
	we.name = "WorldEnvironment"
	we.environment = env
	add_child(we)
	var sun := DirectionalLight3D.new()
	sun.light_energy = 0.9
	sun.rotation_degrees = Vector3(-50, -35, 0)
	sun.shadow_enabled = true
	add_child(sun)


func _add_moving_stairs() -> void:
	if not _layout.has("moving_stairs"):
		return
	_stairs = (load("res://tools/castle/moving_stairs_preview.gd") as GDScript).new()
	_stairs.name = "MovingStairs"
	add_child(_stairs)
	var mats := {}
	if OS.get_cmdline_user_args().has("--grey"):
		for key in ["deck", "step", "rail", "gate"]:
			mats[key] = Blockout.grid_material({"deck": Color(0.55, 0.50, 0.46), "step": Color(0.86, 0.80, 0.70),
				"rail": Color(0.33, 0.52, 0.82), "gate": Color(0.85, 0.25, 0.25)}[key])
	else:
		mats = {"deck": Blockout.kit_material("trim"), "step": Blockout.kit_material("stone_floor"),
			"rail": Blockout.kit_material("trim"), "gate": Blockout.kit_material("wood_dark")}
	_stairs.call("setup", _layout["moving_stairs"], MAP_Y, mats)


func _make_player() -> void:
	_body = CharacterBody3D.new()
	var col := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.35
	cap.height = 1.75
	col.shape = cap
	col.position.y = 0.875
	_body.add_child(col)
	_body.collision_mask = 1
	_body.floor_max_angle = deg_to_rad(46)
	_body.floor_snap_length = 0.4
	add_child(_body)
	_cam = Camera3D.new()
	_cam.far = 800.0
	_cam.fov = 72.0
	_cam.position.y = 1.62
	_body.add_child(_cam)
	_cam.current = true
	_hud = Label.new()
	_hud.position = Vector2(12, 8)
	_hud.add_theme_color_override("font_outline_color", Color.BLACK)
	_hud.add_theme_constant_override("outline_size", 6)
	var ui := CanvasLayer.new()
	ui.add_child(_hud)
	add_child(ui)


func _teleport(local: Vector3) -> void:
	_body.global_position = local + Vector3(0, MAP_Y + 0.2, 0)
	_body.velocity = Vector3.ZERO


# ------------------------------------------------------------------ control

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_yaw -= event.relative.x * 0.003
		_pitch = clampf(_pitch - event.relative.y * 0.003, -1.5, 1.5)
	elif event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_ESCAPE:
				Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
			KEY_TAB:
				_flying = not _flying
			KEY_F3:
				_hud.visible = not _hud.visible
			KEY_P:
				if _stairs != null:
					_stairs.set("paused", not bool(_stairs.get("paused")))
			KEY_0:
				_teleport(LANDMARKS[9][1])
			_:
				var n: int = event.keycode - KEY_1
				if n >= 0 and n < 9:
					_teleport(LANDMARKS[n][1])


func _physics_process(delta: float) -> void:
	_cam.rotation = Vector3(_pitch, 0, 0)
	_body.rotation = Vector3(0, _yaw, 0)
	var input := Vector3(
		float(Input.is_key_pressed(KEY_D)) - float(Input.is_key_pressed(KEY_A)),
		float(Input.is_key_pressed(KEY_SPACE)) - float(Input.is_key_pressed(KEY_C)),
		float(Input.is_key_pressed(KEY_S)) - float(Input.is_key_pressed(KEY_W)))
	var fast := FAST if Input.is_key_pressed(KEY_SHIFT) else 1.0
	if _flying:
		var dir := (_cam.global_basis * Vector3(input.x, 0, input.z)) + Vector3(0, input.y, 0)
		_body.velocity = dir.limit_length(1.0) * FLY_SPEED * fast
	else:
		_walk(Vector2(input.x, input.z), fast, Input.is_key_pressed(KEY_SPACE), delta)
	_body.move_and_slide()
	var p := _body.global_position
	_hud.text = "%s  x %.1f  y %.1f (kat %s)  z %.1f   %d fps   [Tab yürü/uç, 1-9/0 odalar, Shift hızlı]" % [
		"UÇUŞ" if _flying else "YÜRÜYÜŞ", p.x, p.y, _level_name(p.y - MAP_Y), p.z, Engine.get_frames_per_second()]


func _walk(move: Vector2, fast: float, jump: bool, delta: float) -> void:
	var flat := (_body.global_basis * Vector3(move.x, 0, move.y)).limit_length(1.0) * WALK_SPEED * fast
	_body.velocity.x = flat.x
	_body.velocity.z = flat.z
	_body.velocity.y = 6.0 if _body.is_on_floor() and jump else _body.velocity.y - GRAVITY * delta


func _level_name(local_y: float) -> String:
	var best := ""
	var best_y := -INF
	var levels: Dictionary = _layout.get("levels", {})
	for k in levels:
		var ly := float(levels[k])
		if local_y >= ly - 0.6 and ly > best_y:
			best = k
			best_y = ly
	return best


# ------------------------------------------------------------------ review

func _render_shots(out_dir: String) -> void:
	set_physics_process(false)
	if _stairs != null:
		_stairs.call("dock_all", 0)
	_cam.top_level = true
	DirAccess.make_dir_recursive_absolute(out_dir)
	for i in 3:
		await get_tree().process_frame
	var only := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--only="):
			only = a.trim_prefix("--only=")
	for s in SHOTS:
		if only != "" and not (",%s," % only).contains(",%s," % s[0]):
			continue
		_cam.look_at_from_position(s[1] + Vector3(0, MAP_Y, 0), s[2] + Vector3(0, MAP_Y, 0))
		for i in 3:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(out_dir.path_join("%s.jpg" % s[0]), 0.9)
		print("SHOT %s draws=%d" % [s[0], RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME)])
	get_tree().quit()


var _fails := 0
var _passes := 0

func _check(ok: bool, what: String) -> void:
	if ok:
		_passes += 1
		print("  PASS  ", what)
	else:
		_fails += 1
		print("  FAIL  ", what)


## Collision sanity for the blockout:
##   * every room has floor at its level (probed 1.5 m inside its south-east
##     corner, clear of daises and flights);
##   * every door has a walkable sill and head room;
##   * the player capsule climbs/descends every stair flight end to end.
func _run_checks() -> void:
	set_physics_process(false)
	for i in 4:
		await get_tree().physics_frame
	var space := get_world_3d().direct_space_state
	print("CASTLE BLOCKOUT CHECK")
	for r in _layout["rooms"]:
		if r["id"] == "dungeon_stairwell":
			continue  # the whole room is the flight; walked below
		var rect: Array = r["rect"]
		var y := float(r["y"])
		var probe := Vector3(float(rect[1]) - 1.5, MAP_Y + y + 1.0, float(rect[3]) - 1.5)
		var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(probe, probe + Vector3(0, -3, 0)))
		_check(not hit.is_empty() and absf(hit.position.y - (MAP_Y + y)) < 0.05,
			"floor under %s at y %.1f" % [r["id"], y])
	for d in _layout["doors"]:
		if d.has("sealed"):
			continue
		var at: Array = d["at"]
		var y := float(d["y"])
		var top := Vector3(float(at[0]), MAP_Y + y + float(d["h"]) - 0.2, float(at[1]))
		var down := space.intersect_ray(PhysicsRayQueryParameters3D.create(top, top + Vector3(0, -float(d["h"]), 0)))
		_check(not down.is_empty() and absf(down.position.y - (MAP_Y + y)) < 0.05,
			"door %s: clear %.1f m and a sill at y %.1f" % [d["id"], float(d["h"]) - 0.2, y])
	for s in _layout["stairs"]:
		await _walk_stair(s)
	var expected := (_layout.get("moving_stairs", {}).get("flights", []) as Array).size()
	_check(_stairs != null and int(_stairs.call("flight_count")) == expected,
		"the Grand Staircase built all %d moving flights" % expected)
	if _stairs != null and int(_stairs.call("flight_count")) == expected:
		for which in [0, 1]:
			_stairs.call("dock_all", which)
			for i in 3:
				await get_tree().physics_frame
			for k in int(_stairs.call("flight_count")):
				var yaw := float(_layout["moving_stairs"]["flights"][k]["docks"][which])
				var ends: Array = _stairs.call("flight_ends", k, yaw)
				await _walk_stair({"id": "moving_%d_dock%d" % [k, which],
					"from": [ends[0].x, ends[0].y, ends[0].z], "to": [ends[1].x, ends[1].y, ends[1].z]})
	if _stairs != null and int(_stairs.call("flight_count")) == expected:
		await _ride_swing()
	print("CASTLE BLOCKOUT CHECK %d passed, %d failed" % [_passes, _fails])
	get_tree().quit(1 if _fails > 0 else 0)


## Put the capsule just before the low end of a flight and walk it to the high
## end (then back down) with the same controller the preview uses.
func _walk_stair(s: Dictionary) -> void:
	var a := Vector3(s["from"][0], s["from"][1], s["from"][2])
	var b := Vector3(s["to"][0], s["to"][1], s["to"][2])
	var low := a if a.y < b.y else b
	var high := b if a.y < b.y else a
	var dir := Vector3(high.x - low.x, 0, high.z - low.z).normalized()
	for leg in [[low - dir * 0.8, high, dir], [high + dir * 0.8, low, -dir]]:
		var start: Vector3 = leg[0]
		var goal: Vector3 = leg[1]
		var d: Vector3 = leg[2]
		_body.global_position = start + Vector3(0, MAP_Y + 0.15, 0)
		_body.velocity = Vector3.ZERO
		_body.rotation = Vector3(0, atan2(-d.x, -d.z), 0)
		var run := Vector2(start.x - goal.x, start.z - goal.z).length()
		# along a slope the controller covers less ground per second than on the flat
		var frames := int((run + 1.5) / WALK_SPEED * 60.0 * 1.6) + 30
		var reached := false
		for f in frames:
			_walk(Vector2(0, -1), 1.0, false, 1.0 / 60.0)
			_body.move_and_slide()
			await get_tree().physics_frame
			var p := _body.global_position - Vector3(0, MAP_Y, 0)
			if Vector2(p.x - start.x, p.z - start.z).length() >= run and absf(p.y - goal.y) < 0.35:
				reached = true
				break
		var end := _body.global_position - Vector3(0, MAP_Y, 0)
		_check(reached, "stair %s %s: reached y %.1f (at %.1f, %.1f, %.1f)" % [
			s["id"], "up" if leg[2] == dir else "down", goal.y, end.x, end.y, end.z])


## Stand in the middle of storey 0's flight while it swings between its docks:
## the rider must be carried round with the deck, not dropped into the well.
func _ride_swing() -> void:
	_stairs.call("dock_all", 0)
	_stairs.set("time", 0.0)
	var ends: Array = _stairs.call("flight_ends", 0, float(_layout["moving_stairs"]["flights"][0]["docks"][0]))
	var mid: Vector3 = (ends[0] + ends[1]) * 0.5
	_body.global_position = mid + Vector3(0, MAP_Y + 0.3, 0)
	_body.velocity = Vector3.ZERO
	for i in 20:
		_walk(Vector2.ZERO, 1.0, false, 1.0 / 60.0)
		_body.move_and_slide()
		await get_tree().physics_frame
	_stairs.set("paused", false)
	var lowest := INF
	for f in int(8.0 * 60.0):
		_walk(Vector2.ZERO, 1.0, false, 1.0 / 60.0)
		_body.move_and_slide()
		await get_tree().physics_frame
		lowest = minf(lowest, _body.global_position.y - MAP_Y)
	_stairs.set("paused", true)
	var end_ends: Array = _stairs.call("flight_ends", 0, float(_layout["moving_stairs"]["flights"][0]["docks"][1]))
	var end_mid: Vector3 = (end_ends[0] + end_ends[1]) * 0.5
	var p := _body.global_position - Vector3(0, MAP_Y, 0)
	_check(lowest > mid.y - 1.0 and Vector2(p.x - end_mid.x, p.z - end_mid.z).length() < 2.5,
		"a rider is carried round by the swinging flight (ended %.1f m from the deck middle, lowest y %.1f)" % [
			Vector2(p.x - end_mid.x, p.z - end_mid.z).length(), lowest])



## Frame time at every review viewpoint (2 s warm-up, 3 s sample), for the
## quality preset this run uses.
func _measure_perf() -> void:
	set_physics_process(false)
	_cam.top_level = true
	get_viewport().get_window().size = Vector2i(1600, 900)
	for i in 30:
		await get_tree().process_frame
	# Ablations for finding the cost: --perf-off=fill,decor_lights,shadows,moon,fog,feast
	var off: PackedStringArray = []
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--perf-off="):
			off = arg.trim_prefix("--perf-off=").split(",")
	for n in find_children("*", "Light3D", true, false):
		var light := n as Light3D
		var in_decor := light.get_parent() != self
		if off.has("fill") and not in_decor and light is OmniLight3D:
			light.visible = false
		if off.has("decor_lights") and in_decor and light is OmniLight3D:
			light.visible = false
		if off.has("shadows") and light is OmniLight3D:
			light.shadow_enabled = false
		if off.has("moon") and light is DirectionalLight3D:
			light.visible = false
	if off.has("glow"):
		(get_node("WorldEnvironment") as WorldEnvironment).environment.glow_enabled = false
	if off.has("aniso"):
		ProjectSettings.set_setting("rendering/textures/default_filters/anisotropic_filtering_level", 0)
		RenderingServer.viewport_set_anisotropic_filtering_level(get_viewport().get_viewport_rid(), RenderingServer.VIEWPORT_ANISOTROPY_DISABLED)
	if off.has("fog"):
		(get_node("WorldEnvironment") as WorldEnvironment).environment.volumetric_fog_enabled = false
	if off.has("feast"):
		for n in find_children("Feast", "Node3D", true, false):
			(n as Node3D).visible = false
	var only: PackedStringArray = []
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--perf-only="):
			only = arg.trim_prefix("--perf-only=").split(",")
	print("PERF quality=%s adapter=%s off=%s" % [QualityPreset.current(), RenderingServer.get_video_adapter_name(), off])
	# vsync caps the frame rate: the main viewport's GPU time tells the cost
	var vp := get_viewport().get_viewport_rid()
	RenderingServer.viewport_set_measure_render_time(vp, true)
	for s in SHOTS:
		if not only.is_empty() and not only.has(s[0]):
			continue
		_cam.look_at_from_position(s[1] + Vector3(0, MAP_Y, 0), s[2] + Vector3(0, MAP_Y, 0))
		var t0 := Time.get_ticks_msec()
		while Time.get_ticks_msec() - t0 < 2000:
			await get_tree().process_frame
		var frames := 0
		var gpu := 0.0
		t0 = Time.get_ticks_usec()
		while Time.get_ticks_usec() - t0 < 3000000:
			await get_tree().process_frame
			gpu += RenderingServer.viewport_get_measured_render_time_gpu(vp)
			frames += 1
		var ms := float(Time.get_ticks_usec() - t0) / 1000.0 / frames
		print("PERF %-24s %6.1f fps  %5.1f ms  gpu %5.2f ms  draws=%d prims=%d" % [s[0], 1000.0 / ms, ms, gpu / frames,
			RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
			RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME)])
	get_tree().quit()
