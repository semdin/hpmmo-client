extends Node

## Repeatable visual QA. Run this scene with a graphical rendering driver.
@onready var world = $GameWorld

func _ready() -> void:
	await get_tree().create_timer(1.5).timeout
	var camera := Camera3D.new()
	world.add_child(camera)
	camera.current = true
	camera.fov = 65
	world.get_node("CanvasLayer").hide()
	world.overlay.hide()
	await _capture(camera, "castle-exterior", Vector3(53, 30, -5), Vector3(0, 13, -72))
	await _capture(camera, "great-hall", Vector3(0, 3.4, -50), Vector3(0, 5.5, -87))
	await _capture(camera, "library", Vector3(-22, 3.0, -62), Vector3(-31, 2.1, -79))
	var player = world.local_player
	player.global_position = Vector3(0, 0.15, -30)
	player.camera_rot_y = 0
	player.camera.current = true
	world.get_node("CanvasLayer").show()
	world.overlay.show()
	await get_tree().create_timer(0.6).timeout
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png("res://tools/downloads/gameplay-hud.png")
	world.get_node("CanvasLayer").hide()
	world.overlay.hide()
	camera.current = true
	var mobs = world.get_node("EncounterDirector").packs
	# Portrait lineup of the actual runtime assets.
	var members := [mobs[0].members[0], mobs[2].members[0], mobs[3].members[0], mobs[6].members[0]]
	for i in range(members.size()):
		members[i].global_position = Vector3(-6 + i * 4, 0, 50)
		members[i].set_physics_process(false)
		members[i].visuals.rotation.y = 0
	await _capture(camera, "enemy-assets", Vector3(0, 4, 63), Vector3(0, 1.7, 50))
	player.global_position = Vector3(0, 0.1, 5)
	await get_tree().create_timer(0.4).timeout
	player.toggle_broom_mount()
	player.global_position = Vector3(0, 4, 15)
	await _capture(camera, "broom-flight", Vector3(5, 5, 20), Vector3(0, 5, 15))
	# Phase 1 orientation evidence: rider + broom from rear, front and side,
	# moved to open ground so the castle-gate pillars do not occlude the shot.
	player.global_position = Vector3(0, 4.2, 24)
	player.visuals.rotation.y = 0.0
	await get_tree().create_timer(0.3).timeout
	await _capture(camera, "mount-rear", Vector3(0, 3.6, 19.6), Vector3(0, 3.9, 24))
	await _capture(camera, "mount-front", Vector3(0, 3.6, 28.4), Vector3(0, 3.9, 24))
	await _capture(camera, "mount-side", Vector3(5.2, 3.8, 24), Vector3(0, 3.9, 24))
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

func _capture(camera: Camera3D, filename: String, pos: Vector3, target: Vector3) -> void:
	camera.global_position = pos
	camera.look_at(target)
	await get_tree().create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	var error := get_viewport().get_texture().get_image().save_png("res://tools/downloads/%s.png" % filename)
	print("CAPTURE %s: %s" % [filename, error])
	print("RENDER %s: fps=%d, draw_calls=%d" % [filename, Engine.get_frames_per_second(), Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)])
