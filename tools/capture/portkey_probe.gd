extends Node

## Offline Portkey look-and-path check: set a boot down in the courtyard for
## Hagrid's hut, photograph the boot with its countdown, then let it fire and
## report where the owner lands.
##   godot --path . tools/capture/portkey_probe.tscn -- [--out=<dir>]

@onready var world = $GameWorld
var _out := ""

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			_out = arg.trim_prefix("--out=")
	await get_tree().create_timer(2.5).timeout
	var mc = world.get_node("MapController")
	var hud = world.get("hud")
	if hud.get("skill_pick") != null:
		hud.skill_pick.close()
	var player: Node3D = world.get("local_player")
	var bag: Array = player.get("inventory")
	HPEquipment.add(bag, "portkey_boot", 0, 1)
	player.set("inventory", bag)
	player.global_position = Vector3(8.0, 59.0, 50.0)
	await get_tree().create_timer(1.0).timeout
	SimNet.portkey_place(player, "floo_hagrid")
	await get_tree().create_timer(0.5).timeout
	player.global_position += Vector3(-2.0, 0.3, -1.2)
	await get_tree().create_timer(2.0).timeout
	print("PORTKEY prompt: %s" % mc.get("_active_label"))
	if _out != "":
		var cam := Camera3D.new()
		world.add_child(cam)
		var boot: Node3D = world.get_node("PortkeyViews").get_child(0)
		cam.global_position = boot.global_position + Vector3(3.2, 2.0, 3.2)
		cam.look_at(boot.global_position + Vector3(0, 0.7, 0))
		cam.current = true
		await get_tree().create_timer(0.3).timeout
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(_out.path_join("portkey_waiting.jpg"), 0.85)
		cam.queue_free()
	var t := 0.0
	while mc.current_map == "grounds" and player.global_position.distance_to(Vector3(-266, 22, -8)) > 10.0 and t < 25.0:
		await get_tree().create_timer(0.25).timeout
		t += 0.25
	await get_tree().create_timer(0.4).timeout
	var hagrid := TravelNodes.point(HPMaps.travel_node("floo_hagrid"))
	var d := player.global_position - hagrid
	var held := 0
	for e in player.get("inventory"):
		if String(e.get("id", "")) == "portkey_boot":
			held += int(e.get("amount", 1))
	print("PORTKEY landed at %s, %.1f m from Hagrid's hearth, boots left %d -> %s" % [player.global_position,
		Vector2(d.x, d.z).length(), held, "PASS" if Vector2(d.x, d.z).length() < 6.0 and held == 0 else "FAIL"])
	if _out != "":
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(_out.path_join("portkey_arrived.jpg"), 0.85)
	get_tree().quit()
