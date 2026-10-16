extends Node

const FX = preload("res://scripts/spells/skill_fx.gd")
const Rules = preload("res://scripts/spells/combat_rules.gd")
const SafeZone = preload("res://scripts/world/safe_zone.gd")
var failures: Array[String] = []
var checks := 0
@onready var world = $GameWorld

func _enter_tree() -> void:
	# Reproduce a decoded database response without touching real accounts/saves.
	NetworkManager.local_character_data = JSON.parse_string('{"level":3,"exp":75,"max_hp":580,"current_hp":421,"max_mana":350,"current_mana":215,"inventory":[{"id":"potion_health","amount":2},null,7,{"id":"missing"}],"wand_tier":4,"pos_z":5}')
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false

func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)

## A point on the grounds terrain, 0.1 m up.
func _g(x: float, z: float) -> Vector3:
	var h := GroundsTerrain.height_at(x, z)
	return Vector3(x, (0.0 if is_nan(h) else h) + 0.1, z)

func _ready() -> void:
	await get_tree().create_timer(0.4).timeout
	var player = world.local_player
	var hud = world.hud
	var director = world.get_node("EncounterDirector")
	_check_mob_system(director, world.overlay)
	check(player.inventory.size() == 1 and player.inventory[0].amount == 2, "JSON inventory converts safely, malformed entries ignored")
	check(player.level == 3 and player.max_exp == 450, "Saved level restores its EXP threshold")
	check(hud.hp_bar.value == player.current_hp and hud.mana_bar.value == player.current_mana and hud.exp_bar.value == 75, "HUD binds after restoring a DB character")
	player.restore_character({"inventory": []})
	check(player.inventory.is_empty(), "Intentionally empty inventory stays empty")
	# Combat fixtures explicitly own their kit; an empty saved bag is never seeded.
	player.equipment = {"main_hand": {"id":"wand_hawthorn", "tier":0}, "broom": {"id":"broom_nimbus2000", "tier":0}}
	SimAuthority.refresh_equipment(SimAuthority.record_for(player))
	player.current_hp = 300
	player.current_mana = 100
	player._regen_hp = 0
	player._regen_mana = 0
	for _i in range(120):
		player._tick_regeneration(1.0 / 120)
	check(player.current_hp >= 303 and player.current_mana >= 107, "Regeneration works at 120 FPS")
	check(hud.hp_bar.value == player.current_hp and hud.mana_bar.value == player.current_mana, "Regeneration emits live HUD stats")
	player.take_damage(30, "melee", null)
	check(hud.hp_bar.value == player.current_hp, "Damage updates HP immediately")
	player.add_exp(210)
	check(player.level == 2 and hud.exp_bar.value == player.current_exp, "EXP rollover and level update HUD")
	await _check_house_standing(player, hud)
	await _check_server_quests(player)
	await _check_skill_training(player, hud)
	player.current_mana = player.max_mana
	player.cast_spell("protego")
	check(player.is_protego_active and hud.mana_bar.value == player.current_mana, "Skill mana payment updates HUD")
	var mana_after: int = player.current_mana
	player.cast_spell("protego")
	check(player.current_mana == mana_after, "Cooldown rejects duplicate payment")
	await get_tree().create_timer(0.4).timeout
	var dummy = world.get_node("TrainingGrounds/Dummy0")
	player.global_position = dummy.global_position + Vector3(0, 0, 8)
	player.set_target(dummy)
	var hp_before: int = dummy.current_hp
	player.cast_spell("basic_cast")
	await get_tree().create_timer(0.3).timeout
	check(dummy.current_hp < hp_before, "Aimed projectile reaches and damages the selected target")
	var projectile = preload("res://scenes/spells/spell_projectile.tscn").instantiate()
	world.add_child(projectile)
	projectile.global_position = dummy.global_position + Vector3.UP
	projectile.setup(player, "basic_cast", Vector3.UP)
	# Exact-damage checks run with critical hits switched off; the crit rules get
	# their own checks right after.
	var crit_rules: Dictionary = HPRules.combat().get("critical", {})
	var base_crit := float(crit_rules.get("base_chance", 0.0))
	crit_rules["base_chance"] = 0.0
	hp_before = dummy.current_hp
	projectile._handle_hit(dummy)
	projectile._handle_hit(dummy)
	check(dummy.current_hp == hp_before - 40, "Duplicate body/swept collisions deal damage only once")
	await _check_crit_and_combo(player, dummy, crit_rules)
	crit_rules["base_chance"] = base_crit
	check(not Rules.can_damage(player, player), "Friendly fire is rejected")
	check(not Rules.can_damage(player, world.get_node("NPCs/ProfessorFig")), "Peaceful NPCs cannot be attacked")
	FX.play_impact(world, Vector3(0, 1, 0), "expelliarmus")
	check(absf(Rules.safe_up(Vector3.UP).dot(Vector3.UP)) < 0.01, "Vertical spell effect uses a non-collinear up vector")
	await get_tree().create_timer(0.4).timeout
	var authored_active := 0
	for region in HPRules.regions():
		authored_active += HPRules.active_encounters_for(String(region.get("id", ""))).size()
	check(director.packs.size() == authored_active and authored_active >= 45,
		"Every active encounter is created (%d of %d)" % [director.packs.size(), authored_active])
	var unspawned: Array = []
	for pack in director.packs:
		if pack.members.size() != pack.count:
			unspawned.append("%s(%s)" % [pack.get("encounter_id", "?"), "deferred" if pack.get("deferred", false) else "?"])
	check(unspawned.is_empty(), "Every encounter found valid ground and spawned its full pack %s" % str(unspawned))
	# Presentation LOD: far bodies neither draw nor pose; near ones do.
	await get_tree().create_timer(0.8).timeout
	var cam := get_viewport().get_camera_3d()
	var far_awake := 0
	var near_dormant := 0
	var far_seen := 0
	for pack in director.packs:
		for member in pack.members:
			if cam == null or not is_instance_valid(member):
				continue
			var dist: float = cam.global_position.distance_to(member.global_position)
			if dist > member.VISUAL_RANGE + 5.0:
				far_seen += 1
				if member.visuals.visible or (member.anim_player and member.anim_player.active):
					far_awake += 1
			elif dist < member.VISUAL_RANGE - 5.0 and not member.visuals.visible:
				near_dormant += 1
	check(cam != null and far_seen > 50 and far_awake == 0 and near_dormant == 0,
		"Far creatures stop drawing and posing, near ones stay awake (%d far, %d awake far, %d asleep near)" % [far_seen, far_awake, near_dormant])
	for pack in director.packs:
		for member in pack.members:
			check(member.spawn_point.distance_to(member.global_position) < 8, "Spawn anchor is assigned before mob ready")
	# Ordinary mobs are reactive; protected volumes gate damage.
	# Fixed staging point far from every authored volume keeps these checks
	# deterministic regardless of the random pack anchors.
	var staging := _g(250, -150)
	var passive_pack = director.packs[1]
	var passive_mob = passive_pack.members[0]
	var staged: Array = [passive_mob, passive_pack.members[1], passive_pack.members[2]]
	var homes: Array = []
	var anchors: Array = []
	for i in range(3):
		homes.append(staged[i].spawn_point)
		anchors.append(staged[i].pack_anchor)
		staged[i].pack_anchor = staging + Vector3(i * 3.1, 0, 0)
		staged[i].spawn_point = staging + Vector3(i * 3.1, 0, 0)
		staged[i].global_position = staging + Vector3(i * 3.1, 0, 0)
	player.global_position = staging + Vector3(0, 0, 14)
	await get_tree().create_timer(1.0).timeout
	check(passive_mob.state != passive_mob.State.CHASE and passive_mob.target_player == null, "Walking beside a reactive pack does not start combat")
	check(passive_mob.aggro_mode == "reactive" and passive_mob.assist_radius == 16.0 and passive_mob.leash_distance == 26.0, "Encounter aggro fields are data-configured")
	check(director.packs[5].members[0].leash_distance == 40.0 and director.packs[5].members[0].assist_radius == 20.0, "Boss encounters carry their own leash and assist data")
	passive_mob.take_damage(5, "basic_cast", player)
	check(passive_mob.state == passive_mob.State.CHASE and passive_mob.target_player == player, "A valid hit activates the attacked mob")
	check(passive_pack.members[1].target_player == player, "Assistance stays inside the attacked pack")
	check(director.packs[2].members[0].target_player == null, "Other packs are not chain-pulled")
	# Positive control: explicit aggressive data still uses the proximity scan.
	passive_pack.members[2].aggro_mode = "aggressive"
	passive_pack.members[2].aggro_radius = 40.0
	passive_pack.members[2].global_position = staging + Vector3(-14, 0, 0)
	passive_pack.members[2].pack_anchor = staging + Vector3(-14, 0, 0)
	passive_pack.members[2].spawn_point = staging + Vector3(-14, 0, 0)
	await get_tree().create_timer(0.8).timeout
	check(passive_pack.members[2].target_player == player, "Aggressive encounter data still aggros via proximity")
	passive_pack.members[2].aggro_mode = "reactive"
	passive_pack.members[2].aggro_radius = 9.0
	passive_pack.members[2]._respawn()
	player.global_position = _g(0, 78)
	await get_tree().create_timer(0.12).timeout
	check(passive_mob.target_player == null and passive_pack.members[1].target_player == null and passive_mob.state not in [passive_mob.State.CHASE, passive_mob.State.ATTACK], "Mobs drop the fight when the target enters the courtyard")
	var zone_mob = director.packs[2].members[0]
	check(SafeZone.is_protected_point(_g(0, 65)) and SafeZone.is_protected_point(_g(0, 10)) and not SafeZone.is_protected_point(_g(250, -150)), "Safe-zone volumes are authored at specific locations")
	check(not Rules.can_damage(zone_mob, player), "Mobs cannot attack a player inside the courtyard")
	check(not Rules.can_damage(player, zone_mob), "Protected players cannot snipe outdoor mobs")
	check(Rules.can_damage(player, dummy), "Training dummies remain practiceable inside the courtyard")
	zone_mob.global_position = _g(250, -180)
	player.global_position = _g(258, -180)
	check(Rules.can_damage(player, zone_mob), "Outside protected space, combat is allowed")
	check(not director._formation_clear(_g(0, 65), 5) and director._formation_clear(_g(250, -150), 5), "Encounter spawn sampling rejects protected anchors and rings")
	var stray = director.packs[3].members[0]
	stray.global_position = _g(0, 70)
	await get_tree().create_timer(0.12).timeout
	check(stray.state == stray.State.RETURN, "Enemies displaced inside a protected volume are sent home")
	stray._respawn()
	zone_mob._respawn()
	for i in range(3):
		staged[i].pack_anchor = anchors[i]
		staged[i].spawn_point = homes[i]
		staged[i]._respawn()
	var pack = director.packs[0]
	var mob = pack.members[0]
	player.global_position = mob.global_position + Vector3(7, 0, 0)
	mob.aggro_on(player)
	check(pack.members[1].target_player == player, "Pulling one mob alerts the entire pack")
	mob.take_damage(1, "stupefy", player)
	check(mob.state == mob.State.STUNNED and mob.target_player == player, "Stun retains the attacker for subsequent chase")
	mob.take_damage(1, "expelliarmus", player)
	check(mob._weaken_timer == 5, "Disarm applies temporary attack weakening")
	var old_anchor: Vector3 = mob.pack_anchor
	for member in pack.members:
		member.take_damage(100000, "test", player)
	check(pack.timer >= 25 and pack.timer <= 35, "Pack respawn timer begins only when every member dies")
	check(mob.state == mob.State.DEAD and not mob.is_in_group("targetable"), "Dead mobs cannot be targeted")
	await get_tree().create_timer(0.1).timeout
	player.global_position = _g(0, 78)
	director._spawn_pack(0)
	check(mob.current_hp == mob.max_hp and mob.pack_anchor != old_anchor, "Whole pack respawns at a new valid anchor")
	var commander = director.packs[6].members[0]
	var guard = director.packs[6].members[1]
	var base_power: int = commander.attack_power
	guard.take_damage(100000, "test", player)
	check(commander.is_enraged and commander.attack_power > base_power, "Commander enrages after escort death")
	commander._respawn()
	check(not commander.is_enraged and commander.attack_power == base_power, "Respawn resets enrage without stacking stats")
	commander._attack_kind = "slam"
	commander._windup = 1
	commander._attack_center = commander.global_position
	commander._show_warning()
	commander.take_damage(100000, "test", player)
	check(commander._windup == 0 and commander._warning == null, "Boss death cancels the telegraphed attack")
	# The castle is a solid shell; its great doors are reached on foot from the
	# castle approach (the interior is its own map, checked by the walkthrough).
	await get_tree().physics_frame
	var space = world.get_world_3d().direct_space_state
	var approach := _g(0, 20)
	var hit: Dictionary = space.intersect_ray(PhysicsRayQueryParameters3D.create(approach + Vector3(-30, 6, -6), approach + Vector3(-30, 6, -60), 1))
	check(not hit.is_empty() and float(hit["position"].z) > -40.0, "The castle front is solid to movement and spells")
	player.set_target(null)
	player.global_position = approach + Vector3(0, 0.15, 0)
	player.velocity = Vector3.ZERO
	Input.action_press("move_forward")
	await get_tree().create_timer(3.0).timeout
	Input.action_release("move_forward")
	var door: Dictionary = HPMaps.portal("castle_door")
	var door_center := Vector3(door["trigger"]["center"][0], door["trigger"]["center"][1], door["trigger"]["center"][2])
	check(Vector2(player.global_position.x - door_center.x, player.global_position.z - door_center.z).length() < 3.5,
		"Actual character movement reaches the great doors from the approach (%.1f m off)" % Vector2(player.global_position.x - door_center.x, player.global_position.z - door_center.z).length())
	player.velocity = Vector3.ZERO
	hud.chat_input.grab_focus()
	Input.action_press("move_forward")
	var typing_pos: Vector3 = player.global_position
	await get_tree().create_timer(0.3).timeout
	Input.action_release("move_forward")
	hud.chat_input.release_focus()
	check(player.global_position.distance_to(typing_pos) < 0.1, "Typing into chat does not move the character")
	world.inventory_ui.open_for_player(player)
	player.add_loot("galleons", 37)
	check(world.inventory_ui.galleons_label.text == "Galleons: %d" % player.galleons, "Open bag refreshes currency after loot")
	world.inventory_ui.hide()
	player.global_position = _g(0, 78)
	await get_tree().create_timer(0.2).timeout
	player._cast_lock = 0
	player._mount_lock = 0
	player.toggle_broom_mount()
	check(player.is_mounted, "Grounded mount succeeds")
	await get_tree().create_timer(0.35).timeout
	player.current_mana = player.max_mana
	var mana_before_mounted_cast: int = player.current_mana
	player.cast_spell("stupefy")
	check(player.current_mana == mana_before_mounted_cast and float(player.spell_cooldowns.get("stupefy", 0.0)) <= 0.0, "Offensive casting is disabled while mounted")
	var ft_parent = player.get_parent()
	var texts_before := 0
	for child in ft_parent.get_children():
		if child is Node3D and child.scene_file_path.ends_with("floating_text.tscn"):
			texts_before += 1
	player._basic_held = true
	await get_tree().create_timer(0.3).timeout
	player._basic_held = false
	var texts_after := 0
	for child in ft_parent.get_children():
		if child is Node3D and child.scene_file_path.ends_with("floating_text.tscn"):
			texts_after += 1
	check(texts_after - texts_before <= 1, "Held attack while mounted does not spawn feedback every frame")
	var ground_y: float = _g(player.global_position.x, player.global_position.z).y
	player.global_position.y = ground_y + 12.0
	player.toggle_broom_mount()
	check(player.is_mounted, "High-altitude dismount is rejected")
	await get_tree().create_timer(0.35).timeout
	player.global_position.y = ground_y + 1.5
	player.toggle_broom_mount()
	check(not player.is_mounted, "Dismount near the ground succeeds")
	check(player.broom_particles.mesh is QuadMesh, "Flight uses textured translucent particles")
	var bristles: Node3D = player.get_node("Visuals/BroomMesh/Bristles")
	var exhaust: Node3D = player.get_node("Visuals/BroomMesh/BroomParticles")
	check(player.visuals.to_local(bristles.global_position).z < -0.4, "Broom bristles trail behind the rider")
	check(player.visuals.to_local(exhaust.global_position).z < -0.5, "Broom exhaust emits behind the rider")
	var monolith = world.monoliths_container.get_child(0)
	monolith.take_damage(2300, "bombarda", player)
	check(monolith.wave1_triggered and monolith.wave2_triggered and monolith.wave3_triggered, "Heavy monolith hit triggers every crossed wave threshold")
	await get_tree().process_frame
	var summons := 0
	for enemy in get_tree().get_nodes_in_group("mobs"):
		if enemy.summoned:
			summons += 1
	check(summons == 21, "Monolith summons three waves with finite lifecycles")
	monolith.take_damage(10000, "test", player)
	check(monolith.is_destroyed and not monolith.visible and is_instance_valid(monolith._respawn_timer) and monolith._respawn_timer.time_left > 0.0, "Destroyed monolith arms exactly one respawn timer")
	monolith._respawn()
	check(not monolith.is_destroyed and monolith.visible and monolith._respawn_timer == null and monolith.current_hp == monolith.max_hp, "Monolith respawn clears the timer and restores state")
	player.is_protego_active = false
	player.take_damage(100000, "test", null)
	var death_mana: int = player.current_mana
	player.cast_spell("stupefy")
	check(player.is_dead and player.current_mana == death_mana, "Dead player cannot cast or spend mana")
	await get_tree().create_timer(2.7).timeout
	check(not player.is_dead and player.current_hp == player.max_hp, "Player death animation ends in a clean respawn")
	world.queue_free()
	await get_tree().process_frame
	# Re-entering a world must rebuild geometry; no process-wide static guard.
	var second_world = preload("res://scenes/world/game_world.tscn").instantiate()
	add_child(second_world)
	check(second_world.has_node("HogwartsCastle"), "Scene re-entry rebuilds castle geometry")
	second_world.queue_free()
	await get_tree().process_frame
	print("REGRESSION RESULT: %d checks, %d failures" % [checks, failures.size()])
	get_tree().quit(0 if failures.is_empty() else 1)

## Mob system v2 (M0): creature catalog, resistances, elite rolls, per-species
## loot, the level-gap rule and the hunting-region bands the HUD names.
func _check_mob_system(director: Node, overlay: Node) -> void:
	var report: Dictionary = HPRules.validate_encounters()
	check(report["ok"], "Encounter data validates against the creature catalog and region bands %s" % str(report["problems"]))
	var scenes_ok := true
	for species in HPRules.mob_ids():
		scenes_ok = scenes_ok and ResourceLoader.exists(HPRules.mob_scene_path(species))
	check(scenes_ok and HPRules.mob_ids().size() >= 6, "Every catalog species resolves to a mob scene (%d species)" % HPRules.mob_ids().size())
	# M1 creatures: each body carries the clips its animation set plays, the
	# attack windup clip is time-stretched onto the authored phase, and the
	# replication variant round-trips.
	var clip_problems: Array = []
	for species in ["troll_forest", "troll_mountain", "dementor"]:
		var body = load(HPRules.mob_scene_path(species)).instantiate()
		add_child(body)
		var anim: AnimationPlayer = body.anim_player
		if anim == null:
			clip_problems.append("%s: no AnimationPlayer" % species)
		else:
			for slot in ["idle", "walk", "anticipation", "attack", "hit", "death"]:
				if not anim.has_animation(body._clip_for(slot)) or body._clip_for(slot) == "Idle" and slot != "idle":
					clip_problems.append("%s: slot %s -> %s missing" % [species, slot, body._clip_for(slot)])
			var stretch: float = body._phase_speed("anticipation", body._clip_for("anticipation"))
			if not (stretch > 0.4 and stretch < 3.0):
				clip_problems.append("%s: anticipation stretch %.2f" % [species, stretch])
		if HPProtocol.mob_scene(HPProtocol.mob_variant(body.scene_file_path)) != body.scene_file_path:
			clip_problems.append("%s: replication variant does not round-trip" % species)
		body.queue_free()
	check(clip_problems.is_empty(), "Trolls and dementors carry their animation sets and replicate %s" % str(clip_problems))
	var encounter_ids: Array = director.packs.map(func(p): return String(p.get("encounter_id", "")))
	check(encounter_ids.has("enc_troll_hollow_forest_trolls") and encounter_ids.has("enc_highland_moor_mountain_trolls")
		and encounter_ids.has("enc_misty_shore_dementors"), "The troll and dementor encounters are active in the director")
	check(HPRules.damage_after_resistances(100, "incendio", false, HPRules.mob_resist("inferi")) == 200
		and HPRules.damage_after_resistances(100, "incendio", true) == 200
		and HPRules.damage_after_resistances(100, "basic_cast", false, HPRules.mob_resist("darksnatcher")) == 85
		and HPRules.damage_after_resistances(100, "bombarda", false, HPRules.mob_resist("inferi")) == 100,
		"Resistances scale damage per spell element (fire x2 on inferi, arcane -15% on snatchers)")
	check(is_equal_approx(HPRules.level_gap_exp(10, 10), 1.0) and is_equal_approx(HPRules.level_gap_exp(30, 3), 0.05)
		and is_equal_approx(HPRules.level_gap_exp(5, 15), 1.2) and HPRules.level_gap_drop(20, 8) < 1.0,
		"Level gap: same level pays in full, far-lower mobs pay almost nothing, tougher ones pay extra")
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var count_galleons := func(drops: Array) -> int:
		return drops.filter(func(d): return d["id"] == "galleons").size()
	check(count_galleons.call(HPRules.mob_loot(false, rng)) == 1
		and count_galleons.call(HPRules.mob_loot(false, rng, "dark_wizard")) == 2
		and count_galleons.call(HPRules.mob_loot(false, rng, "dark_wizard", true)) == 3,
		"Loot stacks the base table, the species table and the elite table")
	var forest: Dictionary = HPRules.region_by_id("forest_w")
	var inside := Vector3(float(forest["center"][0]), 0.0, float(forest["center"][1]))
	check(String(HPRules.hunting_region_at(inside).get("id", "")) == "forest_w"
		and HPRules.hunting_region_at(Vector3(0, 0, 65)).is_empty()
		and HPRules.region_level_band("forest_w") == [6, 12],
		"Hunting regions are strict and carry their level band (the courtyard is not one)")
	check(overlay.band_color(10, 6, 12) != overlay.band_color(2, 6, 12) and overlay.band_color(30, 6, 12) != overlay.band_color(10, 6, 12),
		"The zone banner colours a level band against the player's level")
	# Elite: force the roll and configure a fresh body the way the director does.
	var elite_rules: Dictionary = HPRules.elite_rules()
	var chance := float(elite_rules.get("chance", 0.0))
	elite_rules["chance"] = 1.0
	var pack := {"mob": "acromantula", "level": 8, "boss": false}
	var elite_mob = load(HPRules.mob_scene_path("acromantula")).instantiate()
	director._configure_member(elite_mob, pack, true)
	var normal_mob = load(HPRules.mob_scene_path("acromantula")).instantiate()
	elite_rules["chance"] = 0.0
	director._configure_member(normal_mob, pack, true)
	elite_rules["chance"] = chance
	check(elite_mob.is_elite and not normal_mob.is_elite and elite_mob.mob_name.begins_with("Elite ")
		and absi(elite_mob.max_hp - normal_mob.max_hp * 3) <= 3,
		"An elite roll triples health and prefixes the name")
	check(elite_mob.species == "acromantula" and elite_mob.loot_table == "spider" and float(elite_mob.resist.get("fire", 0.0)) < 0.0,
		"A configured mob carries its catalog species, loot table and resistances")
	elite_mob.free()
	normal_mob.free()
	var configured := 0
	var wrong := 0
	for pack_data in director.packs:
		for member in pack_data.members:
			if not is_instance_valid(member):
				continue
			configured += 1
			var record: Dictionary = SimAuthority.record_for(member)
			if member.species != String(pack_data.get("mob", "")) or record.get("resist", {}) != member.resist 					or int(SimAuthority.mob_info_of(record).get("level", 0)) != int(pack_data.get("level", -1)):
				wrong += 1
	check(wrong == 0, "Spawned pack members (%d) carry species, resistances and level into the authority record" % configured)

## House standing: quest reputation -> rank 1..7, shown on the HUD, persisted in
## the `quests` object, and able to gate a spell on the authority.
## Critical hits are rolled by the authority and reach presentation as HIT_CRIT;
## the basic chain advances 0-1-2 inside its window and resets after it.
func _check_crit_and_combo(player: Node, dummy: Node, crit_rules: Dictionary) -> void:
	var attacker := SimAuthority.record_for(player)
	var victim := SimAuthority.record_for(dummy)
	var seen: Array = []
	var listener := func(uid: int, amount: int, _hp: int, _spell: String, _attacker: int, flags: int):
		if uid == int(victim.get("uid", -1)):
			seen.append([amount, flags])
	SimAuthority.entity_hit.connect(listener)
	victim["hp"] = int(victim.get("max_hp", 1000))
	SimAuthority._apply_damage(victim, 40, "basic_cast", attacker)
	var max_crit = crit_rules.get("max_chance", 100.0)
	crit_rules["base_chance"] = 100.0
	crit_rules["max_chance"] = 100.0
	SimAuthority._apply_damage(victim, 40, "basic_cast", attacker, HPProtocol.HIT_FINISHER)
	crit_rules["base_chance"] = 0.0
	crit_rules["max_chance"] = max_crit
	SimAuthority.entity_hit.disconnect(listener)
	check(seen.size() == 2 and seen[0][1] & HPProtocol.HIT_CRIT == 0 and int(seen[0][0]) == 40,
		"A hit with no crit chance is plain and carries no crit flag")
	check(seen.size() == 2 and seen[1][1] & HPProtocol.HIT_CRIT != 0 and seen[1][1] & HPProtocol.HIT_FINISHER != 0 		and int(seen[1][0]) == int(round(40 * HPRules.crit_multiplier())), "A critical finisher deals crit damage and reports both flags")
	check(is_equal_approx(HPRules.crit_chance(3.0, true), 3.0 + float(crit_rules.get("finisher_bonus", 0.0))),
		"Enchanted crit chance and the finisher bonus add up")
	attacker["combo_until_tick"] = 0
	var steps: Array = []
	for _i in 3:
		steps.append(SimAuthority._advance_combo(attacker))
	check(steps == [0, 1, 2], "The basic chain advances flick, backhand, finisher")
	attacker["combo_until_tick"] = SimAuthority.sim_tick - 1
	check(SimAuthority._advance_combo(attacker) == 0, "The chain restarts once its window has passed")
	attacker["combo_until_tick"] = 0
	attacker["combo_index"] = 0
	await get_tree().process_frame

## Skill training: one point per level gained, spent on the authority, level 10
## is Master ("M" on the action bar), and the levels persist in `quests.skills`.
func _check_skill_training(player: Node, hud: Node) -> void:
	var record: Dictionary = SimAuthority.record_for(player)
	var saved_level := int(record.get("level", 1))
	record["skill_levels"] = {}
	SimAuthority._push_stats(record)
	check(HPRules.skill_points_available(2, {}) == 1 and HPRules.skill_points_available(1, {}) == 0
		and HPRules.skill_points_available(5, {"stupefy": 3}) == 2, "One skill point per level gained, minus points spent")
	check(HPRules.skill_level_label(9) == "9" and HPRules.skill_level_label(10) == "M", "Level 10 reads as Master")
	check(HPRules.spell_damage("stupefy", 0, "", 1.0, 10) > HPRules.spell_damage("stupefy", 0, "", 1.0, 1)
		and HPRules.cooldown_for("stupefy", "", 10) < HPRules.cooldown_for("stupefy", "", 1), "Trained skills hit harder and recover faster")
	record["level"] = 2
	SimAuthority._push_stats(record)
	var first: Dictionary = SimNet.submit_skill_up(player, "stupefy")
	check(bool(first.get("ok", false)) and HPRules.skill_level_of(record.skill_levels, "stupefy") == 2
		and player.skill_level("stupefy") == 2 and int(player.skill_points) == 0, "A skill point raises the skill on the authority and the body")
	var broke: Dictionary = SimNet.submit_skill_up(player, "incendio")
	check(String(broke.get("reason", "")) == HPProtocol.REJECT_NO_SKILL_POINTS, "Training without a point is refused")
	check(String(SimNet.submit_skill_up(player, "basic_cast").get("reason", "")) == HPProtocol.REJECT_SKILL_UNKNOWN, "The basic attack cannot be trained")
	record["level"] = 20
	record["skill_levels"] = {"stupefy": 9}
	SimAuthority._push_stats(record)
	var master: Dictionary = SimAuthority.skill_up_for_record(record, "stupefy")
	var capped: Dictionary = SimAuthority.skill_up_for_record(record, "stupefy")
	check(bool(master.get("ok", false)) and String(capped.get("reason", "")) == HPProtocol.REJECT_SKILL_MAX
		and player.skill_level("stupefy") == 10, "A skill stops at Master")
	await get_tree().process_frame
	var slot: HudSlot = hud.action_bar.spell_slots[0]
	check(slot.held_id == "stupefy" and slot.badge_text == "M" and hud.action_bar.spell_slots[1].badge_text == "1", "Action bar shows skill levels, M for Master")
	hud.skill_window.open()
	await get_tree().process_frame
	var row: Dictionary = hud.skill_window._rows.get("stupefy", {})
	check(hud.skill_window.is_open() and not row.is_empty() and (row.level as Label).text == "MASTER"
		and (row.button as Button).disabled and not (hud.skill_window._rows.incendio.button as Button).disabled, "Skill window lists levels and offers the points")
	check(hud.handle_escape() == "skills" and not hud.skill_window.is_open(), "Esc closes the skill window")
	check(int((player.persisted_quests().get("skills", {}) as Dictionary).get("stupefy", 0)) == 10, "Skill levels save into the quests object")
	player.restore_quest_state(player.persisted_quests())
	SimAuthority._load_quest_state(record, player)
	check(HPRules.skill_level_of(record.skill_levels, "stupefy") == 10, "Skill levels restore onto the authority record")
	record["skill_levels"] = {}
	player.skill_levels = {}
	record["level"] = saved_level
	SimAuthority._push_stats(record)

func _check_house_standing(player: Node, hud: Node) -> void:
	check(HPRules.max_house_rank() == 7 and HPRules.house_rank_for(0) == 1 and HPRules.house_rank_for(99) == 1 \
		and HPRules.house_rank_for(100) == 2 and HPRules.house_rank_for(2400) == 7, "House rank table has seven ranks")
	check(HPRules.clamp_house_rep(999999) == HPRules.max_house_rep() and HPRules.clamp_house_rep(-5) == 0, "House reputation is clamped to the rank table")
	check(player.house_rep == 0 and player.house_rank() == 1, "A sheet without house standing starts at rank 1")
	player.add_house_rep(120)
	await get_tree().process_frame
	var record: Dictionary = SimAuthority.record_for(player)
	var stats: Dictionary = SimAuthority.build_stats(record)
	check(player.house_rep == 120 and int(record.get("house_rep", -1)) == 120 and int(stats.get("house_rank", 0)) == 2 \
		and int(stats.get("house_next_rep", 0)) == 250, "Authority grants house reputation and reports the rank")
	check(hud.unit_frame.house_rank == 2 and hud.unit_frame.house_rep == 120, "Unit frame shows the house rank")
	check(hud.notices.visible_texts().any(func(t): return String(t).contains("Rank 2")), "Rank up raises a HUD notice")
	# Persistence: the free-form quests object round-trips, unknown keys survive.
	player.restore_quest_state({"house_rep": 900.0, "future_key": {"a": 1}})
	var persisted: Dictionary = player.persisted_quests()
	check(player.house_rank() == 5 and int(persisted.house_rep) == 900 and persisted.has("future_key"), "House standing restores from and saves into the quests object")
	var bridge: Node = load("res://addons/hpmmo_sim/persistence.gd").new()
	var payload: Dictionary = bridge.character_payload(player, record)
	bridge.free()
	check(int((payload.get("quests", {}) as Dictionary).get("house_rep", -1)) == 900, "World save payload carries house standing")
	# Gating: a spell that names a house rank is refused below it.
	record["house_rep"] = 0
	var spell: Dictionary = HPRules.spell("protego")
	spell["requires_house_rank"] = 3
	var refused: Dictionary = SimAuthority.cast_for_record(record, "protego", Vector3.ZERO, 900001)
	spell.erase("requires_house_rank")
	check(String(refused.get("reason", "")) == HPProtocol.REJECT_HOUSE_RANK, "Spells gated by house rank are refused below it")
	record["house_rep"] = player.house_rep

## Quests are decided by the authority: talk is range-checked against the NPC,
## kills count by species from the kill credit, refinement counts on the
## server's own success, a visit is the body's position (and broom), and the
## reward is paid once. The QuestManager only mirrors the chain position.
func _check_server_quests(player: Node) -> void:
	var record: Dictionary = SimAuthority.record_for(player)
	var peer := int(record.get("peer_id", 0))
	var home: Vector3 = player.global_position
	var completed: Array = []
	var on_completed := func(id: String): completed.append(id)
	QuestManager.quest_completed.connect(on_completed)
	_set_quest(record, 0, 0)
	await get_tree().process_frame
	check(QuestManager.active_index == 0 and String(QuestManager.current_quest().get("id", "")) == "welcome", "Quest view mirrors the authority's chain position")

	# Talk: the NPC must exist and the body must stand beside it.
	var fig: Node3D = world.get_node("NPCs/ProfessorFig")
	player.global_position = fig.global_position + Vector3(30, 0, 0)
	var far: Dictionary = SimAuthority.request_talk(peer, "Professor Fig")
	check(String(far.get("reason", "")) == HPProtocol.REJECT_RANGE and int(record.quest_active) == 0, "Talking from out of range does not count")
	check(String(SimAuthority.request_talk(peer, "Nobody").get("reason", "")) == HPProtocol.REJECT_NO_TARGET, "Talking to an unknown NPC is refused")
	player.global_position = fig.global_position + Vector3(1.5, 0, 0)
	var gold_before: int = player.galleons
	var rep_before: int = player.house_rep
	var exp_before: int = player.current_exp
	var level_before: int = player.level
	var near: Dictionary = SimAuthority.request_talk(peer, "Professor Fig")
	await get_tree().process_frame
	check(bool(near.get("ok", false)) and int(record.quest_active) == 1 and player.quest_active == 1 and QuestManager.active_index == 1, "In-range talk completes the talk quest on the authority")
	check(player.galleons == gold_before + 150 and player.house_rep == rep_before + 25 \
		and (player.current_exp != exp_before or player.level != level_before), "Quest completion pays EXP, Galleons and house reputation")
	check(completed == ["welcome"], "Quest view announces the completion once")
	SimAuthority.request_talk(peer, "Professor Fig")
	check(int(record.quest_active) == 1 and player.galleons == gold_before + 150, "Repeating a finished conversation pays nothing")

	# Kill: a real kill credit counts by species; another species does not.
	SimAuthority.quest_event(record, "kill", "inferi")
	check(int(record.quest_progress) == 0, "A kill of another species does not count")
	# A summoned spider of its own, far from the authored packs the encounter
	# checks below stage (the same way a monolith wave brings one in).
	var spider_node: Node3D = preload("res://scenes/entities/mobs/mob_acromantula.tscn").instantiate()
	var spot := _g(260, -170)
	spider_node.summoned = true
	spider_node.pack_anchor = spot
	spider_node.spawn_point = spot
	world.get_node("Mobs").add_child(spider_node)
	spider_node.global_position = spot
	SimAuthority.register_mob(spider_node, 0, String(HPRules.zone_id_for(spot)))
	var spider: Dictionary = SimAuthority.record_for(spider_node)
	check(SimAuthority._mob_species(spider) == "acromantula", "A kill quest reads the mob's species from its scene")
	SimAuthority._apply_damage(spider, 999999, "basic_cast", record)
	check(bool(spider.get("dead", false)) and int(record.quest_progress) == 1, "An authoritative Acromantula kill advances the hunt")
	for _i in range(4 - int(record.quest_progress)):
		SimAuthority.quest_event(record, "kill", "acromantula")
	check(int(record.quest_active) == 2 and completed.has("rats"), "Four Acromantula kills complete the hunt")

	# Monolith credit.
	_set_quest(record, 3, 0)
	SimAuthority.quest_event(record, "monolith", "")
	check(int(record.quest_active) == 4, "Monolith credit completes the monolith quest")

	# Refine: two successful refinements through the real equipment request.
	record["last_combat_tick"] = -100000
	player.equipment["main_hand"] = {"id": "wand_hawthorn", "tier": 0}
	player.add_loot("mat_phoenix_ash", 2)
	player.galleons += 1000
	SimAuthority.refresh_equipment(record)
	for i in range(2):
		var answer: Dictionary = SimAuthority.request_equipment(peer, 70000 + i, player.inventory_revision, "refine", "main_hand", "", 0)
		check(String(answer.get("reason", "")) == "refined", "Refinement %d succeeds on the authority" % (i + 1))
	check(int(record.quest_active) == 5 and completed.has("refine"), "Two refinements complete Ollivander's quest")

	# Visit: the server checks the body's position, and this quest wants the broom.
	var pitch: Vector3 = _g(330, -330) + Vector3(0, 6, 0)
	check(HPRules.quest_place_at(HPProtocol.DEFAULT_MAP, pitch) == "Quidditch Pitch" \
		and world.overlay.zone_at(pitch) == "Quidditch Pitch", "The pitch is a named place for the server and the zone banner")
	player.global_position = pitch
	var was_mounted := bool(record.get("mounted", false))
	record["mounted"] = false
	SimAuthority._tick_quest_visits()
	check(int(record.quest_active) == 5, "Walking onto the pitch without the broom does not count")
	record["mounted"] = true
	SimAuthority._tick_quest_visits()
	record["mounted"] = was_mounted
	await get_tree().process_frame
	check(int(record.quest_active) == 6 and QuestManager.is_all_done(), "Flying onto the pitch completes the chain")

	# Persistence: the chain position is what the save writes.
	var bridge: Node = load("res://addons/hpmmo_sim/persistence.gd").new()
	var saved: Dictionary = (bridge.character_payload(player, record).get("quests", {}) as Dictionary)
	bridge.free()
	check(int(saved.get("active", -1)) == 6 and (saved.get("done", []) as Array).has("broom"), "The save carries the quest chain position")
	QuestManager.quest_completed.disconnect(on_completed)
	player.global_position = home
	_set_quest(record, 0, 0)

func _set_quest(record: Dictionary, index: int, progress: int) -> void:
	record["quest_active"] = index
	record["quest_progress"] = progress
	SimAuthority._store_quest_state(record)
	SimAuthority._push_stats(record)
