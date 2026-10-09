extends Node

## Rig presentation capture: frames the wand in the hand, the cast aim, the
## rider's grip on the broom and the walking feet, as PNGs in tools/downloads/,
## next to the measurements the same frames describe.
##
## Run with a rendering driver (not --headless):
##   godot --path . res://scenes/test/rig_capture.tscn

var rendered_bones := {}

const OUT_DIR := "res://tools/downloads"

@onready var world = $GameWorld

func _enter_tree() -> void:
	NetworkManager.local_character_data = {}
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false

func _ready() -> void:
	await get_tree().create_timer(1.2).timeout
	var player = world.local_player
	var skeleton: Skeleton3D = player._find_skeleton()
	skeleton.skeleton_updated.connect(func():
		for i in range(skeleton.get_bone_count()):
			rendered_bones[skeleton.get_bone_name(i)] = skeleton.global_transform * skeleton.get_bone_global_pose(i)
	)
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	if player.nameplate:
		player.nameplate.hide()
	var camera := Camera3D.new()
	world.add_child(camera)
	camera.current = true
	camera.fov = 42.0

	# ---- standing: the wand in the hand
	await _stage(player, Vector3(0, 0.15, 5), 0.0)
	await get_tree().create_timer(0.6).timeout
	var wrist: Vector3 = _bone(player, "Wrist.R")
	print("CAPTURE idle wrist.R=%s" % wrist)
	var chest: Vector3 = _bone(player, "Chest")
	await _shot(camera, "rig-0-body-front", chest + Vector3(0.0, 0.15, 3.4), chest)
	await _shot(camera, "rig-1-wand-idle", wrist + Vector3(-1.15, 0.35, 1.45), wrist)
	await _shot(camera, "rig-1-wand-idle-far", wrist + Vector3(-0.35, 0.75, 2.35), wrist)

	# ---- casting at a target dead ahead
	var dummy := Node3D.new()
	world.add_child(dummy)
	dummy.global_position = Vector3(0, 1.2, 16)
	player.set_target(dummy)
	player.current_mana = player.max_mana
	player._cast_lock = 0.0
	player.spell_cooldowns.clear()
	player.cast_spell("basic_cast")
	await get_tree().create_timer(0.14).timeout
	print("CAPTURE cast weight=%.2f aiming=%s" % [player.hero_anim.cast_weight(),
		player.hero_anim.cast_aiming()])
	_report_wand_nodes(player)
	# The hold is 0.42 s: shoot without a settle so the release pose is still up.
	await _shot(camera, "rig-2-cast", chest + Vector3(0.9, 0.25, 2.6), chest, 0.0)
	await _shot(camera, "rig-2-cast-side", chest + Vector3(2.6, 0.25, 0.4), chest, 0.0)
	await _shot(camera, "rig-2-cast-close", wrist + Vector3(-1.1, 0.5, 1.5), wrist, 0.0)
	player.set_target(null)
	dummy.queue_free()
	await get_tree().create_timer(0.8).timeout

	# ---- mounted: the rider's grip on the broom
	await _stage(player, Vector3(0, 0.15, 5), 0.0)
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player._combat_until = 0.0
	player.toggle_broom_mount()
	player.global_position = Vector3(0, 3.2, 20)
	player.velocity = Vector3.ZERO
	# The grip yields while the get-on one-shot plays; wait for it to engage so the
	# capture shows the ride pose, not the transition.
	for _i in range(240):
		if player.broom_grip and player.broom_grip.engaged():
			break
		await get_tree().physics_frame
	await get_tree().create_timer(0.2).timeout
	print("CAPTURE mount grip_engaged=%s error=%.3f" % [
		player.broom_grip.engaged() if player.broom_grip else false,
		player.broom_grip.hand_error() if player.broom_grip else -1.0])
	var hips: Vector3 = player.socket("Socket_Hips").global_position
	print("CAPTURE mount hips=%s mounted=%s clip=%s" % [hips, player.is_mounted,
		player.hero_anim.current_clip])
	await _shot(camera, "rig-3-mount-side", hips + Vector3(4.6, 0.2, 0.0), hips)
	await _shot(camera, "rig-3-mount-front", hips + Vector3(0.0, 0.3, 4.2), hips)
	await _shot(camera, "rig-3-mount-three-quarter", hips + Vector3(3.0, 1.4, 3.2), hips)
	var handle_focus: Vector3 = player.broom.grip_socket.global_position + Vector3.UP * BroomGripModifier.SHAFT_RISE
	await _shot(camera, "rig-3-handle-close", handle_focus + Vector3(0.55, 0.4, 0.9), handle_focus)
	Input.action_press("move_left")
	await get_tree().create_timer(0.9).timeout
	await _shot(camera, "rig-3-mount-bank", hips + Vector3(3.4, 1.0, 3.4), hips)
	# Close on the hands, which is what "holding the broom" actually means.
	# Close on the hands, hovering (the rider is ~1 m above the body origin while
	# seated), which is what "holding the broom" actually means.
	Input.action_release("move_left")
	await get_tree().create_timer(0.8).timeout
	var focus := Vector3(0, 1.0, 0.2)
	print("CAPTURE grip close: hips=%s player=%s error=%.3f" % [
		player.socket("Socket_Hips").global_position, player.global_position,
		player.broom_grip.hand_error()])
	# Independent check: the distance from each hand to the shaft line derived from
	# the broom's OWN sockets in world space (not from the modifier's helper).
	var sk2: Skeleton3D = player._find_skeleton()
	var line_a: Vector3 = player.broom.grip_socket.global_position + player.broom.get("model_root_ref").global_basis.y * BroomGripModifier.SHAFT_RISE
	var shaft_dir: Vector3 = player.broom.broom_forward()
	for side in ["L", "R"]:
		var wrist_frame: Transform3D = rendered_bones["Wrist." + side]
		var palm := wrist_frame * RigIK.grip_frame(sk2, side, BroomGripModifier.PALM_DEPTH).origin
		print("CAPTURE hand %s dist_to_wood=%.3f" % [side, RigIK.distance_to_line(palm, line_a, shaft_dir)])
	await _follow(camera, player, "rig-3-grip-closeup", Vector3(1.25, 0.55, 1.0), focus)
	await _follow(camera, player, "rig-3-grip-tight", Vector3(0.95, 0.16, 0.55), focus)
	await _follow(camera, player, "rig-3-grip-top", Vector3(0.0, 1.35, 0.35), focus)
	await _follow(camera, player, "rig-3-grip-front", Vector3(0.35, 0.5, 1.5), focus)
	await _follow(camera, player, "rig-3-grip-above", Vector3(1.0, 1.4, 0.8), focus)
	Input.action_release("move_left")
	await get_tree().create_timer(0.5).timeout

	# ---- walking: the feet
	player.global_position = Vector3(0, 1.0, 20)
	player.velocity = Vector3.ZERO
	player._mount_lock = 0.0
	player.toggle_broom_mount()
	await _stage(player, Vector3(0, 0.15, 5), 0.0)
	Input.action_press("move_forward")
	await get_tree().create_timer(0.7).timeout
	var foot: Vector3 = _bone(player, "Foot.L")
	print("CAPTURE walk clip=%s foot=%s origin=%s" % [
		player.hero_anim.current_clip, foot, player.global_position])
	# Follow the runner: the camera re-aims every frame, so the body stays framed.
	await _follow(camera, player, "rig-4-walk-side", Vector3(3.0, 0.75, 0.0))
	await get_tree().create_timer(0.22).timeout
	await _follow(camera, player, "rig-4-walk-side-2", Vector3(3.0, 0.75, 0.0))
	await _follow(camera, player, "rig-4-walk-behind", Vector3(0.0, 0.7, -3.0))
	Input.action_release("move_forward")
	await get_tree().create_timer(0.03).timeout
	await _follow(camera, player, "rig-5-stop-side", Vector3(3.0, 0.75, 0.0))
	print("CAPTURE DONE")
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

func _stage(player, spot: Vector3, yaw: float) -> void:
	player.global_position = spot
	player.velocity = Vector3.ZERO
	player.visuals.rotation.y = yaw
	for _i in range(40):
		await get_tree().physics_frame

func _bone(player, name: String) -> Vector3:
	var sk: Skeleton3D = player._find_skeleton()
	if sk == null:
		return Vector3.ZERO
	var idx := sk.find_bone(name)
	if idx < 0:
		return Vector3.ZERO
	return (rendered_bones.get(name, sk.global_transform * sk.get_bone_global_pose(idx)) as Transform3D).origin

## Every wand-like node in the scene, where it is, and how far it sits from the
## casting wrist. A frame can show a wand that is not the caster's (a mob carries
## `1H_Wand` too, and a camera can end up inside one), so the capture transcript
## names each of them instead of leaving it to the eye.
func _report_wand_nodes(player) -> void:
	var wrist := _bone(player, "Wrist.R")
	for node in _wand_like(get_tree().root):
		var parent: Node = node.get_parent()
		print("CAPTURE wandnode %s parent=%s pos=%s wrist=%s dist=%.3f" % [
			node.name, parent.name if parent != null else "<root>", node.global_position,
			wrist, node.global_position.distance_to(wrist)])

func _wand_like(node: Node) -> Array:
	var out: Array = []
	if node is Node3D and String(node.name).contains("Wand"):
		out.append(node as Node3D)
	for child in node.get_children():
		out.append_array(_wand_like(child))
	return out

func _shot(camera: Camera3D, filename: String, pos: Vector3, target: Vector3,
		settle := 0.25) -> void:
	camera.global_position = pos
	camera.look_at(target)
	if settle > 0.0:
		await get_tree().create_timer(settle).timeout
	await RenderingServer.frame_post_draw
	var error := get_viewport().get_texture().get_image().save_png("%s/%s.png" % [OUT_DIR, filename])
	print("CAPTURE %s: %s" % [filename, error])

## A shot that tracks a moving body: the camera is re-aimed on every frame up to
## the moment of capture, so a running character stays in frame.
func _follow(camera: Camera3D, body: Node3D, filename: String, offset: Vector3,
		focus_offset := Vector3(0, 0.9, 0)) -> void:
	for _i in range(10):
		_aim(camera, body, offset, focus_offset)
		await get_tree().process_frame
	_aim(camera, body, offset, focus_offset)
	await RenderingServer.frame_post_draw
	var error := get_viewport().get_texture().get_image().save_png("%s/%s.png" % [OUT_DIR, filename])
	print("CAPTURE %s: %s  body=%s" % [filename, error, body.global_position])

func _aim(camera: Camera3D, body: Node3D, offset: Vector3,
		focus_offset := Vector3(0, 0.9, 0)) -> void:
	var focus: Vector3 = body.global_position + focus_offset
	camera.global_position = focus + offset
	camera.look_at(focus)
