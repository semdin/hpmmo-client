extends RefCounted

## One faction check shared by bolts, cones, explosions and enemy attacks.
static func can_damage(caster: Node, target: Node) -> bool:
	if not is_instance_valid(target) or target == caster or not target.has_method("take_damage"):
		return false
	if target.is_in_group("npcs"):
		return false
	if "current_hp" in target and target.current_hp <= 0:
		return false
	if "is_destroyed" in target and target.is_destroyed:
		return false
	if not is_instance_valid(caster):
		return false
	if caster.is_in_group("players"):
		return not target.is_in_group("players")
	return target.is_in_group("players")

static func has_line_of_sight(source: Node3D, target: Node3D) -> bool:
	var query := PhysicsRayQueryParameters3D.create(source.global_position + Vector3.UP, target.global_position + Vector3.UP, 1)
	return source.get_world_3d().direct_space_state.intersect_ray(query).is_empty()

static func safe_up(direction: Vector3) -> Vector3:
	return Vector3.FORWARD if absf(direction.normalized().dot(Vector3.UP)) > 0.98 else Vector3.UP
