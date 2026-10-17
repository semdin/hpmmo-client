extends Node3D

## Bestiary portraits: every creature in mobs.json posed on its idle clip,
## framed on its own bounds and written with a transparent background to
## res://assets/ui/bestiary/<species>.png (the bestiary window's portraits).
##   godot --path . res://scenes/test/bestiary_capture.tscn

const SIZE := 320
## Hand framing for bodies the collision proxy does not describe (a pixie
## flits above a tall proxy, a dementor floats above its own): AABB override.
const FRAME := {
	"cornish_pixie": AABB(Vector3(-0.35, 0.75, -0.35), Vector3(0.7, 0.75, 0.7)),
	"dementor": AABB(Vector3(-0.6, 0.6, -0.6), Vector3(1.2, 2.8, 1.2)),
}

func _ready() -> void:
	var vp := SubViewport.new()
	vp.size = Vector2i(SIZE, SIZE)
	vp.transparent_bg = true
	vp.own_world_3d = true
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(vp)
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_CLEAR_COLOR
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.62, 0.62, 0.68)
	env.environment.ambient_light_energy = 0.8
	env.environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	vp.add_child(env)
	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-35, 30, 0)
	key.light_energy = 1.4
	vp.add_child(key)
	var rim := DirectionalLight3D.new()
	rim.rotation_degrees = Vector3(-20, 200, 0)
	rim.light_energy = 0.9
	rim.light_color = Color(0.75, 0.82, 1.0)
	vp.add_child(rim)
	var cam := Camera3D.new()
	cam.fov = 30.0
	vp.add_child(cam)
	cam.current = true
	var defs: Dictionary = {}
	if defs.is_empty():
		var raw: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://addons/hpmmo_sim/data/mobs.json"))
		defs = raw.get("mobs", {})
	for species in defs.keys():
		var scene_path := String((defs[species] as Dictionary).get("scene", ""))
		if not ResourceLoader.exists(scene_path):
			continue
		if species in ["snare_vine", "fluffy_head"]:
			continue   # parts of a larger body, not creatures of their own
		var mob: Node = (load(scene_path) as PackedScene).instantiate()
		var visuals: Node3D = mob.get_node_or_null("Visuals")
		var box: AABB = FRAME.get(species, _collision_box(mob))
		if visuals == null:
			mob.free()
			continue
		mob.remove_child(visuals)
		mob.free()
		var boss := visuals.get_node_or_null("BossVariant")
		if boss != null and visuals.get_node_or_null("NormalVariant") != null:
			boss.free()
		visuals.position = Vector3.ZERO
		visuals.rotation = Vector3(0, deg_to_rad(-28), 0)
		vp.add_child(visuals)
		var anim := visuals.find_child("AnimationPlayer", true, false) as AnimationPlayer
		if anim != null:
			var clip := "Idle" if anim.has_animation("Idle") else ("Float" if anim.has_animation("Float") else "")
			if clip != "":
				anim.play(clip)
				anim.seek(anim.get_animation(clip).length * 0.3, true)
				anim.pause()
		for i in 3:
			await get_tree().process_frame
		var centre := box.get_center()
		var radius := maxf(box.size.y, box.size.x) * 0.5
		var dist := radius / tan(deg_to_rad(cam.fov * 0.5)) * 1.25
		cam.position = centre + Vector3(0, box.size.y * 0.08, dist)
		cam.look_at(centre + Vector3(0, box.size.y * 0.04, 0))
		for i in 4:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var img := vp.get_texture().get_image()
		img.save_png("res://assets/ui/bestiary/%s.png" % species)
		print("BESTIARY %s %s" % [species, box])
		visuals.queue_free()
		await get_tree().process_frame
	get_tree().quit()

## The body's own collision proxy (the boss proxy when there is one is the
## bigger body; an ordinary creature uses CollisionShape3D).
func _collision_box(mob: Node) -> AABB:
	var shape_node := mob.get_node_or_null("CollisionShape3D") as CollisionShape3D
	var h := 2.0
	var r := 0.6
	var y := 1.0
	if shape_node != null and shape_node.shape != null:
		var sh := shape_node.shape
		y = shape_node.position.y
		if sh is CapsuleShape3D:
			h = (sh as CapsuleShape3D).height
			r = (sh as CapsuleShape3D).radius
		elif sh is SphereShape3D:
			r = (sh as SphereShape3D).radius
			h = r * 2.0
		elif sh is BoxShape3D:
			h = (sh as BoxShape3D).size.y
			r = maxf((sh as BoxShape3D).size.x, (sh as BoxShape3D).size.z) * 0.5
		elif sh is CylinderShape3D:
			h = (sh as CylinderShape3D).height
			r = (sh as CylinderShape3D).radius
	var bottom := maxf(0.0, y - h * 0.5)
	var top := y + h * 0.5
	var w := maxf(r * 2.0, (top) * 0.55)
	return AABB(Vector3(-w * 0.5, 0.0, -w * 0.5), Vector3(w, maxf(top, bottom + 0.3), w))

func _bounds(root: Node3D) -> AABB:
	var out := AABB()
	var first := true
	for mi in root.find_children("*", "VisualInstance3D", true, false):
		var v := mi as VisualInstance3D
		if not v.is_visible_in_tree() or not (v is GeometryInstance3D):
			continue
		var b := v.global_transform * v.get_aabb()
		if first:
			out = b
			first = false
		else:
			out = out.merge(b)
	return out
