extends Node3D

## In-engine look at the M1 creatures (trolls, dementors) under the game's
## daylight: each body is posed on a clip at a fixed fraction and the frame is
## written to res://tools/downloads/creature-capture.png.
##   godot --path . res://scenes/test/creature_capture.tscn

const LINEUP := [
	["res://assets/models/monsters/troll_forest.glb", "Swing_Anticipation", 0.85],
	["res://assets/models/monsters/troll_mountain.glb", "Walk", 0.3],
	["res://assets/models/monsters/dementor.glb", "Reach_Attack", 0.3],
	["res://assets/models/monsters/dementor_warden.glb", "Idle", 0.2],
	["res://assets/models/monsters/troll_forest.glb", "Idle", 0.5],
]

func _ready() -> void:
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.55, 0.62, 0.7)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.55, 0.58, 0.62)
	env.environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 35, 0)
	sun.light_energy = 1.3
	sun.shadow_enabled = true
	add_child(sun)
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(60, 30)
	ground.mesh = plane
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.32, 0.36, 0.26)
	ground.material_override = mat
	add_child(ground)
	var x := -10.0
	for entry in LINEUP:
		var body: Node3D = load(entry[0]).instantiate()
		body.position = Vector3(x, 0, 0)
		add_child(body)
		var anim: AnimationPlayer = body.find_child("AnimationPlayer", true, false)
		if anim and anim.has_animation(entry[1]):
			anim.play(entry[1])
			anim.seek(anim.get_animation(entry[1]).length * entry[2], true)
			anim.pause()
		else:
			push_error("missing clip %s on %s" % [entry[1], entry[0]])
		x += 5.0
	var cam := Camera3D.new()
	cam.position = Vector3(0, 3.2, 17)
	cam.fov = 58
	add_child(cam)
	cam.look_at(Vector3(0, 2.0, 0))
	cam.current = true
	await get_tree().create_timer(1.0).timeout
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://tools/downloads"))
	img.save_png("res://tools/downloads/creature-capture.png")
	print("CAPTURE written")
	get_tree().quit()
