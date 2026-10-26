extends Node

## Blackweb Caverns grinding check, offline: enter through the crypt portal,
## count the cavern packs, stand the player beside a Venomfang pack and a
## Broodguard pack and record what reaches the player (damage, poison, web).
##   godot --path . tools/capture/cavern_probe.tscn -- [--out=<dir>]
## Ends with `CAVERN PASS` or `CAVERN FAIL: <reasons>` (exit code 0 / 1).

@onready var world = $GameWorld
var _out := ""
var _failures: Array = []

func _expect(ok: bool, what: String) -> void:
	if not ok:
		_failures.append(what)

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
	_expect(mc.current_map == "spider_caverns", "the crypt portal did not reach the caverns")
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
	_expect(not counts.is_empty(), "no cavern packs")
	_expect(floating == 0, "%d creatures float above the floor" % floating)
	for species in ["acromantula_venomfang", "acromantula_broodguard"]:
		await _stand_by(player, species)
	await _break_stone(player)
	print("CAVERN PASS" if _failures.is_empty() else "CAVERN FAIL: " + "; ".join(_failures))
	get_tree().quit(0 if _failures.is_empty() else 1)

## Break the nearest Webbound Seal Stone with authoritative damage and report
## its waves and what dropped.
func _break_stone(player: Node3D) -> void:
	var stone: Node3D = null
	for m in get_tree().get_nodes_in_group("monoliths"):
		if String(m.get("monolith_type")) == "spider":
			stone = m
			break
	if stone == null:
		print("CAVERN stone: none")
		_expect(false, "no seal stone in the caverns")
		return
	player.global_position = stone.global_position + Vector3(5, 1, 0)
	var rec: Dictionary = SimAuthority.record_for(player)
	rec["hp"] = 900000
	rec["max_hp"] = 900000
	var stone_rec: Dictionary = SimAuthority.record_for(stone)
	print("CAVERN stone %s lv=%s hp=%s variant=%s loot=%s" % [stone.call("display_name"), stone_rec.get("level"),
		stone_rec.get("max_hp"), stone_rec.get("variant"), stone_rec.get("loot_table")])
	var before := get_tree().get_nodes_in_group("mobs").size()
	var loot_before := 0
	for uid in SimAuthority.entities:
		if int(SimAuthority.entities[uid].get("kind", 0)) == HPProtocol.Kind.LOOT:
			loot_before += 1
	if _out != "":
		for layer in world.find_children("*", "CanvasLayer", true, false):
			(layer as CanvasLayer).visible = false
		var cam := Camera3D.new()
		world.add_child(cam)
		cam.global_position = stone.global_position + Vector3(7, 3.5, 7)
		cam.look_at(stone.global_position + Vector3.UP * 1.6)
		cam.current = true
		await get_tree().create_timer(0.5).timeout
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_jpg(_out.path_join("probe_spider_stone.jpg"), 0.85)
		cam.queue_free()
	# A tenth of the stone's health per blow (a fixed 800 stopped breaking it
	# once the seal stone went to 20000 HP).
	var blow := int(ceil(float(stone_rec.get("max_hp", 10000)) / 10.0))
	for i in 12:
		SimAuthority.apply_damage(stone, blow, "basic_cast", player)
		await get_tree().create_timer(0.3).timeout
	var drops: Array = []
	for uid in SimAuthority.entities:
		var r: Dictionary = SimAuthority.entities[uid]
		if int(r.get("kind", 0)) == HPProtocol.Kind.LOOT:
			for slot in r.get("slots", r.get("items", [])):
				drops.append(slot)
	var loot_entities: int = SimAuthority.entities.values().filter(func(r): return int(r.get("kind", 0)) == HPProtocol.Kind.LOOT).size() - loot_before
	print("CAVERN stone broken=%s wave_mobs=%d loot_entities=%d drops=%s" % [stone.get("is_destroyed"),
		get_tree().get_nodes_in_group("mobs").size() - before, loot_entities, str(drops).left(600)])
	_expect(bool(stone.get("is_destroyed")), "the seal stone did not break")
	_expect(loot_entities > 0, "the broken seal stone dropped nothing")

func _stand_by(player: Node3D, species: String) -> void:
	var target: Node3D = null
	for mob in get_tree().get_nodes_in_group("mobs"):
		if (mob as Node3D).global_position.y > 1500.0 and String(mob.get("species")) == species:
			target = mob
			break
	if target == null:
		print("CAVERN %s: none found" % species)
		_expect(false, "no %s in the caverns" % species)
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
	var taken := hp0 - int(SimAuthority.record_for(player).get("hp", 0))
	print("CAVERN %s: lv=%s hp=%s state=%s damage_taken=%d poisoned=%s webbed=%s abilities=%s" % [
		species, target.get("level"), target.get("max_hp"), target.get("state"),
		taken, poisoned, webbed, abilities.keys()])
	_expect(taken > 0, "%s never hurt the player" % species)
	if species == "acromantula_venomfang":
		_expect(poisoned, "the venomfang never poisoned")
	if species == "acromantula_broodguard":
		_expect(webbed, "the broodguard never webbed")
