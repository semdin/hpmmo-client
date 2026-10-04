extends SceneTree

## Dumps the imported tree, skeleton bones and animation list of a GLB so the
## integration code can bind by measured names instead of assumed ones.
## Run: godot --headless --path . --script res://tools/inspect_import.gd

func _init() -> void:
	var path := "res://assets/models/characters/hero_wizard.glb"
	if OS.get_environment("INSPECT_PATH") != "":
		path = OS.get_environment("INSPECT_PATH")
	var packed: PackedScene = load(path)
	print("INSPECT_BEGIN ", path)
	if packed == null:
		print("LOAD FAILED")
		quit(1)
		return
	var root: Node = packed.instantiate()
	print("root=", root.name, " class=", root.get_class())
	_dump(root, 0)
	var ap := _find_first(root, "AnimationPlayer") as AnimationPlayer
	if ap:
		var libs := ap.get_animation_library_list()
		print("animation libraries: ", libs)
		for lib in libs:
			var library := ap.get_animation_library(lib)
			var names := library.get_animation_list()
			print("library '%s': %d animations" % [lib, names.size()])
			for n in names:
				var anim := library.get_animation(n)
				print("  ANIM %s loop=%d len=%.3f tracks=%d" % [n, anim.loop_mode, anim.length, anim.get_track_count()])
	var sk := _find_first(root, "Skeleton3D") as Skeleton3D
	if sk:
		print("skeleton bones: %d" % sk.get_bone_count())
		for i in sk.get_bone_count():
			var parent := sk.get_bone_parent(i)
			print("  BONE %d %s parent=%s" % [i, sk.get_bone_name(i), sk.get_bone_name(parent) if parent >= 0 else "-"])
	print("INSPECT_END")
	root.free()
	quit(0)

func _find_first(node: Node, cls: String) -> Node:
	if node.is_class(cls):
		return node
	for c in node.get_children():
		var found := _find_first(c, cls)
		if found:
			return found
	return null

func _dump(node: Node, depth: int) -> void:
	print("  ".repeat(depth), node.name, " [", node.get_class(), "]",
		"" if not (node is Node3D) else " pos=%s scale=%s" % [(node as Node3D).position, (node as Node3D).scale])
	for c in node.get_children():
		_dump(c, depth + 1)
