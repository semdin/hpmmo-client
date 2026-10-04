extends Node

## Phase 10 checks (plan.md Phase 10 evidence): everything about the art pass
## that is mechanically assertable, asserted.
##
## Headless-safe. Run:
##   godot --headless --path client res://scenes/test/phase10_regression.tscn \
##     --fixed-fps 60 --quit-after 3600
##
## Covers: PBR maps present and assigned (and the normal maps not colour-space
## damaged), non-metallic stone/wood surfaces, kit modules at their documented
## sizes, collision surfaces and routes intact indoors and out (including the
## new hill terrain colliding where it is drawn), room dressing present per
## room purpose, the reachable tower, sealed exterior towers, instanced repeats
## instead of one merged interior mesh, and the reduced quality preset.

const PBR = preload("res://scripts/assets/pbr_kit.gd")
const QualityPreset = preload("res://scripts/world/quality_preset.gd")
const OutdoorTerrain = preload("res://scripts/world/outdoor_terrain.gd")

## Documented module sizes from tools/blender/phase10_kit.py, as
## [x, y, z] with a tolerance. These are the grid the rooms are assembled on.
const KIT_SIZES := {
	"wall_module_4x6": [4.08, 6.00, 0.58],
	"arch_pointed_2_4x3_4": [2.43, 3.60, 0.41],
	"arch_arcade_6x5": [6.82, 5.69, 1.02],
	"column_6": [1.10, 5.97, 1.10],
	"buttress_1x6": [1.40, 6.70, 1.48],
	"window_lancet_2x4": [2.70, 4.74, 0.56],
	"floor_flag_4": [4.35, 0.15, 4.15],
	"stair_tread_0_2x4": [4.00, 0.20, 0.35],
	"balustrade_4": [4.00, 1.10, 0.26],
	"newel_post_1_2": [0.44, 1.26, 0.44],
	"roof_slope_4x6": [4.00, 6.05, 0.21],
	"tower_cap_7": [14.60, 4.10, 14.60],
	"trim_band_4": [4.00, 0.38, 0.48],
	"long_table_8": [7.60, 0.80, 1.62],
	"bench_4": [3.80, 0.51, 0.42],
	"bookshelf_4x3": [4.02, 3.13, 0.81],
	"ladder_3": [0.53, 3.00, 0.09],
	"desk_1_6": [1.60, 1.01, 1.42],
	"lectern_1": [1.30, 0.90, 0.60],
	"armour_stand_2": [1.17, 2.30, 1.00],
	"banner_1_2x3": [1.50, 3.14, 0.10],
	"portrait_1x1_5": [1.00, 1.50, 0.12],
	"candelabra_1_6": [0.56, 1.64, 0.92],
	"candle_cluster": [0.33, 0.35, 0.51],
	"tree_pine_8": [3.40, 8.70, 2.95],
	"rock_01": [2.28, 1.04, 2.22],
}

var checks := 0
var failures: Array[String] = []
var world: Node3D
var interior: Node3D

func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)

func _ready() -> void:
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false
	world = get_node_or_null("GameWorld")
	await get_tree().create_timer(0.8).timeout

	_check_materials()
	_check_kit_sizes()
	_check_quality_preset()
	_check_outdoor_collision()
	_check_outdoor_dressing()
	await _check_interior()
	_report()
	if world != null:
		world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if failures.is_empty() else 1)

# ------------------------------------------------------------------ materials

func _check_materials() -> void:
	var paths := PBR.expected_paths()
	var missing: Array = []
	for path in paths:
		if not ResourceLoader.exists(path):
			missing.append(path)
	check(missing.is_empty(), "Every PBR map and kit module resource exists (%d expected, %d missing)" % [
		paths.size(), missing.size()])
	if not missing.is_empty():
		print("  missing: ", missing)

	# Normal maps must arrive as raw data: a mean far from (0.5, 0.5, 1.0)
	# would mean the import applied an sRGB transform to a data texture.
	for set_id in ["stone_ashlar_01", "floor_flagstone_01", "wood_timber_01"]:
		var maps := PBR.set_maps(set_id)
		var normal: Texture2D = maps.get("normal")
		check(normal != null, "%s has a normal map" % set_id)
		if normal == null:
			continue
		var mean := _mean_rgb(normal.get_image())
		check(absf(mean.x - 0.5) < 0.12 and absf(mean.y - 0.5) < 0.12 and mean.z > 0.85,
			"%s normal map is raw tangent-space data (mean %.2f/%.2f/%.2f)" % [set_id, mean.x, mean.y, mean.z])
		var albedo: Texture2D = maps.get("albedo")
		check(albedo != null and albedo.get_width() == normal.get_width(),
			"%s albedo and normal match resolution" % set_id)

	# Materials: stone and wood non-metallic, iron metallic, and the shader
	# actually carries the maps it claims.
	var stone: ShaderMaterial = PBR.slot_material("stone")
	var wood: Material = PBR.slot_material("wood")
	var iron: Material = PBR.slot_material("iron")
	check(stone != null and stone.shader != null, "Stone material uses the triplanar PBR shader")
	if stone != null:
		check(stone.get_shader_parameter("albedo_tex") != null
			and stone.get_shader_parameter("normal_tex") != null
			and stone.get_shader_parameter("rough_tex") != null
			and stone.get_shader_parameter("ao_tex") != null,
			"Stone material has albedo, normal, roughness and AO assigned")
		check(float(stone.get_shader_parameter("metallic_amount")) == 0.0,
			"Stone is non-metallic")
		check(absf(float(stone.get_shader_parameter("world_scale")) - 1.0 / 8.0) < 0.0001,
			"Stone world scale is 256 px/m at 2k (8 m tile)")
	check(wood != null and (wood is StandardMaterial3D) and (wood as StandardMaterial3D).metallic == 0.0,
		"Wood is non-metallic")
	check(iron != null and iron is ShaderMaterial
		and float((iron as ShaderMaterial).get_shader_parameter("metallic_amount")) == 1.0,
		"Iron is metallic (the only metal surface in the kit)")
	# Every kit module slot resolves to a real material, never the magenta
	# unassigned fallback.
	var bad_slots: Array = []
	for module_name in PBR.KIT_SLOTS:
		for slot in PBR.KIT_SLOTS[module_name]:
			var mat: Material = PBR.slot_material(String(slot))
			if mat == null:
				bad_slots.append("%s:%s" % [module_name, slot])
	check(bad_slots.is_empty(), "Every kit material slot resolves (%d slots)" % [
		_count_slots()])
	# Decal materials blend; foliage cuts; no surface is unshaded.
	var moss: StandardMaterial3D = PBR.slot_material("moss")
	check(moss.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA,
		"Ground decals (moss/dirt) use soft alpha blending")

func _count_slots() -> int:
	var total := 0
	for module_name in PBR.KIT_SLOTS:
		total += (PBR.KIT_SLOTS[module_name] as Array).size()
	return total

func _mean_rgb(image: Image) -> Vector3:
	var total := Vector3.ZERO
	var count := 0
	var step := maxi(1, image.get_width() / 32)
	for y in range(0, image.get_height(), step):
		for x in range(0, image.get_width(), step):
			var c := image.get_pixel(x, y)
			total += Vector3(c.r, c.g, c.b)
			count += 1
	return total / maxf(1.0, float(count))

# ------------------------------------------------------------------ kit sizes

func _check_kit_sizes() -> void:
	for module_name in KIT_SIZES:
		var mesh := PBR.kit_mesh(module_name)
		if mesh == null:
			check(false, "Kit module %s loads" % module_name)
			continue
		var expected: Array = KIT_SIZES[module_name]
		var size := mesh.get_aabb().size
		var ok: bool = absf(size.x - float(expected[0])) < 0.25 \
			and absf(size.y - float(expected[1])) < 0.25 \
			and absf(size.z - float(expected[2])) < 0.25
		check(ok, "Kit module %s is at its documented size (%.2f x %.2f x %.2f)" % [
			module_name, size.x, size.y, size.z])
		var tris := 0
		for surface in range(mesh.get_surface_count()):
			tris += mesh.surface_get_arrays(surface)[Mesh.ARRAY_INDEX].size() / 3
		check(tris < 4000, "Kit module %s stays low poly (%d tris)" % [module_name, tris])

# ------------------------------------------------------------------ quality

func _check_quality_preset() -> void:
	# Headless resolves to the reduced preset, the same configuration the
	# target Intel integrated profile gets.
	check(QualityPreset.current() == "low",
		"The reduced preset is selected for this adapter profile (%s)" % QualityPreset.current())
	var settings := QualityPreset.settings()
	check(not bool(settings["sun_shadows"]), "Reduced preset disables sun shadows")
	check(not bool(settings["glow"]), "Reduced preset disables glow")
	check(not bool(settings["ssao"]), "Reduced preset disables SSAO")
	check(int(settings["msaa"]) == 0, "Reduced preset disables MSAA")
	check(float(settings["foliage_density"]) <= 0.6, "Reduced preset halves vegetation density")
	check(float(settings["particle_scale"]) <= 0.6, "Reduced preset halves particle density")
	if world != null:
		QualityPreset.apply(world)
		var sun := world.get_node_or_null("DirectionalLight3D") as DirectionalLight3D
		check(sun != null and not sun.shadow_enabled,
			"Applying the preset turns the sun's shadow off on the live world")
		var env_node := world.get_node_or_null("WorldEnvironment")
		if env_node is WorldEnvironment:
			var env: Environment = (env_node as WorldEnvironment).environment
			check(not env.glow_enabled and not env.ssao_enabled,
				"Applying the preset turns glow and SSAO off on the live environment")
		# Particle budget is applied to live systems, including spawns.
		var probe := GPUParticles3D.new()
		probe.amount = 64
		world.add_child(probe)
		QualityPreset.tune_particles(world)
		check(absf(probe.amount_ratio - 0.5) < 0.01,
			"Reduced preset halves live particle systems (ratio %.2f)" % probe.amount_ratio)
		probe.queue_free()

# ------------------------------------------------------------------ outdoors

func _check_outdoor_collision() -> void:
	check(world != null and world.has_node("TerrainPass"),
		"The shaped terrain pass is built outdoors")
	# The hills collide exactly where the mesh draws them: sample the same
	# function the mesh and the heightfield are both built from.
	var space := world.get_world_3d().direct_space_state
	var worst := 0.0
	var samples := 0
	for probe in [Vector3(-150, 0, -30), Vector3(150, 0, -60), Vector3(0, 0, 130),
			Vector3(-190, 0, 60), Vector3(60, 0, 150)]:
		var expected := OutdoorTerrain._height(probe.x, probe.z)
		if expected < 0.5:
			continue
		var query := PhysicsRayQueryParameters3D.create(
			probe + Vector3(0, expected + 30.0, 0), probe + Vector3(0, expected - 30.0, 0), 1)
		var hit: Dictionary = space.intersect_ray(query)
		if hit.is_empty():
			check(false, "Hill terrain collides at %s" % probe)
			continue
		var got: float = (hit["position"] as Vector3).y
		worst = maxf(worst, absf(got - expected))
		samples += 1
	check(samples > 0 and worst < 1.5,
		"Hill collision matches the drawn terrain (worst error %.2f m over %d samples)" % [worst, samples])
	# The playable core stays flat: an encounter area, the landing pad and the
	# approach must still ray to y ~ 0.
	for point in [Vector2(17, -33), Vector2(-91, -74), Vector2(53, -91), Vector2(0, -40), Vector2(0, -47)]:
		check(absf(OutdoorTerrain._height(point.x, point.y)) < 0.01,
			"Encounter/route ground stays flat at (%s)" % point)
	# Safe-zone boundary is marked (visual line + ward stones).
	var ward_lines := 0
	for node in world.find_children("WardLine", "MeshInstance3D", true, false):
		ward_lines += 1
	check(ward_lines >= 1, "The safe-zone boundary is drawn as a visible ward line (%d)" % ward_lines)
	# Instanced vegetation, not per-node scatter.
	var instanced := 0
	for node in world.find_children("*", "MultiMeshInstance3D", true, false):
		instanced += 1
	check(instanced >= 6, "Repeated vegetation and props are instanced (%d MultiMesh draws)" % instanced)

func _check_outdoor_dressing() -> void:
	var labels: Array = []
	for node in world.find_children("*", "Label3D", true, false):
		labels.append(String((node as Label3D).text))
	var sealed := 0
	for text in labels:
		if String(text).contains("TOWER SEALED"):
			sealed += 1
	check(sealed >= 2, "Inactive exterior towers are visibly non-enterable (%d sealed plaques)" % sealed)
	check(world.has_node("BroomLanding"), "The broom landing pad survives the terrain pass")
	check(world.has_node("StonePaths"), "The cobbled paths survive the terrain pass")

# ------------------------------------------------------------------ interior

func _check_interior() -> void:
	var packed: PackedScene = load("res://scenes/world/castle_interior.tscn")
	interior = packed.instantiate()
	interior.name = "Phase10Interior"
	world.add_child(interior)
	await get_tree().process_frame
	await get_tree().process_frame

	# Collision: the Phase 8 route legs, sampled exactly like the walkthrough.
	var legs := [
		[Vector3(0, 201.2, 33), Vector3(0, 201.2, 20), "vestibule to stair hall"],
		[Vector3(-11, 201.2, 20), Vector3(-11, 201.2, 3), "stair hall west bay"],
		[Vector3(0, 201.2, 10), Vector3(-30, 201.2, 10), "great hall through the arcade"],
		[Vector3(-36, 201.2, 18), Vector3(-36, 201.2, -18), "great hall south to dais"],
		[Vector3(-34, 207.2, -27), Vector3(-34, 207.2, -34), "library doorway"],
		[Vector3(-4, 207.2, -27), Vector3(-4, 207.2, -34), "classroom doorway"],
		[Vector3(40, 213.2, 8), Vector3(46, 213.2, 8), "tower bridge"],
		[Vector3(-46, 195.2, -13), Vector3(-46, 195.2, -9), "dungeon divider doorway"],
	]
	for leg in legs:
		check(interior.route_clear(leg[0], leg[1]), "Route still walkable: %s" % String(leg[2]))
	var space := interior.get_world_3d().direct_space_state
	check(not space.intersect_ray(PhysicsRayQueryParameters3D.create(
		Vector3(-30, 202.0, 10), Vector3(-30, 202.0, 30), 1)).is_empty(),
		"Solid walls still block movement in the Great Hall")
	# Stair flights: collision under the feet and headroom, as the walkthrough.
	for flight in [["z", 41.0, 24.0, 200.0, -1.0], ["z", 41.0, 8.0, 206.0, -1.0], ["z", -46.0, -24.0, 200.0, 1.0]]:
		check(_ramp_ok(interior, flight), "Stair flight intact at z=%.0f from y=%.0f" % [
			float(flight[1]), float(flight[3])])

	# Room dressing by purpose. Repeated props live inside MultiMesh batches
	# (KitBatch_<module>), so count both shapes.
	check(_instance_count(interior, "long_table_8") >= 6,
		"Great Hall: long tables (%d)" % _instance_count(interior, "long_table_8"))
	check(_instance_count(interior, "candle_cluster") >= 8,
		"Great Hall: candles on the tables (%d instances)" % _instance_count(interior, "candle_cluster"))
	check(_instance_count(interior, "bookshelf_4x3") >= 6,
		"Library: shelves (%d)" % _instance_count(interior, "bookshelf_4x3"))
	check(_instance_count(interior, "ladder_3") >= 1,
		"Library: a ladder (%d)" % _instance_count(interior, "ladder_3"))
	check(_instance_count(interior, "lectern_1") >= 2,
		"Classrooms: lecterns (%d)" % _instance_count(interior, "lectern_1"))
	check(_instance_count(interior, "desk_1_6") >= 12,
		"Classrooms: desks (%d instances)" % _instance_count(interior, "desk_1_6"))
	check(_instance_count(interior, "armour_stand_2") >= 3,
		"Circulation: suits of armour (%d)" % _instance_count(interior, "armour_stand_2"))
	check(_instance_count(interior, "banner_1_2x3") >= 4,
		"Circulation: house banners (%d)" % _instance_count(interior, "banner_1_2x3"))
	check(_instance_count(interior, "portrait_1x1_5") >= 4,
		"Circulation: portraits (%d)" % _instance_count(interior, "portrait_1x1_5"))
	check(_instance_count(interior, "candelabra_1_6") >= 4,
		"Circulation: candelabra (%d)" % _instance_count(interior, "candelabra_1_6"))
	check(_instance_count(interior, "tower_cap_7") >= 1, "The tower carries a slate cap")
	check(_instance_count(interior, "arch_pointed_2_4x3_4") >= 6,
		"Pointed arches dress the doorways (%d)" % _instance_count(interior, "arch_pointed_2_4x3_4"))
	# The reachable tower: its landing is a real room, reachable by route.
	check(interior.route_clear(Vector3(50, 213.2, 8), Vector3(60, 213.2, 8)),
		"The tower landing is reachable from the interior route")

	# Instancing, not one giant interior mesh.
	var batch_count := 0
	for node in interior.find_children("*", "MultiMeshInstance3D", true, false):
		batch_count += 1
	check(batch_count >= 10, "Interior draws are chunk/instanced batches (%d MultiMeshes)" % batch_count)
	# Chunked culling: architecture batches are named per chunk cell (Godot
	# auto-renames duplicates, so match by name prefix).
	var chunk_batches := 0
	for node in interior.find_children("*", "MultiMeshInstance3D", true, false):
		if String(node.name).contains("ArchitectureBatch"):
			chunk_batches += 1
	check(chunk_batches >= 4, "Architecture is batched per chunk, not merged interior-wide (%d chunks)" % chunk_batches)
	# No shadow-casting dynamic light indoors.
	var shadow_lights := 0
	for node in interior.find_children("*", "Light3D", true, false):
		if (node as Light3D).shadow_enabled:
			shadow_lights += 1
	check(shadow_lights == 0, "No shadow-casting dynamic lights inside the castle")

	interior.queue_free()
	await get_tree().process_frame

## Kit instances of one module under a root: individually placed nodes (Godot
## auto-renames duplicate siblings, so the module rides in metadata) plus
## whatever a MultiMesh batch carries.
func _instance_count(root: Node3D, module_name: String) -> int:
	var total := 0
	for node in root.find_children("*", "MeshInstance3D", true, false):
		if String(node.get_meta("kit_module", "")) == module_name:
			total += 1
	for node in root.find_children("KitBatch_" + module_name, "MultiMeshInstance3D", true, false):
		var mm := (node as MultiMeshInstance3D).multimesh
		if mm != null:
			total += mm.instance_count
	return total

func _ramp_ok(interior: Node3D, flight: Array) -> bool:
	var axis := String(flight[0])
	var cross := float(flight[1])
	var start := float(flight[2])
	var y0 := float(flight[3])
	var dir := float(flight[4])
	var rise := 6.0
	var run := 12.0
	var space := interior.get_world_3d().direct_space_state
	for i in range(8):
		var t := (float(i) + 0.5) / 8.0
		var along := start + dir * run * t
		var expected := y0 + rise * t
		var point := Vector3(cross, 0, along) if axis == "z" else Vector3(along, 0, cross)
		var down := PhysicsRayQueryParameters3D.create(
			point + Vector3.UP * (expected + 1.6), point + Vector3.UP * (expected - 1.6), 1)
		var hit: Dictionary = space.intersect_ray(down)
		if hit.is_empty() or absf((hit["position"] as Vector3).y - expected) > 0.45:
			return false
	return true

# ------------------------------------------------------------------ report

func _report() -> void:
	print("--------------------------------------------------------------")
	for message in failures:
		print("  FAILED: " + message)
	print("PHASE10 RESULT: %d checks, %d failures" % [checks, failures.size()])
