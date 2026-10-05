extends Node

## Phase 12 capture harness (plan.md Phase 12 evidence).
##
## Runs windowed (a real renderer and a real audio device):
##
##   godot --path client res://scenes/test/phase12_capture.tscn -- --quality=high
##
## For every spell it stages the cast and the impact at a fixed spot and shoots
## three contexts - daylight outdoors, the dark castle interior, and a group
## fight with a live mob pack - as res://tools/downloads/phase12-<spell>-<context>.png.
## It then shoots the broom trail in flight and the boss warning mid-telegraph.
##
## The flipbook atlases themselves are copied beside the captures so the
## temporal evidence (frame order, cells) is inspectable from the same folder.

const OUT_DIR := "res://tools/downloads"
const SPELLS := ["basic_cast", "stupefy", "incendio", "bombarda", "expelliarmus", "protego", "ultimate"]

@onready var world = $GameWorld

var _camera: Camera3D
var _sun: DirectionalLight3D
var _quality := "high"
var _interior: Node3D

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--quality="):
			_quality = arg.trim_prefix("--quality=")
	preload("res://scripts/world/quality_preset.gd").forced(_quality)
	await get_tree().create_timer(1.4).timeout
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	_hide_hud_layers(world)
	_sun = world.get_node_or_null("DirectionalLight3D")
	_camera = Camera3D.new()
	_camera.fov = 62.0
	world.add_child(_camera)
	_camera.current = true
	_copy_atlases()

	await _capture_daylight()
	await _capture_interior()
	await _capture_group_fight()
	await _capture_broom_trail()
	await _capture_boss_warning()

	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

## ---------------------------------------------------------------- contexts

func _capture_daylight() -> void:
	var spot := Vector3(0, 0.15, -12)
	var view_from := Vector3(0, 2.4, -4.5)
	for spell in SPELLS:
		await _shoot_spell(spell, "daylight", spot, view_from)

func _capture_interior() -> void:
	_interior = load("res://scenes/world/castle_interior.tscn").instantiate()
	_interior.name = "Phase12Interior"
	world.add_child(_interior)
	await get_tree().create_timer(0.8).timeout
	var controller = world.get_node_or_null("MapController")
	if controller != null and controller.has_method("_apply_interior_ambience"):
		controller.call("_apply_interior_ambience", true)
	if _sun:
		_sun.visible = false
	# the Great Hall, from the phase-10 comparison viewpoint
	var spot := Vector3(-30, 201.35, 4)
	var view_from := Vector3(-18, 202.0, 8)
	for spell in SPELLS:
		await _shoot_spell(spell, "interior", spot, view_from)

func _capture_group_fight() -> void:
	# A real pack, staged in the clearing: the combat readability shot.
	var spot := Vector3(-70, 0.15, 20)
	var view_from := Vector3(-62, 2.6, 27)
	var staged := 0
	for pack in world.get_node("EncounterDirector").packs:
		for member in pack.members:
			if staged >= 5:
				break
			member.global_position = spot + Vector3(cos(staged * 1.3) * 2.6, 0.05, sin(staged * 1.3) * 2.6)
			member.spawn_point = member.global_position
			member.pack_anchor = member.global_position
			staged += 1
		if staged >= 5:
			break
	await get_tree().create_timer(0.4).timeout
	for spell in SPELLS:
		await _shoot_spell(spell, "groupfight", spot, view_from)

## ---------------------------------------------------------------- effects

func _shoot_spell(spell: String, context: String, spot: Vector3, view_from: Vector3) -> void:
	var skill := preload("res://scripts/spells/skill_fx.gd")
	_camera.global_position = view_from
	_camera.look_at(spot + Vector3(0, 1.0, 0))
	# cast stage first, then the impact that explains the hit
	skill.play_cast(world, null, spell, spot + Vector3(0, 1.2, 0), (view_from - spot).normalized())
	await get_tree().create_timer(0.22).timeout
	await RenderingServer.frame_post_draw
	_save("phase12-%s-%s.png" % [spell, context])
	# let the cast clear, then the impact
	await get_tree().create_timer(0.5).timeout
	skill.play_impact(world, spot + Vector3(0, 1.0, 0), spell)
	await get_tree().create_timer(0.2).timeout
	await RenderingServer.frame_post_draw
	_save("phase12-%s-%s-impact.png" % [spell, context])
	await get_tree().create_timer(0.9).timeout

func _capture_broom_trail() -> void:
	var player = world.local_player
	# mount from the ground (clearance is validated) and then climb: a mount
	# request in mid-air is correctly refused, which would capture nothing
	player.global_position = Vector3(0, 0.15, 20)
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.3).timeout
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player.toggle_broom_mount()
	player.global_position = Vector3(-4.0, 5.0, 24)
	await get_tree().physics_frame
	_camera.global_position = Vector3(6.0, 7.4, 34.0)
	_camera.look_at(Vector3(0, 5.2, 23.0))
	for i in range(30):
		player.velocity = Vector3(9, 0, -2)
		await get_tree().physics_frame
	_camera.global_position = Vector3(6.0, 7.4, 34.0)
	_camera.look_at(Vector3(0, 5.2, 23.0))
	await RenderingServer.frame_post_draw
	_save("phase12-broom-trail.png")
	print("PHASE12 CAPTURE broom mounted=%s" % player.is_mounted)
	player.toggle_broom_mount()
	await get_tree().create_timer(0.3).timeout

func _capture_boss_warning() -> void:
	var boss: Node3D = null
	for pack in world.get_node("EncounterDirector").packs:
		for member in pack.members:
			if bool(member.get("is_boss")):
				boss = member
				break
		if boss != null:
			break
	if boss == null:
		print("PHASE12 CAPTURE: no boss to stage")
		return
	# Outside the protected courtyard - inside it the boss legitimately refuses
	# to attack - and with a real target so the mob's OWN attack loop publishes
	# the telegraph. The shot is taken from whatever the authority says.
	var centre := Vector3(-70, 0.15, 20)
	# Move the anchor too: a boss teleported away from its leash walks home and
	# cancels the attack before it ever telegraphs.
	boss.global_position = centre + Vector3(0, 0, 3.0)
	boss.spawn_point = centre + Vector3(0, 0, 3.0)
	boss.pack_anchor = centre + Vector3(0, 0, 3.0)
	var player = world.local_player
	player.global_position = centre + Vector3(0, 0.15, 8.0)
	player.velocity = Vector3.ZERO
	boss.aggro_on(player)
	_camera.global_position = centre + Vector3(0, 8.6, 12.5)
	_camera.look_at(centre + Vector3(0, 0.4, 3.0))
	var shots := 0
	for i in range(600):
		await get_tree().physics_frame
		var effect = boss.get("_warning_effect")
		if effect != null and is_instance_valid(effect) and float(effect.get("progress")) > 0.45:
			if shots == 0:
				await RenderingServer.frame_post_draw
				_save("phase12-boss-warning.png")
				print("PHASE12 CAPTURE boss warning: %s" % str(effect.call("describe")))
				shots += 1
				break
	if shots == 0:
		print("PHASE12 CAPTURE boss warning: no telegraph observed")


## ---------------------------------------------------------------- helpers

func _shoot(path: String) -> void:
	await RenderingServer.frame_post_draw
	_save(path)

func _save(name: String) -> void:
	var path := "%s/%s" % [OUT_DIR, name]
	var error := get_viewport().get_texture().get_image().save_png(path)
	print("PHASE12 CAPTURE %s: %s (draw_calls=%d, prims=%d)" % [name, error,
		Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)])

func _hide_hud_layers(root: Node3D) -> void:
	for node in root.find_children("*", "CanvasLayer", true, false):
		if node.name != "CanvasLayer":
			(node as CanvasLayer).visible = false

## Copy the atlas sheets beside the captures: the frames themselves are evidence
## of the temporal build, not only the in-engine shots.
func _copy_atlases() -> void:
	var atlases := ["flame_loop_8x8_2k", "fire_burst_8x8_2k", "smoke_puff_8x8_2k",
		"energy_impact_8x8_2k", "shield_ripple_4x4_1k", "ground_marks_2x2_1k",
		"rune_masks_2x2_1k", "lightning_branches_2x2_1k"]
	for atlas in atlases:
		var source := "res://assets/vfx/atlases/%s.png" % atlas
		var image := Image.load_from_file(ProjectSettings.globalize_path(source))
		if image == null:
			continue
		image.save_png("%s/phase12-atlas-%s.png" % [OUT_DIR, atlas])
		print("PHASE12 CAPTURE atlas copied: %s" % atlas)
