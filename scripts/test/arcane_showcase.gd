extends Control

func _ready() -> void:
	theme = UITheme.get_theme()
	var backdrop := ColorRect.new()
	backdrop.color = Color("090f1a")
	backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(backdrop)
	var window := UIWindow.new("ARCANE / COMPONENT SHOWCASE",Vector2(840,510))
	add_child(window)
	window.theme_type_variation = &"ArcaneWindow"
	window._ribbon.add_theme_stylebox_override("panel",ArcaneSkin.surface())
	ArcaneSkin.decorate(window)
	window.place_centred(Vector2(840,510))
	window.body.add_child(UITheme.heading("MIDNIGHT BLUE · AGED GOLD",22))
	window.body.add_child(UITheme.body("Shared geometry, responsive containers, artwork only where it adds character.",16))
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation",12)
	window.body.add_child(row)
	for state in ["normal","hover","pressed","disabled","focus"]:
		var column := VBoxContainer.new()
		row.add_child(column)
		column.add_child(UITheme.body(state.capitalize(),13))
		var button := Button.new()
		button.text = "Equip"
		button.theme_type_variation = &"ArcaneButton"
		button.custom_minimum_size = Vector2(132,38)
		button.add_theme_stylebox_override("normal",theme.get_stylebox(state,"ArcaneButton"))
		column.add_child(button)
	var slots := HBoxContainer.new()
	slots.add_theme_constant_override("separation",10)
	window.body.add_child(slots)
	for id in ["wand_hawthorn","hat_apprentice","gloves_apprentice","boots_apprentice","focus_apprentice","pendant_apprentice","ring_apprentice","ring_adept"]:
		var slot := UISlot.new(Vector2(62,62))
		slots.add_child(slot)
		slot.theme_type_variation = &"ArcaneSlot"
		slot.set_item(id,{"id":id,"amount":1,"tier":0})
	var map := TextureRect.new()
	map.texture = ArcaneSkin.texture("minimap")
	map.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	map.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	map.custom_minimum_size = Vector2(160,160)
	map.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	window.body.add_child(map)
	window.body.add_child(UITheme.body("15–16 px body text · 13 px secondary labels · Cyan focus · Gameplay colors reserved for state",15))

	if "--capture" in OS.get_cmdline_user_args():
		for i in 12: await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png("res://tools/downloads/arcane/component-showcase.png")
		print("ARCANE SHOWCASE CAPTURED")
		get_tree().quit()
