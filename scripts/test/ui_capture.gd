extends Node

## UI capture harness - visual evidence for the interface redesign.
##
## Runs windowed (a real renderer is required; nothing here draws headless):
##
##   godot --path client res://scenes/test/ui_capture.tscn
##
## Every shot lands in res://tools/downloads/ui-<subject>.png.
##
## The panels are staged through the same entry points the game uses -
## `inventory_ui.open_for_player`, `player.add_loot`, real `GameData.ITEMS`
## records - never by writing widget text directly, so a shot is evidence the
## binding works rather than a picture of a mock-up.

const OUT_DIR := "res://tools/downloads"

@onready var world = $GameWorld

var _camera: Camera3D


func _ready() -> void:
	await get_tree().create_timer(1.8).timeout
	_camera = Camera3D.new()
	_camera.fov = 65.0
	world.add_child(_camera)

	await _capture_inventory()
	await _capture_tooltip()

	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()


## Put the player somewhere photogenic and stock a full bag.
func _stage_player() -> Node3D:
	var player = world.local_player
	player.global_position = Vector3(0, 0.15, -30)
	player.camera_rot_y = 0
	player.camera.current = true
	_stock_inventory(player)
	return player


func _stock_inventory(player) -> void:
	player.inventory.clear()
	for spec in [
		["wand_hawthorn", 1, 3],
		["wand_elder", 1, 6],
		["robe_apprentice", 1, 0],
		["broom_nimbus2000", 1, 0],
		["potion_health", 5, 0],
		["potion_mana", 3, 0],
		["mat_phoenix_ash", 12, 0],
		["mat_dragon_heartstring", 4, 0],
		["mat_thestral_hair", 2, 0],
		["mat_elder_core", 1, 0],
	]:
		var id: String = spec[0]
		if not GameData.ITEMS.has(id):
			continue
		player.inventory.append({"id": id, "amount": int(spec[1]), "tier": int(spec[2])})
	player.galleons = 22874
	player.emit_stats()
	player.inventory_changed.emit()


func _capture_inventory() -> void:
	var player = _stage_player()
	world.inventory_ui.open_for_player(player)
	await get_tree().create_timer(0.8).timeout
	await _shot("inventory")


func _capture_tooltip() -> void:
	var ui = world.inventory_ui
	var slot: UISlot = null
	for candidate in ui._bag_slots:
		if candidate.item_id == "wand_elder":
			slot = candidate
			break
	if slot == null:
		for candidate in ui._bag_slots:
			if candidate.item_id != "":
				slot = candidate
				break
	if slot == null:
		return

	# Park the card beside the cell instead of at the (unmoved) cursor, so the
	# shot frames the tooltip and its slot together.
	ui._on_slot_entered(slot)
	ui.set_process(false)
	ui._tooltip.set_process(false)
	var at: Vector2 = slot.global_position + Vector2(slot.size.x + 14, -30)
	print("DIAG tooltip rect=%s size=%s z=%d visible=%s parent=%s sb=%s" % [
		ui._tooltip.global_position, ui._tooltip.size, ui._tooltip.z_index,
		ui._tooltip.visible, ui._tooltip.get_parent().name,
		ui._tooltip.get_theme_stylebox("panel")])
	var delta: Vector2 = at - ui._tooltip.global_position
	ui._tooltip.offset_left += delta.x
	ui._tooltip.offset_right += delta.x
	ui._tooltip.offset_top += delta.y
	ui._tooltip.offset_bottom += delta.y
	await get_tree().create_timer(0.5).timeout
	await _shot("tooltip")


func _shot(subject: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var error := img.save_png("%s/ui-%s.png" % [OUT_DIR, subject])
	print("CAPTURE ui-%s: %s" % [subject, error])
