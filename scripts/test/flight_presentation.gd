extends Node

## Phase 9 flight presentation. Runs the real game world, mounts the local
## player and captures the rider from the front, the side and the rear, plus a
## banking turn and a landing, as PNGs in tools/downloads/.
##
## Run with a rendering driver (not --headless):
##   godot --path . res://scenes/test/flight_presentation.tscn

const OUT_DIR := "res://tools/downloads"

@onready var world = $GameWorld

func _ready() -> void:
	await get_tree().create_timer(1.5).timeout
	var player = world.local_player
	var camera := Camera3D.new()
	world.add_child(camera)
	camera.current = true
	camera.fov = 50.0
	world.get_node("CanvasLayer").hide()
	world.overlay.hide()

	# Stage on open ground, mount, then hover clear of the fountain and walls.
	player.global_position = Vector3(0, 0.15, 5)
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.4).timeout
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player.toggle_broom_mount()
	player.global_position = Vector3(0, 3.2, 20)
	player.velocity = Vector3.ZERO
	player.visuals.rotation.y = 0.0
	await get_tree().create_timer(0.8).timeout

	await _capture(camera, "phase9-flight-front", Vector3(0, 3.9, 24.4), Vector3(0, 3.9, 20.0))
	await _capture(camera, "phase9-flight-side", Vector3(4.4, 3.8, 20.0), Vector3(0, 3.9, 20.0))
	await _capture(camera, "phase9-flight-rear", Vector3(0, 3.9, 15.6), Vector3(0, 3.9, 20.0))
	await _capture(camera, "phase9-flight-three-quarter", Vector3(3.2, 4.6, 23.2), Vector3(0, 3.7, 20.0))

	# A banking turn: hold left so the phase and the lean both respond.
	Input.action_press("move_left")
	await get_tree().create_timer(0.9).timeout
	var phase_mid: int = player.mount_phase()
	var clip_mid: String = player.hero_anim.current_clip if player.hero_anim else ""
	print("TURN phase=%d clip=%s bank=%.3f" % [phase_mid, clip_mid, player.visuals.rotation.z])
	await _capture(camera, "phase9-flight-turn", Vector3(3.0, 4.4, 23.4), Vector3(0, 3.6, 20.0))
	Input.action_release("move_left")
	await get_tree().create_timer(0.6).timeout

	# Landing: descend, then take the landing clip and a last shot.
	player.global_position = Vector3(0, 1.0, 20)
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.2).timeout
	if player.hero_anim:
		player.hero_anim.play_oneshot("Broom_Land")
	await get_tree().create_timer(0.35).timeout
	await _capture(camera, "phase9-flight-landing", Vector3(3.0, 2.2, 22.8), Vector3(0, 1.5, 20.0))

	# Measurements for the report: what the deployed rig actually spans.
	var head_socket: Node3D = player.socket("Socket_Head")
	var foot_socket: Node3D = player.socket("Socket_Foot_L")
	var broom_report: Dictionary = player.broom.verify_axes()
	print("MEASURE sockets head=%.3f foot=%.3f player=%.3f" % [
		head_socket.global_position.y if head_socket else -1.0,
		foot_socket.global_position.y if foot_socket else -1.0,
		player.global_position.y])
	print("MEASURE broom nose=%.2f tail=%.2f seat_y=%.2f" % [
		broom_report["nose_z"], broom_report["tail_z"], broom_report["seat_y"]])
	print("MEASURE seat_gap=%.3f" % (
		player.broom.seat_socket.global_position.distance_to(player.socket("Socket_Hips").global_position)
		if player.broom and player.broom.seat_socket and player.socket("Socket_Hips") else -1.0))
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

func _capture(camera: Camera3D, filename: String, pos: Vector3, target: Vector3) -> void:
	camera.global_position = pos
	camera.look_at(target)
	await get_tree().create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	var error := get_viewport().get_texture().get_image().save_png("%s/%s.png" % [OUT_DIR, filename])
	print("CAPTURE %s: %s" % [filename, error])
