extends RefCounted

## Cooks the vegetation / rock models (assets/models/vegetation/*.glb, exported
## by art/vegetation/scripts) into game scenes for the Terrain3D instancer:
##   assets/terrain/vegetation/<variant>.tscn   Node3D with LOD0, LOD1 (, LOD2) MeshInstance3Ds
##   assets/terrain/vegetation/<variant>_lod<i>.res, <model>_<surface>.tres
## Called by build_grounds.gd with the parsed vegetation.json.
##
## What cooking does: the glTF materials become game materials. Foliage cards and
## impostors: alpha scissor with alpha-to-coverage (no shimmering under MSAA),
## both sides lit, soft wrap lighting and backlight so a canopy reads as a volume,
## species tint. Wood and rock keep their scan textures with a tint.

const MODEL_DIR := "res://assets/models/vegetation/"
const OUT_DIR := "res://assets/terrain/vegetation/"


static func cook_all(catalog: Dictionary) -> Dictionary:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT_DIR))
	var scenes := {}
	var variants: Dictionary = catalog.get("variants", {})
	for name in variants:
		var path := cook(String(name), variants[name])
		if path != "":
			scenes[name] = path
	return scenes


static func cook(variant: String, spec: Dictionary) -> String:
	var model_path := MODEL_DIR + String(spec.get("model", variant)) + ".glb"
	if not ResourceLoader.exists(model_path):
		push_error("cook_vegetation: missing %s" % model_path)
		return ""
	var src: Node = (load(model_path) as PackedScene).instantiate()
	var leaf_tint := _color(spec.get("leaf_tint", [1, 1, 1]))
	var wood_tint := _color(spec.get("wood_tint", [1, 1, 1]))
	var root := Node3D.new()
	root.name = variant
	var lods: Array = src.find_children("*_LOD*", "MeshInstance3D", true, false)
	lods.sort_custom(func(a, b): return String(a.name) < String(b.name))
	var meshes: Array = lods.map(func(mi): return (mi as MeshInstance3D).mesh as ArrayMesh)
	# Scans exported with a single detail level (or a too-heavy one) get their
	# chain from the catalogue: `simplify` lists each LOD's triangle budget as a
	# fraction of the source LOD0 (meshoptimizer, via ImporterMesh).
	if spec.has("simplify"):
		meshes = _simplified_chain(meshes[0], spec["simplify"])
	var materials := {}
	for i in meshes.size():
		var mesh: ArrayMesh = (meshes[i] as ArrayMesh).duplicate()
		for s in mesh.get_surface_count():
			var src_mat := mesh.surface_get_material(s) as BaseMaterial3D
			var key := src_mat.resource_name if src_mat else "surface%d" % s
			if not materials.has(key):
				materials[key] = _cook_material(src_mat, variant, key, leaf_tint, wood_tint)
			mesh.surface_set_material(s, materials[key])
		var mesh_path := "%s%s_lod%d.res" % [OUT_DIR, variant, i]
		ResourceSaver.save(mesh, mesh_path)
		var out := MeshInstance3D.new()
		out.name = "LOD%d" % i
		out.mesh = load(mesh_path)
		root.add_child(out)
		out.owner = root
	src.free()
	var packed := PackedScene.new()
	packed.pack(root)
	var scene_path := "%s%s.tscn" % [OUT_DIR, variant]
	ResourceSaver.save(packed, scene_path)
	root.free()
	return scene_path


## LODs from one source mesh: for each fraction, the generated detail level
## whose index count is closest to that share of the source (1.0 = the source).
## Vertices are compacted so a low LOD does not carry the full vertex buffer.
static func _simplified_chain(source: ArrayMesh, fractions: Array) -> Array:
	var im := ImporterMesh.new()
	for s in source.get_surface_count():
		im.add_surface(source.surface_get_primitive_type(s), source.surface_get_arrays(s), [], {},
			source.surface_get_material(s), source.surface_get_name(s))
	im.generate_lods(60.0, 25.0, [])
	var out: Array = []
	for f in fractions:
		var mesh := ArrayMesh.new()
		for s in im.get_surface_count():
			var arrays: Array = im.get_surface_arrays(s)
			var full: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
			var best := full
			if float(f) < 1.0:
				var target := float(full.size()) * float(f)
				for l in im.get_surface_lod_count(s):
					var cand: PackedInt32Array = im.get_surface_lod_indices(s, l)
					if absf(cand.size() - target) < absf(best.size() - target):
						best = cand
			mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, _compact(arrays, best))
			mesh.surface_set_material(s, im.get_surface_material(s))
			mesh.surface_set_name(s, im.get_surface_name(s))
		out.append(mesh)
	return out


static func _compact(arrays: Array, indices: PackedInt32Array) -> Array:
	var remap := {}
	var order := PackedInt32Array()
	var new_idx := PackedInt32Array()
	new_idx.resize(indices.size())
	for k in indices.size():
		var v := indices[k]
		if not remap.has(v):
			remap[v] = order.size()
			order.append(v)
		new_idx[k] = remap[v]
	var out := []
	out.resize(Mesh.ARRAY_MAX)
	for a in Mesh.ARRAY_MAX:
		var src = arrays[a]
		if src == null or a == Mesh.ARRAY_INDEX or a == Mesh.ARRAY_BONES or a == Mesh.ARRAY_WEIGHTS:
			continue
		var per := 4 if a == Mesh.ARRAY_TANGENT else 1
		var dst = src.duplicate()
		dst.resize(order.size() * per)
		for k in order.size():
			for c in per:
				dst[k * per + c] = src[order[k] * per + c]
		out[a] = dst
	out[Mesh.ARRAY_INDEX] = new_idx
	return out


static func _cook_material(src: BaseMaterial3D, variant: String, key: String, leaf_tint: Color, wood_tint: Color) -> Material:
	var foliage := key.ends_with("_leaves") or key.ends_with("_impostor") or (src != null and src.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED)
	var m: StandardMaterial3D = (src.duplicate() as StandardMaterial3D) if src is StandardMaterial3D else StandardMaterial3D.new()
	m.resource_name = key
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	m.vertex_color_use_as_albedo = false
	if foliage:
		m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
		m.alpha_scissor_threshold = 0.45
		m.alpha_antialiasing_mode = BaseMaterial3D.ALPHA_ANTIALIASING_ALPHA_TO_COVERAGE
		m.cull_mode = BaseMaterial3D.CULL_DISABLED
		m.albedo_color = leaf_tint
		m.roughness = 0.85
		m.metallic = 0.0
		m.metallic_specular = 0.25
		m.diffuse_mode = BaseMaterial3D.DIFFUSE_LAMBERT_WRAP
		m.backlight_enabled = true
		m.backlight = Color(0.22, 0.27, 0.10)
		if m.normal_texture != null:
			m.normal_enabled = true
			m.normal_scale = 0.6
	else:
		m.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED
		m.cull_mode = BaseMaterial3D.CULL_BACK
		m.albedo_color = m.albedo_color * wood_tint
	var path := "%s%s_%s.tres" % [OUT_DIR, variant, key.validate_filename()]
	ResourceSaver.save(m, path)
	return load(path)


static func _color(a: Array) -> Color:
	return Color(float(a[0]), float(a[1]), float(a[2]))
