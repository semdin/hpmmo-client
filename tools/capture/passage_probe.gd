extends Node

## Offline check of the twin links (data/travel.json cabinet / passage):
## Hogsmeade trapdoor -> One-Eyed Witch (castle) -> Room of Requirement cabinet
## -> Egg Caverns cabinet -> back -> witch -> Hogsmeade. Each leg goes through
## the real interact path (map controller) and is photographed on arrival.
##   godot --path . tools/capture/passage_probe.tscn -- [--out=<dir>]

@onready var world = $GameWorld
var _out := ""
var _ok := true
var _refused := ""

## A level-35 tester: a fresh level-1 wizard stepping out of the cabinet into
## the caverns (level 24-32 spiders) was sometimes killed before the leg back,
## and the probe failed for that.
func _enter_tree() -> void:
	TestGround.use_test_character("corridor")

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			_out = arg.trim_prefix("--out=")
	await get_tree().create_timer(2.5).timeout
	var mc = world.get_node("MapController")
	var player: Node3D = world.get("local_player")
	SimAuthority.transfer_refused.connect(func(_peer: int, reason: String): _refused = reason)
	for leg in ["passage_hogsmeade", "cabinet_requirement", "cabinet_caverns", "witch_statue"]:
		await _leg(mc, player, leg)
	print("PASSAGE %s" % ("PASS" if _ok else "FAIL"))
	get_tree().quit(0 if _ok else 1)

func _leg(mc: Node, player: Node3D, from_id: String) -> void:
	var src := HPMaps.travel_node(from_id)
	var to_id := String(src.get("pair", ""))
	var dest := HPMaps.travel_node(to_id)
	# Walk to the source (a different map first needs a transfer of its own:
	# the probe only starts each leg on the source's map, see the order above).
	player.global_position = TravelNodes.point(src) + HPMaps.travel_facing(src) * 1.4 + Vector3.UP * 0.4
	# The caverns cabinet stands among spiders: whatever fights the body there
	# holds the travel back (combat lock, a real rule). The probe checks the
	# passage, not a fight: clear the creatures round the source and let the
	# lock run out.
	if _clear_creatures(player.global_position, 35.0) > 0:
		await get_tree().create_timer(5.5).timeout
	await get_tree().create_timer(0.9).timeout
	var prompt := String(mc.get("_active_label"))
	_refused = ""
	mc.call("_passage_depart", from_id)
	var t := 0.0
	await get_tree().create_timer(1.2).timeout
	while mc.busy and t < 30.0:
		await get_tree().create_timer(0.25).timeout
		t += 0.25
	await get_tree().create_timer(1.2).timeout
	var d := player.global_position - TravelNodes.point(dest)
	var arrived: bool = mc.current_map == String(dest.get("map", "")) and Vector2(d.x, d.z).length() < 3.5
	print("PASSAGE %s -> %s: prompt='%s' map=%s dist=%.1f on_floor=%s arrived=%s%s" % [from_id, to_id, prompt,
		mc.current_map, Vector2(d.x, d.z).length(), player.is_on_floor(), arrived,
		(" refused=" + _refused) if _refused != "" else ""])
	_ok = _ok and arrived
	if _out != "":
		for layer in world.find_children("*", "CanvasLayer", true, false):
			(layer as CanvasLayer).visible = false
		var cam := Camera3D.new()
		world.add_child(cam)
		var face := HPMaps.travel_facing(dest)
		var at := TravelNodes.point(dest)
		cam.global_position = at + face * 5.5 + Vector3(face.z, 0, -face.x) * 1.8 + Vector3.UP * 2.2
		cam.look_at(at + Vector3.UP * 1.3)
		cam.current = true
		await get_tree().create_timer(0.3).timeout
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(_out.path_join("passage_" + to_id + ".jpg"), 0.85)
		cam.queue_free()
		for layer in world.find_children("*", "CanvasLayer", true, false):
			(layer as CanvasLayer).visible = true

## Kill the creatures within `radius` of `at` (environmental damage, no
## rewards). Returns how many there were.
func _clear_creatures(at: Vector3, radius: float) -> int:
	var n := 0
	for mob in get_tree().get_nodes_in_group("mobs"):
		if mob is Node3D and (mob as Node3D).global_position.distance_to(at) <= radius:
			SimAuthority.apply_damage(mob, 1000000000, "basic_cast", null)
			n += 1
	return n
