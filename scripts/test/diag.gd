extends Node
@onready var world = $GameWorld
func _ready() -> void:
	await get_tree().create_timer(0.6).timeout
	var space: PhysicsDirectSpaceState3D = world.get_world_3d().direct_space_state
	var origin := Vector3(0, 1.0, 5.0)
	for i in range(16):
		var angle := TAU * float(i) / 16.0
		var dir := Vector3(cos(angle), 0, sin(angle))
		var q := PhysicsRayQueryParameters3D.create(origin, origin + dir * 12.0, 1)
		var hit: Dictionary = space.intersect_ray(q)
		if not hit.is_empty():
			print("dir %5.1f deg -> %s at %.1f m" % [rad_to_deg(angle), hit.collider.name, origin.distance_to(hit.position)])
		else:
			print("dir %5.1f deg -> clear" % rad_to_deg(angle))
	# what is around (6,0,6)?
	var q2 := PhysicsShapeQueryParameters3D.new()
	var shape := CapsuleShape3D.new(); shape.radius = 0.45; shape.height = 1.8
	q2.shape = shape
	q2.transform = Transform3D(Basis(), Vector3(6, 0.9, 6))
	q2.collision_mask = 1
	var hits: Array = space.intersect_shape(q2, 8)
	print("at (6,0.9,6): ", hits.size(), " colliders")
	for h in hits:
		print("   ", h.collider.name)
	get_tree().quit()
