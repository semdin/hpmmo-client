extends SceneTree

## height.raw (art/spider_caverns/out, float32, (cells+1)^2, row = +z) ->
## HeightMapShape3D resource the map's collider is built from on every process.
##
##   godot --headless --path client -s res://tools/maps/build_cavern_collision.gd -- <height.raw> <cells> <out.res>

func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 3:
		printerr("usage: -- <height.raw> <cells> <out.res>")
		quit(1)
		return
	var n := int(args[1]) + 1
	var bytes := FileAccess.get_file_as_bytes(args[0])
	if bytes.size() != n * n * 4:
		printerr("height.raw is %d bytes, expected %d" % [bytes.size(), n * n * 4])
		quit(1)
		return
	var shape := HeightMapShape3D.new()
	shape.map_width = n
	shape.map_depth = n
	shape.map_data = bytes.to_float32_array()
	var err := ResourceSaver.save(shape, args[2], ResourceSaver.FLAG_COMPRESS)
	print("[cavern_collision] %dx%d samples, min %.2f max %.2f -> %s (%s)" % [
		n, n, shape.get_min_height(), shape.get_max_height(), args[2], error_string(err)])
	quit(0 if err == OK else 1)
