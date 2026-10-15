extends Node

var checks := 0
var failures := 0
var player: Node3D
var record: Dictionary
var sequence := 1000
@onready var world = $GameWorld

class FakePersistence extends "res://addons/hpmmo_sim/persistence.gd":
	var requests: Array = []
	var sync_response := {"_status": 503}
	func _post_sync(_path: String, _body: Dictionary) -> Dictionary:
		return sync_response.duplicate(true)
	func _post_async(path: String, body: Dictionary, callback: Callable) -> void:
		requests.append({"path":path, "body":body.duplicate(true), "callback":callback})
	func reply(response: Dictionary) -> void:
		var request: Dictionary = requests.pop_front()
		request.callback.call(response)

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error("FAIL: " + message)
	else: print("PASS: " + message)

func request(operation: String, slot: String, id := "", tier := 0, revision := -1) -> Dictionary:
	sequence += 1
	return SimAuthority.request_equipment(record.peer_id, sequence, player.inventory_revision if revision < 0 else revision, operation, slot, id, tier)

func totals(bag: Array, gear: Dictionary) -> Dictionary:
	var result := {}
	for e in bag:
		var key := "%s:%d" % [e.id, e.get("tier",0)]
		result[key] = result.get(key,0) + e.amount
	for e in gear.values():
		var key := "%s:%d" % [e.id, e.get("tier",0)]
		result[key] = result.get(key,0) + 1
	return result

func _ready() -> void:
	QuestManager.persistence_enabled = false
	await get_tree().create_timer(0.5).timeout
	player = world.local_player
	record = SimAuthority.record_for(player)
	# Freeze simulation advancement so boundary checks are exact and reproducible.
	SimAuthority.set_physics_process(false)
	_test_pure()
	_test_authority()
	await _test_gestures()
	_test_stat_revisions()
	_test_persistence()
	print("EQUIPMENT RESULT: %d checks, %d failures" % [checks,failures])
	get_tree().quit(0 if failures == 0 else 1)

func _test_pure() -> void:
	for id in HPEquipment.catalog():
		for slot in HPEquipment.SLOTS:
			var allowed: bool = slot in HPEquipment.item(id).get("slots", [])
			var result := HPEquipment.swap([{ "id":id, "amount":1, "tier":2}], {}, slot, id, 2)
			check(bool(result.ok) == allowed, "%s compatibility with %s" % [id,slot])
	var bag := [{"id":"ring_apprentice","amount":2,"tier":0}, {"id":"wand_hawthorn","amount":2,"tier":1}, {"id":"wand_hawthorn","amount":1,"tier":4}]
	var gear := {}
	var ownership := totals(bag,gear)
	for pair in [["ring_left","ring_apprentice",0], ["ring_right","ring_apprentice",0], ["main_hand","wand_hawthorn",4], ["main_hand","wand_hawthorn",1]]:
		var change := HPEquipment.swap(bag,gear,pair[0],pair[1],pair[2])
		bag = change.inventory
		gear = change.equipment
		check(totals(bag,gear) == ownership,"swap conserves each item and its tier")
	check(gear.ring_left.id == gear.ring_right.id and gear.ring_left.uid != gear.ring_right.uid,"two identical rings occupy separate slots as separate instances")
	check(bag.any(func(e): return e.id == "wand_hawthorn" and e.tier == 4),"swapping returns the higher-tier wand unchanged")
	var full: Array = []
	for i in 40: full.append({"id":"fixture_%d" % i,"amount":1,"tier":0})
	var before := full.duplicate(true)
	check(HPEquipment.swap(full,gear,"main_hand").reason == "bag_full" and full == before,"full bag rejects unequip atomically")
	full[0] = {"id":"wand_elder","amount":1,"tier":0}
	check(HPEquipment.swap(full,gear,"main_hand","wand_elder").ok,"occupied swap can use the bag space it releases")
	var migrated := HPEquipment.migrate( [{"id":"wand_elder","amount":1,"tier":7},{"id":"wand_hawthorn","amount":2,"tier":2}],4)
	check(migrated.equipment.main_hand == {"id":"wand_hawthorn","tier":4},"legacy migration selects Hawthorn and transfers legacy refinement")
	check(migrated.inventory.size() == 2 and migrated.inventory[1].tier == 2,"migration preserves spare wand tiers")
	check(HPEquipment.migrate([],9).equipment.is_empty(),"migration never invents absent equipment")
	_test_broom_catalog()
	_test_instances()

## Item instances: non-stackables are their own entries with a uid and
## bonuses, equip/unequip move exactly that instance, and stored stacks from
## before instances split into them once.
func _test_instances() -> void:
	var bag := []
	HPEquipment.add(bag,"wand_hawthorn",0,2)
	HPEquipment.add(bag,"potion_health",0,3)
	HPEquipment.add(bag,"potion_health",0,2)
	var wands: Array = bag.filter(func(e): return e.id == "wand_hawthorn")
	check(bag.size() == 3 and wands.size() == 2 and bag.any(func(e): return e.id == "potion_health" and e.amount == 5),"wands are separate instances while potions stack")
	check(wands[0].uid > 0 and wands[1].uid > 0 and wands[0].uid != wands[1].uid and wands.all(func(e): return e.amount == 1),"every instance has its own uid and an amount of one")
	wands[1].bonuses = [{"stat":"spell_power","value":5}]
	var target: int = wands[1].uid
	var worn := HPEquipment.swap(bag,{},"main_hand","wand_hawthorn",0,target)
	check(worn.ok and worn.equipment.main_hand.uid == target and worn.equipment.main_hand.bonuses == wands[1].bonuses,"equipping names the exact instance and keeps its bonuses")
	check(worn.inventory.any(func(e): return e.id == "wand_hawthorn" and e.uid == wands[0].uid),"the other wand stays in the bag")
	var back := HPEquipment.swap(worn.inventory,worn.equipment,"main_hand")
	check(back.ok and back.inventory.any(func(e): return e.get("uid",0) == target and e.bonuses == wands[1].bonuses),"unequipping returns the same instance with its bonuses")
	check(HPEquipment.swap(bag,{},"main_hand","wand_hawthorn",0,123456789).reason == "item_missing","an instance the bag does not hold cannot be equipped")
	var legacy := [{"id":"wand_elder","amount":3,"tier":2},{"id":"potion_mana","amount":4,"tier":0}]
	var gear := {"chest":{"id":"robe_apprentice","tier":0}}
	check(HPEquipment.normalize(legacy,gear) and legacy.size() == 4 and legacy.filter(func(e): return e.id == "wand_elder" and e.tier == 2 and e.uid > 0).size() == 3,"a stored stack of wands splits into instances that keep their tier")
	check(gear.chest.uid > 0 and gear.chest.bonuses == [],"worn gear saved before instances gets a uid")
	var settled := legacy.duplicate(true)
	check(not HPEquipment.normalize(legacy,gear) and legacy == settled,"normalizing twice changes nothing")
	var rings := []
	HPEquipment.add(rings,"ring_apprentice",0,HPEquipment.BAG_SLOTS + 1)
	check(not HPEquipment.capacity_ok(rings),"each instance takes a bag slot")

## One upgrade standard for wands, robes and brooms: the same refine request on
## the slot, the same step table, and each kind's own bonus curve feeding the
## derived stats; anything else refuses.
func _test_upgrade_kinds() -> void:
	var gold: int = player.galleons
	player.galleons = 100000
	HPEquipment.add(player.inventory,"mat_phoenix_ash",0,10)
	record.last_combat_tick = SimAuthority.sim_tick - 5 * HPProtocol.SIM_HZ
	check(request("equip","chest","robe_apprentice").ok,"a robe is worn for refinement")
	var robe_uid: int = player.equipment.chest.uid
	var hp_at_0: int = player.max_hp
	check(request("refine","chest").reason == "refined" and player.equipment.chest.tier == 1 and player.equipment.chest.uid == robe_uid,"refining the chest raises that robe instance to +1")
	var at_1 := HPEquipment.item_stats("robe_apprentice",1)
	check(player.max_hp == hp_at_0 - 50 + int(at_1.bonus_hp) and player.derived_stats.defense >= float(at_1.bonus_defense),"a refined robe adds its curve's health and armour")
	check(request("equip","broom","broom_ashwood").ok,"a broom is worn for refinement")
	check(request("refine","broom").reason == "refined" and player.equipment.broom.tier == 1,"refining the broom slot raises the broom")
	check(is_equal_approx(player.mounted_speed, float(HPEquipment.item_stats("broom_ashwood",1).mount_speed)) and player.mounted_speed > 15.0,"a refined broom flies faster")
	request("equip","head","hat_apprentice")
	check(request("refine","head").reason == "not_refinable","accessories are not refinable")
	request("unequip","hands")
	check(request("refine","hands").reason == "nothing_equipped","an empty slot cannot be refined")
	check(HPEquipment.item_stats("robe_apprentice",9).bonus_hp > HPEquipment.item_stats("robe_apprentice",8).bonus_hp and HPEquipment.item_stats("broom_ashwood",9).mount_speed > HPEquipment.item_stats("broom_ashwood",8).mount_speed,"each +N is worth more than the one before")
	player.galleons = gold

## Enchantments: imbue adds one bonus from the kind's pool (never a stat twice,
## never past the cap), reweave rerolls keeping the count, the scroll is spent on
## every attempt, and worn bonuses reach the derived stats and creature damage.
func _test_enchant() -> void:
	var rules := HPEquipment.enchant_rules()
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var bag := []
	HPEquipment.add(bag,"wand_hawthorn",0,1)
	HPEquipment.add(bag,"scroll_imbue",0,200)
	HPEquipment.add(bag,"scroll_reweave",0,3)
	var wand_uid: int = bag[0].uid
	var gear := {}
	check(HPEquipment.enchant(bag,gear,"scroll_reweave",wand_uid,rng).reason == "no_bonus","nothing to reweave on a fresh wand")
	var tries := 0
	while bag[0].bonuses.size() < int(rules.max_bonuses) and tries < 150:
		var r := HPEquipment.enchant(bag,gear,"scroll_imbue",wand_uid,rng)
		if not r.ok: break
		bag.assign(r.inventory)
		tries += 1
		if tries == 1:
			check(r.reason == "enchanted" and bag.filter(func(e): return e.id == "wand_hawthorn")[0].bonuses.size() == 1,"the first imbue always holds")
	var wand: Dictionary = bag.filter(func(e): return e.id == "wand_hawthorn")[0]
	var stats_seen := {}
	for b in wand.bonuses: stats_seen[b.stat] = true
	var pool: Array = HPEquipment.enchant_pool("wand_hawthorn")
	check(wand.bonuses.size() == mini(int(rules.max_bonuses), pool.size()) and stats_seen.size() == wand.bonuses.size() and stats_seen.keys().all(func(st): return st in pool),"imbue fills the wand from its pool, each stat at most once")
	var scrolls_left := int(bag.filter(func(e): return e.id == "scroll_imbue")[0].amount)
	check(scrolls_left == 200 - tries,"every imbue attempt spends exactly one scroll")
	check(HPEquipment.enchant(bag,gear,"scroll_imbue",wand_uid,rng).reason == "bonus_full","a full item refuses another imbue")
	var before: Array = wand.bonuses.duplicate(true)
	var rew := HPEquipment.enchant(bag,gear,"scroll_reweave",wand_uid,rng)
	var after: Array = rew.inventory.filter(func(e): return e.id == "wand_hawthorn")[0].bonuses
	check(rew.reason == "enchanted" and after.size() == before.size(),"reweave keeps the number of bonuses")
	check(HPEquipment.enchant(bag,gear,"scroll_imbue",wand_uid + 1,rng).reason == "item_missing","an instance the player does not hold cannot be enchanted")
	var hat := []
	HPEquipment.add(hat,"hat_apprentice",0,1)
	HPEquipment.add(hat,"scroll_imbue",0,1)
	check(HPEquipment.enchant(hat,{},"scroll_imbue",hat[0].uid,rng).reason == "not_enchantable","accessories have no enchant pool")
	var plain := HPEquipment.stats(500,300,{"main_hand":{"id":"wand_hawthorn","tier":0,"uid":1,"bonuses":[]}})
	var rich := HPEquipment.stats(500,300,{"main_hand":{"id":"wand_hawthorn","tier":0,"uid":1,"bonuses":[{"stat":"spell_power","value":10},{"stat":"max_hp","value":120},{"stat":"monster_damage","value":15}]}})
	check(is_equal_approx(rich.weapon_multiplier, plain.weapon_multiplier * 1.1) and rich.max_hp == plain.max_hp + 120 and is_equal_approx(rich.monster_damage, 15.0),"worn bonuses reach spell power, health and creature damage")
	check(HPEquipment.bonus_text({"stat":"spell_power","value":6}) == "Spell power +6%","bonus lines read as authored")
	for kind in ["weapon","armor","mount"]:
		check((rules.pools[kind] as Array).size() >= int(rules.max_bonuses),"the %s pool can fill every enchant slot" % kind)
		for stat in rules.pools[kind]:
			check(rules.stats.has(stat),"%s pool stat %s is defined" % [kind, stat])
	var effects := HPEquipment.stats(500,300,{"main_hand":{"id":"wand_hawthorn","tier":0,"uid":1,"bonuses":[{"stat":"crit_chance","value":5},{"stat":"mana_regen","value":6}]},
		"chest":{"id":"robe_apprentice","tier":0,"uid":2,"bonuses":[{"stat":"creature_resist","value":10},{"stat":"hp_regen","value":6}]},
		"broom":{"id":"broom_ashwood","tier":0,"uid":3,"bonuses":[{"stat":"exp_bonus","value":10},{"stat":"galleon_bonus","value":15}]}})
	check(effects.crit_chance == 5.0 and effects.creature_resist == 10.0 and effects.hp_regen == 6.0 and effects.mana_regen == 6.0 and effects.exp_bonus == 10.0 and effects.galleon_bonus == 15.0,"every new enchantment reaches the derived stats")
	# The authority applies them: an EXP grant with +10% and regeneration with +6/s.
	var saved_eq: Dictionary = player.equipment.duplicate(true)
	player.equipment["broom"] = {"id":"broom_ashwood","tier":0,"uid":91,"bonuses":[{"stat":"exp_bonus","value":10}]}
	player.equipment["chest"] = {"id":"robe_apprentice","tier":0,"uid":92,"bonuses":[{"stat":"hp_regen","value":6}]}
	SimAuthority.refresh_equipment(record)
	var exp_before: int = player.current_exp
	var lvl_before: int = player.level
	SimAuthority._grant_exp(record,100)
	check(player.level != lvl_before or player.current_exp == exp_before + 110,"enchanted experience bonus scales an EXP grant")
	player.current_hp = 100
	player._regen_hp = 0.0
	player._tick_regeneration(1.0)
	check(player.current_hp == 110,"enchanted health regeneration adds to the base rate")
	player.equipment = saved_eq
	SimAuthority.refresh_equipment(record)
	# Through the authority on the worn wand: the request names the uid.
	player.galleons = 100000
	HPEquipment.add(player.inventory,"scroll_imbue",0,2)
	record.last_combat_tick = SimAuthority.sim_tick - 5 * HPProtocol.SIM_HZ
	request("equip","main_hand","wand_hawthorn")
	var worn_uid: int = player.equipment.main_hand.uid
	sequence += 1
	var answer := SimAuthority.request_equipment(record.peer_id,sequence,player.inventory_revision,"enchant","","scroll_imbue",0,worn_uid)
	check(answer.ok and player.equipment.main_hand.bonuses.size() >= 1 and player.equipment.main_hand.uid == worn_uid,"the authority enchants the worn wand named by uid")

## Tiered brooms: every `model` loads with the parts the rig binds, and a higher
## tier never asks for less level or flies slower.
func _test_broom_catalog() -> void:
	var tiers := []
	for id in HPEquipment.catalog():
		var data := HPEquipment.item(id)
		if not data.has("model"):
			continue
		var scene := load(String(data.model)) as PackedScene
		check(scene != null, "%s model loads" % id)
		if scene == null:
			continue
		var model := scene.instantiate()
		for part in ["MountRoot", "SeatSocket", "GripSocket", "TailSocket", "Bristles"]:
			check(model.find_child(part, true, false) != null, "%s model carries %s" % [id, part])
		model.free()
		tiers.append([int(data.get("item_tier", 0)), HPEquipment.required_level(id), float(data.get("mount_speed", 0.0))])
	tiers.sort()
	check(tiers.size() == 5 and tiers.map(func(t): return t[0]) == [1, 2, 3, 4, 5], "five broom tiers, one per tier")
	for i in range(1, tiers.size()):
		check(tiers[i][1] > tiers[i - 1][1] and tiers[i][2] > tiers[i - 1][2],
			"broom tier %d needs more level and flies faster than tier %d" % [tiers[i][0], tiers[i - 1][0]])
	check(HPEquipment.broom_model("broom_nimbus2000") == HPEquipment.DEFAULT_BROOM_MODEL, "brooms without a model keep the original broom")

## The level gate is the authority's, and the drawn broom follows the equipped
## item: the GLB parts are swapped, the rig re-binds to the new sockets and the
## old parts leave the tree.
func _test_broom_tiers() -> void:
	var old_level: int = player.level
	player.level = 1
	check(request("equip","broom","broom_moonveil").reason == "level_too_low","a level 1 character cannot equip the level 50 broom")
	check(player.equipment.broom.id == "broom_firebolt","a refused equip leaves the broom in place")
	check(request("equip","broom","broom_ashwood").ok and player.mounted_speed == 15,"the tier 1 broom has no level gate")
	var broom = player.broom
	check(player._broom_model_path == HPEquipment.broom_model("broom_ashwood"),"equipping a tiered broom swaps the drawn model")
	check(broom.seat_socket != null and broom.seat_socket.is_inside_tree() and player.broom_mesh.is_ancestor_of(broom.seat_socket),"the rig re-binds to the new model's seat")
	check(broom.tail_socket != null and broom.tail_socket.is_inside_tree() and broom.trail != null and broom.trail.get("tail_socket") == broom.tail_socket,"the trail follows the new tail socket")
	var roots: Array = player.broom_mesh.get_children().filter(func(n): return n.name.begins_with("BroomRoot"))
	check(roots.size() == 1,"only the equipped broom's parts are drawn")
	player.level = 50
	check(request("equip","broom","broom_moonveil").ok and player.mounted_speed == 23,"level 50 equips the tier 5 broom")
	check(player._broom_model_path == HPEquipment.broom_model("broom_moonveil") and player.broom.seat_socket.is_inside_tree(),"swapping between tiered brooms re-binds again")
	check(request("equip","broom","broom_firebolt").ok and player._broom_model_path == HPEquipment.DEFAULT_BROOM_MODEL,"a broom without its own model restores the original broom")
	check(player.broom_mesh.find_child("Bristles", true, false) != null and player.broom.bristles.is_inside_tree(),"the original broom's parts are back")
	player.level = old_level

func _test_authority() -> void:
	player.inventory.clear()
	player.equipment = {}
	player.base_max_hp = 500
	player.base_max_mana = 300
	player.current_hp = 200
	player.current_mana = 100
	# Instances take a bag slot each: one of every item, a stack of each stackable.
	for id in HPEquipment.catalog(): HPEquipment.add(player.inventory,id,0,3 if HPEquipment.stackable(id) else 1)
	HPEquipment.add(player.inventory,"ring_apprentice",0,1)
	HPEquipment.add(player.inventory,"wand_hawthorn",4,1)
	player.galleons = 100000
	SimAuthority.refresh_equipment(record)
	var all := totals(player.inventory,player.equipment)
	check(request("equip","feet","boots_apprentice").ok and player.max_hp == 525 and player.current_hp == 200,"HP equipment raises maximum without healing")
	check(request("equip","head","hat_apprentice").ok and player.max_mana == 320 and player.current_mana == 100,"mana equipment raises maximum without restoring")
	for i in 5:
		request("unequip","feet")
		request("equip","feet","boots_apprentice")
	check(player.max_hp == 525 and player.current_hp == 200,"repeated equip cycles never accumulate stats or heal")
	check(totals(player.inventory,player.equipment) == all,"authority cycles conserve all items")
	player.current_hp = 525
	request("unequip","feet")
	check(player.current_hp == 500,"removing HP bonus clamps current HP")
	var rev: int = player.inventory_revision
	check(request("equip","head","hat_apprentice",0,rev-1).reason == "stale_inventory","stale inventory rejects without mutation")
	for gate in [["dead",true,"dead"],["pending_transfer",7,"transfer_pending"],["cast_id",1,"casting"],["cast_lock_until_tick",SimAuthority.sim_tick+1,"casting"],["last_combat_tick",SimAuthority.sim_tick-5*HPProtocol.SIM_HZ+1,"in_combat"],["persistence_conflict",true,"invalid_state"]]:
		var old: Variant = record.get(gate[0],0)
		record[gate[0]] = gate[1]
		check(request("equip","hands","gloves_apprentice").reason == gate[2],"authority rejects " + gate[2])
		record[gate[0]] = old
	record.last_combat_tick = SimAuthority.sim_tick - 5 * HPProtocol.SIM_HZ
	check(request("equip","hands","gloves_apprentice").ok,"combat change unlocks at exactly five seconds")
	record.mounted = true
	check(request("equip","broom","broom_nimbus2000").reason == "mounted","broom changes require dismounting")
	record.mounted = false
	check(request("equip","broom","broom_firebolt").ok and player.mounted_speed == 22,"equipped broom controls mounted speed")
	_test_broom_tiers()
	request("unequip","broom")
	check(SimAuthority.submit_mount(record.peer_id,true).reason == "no_broom","mounting requires an equipped broom")
	check(SimAuthority.request_cast(record.peer_id,"basic_cast",Vector3.ZERO,1).reason == "no_wand","offensive spells require an equipped wand")
	request("equip","main_hand","wand_elder")
	var cast_id := SimAuthority._begin_cast(record,"basic_cast",player.global_position+Vector3.FORWARD*10,1.0)
	var cast: Dictionary = SimAuthority.casts[cast_id]
	var damage: int = cast.damage
	check(damage == int(HPRules.spell_damage("basic_cast",0,player.house,1.0)*1.35),"cast uses wand base and house damage modifiers")
	SimAuthority._spawn_projectile(record,cast,player.global_position,Vector3.FORWARD,false)
	var projectile: Dictionary = SimAuthority.projectiles.back()
	record.weapon_multiplier = 20.0
	record.wand_tier = 9
	check(SimAuthority._projectile_damage(projectile,record) == damage,"delayed projectile keeps cast-time damage")
	SimAuthority.interrupt_cast(record)
	record.cast_lock_until_tick = 0
	SimAuthority.refresh_equipment(record)
	request("equip","main_hand","wand_hawthorn")
	var spare := totals(player.inventory,{})
	var gold: int = player.galleons
	var answer := request("refine","main_hand")
	check(answer.ok and player.equipment.main_hand.tier == 1 and player.galleons == gold-100,"tier-zero refinement uses authoritative guaranteed chance and price")
	check(totals(player.inventory,{}).get("wand_hawthorn:4") == spare.get("wand_hawthorn:4"),"refining equipped wand preserves spare tiers")
	var after := totals(player.inventory,player.equipment)
	var duplicate := SimAuthority.request_equipment(record.peer_id,sequence,0,"refine","main_hand","",0)
	check(duplicate == answer and totals(player.inventory,player.equipment) == after and player.galleons == gold-100,"duplicate request cannot refine or charge twice")
	check(SimAuthority.request_equipment(record.peer_id,sequence-2,player.inventory_revision,"refine","main_hand","",0).reason == "stale_request","older request sequence is refused")
	var snapshot := SimAuthority.build_stats(record)
	request("unequip","main_hand")
	player.apply_equipment_snapshot(snapshot)
	check(not player.equipment.has("main_hand"),"older equipment snapshot never rolls state back")
	request("equip","main_hand","wand_hawthorn",4)
	# Pick a reproducible failing random draw without changing catalog chances.
	var probe_rng := RandomNumberGenerator.new()
	var failure_seed := 0
	while true:
		probe_rng.seed = failure_seed
		if probe_rng.randf() * 100 >= HPRules.combat().wand_tiers[4].chance: break
		failure_seed += 1
	SimAuthority.rng.seed = failure_seed
	var before_failure_gold: int = player.galleons
	var failed := request("refine","main_hand")
	check(failed.reason == "refinement_failed" and player.equipment.main_hand.tier == 3,"failed refinement from tier four loses exactly one tier")
	check(player.galleons == before_failure_gold - int(HPRules.combat().wand_tiers[4].cost),"failed refinement still deducts the authoritative cost")
	var preserved := totals(player.inventory,player.equipment)
	player.galleons = 0
	check(request("refine","main_hand").reason == "no_gold" and totals(player.inventory,player.equipment) == preserved,"unaffordable refinement preserves ownership")
	player.galleons = before_failure_gold
	_test_upgrade_kinds()
	_test_enchant()
	# Incoming attack defense and environmental damage use separate paths.
	var mob: Node = get_tree().get_first_node_in_group("mobs")
	player.global_position = Vector3(-70,0.2,20)
	mob.global_position = Vector3(-68,0.2,20)
	record.hp = 500
	record.defense = 90
	record.ward_until_tick = 0
	var attacker := SimAuthority.record_for(mob)
	check(SimAuthority._apply_damage(record,100,"melee",attacker) == 50,"attack defense is capped at fifty percent")
	check(SimAuthority._apply_damage(record,100,"fall",{}) == 100,"environmental damage ignores equipment defense")
	check(request("equip","feet","boots_apprentice").reason == "in_combat","receiving damage starts equipment combat lock")
	check(attacker.last_combat_tick == SimAuthority.sim_tick,"dealing damage starts the attacker combat lock")
	record.last_combat_tick = -100000
	player.global_position = Vector3(0,0.2,5)
	var bag_before_pickup := totals(player.inventory,player.equipment)
	SimAuthority._spawn_loot_node("hat_apprentice",1,player.global_position,"grounds")
	var loot_uid := 0
	for uid in SimAuthority.entities:
		if int(SimAuthority.entities[uid].get("kind",0)) == HPProtocol.Kind.LOOT: loot_uid = maxi(loot_uid,int(uid))
	var loot_record := SimAuthority.record_by_uid(loot_uid)
	player.global_position = loot_record.node.global_position
	check(SimAuthority.request_pickup(record.peer_id,loot_uid).ok,"accessory world loot is obtainable through authority pickup")
	check(totals(player.inventory,player.equipment).get("hat_apprentice:0",0) == bag_before_pickup.get("hat_apprentice:0",0)+1,"pickup credits exactly one bag copy")
	# One drop, one marker. A drop that lands while the player is watching
	# arrives twice (the spawn broadcast and the interest scan's first-sight
	# send); a second view would be untracked, so the pickup's despawn would
	# remove only one of them and leave a copy of the item on the ground.
	SimAuthority.loot_spawned.emit(900001,"potion_health",1,player.global_position)
	SimAuthority.loot_spawned.emit(900001,"potion_health",1,player.global_position)
	var markers := 0
	for child in world.get_children():
		if int(child.get_meta("sim_uid",0)) == 900001: markers += 1
	check(markers == 1,"a repeated loot spawn for one uid makes exactly one marker")
	var stray = world._views.get(900001)
	if is_instance_valid(stray): stray.queue_free()
	world._views.erase(900001)

func _test_gestures() -> void:
	SimNet._equipment_request_id = sequence
	# Use the same slot callbacks the Godot GUI dispatches, including pending ack.
	var ui = world.inventory_ui
	ui.open_for_player(player)
	await get_tree().process_frame
	check(ui._preview.model.find_child("EquippedWand",true,false) != null,"preview attaches the equipped wand to the existing model")
	check(ui._preview.model.find_children("*","CharacterBody3D",true,false).is_empty(),"preview contains no gameplay player body")
	var slot: UISlot = ui._bag_slots.filter(func(s):return s.item_id == "boots_apprentice")[0]
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_RIGHT
	event.pressed = true
	slot._gui_input(event)
	check(ui._pending,"right-click shows pending acknowledgement")
	await get_tree().process_frame
	check(player.equipment.has("feet") and not ui._pending,"right-click equips when authority answers")
	slot = ui._doll_slots.filter(func(s):return s.equipment_slot == "feet")[0]
	event.button_index = MOUSE_BUTTON_LEFT
	event.double_click = true
	slot._gui_input(event)
	await get_tree().process_frame
	check(not player.equipment.has("feet"),"double-left-click unequips")
	var payload := {"arcane_item":true,"id":"boots_apprentice","tier":0,"source_slot":""}
	check(slot._can_drop_data(Vector2.ZERO,payload),"compatible equipment slot accepts drag payload")
	var hat: UISlot = ui._doll_slots.filter(func(s):return s.equipment_slot == "head")[0]
	check(not hat._can_drop_data(Vector2.ZERO,payload),"incompatible drag destination rejects")
	var before := totals(player.inventory,player.equipment)
	hat._drop_data(Vector2.ZERO,payload)
	check(totals(player.inventory,player.equipment) == before,"invalid or cancelled drop preserves ownership")
	slot._drop_data(Vector2.ZERO,payload)
	await get_tree().process_frame
	check(player.equipment.has("feet"),"drag-and-drop equips through authority")
	# Route real mouse input through the viewport: the GUI must consume it before
	# the player sees a camera or attack gesture.
	await get_tree().process_frame
	var bag_slot: UISlot = ui._bag_slots.filter(func(s):return s.item_id == "ring_apprentice")[0]
	var click := InputEventMouseButton.new()
	click.position = bag_slot.get_global_rect().get_center()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	get_viewport().push_input(click,true)
	click = click.duplicate()
	click.pressed = false
	get_viewport().push_input(click,true)
	check(bag_slot.selected and ui._details.text.contains("Apprentice Ring"),"single click selects and shows item details")
	check(not player._basic_held and not player.mouse_orbit_active,"equipment UI input does not start world attack or camera orbit")
	# Actual viewport dispatch must handle both phases of the double click.
	var combat_tick: int = record.last_combat_tick
	# The single pair of boots (one instance) is worn after the drag; put it back
	# through the UI's own request path (its ids, not this harness's).
	ui._request("unequip","feet")
	for _i in 30:
		if not ui._pending: break
		await get_tree().process_frame
	bag_slot = ui._bag_slots.filter(func(s):return s.item_id == "boots_apprentice")[0]
	await _double_click(bag_slot)
	check(player.equipment.has("feet") and not ui._pending, "viewport double click equips without a combat lock")
	await _double_click(ui._doll_slots.filter(func(s):return s.equipment_slot == "feet")[0])
	check(not player.equipment.has("feet"), "viewport double click unequips")
	player.current_hp = 100
	record.hp = 100
	var potion_count := int(totals(player.inventory,{}).get("potion_health:0",0))
	await _double_click(ui._bag_slots.filter(func(s):return s.item_id == "potion_health")[0])
	check(player.current_hp == 250 and int(totals(player.inventory,{}).get("potion_health:0",0)) == potion_count-1, "viewport double click consumes exactly one potion and updates HP")
	check(record.last_combat_tick == combat_tick and not player._basic_held and not player.mouse_orbit_active, "equip, unequip and potion clicks never reach world combat")
	bag_slot = ui._bag_slots.filter(func(s):return s.item_id == "ring_apprentice")[0]
	ui._activate(bag_slot)
	await get_tree().process_frame
	bag_slot = ui._bag_slots.filter(func(s):return s.item_id == "ring_apprentice")[0]
	ui._activate(bag_slot)
	await get_tree().process_frame
	check(player.equipment.has("ring_left") and player.equipment.has("ring_right"),"ring shortcuts use the first empty ring slot")
	bag_slot = ui._bag_slots.filter(func(s):return s.item_id == "ring_adept")[0]
	ui._activate(bag_slot)
	check(ui._ring_menu.visible and not ui._pending,"two occupied rings present a destination choice")
	ui._ring_menu.id_pressed.emit(1)
	ui._ring_menu.hide()
	await get_tree().process_frame
	check(player.equipment.ring_right.id == "ring_adept" and player.equipment.ring_left.id == "ring_apprentice","ring destination choice replaces only the selected hand")
	ui.hide()
	check(ui._preview.view.render_target_update_mode == SubViewport.UPDATE_DISABLED,"closed inventory suspends preview rendering")
	var presses := [0]
	# The action bar's first spell cell (the scene's old Slot1 is kept hidden).
	var spell_cell: Button = world.hud.action_bar.spell_slots[0]
	spell_cell.pressed.connect(func(): presses[0] += 1)
	_mouse_click(spell_cell, false)
	check(presses[0] == 1, "one hotbar click emits one pressed signal")

func _mouse_click(control: Control, double_click: bool) -> void:
	var event := InputEventMouseButton.new()
	event.position = control.get_global_rect().get_center()
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = true
	event.double_click = double_click
	get_viewport().push_input(event, true)
	event = event.duplicate()
	event.pressed = false
	get_viewport().push_input(event, true)

func _double_click(control: Control) -> void:
	_mouse_click(control, false)
	_mouse_click(control, true)
	await get_tree().process_frame
	await get_tree().process_frame

func _test_stat_revisions() -> void:
	var bag: Array = player.inventory.duplicate(true)
	var gear: Dictionary = player.equipment.duplicate(true)
	var revision: int = player.inventory_revision
	var stale := SimAuthority.build_stats(record)
	stale.merge({"inventory_revision": revision-1, "inventory": [], "equipment": {}, "hp": 123, "mana": 45, "exp": 67}, true)
	SimAuthority.apply_stats_payload(record.uid, stale)
	check(player.current_hp == 123 and player.current_mana == 45 and player.current_exp == 67, "stale inventory revision does not block live HP, mana or EXP")
	check(world.hud.hp_bar.value == 123 and world.hud.mana_bar.value == 45 and world.hud.exp_bar.value == 67, "live stats reach HUD through the network payload path")
	check(player.inventory == bag and player.equipment == gear and player.inventory_revision == revision, "stale ownership cannot overwrite the bag or its revision")
	check(record.get("inventory_revision", revision) == revision, "stale ownership cannot regress the authority mirror record")
	var previous_role: int = SimAuthority.role
	SimAuthority.role = SimAuthority.Role.CLIENT
	player.add_loot("hat_apprentice", 1)
	check(player.inventory == bag and player.inventory_revision == revision, "client cannot invent loot or advance inventory revision")
	SimAuthority.role = previous_role

func _test_persistence() -> void:
	var bridge := FakePersistence.new()
	add_child(bridge)
	var sheet := bridge.character_payload(player,record)
	# Reproduce a real HTTP JSON load, not only an in-memory integer fixture.
	player.restore_character(JSON.parse_string(JSON.stringify(sheet)))
	sheet = bridge.character_payload(player,record)
	check(sheet.equipment.values().all(func(entry): return typeof(entry.tier) == TYPE_INT), "JSON-loaded equipment is saved with integer tiers")
	check(sheet.equipment.values().all(func(entry): return typeof(entry.uid) == TYPE_INT and entry.uid > 0 and entry.bonuses is Array),"worn items are saved with their integer uid and bonuses")
	check(sheet.inventory.all(func(e): return HPEquipment.stackable(e.id) == not e.has("uid")),"the saved bag carries a uid for exactly the instances")
	var reloaded_uids: Array = sheet.inventory.filter(func(e): return e.has("uid")).map(func(e): return e.uid)
	player.restore_character(JSON.parse_string(JSON.stringify(sheet)))
	check(player.inventory.filter(func(e): return e.has("uid")).map(func(e): return int(e.uid)) == reloaded_uids,"instance uids survive a JSON save and reload unchanged")
	sheet.inventory.append({"id":"legacy_keepsake","amount":2,"tier":3})
	player.restore_character(sheet)
	check(player.inventory.any(func(e):return e.id == "legacy_keepsake" and e.amount == 2 and e.tier == 3),"loading preserves retired catalog entries and their tiers")
	var previous_house: String = player.house
	player.house = "Hufflepuff"
	player.current_hp = 123
	player._apply_house_customization()
	check(player.current_hp == 123,"restoring house appearance cannot refill saved HP")
	player.house = previous_house
	bridge.revisions[42] = 10
	bridge.save_character(42,{"character_id":42,"inventory_revision":1})
	bridge.save_character(42,{"character_id":42,"inventory_revision":2})
	check(bridge.requests.size() == 1 and bridge.pending_count() == 1,"saves serialize per character")
	bridge.reply({"_status":200,"revision":11})
	check(bridge.requests[0].body.base_revision == 11 and bridge.requests[0].body.inventory_revision == 2,"next queued save uses acknowledged revision")
	bridge.reply({"_status":503})
	check(bridge.pending_count() == 1,"transient persistence failure retains dirty state for barrier and retry")
	for attempt in 7:
		bridge._process(5)
		bridge.reply({"_status":503})
	check(bridge.pending_count() == 1, "extended service outage never discards unsaved inventory")
	check(bridge.resolve_character(42,1).get("reason") == "save_pending" and bridge.pending_count() == 1, "rejoin cannot discard dirty loot or load an older character")
	bridge._process(5)
	bridge.reply({"_status":409,"revision":15})
	check(bridge.requests[0].path == "/api/characters/load" and bridge.revisions[42] == 11,"revision conflict loads newer state instead of overwriting it")
	bridge.reply({"_status":503})
	check(bridge.pending_count() == 1,"failed conflict reload stays dirty")
	for attempt in 7:
		bridge._process(5)
		bridge.reply({"_status":503})
	check(bridge.pending_count() == 1, "extended reconciliation outage remains pending")
	bridge._process(5)
	bridge.reply({"_status":200,"character":{"revision":15}})
	check(bridge.pending_count() == 0 and bridge.revisions[42] == 15,"reconciliation resolves dirty state after successful reload")
	# Loot must reach the persistence queue immediately, before disconnect/autosave.
	var old_id: int = record.character_id
	record.character_id = 42
	SimAuthority.persistence = bridge
	var before := totals(player.inventory,{})
	SimAuthority._collect_loot({"uid":987654321,"item_id":"hat_apprentice","amount":2}, record)
	check(bridge.requests.size() == 1 and int(totals(bridge.requests[0].body.inventory,{}).get("hat_apprentice:0",0)) == before.get("hat_apprentice:0",0)+2, "pickup queues the full updated bag immediately")
	var saved: Dictionary = bridge.requests[0].body.duplicate(true)
	bridge.reply({"_status":200,"revision":16})
	player.inventory.clear()
	player.restore_character(saved)
	check(totals(player.inventory,{}) == totals(saved.inventory,{}), "saved loot survives character restore exactly once")
	SimAuthority.persistence = null
	record.character_id = old_id
	bridge.queue_free()
