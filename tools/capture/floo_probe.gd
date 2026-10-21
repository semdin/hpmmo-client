extends Node

## Floo Network round trip, offline, through the real request path:
## courtyard -> Hagrid (same map) -> Great Hall (castle) -> caverns camp ->
## courtyard. Reports where each trip lands, the powder spent and the refusals
## (no powder); saves the window (at level 19, the caverns locked) and every
## arrival. Every hearth is open from the start; only `level_min` gates one.
##   godot --path . tools/capture/floo_probe.tscn -- [--out=<dir>]

@onready var world = $GameWorld
var _out := ""
var _ok := true

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			_out = arg.trim_prefix("--out=")
	await get_tree().create_timer(2.5).timeout
	var mc = world.get_node("MapController")
	var player: Node3D = world.get("local_player")
	player.set("level", 30)
	SimAuthority.record_for(player)["level"] = 30
	var bag: Array = player.get("inventory")
	HPEquipment.add(bag, "floo_powder", 0, 3)
	player.set("inventory", bag)
	# At the courtyard hearth: open the window (learns it), photograph it.
	var court := TravelNodes.point(HPMaps.travel_node("floo_courtyard")) + HPMaps.travel_facing(HPMaps.travel_node("floo_courtyard")) * 1.6
	player.global_position = court + Vector3.UP * 0.5
	await get_tree().create_timer(0.8).timeout
	print("FLOO at courtyard: active=%s" % mc.get("_active_travel"))
	var hud0 = world.get("hud")
	if hud0.get("skill_pick") != null:
		hud0.skill_pick.close()
	# The window at level 19: every hearth open but the caverns (level 24).
	player.set("level", 19)
	mc.call("open_floo", "floo_courtyard")
	await get_tree().create_timer(0.6).timeout
	await _shot("floo_window")
	player.set("level", 30)
	var hud = world.get("hud")
	hud.floo.close()
	for id in ["floo_courtyard", "floo_hogsmeade"]:
		var n := HPMaps.travel_node(id)
		player.global_position = TravelNodes.point(n) + HPMaps.travel_facing(n) * 1.6 + Vector3.UP * 0.5
		await get_tree().create_timer(1.5).timeout
		await _shot("floo_hearth_" + id, player, n)
	for leg in [["floo_courtyard", "floo_hagrid"], ["floo_hagrid", "floo_great_hall"], ["floo_great_hall", "floo_caverns_camp"]]:
		await _trip(mc, player, leg[0], leg[1])
	# Out of powder now (3 spent): the last leg is refused.
	var before: String = mc.current_map
	await _trip(mc, player, "floo_caverns_camp", "floo_courtyard", false)
	print("FLOO no-powder refused: stayed=%s" % (mc.current_map == before))
	_ok = _ok and mc.current_map == before
	# Buying at the fireplace: 2 pinches for 2 x buy_price.
	player.set("galleons", 10000)
	SimAuthority.record_for(player)["galleons"] = 10000
	SimNet.submit_equipment(player, "buy", "", "floo_powder", 2, 0)
	await get_tree().create_timer(0.5).timeout
	var bought := _powder(player) == 2 and int(player.get("galleons")) == 10000 - 2 * int(HPEquipment.item("floo_powder").get("buy_price", 0))
	print("FLOO buy: powder=%d galleons=%d ok=%s" % [_powder(player), int(player.get("galleons")), bought])
	_ok = _ok and bought
	print("FLOO %s" % ("PASS" if _ok else "FAIL"))
	get_tree().quit()

func _powder(player: Node) -> int:
	var n := 0
	for e in player.get("inventory"):
		if String(e.get("id", "")) == "floo_powder":
			n += int(e.get("amount", 1))
	return n

func _trip(mc: Node, player: Node3D, from_id: String, to_id: String, expect := true) -> void:
	var src := HPMaps.travel_node(from_id)
	player.global_position = TravelNodes.point(src) + HPMaps.travel_facing(src) * 1.6 + Vector3.UP * 0.5
	await get_tree().create_timer(0.8).timeout
	var powder := _powder(player)
	mc.call("_floo_depart", from_id, to_id)
	var t := 0.0
	await get_tree().create_timer(1.2).timeout
	while mc.busy and t < 30.0:
		await get_tree().create_timer(0.25).timeout
		t += 0.25
	await get_tree().create_timer(1.5).timeout
	var dest := HPMaps.travel_node(to_id)
	var want := TravelNodes.point(dest)
	var d := player.global_position - want
	var arrived: bool = mc.current_map == String(dest.get("map", "")) and Vector2(d.x, d.z).length() < 4.0
	print("FLOO %s -> %s: map=%s pos=%s dist=%.1f powder %d->%d arrived=%s on_floor=%s" % [from_id, to_id, mc.current_map,
		player.global_position, Vector2(d.x, d.z).length(), powder, _powder(player), arrived, player.is_on_floor()])
	if expect:
		_ok = _ok and arrived and _powder(player) == powder - 1
		await _shot("floo_arrive_" + to_id, player, dest)

func _shot(name: String, player: Node3D = null, dest: Dictionary = {}) -> void:
	if _out == "":
		return
	var cam: Camera3D = null
	if player != null:
		for layer in world.find_children("*", "CanvasLayer", true, false):
			(layer as CanvasLayer).visible = false
		cam = Camera3D.new()
		world.add_child(cam)
		var face := HPMaps.travel_facing(dest)
		var hearth := TravelNodes.point(dest)
		cam.global_position = hearth + face * 6.5 + Vector3(face.z, 0, -face.x) * 2.0 + Vector3.UP * 2.6
		cam.look_at(hearth + Vector3.UP * 1.2)
		cam.current = true
		await get_tree().create_timer(0.3).timeout
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_jpg(_out.path_join(name + ".jpg"), 0.85)
	if cam != null:
		cam.queue_free()
		for layer in world.find_children("*", "CanvasLayer", true, false):
			(layer as CanvasLayer).visible = true
