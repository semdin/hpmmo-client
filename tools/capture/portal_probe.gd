extends Node

## Walks a real portal round trip offline (the same request/grant/commit path
## a player's E press takes) and reports where the body ends up.
##   godot --path . tools/capture/portal_probe.tscn -- --there=<portal id> --back=<portal id> [--out=<dir>]

@onready var world = $GameWorld

func _ready() -> void:
	var there := ""
	var back := ""
	var out_dir := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--there="):
			there = arg.trim_prefix("--there=")
		elif arg.begins_with("--back="):
			back = arg.trim_prefix("--back=")
		elif arg.begins_with("--out="):
			out_dir = arg.trim_prefix("--out=")
	await get_tree().create_timer(2.0).timeout
	var ok := await _walk(there, out_dir)
	if ok and back != "":
		ok = await _walk(back, out_dir)
	print("PROBE %s" % ("PASS" if ok else "FAIL"))
	get_tree().quit(0 if ok else 1)

func _walk(portal_id: String, out_dir: String) -> bool:
	var mc = world.get_node("MapController")
	var player: Node3D = world.get("local_player")
	var portal := HPMaps.portal(portal_id)
	var c: Array = portal.get("trigger", {}).get("center", [0, 0, 0])
	var at := Vector3(float(c[0]), float(c[1]) + 1.0, float(c[2]))
	player.global_position = at
	if player.has_method("set") and "velocity" in player:
		player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.6).timeout
	var from_map: String = mc.current_map
	print("PROBE %s: from %s at %s (portal %s)" % [portal_id, from_map, player.global_position, at])
	mc.call("_begin_transfer", portal)
	var t := 0.0
	while (mc.busy or mc.current_map == from_map) and t < 40.0:
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
	return mc.current_map == String(portal.get("to_map", "")) and absf(landed.y - settled.y) < 3.0 and floor_ok
