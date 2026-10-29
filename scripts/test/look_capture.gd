extends Node3D

## Appearance capture: heroes with different looks (HeroAppearance.apply_look)
## side by side, then face close-ups, as PNGs in tools/downloads/look-*.png.
##
## Run with a rendering driver (not --headless):
##   godot --path . res://scenes/test/look_capture.tscn

const OUT_DIR := "res://tools/downloads"
const LOOKS := [
	{},
	{"hair": 1, "hair_color": 6, "eyes": 1, "skin": 1, "outfit": 1, "height": 1.0},
	{"hair": 2, "hair_color": 4, "eyes": 2, "skin": 3, "outfit": 2},
	{"hair": 3, "hair_color": 1, "eyes": 3, "skin": 5, "outfit": 3, "height": -1.0},
	{"hair": 0, "hair_color": 2, "eyes": 0, "skin": 2, "outfit": 1},
	{"hair": 3, "hair_color": 8, "eyes": 4, "skin": 2, "outfit": 0},
]

var heroes: Array[Node3D] = []


func _ready() -> void:
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.32, 0.34, 0.38)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.7, 0.74, 0.82)
	env.environment.ambient_light_energy = 0.55
	env.environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-40, -25, 0)
	sun.light_energy = 1.6
	sun.shadow_enabled = true
	add_child(sun)
	for i in range(LOOKS.size()):
		var anchor := Node3D.new()
		anchor.position = Vector3((i - (LOOKS.size() - 1) * 0.5) * 0.95, 0, 0)
		add_child(anchor)
		var hero := HeroAppearance.spawn(anchor, Color(0.6, 0.1, 0.1))
		HeroAppearance.apply_look(anchor, LOOKS[i])
		heroes.append(hero)
	var camera := Camera3D.new()
	add_child(camera)
	camera.current = true
	camera.fov = 30.0
	await get_tree().create_timer(1.5).timeout
	camera.look_at_from_position(Vector3(0, 1.05, 9.0), Vector3(0, 0.95, 0))
	await _shot("look-row")
	for i in range(LOOKS.size()):
		var skeleton := heroes[i].find_child("Skeleton3D", true, false) as Skeleton3D
		var head := skeleton.global_transform * skeleton.get_bone_global_pose(skeleton.find_bone("Head")).origin
		var face := head + Vector3(0, 0.03, 0)
		camera.fov = 14.0
		camera.look_at_from_position(face + Vector3(0.22, 0.02, 1.0), face)
		await _shot("look-face-%d" % i)
	print("LOOK capture done")
	get_tree().quit()


func _shot(file: String) -> void:
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(ProjectSettings.globalize_path("%s/%s.png" % [OUT_DIR, file]))
	print("LOOK %s" % file)
