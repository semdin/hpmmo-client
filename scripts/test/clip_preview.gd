extends Node3D

## Clip preview: the real player body on a neutral stage plays one spell's cast
## through the game path (`_play_cast_animation`: cast layer, release retiming,
## wand aim) and, after it, the raw full-body clip as a one-shot. Frames at
## fixed times after each start land in res://tools/downloads/clip-preview/
## and are tiled into one contact sheet per pass.
##
##   godot --path . res://scenes/test/clip_preview.tscn -- --spell stupefy [--clip Cast_Stupefy]
##   godot --path . res://scenes/test/clip_preview.tscn -- --variants <dir>
##   godot --path . res://scenes/test/clip_preview.tscn -- --fx --spell bombarda [--combo N] [--house Slytherin]
##
## `--fx` fires the real spell: the cast animation, the wand-release cast flash,
## a visual-only bolt into a wall 10 m ahead (or Incendio's cone / Protego's
## ward) and the impact, shot wide from the side at fixed times -> one
## `fx-<spell>.png` strip per spell.
##
## `--variants` loads every *.glb in an absolute directory at runtime (glTF
## import, no Godot import step), and writes one raw-clip sheet per file to
## <dir>/sheets/ - for choosing between generated takes.

const OUT := "res://tools/downloads/clip-preview"
const CAST_TIMES := [0.0, 0.05, 0.1, 0.15, 0.22, 0.32, 0.45, 0.62]
const RAW_STEP := 0.1
var player: CharacterBody3D
var camera: Camera3D
var spell := "stupefy"
var clip := ""
var front := false
var fx_mode := false
const FX_TIMES := [0.05, 0.12, 0.2, 0.28, 0.36, 0.45, 0.55, 0.68, 0.82, 1.0, 1.25, 1.6]
const SFX = preload("res://scripts/spells/skill_fx.gd")
var combo := 0
var house := ""

func _ready() -> void:
	QuestManager.persistence_enabled = false
	var args := OS.get_cmdline_user_args()
	for i in args.size() - 1:
		if args[i] == "--spell":
			spell = args[i + 1]
		elif args[i] == "--clip":
			clip = args[i + 1]
		elif args[i] == "--combo":
			combo = int(args[i + 1])
		elif args[i] == "--house":
			house = args[i + 1]
	if clip == "":
		var key := "basic_cast:%d" % combo if spell == "basic_cast" else spell
		clip = String(preload("res://scripts/entities/player.gd").SPELL_CLIPS.get(key, {}).get("clip", "Spellcast_Shoot"))
	front = "--front" in args
	fx_mode = "--fx" in args
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT))
	var environment := WorldEnvironment.new()
	var settings := Environment.new()
	settings.background_mode = Environment.BG_COLOR
	settings.background_color = Color("1a2638")
	settings.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	settings.ambient_light_color = Color("c8d4e6")
	settings.ambient_light_energy = 0.8
	environment.environment = settings
	add_child(environment)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-45, -30, 0)
	light.light_energy = 1.3
	add_child(light)
	var floor_body := StaticBody3D.new()
	var collision := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(40, 0.2, 40)
	collision.shape = shape
	floor_body.position.y = -0.1
	floor_body.add_child(collision)
	var floor_mesh := MeshInstance3D.new()
	floor_mesh.mesh = BoxMesh.new()
	(floor_mesh.mesh as BoxMesh).size = shape.size
	var floor_mat := StandardMaterial3D.new()
	floor_mat.albedo_color = Color("2b3242")
	floor_mesh.material_override = floor_mat
	floor_body.add_child(floor_mesh)
	add_child(floor_body)
	player = preload("res://scenes/entities/player/player.tscn").instantiate()
	player.is_local_player = false
	player.sim_server_controlled = true
	add_child(player)
	if house != "":
		player.house = house
	player.nameplate.hide()
	player.sim_input = {"move": Vector2.ZERO, "yaw": 0.0, "jump": false}
	camera = Camera3D.new()
	camera.fov = 38.0
	add_child(camera)
	camera.current = true
	await get_tree().create_timer(1.0).timeout
	if fx_mode:
		await _fx_pass()
		get_tree().quit()
		return
	var variants_at := args.find("--variants")
	if variants_at >= 0 and variants_at + 1 < args.size():
		await _variants(args[variants_at + 1])
		get_tree().quit()
		return
	print("CLIP has %s_Upper=%s raw=%s" % [clip, player.hero_anim.has_clip(clip + "_Upper"), player.hero_anim.has_clip(clip)])
	for mi in player.visuals.find_children("Hero_Peasant_Arms", "MeshInstance3D", true, false):
		for si in range(mi.mesh.get_surface_count()):
			var src = mi.mesh.surface_get_material(si)
			var ov = mi.get_surface_override_material(si)
			print("ARMS surf %d src=%s ov=%s shader=%s" % [si, src.resource_name if src else "-", ov, (ov as ShaderMaterial).shader.resource_path if ov is ShaderMaterial else "-"])
	await _pass("cast", func(): player._play_cast_animation("Spellcast_Shoot",
		player.global_position + player.visuals.global_basis.z * 12.0 + Vector3.UP * 1.2, spell, combo), CAST_TIMES)
	await get_tree().create_timer(1.0).timeout
	var raw_times: Array = []
	var length: float = player.hero_anim.clip_length(clip)
	var t := 0.0
	while t <= length + 0.001:
		raw_times.append(t)
		t += RAW_STEP
	await _pass("raw", func(): player.hero_anim.play_oneshot(clip), raw_times)
	get_tree().quit()

func _variants(dir: String) -> void:
	var out_dir := dir.path_join("sheets")
	DirAccess.make_dir_recursive_absolute(out_dir)
	for file in DirAccess.get_files_at(dir):
		if not file.ends_with(".glb"):
			continue
		var doc := GLTFDocument.new()
		var state := GLTFState.new()
		if doc.append_from_file(dir.path_join(file), state) != OK:
			print("VARIANT %s: load failed" % file)
			continue
		var scene := doc.generate_scene(state)
		var tag := file.get_basename()
		var added := HeroAnimation.merge_clips_from(player.anim_player, scene.find_child("AnimationPlayer", true, false) as AnimationPlayer,
			func(n: String) -> String: return "V_%s%s" % [tag, n.trim_prefix("Clip")])
		scene.free()
		var name := "V_" + tag
		var times: Array = []
		var length: float = player.hero_anim.clip_length(name)
		var t := 0.0
		while t <= length + 0.001:
			times.append(t)
			t += RAW_STEP
		await get_tree().create_timer(0.5).timeout
		await _pass_to(out_dir.path_join(tag + ".png"), func(): player.hero_anim.play_oneshot(name), times)
		print("VARIANT %s: %d clips, %.2fs" % [tag, added, length])

## Torso lean (hips -> upper chest, degrees from vertical) and the clip the
## cast layer is playing, per captured shot.
func _report_lean(at: float) -> void:
	var skeleton: Skeleton3D = player.hero_anim.skeleton
	if skeleton == null:
		return
	var hips := skeleton.get_bone_global_pose(skeleton.find_bone("Hips")).origin
	var chest := skeleton.get_bone_global_pose(skeleton.find_bone("UpperChest")).origin
	var lean := rad_to_deg((chest - hips).normalized().angle_to(Vector3.UP))
	var layer = player.hero_anim.cast_layer
	print("LEAN t=%.2f %.0f deg cast_clip=%s layer=%s w=%.2f" % [at, lean, player.hero_anim.cast_clip,
		layer.animation.resource_name if layer != null and layer.animation != null else "-", layer.weight if layer != null else 0.0])

## The spell's whole presentation against a wall: cast flash, bolt, impact.
func _fx_pass() -> void:
	var wall := StaticBody3D.new()
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(6, 4, 0.4)
	shape.shape = box
	wall.add_child(shape)
	var wall_mesh := MeshInstance3D.new()
	wall_mesh.mesh = BoxMesh.new()
	(wall_mesh.mesh as BoxMesh).size = box.size
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color("3a4252")
	wall_mesh.material_override = mat
	wall.add_child(wall_mesh)
	add_child(wall)
	var forward: Vector3 = player.visuals.global_basis.z
	wall.global_position = player.global_position + forward * 10.0 + Vector3.UP * 2.0
	wall.look_at(player.global_position + Vector3.UP * 2.0, Vector3.UP)
	var aim: Vector3 = player.global_position + forward * 10.0 + Vector3.UP * 1.3
	_fx_aim = aim
	_fx_forward = forward
	player.animation_event.connect(_on_fx_release)
	await _pass_to("%s/fx-%s%s%s.png" % [OUT, spell, ("-%d" % combo) if spell == "basic_cast" else "", ("-" + house) if house != "" else ""],
		func(): player._play_cast_animation("Spellcast_Shoot", aim, spell, combo), FX_TIMES)

var _fx_aim := Vector3.ZERO
var _fx_forward := Vector3.FORWARD

func _on_fx_release(event: String) -> void:
	if event != "fx:wand_release":
		return
	var dir := (_fx_aim - (player.global_position + Vector3.UP * 1.3)).normalized()
	var origin := SFX.emission_origin(player, player.global_position + Vector3.UP * 1.3, dir)
	var sk: Skeleton3D = player.hero_anim.skeleton
	var head := (sk.global_transform * sk.get_bone_global_pose(sk.find_bone("Head"))).origin
	var hand := (sk.global_transform * sk.get_bone_global_pose(sk.find_bone("RightHand"))).origin
	print("RELEASE origin=%s head_dist=%.2f hand_dist=%.2f tip_ahead=%.2f" % [origin, origin.distance_to(head), origin.distance_to(hand),
		(origin - player.global_position).dot(player.visuals.global_basis.z)])
	if spell == "incendio":
		SFX.play_cast(self, player, spell, origin, dir)
		await get_tree().create_timer(0.25).timeout
		SFX.play_impact(self, _fx_aim - dir * 0.3, spell, null, dir)
	elif spell == "protego":
		SFX.play_cast(self, player, spell, origin, dir)
		var shield = preload("res://scenes/spells/protego_shield.tscn").instantiate()
		add_child(shield)
		shield.setup(player)
		await get_tree().create_timer(0.45).timeout
		var hit_at: Vector3 = player.global_position + Vector3.UP * 1.2 + _fx_forward * 1.6
		shield.on_hit(hit_at)
		SFX.play_impact(self, hit_at, spell, null, -dir)
	else:
		var bolt = preload("res://scenes/spells/spell_projectile.tscn").instantiate()
		add_child(bolt)
		bolt.global_position = origin
		bolt.visual_only = true
		bolt.setup(player, spell, dir, null, 1.0, _fx_aim)

func _process(_delta: float) -> void:
	if camera != null and player != null and fx_mode:
		# wide side shot that holds the caster and the wall
		var fwd: Vector3 = player.visuals.global_basis.z
		var side: Vector3 = player.visuals.global_basis.x
		# centred a little past halfway, so the impact at the wall stays in frame
		var mid := player.global_position + fwd * 5.4 + Vector3.UP * 1.3
		camera.fov = 50.0
		camera.global_position = mid - side * 6.0 + Vector3.UP * 0.9 - fwd * 0.5
		camera.look_at(mid)
		return
	if camera != null and player != null:
		# Profile from the wand side (a forward thrust reads as one), slightly
		# ahead so the face shows; `--front` for a front three-quarter.
		var focus := player.global_position + Vector3(0, 1.05, 0)
		var forward: Vector3 = player.visuals.global_basis.z
		var side: Vector3 = player.visuals.global_basis.x
		if front:
			camera.global_position = focus + forward * 3.2 - side * 2.0 + Vector3.UP * 0.5
		else:
			camera.global_position = focus - side * 3.6 + forward * 0.9 + Vector3.UP * 0.3
		camera.look_at(focus)

func _pass(tag: String, start: Callable, times: Array) -> void:
	await _pass_to("%s/%s-%s-%s.png" % [OUT, spell, clip, tag], start, times)

func _pass_to(path: String, start: Callable, times: Array) -> void:
	start.call()
	var began := Time.get_ticks_msec()
	var shots: Array[Image] = []
	for at in times:
		while (Time.get_ticks_msec() - began) / 1000.0 < float(at):
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		_report_lean(float(at))
		var img := get_viewport().get_texture().get_image()
		var shrink := 0.5 if fx_mode else 0.4
		img.resize(int(img.get_width() * shrink), int(img.get_height() * shrink))
		shots.append(img)
	var w := shots[0].get_width()
	var h := shots[0].get_height()
	var cols := mini(shots.size(), 6 if fx_mode else 10)
	var rows := int(ceil(shots.size() / float(cols)))
	var sheet := Image.create(w * cols, h * rows, false, shots[0].get_format())
	for i in shots.size():
		sheet.blit_rect(shots[i], Rect2i(0, 0, w, h), Vector2i((i % cols) * w, (i / cols) * h))
	print("CAPTURE %s: %s" % [path, sheet.save_png(path)])
