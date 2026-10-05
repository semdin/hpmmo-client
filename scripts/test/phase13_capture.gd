extends Node

## Phase 13 capture harness (plan.md Phase 13 evidence).
##
## Runs windowed (a real renderer), with the full HUD visible:
##
##   godot --path client res://scenes/test/phase13_capture.tscn
##
## Shoots the HUD in combat (target frame, cast bar, status icons, toasts),
## in the castle (indoor floor label, staircase warning, travel UI), during a
## maintenance countdown, and in the onboarding flow; plus the settings screen.
## Every shot is written to res://tools/downloads/phase13-<subject>.png.
##
## The gameplay state each shot shows is staged through the same authoritative
## payloads the server sends (`SimAuthority.stats_changed`,
## `cast_started`, `reward_granted`, `maintenance_event`, `map_changed`), never
## by faking widget values - so the capture is evidence the binding works, not
## evidence a painter can draw numbers.

const OUT_DIR := "res://tools/downloads"

@onready var world = $GameWorld

var _camera: Camera3D

func _ready() -> void:
	await get_tree().create_timer(1.6).timeout
	_camera = Camera3D.new()
	_camera.fov = 65.0
	world.add_child(_camera)
	# The game camera keeps rendering; this one is only used to frame shots.
	await _capture_combat()
	await _capture_castle()
	await _capture_maintenance()
	await _capture_onboarding()
	await _capture_settings()
	_report_layout()
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

## ---------------------------------------------------------------- combat

func _capture_combat() -> void:
	var player = world.local_player
	var hud = world.hud
	var spot := Vector3(-70, 0.15, 20)
	# Stage a real pack around the player, exactly as a fight finds them.
	var staged := 0
	var first: Node3D = null
	for pack in world.get_node("EncounterDirector").packs:
		for member in pack.members:
			if staged >= 4:
				break
			member.global_position = spot + Vector3(cos(staged * 1.3) * 3.0, 0.05, sin(staged * 1.3) * 3.0)
			member.spawn_point = member.global_position
			member.pack_anchor = member.global_position
			if first == null:
				first = member
			staged += 1
		if staged >= 4:
			break
	player.global_position = spot + Vector3(0, 0.15, 5.0)
	player.velocity = Vector3.ZERO
	if first != null:
		player.set_target(first)
	# Wounded bars, a ward, a cast in flight and fresh rewards: one frame of a
	# fight, all of it through authoritative payloads.
	_stage_stats(hud, {"hp": 268, "max_hp": 500, "mana": 122, "max_mana": 300,
		"exp": 1450, "max_exp": 2000, "level": 12, "galleons": 1875})
	var record: Dictionary = SimAuthority.record_for(player)
	if not record.is_empty():
		record["ward_until_tick"] = int(SimAuthority.sim_tick) + 70
	SimAuthority.cast_ack.emit(7, 0, false, HPProtocol.REJECT_NO_MANA)
	if first != null:
		var uid := int(SimAuthority.record_for(first).get("uid", 0))
		if uid != 0:
			SimAuthority.entity_health.emit(uid, int(first.get("current_hp")), int(first.get("max_hp")), 0)
	SimAuthority.cast_started.emit(hud.binder.local_uid(), 9001, "incendio", Vector3.ZERO, int(SimAuthority.sim_tick) + 40)
	SimAuthority.reward_granted.emit(hud.binder.local_uid(), 1, 340, 65, [{"id": "mat_phoenix_ash", "amount": 1}], "capture:kill:1")
	await get_tree().create_timer(0.35).timeout
	_frame(spot + Vector3(0, 1.2, 0), Vector3(-4.5, 2.6, 8.5))
	_save("phase13-hud-combat.png")
	print("PHASE13 CAPTURE combat: hp=%s cast=%s" % [hud.hp_bar.value, hud.feedback.cast_spell])

## ---------------------------------------------------------------- castle

func _capture_castle() -> void:
	var hud = world.hud
	world.map_controller._start_transfer("castle_interior", "vestibule", 0)
	var waited := 0.0
	while world.map_controller.busy and waited < 8.0:
		await get_tree().process_frame
		waited += get_process_delta_time()
	await get_tree().create_timer(0.6).timeout
	var player = world.local_player
	player.global_position = Vector3(-30, 201.35, 4)
	player.velocity = Vector3.ZERO
	# Wait for the staircase's own cycle to leave the docked state: the warning
	# the shot must show is the authority's real transition, not a staged flag.
	var stairs = hud.travel._find_staircase()
	if stairs != null:
		var waited_stairs := 0.0
		while String(stairs.get("state")) == "docked" and waited_stairs < 14.0:
			await get_tree().process_frame
			waited_stairs += get_process_delta_time()
		print("PHASE13 CAPTURE staircase state=%s after %.1fs" % [stairs.get("state"), waited_stairs])
	await get_tree().create_timer(0.4).timeout
	_frame(Vector3(-30, 201.6, 4), Vector3(-16, 202.4, 12))
	await RenderingServer.frame_post_draw
	_save("phase13-hud-castle.png")
	print("PHASE13 CAPTURE castle: location=%s" % hud.travel.location_text())

## ---------------------------------------------------------------- maintenance

func _capture_maintenance() -> void:
	var hud = world.hud
	SimAuthority.maintenance_event.emit("ANNOUNCING", "scheduled maintenance", 150)
	await get_tree().create_timer(0.4).timeout
	_save("phase13-hud-maintenance.png")
	print("PHASE13 CAPTURE maintenance: %s (%s)" % [hud.maintenance.countdown_text(), hud.maintenance._title.text])
	SimAuthority.maintenance_event.emit("ONLINE", "", 0)

## ---------------------------------------------------------------- onboarding

func _capture_onboarding() -> void:
	var hud = world.hud
	var player = world.local_player
	# Back outside, in the courtyard, at the second step of the route.
	world.map_controller._start_transfer("grounds", "courtyard", 0)
	var waited := 0.0
	while world.map_controller.busy and waited < 8.0:
		await get_tree().process_frame
		waited += get_process_delta_time()
	player.global_position = Vector3(-9, 0.15, 2)
	player.velocity = Vector3.ZERO
	hud.onboarding.reset()
	var dummy = world.get_node_or_null("TrainingGrounds/Dummy0")
	if dummy != null:
		var uid := int(SimAuthority.record_for(dummy).get("uid", 0))
		print("PHASE13 CAPTURE onboarding staging: dummy_uid=%d kind=%s local_uid=%d protected=%s" % [
			uid, SimAuthority.record_by_uid(uid).get("kind", -1), hud.binder.local_uid(),
			HPRules.is_protected_point(player.global_position)])
		if uid != 0:
			SimAuthority.cast_landed.emit(901, hud.binder.local_uid(), "stupefy", [{"uid": uid, "amount": 40}])
		print("PHASE13 CAPTURE onboarding index after dummy witness: %d" % hud.onboarding.current_index)
	if dummy != null:
		player.set_target(dummy)
	await get_tree().create_timer(0.6).timeout
	_frame(Vector3(-9, 1.4, 2), Vector3(-2.5, 2.0, -2.0))
	await RenderingServer.frame_post_draw
	_save("phase13-onboarding.png")
	print("PHASE13 CAPTURE onboarding: step %d, %s" % [hud.onboarding.current_index, hud.onboarding._title.text])
	# Leave the saved route at the start: the capture staged its progress.
	hud.onboarding.reset()

## ---------------------------------------------------------------- settings

func _capture_settings() -> void:
	var hud = world.hud
	hud.settings.open()
	await get_tree().create_timer(0.3).timeout
	_save("phase13-settings.png")
	print("PHASE13 CAPTURE settings: open=%s" % hud.settings.is_open())
	hud.settings.close()

## ---------------------------------------------------------------- helpers

## Print every panel's rect: the layout evidence for the capture pass (each
## panel must be inside the viewport at this resolution).
func _report_layout() -> void:
	var size := get_viewport().get_visible_rect().size
	print("PHASE13 CAPTURE viewport: %s" % size)
	print("PHASE13 CAPTURE hud size=%s feedback size=%s onboarding size=%s" % [
		world.hud.size, world.hud.feedback.size, world.hud.onboarding.size])
	print("PHASE13 CAPTURE feedback anchors=(%.2f,%.2f,%.2f,%.2f) offsets=(%.1f,%.1f,%.1f,%.1f) parent=%s" % [
		world.hud.feedback.anchor_left, world.hud.feedback.anchor_top,
		world.hud.feedback.anchor_right, world.hud.feedback.anchor_bottom,
		world.hud.feedback.offset_left, world.hud.feedback.offset_top,
		world.hud.feedback.offset_right, world.hud.feedback.offset_bottom,
		world.hud.feedback.get_parent().size])
	var report: Dictionary = world.hud.layout_report()
	for key in report:
		var rect: Rect2 = report[key]
		var inside := rect.position.x >= 0.0 and rect.position.y >= 0.0 \
			and rect.end.x <= size.x and rect.end.y <= size.y
		print("PHASE13 CAPTURE layout %s: pos=(%d,%d) size=(%d,%d) inside=%s" % [
			key, rect.position.x, rect.position.y, rect.size.x, rect.size.y, inside])

## Stage one authoritative stat payload the way the server does: the record, the
## mirror node, then the wire signal. The HUD shows only what the payload says.
func _stage_stats(hud, values: Dictionary) -> void:
	var uid: int = hud.binder.local_uid()
	var stats := {
		"uid": uid, "hp": 500, "max_hp": 500, "mana": 300, "max_mana": 300,
		"exp": 0, "max_exp": 200, "level": 1, "galleons": 0,
		"dead": false, "mounted": false,
	}
	for key in values:
		stats[key] = values[key]
	var record: Dictionary = SimAuthority.entities.get(uid, {})
	if not record.is_empty():
		for key in ["hp", "max_hp", "mana", "max_mana", "exp", "level", "galleons"]:
			record[key] = stats[key]
	var player = world.local_player
	player.apply_authoritative_stats(stats)
	SimAuthority.stats_changed.emit(uid, stats)

func _frame(look_at_point: Vector3, from: Vector3) -> void:
	_camera.global_position = from
	_camera.look_at(look_at_point)
	_camera.current = true

func _save(name: String) -> void:
	var path := "%s/%s" % [OUT_DIR, name]
	var error := get_viewport().get_texture().get_image().save_png(path)
	print("PHASE13 CAPTURE %s: %s" % [name, error])
