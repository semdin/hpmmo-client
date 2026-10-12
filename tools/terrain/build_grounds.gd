extends SceneTree

## Builds the outdoor terrain (the "grounds" map) for Terrain3D from the map
## pipeline's raw output, and writes the terrain's texture set.
##
##   godot --headless --path . -s tools/terrain/build_grounds.gd -- [--src <dir>]
##
## <dir> holds height.raw and control.raw written by art/map/scripts
## (heightfield.py, control.py), default ../art/map/out. Both are 2048x2048,
## little-endian 32-bit, row = +z, column = +x, starting at world (-1024, -1024):
## height in metres (lake surface = 0 m), control as Terrain3D's packed control
## words. Writes:
##   assets/terrain/grounds/data/   Terrain3D regions (heights, control, collision source)
##   assets/terrain/grounds_assets.tres    the 8 ground textures
## assets/terrain/grounds_material.tres (shader settings) is hand-authored:
## the headless renderer has no shader to hold parameters, so it is not written here.
## The scene scenes/world/grounds_terrain.tscn points at all three.

const SIZE := 2048
const ORIGIN := Vector3(-1024.0, 0.0, -1024.0)
const DATA_DIR := "res://assets/terrain/grounds/data"
const ASSETS_PATH := "res://assets/terrain/grounds_assets.tres"
const TEX_DIR := "res://assets/terrain/textures/"

## Slot order is the contract with art/map/scripts/control.py.
## [name, texture set, uv_scale, detiling rotation, albedo tint, normal depth, roughness offset]
const SLOTS := [
	["grass_meadow", "grass_meadow", 0.16, 0.20, Color(0.52, 0.60, 0.48), 1.0, 0.0],
	["cliff_rock", "cliff_rock", 0.06, 0.12, Color(0.60, 0.58, 0.56), 1.2, 0.0],
	["forest_floor", "forest_floor", 0.22, 0.30, Color(0.52, 0.46, 0.36), 1.0, 0.05],
	["sand_shore", "sand_shore", 0.20, 0.25, Color(0.92, 0.88, 0.80), 0.8, 0.0],
	["gravel", "gravel", 0.30, 0.25, Color(0.80, 0.78, 0.76), 1.0, 0.0],
	# No dedicated dirt set yet: the sand set, tinted to packed earth.
	["dirt_path", "sand_shore", 0.24, 0.25, Color(0.70, 0.58, 0.45), 1.0, 0.05],
	["cobblestone", "cobblestone", 0.35, 0.0, Color(0.82, 0.80, 0.78), 1.2, 0.0],
	["grass_lush", "grass_lush", 0.18, 0.20, Color(0.48, 0.56, 0.42), 1.0, 0.0],
	# Highland grass: the meadow set dried to a tawny moor colour.
	["moor_grass", "grass_meadow", 0.14, 0.20, Color(0.56, 0.54, 0.42), 1.0, 0.05],
]


func _initialize() -> void:
	_build.call_deferred()


func _src_dir() -> String:
	var args := OS.get_cmdline_user_args()
	var i := args.find("--src")
	if i >= 0 and i + 1 < args.size():
		return args[i + 1]
	return ProjectSettings.globalize_path("res://").path_join("../art/map/out").simplify_path()


func _load_raw(path: String) -> Image:
	var bytes := FileAccess.get_file_as_bytes(path)
	if bytes.size() != SIZE * SIZE * 4:
		push_error("build_grounds: %s is %d bytes, expected %d" % [path, bytes.size(), SIZE * SIZE * 4])
		return null
	return Image.create_from_data(SIZE, SIZE, false, Image.FORMAT_RF, bytes)


func _build() -> void:
	var t0 := Time.get_ticks_msec()
	var src := _src_dir()
	var height := _load_raw(src.path_join("height.raw"))
	var control := _load_raw(src.path_join("control.raw"))
	if height == null or control == null:
		quit(1)
		return

	var terrain := Terrain3D.new()
	root.add_child(terrain)
	await process_frame
	terrain.region_size = 1024
	terrain.assets = _make_assets()
	terrain.data.import_images([height, control, null], ORIGIN, 0.0, 1.0)

	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(DATA_DIR))
	for f in DirAccess.get_files_at(DATA_DIR):
		if f.ends_with(".res"):
			DirAccess.remove_absolute(ProjectSettings.globalize_path(DATA_DIR.path_join(f)))
	terrain.data.save_directory(DATA_DIR)
	_check(ResourceSaver.save(terrain.assets, ASSETS_PATH), ASSETS_PATH)

	var probes := {"castle_plateau": Vector3(0, 0, -20), "courtyard": Vector3(0, 0, 65),
		"hogsmeade": Vector3(680, 0, -140), "lake_middle": Vector3(0, 0, 330), "highlands": Vector3(280, 0, -760)}
	var report := []
	for k in probes:
		report.append("%s=%.1f" % [k, terrain.data.get_height(probes[k])])
	print("BUILD_GROUNDS ok regions=%d ms=%d  %s" % [terrain.data.get_region_count(), Time.get_ticks_msec() - t0, "  ".join(report)])
	quit(0)


func _check(err: int, path: String) -> void:
	if err != OK:
		push_error("build_grounds: could not save %s (%d)" % [path, err])


func _make_assets() -> Terrain3DAssets:
	var assets := Terrain3DAssets.new()
	for i in SLOTS.size():
		var s: Array = SLOTS[i]
		var ta := Terrain3DTextureAsset.new()
		ta.name = s[0]
		ta.id = i
		ta.albedo_texture = load(TEX_DIR + s[1] + "_alb_ht.png")
		ta.normal_texture = load(TEX_DIR + s[1] + "_nrm_rgh.png")
		ta.uv_scale = s[2]
		ta.detiling_rotation = s[3]
		ta.albedo_color = s[4]
		ta.normal_depth = s[5]
		ta.roughness = s[6]
		ta.ao_strength = 1.5
		assets.set_texture(i, ta)
	return assets

