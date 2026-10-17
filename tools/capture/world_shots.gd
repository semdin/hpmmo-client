extends Node

## Ad-hoc visual review of the live game world, outside a login.
##   godot --path . tools/capture/world_shots.tscn -- --views=<views.json> --out=<dir> [--interior] [--quality=low]
## views.json: [["name", [x, y, z], [tx, ty, tz]], ...] in world coordinates.
## --interior builds the castle interior in place (its L0 floor is y 200).

@onready var world = $GameWorld

func _ready() -> void:
	var views_path := ""
	var out_dir := "user://world_shots"
	var interior := false
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--views="):
			views_path = arg.trim_prefix("--views=")
		elif arg.begins_with("--out="):
			out_dir = arg.trim_prefix("--out=")
		elif arg == "--interior":
			interior = true
	var views: Array = JSON.parse_string(FileAccess.get_file_as_string(views_path))
	DirAccess.make_dir_recursive_absolute(out_dir)
	await get_tree().create_timer(1.5).timeout
	for node in world.find_children("*", "CanvasLayer", true, false):
		(node as CanvasLayer).visible = false
	if world.get("overlay") != null:
		world.overlay.hide()
	var camera := Camera3D.new()
	camera.fov = 65
	camera.far = 3000.0
	world.add_child(camera)
	camera.current = true
	if interior:
		var rig = load("res://scenes/world/castle_interior.tscn").instantiate()
		world.add_child(rig)
		if rig.has_method("attach_staircase"):
			rig.call("attach_staircase")
		var controller = world.get_node_or_null("MapController")
		if controller != null and controller.has_method("_apply_interior_ambience"):
			controller.call("_apply_interior_ambience", true)
		if controller != null:
			controller.set("current_map", "castle_interior")
		for light in world.find_children("*", "DirectionalLight3D", true, false):
			if (light as DirectionalLight3D).light_energy > 0.5 and not rig.is_ancestor_of(light):
				light.visible = false
		await get_tree().create_timer(1.0).timeout
	for v in views:
		var p: Array = v[1]
		var t: Array = v[2]
		var opts: Dictionary = v[4] if v.size() > 4 else {}
		camera.global_position = Vector3(p[0], p[1], p[2])
		camera.look_at(Vector3(t[0], t[1], t[2]))
		var player = world.get("local_player")
		if player != null and is_instance_valid(player):
			if opts.has("player"):
				var at: Array = opts["player"]
				player.global_position = Vector3(at[0], at[1], at[2])
				player.visible = true
			else:
				player.global_position = camera.global_position + Vector3(0, -1.5, 0)
				player.visible = false
		if opts.has("waypoint"):
			var w: Array = opts["waypoint"]
			var guide := WaypointGuide.find(get_tree())
			if guide != null:
				guide.set_target(String(w[3]), Vector3(w[0], w[1], w[2]))
				var r := guide.route()
				print("WAYPOINT route points: %d  ys: %s" % [r.size(), str(Array(r).map(func(q): return snappedf(q.y, 0.1)).slice(0, 200, 6))])
		var hud_map: Node = null
		if bool(opts.get("map", false)):
			for node in world.find_children("*", "CanvasLayer", true, false):
				(node as CanvasLayer).visible = true
			hud_map = world.find_child("WorldMap", true, false)
			if hud_map != null:
				hud_map.call("open")
				if opts.has("map_level"):
					await get_tree().process_frame
					await get_tree().process_frame
					hud_map.call("_show_level", int(opts["map_level"]))
		await get_tree().create_timer(float(v[3]) if v.size() > 3 else 0.8).timeout
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(out_dir.path_join("%s.jpg" % v[0]), 0.88)
		print("SHOT %s" % v[0])
		var g := WaypointGuide.find(get_tree())
		if g != null and g.has_target():
			print("  guide: map=%s route=%d prints=%d air=%d player=%s" % [g.current_map(), g.route().size(),
				g.get_node("Footprints").multimesh.visible_instance_count, g.get_node("AirRoute").multimesh.visible_instance_count, g.player.global_position if g.player else null])
		if hud_map != null:
			hud_map.call("close")
			for node in world.find_children("*", "CanvasLayer", true, false):
				(node as CanvasLayer).visible = false
	get_tree().quit()
