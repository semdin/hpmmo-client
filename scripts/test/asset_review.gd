extends Node3D

## in-engine asset review.
##
## Lineup of representative candidates at actual gameplay camera distance
## (the player SpringArm is 8 m; this scene shoots from ~9.5 m wide and ~3.6 m
## close-ups), under two lighting setups:
##   neutral  - flat grey studio: exposes texture/material truth without mood
##   final    - the game's daylight rig: shows how the set reads in context
##
## Run windowed (a real renderer is required):
##   godot --path . res://scenes/test/asset_review.tscn
## PNGs are written to res://tools/downloads/asset-review-*.png.

const OUT_DIR := "res://tools/downloads/"
const CANDIDATE_ROOT := "res://assets/candidates/"

var _camera: Camera3D
var _env: WorldEnvironment
var _neutral_lights: Array[Node3D] = []
var _sun: DirectionalLight3D
var _items: Array[Node3D] = []

func _ready() -> void:
	_build_stage()
	_build_lineup()
	await get_tree().create_timer(0.8).timeout
	for mode in ["neutral", "final"]:
		_apply_lighting(mode)
		await get_tree().create_timer(0.5).timeout
		await _shot("asset-review-actors-%s" % mode, Vector3(0, 2.6, 9.9), Vector3(0, 1.1, 0))
		await _shot("asset-review-surfaces-%s" % mode, Vector3(0.2, 3.2, -1.5), Vector3(0.2, 1.7, -12))
		for item in _items:
			var label: String = item.get_meta("review_label")
			var height: float = float(item.get_meta("review_height"))
			var z: float = item.global_position.z
			await _shot("asset-review-%s-%s" % [mode, label], Vector3(item.global_position.x, 1.5, z + 3.6), Vector3(item.global_position.x, height, z))
	print("ASSET REVIEW COMPLETE")
	get_tree().quit()

func _build_stage() -> void:
	# Ground
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(80, 80)
	var gmat := StandardMaterial3D.new()
	gmat.albedo_color = Color(0.32, 0.32, 0.34)
	gmat.roughness = 0.95
	plane.material = gmat
	ground.mesh = plane
	add_child(ground)
	# Collision floor so physics-driven mobs in the lineup stand still.
	var body := StaticBody3D.new()
	var col := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(80, 0.2, 80)
	col.shape = box
	col.position.y = -0.1
	body.add_child(col)
	add_child(body)

	_env = WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.5, 0.5, 0.5)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(1, 1, 1)
	env.ambient_light_energy = 0.6
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	_env.environment = env
	add_child(_env)

	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-45, -35, 0)
	key.light_energy = 1.1
	key.shadow_enabled = true
	_neutral_lights.append(key)
	add_child(key)

	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-20, 140, 0)
	fill.light_energy = 0.5
	_neutral_lights.append(fill)
	add_child(fill)

	_sun = DirectionalLight3D.new()
	_sun.rotation_degrees = Vector3(-52, 40, 0)
	_sun.light_energy = 1.25
	_sun.light_color = Color(1.0, 0.96, 0.88)
	_sun.shadow_enabled = true
	_sun.visible = false
	add_child(_sun)

	_camera = Camera3D.new()
	_camera.fov = 65.0
	_camera.current = true
	add_child(_camera)
	_apply_lighting("neutral")

func _apply_lighting(mode: String) -> void:
	var env := _env.environment
	if mode == "neutral":
		for light in _neutral_lights:
			light.visible = true
		_sun.visible = false
		env.background_mode = Environment.BG_COLOR
		env.background_color = Color(0.5, 0.5, 0.5)
		env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		env.ambient_light_energy = 0.6
	else:
		for light in _neutral_lights:
			light.visible = false
		_sun.visible = true
		var sky := Sky.new()
		var sky_mat := ProceduralSkyMaterial.new()
		sky_mat.sky_top_color = Color(0.35, 0.55, 0.85)
		sky_mat.sky_horizon_color = Color(0.75, 0.82, 0.9)
		sky_mat.ground_bottom_color = Color(0.35, 0.38, 0.32)
		sky_mat.ground_horizon_color = Color(0.6, 0.65, 0.6)
		sky.sky_material = sky_mat
		env.background_mode = Environment.BG_SKY
		env.sky = sky
		env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
		env.ambient_light_energy = 1.0

func _build_lineup() -> void:
	# Actors row (z = 0): shipped chibi vs taller CC0 candidates. The spider
	# candidate ships x100 node scale; it is shown here at its ~2 m production
	# span (normalize at import in the creature pass).
	_add_model("hero-current", "res://assets/models/characters/wizard.glb", Vector3(-5.25, 0, 0), 1.6)
	_add_model("hero-adventurer", "res://assets/candidates/character/quaternius-adventurer-male/adventurer-male.glb", Vector3(-3.15, 0, 0), 1.7)
	_add_model("hero-hooded", "res://assets/candidates/character/quaternius-hooded-adventurer/hooded-adventurer.glb", Vector3(-1.05, 0, 0), 1.7)
	_add_model("hero-mannequin", "res://assets/candidates/character/quaternius-universal-animation-library/UAL1_Standard.glb", Vector3(1.05, 0, 0), 1.7)
	_add_scene("spider-current", "res://scenes/entities/mobs/mob_acromantula.tscn", Vector3(3.15, 0.2, 0), 1.0)
	_add_model("spider-candidate-2m", "res://assets/candidates/spider-creature/quaternius-easy-enemies-spider/spider.glb", Vector3(5.25, 0, 0), 0.8, 0.34)
	# Surfaces row (z = -12, shot from between the rows): wall + fire pairs.
	_add_model("wall-current", "res://assets/models/environment/wall.gltf.glb", Vector3(-4.4, 0, -12), 4.0)
	_add_pbr_wall("wall-pbr", Vector3(-0.6, 0, -12))
	_add_fire_current(Vector3(2.4, 0, -12))
	_add_flipbook_sheet("fire-flipbook", Vector3(4.8, 0, -12), "res://assets/candidates/vfx-fire-energy/para-flipbooks/particlefx_09.png")

func _register_item(node: Node3D, label: String, height: float) -> void:
	node.set_meta("review_label", label)
	node.set_meta("review_height", height)
	var tag := Label3D.new()
	tag.text = label
	tag.font_size = 40
	tag.outline_size = 8
	tag.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	tag.position = Vector3(0, height + 1.4, 0)
	tag.modulate = Color(1, 1, 0.4)
	node.add_child(tag)
	_items.append(node)

func _add_model(label: String, path: String, pos: Vector3, face_height: float, scale_mult: float = 1.0) -> void:
	if not ResourceLoader.exists(path):
		print("SKIP %s: missing %s" % [label, path])
		return
	var inst: Node3D = (load(path) as PackedScene).instantiate()
	inst.position = pos
	if scale_mult != 1.0:
		inst.scale = Vector3.ONE * scale_mult
	add_child(inst)
	_play_idle(inst)
	_register_item(inst, label, face_height)

## Play the first available idle clip so candidates are reviewed in a neutral pose.
func _play_idle(inst: Node3D) -> void:
	for child in inst.find_children("*", "AnimationPlayer", true, false):
		var player := child as AnimationPlayer
		for clip in ["Idle_Loop", "Idle", "Idle_Neutral"]:
			if player.has_animation(clip):
				player.play(clip)
				return

func _add_scene(label: String, path: String, pos: Vector3, face_height: float) -> void:
	if not ResourceLoader.exists(path):
		print("SKIP %s: missing %s" % [label, path])
		return
	var inst: Node3D = (load(path) as PackedScene).instantiate()
	inst.position = pos
	add_child(inst)
	_register_item(inst, label, face_height)

## Delivered flipbook atlas shown as-is (frames are wired in the spell effects).
func _add_flipbook_sheet(label: String, pos: Vector3, path: String) -> void:
	if not ResourceLoader.exists(path):
		print("SKIP %s: missing %s" % [label, path])
		return
	var tex: Texture2D = load(path)
	if tex == null:
		print("SKIP %s: %s not imported yet" % [label, path])
		return
	var quad := MeshInstance3D.new()
	var mesh := QuadMesh.new()
	mesh.size = Vector2(2.2, 2.2)
	var mat := StandardMaterial3D.new()
	mat.albedo_texture = tex
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mesh.material = mat
	quad.mesh = mesh
	quad.position = pos + Vector3(0, 1.2, 0)
	add_child(quad)
	_register_item(quad, label, 1.2)

func _add_pbr_wall(label: String, pos: Vector3) -> void:
	# Assemble a candidate PBR material from the first downloaded texture set:
	# files are matched by common naming (diffuse/albedo, normal, rough, ao).
	var dirs: Array[String] = []
	var root := CANDIDATE_ROOT + "pbr-textures"
	if DirAccess.dir_exists_absolute(root):
		var dir := DirAccess.open(root)
		dir.list_dir_begin()
		var name := dir.get_next()
		while name != "":
			if dir.current_is_dir():
				dirs.append(root.path_join(name))
			name = dir.get_next()
		dir.list_dir_end()
	if dirs.is_empty():
		print("SKIP %s: no PBR sets under %s" % [label, root])
		return
	var set_dir: String = dirs[0]
	print("PBR SET for %s: %s" % [label, set_dir])
	var mat := StandardMaterial3D.new()
	var keys := {"diffuse": ["diff", "albedo", "col", "basecolor"], "normal": ["nor", "normal"], "rough": ["rough", "rgh"], "ao": ["ao", "ambient"]}
	var dir := DirAccess.open(set_dir)
	dir.list_dir_begin()
	var fname := dir.get_next()
	while fname != "":
		var lower := fname.to_lower()
		if not dir.current_is_dir() and (lower.ends_with(".png") or lower.ends_with(".jpg")):
			var key := ""
			for k in keys:
				for token in keys[k]:
					if lower.contains(token):
						key = k
						break
				if key != "":
					break
			if key != "":
				var tex: Texture2D = load(set_dir.path_join(fname))
				if tex:
					if key == "diffuse":
						mat.albedo_texture = tex
					elif key == "normal":
						mat.normal_enabled = true
						mat.normal_texture = tex
					elif key == "rough":
						mat.roughness_texture = tex
					elif key == "ao":
						mat.ao_enabled = true
						mat.ao_texture = tex
		fname = dir.get_next()
	dir.list_dir_end()
	mat.uv1_scale = Vector3(1, 1, 1)
	var wall := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(4, 4, 0.35)
	box.material = mat
	wall.mesh = box
	wall.position = pos + Vector3(0, 2, 0)
	add_child(wall)
	_register_item(wall, label, 4.0)

func _add_fire_current(pos: Vector3) -> void:
	# The shipped spell-fire look: Kenney flame quads on a CPUParticles3D.
	var holder := Node3D.new()
	holder.position = pos
	add_child(holder)
	var flame := CPUParticles3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(0.6, 0.6)
	var mat := StandardMaterial3D.new()
	var tex: Texture2D = load("res://assets/vfx/flame_01.png")
	mat.albedo_texture = tex
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.vertex_color_use_as_albedo = true
	quad.material = mat
	flame.mesh = quad
	flame.amount = 40
	flame.lifetime = 0.7
	flame.direction = Vector3(0, 1, 0)
	flame.spread = 12
	flame.initial_velocity_min = 1.5
	flame.initial_velocity_max = 3.0
	flame.gravity = Vector3(0, 1.0, 0)
	flame.scale_amount_min = 0.9
	flame.scale_amount_max = 2.2
	flame.color = Color(1.0, 0.55, 0.15)
	flame.position = Vector3(0, 0.4, 0)
	holder.add_child(flame)
	_register_item(holder, "fire-current", 0.9)

func _shot(name: String, cam_pos: Vector3, look_at: Vector3) -> void:
	_camera.global_position = cam_pos
	_camera.look_at(look_at)
	await get_tree().create_timer(0.35).timeout
	await RenderingServer.frame_post_draw
	var err := get_viewport().get_texture().get_image().save_png(OUT_DIR + name + ".png")
	print("CAPTURE %s: %s" % [name, err])
