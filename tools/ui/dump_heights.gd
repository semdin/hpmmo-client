extends Node
## Samples the grounds terrain on a 1024 x 1024 grid (2 m cells over the 2 x 2 km
## map) and writes raw float32 heights for tools/ui/paint_world_map.py.
##   godot --headless --path client res://tools/ui/dump_heights.tscn -- /tmp/heights.bin
func _ready() -> void:
	var t: Node = load("res://scenes/world/grounds_terrain.tscn").instantiate()
	add_child(t)
	await get_tree().process_frame
	await get_tree().process_frame
	var n := 1024
	var buf := PackedFloat32Array()
	buf.resize(n * n)
	for zi in range(n):
		for xi in range(n):
			var x := -1024.0 + (xi + 0.5) * 2.0
			var z := -1024.0 + (zi + 0.5) * 2.0
			var h: float = GroundsTerrain.height_at(x, z)
			buf[zi * n + xi] = -100.0 if is_nan(h) else h
	var f := FileAccess.open(OS.get_cmdline_user_args()[0] if OS.get_cmdline_user_args().size() > 0 else "user://heights.bin", FileAccess.WRITE)
	f.store_buffer(buf.to_byte_array())
	f.close()
	print("DUMP_DONE")
	get_tree().quit()
