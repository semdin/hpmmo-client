extends Node

var world: Node
var player: Node3D
var answers: Array[Dictionary] = []
var verify_only := false
var failures := 0

func _ready() -> void:
	var port := 7777
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--port="): port = int(arg.substr(7))
		if arg == "--verify": verify_only = true
	QuestManager.persistence_enabled = false
	SimAuthority.configure(SimAuthority.Role.CLIENT)
	world = preload("res://scenes/world/game_world.tscn").instantiate()
	add_child(world)
	SimNet.joined.connect(func(ok: bool, reason: String, _sheet: Dictionary):
		check(ok,"authenticated equipment join: "+reason)
		if ok: _run.call_deferred()
		else: get_tree().quit(1))
	get_tree().create_timer(40).timeout.connect(func():
		push_error("Equipment network probe timed out")
		get_tree().quit(2))
	SimNet.join("127.0.0.1",port,"arcane")

func check(ok: bool,message: String) -> void:
	if not ok: failures += 1
	print(("PASS: " if ok else "FAIL: ")+message)

func send(operation: String,slot: String,id := "",tier := 0) -> Dictionary:
	var request_id := SimNet.submit_equipment(player,operation,slot,id,tier)
	while true:
		await get_tree().process_frame
		for answer in answers:
			if int(answer.request_id) == request_id:
				answers.erase(answer)
				return answer
	return {}

func _run() -> void:
	await get_tree().create_timer(0.4).timeout
	player = world.local_player
	player.equipment_answer.connect(func(answer:Dictionary):answers.append(answer))
	if verify_only:
		check(player.equipment.get("main_hand",{}).get("tier",-1) == 1,"refined equipped wand survives reconnect")
		check(player.equipment.has("ring_left") and player.equipment.has("ring_right"),"both rings survive reconnect")
		check(not player.equipment.has("chest") and player.inventory.any(func(e):return e.id == "robe_apprentice" and e.amount == 1),"unequipped robe survives in bag exactly once")
		check(player.galleons == 400,"authoritative refinement price survives reconnect")
	else:
		check(player.equipment.has("main_hand") and player.equipment.has("chest"),"initial server snapshot includes equipment")
		# A locally visible marker is not proof of ownership: the server can
		# refuse a pickup that raced another collector or already despawned.
		var bag_before: Array = player.inventory.duplicate(true)
		var revision_before: int = player.inventory_revision
		var marker = preload("res://scenes/entities/loot/loot_drop.tscn").instantiate()
		world.add_child(marker)
		marker.global_position = player.global_position
		marker.setup("hat_apprentice", 1)
		marker.set_meta("sim_uid", 987654321)
		check(marker.collect(player), "client sends pickup intent for a visible marker")
		check(not marker.is_collected and player.inventory == bag_before and player.inventory_revision == revision_before, "pending pickup neither grants loot nor hides the marker")
		await get_tree().create_timer(0.3).timeout
		check(not marker.is_collected and player.inventory == bag_before and player.inventory_revision == revision_before, "rejected pickup leaves bag, revision and marker unchanged")
		marker.queue_free()
		var answer := await send("unequip","chest")
		check(answer.ok and not player.equipment.has("chest"),"network unequip is acknowledged")
		answer = await send("equip","ring_left","ring_apprentice")
		check(answer.ok,"network equips first ring")
		answer = await send("equip","ring_right","ring_apprentice")
		check(answer.ok and player.max_mana == 320,"network equips identical second ring and derives mana")
		answer = await send("equip","head","wand_hawthorn")
		check(not answer.ok and answer.reason == "wrong_slot","remote authority rejects incompatible slots")
		answer = await send("equip","main_hand","wand_hawthorn",9)
		check(not answer.ok and answer.reason == "item_missing","remote authority rejects an unowned forged tier")
		answer = await send("refine","main_hand")
		check(answer.ok and player.equipment.main_hand.tier == 1 and player.galleons == 400,"network refinement updates tier and currency from authority")
		var revision: int = player.inventory_revision
		SimNet.sim_equipment_request.rpc_id(1,int(answer.request_id),revision-1,"refine","main_hand","",0)
		await get_tree().create_timer(0.3).timeout
		check(player.inventory_revision == revision and player.galleons == 400,"replayed reliable request does not charge twice")
	check(player.inventory.any(func(e):return e.id == "wand_hawthorn" and e.tier == 4 and e.amount == 1),"spare higher-tier wand remains separate")
	print("EQUIPMENT NETWORK RESULT: %d failures" % failures)
	SimNet.leave()
	await get_tree().create_timer(0.5).timeout
	get_tree().quit(0 if failures == 0 else 1)
