extends SceneTree

## Asset baker — run once to write real PNG textures to assets/textures/.
## godot --headless --path . -s tools/generate_assets.gd

func _init() -> void:
	var out_dir := "assets/textures"
	DirAccess.make_dir_recursive_absolute(out_dir)
	_bake("grass.png", Color(0.23, 0.42, 0.20), Color(0.13, 0.28, 0.12), 256, 10, 11)
	_bake("cobble.png", Color(0.52, 0.51, 0.53), Color(0.30, 0.29, 0.31), 256, 8, 21)
	_bake("castle_wall.png", Color(0.62, 0.58, 0.52), Color(0.38, 0.35, 0.32), 256, 9, 31)
	_bake("castle_roof.png", Color(0.25, 0.32, 0.45), Color(0.12, 0.16, 0.26), 256, 8, 41)
	_bake("wood.png", Color(0.45, 0.30, 0.16), Color(0.24, 0.15, 0.08), 256, 6, 51)
	_bake("bark.png", Color(0.33, 0.22, 0.13), Color(0.15, 0.10, 0.06), 256, 9, 52)
	_bake("leaves.png", Color(0.16, 0.38, 0.14), Color(0.07, 0.20, 0.08), 256, 10, 61)
	_bake("obsidian.png", Color(0.16, 0.07, 0.22), Color(0.05, 0.02, 0.08), 256, 7, 91)
	print("ASSETS BAKED to assets/textures/")
	quit(0)

func _bake(fname: String, base: Color, variation: Color, size: int, cells: int, seed_val: int) -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_val
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var cell := size / cells
	for y in range(size):
		for x in range(size):
			var cx := int(x / cell)
			var cy := int(y / cell)
			var h: float = abs(fmod(float((cx * 73856093) ^ (cy * 19349663) ^ (seed_val * 83492791)), 1000.0)) / 1000.0
			var grain := rng.randf_range(-0.08, 0.08)
			var t: float = clamp(h * 0.65 + grain + 0.18 * sin(float(x) * 0.35) * cos(float(y) * 0.3), 0.0, 1.0)
			img.set_pixel(x, y, base.lerp(variation, t))
	img.save_png("assets/textures/" + fname)
