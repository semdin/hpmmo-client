extends SceneTree

## Cooks the courtyard's Poly Haven plants (CC0) into light game meshes:
##   godot --headless --path . -s tools/terrain/cook_plants.gd
## Reads assets/models/plants/<id>/<id>_1k.gltf, simplifies every variant to the
## triangle budget below (meshoptimizer, the same chain as cook_vegetation.gd)
## and writes assets/models/plants/cooked/<id>_<n>.res, one mesh per variant,
## with the game material: leaves are alpha cards, and Poly Haven ships their
## mask as a separate Alpha map the glTF does not reference, so the colour map
## and the mask are joined into textures/<id>_diffa_1k.png and drawn
## alpha-scissored, both sides lit, never metal.
## The client keeps only the cooked meshes and the textures they use. To
## re-cook, copy art/vegetation/source/<id>/ (glTF, bin, textures/ with the
## diff and alpha jpgs) back into assets/models/plants/<id>/, rebuild the png
## (colour RGB + alpha jpg as A, e.g. PIL putalpha), import, run this, then
## remove the glTF, bin and diff jpg again.

const Cook = preload("res://tools/terrain/cook_vegetation.gd")
const OUT := "res://assets/models/plants/cooked/"
## Triangles per variant.
const BUDGET := {
	"flower_gazania": 700,
	"flower_ursinia": 600,
	"flower_empodium": 300,
	# eight in the courtyard: kept whole (its leaves do not survive simplifying)
	"wild_rooibos_bush": 100000,
}


func _initialize() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT))
	for id in BUDGET:
		var path := "res://assets/models/plants/%s/%s_1k.gltf" % [id, id]
		if not ResourceLoader.exists(path):
			printerr("cook_plants: missing %s" % path)
			continue
		var scene: Node = (load(path) as PackedScene).instantiate()
		var k := 0
		var before := 0
		var after := 0
		for node in scene.find_children("*", "MeshInstance3D", true, false):
			var src := (node as MeshInstance3D).mesh as ArrayMesh
			var tris := _tris(src)
			var mesh: ArrayMesh = src.duplicate() if tris <= int(BUDGET[id]) \
				else Cook._simplified_chain(src, [float(BUDGET[id]) / tris])[0]
			for s in mesh.get_surface_count():
				mesh.surface_set_material(s, _material(mesh.surface_get_material(s), id))
			ResourceSaver.save(mesh, "%s%s_%d.res" % [OUT, id, k])
			before += tris
			after += _tris(mesh)
			k += 1
		scene.free()
		print("cook_plants %s: %d variants, %d -> %d triangles" % [id, k, before, after])
	quit()


static func _tris(mesh: ArrayMesh) -> int:
	var n := 0
	for s in mesh.get_surface_count():
		var idx: PackedInt32Array = mesh.surface_get_arrays(s)[Mesh.ARRAY_INDEX]
		n += idx.size() / 3
	return n


static func _material(src: Material, id: String) -> StandardMaterial3D:
	var m: StandardMaterial3D = (src.duplicate() as StandardMaterial3D) if src is StandardMaterial3D else StandardMaterial3D.new()
	m.albedo_texture = load("res://assets/models/plants/%s/textures/%s_diffa_1k.png" % [id, id])
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	m.alpha_scissor_threshold = 0.5
	m.alpha_antialiasing_mode = BaseMaterial3D.ALPHA_ANTIALIASING_ALPHA_TO_COVERAGE
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.diffuse_mode = BaseMaterial3D.DIFFUSE_LAMBERT_WRAP
	m.roughness = maxf(m.roughness, 0.75)
	# the glTF's packed AO/rough/metal map is read as metal: leaves turned black
	m.metallic = 0.0
	m.metallic_texture = null
	m.metallic_specular = 0.25
	# Poly Haven plants carry vertex colours (wind and AO masks), not paint
	m.vertex_color_use_as_albedo = false
	# thin leaves lit through from behind, as the cooked trees (cook_vegetation.gd)
	m.backlight_enabled = true
	m.backlight = Color(0.22, 0.27, 0.10)
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	return m
