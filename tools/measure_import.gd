extends SceneTree

## Measures the world-space bounds and named parts of the rig models so the
## scene wiring uses measured numbers, not assumed ones.
## Run: godot --headless --path . --script res://tools/measure_import.gd

func _init() -> void:
	for path in ["res://assets/models/characters/hero_wizard.glb",
			"res://assets/models/props/broom_flight.glb"]:
		var packed: PackedScene = load(path)
		if packed == null:
			print("MEASURE %s FAILED TO LOAD" % path)
			continue
		var root: Node3D = packed.instantiate()
		get_root().add_child(root)
		var bounds := _bounds(root)
		print("MEASURE %s min=%s max=%s size=%s" % [path, bounds[0], bounds[1], bounds[1] - bounds[0]])
		_report(root)
		var sk := _find(root, "Skeleton3D")
		if sk:
			var sockets := ["Hips", "Wrist_R", "Wrist.L", "Foot_L", "Foot.L", "Chest", "Head"]
			for s in sockets:
				var idx: int = (sk as Skeleton3D).find_bone(s)
				if idx >= 0:
					var pose := (sk as Skeleton3D).global_transform * (sk as Skeleton3D).get_bone_global_pose(idx)
					print("   bone %-10s origin=%s" % [s, pose.origin])
		root.free()
	quit(0)

func _report(node: Node, depth := 0) -> void:
	if node is Node3D and depth < 4:
		print("   %s%s (%s) pos=%s scale=%s" % ["  ".repeat(depth), node.name, node.get_class(),
			(node as Node3D).position, (node as Node3D).scale])
	for c in node.get_children():
		_report(c, depth + 1)

func _find(node: Node, cls: String) -> Node:
	if node.is_class(cls):
		return node
	for c in node.get_children():
		var f := _find(c, cls)
		if f:
			return f
	return null

func _bounds(node: Node) -> Array:
	var minv := Vector3(1e9, 1e9, 1e9)
	var maxv := Vector3(-1e9, -1e9, -1e9)
	var stack: Array = [node]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		if n is MeshInstance3D and (n as MeshInstance3D).mesh:
			var aabb: AABB = (n as MeshInstance3D).get_aabb()
			for i in range(8):
				var world: Vector3 = (n as Node3D).global_transform * aabb.get_endpoint(i)
				minv = minv.min(world)
				maxv = maxv.max(world)
		for c in n.get_children():
			stack.append(c)
	return [minv, maxv]
