extends CharacterBody3D

## MobBase - Base AI Controller for Harry Potter hostile creatures
## Implements Metin2-style pack aggro, wandering, combat, weakness, and 3D animations

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
@onready var visuals: Node3D = get_node_or_null("Visuals")
var anim_player: AnimationPlayer = null

const LOOT_SCENE = preload("res://scenes/entities/loot/loot_drop.tscn")
const PROJECTILE_SCENE = preload("res://scenes/spells/spell_projectile.tscn")

func _ready() -> void:
	add_to_group("mobs")
	add_to_group("targetable")
	current_hp = max_hp
	spawn_point = global_position
	
	# Find AnimationPlayer in visuals if available
	if visuals:
		anim_player = visuals.find_child("AnimationPlayer", true, false)
	
	_play_anim("Idle")
	_update_label()

func _update_label() -> void:
	if label:
		label.text = "[Lv.%d] %s\n%d / %d" % [level, mob_name, current_hp, max_hp]
		var ratio := float(current_hp) / float(max_hp)
		if ratio > 0.5:
			label.modulate = Color(1.0, 0.4, 0.4)
		else:
			label.modulate = Color(1.0, 0.15, 0.15)

func _play_anim(anim_name: String, blend: float = 0.2) -> void:
	if not is_instance_valid(anim_player):
		return
	if anim_player.has_animation(anim_name) and anim_player.current_animation != anim_name:
		anim_player.play(anim_name, blend)

func _physics_process(delta: float) -> void:
	if state == State.DEAD:
		return
	
	if knockback_velocity.length_squared() > 0.1:
		velocity = knockback_velocity
		knockback_velocity = knockback_velocity.lerp(Vector3.ZERO, 6.0 * delta)
		move_and_slide()
		return
	
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
	_play_anim("Idle")
	wander_timer -= delta
	if wander_timer <= 0.0:
		wander_timer = randf_range(2.0, 5.0)
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
	_play_anim("Walking_A")
	_face_direction(dir.normalized(), delta)
	_scan_for_players()

func _scan_for_players() -> void:
	var players = get_tree().get_nodes_in_group("players")
	for p in players:
		if p.global_position.distance_to(global_position) <= aggro_radius:
			aggro_on(p)
			break

func aggro_on(player_node: Node3D, alert_pack: bool = true) -> void:
	if state == State.DEAD or not is_instance_valid(player_node):
		return
	target_player = player_node
	state = State.CHASE
	
	if alert_pack:
		# Pack Pull: alert nearby mobs within 9m
		var nearby_mobs = get_tree().get_nodes_in_group("mobs")
		for m in nearby_mobs:
			if m != self and is_instance_valid(m) and (m.state == State.IDLE or m.state == State.WANDER):
				if m.global_position.distance_to(global_position) <= 9.0:
					m.target_player = player_node
					m.state = State.CHASE

func _process_chase(delta: float) -> void:
	if not is_instance_valid(target_player):
		state = State.IDLE
		return
	
	var dist_to_spawn := global_position.distance_to(spawn_point)
	if dist_to_spawn > 35.0:
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
	_play_anim("Running_A")
	_face_direction(dir.normalized(), delta)

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
	var to_player := (target_player.global_position - global_position).normalized()
	to_player.y = 0
	_face_direction(to_player, delta)
	
	if attack_timer <= 0.0:
		attack_timer = attack_cooldown
		_execute_attack()

func _face_direction(dir: Vector3, delta: float) -> void:
	if dir.length_squared() < 0.001:
		return
	var target_yaw := atan2(dir.x, dir.z)
	if visuals:
		visuals.rotation.y = lerp_angle(visuals.rotation.y, target_yaw, 12.0 * delta)
	else:
		rotation.y = lerp_angle(rotation.y, target_yaw, 12.0 * delta)

func _execute_attack() -> void:
	if not is_instance_valid(target_player):
		return
	
	if is_ranged:
		_play_anim("Spellcast_Shoot", 0.1)
		var proj = PROJECTILE_SCENE.instantiate()
		get_parent().add_child(proj)
		var spawn_pos := global_position + Vector3(0, 1.2, 0)
		proj.global_position = spawn_pos
		var dir := (target_player.global_position + Vector3(0, 1.0, 0) - spawn_pos).normalized()
		proj.setup(self, "stupefy", dir, target_player)
		proj.damage = attack_power
		proj.spell_color = Color(0.1, 0.9, 0.3)
	else:
		_play_anim("1H_Melee_Attack_Chop", 0.1)
		if target_player.has_method("take_damage"):
			target_player.take_damage(attack_power, "melee", self)

func take_damage(amount: int, spell_type: String, attacker: Node3D) -> void:
	if state == State.DEAD:
		return
	
	var actual_damage := amount
	if weak_to_fire and spell_type == "incendio":
		actual_damage = int(amount * 2.0)
	
	current_hp = max(0, current_hp - actual_damage)
	_update_label()
	
	if spell_type == "stupefy":
		state = State.STUNNED
		stun_timer = 1.8
		var ft_scene = load("res://scenes/ui/floating_text.tscn")
		if ft_scene:
			var ft = ft_scene.instantiate()
			get_parent().add_child(ft)
			ft.global_position = global_position + Vector3(0, 1.8, 0)
			ft.setup("STUNNED!", Color(1.0, 0.8, 0.2), 1.2)
	elif state != State.STUNNED and is_instance_valid(attacker):
		aggro_on(attacker)
		_play_anim("Hit_A", 0.1)
	
	if current_hp <= 0:
		_die(attacker)

func apply_knockback(force: Vector3) -> void:
	knockback_velocity = force

func _die(killer: Node3D) -> void:
	state = State.DEAD
	$CollisionShape3D.set_deferred("disabled", true)
	_play_anim("Death_A", 0.1)
	
	if is_instance_valid(killer) and killer.has_method("add_exp"):
		killer.add_exp(exp_reward)
	
	_drop_mob_loot()
	
	await get_tree().create_timer(1.5).timeout
	hide()
	await get_tree().create_timer(12.0).timeout
	_respawn()

func _drop_mob_loot() -> void:
	var drops := [
		{"id": "galleons", "amount": randi_range(20, 75)}
	]
	if randf() < 0.45:
		drops.append({"id": "mat_phoenix_ash", "amount": 1})
	if randf() < 0.25:
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
	_play_anim("Idle")
	_update_label()
