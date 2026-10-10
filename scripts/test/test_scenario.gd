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

func _ready() -> void:
	await get_tree().create_timer(0.4).timeout
	var player = world.local_player
	var hud = world.hud
	var director = world.get_node("EncounterDirector")
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
	hp_before = dummy.current_hp
	projectile._handle_hit(dummy)
	projectile._handle_hit(dummy)
	check(dummy.current_hp == hp_before - 40, "Duplicate body/swept collisions deal damage only once")
	check(not Rules.can_damage(player, player), "Friendly fire is rejected")
	check(not Rules.can_damage(player, world.get_node("NPCs/ProfessorFig")), "Peaceful NPCs cannot be attacked")
	FX.play_impact(world, Vector3(0, 1, 0), "expelliarmus")
	check(absf(Rules.safe_up(Vector3.UP).dot(Vector3.UP)) < 0.01, "Vertical spell effect uses a non-collinear up vector")
	await get_tree().create_timer(0.4).timeout
	check(director.packs.size() == 7, "Seven encounter groups created")
	for pack in director.packs:
		check(pack.members.size() == pack.count, "Encounter has its configured 3/5 pack or boss composition")
		for member in pack.members:
			check(member.spawn_point.distance_to(member.global_position) < 8, "Spawn anchor is assigned before mob ready")
	# Ordinary mobs are reactive; protected volumes gate damage.
	# Fixed staging point far from every authored volume keeps these checks
	# deterministic regardless of the random pack anchors.
	var staging := Vector3(-70, 0.1, 20)
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
	player.global_position = Vector3(0, 0.1, 5)
	await get_tree().create_timer(0.12).timeout
	check(passive_mob.target_player == null and passive_pack.members[1].target_player == null and passive_mob.state not in [passive_mob.State.CHASE, passive_mob.State.ATTACK], "Mobs drop the fight when the target enters the courtyard")
	var zone_mob = director.packs[2].members[0]
	check(SafeZone.is_protected_point(Vector3(0, 0, 5)) and not SafeZone.is_protected_point(Vector3(60, 0, 60)), "Safe-zone volumes are authored at specific locations")
	check(not Rules.can_damage(zone_mob, player), "Mobs cannot attack a player inside the courtyard")
	check(not Rules.can_damage(player, zone_mob), "Protected players cannot snipe outdoor mobs")
	check(Rules.can_damage(player, dummy), "Training dummies remain practiceable inside the courtyard")
	zone_mob.global_position = Vector3(-70, 0.1, -20)
	player.global_position = Vector3(-62, 0.1, -20)
	check(Rules.can_damage(player, zone_mob), "Outside protected space, combat is allowed")
	check(not director._formation_clear(Vector3(0, 0.1, 0), 5) and director._formation_clear(Vector3(60, 0.1, 60), 5), "Encounter spawn sampling rejects protected anchors and rings")
	var stray = director.packs[3].members[0]
	stray.global_position = Vector3(0, 0.1, -2)
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
	player.global_position = Vector3(0, 0.1, 5)
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
	# Structural collision sweeps prove a connected indoor route and solid walls.
	await get_tree().physics_frame
	var space = world.get_world_3d().direct_space_state
	for route in [[Vector3(0, 1, -38), Vector3(0, 1, -86)], [Vector3(0, 1, -72), Vector3(-24, 1, -72)], [Vector3(0, 1, -72), Vector3(26, 1, -72)]]:
		var query := PhysicsRayQueryParameters3D.create(route[0], route[1], 1)
		check(space.intersect_ray(query).is_empty(), "Castle entrance and both side rooms are traversable")
	check(not space.intersect_ray(PhysicsRayQueryParameters3D.create(Vector3(0, 2, -57), Vector3(18, 2, -57), 1)).is_empty(), "Great Hall walls block movement/spells")
	player.set_target(null)
	player.global_position = Vector3(0, 0.15, -38)
	player.velocity = Vector3.ZERO
	Input.action_press("move_forward")
	await get_tree().create_timer(3.0).timeout
	Input.action_release("move_forward")
	check(player.global_position.z < -59, "Actual character movement enters the castle through the doorway")
	player.global_position = Vector3(0, 0.15, -72)
	player.velocity = Vector3.ZERO
	Input.action_press("move_left")
	await get_tree().create_timer(3.0).timeout
	Input.action_release("move_left")
	check(player.global_position.x < -22, "Actual character movement reaches the library through the cross aisle")
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
	player.global_position = Vector3(0, 0.1, 5)
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
	player.global_position.y = 12
	player.toggle_broom_mount()
	check(player.is_mounted, "High-altitude dismount is rejected")
	await get_tree().create_timer(0.35).timeout
	player.global_position.y = 1.5
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
