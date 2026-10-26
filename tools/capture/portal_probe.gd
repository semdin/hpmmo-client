extends Node

## Walks real portals offline (the same request/grant/commit path a player's
## E press takes) and reports where the body ends up, as a level-35 test wizard
## (the Trial Hall wants level 5, the Forbidden Corridor 30).
##   godot --path . tools/capture/portal_probe.tscn -- --there=<portal id> --back=<portal id> [--out=<dir>]
##   godot --path . tools/capture/portal_probe.tscn -- --route=castle_door,fc_entry,fc_exit,vestibule_exit
## A route walks its portals in order, so a portal on another map (the
## Forbidden Corridor door is in the castle) is reached through the ones before.

@onready var world = $GameWorld
var _refused := ""

func _enter_tree() -> void:
	TestGround.use_test_character("corridor")

func _ready() -> void:
	var route: Array = []
	var out_dir := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--there="):
			route.push_front(arg.trim_prefix("--there="))
		elif arg.begins_with("--back="):
			route.append(arg.trim_prefix("--back="))
		elif arg.begins_with("--route="):
			route = Array(arg.trim_prefix("--route=").split(",", false))
		elif arg.begins_with("--out="):
			out_dir = arg.trim_prefix("--out=")
	SimAuthority.transfer_refused.connect(func(_peer: int, reason: String): _refused = reason)
	await get_tree().create_timer(2.0).timeout
	var ok := not route.is_empty()
	for portal_id in route:
		ok = ok and await _walk(String(portal_id), out_dir)
	print("PROBE %s" % ("PASS" if ok else "FAIL"))
	get_tree().quit(0 if ok else 1)

func _walk(portal_id: String, out_dir: String) -> bool:
	var mc = world.get_node("MapController")
	var player: Node3D = world.get("local_player")
	var portal := HPMaps.portal(portal_id)
	if portal.is_empty():
		printerr("PROBE unknown portal '%s' (--there=<id> --back=<id>; ids in maps.json `portals`)" % portal_id)
		return false
	if String(portal.get("map_id", "")) != String(mc.current_map).get_slice("#", 0):
		printerr("PROBE %s is on %s, the body is on %s: walk there first (--route=...)" % [
			portal_id, portal.get("map_id", ""), mc.current_map])
		return false
	_refused = ""
	var c: Array = portal.get("trigger", {}).get("center", [0, 0, 0])
	# A dungeon copy's portals are authored local to the copy.
	var at := Vector3(float(c[0]), float(c[1]) + 1.0, float(c[2])) + HPMaps.instance_origin(String(mc.current_map))
	player.global_position = at
	if player.has_method("set") and "velocity" in player:
		player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.6).timeout
	var from_map: String = mc.current_map
	print("PROBE %s: from %s at %s (portal %s)" % [portal_id, from_map, player.global_position, at])
	mc.call("_begin_transfer", portal)
	var t := 0.0
	while (mc.busy or mc.current_map == from_map) and t < 40.0 and _refused == "":
		await get_tree().create_timer(0.25).timeout
		t += 0.25
	var landed := player.global_position
	await get_tree().create_timer(3.0).timeout
	var settled := player.global_position
	var floor_ok: bool = player.is_on_floor() if player.has_method("is_on_floor") else false
	print("PROBE %s: map=%s after %.1fs landed=%s settled=%s drop=%.2f on_floor=%s" % [
		portal_id, mc.current_map, t, landed, settled, landed.y - settled.y, floor_ok])
	if out_dir != "":
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(out_dir.path_join("probe_%s.jpg" % portal_id), 0.85)
	if _refused != "":
		print("PROBE %s: refused (%s)" % [portal_id, _refused])
		return false
	# A dungeon copy is `<map>#<slot>`.
	return String(mc.current_map).get_slice("#", 0) == String(portal.get("to_map", "")) \
		and absf(landed.y - settled.y) < 3.0 and floor_ok
