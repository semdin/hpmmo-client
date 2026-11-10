extends SceneTree

## Re-bakes the trees' far band alone (bake_impostors.gd), without rebuilding
## the grounds:
##   godot --headless --path client -s tools/terrain/bake_impostors_run.gd [-- --catalog=<vegetation.json>]
## then `godot --headless --path client --import` for the texture arrays.
## The catalogue defaults to art/map/vegetation.json beside the client.

const Impostors = preload("res://tools/terrain/bake_impostors.gd")


func _initialize() -> void:
	var src := ProjectSettings.globalize_path("res://").path_join("../art/map/vegetation.json").simplify_path()
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--catalog="):
			src = arg.trim_prefix("--catalog=")
	var catalog = JSON.parse_string(FileAccess.get_file_as_string(src))
	if not catalog is Dictionary:
		printerr("bake_impostors_run: cannot read %s" % src)
		quit(1)
		return
	var names := Impostors.bake(catalog)
	print("bake_impostors: %d variants %s" % [names.size(), str(names)])
	quit(0 if not names.is_empty() else 1)
