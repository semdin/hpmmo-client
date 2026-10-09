extends Node3D

## Isolated art-review stage using the REAL projectile, collision and VFX.
## godot --path client res://scenes/test/stupefy_preview.tscn -- --capture
## Space replays; 1/2/3 select quality; S switches real time / slow motion.
const FX = preload("res://scripts/spells/skill_fx.gd")
const QUALITY = preload("res://scripts/world/quality_preset.gd")
const OUT := "res://tools/downloads/stupefy-preview"
var player: CharacterBody3D
var target: StaticBody3D
var label: Label
var capture := false
var cycle := 0.0
var fired := false
var frames := 0
var recording := false
var spell := "stupefy"
var output_dir := OUT
var capture_frames := 250

func _ready() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	QUALITY.forced("high")
	Engine.time_scale = 0.4
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--quality="):
			QUALITY.forced(arg.trim_prefix("--quality="))
		elif arg.begins_with("--speed="):
			Engine.time_scale = clampf(float(arg.trim_prefix("--speed=")), 0.1, 1.0)
		elif arg.begins_with("--spell="):
			spell = arg.trim_prefix("--spell=")
	output_dir = "res://tools/downloads/%s-preview" % spell
	if spell == "protego":
		capture_frames = int(ceil(4.4 * 60 / Engine.time_scale))
	var environment := WorldEnvironment.new()
	var settings := Environment.new()
	settings.background_mode = Environment.BG_COLOR
	settings.background_color = Color("101522")
	settings.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	settings.ambient_light_color = Color("9aaecf")
	settings.ambient_light_energy = 0.55
	settings.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	settings.glow_enabled = true
	settings.glow_intensity = 0.6
	settings.glow_bloom = 0.08
	environment.environment = settings
	add_child(environment)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55, -25, 0)
	sun.light_energy = 1.5
	sun.shadow_enabled = true
	add_child(sun)
	var floor_body := StaticBody3D.new()
	add_child(floor_body)
	var floor_shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(40, 0.2, 30)
	floor_shape.shape = box
	floor_shape.position.y = -0.12
	floor_body.add_child(floor_shape)
	var floor_mesh := BoxMesh.new()
	floor_mesh.size = box.size
	_mesh(floor_body, floor_mesh, Vector3(0, -0.12, 0), Color("202a3b"))
	for x in range(-10, 11):
		var line := BoxMesh.new()
		line.size = Vector3(0.012, 0.003, 16)
		_mesh(self, line, Vector3(x, -0.012, 0), Color("334259"))
	for z in range(-8, 9):
		var line := BoxMesh.new()
		line.size = Vector3(20, 0.003, 0.012)
		_mesh(self, line, Vector3(0, -0.012, z), Color("334259"))
	player = preload("res://scenes/entities/player/player.tscn").instantiate()
	player.is_local_player = false
	player.position = Vector3(-4, 0, 0)
	add_child(player)
	player.set_physics_process(false)
	player.nameplate.hide()
	player.visuals.rotation.y = PI * 0.5
	player.hero_anim.set_locomotion("idle", "Idle")
	target = StaticBody3D.new()
	target.position = Vector3(4, 0, 0)
	add_child(target)
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.28
	capsule.height = 1.8
	shape.shape = capsule
	shape.position.y = 0.9
	target.add_child(shape)
	var dummy := CapsuleMesh.new()
	dummy.radius = 0.28
	dummy.height = 1.8
	_mesh(target, dummy, Vector3(0, 0.9, 0), Color("7d879d"))
	var camera := Camera3D.new()
	camera.position = Vector3(0.2, 3.1, 10.8)
	camera.fov = 53
	add_child(camera)
	camera.look_at(Vector3(0, 1.0, 0))
	camera.current = true
	var canvas := CanvasLayer.new()
	add_child(canvas)
	label = Label.new()
	label.position = Vector2(38, 28)
	label.add_theme_font_size_override("font_size", 24)
	canvas.add_child(label)
	var hint := Label.new()
	hint.position = Vector2(40, 666)
	hint.text = "SPACE  replay     S  speed     1 / 2 / 3  quality     •     Runtime spell VFX"
	hint.modulate = Color("97a6be")
	canvas.add_child(hint)
	if capture:
		DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(output_dir))
	await get_tree().create_timer(0.25).timeout
	recording = true

func _mesh(parent: Node3D, mesh: Mesh, location: Vector3, colour: Color) -> void:
	var node := MeshInstance3D.new()
	node.mesh = mesh
	node.position = location
	var material := StandardMaterial3D.new()
	material.albedo_color = colour
	material.roughness = 0.82
	node.material_override = material
	parent.add_child(node)

func _process(delta: float) -> void:
	if player != null and player.hero_anim:
		player.hero_anim.tick(delta)
	if not recording:
		return
	cycle += delta
	label.text = "%s\n%.1fx   /   %s" % [String(GameData.SPELLS.get(spell, {}).get("name", spell)).to_upper(), Engine.time_scale, QUALITY.current()]
	if cycle >= 0.16 and not fired:
		fired = true
		_fire()
	if cycle > (4.4 if spell == "protego" else 2.1) and not capture:
		cycle = 0
		fired = false
	if capture:
		frames += 1
		if frames % 2 == 0:
			_save_frame(frames / 2)
		if frames >= capture_frames:
			recording = false
			await RenderingServer.frame_post_draw
			get_tree().quit()

func _fire() -> void:
	var hit := target.global_position + Vector3.UP * 1.05
	player._play_cast_animation("Spellcast_Shoot", hit, spell)
	# Short pose settle is review-only. The gameplay launch timing is untouched.
	await get_tree().create_timer(0.07).timeout
	var origin := FX.emission_origin(player, player.global_position + Vector3.UP * 1.25, Vector3.RIGHT)
	if spell == "incendio":
		FX.play_cast(self, player, spell, origin, (hit - origin).normalized())
		await get_tree().create_timer(0.1).timeout
		FX.play_impact(self, hit, spell, target, Vector3.RIGHT)
		return
	if spell == "protego":
		var shield = preload("res://scenes/spells/protego_shield.tscn").instantiate()
		player.add_child(shield)
		shield.setup(player)
		FX.play_cast(self, player, spell, origin, Vector3.RIGHT)
		await get_tree().create_timer(0.75).timeout
		if is_instance_valid(shield):
			shield.on_hit(player.global_position + Vector3(1.65, 1.3, 0))
		return
	var bolt = preload("res://scenes/spells/spell_projectile.tscn").instantiate()
	add_child(bolt)
	bolt.global_position = origin
	bolt.visual_only = true
	bolt.setup(player, spell, (hit - origin).normalized())

func _save_frame(index: int) -> void:
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png("%s/frame-%03d.png" % [output_dir, index])

func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_SPACE:
				cycle = 0
				fired = false
			KEY_S:
				Engine.time_scale = 1.0 if Engine.time_scale < 0.9 else 0.4
			KEY_1:
				QUALITY.forced("low")
			KEY_2:
				QUALITY.forced("medium")
			KEY_3:
				QUALITY.forced("high")
			KEY_ESCAPE:
				get_tree().quit()

func _exit_tree() -> void:
	Engine.time_scale = 1.0
