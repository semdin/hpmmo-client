extends Node

## Screenshots the out-of-game front end (main menu + character select) so the
## menu styling can be reviewed the same way the in-game panels are.
##   godot --path client res://scenes/test/ui_menu_capture.tscn

@onready var menu := $MainMenu

func _ready() -> void:
	await get_tree().create_timer(1.4).timeout
	await _shot("menu-auth")
	var select_panel := menu.get_node_or_null("CharSelectPanel")
	if select_panel != null:
		menu.get_node("AuthPanel").hide()
		select_panel.show()
		await get_tree().create_timer(0.6).timeout
		await _shot("menu-charselect")
	get_tree().quit()

func _shot(subject: String) -> void:
	await RenderingServer.frame_post_draw
	var err := get_viewport().get_texture().get_image().save_png("res://tools/downloads/ui-%s.png" % subject)
	print("CAPTURE ui-%s: %s" % [subject, err])
