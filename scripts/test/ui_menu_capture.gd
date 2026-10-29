extends Node

## Screenshots the out-of-game front end (the login screen, plain and with the
## maintenance notice) so the menu styling can be reviewed the same way the
## in-game panels are.
##   godot --path client res://scenes/test/ui_menu_capture.tscn

@onready var menu := $MainMenu

func _ready() -> void:
	await get_tree().create_timer(1.4).timeout
	await _shot("menu-auth")
	menu.call("_set_mode", true)
	await get_tree().create_timer(0.3).timeout
	await _shot("menu-register")
	menu.call("_set_mode", false)
	menu.set("server_state", "MAINTENANCE")
	menu.call("_render_server_state")
	menu.call("_show_maintenance_notice", true)
	menu.call("_set_status", "Sunucu şu an bakımda. Lütfen biraz sonra tekrar dene.", "warn")
	await get_tree().create_timer(0.3).timeout
	await _shot("menu-maintenance")
	# The character screen and its create card (run with --resolution 1280x800
	# to see a 16:10 laptop).
	menu.queue_free()
	var select: Node = load("res://scenes/main/character_select.tscn").instantiate()
	add_child(select)
	await get_tree().create_timer(1.0).timeout
	await _shot("charselect")
	select.call("_on_new_char_pressed")
	await get_tree().create_timer(0.4).timeout
	await _shot("charselect-create")
	# the appearance editor drives the podium wizard live
	var editor: LookEditor = select.get("_look_editor")
	editor.set_look({"hair": 1, "hair_color": 5, "eyes": 2, "skin": 3, "outfit": 1, "height": 0.6}, true)
	await get_tree().create_timer(0.6).timeout
	await _shot("charselect-look")
	get_tree().quit()

func _shot(subject: String) -> void:
	await RenderingServer.frame_post_draw
	var err := get_viewport().get_texture().get_image().save_png("res://tools/downloads/ui-%s.png" % subject)
	print("CAPTURE ui-%s: %s" % [subject, err])
