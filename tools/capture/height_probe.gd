extends Node

## Terrain heights over world rectangles, for site planning (layout reviews).
##   godot --path . tools/capture/height_probe.tscn -- --rects=<json> --out=<file.json>
## rects.json: [["name", x0, z0, x1, z1, step], ...]; out: {name: {x0, z0, step, w, h, y: [...]}}
## (row-major from (x0, z0); NaN where there is no terrain written as null).

@onready var world = $GameWorld

func _ready() -> void:
	var rects_path := ""
	var out_path := "user://height_probe.json"
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--rects="):
			rects_path = arg.trim_prefix("--rects=")
		elif arg.begins_with("--out="):
			out_path = arg.trim_prefix("--out=")
	var rects = JSON.parse_string(FileAccess.get_file_as_string(rects_path)) if rects_path != "" else null
	if not rects is Array:
		printerr("height_probe: --rects=<json array of [name, x0, z0, x1, z1, step]>")
		get_tree().quit(1)
		return
	await get_tree().create_timer(1.5).timeout
	var out := {}
	for r in rects:
		var step := float(r[5])
		var w := int((float(r[3]) - float(r[1])) / step) + 1
		var h := int((float(r[4]) - float(r[2])) / step) + 1
		var ys: Array = []
		for j in h:
			for i in w:
				var y := GroundsTerrain.height_at(float(r[1]) + i * step, float(r[2]) + j * step)
				ys.append(null if is_nan(y) else snappedf(y, 0.1))
		out[String(r[0])] = {"x0": r[1], "z0": r[2], "step": step, "w": w, "h": h, "y": ys}
	var f := FileAccess.open(out_path, FileAccess.WRITE)
	f.store_string(JSON.stringify(out))
	f.close()
	print("HEIGHT PROBE written %s" % ProjectSettings.globalize_path(out_path))
	get_tree().quit()
