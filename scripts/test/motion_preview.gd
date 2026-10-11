extends Node3D

## Real player controller on a neutral stage. Space replays, S toggles slow
## motion, Escape closes. --capture saves a complete loop at fixed 60 fps.
const OUT := "res://tools/downloads/motion-preview"
const FX = preload("res://scripts/spells/skill_fx.gd")
var player: CharacterBody3D
var camera: Camera3D
var title: Label
var detail: Label
var elapsed := 0.0
var frame := 0
var capture := false
var triggered := {}
var spell := "basic_cast"
var finishing := false

func _ready() -> void:
	QuestManager.persistence_enabled = false
	capture = "--capture" in OS.get_cmdline_user_args()
	if capture:
		DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT))
	var environment := WorldEnvironment.new()
	var settings := Environment.new()
	settings.background_mode = Environment.BG_COLOR
	settings.background_color = Color("111b29")
	settings.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	settings.ambient_light_color = Color("bdcce1")
	settings.ambient_light_energy = 0.65
	settings.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment.environment = settings
	add_child(environment)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, -35, 0)
	light.light_energy = 1.4
	light.shadow_enabled = true
	add_child(light)
	var floor_body := StaticBody3D.new()
	var collision := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(100, 0.2, 100)
	collision.shape = shape
	floor_body.position.y = -0.1
	floor_body.add_child(collision)
	add_child(floor_body)
	var floor_mesh := BoxMesh.new()
	floor_mesh.size = shape.size
	mesh(floor_body, floor_mesh, Vector3.ZERO, Color("253547"))
	for i in range(-40, 41):
		var line := BoxMesh.new()
		line.size = Vector3(0.015, 0.003, 80)
		mesh(self, line, Vector3(i, 0.003, 0), Color("34495f"))
		line = BoxMesh.new()
		line.size = Vector3(80, 0.003, 0.015)
		mesh(self, line, Vector3(0, 0.003, i), Color("34495f"))
	player = preload("res://scenes/entities/player/player.tscn").instantiate()
	player.is_local_player = false
	player.sim_server_controlled = true
	add_child(player)
	player.nameplate.hide()
	player.animation_event.connect(_animation_event)
	camera = Camera3D.new()
	camera.fov = 40.0
	add_child(camera)
	camera.current = true
	var canvas := CanvasLayer.new()
	add_child(canvas)
	title = Label.new()
	title.position = Vector2(36, 26)
	title.add_theme_font_size_override("font_size", 30)
	canvas.add_child(title)
	detail = Label.new()
	detail.position = Vector2(38, 68)
	detail.modulate = Color("9cb4cd")
	canvas.add_child(detail)
	var hint := Label.new()
	hint.text = "SPACE  tekrar     S  yavaş çekim     ESC  kapat"
	hint.position = Vector2(38, 670)
	hint.modulate = Color("9cb4cd")
	canvas.add_child(hint)
	_restart()

func mesh(parent: Node3D, resource: Mesh, location: Vector3, colour: Color) -> void:
	var instance := MeshInstance3D.new()
	instance.mesh = resource
	instance.position = location
	var material := StandardMaterial3D.new()
	material.albedo_color = colour
	material.roughness = 0.85
	instance.material_override = material
	parent.add_child(instance)

func _restart() -> void:
	elapsed = 0.0
	triggered.clear()
	player.global_position = Vector3.ZERO
	player.velocity = Vector3.ZERO
	player.sim_input = {}
	player.visuals.rotation.y = 0.0
	player.hero_anim.end_cast()
	player.animation_events.clear()

func _physics_process(delta: float) -> void:
	if player == null:
		return
	elapsed += delta
	player.walk_speed = 8.5
	var movement := Vector2.ZERO
	var yaw := 90.0
	var jump := false
	var phase := "BEKLEME"
	if elapsed >= 1.0 and elapsed < 2.8:
		phase = "YÜRÜYÜŞ"
		player.walk_speed = 3.0
		movement = Vector2(0, -1)
	elif elapsed >= 2.8 and elapsed < 4.0:
		phase = "KOŞUYA GEÇİŞ"
		movement = Vector2(0, -1)
	elif elapsed >= 4.0 and elapsed < 5.2:
		phase = "DÖNÜŞ"
		yaw = 90.0 + smoothstep(4.0, 5.2, elapsed) * 180.0
		movement = Vector2(0, -1)
	elif elapsed >= 5.2 and elapsed < 6.0:
		phase = "DURUŞ"
	elif elapsed >= 6.0 and elapsed < 8.0:
		phase = "ASA KOMBOSU"
		for i in range(3):
			if elapsed >= 6.1 + i * 0.55 and not triggered.has(i):
				triggered[i] = true
				_cast("basic_cast", i)
	elif elapsed >= 8.0 and elapsed < 9.5:
		phase = "ZIPLAMA / İNİŞ"
		jump = elapsed < 8.1
	elif elapsed >= 9.5 and elapsed < 11.0:
		phase = "HAREKET HALİNDE BÜYÜ"
		movement = Vector2(0, -1)
		yaw = 270.0
		if elapsed > 9.9 and not triggered.has("moving"):
			triggered["moving"] = true
			_cast("stupefy")
	elif elapsed >= 11.0:
		phase = "TOPARLANMA"
	player.sim_input = {"move": movement, "yaw": yaw, "jump": jump}
	title.text = phase
	detail.text = "Hareket çalışması   /   %.1f m/s   /   %.1fx" % [Vector2(player.velocity.x, player.velocity.z).length(), Engine.time_scale]
	if elapsed > 12.0 and not capture:
		_restart()

func _process(_delta: float) -> void:
	if camera == null:
		return
	var focus := player.global_position + Vector3(0, 1.0, 0)
	camera.global_position = player.global_position + Vector3(3.3, 2.5, 5.4)
	camera.look_at(focus)
	if capture:
		frame += 1
		if frame % 3 == 0:
			_save_frame(frame / 3)
		if frame >= 720:
			set_process(false)
			await RenderingServer.frame_post_draw
			_finish()

func _cast(id: String, combo := 0) -> void:
	spell = id
	var aim: Vector3 = player.global_position + player.visuals.global_basis.z * 12.0 + Vector3.UP * 1.2
	player._play_cast_animation("Spellcast_Shoot", aim, id, combo)

func _animation_event(event: String) -> void:
	if event != "fx:wand_release":
		return
	var direction: Vector3 = player.visuals.global_basis.z
	var origin := FX.emission_origin(player, player.global_position + Vector3.UP, direction)
	var bolt = preload("res://scenes/spells/spell_projectile.tscn").instantiate()
	add_child(bolt)
	bolt.global_position = origin
	bolt.visual_only = true
	bolt.setup(player, spell, direction)

func _save_frame(index: int) -> void:
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png("%s/frame-%03d.png" % [OUT, index])

func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_SPACE: _restart()
			KEY_S: Engine.time_scale = 0.4 if Engine.time_scale > 0.9 else 1.0
			KEY_ESCAPE: _finish()

func _finish() -> void:
	if finishing:
		return
	finishing = true
	set_process(false)
	set_physics_process(false)
	FX.cancel_all_of(player)
	for child in get_children():
		child.queue_free()
	await get_tree().process_frame
	await get_tree().process_frame
	get_tree().quit()

func _exit_tree() -> void:
	Engine.time_scale = 1.0
