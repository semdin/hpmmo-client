extends SceneTree

# Script to test and tune hand grip poses for wand and broom
func _init() -> void:
	var hero_scene = load("res://assets/models/characters/hero_wizard.glb")
	var instance = hero_scene.instantiate()
	root.add_child(instance)
	
	var skel: Skeleton3D = null
	for child in instance.find_children("*", "Skeleton3D", true, false):
		skel = child
		break
	
	if skel == null:
		print("No skeleton found!")
		quit()
		return
	
	print("Skeleton found: %s" % skel.name)
	
	# Let's inspect local rest bases of finger bones on R hand
	var fingers = ["Index", "Middle", "Ring", "Pinky"]
	for f in fingers:
		for k in [1, 2, 3, 4]:
			var bname = "%s%d.R" % [f, k]
			var idx = skel.find_bone(bname)
			if idx >= 0:
				var rest = skel.get_bone_rest(idx)
				print("%-10s rest basis: X=%s Y=%s Z=%s" % [bname, rest.basis.x, rest.basis.y, rest.basis.z])
	
	for k in [1, 2, 3]:
		var bname = "Thumb%d.R" % k
		var idx = skel.find_bone(bname)
		if idx >= 0:
			var rest = skel.get_bone_rest(idx)
			print("%-10s rest basis: X=%s Y=%s Z=%s" % [bname, rest.basis.x, rest.basis.y, rest.basis.z])
			
	quit()
