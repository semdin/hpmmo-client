extends CharacterBody3D

## 3D Wizard Player Controller (Metin2 MMO Style)
## Decoupled 3rd-person camera, animated 3D wizard model, wand combat, broom mount, and Ollivander auras

signal stats_changed(hp: int, max_hp: int, mana: int, max_mana: int, exp: int, max_exp: int, level: int)
signal target_changed(target_node: Node3D)
signal spell_cast_signal(spell_id: String, cooldown: float)
signal loot_collected_signal(item_id: String, amount: int)
signal mounted_changed(is_mounted: bool)

# Player Info
@export var player_name: String = "Harry"
@export var house: String = "Gryffindor"
@export var wand_tier: int = 0
@export var is_local_player: bool = true

# Base Stats
var level: int = 1
var current_exp: int = 0
var max_exp: int = 200
var max_hp: int = 500
var current_hp: int = 500
var max_mana: int = 300
var current_mana: int = 300
var galleons: int = 500
var inventory: Array[Dictionary] = []

# Movement & Speeds
var walk_speed: float = 8.5
var mounted_speed: float = 15.0
var is_mounted: bool = false
var gravity: float = 24.0

# Decoupled Camera Orbit
var camera_rot_x: float = -20.0
var camera_rot_y: float = 0.0
var camera_distance: float = 8.0
var mouse_orbit_active: bool = false

# Combat & Targeting
var current_target: Node3D = null
var spell_cooldowns: Dictionary = {}
var is_protego_active: bool = false
var is_casting_anim: bool = false

# Node References
@onready var visuals: Node3D = $Visuals
@onready var anim_player: AnimationPlayer = $Visuals/wizard/AnimationPlayer
@onready var camera_pivot: Node3D = $CameraPivot
@onready var spring_arm: SpringArm3D = $CameraPivot/SpringArm3D
@onready var camera: Camera3D = $CameraPivot/SpringArm3D/Camera3D
@onready var broom_mesh: MeshInstance3D = $Visuals/BroomMesh
@onready var broom_particles: CPUParticles3D = $Visuals/BroomMesh/BroomParticles
@onready var wand_aura_particles: CPUParticles3D = $Visuals/WandAuraParticles
@onready var wand_tip: Marker3D = $Visuals/WandTipMarker
@onready var nameplate: Label3D = $NameplateLabel3D

const PROJECTILE_SCENE = preload("res://scenes/spells/spell_projectile.tscn")
const PROTEGO_SCENE = preload("res://scenes/spells/protego_shield.tscn")
const FT_SCENE = preload("res://scenes/ui/floating_text.tscn")

func _ready() -> void:
	add_to_group("players")
	
	if is_local_player:
		var nm = get_node_or_null("/root/NetworkManager")
		if nm:
			player_name = nm.local_player_name
			house = nm.local_player_house
	
	# Decouple camera pivot from player rotation completely
	camera_pivot.top_level = true
	camera_pivot.global_position = global_position + Vector3(0, 1.4, 0)
	camera_pivot.rotation_degrees = Vector3(0, camera_rot_y, 0)
	spring_arm.rotation_degrees = Vector3(camera_rot_x, 0, 0)
	spring_arm.spring_length = camera_distance
	
	_setup_character_model()
	_apply_house_customization()
	_apply_wand_aura()
	_update_nameplate()
	_init_starter_inventory()
	
	if not is_local_player:
		camera.current = false
		camera_pivot.hide()
	else:
		camera.current = true
		emit_stats()

func _setup_character_model() -> void:
	# Hide staff and closed spellbook, show 1H wand and cape
	var staff = visuals.get_node_or_null("wizard/Rig/Skeleton3D/handslot_r/2H_Staff")
	if staff:
		staff.hide()
	var spellbook = visuals.get_node_or_null("wizard/Rig/Skeleton3D/handslot_l/Spellbook")
	if spellbook:
		spellbook.hide()
	var spellbook_open = visuals.get_node_or_null("wizard/Rig/Skeleton3D/handslot_l/Spellbook_open")
	if spellbook_open:
		spellbook_open.hide()

func _apply_house_customization() -> void:
	if not GameData.HOUSES.has(house):
		return
	var h_data = GameData.HOUSES[house]
	var primary_col: Color = h_data.primary_color
	
	# Tint cape with Hogwarts house primary color
	var cape = visuals.get_node_or_null("wizard/Rig/Skeleton3D/chest/Mage_Cape")
	if cape and cape is MeshInstance3D:
		var mat = StandardMaterial3D.new()
		mat.albedo_color = primary_col
		mat.roughness = 0.5
		cape.set_surface_override_material(0, mat)
	
	if house == "Hufflepuff":
		max_hp = 625
		current_hp = 625
	elif house == "Ravenclaw":
		max_mana = 375
		current_mana = 375

func _update_nameplate() -> void:
	if nameplate:
		nameplate.text = "[%s]\n%s (Lv.%d)" % [house, player_name, level]
		if GameData.HOUSES.has(house):
			nameplate.modulate = GameData.HOUSES[house].secondary_color

func _init_starter_inventory() -> void:
	inventory.clear()
	inventory.append({"id": "wand_hawthorn", "amount": 1, "tier": wand_tier})
	inventory.append({"id": "robe_apprentice", "amount": 1, "tier": 0})
	inventory.append({"id": "broom_nimbus2000", "amount": 1, "tier": 0})
	inventory.append({"id": "mat_phoenix_ash", "amount": 5, "tier": 0})
	inventory.append({"id": "mat_dragon_heartstring", "amount": 2, "tier": 0})
	inventory.append({"id": "potion_health", "amount": 5, "tier": 0})
	inventory.append({"id": "potion_mana", "amount": 5, "tier": 0})

func _unhandled_input(event: InputEvent) -> void:
	if not is_local_player:
		return
	
	# Mouse look on right-click hold (Classic MMO / Metin2 feel)
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT:
			mouse_orbit_active = event.pressed
		elif event.button_index == MOUSE_BUTTON_WHEEL_UP:
			camera_distance = clamp(camera_distance - 0.8, 3.0, 16.0)
			spring_arm.spring_length = camera_distance
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			camera_distance = clamp(camera_distance + 0.8, 3.0, 16.0)
			spring_arm.spring_length = camera_distance
		elif event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
			if not _try_click_target():
				cast_spell("basic_cast")
	
	elif event is InputEventMouseMotion and mouse_orbit_active:
		camera_rot_y -= event.relative.x * 0.28
		camera_rot_x = clamp(camera_rot_x - event.relative.y * 0.25, -70.0, 25.0)

func _process(delta: float) -> void:
	# Tick spell cooldowns
	for spell_id in spell_cooldowns.keys():
		spell_cooldowns[spell_id] = max(0.0, spell_cooldowns[spell_id] - delta)
	
	# Passive Regen
	current_mana = min(max_mana, current_mana + int(8 * delta))
	current_hp = min(max_hp, current_hp + int(4 * delta))
	
	if is_local_player:
		_handle_hotkeys()

func _physics_process(delta: float) -> void:
	# Update decoupled camera pivot position & rotation smoothly
	if is_local_player and is_instance_valid(camera_pivot):
		camera_pivot.global_position = camera_pivot.global_position.lerp(global_position + Vector3(0, 1.4, 0), 20.0 * delta)
		camera_pivot.rotation_degrees.y = camera_rot_y
		spring_arm.rotation_degrees.x = camera_rot_x
	
	if not is_local_player:
		return
	
	# Gravity & Mounting
	if not is_on_floor() and not is_mounted:
		velocity.y -= gravity * delta
	elif is_mounted:
		velocity.y = 0.0
	
	# Input direction relative to camera yaw
	var input_dir := Vector2.ZERO
	if Input.is_action_pressed("move_forward"):
		input_dir.y -= 1
	if Input.is_action_pressed("move_backward"):
		input_dir.y += 1
	if Input.is_action_pressed("move_left"):
		input_dir.x -= 1
	if Input.is_action_pressed("move_right"):
		input_dir.x += 1
	input_dir = input_dir.normalized()
	
	var active_speed := mounted_speed if is_mounted else walk_speed
	var is_moving := input_dir.length_squared() > 0.01
	
	if is_moving:
		# Calculate movement vector relative to camera yaw
		var cam_yaw: float = deg_to_rad(camera_rot_y)
		var forward := Vector3(-sin(cam_yaw), 0, -cos(cam_yaw))
		var right := Vector3(cos(cam_yaw), 0, -sin(cam_yaw))
		var move_vector := (right * input_dir.x + forward * -input_dir.y).normalized()
		
		velocity.x = move_vector.x * active_speed
		velocity.z = move_vector.z * active_speed
		
		# Rotate ONLY visuals towards move direction (Camera remains independent!)
		var target_yaw := atan2(move_vector.x, move_vector.z)
		visuals.rotation.y = lerp_angle(visuals.rotation.y, target_yaw, 14.0 * delta)
		
		if not is_casting_anim and is_instance_valid(anim_player):
			var run_anim := "Running_A" if not is_mounted else "Idle"
			if anim_player.current_animation != run_anim:
				anim_player.play(run_anim, 0.2)
	else:
		velocity.x = move_toward(velocity.x, 0, active_speed * 12.0 * delta)
		velocity.z = move_toward(velocity.z, 0, active_speed * 12.0 * delta)
		
		# If holding right-click while standing, face camera direction
		if mouse_orbit_active:
			var cam_yaw: float = deg_to_rad(camera_rot_y)
			visuals.rotation.y = lerp_angle(visuals.rotation.y, cam_yaw, 10.0 * delta)
		
		if not is_casting_anim and is_instance_valid(anim_player):
			if anim_player.current_animation != "Idle":
				anim_player.play("Idle", 0.25)
	
	move_and_slide()

func _handle_hotkeys() -> void:
	if Input.is_action_just_pressed("spell_1"):
		cast_spell("stupefy")
	elif Input.is_action_just_pressed("spell_2"):
		cast_spell("incendio")
	elif Input.is_action_just_pressed("spell_3"):
		cast_spell("bombarda")
	elif Input.is_action_just_pressed("spell_4"):
		cast_spell("expelliarmus")
	elif Input.is_action_just_pressed("spell_q"):
		cast_spell("protego")
	elif Input.is_action_just_pressed("spell_e"):
		cast_spell("ultimate")
	elif Input.is_action_just_pressed("mount_broom"):
		toggle_broom_mount()
	elif Input.is_action_just_pressed("target_cycle"):
		cycle_nearest_target()
	elif Input.is_action_just_pressed("pickup_loot"):
		pickup_nearest_loot()

func toggle_broom_mount() -> void:
	is_mounted = !is_mounted
	broom_mesh.visible = is_mounted
	if broom_particles:
		broom_particles.emitting = is_mounted
	
	if is_mounted:
		visuals.position.y = 0.55
		_spawn_floating_text("Mounted Nimbus 2000!", Color(1.0, 0.85, 0.2))
	else:
		visuals.position.y = 0.0
		_spawn_floating_text("Dismounted", Color(0.8, 0.8, 0.8))
	
	emit_signal("mounted_changed", is_mounted)

func cast_spell(spell_id: String) -> void:
	if not GameData.SPELLS.has(spell_id):
		return
	
	var s_data: Dictionary = GameData.SPELLS[spell_id]
	if spell_cooldowns.get(spell_id, 0.0) > 0.0:
		return
	
	var cost: int = s_data.mana_cost
	if current_mana < cost:
		_spawn_floating_text("Not enough Mana!", Color(0.3, 0.6, 1.0))
		return
	
	current_mana -= cost
	var cd: float = s_data.cooldown
	if house == "Ravenclaw":
		cd *= 0.8
	spell_cooldowns[spell_id] = cd
	
	emit_signal("spell_cast_signal", spell_id, cd)
	emit_stats()
	
	# Play wand flick animation
	_play_cast_animation()
	
	# Aim direction
	var spawn_pos := wand_tip.global_position if wand_tip else global_position + Vector3(0, 1.2, 0)
	var cast_dir := Vector3.FORWARD
	
	if is_instance_valid(current_target):
		var target_center = current_target.global_position + Vector3(0, 1.2, 0)
		cast_dir = (target_center - spawn_pos).normalized()
		# Face target smoothly
		var look_pos = current_target.global_position
		look_pos.y = global_position.y
		var to_target = (look_pos - global_position).normalized()
		visuals.rotation.y = atan2(to_target.x, to_target.z)
	else:
		var cam_yaw: float = deg_to_rad(camera_rot_y)
		cast_dir = Vector3(-sin(cam_yaw), 0, -cos(cam_yaw)).normalized()
		visuals.rotation.y = cam_yaw
	
	# Multipliers
	var upgrade_info = GameData.UPGRADE_TABLE.get(wand_tier, {})
	var damage_mult: float = upgrade_info.get("multiplier", 1.0)
	if house == "Gryffindor" and spell_id == "incendio":
		damage_mult *= 1.15
	elif house == "Slytherin" and (spell_id == "ultimate" or spell_id == "expelliarmus"):
		damage_mult *= 1.20
	
	if spell_id == "protego":
		_activate_protego()
	else:
		var proj = PROJECTILE_SCENE.instantiate()
		get_parent().add_child(proj)
		proj.global_position = spawn_pos
		proj.setup(self, spell_id, cast_dir, current_target, damage_mult)

func _play_cast_animation() -> void:
	if not is_instance_valid(anim_player):
		return
	is_casting_anim = true
	anim_player.play("Spellcast_Shoot", 0.1)
	await get_tree().create_timer(0.4).timeout
	is_casting_anim = false

func _activate_protego() -> void:
	is_protego_active = true
	var p_shield = PROTEGO_SCENE.instantiate()
	add_child(p_shield)
	p_shield.setup(self)
	_spawn_floating_text("PROTEGO!", Color(0.2, 0.8, 1.0), 1.2)
	await get_tree().create_timer(3.5).timeout
	is_protego_active = false

func take_damage(amount: int, spell_type: String, attacker: Node3D) -> void:
	var actual_dmg := amount
	if is_protego_active:
		actual_dmg = int(amount * 0.5)
		_spawn_floating_text("BLOCKED 50%!", Color(0.3, 0.7, 1.0))
	
	current_hp = max(0, current_hp - actual_dmg)
	_spawn_floating_text(str(actual_dmg), Color(1.0, 0.2, 0.2), 1.3)
	
	if is_instance_valid(anim_player) and not is_casting_anim and current_hp > 0:
		anim_player.play("Hit_A", 0.1)
	
	emit_stats()
	if current_hp <= 0:
		_die()

func _die() -> void:
	if is_instance_valid(anim_player):
		anim_player.play("Death_A", 0.1)
	_spawn_floating_text("DEFEATED!", Color(1.0, 0.0, 0.0), 2.0)
	await get_tree().create_timer(2.5).timeout
	global_position = Vector3(0, 0.5, 5.0)
	current_hp = max_hp
	current_mana = max_mana
	if is_instance_valid(anim_player):
		anim_player.play("Idle", 0.2)
	emit_stats()

func add_exp(amount: int) -> void:
	current_exp += amount
	_spawn_floating_text("+%d EXP" % amount, Color(0.3, 1.0, 0.5), 1.2)
	while current_exp >= max_exp:
		current_exp -= max_exp
		level += 1
		max_exp = int(max_exp * 1.5)
		max_hp += 40
		current_hp = max_hp
		max_mana += 25
		current_mana = max_mana
		_update_nameplate()
		_spawn_floating_text("LEVEL UP! (Lv.%d)" % level, Color(1.0, 0.85, 0.2), 1.8)
	emit_stats()

func add_loot(item_id: String, amount: int) -> void:
	if item_id == "galleons":
		galleons += amount
		emit_signal("loot_collected_signal", "galleons", amount)
		return
	
	var found := false
	for item in inventory:
		if item.id == item_id:
			item.amount += amount
			found = true
			break
	if not found:
		inventory.append({"id": item_id, "amount": amount, "tier": 0})
	
	emit_signal("loot_collected_signal", item_id, amount)

func pickup_nearest_loot() -> void:
	var loot_nodes = get_tree().get_nodes_in_group("loot")
	var nearest_loot: Area3D = null
	var min_dist: float = 7.0
	for loot in loot_nodes:
		if is_instance_valid(loot):
			var dist = global_position.distance_to(loot.global_position)
			if dist < min_dist:
				min_dist = dist
				nearest_loot = loot
	if nearest_loot and nearest_loot.has_method("collect"):
		nearest_loot.collect(self)

func cycle_nearest_target() -> void:
	var targets = get_tree().get_nodes_in_group("targetable")
	var nearest: Node3D = null
	var min_dist: float = 35.0
	for t in targets:
		if is_instance_valid(t) and t != self:
			if "state" in t and t.state == 5:
				continue
			if "is_destroyed" in t and t.is_destroyed:
				continue
			var dist = global_position.distance_to(t.global_position)
			if dist < min_dist:
				min_dist = dist
				nearest = t
	set_target(nearest)

func set_target(node: Node3D) -> void:
	current_target = node
	emit_signal("target_changed", current_target)

func _try_click_target() -> bool:
	var mouse_pos := get_viewport().get_mouse_position()
	var from := camera.project_ray_origin(mouse_pos)
	var to := from + camera.project_ray_normal(mouse_pos) * 60.0
	var space := get_world_3d().direct_space_state
	var query := PhysicsRayQueryParameters3D.create(from, to)
	query.collision_mask = 2
	var result := space.intersect_ray(query)
	if result:
		var collider = result.collider
		if collider.is_in_group("targetable"):
			set_target(collider)
			return true
	return false

func upgrade_wand(new_tier: int) -> void:
	wand_tier = clamp(new_tier, 0, 9)
	_apply_wand_aura()
	_spawn_floating_text("WAND REFINED TO +%d!" % wand_tier, Color(1.0, 0.9, 0.2), 1.6)

func _apply_wand_aura() -> void:
	if not wand_aura_particles:
		return
	var up_info = GameData.UPGRADE_TABLE.get(wand_tier, {})
	var aura_color: Color = up_info.get("aura", Color.TRANSPARENT)
	if wand_tier >= 4:
		wand_aura_particles.emitting = true
		wand_aura_particles.color = aura_color
		wand_aura_particles.amount = 20 if wand_tier < 7 else (40 if wand_tier < 9 else 70)
	else:
		wand_aura_particles.emitting = false

func _spawn_floating_text(text: String, col: Color, scale_mult: float = 1.0) -> void:
	if FT_SCENE:
		var ft = FT_SCENE.instantiate()
		get_parent().add_child(ft)
		ft.global_position = global_position + Vector3(0, 2.2, 0)
		ft.setup(text, col, scale_mult)

func emit_stats() -> void:
	emit_signal("stats_changed", current_hp, max_hp, current_mana, max_mana, current_exp, max_exp, level)
