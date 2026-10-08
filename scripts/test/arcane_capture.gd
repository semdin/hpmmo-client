extends Node

@onready var world = $GameWorld
const OUTPUT := "res://tools/downloads/arcane"
var failures := 0

func _ready() -> void:
	QuestManager.persistence_enabled = false
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUTPUT))
	await get_tree().create_timer(1.0).timeout
	var player = world.local_player
	player.global_position = Vector3(0,0.15,5)
	player.camera_rot_y = 0.3
	player.inventory.clear()
	for id in HPEquipment.catalog(): HPEquipment.add(player.inventory,id,0,3)
	HPEquipment.add(player.inventory,"wand_elder",6,1)
	player.galleons = 22874
	SimAuthority.refresh_equipment(SimAuthority.record_for(player))
	var args := OS.get_cmdline_user_args()
	var resolutions := [Vector2i(1280,720),Vector2i(1920,1080),Vector2i(2560,1440),Vector2i(3440,1440)]
	if "--quick" in args: resolutions = [Vector2i(1280,720)]
	for resolution in resolutions:
		get_window().size = resolution
		for scale in ([1.0,1.75,0.75] if "--quick" not in args else [1.0,1.75]):
			get_window().content_scale_factor = scale
			await _settle()
			var key := "%dx%d-%.2f" % [resolution.x,resolution.y,scale]
			world.inventory_ui.hide()
			await _shot(key+"-hud")
			var hotbar: Control = world.hud.get_node("BottomBar/Hotbar")
			var quick: Control = world.hud.get_node("BottomBar/QuickBar")
			check(not hotbar.get_global_rect().intersects(quick.get_global_rect()),key+" combat and shortcuts do not overlap")
			await _combat_shot(key)
			world.inventory_ui.open_for_player(player)
			await _settle()
			await _shot(key+"-equipment")
			var ui = world.inventory_ui
			var canvas := get_viewport().get_visible_rect()
			check(canvas.encloses(ui._window.get_global_rect()),key+" inventory window fits canvas")
			for slot in ui._doll_slots:
				check(canvas.encloses(slot.get_global_rect()),key+" gear slot "+slot.equipment_slot+" fits")
			if ui._compact:
				ui._tabs.current_tab = 1
				await _settle()
				await _shot(key+"-bag")
			ui._on_slot_entered(ui._bag_slots[0])
			await _settle()
			check(canvas.encloses(ui._tooltip.get_global_rect()),key+" tooltip fits canvas")
			ui._on_slot_exited(ui._bag_slots[0])
			ui.hide()
	print("ARCANE CAPTURE RESULT: %d failures" % failures)
	get_tree().quit(failures)

func check(ok: bool,message: String) -> void:
	if not ok: failures += 1
	print(("PASS: " if ok else "FAIL: ")+message)

func _settle() -> void:
	for i in 8: await get_tree().process_frame

func _shot(key: String) -> void:
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(OUTPUT+"/"+key+".png")
	print("CAPTURE %s image=%s canvas=%s" % [key,img.get_size(),get_viewport().get_visible_rect()])

func _combat_shot(key: String) -> void:
	var player = world.local_player
	var hud = world.hud
	var boss = get_tree().get_first_node_in_group("monoliths")
	player.set_target(boss)
	SimAuthority.cast_started.emit(hud.binder.local_uid(),9001,"incendio",Vector3.ZERO,SimAuthority.sim_tick+200)
	hud.feedback.show_feedback("Not enough mana",UITheme.c("blood_lt"))
	SimAuthority.reward_granted.emit(hud.binder.local_uid(),1,340,65,[{"id":"hat_apprentice","amount":1}],"arcane:"+key)
	await _settle()
	await _shot(key+"-combat")
	check(not hud.travel._location_label.get_global_rect().intersects(hud.target_panel.get_global_rect()),key+" location and target are separate")
	check(not hud.feedback._cast_panel.get_global_rect().intersects(hud.get_node("BottomBar/Hotbar").get_global_rect()),key+" cast bar clears spells")
	check(not hud.feedback._toast_panel.get_global_rect().intersects(hud.feedback._cast_panel.get_global_rect()),key+" rewards clear casting")
	player.set_target(null)
	hud.feedback.cast_id = 0
	hud.feedback._cast_panel.hide()
	hud.feedback._feedback_label.hide()
