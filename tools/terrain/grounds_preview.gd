extends Node3D

## Walk / fly preview of the grounds terrain, outside the game.
##
## Open tools/terrain/grounds_preview.tscn in the editor and press F6.
##   Mouse look (click to capture, Esc to release)
##   WASD move, Space/C up/down (fly), Shift fast, Tab walk <-> fly,
##   1..9 jump to a landmark, F3 toggle the stats line.
## Headless shots (reviews):
##   godot --path . tools/terrain/grounds_preview.tscn -- --shots <out_dir>

const LANDMARKS := [
	["Avlu", Vector3(0, 0, 65)], ["Şato kapısı", Vector3(0, 0, 5)],
	["Hagrid", Vector3(-280, 0, -20)], ["Hogsmeade", Vector3(680, 0, -140)],
	["İstasyon", Vector3(610, 0, 260)], ["Quidditch", Vector3(330, 0, -330)],
	["Yaylalar", Vector3(280, 0, -760)], ["Kaçakçı sırtı", Vector3(-440, 0, -720)],
	["Örümcek çukuru", Vector3(-700, 0, 430)],
]
## [name, camera position, look target] for --shots.
const SHOTS := [
	["overview_se", Vector3(620, 380, 900), Vector3(-60, 40, -60)],
	["courtyard_ground", Vector3(-6, 60.5, 104), Vector3(0, 60, 20)],
	["lake_to_castle", Vector3(60, 8, 470), Vector3(0, 55, -10)],
	["east_road", Vector3(330, 47, -40), Vector3(680, 40, -140)],
	["hogsmeade_west", Vector3(820, 75, -70), Vector3(500, 30, -90)],
	["forest_trail", Vector3(-460, 52, -110), Vector3(-640, 40, -180)],
	["highlands", Vector3(150, 150, -520), Vector3(320, 115, -780)],
	["broom_high", Vector3(-200, 230, 300), Vector3(200, 40, -200)],
	["shore_low", Vector3(-185, 2.5, 130), Vector3(200, 0, 330)],
	["forest_edge", Vector3(-250, 30, 40), Vector3(-420, 25, -60)],
	["forest_inside", Vector3(-520, 36, -20), Vector3(-560, 36, 60)],
	["meadow_grove", Vector3(150, 30, 560), Vector3(300, 20, 700)],
	["castle_close", Vector3(-30, 66, 60), Vector3(0, 75, -10)],
	["hogsmeade_street", Vector3(600, 46, -110), Vector3(690, 42, -150)],
	["hagrid_hut", Vector3(-262, 27, 8), Vector3(-282, 23, -20)],
	["castle_from_lake_air", Vector3(120, 70, 300), Vector3(0, 75, -30)],
]

const WALK_SPEED := 6.0
const FLY_SPEED := 30.0
const FAST := 4.0
const GRAVITY := 22.0

var _terrain: GroundsTerrain
var _cam: Camera3D
var _body: CharacterBody3D
var _flying := true
var _yaw := 0.0
var _pitch := -0.2
var _hud: Label


func _ready() -> void:
	_build_environment()
	# The same build the game runs (terrain, castle, sites, lake, lamps, horizon).
	GroundsBuilder.build(self)
	_terrain = GroundsTerrain.active()
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
	add_child(_body)
	_cam = Camera3D.new()
	_cam.far = 4000.0
	_cam.fov = 70.0
	_cam.position.y = 1.62
	_body.add_child(_cam)
	_cam.current = true
	_terrain.set_camera(_cam)
	_hud = Label.new()
	_hud.position = Vector2(12, 8)
	_hud.add_theme_color_override("font_outline_color", Color.BLACK)
	_hud.add_theme_constant_override("outline_size", 6)
	var ui := CanvasLayer.new()
	ui.add_child(_hud)
	add_child(ui)
	_teleport(Vector3(0, 0, 100), true)
	var args := OS.get_cmdline_user_args()
	var i := args.find("--shots")
	if i >= 0:
		_hud.visible = false
		var only := args[args.find("--only") + 1].split(",") if args.has("--only") else PackedStringArray()
		_render_shots(args[i + 1] if i + 1 < args.size() else "user://grounds_shots", only)


func _build_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.24, 0.35, 0.49)
	sky_mat.sky_horizon_color = Color(0.57, 0.64, 0.70)
	sky_mat.ground_bottom_color = Color(0.14, 0.16, 0.17)
	sky_mat.ground_horizon_color = Color(0.29, 0.32, 0.34)
	sky_mat.sun_angle_max = 3.0
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	env.sky.sky_material = sky_mat
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.62
	env.tonemap_mode = Environment.TONE_MAPPER_ACES
	env.tonemap_exposure = 0.92
	env.fog_enabled = true
	env.fog_light_color = Color(0.66, 0.73, 0.80)
	env.fog_density = 0.00025
	env.fog_aerial_perspective = 0.35
	env.fog_sky_affect = 0.3
	env.ssao_enabled = true
	var we := WorldEnvironment.new()
	we.name = "WorldEnvironment"
	we.environment = env
	add_child(we)
	var sun := DirectionalLight3D.new()
	sun.name = "DirectionalLight3D"
	sun.light_color = Color(1.0, 0.96, 0.89)
	sun.light_energy = 1.1
	sun.rotation_degrees = Vector3(-38, -30, 0)
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_max_distance = 400.0
	sun.directional_shadow_blend_splits = true
	add_child(sun)


func _teleport(xz: Vector3, ground: bool) -> void:
	var h := GroundsTerrain.height_at(xz.x, xz.z)
	if is_nan(h):
		h = 0.0
	_body.global_position = Vector3(xz.x, maxf(h, 0.0) + (0.2 if ground else 25.0), xz.z)
	_body.velocity = Vector3.ZERO


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
			_:
				var n: int = event.keycode - KEY_1
				if n >= 0 and n < LANDMARKS.size():
					_teleport(LANDMARKS[n][1], not _flying)


func _physics_process(delta: float) -> void:
	_cam.rotation = Vector3(_pitch, 0, 0)
	_body.rotation = Vector3(0, _yaw, 0)
	var input := Vector3(
		Input.get_axis(&"ui_left", &"ui_right") + float(Input.is_key_pressed(KEY_D)) - float(Input.is_key_pressed(KEY_A)),
		float(Input.is_key_pressed(KEY_SPACE)) - float(Input.is_key_pressed(KEY_C)),
		float(Input.is_key_pressed(KEY_S)) - float(Input.is_key_pressed(KEY_W)))
	var fast := FAST if Input.is_key_pressed(KEY_SHIFT) else 1.0
	if _flying:
		var dir := (_cam.global_basis * Vector3(input.x, 0, input.z)) + Vector3(0, input.y, 0)
		_body.velocity = dir.limit_length(1.0) * FLY_SPEED * fast
	else:
		var flat := (_body.global_basis * Vector3(input.x, 0, input.z)).limit_length(1.0) * WALK_SPEED * fast
		_body.velocity.x = flat.x
		_body.velocity.z = flat.z
		_body.velocity.y = 6.0 if _body.is_on_floor() and Input.is_key_pressed(KEY_SPACE) else _body.velocity.y - GRAVITY * delta
	_body.move_and_slide()
	var p := _body.global_position
	var g := GroundsTerrain.height_at(p.x, p.z)
	_hud.text = "%s  x %.0f  y %.1f  z %.0f  zemin %.1f  (+%.0f m)   %d fps   [Tab yürü/uç, 1-9 yerler]" % [
		"UÇUŞ" if _flying else "YÜRÜYÜŞ", p.x, p.y, p.z, g, p.y - g, Engine.get_frames_per_second()]


func _render_shots(out_dir: String, only: PackedStringArray) -> void:
	set_physics_process(false)
	# Review shots are rendered in software on build machines: drop the costly bits.
	get_viewport().msaa_3d = Viewport.MSAA_DISABLED
	get_viewport().use_taa = false
	RenderingServer.directional_soft_shadow_filter_set_quality(RenderingServer.SHADOW_QUALITY_HARD)
	if OS.get_cmdline_user_args().has("--noshadow"):
		for n in get_children():
			if n is DirectionalLight3D:
				n.shadow_enabled = false
	if OS.get_cmdline_user_args().has("--flat"):
		_terrain.material = Terrain3DMaterial.new()
	_cam.top_level = true
	DirAccess.make_dir_recursive_absolute(out_dir)
	for i in 3:
		await get_tree().process_frame
		print("warmup frame ", i, " t=", Time.get_ticks_msec())
	for s in SHOTS:
		if not only.is_empty() and not only.has(s[0]):
			continue
		_cam.look_at_from_position(s[1], s[2])
		for i in 3:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(out_dir.path_join("%s.jpg" % s[0]), 0.9)
		print("SHOT ", s[0])
	get_tree().quit()
