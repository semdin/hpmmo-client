extends Area3D

const SkillFXScript = preload("res://scripts/spells/skill_fx.gd")

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
		var mat := StandardMaterial3D.new()
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.albedo_color = spell_color
		mesh.set_surface_override_material(0, mat)
		
		# Distinct projectile shapes and scales
		if spell_id == "bombarda":
			mesh.scale = Vector3(1.8, 1.8, 2.4)
		elif spell_id == "incendio":
			mesh.scale = Vector3(1.4, 1.4, 2.0)
		elif spell_id == "ultimate":
			mesh.scale = Vector3(2.2, 2.2, 3.8)
		elif spell_id == "stupefy":
			mesh.scale = Vector3(1.2, 1.2, 1.6)
		else:
			mesh.scale = Vector3(0.9, 0.9, 1.3)
			
	if light:
		light.light_color = spell_color
		light.light_energy = 4.0 if spell_id in ["bombarda", "ultimate"] else 2.2
		light.omni_range = 9.0 if spell_id in ["bombarda", "ultimate"] else 5.5
		
	if particles:
		particles.color = spell_color
		particles.amount = 45 if spell_id in ["incendio", "bombarda", "ultimate"] else 24
		particles.speed_scale = 1.8 if spell_id == "incendio" else 1.2

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
	# MMO bolt pulse so projectiles read at distance
	if mesh:
		var s := 1.0 + sin(Time.get_ticks_msec() * 0.03) * 0.18
		mesh.scale = Vector3.ONE * s

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

	# MMO impact FX (own art) + damage numbers
	if is_instance_valid(get_parent()):
		SkillFXScript.play_impact(get_parent() as Node3D, global_position, spell_id)
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
