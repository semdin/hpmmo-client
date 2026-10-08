extends Node

## Art pass fixed-view capture harness (evidence).
##
## Runs the same seven camera views in two lighting modes so the "neutral vs
## final" material comparison and the greybox before/after are the same frames:
##
##   godot --path client res://scenes/test/art_capture.tscn -- --mode=final
##   godot --path client res://scenes/test/art_capture.tscn -- --mode=neutral
##
## Neutral mode: flat ambient light, no sun, no glow, no fog, no SSAO — it shows
## what the albedo/normal/roughness maps actually contain. Final mode: the real
## game lighting. Files land in res://tools/downloads/art-<mode>-<view>.png.
##
## The interior is instantiated directly (not through the map transfer) so the
## capture does not depend on portal state; it is the same scene the transfer
## loads.

@onready var world = $GameWorld

var _camera: Camera3D
var _sun: DirectionalLight3D
var _mode := "final"
var _directional_hidden: Array = []

## name -> [camera position, look-at target] in the map's own coordinates.
const OUTDOOR_VIEWS := [
	["approach", Vector3(0, 3.4, -16), Vector3(0, 9.5, -70)],
	["courtyard", Vector3(13, 6.5, 27), Vector3(-2, 2, -12)],
	["terrain-west", Vector3(-30, 16, 30), Vector3(-70, 2, -24)],
]
const INTERIOR_VIEWS := [
	["great-hall", Vector3(-52, 203.4, 2), Vector3(-16, 204.5, -2)],
	["stair-hall", Vector3(8, 202.2, -16), Vector3(42, 205.0, -14)],
	["library", Vector3(-24, 207.6, -33), Vector3(-52, 208.2, -44)],
	["tower", Vector3(47, 213.6, 7), Vector3(60, 212.8, 9)],
	# Material close-up: raking torch light across the ashlar, so the normal
	# map's groove direction and the roughness break-up are verifiable.
	["wall-closeup", Vector3(-52.5, 201.6, 1.5), Vector3(-57.4, 202.4, -1.0)],
]

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--mode="):
			_mode = arg.trim_prefix("--mode=")
	await get_tree().create_timer(1.2).timeout
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	_hide_hud_layers(world)
	_camera = Camera3D.new()
	_camera.fov = 65
	world.add_child(_camera)
	_camera.current = true
	_sun = world.get_node_or_null("DirectionalLight3D")
	if _mode == "neutral":
		_apply_neutral(world)
	for view in OUTDOOR_VIEWS:
		await _shoot(world, String(view[0]), view[1], view[2])
	# Interior: the same scene the map controller loads, built in place.
	var interior = load("res://scenes/world/castle_interior.tscn").instantiate()
	interior.name = "InteriorLightRig"
	world.add_child(interior)
	await get_tree().create_timer(0.8).timeout
	# The game switches to the warm interior ambient on the transfer; do the
	# same here so the capture is the look the player actually gets. The
	# outdoor sun is hidden indoors by the map controller, so hide it too.
	var controller = world.get_node_or_null("MapController")
	if controller != null and controller.has_method("_apply_interior_ambience"):
		controller.call("_apply_interior_ambience", true)
	_directional_hidden.clear()
	for light in world.find_children("*", "DirectionalLight3D", true, false):
		var sun := light as DirectionalLight3D
		if sun.visible and sun.light_energy > 0.5:
			_directional_hidden.append(sun)
			sun.visible = false
	if _mode == "neutral":
		_apply_neutral(world)
	for view in INTERIOR_VIEWS:
		await _shoot(world, String(view[0]), view[1], view[2])
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

## Flat, texture-revealing lighting: a single colour ambient, no directional
## light, no post-processing. Nothing here is the game look; it is the material
## look.
func _apply_neutral(root: Node3D) -> void:
	var env_node := root.get_node_or_null("WorldEnvironment")
	if env_node and env_node is WorldEnvironment:
		var env := (env_node as WorldEnvironment).environment
		env.background_mode = Environment.BG_COLOR
		env.background_color = Color(0.55, 0.55, 0.56)
		env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		env.ambient_light_color = Color(1, 1, 1)
		env.ambient_light_energy = 0.9
		# Linear tone mapping so the capture shows the albedo map itself, not a
		# filmic curve on top of it.
		env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
		env.tonemap_exposure = 1.0
		env.fog_enabled = false
		env.glow_enabled = false
		env.ssao_enabled = false
		env.adjustment_enabled = false
	if _sun:
		_sun.visible = false
	# Local fixtures too: a neutral material view has no point lights adding
	# warmth on top of the flat ambient.
	for light in root.find_children("*", "Light3D", true, false):
		var any_light := light as Light3D
		if any_light is OmniLight3D or any_light is SpotLight3D:
			any_light.visible = false

## The map controller draws its own fade/location UI on a private CanvasLayer;
## hide every CanvasLayer that is not the game HUD so captures show only the
## world.
func _hide_hud_layers(root: Node3D) -> void:
	for node in root.find_children("*", "CanvasLayer", true, false):
		if node.name != "CanvasLayer":
			(node as CanvasLayer).visible = false

func _shoot(root: Node3D, label: String, pos: Vector3, target: Vector3) -> void:
	_camera.global_position = pos
	_camera.look_at(target)
	await get_tree().create_timer(0.35).timeout
	await RenderingServer.frame_post_draw
	var path := "res://tools/downloads/art-%s-%s.png" % [_mode, label]
	var error := get_viewport().get_texture().get_image().save_png(path)
	print("ART CAPTURE %s: %s (draw_calls=%d, prims=%d)" % [
		label, error, Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)])
