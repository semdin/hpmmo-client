extends Node3D

## Run with a real renderer: the same matte plane must receive the same light
## when the camera orbits. This catches world/view normal-space mistakes.
func _ready() -> void:
	var environment := WorldEnvironment.new()
	var settings := Environment.new()
	settings.background_mode = Environment.BG_COLOR
	settings.background_color = Color.BLACK
	settings.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	environment.environment = settings
	add_child(environment)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55, -25, 0)
	sun.light_energy = 0.8
	add_child(sun)
	var plane := MeshInstance3D.new()
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(20, 20)
	plane.mesh = mesh
	var material := ShaderMaterial.new()
	material.shader = preload("res://assets/shaders/triplanar_pbr.gdshader")
	material.set_shader_parameter("albedo_tex", _texture(Color(0.5, 0.5, 0.5)))
	material.set_shader_parameter("normal_tex", _texture(Color(0.5, 0.5, 1)))
	material.set_shader_parameter("rough_min", 1.0)
	material.set_shader_parameter("normal_strength", 0.0)
	plane.material_override = material
	add_child(plane)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 4
	add_child(camera)
	camera.current = true
	var samples: Array[float] = []
	for angle in [0.0, PI * 0.5, PI, PI * 1.5]:
		camera.position = Vector3(sin(angle) * 6, 6, cos(angle) * 6)
		camera.look_at(Vector3.ZERO)
		for frame in range(12):
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var image := get_viewport().get_texture().get_image()
		var center := image.get_pixel(image.get_width() / 2, image.get_height() / 2)
		samples.append(center.get_luminance())
	var spread: float = samples.max() - samples.min()
	var passed: bool = samples.min() > 0.1 and spread < 0.025
	print("LIGHTING RESULT: camera-orbit luminance=%s, spread=%.4f, %s" % [samples, spread, "PASS" if passed else "FAIL"])
	get_tree().quit(0 if passed else 1)

func _texture(color: Color) -> ImageTexture:
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	image.fill(color)
	return ImageTexture.create_from_image(image)
