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
	await _capture_tooltip("robe_apprentice", "tooltip-cloak")
	await _capture_tooltip("focus_emberwing", "tooltip-focus-t4")
	await _capture_tooltip("ring_moonveil", "tooltip-ring-t5")
	await _capture_skills()
	await _capture_chest()
	await _capture_windows()

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
		["wand_runebound", 1, 0, [{"stat": "spell_power", "value": 6, "grade": 2}, {"stat": "crit_chance", "value": 2, "grade": 1}]],
		["wand_elder", 1, 6],
		["robe_apprentice", 1, 0],
		["broom_nimbus2000", 1, 0],
		["potion_health", 5, 0],
		["potion_mana", 3, 0],
		["mat_phoenix_ash", 12, 0],
		["mat_dragon_heartstring", 4, 0],
		["mat_thestral_hair", 2, 0],
		["mat_elder_core", 1, 0],
	] + _tier_accessories():
		var id: String = spec[0]
		if not GameData.ITEMS.has(id):
			continue
		if HPEquipment.stackable(id):
			player.inventory.append({"id": id, "amount": int(spec[1]), "tier": int(spec[2])})
		else:
			player.inventory.append(HPEquipment.instance(id, int(spec[2]), spec[3] if spec.size() > 3 else []))
	player.galleons = 22874
	player.emit_stats()
	player.inventory_changed.emit()


## Every T2-T5 accessory (hat/gloves/boots/focus/pendant/ring x runebound..moonveil),
## so the bag shot shows their icons.
func _tier_accessories() -> Array:
	var out: Array = []
	for kind in ["hat", "gloves", "boots", "focus", "pendant", "ring"]:
		for tier in ["runebound", "silverthorn", "emberwing", "moonveil"]:
			out.append([kind + "_" + tier, 1, 0])
	return out


func _capture_inventory() -> void:
	var player = _stage_player()
	world.inventory_ui.open_for_player(player)
	await get_tree().create_timer(0.8).timeout
	await _shot("inventory")
	# The merchant beside it, pricing an enchanted wand.
	ui_merchant_offer(player)
	await get_tree().create_timer(0.5).timeout
	await _shot("merchant")


func ui_merchant_offer(player) -> void:
	var ui = world.inventory_ui
	ui._set_merchant_open(true)
	for entry in player.inventory:
		if not (entry.get("bonuses", []) as Array).is_empty():
			ui._offer(entry)
			return


func _capture_tooltip(item_id := "wand_elder", subject := "tooltip") -> void:
	var ui = world.inventory_ui
	var slot: UISlot = null
	for candidate in ui._bag_slots:
		if candidate.item_id == item_id:
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
	if at.x + ui._tooltip.size.x > get_viewport().get_visible_rect().size.x:
		at.x = slot.global_position.x - ui._tooltip.size.x - 14   # the bag sits at the right edge
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
	await _shot(subject)


## The skill window (V) and the action-bar level badges, with a Master skill,
## trained skills and points left to spend - staged through the authority.
func _capture_skills() -> void:
	world.inventory_ui.hide()
	var player = world.local_player
	var record: Dictionary = SimAuthority.record_for(player)
	record["level"] = 22
	record["skill_levels"] = {"stupefy": 10, "incendio": 6, "bombarda": 3, "protego": 2}
	SimAuthority._push_stats(record)
	world.hud.skill_window.open()
	await get_tree().create_timer(0.6).timeout
	await _shot("skills")


## Two loot chests beside the player (plain gold glow, enchanted violet) and
## the chest window opened on the enchanted one - staged through the authority.
func _capture_chest() -> void:
	world.hud.skill_window.close()
	var player = world.local_player
	var at: Vector3 = player.global_position + Vector3(0, 0, -3.0)
	SimAuthority._spawn_chest([{"id": "galleons", "amount": 64}, {"id": "potion_health", "amount": 1}], at + Vector3(-1.6, 0, 0))
	SimAuthority._spawn_chest([{"id": "galleons", "amount": 88}, {"id": "mat_phoenix_ash", "amount": 2},
		{"id": "wand_runebound", "amount": 1, "bonuses": [{"stat": "spell_power", "value": 6, "grade": 2}, {"stat": "crit_chance", "value": 2, "grade": 1}]}],
		at + Vector3(1.6, 0, 0))
	await get_tree().create_timer(0.6).timeout
	var rare: Node3D = null
	for node in get_tree().get_nodes_in_group("loot"):
		if node.get("item_id") == "chest_rare":
			rare = node
	if rare != null:
		world.loot_window.open_chest(rare)
	await get_tree().create_timer(0.6).timeout
	await _shot("chest")


## The HUD windows (B bestiary, M map), Ollivander and an NPC dialogue.
func _capture_windows() -> void:
	world.loot_window.close()
	world.inventory_ui.hide()
	world.hud.bestiary.open()
	await get_tree().create_timer(0.6).timeout
	await _shot("bestiary")
	world.hud.bestiary.close()
	world.hud.world_map.open()
	await get_tree().create_timer(0.6).timeout
	await _shot("map")
	world.hud.world_map.close()
	world.hud.character_window.open()
	await get_tree().create_timer(0.6).timeout
	await _shot("character")
	world.hud.character_window.close()
	world.ollivander_ui.open_for_player(world.local_player)
	for entry in world.local_player.inventory:
		if not (entry.get("bonuses", []) as Array).is_empty():
			world.ollivander_ui.set_target(int(entry.get("uid", 0)))
	await get_tree().create_timer(0.6).timeout
	await _shot("ollivander")
	world.ollivander_ui.hide()
	world.inventory_ui.hide()
	var fig: Node = null
	for npc in get_tree().get_nodes_in_group("npcs"):
		if String(npc.get("npc_name")) == "Professor Fig":
			fig = npc
	if fig != null:
		world.overlay.show_dialogue(fig.npc_name, fig.talk(world.local_player))
		await get_tree().create_timer(0.6).timeout
		await _shot("dialogue")
		world.overlay._dialog_panel.hide()
	# The target ring under the nearest targetable thing, moved in front of us.
	var player = world.local_player
	var best: Node3D = null
	for node in get_tree().get_nodes_in_group("targetable"):
		if node is Node3D and node != player and (best == null or node.global_position.distance_to(player.global_position) < best.global_position.distance_to(player.global_position)):
			best = node
	if best != null:
		player.global_position = best.global_position + Vector3(0, 0, 6)
		player.camera_rot_y = 0
		player.set_target(best)
		await get_tree().create_timer(0.8).timeout
		var ring = world.get_node_or_null("TargetRing")
		print("DIAG ring target=%s at=%s ring_visible=%s ring_pos=%s scale=%s" % [best.name, best.global_position, ring.visible if ring else "none", ring.global_position if ring else Vector3.ZERO, ring.scale if ring else Vector3.ZERO])
		await _shot("target-ring")


func _shot(subject: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var error := img.save_png("%s/ui-%s.png" % [OUT_DIR, subject])
	print("CAPTURE ui-%s: %s" % [subject, error])
