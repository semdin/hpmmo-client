extends Node

## Blackweb Caverns grinding check, offline: enter through the crypt portal,
## count the cavern packs, stand the player beside a Venomfang pack and a
## Broodguard pack and record what reaches the player (damage, poison, web).
##   godot --path . tools/capture/cavern_probe.tscn -- [--out=<dir>]

@onready var world = $GameWorld
var _out := ""

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			_out = arg.trim_prefix("--out=")
	await get_tree().create_timer(2.0).timeout
	var mc = world.get_node("MapController")
	var player: Node3D = world.get("local_player")
	var portal := HPMaps.portal("crypt_descend")
	var c: Array = (portal.get("trigger", {}) as Dictionary).get("center", [0, 0, 0])
	player.global_position = Vector3(c[0], float(c[1]) + 1.0, c[2])
	await get_tree().create_timer(0.5).timeout
	mc.call("_begin_transfer", portal)
	var t := 0.0
	while (mc.busy or mc.current_map != "spider_caverns") and t < 30.0:
		await get_tree().create_timer(0.25).timeout
		t += 0.25
	print("CAVERN map=%s" % mc.current_map)
	await get_tree().create_timer(3.0).timeout
	var counts := {}
	var floating := 0
	for mob in get_tree().get_nodes_in_group("mobs"):
		var m := mob as Node3D
		if m.global_position.y < 1500.0:
			continue
		var sp: String = String(m.get("species")) if m.get("species") != null else String(m.name)
		counts[sp] = int(counts.get(sp, 0)) + 1
		var q := PhysicsRayQueryParameters3D.create(m.global_position + Vector3.UP, m.global_position - Vector3.UP * 3.0, 1)
		if m.get_world_3d().direct_space_state.intersect_ray(q).is_empty():
			floating += 1
	print("CAVERN mobs %s floating=%d" % [counts, floating])
	for species in ["acromantula_venomfang", "acromantula_broodguard"]:
		await _stand_by(player, species)
	get_tree().quit()

func _stand_by(player: Node3D, species: String) -> void:
	var target: Node3D = null
	for mob in get_tree().get_nodes_in_group("mobs"):
		if (mob as Node3D).global_position.y > 1500.0 and String(mob.get("species")) == species:
			target = mob
			break
	if target == null:
		print("CAVERN %s: none found" % species)
		return
	var rec: Dictionary = SimAuthority.record_for(player)
	rec["hp"] = 50000
	rec["max_hp"] = 50000
	player.set("max_hp", 50000)
	player.set("current_hp", 50000)
	player.global_position = target.global_position + Vector3(9, 1, 0)
	var poisoned := false
	var webbed := false
	var hp0 := int(SimAuthority.record_for(player).get("hp", 0))
	var abilities := {}
	for i in 60:
		await get_tree().create_timer(0.25).timeout
		rec = SimAuthority.record_for(player)
		if int(rec.get("burn_until_tick", 0)) > SimAuthority.sim_tick and String(rec.get("burn_kind", "")) == "poison":
			poisoned = true
		if int(rec.get("webbed_until_tick", 0)) > SimAuthority.sim_tick:
			webbed = true
		var plan = target.get("_attack_plan")
		if plan is Dictionary and plan.has("id"):
			abilities[String(plan.id)] = true
		if i == 20 and _out != "":
			for layer in world.find_children("*", "CanvasLayer", true, false):
				(layer as CanvasLayer).visible = false
			var cam := Camera3D.new()
			world.add_child(cam)
			cam.global_position = target.global_position + Vector3(6, 3.2, 6)
			cam.look_at(target.global_position + Vector3.UP)
			cam.current = true
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_jpg(_out.path_join("probe_%s.jpg" % species), 0.85)
			cam.queue_free()
			for layer in world.find_children("*", "CanvasLayer", true, false):
				(layer as CanvasLayer).visible = true
	print("CAVERN %s: lv=%s hp=%s state=%s damage_taken=%d poisoned=%s webbed=%s abilities=%s" % [
		species, target.get("level"), target.get("max_hp"), target.get("state"),
		hp0 - int(SimAuthority.record_for(player).get("hp", 0)), poisoned, webbed, abilities.keys()])
