extends Area3D

## Spell projectile with particle trail, targeting, and Protego reflection support

@export var speed: float = 40.0
@export var damage: int = 40
@export var spell_id: String = "basic_cast"
@export var spell_color: Color = Color(1.0, 0.85, 0.4)
@export var max_lifetime: float = 4.0

var direction: Vector3 = Vector3.FORWARD
var caster: Node3D = null
var target_node: Node3D = null
var lifetime: float = 0.0

@onready var mesh: MeshInstance3D = $MeshInstance3D
@onready var light: OmniLight3D = $OmniLight3D
@onready var particles: CPUParticles3D = $CPUParticles3D

func _ready() -> void:
	body_entered.connect(_on_body_entered)
	area_entered.connect(_on_area_entered)
	_apply_visuals()

func setup(p_caster: Node3D, p_spell_id: String, p_dir: Vector3, p_target: Node3D = null, bonus_mult: float = 1.0) -> void:
	caster = p_caster
	spell_id = p_spell_id
	direction = p_dir.normalized()
	target_node = p_target
	
	if GameData.SPELLS.has(spell_id):
		var s_data: Dictionary = GameData.SPELLS[spell_id]
		damage = int(s_data.damage * bonus_mult)
		speed = s_data.get("projectile_speed", 40.0)
		spell_color = s_data.color
	
	_apply_visuals()

func _apply_visuals() -> void:
	if mesh:
		var mat: StandardMaterial3D = mesh.get_active_material(0)
		if mat:
			mat.albedo_color = spell_color
			mat.emission = spell_color
	if light:
		light.light_color = spell_color
	if particles:
		particles.color = spell_color

func _physics_process(delta: float) -> void:
	lifetime += delta
	if lifetime >= max_lifetime:
		queue_free()
		return
	
	# Slight homing towards locked target if exists and valid
	if is_instance_valid(target_node):
		var target_pos := target_node.global_position + Vector3(0, 1.2, 0)
		var desired_dir := (target_pos - global_position).normalized()
		direction = direction.lerp(desired_dir, 6.0 * delta).normalized()
	
	global_position += direction * speed * delta
	if direction.length_squared() > 0.001:
		look_at(global_position + direction, Vector3.UP)

func _on_body_entered(body: Node3D) -> void:
	if body == caster:
		return
	_handle_hit(body)

func _on_area_entered(area: Area3D) -> void:
	if area == caster or area.get_parent() == caster:
		return
	# Check if hit Protego shield
	if area.is_in_group("shields"):
		_reflect_projectile(area.get_parent())
		return
	_handle_hit(area)

func _reflect_projectile(shield_owner: Node3D) -> void:
	# Reverse direction and set target to original caster
	direction = -direction
	target_node = caster
	caster = shield_owner
	speed *= 1.2
	
	# Visual flare
	var ft_scene = load("res://scenes/ui/floating_text.tscn")
	if ft_scene:
		var ft = ft_scene.instantiate()
		get_parent().add_child(ft)
		ft.global_position = global_position
		ft.setup("PROTEGO REFLECT!", Color(0.2, 0.8, 1.0), 1.3)

func _handle_hit(target: Node) -> void:
	var hit_something := false
	
	if target.has_method("take_damage"):
		target.take_damage(damage, spell_id, caster)
		hit_something = true
	elif target.get_parent() and target.get_parent().has_method("take_damage"):
		target.get_parent().take_damage(damage, spell_id, caster)
		hit_something = true
	
	# Bombarda AOE explosion trigger
	if spell_id == "bombarda":
		_trigger_bombarda_aoe()
	
	# Spawn impact effect
	_spawn_impact_particles()
	queue_free()

func _trigger_bombarda_aoe() -> void:
	var explosion_scene = load("res://scenes/spells/bombarda_explosion.tscn")
	if explosion_scene:
		var exp_node = explosion_scene.instantiate()
		get_parent().add_child(exp_node)
		exp_node.global_position = global_position
		exp_node.setup(caster, damage)

func _spawn_impact_particles() -> void:
	var ft_scene = load("res://scenes/ui/floating_text.tscn")
	if ft_scene and damage > 0:
		var ft = ft_scene.instantiate()
		get_parent().add_child(ft)
		ft.global_position = global_position + Vector3(0, 0.5, 0)
		var text_color = Color(1.0, 0.3, 0.2)
		if spell_id == "stupefy":
			text_color = Color(1.0, 0.1, 0.1)
		elif spell_id == "incendio":
			text_color = Color(1.0, 0.6, 0.0)
		elif spell_id == "ultimate":
			text_color = Color(0.2, 1.0, 0.3)
		ft.setup(str(damage), text_color, 1.4)
