extends RefCounted

## Bakes the far band of the grounds' trees (GroundsImpostors) from the cooked
## vegetation: build_grounds.gd runs it after cooking and copying the scatter;
## tools/terrain/bake_impostors_run.gd runs it alone.
##
## Writes, next to the cooked vegetation (client-only, never exported to the
## world server):
##   impostor_alb.png / impostor_nrm.png   every variant's impostor texture as
##       one SLICE x SLICE slice of a vertical strip, imported as a
##       Texture2DArray (slice = variant index)
##   impostors.json   per variant: name, card width / height, tint, the near
##       and far catalogue ranges (vegetation.json "lod" [1] and [2])
##   impostor_tiles.bin   one ready MultiMesh buffer per TILE x TILE metre tile
##       (see GroundsImpostors for the layout)
##
## A variant gets the band when its cooked last LOD is an impostor card
## (material `<variant>_impostor`): the card mesh and material stay on disk as
## the bake's source, but the variant's scene carries only LOD0 and LOD1
## (cook_vegetation.gd), so Terrain3D draws nothing past LOD1.

const VEG_DIR := "res://assets/terrain/vegetation/"
const SCATTER_DIR := "res://assets/terrain/grounds/scatter/"
## Texels per slice side. Past the near range (66-78 m on low, 110-130 m on
## high) a 20 m tree is ~220 px tall at 1080p, so 512 (two 256 px views side by
## side) keeps the detail the 1024 px sources had there.
const SLICE := 512
const TILE := 256.0
## Terrain3D's instancer cell (Terrain3DInstancer CELL_SIZE at 1 m vertex spacing).
const CELL := 32.0


## `catalog` is the parsed art/map/vegetation.json. Returns the variants baked.
static func bake(catalog: Dictionary) -> Array:
	var variants: Dictionary = catalog.get("variants", {})
	var names: Array = []
	for name in variants:
		if _impostor_mesh(String(name)) != null:
			names.append(String(name))
	if names.is_empty():
		push_error("bake_impostors: no variant has an impostor LOD")
		return names
	var alb := Image.create_empty(SLICE, SLICE * names.size(), false, Image.FORMAT_RGBA8)
	var nrm := Image.create_empty(SLICE, SLICE * names.size(), false, Image.FORMAT_RGB8)
	var entries: Array = []
	var lod0_boxes: Array = []
	for v in names.size():
		var name: String = names[v]
		var card := _impostor_mesh(name)
		var mat := card.surface_get_material(0) as StandardMaterial3D
		alb.blit_rect(_slice(mat.albedo_texture, true), Rect2i(0, 0, SLICE, SLICE), Vector2i(0, v * SLICE))
		nrm.blit_rect(_slice(mat.normal_texture, false), Rect2i(0, 0, SLICE, SLICE), Vector2i(0, v * SLICE))
		var box := card.get_aabb()
		var lods: Array = variants[name].get("lod", [40, 120, 600])
		entries.append({
			"name": name,
			"width": snappedf(box.size.x, 0.0001),
			"height": snappedf(box.size.y, 0.0001),
			"tint": [snappedf(mat.albedo_color.r, 0.001), snappedf(mat.albedo_color.g, 0.001), snappedf(mat.albedo_color.b, 0.001)],
			"near": float(lods[1]),
			"far": float(lods[2]),
		})
		lod0_boxes.append((load("%s%s_lod0.res" % [VEG_DIR, name]) as Mesh).get_aabb())
	alb.save_png(ProjectSettings.globalize_path(VEG_DIR + "impostor_alb.png"))
	nrm.save_png(ProjectSettings.globalize_path(VEG_DIR + "impostor_nrm.png"))
	for file in ["impostor_alb.png", "impostor_nrm.png"]:
		_write_import(VEG_DIR + file, names.size())
	var json := {"slice": SLICE, "tile": TILE, "variants": entries}
	var f := FileAccess.open(VEG_DIR + "impostors.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(json, "\t") + "\n")
	f.close()
	_write_tiles(names, entries, lod0_boxes)
	return names


## True when `variant` has a cooked impostor card (its far band is baked).
static func is_banded(variant: String) -> bool:
	return _impostor_mesh(variant) != null


## The variant's impostor card (its cooked last LOD), or null.
static func _impostor_mesh(variant: String) -> ArrayMesh:
	for lod in [3, 2]:
		var path := "%s%s_lod%d.res" % [VEG_DIR, variant, lod]
		if not ResourceLoader.exists(path):
			continue
		var mesh := load(path) as ArrayMesh
		var mat := mesh.surface_get_material(0) if mesh.get_surface_count() == 1 else null
		if mat != null and mat.resource_name.ends_with("_impostor"):
			return mesh
		return null
	return null


## One slice from a source texture's PNG (the lossless source, not the
## imported copy). Albedo: transparent texels take their neighbours' colour
## first, so the mips and the shrink do not bleed black into the edges.
static func _slice(tex: Texture2D, albedo: bool) -> Image:
	var img := Image.load_from_file(ProjectSettings.globalize_path(tex.resource_path))
	img.convert(Image.FORMAT_RGBA8 if albedo else Image.FORMAT_RGB8)
	if albedo:
		img.fix_alpha_edges()
	img.resize(SLICE, SLICE, Image.INTERPOLATE_LANCZOS)
	return img


static func _write_import(res_path: String, slices: int) -> void:
	var text := """[remap]

importer="2d_array_texture"
type="CompressedTexture2DArray"

[deps]

source_file="%s"

[params]

compress/mode=2
compress/high_quality=false
compress/lossy_quality=0.7
compress/hdr_compression=1
compress/channel_pack=0
mipmaps/generate=true
mipmaps/limit=-1
slices/horizontal=1
slices/vertical=%d
""" % [res_path, slices]
	var path := ProjectSettings.globalize_path(res_path + ".import")
	if FileAccess.file_exists(path) and FileAccess.get_file_as_string(path).contains("slices/vertical=%d" % slices):
		return
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(text)
	f.close()


## impostor_tiles.bin: int32 tile count, then per tile int32 tile x, int32
## tile z, int32 instance count and count x 16 float32 - the MultiMesh buffer
## (3x4 transform rows, then INSTANCE_CUSTOM). The transform is the tree's,
## with the unit card scaled to the variant's width / height. The custom data
## is the centre of the Terrain3D multimesh the tree belongs to (xyz, the AABB
## of its 32 m cell's LOD0 instances - the point Godot measures that
## multimesh's visibility range from) and the variant index (w), so the band
## starts exactly where Terrain3D's LOD1 of that cell ends.
static func _write_tiles(names: Array, entries: Array, lod0_boxes: Array) -> void:
	var cells := {}
	var trees: Array = []
	for v in names.size():
		var data := FileAccess.get_file_as_bytes(SCATTER_DIR + names[v] + ".bin").to_float32_array()
		for k in data.size() / 5:
			var xf := _transform_of(data, k)
			var key := Vector3i(v, floori(xf.origin.x / CELL), floori(xf.origin.z / CELL))
			var box: AABB = xf * (lod0_boxes[v] as AABB)
			cells[key] = (cells[key] as AABB).merge(box) if cells.has(key) else box
			trees.append([v, xf, key])
	var tiles := {}
	for t in trees:
		var v: int = t[0]
		var xf: Transform3D = t[1]
		var e: Dictionary = entries[v]
		var b := xf.basis * Basis.from_scale(Vector3(e.width, e.height, e.width))
		var c: Vector3 = (cells[t[2]] as AABB).get_center()
		var tile := Vector2i(floori(xf.origin.x / TILE), floori(xf.origin.z / TILE))
		var buf: PackedFloat32Array = tiles.get_or_add(tile, PackedFloat32Array())
		buf.append_array([b.x.x, b.y.x, b.z.x, xf.origin.x, b.x.y, b.y.y, b.z.y, xf.origin.y,
			b.x.z, b.y.z, b.z.z, xf.origin.z, c.x, c.y, c.z, float(v)])
		tiles[tile] = buf
	var keys := tiles.keys()
	keys.sort()
	var f := FileAccess.open(VEG_DIR + "impostor_tiles.bin", FileAccess.WRITE)
	f.store_32(keys.size())
	for tile in keys:
		var buf: PackedFloat32Array = tiles[tile]
		f.store_32(tile.x)
		f.store_32(tile.y)
		f.store_32(buf.size() / 16)
		f.store_buffer(buf.to_byte_array())
	f.close()


## GroundsScatter.transform_of (kept here so the tool does not depend on the
## game's class cache).
static func _transform_of(data: PackedFloat32Array, i: int) -> Transform3D:
	var o := i * 5
	var s := data[o + 4]
	return Transform3D(Basis(Vector3.UP, data[o + 3]).scaled(Vector3(s, s, s)),
		Vector3(data[o], data[o + 1], data[o + 2]))
