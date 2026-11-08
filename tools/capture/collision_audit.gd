extends Node

## Walk-through audit of the grounds' buildings: where a player would see a
## surface to stand on (a roof, a wall top, a prop) but the collision under it
## is lower, so a body walks or falls into the drawn geometry.
##   godot --path . tools/capture/collision_audit.tscn -- [--out=<file.json>] [--step=1.0] [--gap=0.6] [--min-area=3]
## Meshes with less than --min-area m2 of walk-through (a lamp head over its
## pole collider, a bench back over its seat box) are counted but not listed.
## Every built mesh (castle, courtyard, sites, broom landing) is turned into a
## temporary trimesh on its own physics layer; a grid of downward rays over each
## mesh compares the drawn top with the collision top (layer 1: terrain, cover,
## buildings). Cells whose drawn top stands more than --gap above the collision
## are walk-through; cells whose collision stands more than --gap above a drawn
## top inside the mesh are invisible blockers. Results are grouped per mesh.
## Needs a window (headless builds no visuals).

const ROOTS := ["HogwartsCastle", "Courtyard", "Precinct", "Sites", "BroomLanding"]
const VISUAL_LAYER := 1 << 19
const WORLD_LAYER := 1
## Meshes nobody stands on or that are meant to be passed through.
const SKIP := ["glass", "Water", "Pool", "Stream", "Splash", "Flowers", "Ward", "Portal", "Glow", "web", "Web"]

@onready var world = $GameWorld

func _ready() -> void:
	var out_path := "user://collision_audit.json"
	var step := 1.0
	var gap := 0.6
	var min_area := 3.0
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			out_path = arg.trim_prefix("--out=")
		elif arg.begins_with("--step="):
			step = float(arg.trim_prefix("--step="))
		elif arg.begins_with("--gap="):
			gap = float(arg.trim_prefix("--gap="))
		elif arg.begins_with("--min-area="):
			min_area = float(arg.trim_prefix("--min-area="))
	await get_tree().create_timer(2.0).timeout
	var meshes: Array[MeshInstance3D] = []
	for root_name in ROOTS:
		var root: Node = world.get_node_or_null(root_name)
		if root == null:
			printerr("collision_audit: no %s under the world" % root_name)
			continue
		for node in root.find_children("*", "MeshInstance3D", true, false):
			var mi := node as MeshInstance3D
			if mi.mesh == null or not mi.is_visible_in_tree() or _skipped(mi):
				continue
			meshes.append(mi)
	# one temporary trimesh body per mesh, on a layer nothing else uses
	var bodies := {}
	for mi in meshes:
		var faces := mi.mesh.get_faces()
		if faces.is_empty():
			continue
		var xf := mi.global_transform
		var world_faces := PackedVector3Array()
		world_faces.resize(faces.size())
		for i in faces.size():
			world_faces[i] = xf * faces[i]
		var shape := ConcavePolygonShape3D.new()
		shape.backface_collision = true
		shape.set_faces(world_faces)
		var body := StaticBody3D.new()
		body.collision_layer = VISUAL_LAYER
		body.collision_mask = 0
		var cs := CollisionShape3D.new()
		cs.shape = shape
		body.add_child(cs)
		add_child(body)
		bodies[mi] = body
	await get_tree().physics_frame
	await get_tree().physics_frame
	var space := get_viewport().world_3d.direct_space_state
	var report: Array = []
	var total_through := 0
	var total_blocked := 0
	for mi in meshes:
		if not bodies.has(mi):
			continue
		var own: StaticBody3D = bodies[mi]
		var box: AABB = mi.global_transform * mi.get_aabb()
		var through: Array = []
		var blocked: Array = []
		var worst := 0.0
		var under := ""
		var x := box.position.x + step * 0.5
		while x < box.end.x:
			var z := box.position.z + step * 0.5
			while z < box.end.z:
				var from := Vector3(x, box.end.y + 2.0, z)
				var to := Vector3(x, box.position.y - 4.0, z)
				var q := PhysicsRayQueryParameters3D.create(from, to, VISUAL_LAYER)
				var drawn := space.intersect_ray(q)
				# only this mesh's own top counts for this mesh
				if not drawn.is_empty() and drawn.collider == own and (drawn.normal as Vector3).y > 0.25 						and _standable(space, own, drawn.position, from.y, to.y):
					var top: float = (drawn.position as Vector3).y
					var q2 := PhysicsRayQueryParameters3D.create(from, to, WORLD_LAYER)
					var solid := space.intersect_ray(q2)
					var floor_y: float = (solid.position as Vector3).y if not solid.is_empty() else box.position.y - 4.0
					if top - floor_y > gap:
						through.append(Vector3(x, top, z))
						worst = maxf(worst, top - floor_y)
						if under == "":
							under = String(solid.collider.name) if not solid.is_empty() else "(nothing)"
					elif floor_y - top > gap:
						blocked.append(Vector3(x, top, z))
				z += step
			x += step
		if through.is_empty() and blocked.is_empty():
			continue
		total_through += through.size()
		total_blocked += blocked.size()
		report.append({
			"mesh": String(world.get_path_to(mi)),
			"walk_through_m2": snappedf(through.size() * step * step, 0.1),
			"worst_gap_m": snappedf(worst, 0.01),
			"under": under,
			"invisible_m2": snappedf(blocked.size() * step * step, 0.1),
			"through_samples": _samples(through),
			"blocked_samples": _samples(blocked),
		})
	report.sort_custom(func(a, b): return float(a.walk_through_m2) > float(b.walk_through_m2))
	print("COLLISION AUDIT meshes=%d walk_through_m2=%.0f invisible_m2=%.0f" % [meshes.size(), total_through * step * step, total_blocked * step * step])
	for entry in report:
		if float(entry.walk_through_m2) < min_area and float(entry.invisible_m2) < min_area:
			continue
		print("  %-60s through %7.1f m2 (worst %.1f m)  invisible %6.1f m2  under %s  e.g. %s" % [entry.mesh, entry.walk_through_m2, entry.worst_gap_m, entry.invisible_m2, entry.under, str(entry.through_samples.slice(0, 2))])
	var f := FileAccess.open(out_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(report, "  "))
		f.close()
		print("COLLISION AUDIT written to %s" % ProjectSettings.globalize_path(out_path))
	get_tree().quit()

## A drawn top a body can stand on: the same mesh is under the capsule's rim
## (0.35 m out, four ways) within a metre (a steep roof still counts). Window sills, lamp heads
## and bench backs are narrower than a body and do not count.
func _standable(space: PhysicsDirectSpaceState3D, own: Object, at: Vector3, top_y: float, bottom_y: float) -> bool:
	for d in [Vector3(0.35, 0, 0), Vector3(-0.35, 0, 0), Vector3(0, 0, 0.35), Vector3(0, 0, -0.35)]:
		var p: Vector3 = at + d
		var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(Vector3(p.x, top_y, p.z), Vector3(p.x, bottom_y, p.z), VISUAL_LAYER))
		if hit.is_empty() or hit.collider != own or absf((hit.position as Vector3).y - at.y) > 1.0:
			return false
	return true


func _skipped(mi: MeshInstance3D) -> bool:
	var n := String(mi.name)
	for s in SKIP:
		if n.contains(s):
			return true
	return false

## A few spread-out cells of a list (rounded), for the report.
func _samples(cells: Array) -> Array:
	var out: Array = []
	if cells.is_empty():
		return out
	var stride := maxi(1, cells.size() / 6)
	for i in range(0, cells.size(), stride):
		var c: Vector3 = cells[i]
		out.append([roundi(c.x), snappedf(c.y, 0.1), roundi(c.z)])
		if out.size() >= 6:
			break
	return out
