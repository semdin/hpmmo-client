extends CharacterBody3D

## MobBase - Base AI Controller for Harry Potter hostile creatures
## Implements Metin2-style pack aggro, wandering, combat, weakness, and loot drops

enum State { IDLE, WANDER, CHASE, ATTACK, STUNNED, DEAD }

@export var mob_name: String = "Dark Creature"
@export var level: int = 10
@export var max_hp: int = 250
@export var attack_power: int = 25
@export var move_speed: float = 6.0
@export var aggro_radius: float = 12.0
@export var attack_range: float = 2.2
@export var attack_cooldown: float = 1.4
@export var exp_reward: int = 65
@export var weak_to_fire: bool = false
@export var is_ranged: bool = false

var current_hp: int = 250
var state: State = State.IDLE
var target_player: Node3D = null
var spawn_point: Vector3 = Vector3.ZERO
var attack_timer: float = 0.0
var stun_timer: float = 0.0
var wander_timer: float = 0.0
var wander_target: Vector3 = Vector3.ZERO
var knockback_velocity: Vector3 = Vector3.ZERO

@onready var label: Label3D = $Label3D
@onready var mesh: MeshInstance3D = $MeshInstance3D

const LOOT_SCENE = preload("res://scenes/entities/loot/loot_drop.tscn")
const PROJECTILE_SCENE = preload("res://scenes/spells/spell_projectile.tscn")

func _ready() -> void:
	add_to_group("mobs")
	add_to_group("targetable")
	current_hp = max_hp
	spawn_point = global_position
	_update_label()

func _update_label() -> void:
	if label:
		label.text = "[Lv.%d] %s\n%d / %d" % [level, mob_name, current_hp, max_hp]
		var ratio := float(current_hp) / float(max_hp)
		if ratio > 0.5:
			label.modulate = Color(1.0, 0.4, 0.4)
		else:
			label.modulate = Color(1.0, 0.15, 0.15)

func _physics_process(delta: float) -> void:
	if state == State.DEAD:
		return
	
	# Knockback decay
	if knockback_velocity.length_squared() > 0.1:
		velocity = knockback_velocity
		knockback_velocity = knockback_velocity.lerp(Vector3.ZERO, 6.0 * delta)
		move_and_slide()
		return
	
	# Handle Stun
	if state == State.STUNNED:
		stun_timer -= delta
		if stun_timer <= 0.0:
			state = State.CHASE if is_instance_valid(target_player) else State.IDLE
		velocity = Vector3.ZERO
		move_and_slide()
		return
	
	attack_timer = max(0.0, attack_timer - delta)
	
	match state:
		State.IDLE:
			_process_idle(delta)
		State.WANDER:
			_process_wander(delta)
		State.CHASE:
			_process_chase(delta)
		State.ATTACK:
			_process_attack(delta)
	
	move_and_slide()

func _process_idle(delta: float) -> void:
	velocity = Vector3.ZERO
	wander_timer -= delta
	if wander_timer <= 0.0:
		wander_timer = randf_range(2.0, 5.0)
		# Pick random point near spawn
		var angle := randf() * TAU
		var dist := randf_range(2.0, 6.0)
		wander_target = spawn_point + Vector3(cos(angle) * dist, 0, sin(angle) * dist)
		state = State.WANDER
	
	_scan_for_players()

func _process_wander(delta: float) -> void:
	var dir := (wander_target - global_position)
	dir.y = 0
	if dir.length() < 1.0:
		state = State.IDLE
		wander_timer = randf_range(2.0, 4.0)
		return
	
	velocity = dir.normalized() * (move_speed * 0.4)
	look_at(global_position + dir.normalized(), Vector3.UP)
	_scan_for_players()

func _scan_for_players() -> void:
	var players = get_tree().get_nodes_in_group("players")
	for p in players:
		if p.global_position.distance_to(global_position) <= aggro_radius:
			aggro_on(p)
			break

func aggro_on(player_node: Node3D) -> void:
	if state == State.DEAD or not is_instance_valid(player_node):
		return
	target_player = player_node
	state = State.CHASE
	
	# Metin2 Pack Pull: Alert nearby friendly mobs within 9 meters!
	var nearby_mobs = get_tree().get_nodes_in_group("mobs")
	for m in nearby_mobs:
		if m != self and is_instance_valid(m) and m.state == State.IDLE or m.state == State.WANDER:
			if m.global_position.distance_to(global_position) <= 9.0:
				m.target_player = player_node
				m.state = State.CHASE

func _process_chase(delta: float) -> void:
	if not is_instance_valid(target_player):
		state = State.IDLE
		return
	
	var dist_to_spawn := global_position.distance_to(spawn_point)
	if dist_to_spawn > 35.0: # Leash reset
		target_player = null
		state = State.WANDER
		wander_target = spawn_point
		return
	
	var dist_to_target := global_position.distance_to(target_player.global_position)
	var active_range := attack_range if not is_ranged else 16.0
	
	if dist_to_target <= active_range:
		state = State.ATTACK
		velocity = Vector3.ZERO
		return
	
	var dir := (target_player.global_position - global_position)
	dir.y = 0
	velocity = dir.normalized() * move_speed
	look_at(global_position + dir.normalized(), Vector3.UP)

func _process_attack(delta: float) -> void:
	if not is_instance_valid(target_player):
		state = State.IDLE
		return
	
	var dist := global_position.distance_to(target_player.global_position)
	var active_range := attack_range if not is_ranged else 18.0
	if dist > active_range * 1.3:
		state = State.CHASE
		return
	
	velocity = Vector3.ZERO
	# Face target
	var face_pos := target_player.global_position
	face_pos.y = global_position.y
	look_at(face_pos, Vector3.UP)
	
	if attack_timer <= 0.0:
		attack_timer = attack_cooldown
		_execute_attack()

func _execute_attack() -> void:
	if not is_instance_valid(target_player):
		return
	
	if is_ranged:
		# Shoot dark bolt
		var proj = PROJECTILE_SCENE.instantiate()
		get_parent().add_child(proj)
		var spawn_pos := global_position + Vector3(0, 1.2, 0)
		proj.global_position = spawn_pos
		var dir := (target_player.global_position + Vector3(0, 1.0, 0) - spawn_pos).normalized()
		proj.setup(self, "stupefy", dir, target_player)
		proj.damage = attack_power
		proj.spell_color = Color(0.1, 0.9, 0.3) # Dark green curse bolt
	else:
		# Melee strike
		if target_player.has_method("take_damage"):
			target_player.take_damage(attack_power, "melee", self)

func take_damage(amount: int, spell_type: String, attacker: Node3D) -> void:
	if state == State.DEAD:
		return
	
	# Fire weakness multiplier (e.g. Inferi take 200% damage from Incendio)
	var actual_damage := amount
	if weak_to_fire and spell_type == "incendio":
		actual_damage = int(amount * 2.0)
	
	current_hp = max(0, current_hp - actual_damage)
	_update_label()
	
	# Stun effect
	if spell_type == "stupefy":
		state = State.STUNNED
		stun_timer = 1.8
		var ft_scene = load("res://scenes/ui/floating_text.tscn")
		if ft_scene:
			var ft = ft_scene.instantiate()
			get_parent().add_child(ft)
			ft.global_position = global_position + Vector3(0, 1.6, 0)
			ft.setup("STUNNED!", Color(1.0, 0.8, 0.2), 1.2)
	elif state != State.STUNNED and is_instance_valid(attacker):
		aggro_on(attacker)
	
	# Mesh flash
	if mesh:
		var mat: StandardMaterial3D = mesh.get_active_material(0)
		if mat:
			var orig = mat.albedo_color
			mat.albedo_color = Color(1.0, 1.0, 1.0)
			await get_tree().create_timer(0.06).timeout
			if is_instance_valid(mat):
				mat.albedo_color = orig
	
	if current_hp <= 0:
		_die(attacker)

func apply_knockback(force: Vector3) -> void:
	knockback_velocity = force

func _die(killer: Node3D) -> void:
	state = State.DEAD
	$CollisionShape3D.set_deferred("disabled", true)
	hide()
	
	# Give EXP to killer
	if is_instance_valid(killer) and killer.has_method("add_exp"):
		killer.add_exp(exp_reward)
	
	# Drop Loot
	_drop_mob_loot()
	
	# Despawn and respawn after 15s
	await get_tree().create_timer(15.0).timeout
	_respawn()

func _drop_mob_loot() -> void:
	var drops := [
		{"id": "galleons", "amount": randi_range(15, 60)}
	]
	
	# 40% chance of material drop
	if randf() < 0.4:
		drops.append({"id": "mat_phoenix_ash", "amount": 1})
	# 20% chance of health potion
	if randf() < 0.2:
		drops.append({"id": "potion_health", "amount": 1})
	
	for d in drops:
		var loot = LOOT_SCENE.instantiate()
		get_parent().add_child(loot)
		loot.global_position = global_position + Vector3(randf_range(-1, 1), 0.3, randf_range(-1, 1))
		loot.setup(d["id"], d["amount"])

func _respawn() -> void:
	global_position = spawn_point
	current_hp = max_hp
	state = State.IDLE
	show()
	$CollisionShape3D.set_deferred("disabled", false)
	_update_label()
