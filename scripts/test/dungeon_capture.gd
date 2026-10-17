extends Node3D

## In-engine look at the D1 Forbidden Corridor: the greybox map with its
## creatures posed in each room, four camera shots written side by side to
## res://tools/downloads/dungeon-capture.png.
##   godot --path . res://scenes/test/dungeon_capture.tscn

const F := 1200.0
const CAST := [
	["res://assets/models/monsters/cornish_pixie.glb", "Swing_Anticipation", 0.6, Vector3(-1.5, F + 1.0, -20), 10.0],
	["res://assets/models/monsters/cornish_pixie.glb", "Idle", 0.3, Vector3(1.2, F + 1.3, -22), -20.0],
	["res://assets/models/monsters/cornish_pixie.glb", "Run", 0.5, Vector3(0.0, F + 1.6, -25), 0.0],
	["res://assets/models/monsters/armour_guard.glb", "Swing_Anticipation", 0.9, Vector3(2.0, F, -30), -10.0],
	["res://assets/models/monsters/armour_commander.glb", "Idle", 0.4, Vector3(0, F, -86), 0.0],
	["res://assets/models/monsters/armour_guard.glb", "Walk", 0.3, Vector3(-5, F, -82), 20.0],
	["res://assets/models/monsters/devils_snare.glb", "Lash_Anticipation", 0.9, Vector3(0, F, -128), 0.0],
	["res://assets/models/monsters/fluffy.glb", "Roar_Attack", 0.25, Vector3(0, F, -196), 0.0],
]
const SHOTS := [
	[Vector3(0, F + 2.2, -8), Vector3(0, F + 1.4, -26)],
	[Vector3(12, F + 3.0, -166), Vector3(18, F + 1.2, -172)],
	[Vector3(5, F + 2.5, -106), Vector3(0, F + 2.2, -128)],
	[Vector3(15, F + 4.0, -180), Vector3(2, F + 0.5, -204)],
]

func _ready() -> void:
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.02, 0.02, 0.03)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.32, 0.30, 0.34)
	env.environment.ambient_light_energy = 0.9
	env.environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.environment.glow_enabled = true
	add_child(env)
	var map: Node3D = (load("res://scenes/world/dungeons/dng_forbidden_corridor.tscn") as PackedScene).instantiate()
	add_child(map)
	for entry in CAST:
		var body: Node3D = load(entry[0]).instantiate()
		body.position = entry[3]
		body.rotation.y = deg_to_rad(entry[4])
		add_child(body)
		var anim := body.find_child("AnimationPlayer", true, false) as AnimationPlayer
		if anim != null and anim.has_animation(entry[1]):
			anim.play(entry[1])
			anim.seek(anim.get_animation(entry[1]).length * float(entry[2]), true)
			anim.pause()
	var cam := Camera3D.new()
	cam.fov = 62.0
	add_child(cam)
	cam.make_current()
	await get_tree().process_frame
	var tiles: Array[Image] = []
	for shot in SHOTS:
		cam.position = shot[0]
		cam.look_at(shot[1])
		for i in 6:
			await get_tree().process_frame
		tiles.append(get_viewport().get_texture().get_image())
	var w := tiles[0].get_width()
	var h := tiles[0].get_height()
	var sheet := Image.create(w * 2, h * 2, false, tiles[0].get_format())
	for i in tiles.size():
		sheet.blit_rect(tiles[i], Rect2i(0, 0, w, h), Vector2i((i % 2) * w, (i / 2) * h))
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://tools/downloads"))
	sheet.save_png("res://tools/downloads/dungeon-capture.png")
	print("CAPTURE saved dungeon-capture.png")
	get_tree().quit()
