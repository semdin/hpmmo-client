extends Node3D

## Focused motion regressions using the shipped player and imported skeleton.
## godot --headless --path client res://scenes/test/motion_regression.tscn
var checks := 0
var failures := 0
var player: CharacterBody3D
var graph: HeroAnimation
var skeleton: Skeleton3D

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok:
		failures += 1
	print("%s: %s" % ["PASS" if ok else "FAIL", message])

func _ready() -> void:
	QuestManager.persistence_enabled = false
	var floor_body := StaticBody3D.new()
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(100, 0.2, 100)
	shape.shape = box
	floor_body.position.y = -0.1
	floor_body.add_child(shape)
	add_child(floor_body)
	player = preload("res://scenes/entities/player/player.tscn").instantiate()
	player.is_local_player = false
	player.sim_server_controlled = true
	add_child(player)
	graph = player.hero_anim
	skeleton = player._find_skeleton()
	await get_tree().create_timer(1.2).timeout
	# Exercise the real physics selector through takeoff, apex and landing.
	player.sim_input = {"jump": true}
	await get_tree().create_timer(0.1).timeout
	check(graph.current_clip == "Jump_Start", "Jump input selects the takeoff clip")
	player.sim_input = {}
	await get_tree().create_timer(0.35).timeout
	check(graph.current_state == "air_down" and graph.current_clip == "Fall",
		"The falling half of a jump enters Fall before touching the ground")
	player.animation_events.clear()
	await get_tree().create_timer(0.1).timeout
	check(not player.animation_events.any(func(e): return String(e).begins_with("footstep:")),
		"An airborne body emits no ground footsteps")
	await get_tree().create_timer(1.0).timeout
	check(player.is_on_floor() and graph.current_state == "idle", "Landing returns to planted idle")

	# Deterministic mixer sampling: compare visible bone poses, not only state names.
	player.set_process(false)
	player.set_physics_process(false)
	graph.tree.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	graph.cancel_oneshot()
	graph.end_cast()
	graph.set_ground_motion(Vector2.ZERO)
	advance(0.5)
	var before := pose()
	graph.set_ground_motion(Vector2(0, 8.5))
	advance(1.0 / 60.0)
	var first := pose()
	check(distance(before, first) < 0.18, "Run startup does not snap the foot/hip pose in one frame")
	advance(0.22)
	check(distance(before, pose()) > 0.1, "The blend reaches a visibly moving stride")
	var fast_rate: float = graph.tree.get("parameters/ground_speed/scale")
	graph.set_ground_motion(Vector2(0, 1.5))
	advance(0.5)
	check(fast_rate > float(graph.tree.get("parameters/ground_speed/scale")) + 0.2,
		"Foot cadence slows with movement speed")
	graph.set_ground_motion(Vector2(6, 6))
	advance(0.3)
	var blend: Vector2 = graph.tree.get("parameters/ground/blend_position")
	check(blend.x > 0.4 and blend.y > 0.4, "Diagonal travel combines forward and side poses")
	graph.set_ground_motion(Vector2.ZERO)
	advance(0.4)
	var rest := pose()
	advance(0.35)
	check(distance(rest, pose()) < 0.05, "Stopping settles the feet instead of cycling in place")

	# A reused logical state may still request a different animation.
	graph.set_locomotion("air", "Jump_Start", true)
	advance(0.2)
	before = pose()
	graph.set_locomotion("air", "Fall")
	advance(1.0 / 60.0)
	check(String(graph.tree.get("parameters/locomotion/current_state")) == "Fall",
		"A clip change is honoured even when the logical state name is unchanged")
	check(distance(before, pose()) < 0.18, "Air-state transition crossfades the existing pose")
	advance(0.3)

	# Repeated hits must restart, and a 2x hit must actually sample at 2x speed.
	graph.set_locomotion("idle_test", "Idle", true)
	advance(0.4)
	graph.play_oneshot("Hit_A")
	graph.tree.advance(0.0)
	advance(0.18)
	var hit_pose := all_rotations()
	advance(0.12)
	graph.play_oneshot("Hit_A")
	graph.tree.advance(0.0)
	advance(0.18)
	check(rotation_distance(hit_pose, all_rotations()) < 0.06, "Consecutive hits restart at the same pose")
	graph.play_oneshot("Hit_A", 2.0)
	graph.tree.advance(0.0)
	advance(0.09)
	check(rotation_distance(hit_pose, all_rotations()) < 0.06, "A 2x hit reaches the same pose in half the time")

	for duration in [0.3, 0.48, 0.72]:
		graph.start_cast("Spellcast_Shoot_Upper", duration)
		graph.align_cast(duration * 0.6, 0.45)
		var layer := graph.cast_layer
		var length := layer.animation.length
		check(is_equal_approx(layer.clip_time_at(duration * 0.6), length * 0.45),
			"%.2fs cast reaches its extension pose on the release beat" % duration)
		layer._process_modification_with_delta(duration * 0.6)
		check(absf(layer.time - length * 0.45) < 0.001,
			"%.2fs cast applies the retiming to the live modifier" % duration)
		check(is_equal_approx(layer.clip_time_at(duration), length),
			"%.2fs cast preserves its recovery through the end of the clip" % duration)

	# Exercise production timing and the rolling event buffer, not only the
	# retiming helper. The old full-buffer guard silently stopped all releases.
	graph.tree.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_IDLE
	player.set_process(true)
	player.set_physics_process(true)
	graph.end_cast()
	await get_tree().create_timer(0.3).timeout
	player.animation_events.clear()
	for _i in range(32):
		player.animation_events.append("old_event")
	var expected_release := float(maxi(1, int(round(HPRules.cast_lock("basic_cast") * 0.5 * HPProtocol.SIM_HZ)))) / HPProtocol.SIM_HZ
	player._play_cast_animation("Spellcast_Shoot", Vector3(0, 1.2, 10), "basic_cast")
	await get_tree().create_timer(expected_release + 0.035).timeout
	check(player.animation_events.has("fx:wand_release"),
		"Gameplay windup emits release on time even when the event buffer is full")
	check(graph.cast_weight() > 0.95, "The casting arm has full influence by the fast release beat")
	await get_tree().create_timer(0.5).timeout
	player.present_replicated_cast_start(42, Vector3(0, 1.2, 10), "stupefy", 0.12)
	check(graph.casting(), "A remote cast begins its gesture during windup")
	var generation: int = player._cast_generation
	await get_tree().create_timer(0.13).timeout
	player.present_replicated_cast(Vector3(0, 1.2, 0), Vector3.BACK, "stupefy", 42)
	check(player._cast_generation == generation, "Remote release does not restart the windup gesture")
	await get_tree().create_timer(0.65).timeout

	print("MOTION RESULT: %d checks, %d failures" % [checks, failures])
	get_tree().quit(0 if failures == 0 else 1)

func advance(seconds: float) -> void:
	var remaining := seconds
	while remaining > 0.00001:
		var delta := minf(remaining, 1.0 / 60.0)
		graph.tick(delta)
		graph.tree.advance(delta)
		remaining -= delta

func pose() -> Array[Vector3]:
	var result: Array[Vector3] = []
	for name in ["Foot.L", "Foot.R", "Hips"]:
		result.append(skeleton.get_bone_global_pose(RigIK.bone_index(skeleton, name)).origin)
	return result

func distance(a: Array[Vector3], b: Array[Vector3]) -> float:
	var result := 0.0
	for i in range(a.size()):
		result = maxf(result, a[i].distance_to(b[i]))
	return result

func all_rotations() -> Array[Quaternion]:
	var result: Array[Quaternion] = []
	for name in ["Hips", "Abdomen", "Torso", "UpperArm.L", "UpperArm.R"]:
		result.append(skeleton.get_bone_pose_rotation(RigIK.bone_index(skeleton, name)))
	return result

func rotation_distance(a: Array[Quaternion], b: Array[Quaternion]) -> float:
	var result := 0.0
	for i in range(a.size()):
		result = maxf(result, a[i].angle_to(b[i]))
	return result
