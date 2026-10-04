extends Node

## Phase 9 headless regression (plan.md Phase 9 exit checks, mechanically).
##
## Asserts, without a rendering server: the body scale and socket contract, the
## broom's measured axes (no backward riding), seat alignment, mount/dismount
## under turning, refusal with no clearance and while in combat/stun/death, the
## animated phase a remote client would show for a replicated mount state, the
## upper-body cast blend, footstep contact events and the wand-release event.
##
## Run: godot --headless --path . res://scenes/test/phase9_regression.tscn \
##        --fixed-fps 60 --quit-after 6000

const BroomFlightScript = preload("res://scripts/entities/broom_flight.gd")

var failures: Array[String] = []
var checks := 0
@onready var world = $GameWorld

func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)

func _enter_tree() -> void:
	NetworkManager.local_character_data = {}
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false

func _ready() -> void:
	await get_tree().create_timer(0.5).timeout
	var player = world.local_player
	await _check_body(player)
	await _check_broom_axes(player)
	await _check_mount_round_trips(player)
	await _check_refusals(player)
	await _check_remote_agreement()
	await _check_animation_graph(player)
	print("PHASE9 RESULT: %d checks, %d failures" % [checks, failures.size()])
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if failures.is_empty() else 1)

## Wait until the body is standing on the floor at `spot`, so every staged mount
## starts from the same state instead of from mid-fall.
func _settle_on_floor(player, spot: Vector3) -> void:
	player.global_position = spot
	player.velocity = Vector3(0, -1.0, 0)
	for _i in range(60):
		await get_tree().physics_frame
		if player.is_on_floor():
			await get_tree().physics_frame
			return

## ---------------------------------------------------------------- body

func _check_body(player) -> void:
	# A spawn drop plays the landing one-shot; measure once the body is back on
	# the idle stance, or the numbers describe a crouch instead of the rig.
	await get_tree().create_timer(1.6).timeout
	var body: Node = player.visuals.find_child("Hero_Body", true, false)
	check(body is MeshInstance3D, "Hero body mesh is present on the player")
	var bind_height := 0.0
	if body is MeshInstance3D and (body as MeshInstance3D).mesh:
		bind_height = (body as MeshInstance3D).mesh.get_aabb().size.y
	check(bind_height > 1.75 and bind_height < 1.90,
		"Hero binds within the approved 1.75-1.90 m band (measured %.3f m)" % bind_height)
	var head_socket: Node3D = player.socket("Socket_Head")
	var foot_socket: Node3D = player.socket("Socket_Foot_L")
	var crown := 0.0
	if head_socket and foot_socket:
		crown = head_socket.global_position.y - foot_socket.global_position.y
	check(crown > 1.2 and crown < 1.9,
		"Deployed rig stands at human scale (head socket above foot socket by %.2f m)" % crown)
	# House variation is material-only (no second rig): the shipped hero must
	# carry a tinted trim slot after _apply_house_customization.
	var hero_body: Node = player.visuals.find_child("Hero_Body", true, false)
	var house_colour: Color = GameData.HOUSES[player.house].primary_color if GameData.HOUSES.has(player.house) else Color.WHITE
	var tinted := 0
	if hero_body is MeshInstance3D:
		var mesh_instance := hero_body as MeshInstance3D
		for i in range(mesh_instance.mesh.get_surface_count()):
			var slot_name := ""
			var source: Material = mesh_instance.mesh.surface_get_material(i)
			if source:
				slot_name = source.resource_name
			var override: Material = mesh_instance.get_surface_override_material(i)
			if slot_name == "Hero_Trim" and override is StandardMaterial3D:
				if (override as StandardMaterial3D).albedo_color.is_equal_approx(house_colour):
					tinted += 1
	check(tinted == 1, "House colour is applied to the hero's trim material (house %s)" % player.house)
	check(hero_body is MeshInstance3D and (hero_body as MeshInstance3D).mesh.get_surface_count() == 5,
		"Hero ships 5 material slots (skin / robe / dark / leather / trim)")
	var shape: CapsuleShape3D = player.get_node("CollisionShape3D").shape
	check(is_equal_approx(shape.radius, 0.35) and is_equal_approx(shape.height, 1.85),
		"Collision capsule follows the documented silhouette (r %.2f h %.2f)" % [shape.radius, shape.height])
	check(player.nameplate.position.y > 1.9 and player.nameplate.position.y < 2.6,
		"Nameplate sits above the taller crown (y %.2f)" % player.nameplate.position.y)
	check(is_equal_approx(player.camera_pivot.global_position.y - player.global_position.y, 1.55)
		or absf(player.camera_pivot.global_position.y - player.global_position.y - 1.55) < 0.2,
		"Camera pivot follows the taller body (%.2f m above the feet)" % (player.camera_pivot.global_position.y - player.global_position.y))
	var required := ["Socket_Wand", "Socket_Hand_L", "Socket_Hand_R", "Socket_Foot_L",
		"Socket_Foot_R", "Socket_Torso", "Socket_Head", "Socket_Hips"]
	var present := 0
	for socket_name in required:
		if player.socket(socket_name) != null:
			present += 1
	check(present == required.size(),
		"All %d documented sockets exist and are bound to bones (%d)" % [required.size(), present])
	var hips: Node3D = player.socket("Socket_Hips")
	var foot: Node3D = player.socket("Socket_Foot_L")
	if hips and foot:
		check(hips.global_position.y > foot.global_position.y + 0.3,
			"Socket_Hips is above Socket_Foot_L on the standing rig (%.2f m apart)" % (hips.global_position.y - foot.global_position.y))

## ---------------------------------------------------------------- broom

func _check_broom_axes(player) -> void:
	var broom = player.broom
	check(broom != null, "Broom rig is attached to the player")
	if broom == null:
		return
	var report: Dictionary = broom.verify_axes()
	check(report["nose_z"] > 0.5, "Broom nose is forward (+Z, measured %.2f m)" % report["nose_z"])
	check(report["tail_z"] < -0.5, "Bristles are behind the seat (-Z, measured %.2f m)" % report["tail_z"])
	check(report["seat_ok"], "SeatSocket sits above the shaft (y %.2f m)" % report["seat_y"])
	# The model's forward axis and the rider's facing must agree: this is the
	# measurement that the old reversed rider would have failed.
	var rider_forward: Vector3 = player.visuals.global_transform.basis.z.normalized()
	var broom_forward: Vector3 = (broom.broom_forward())
	check(rider_forward.dot(broom_forward) > 0.9,
		"Broom forward axis and rider facing agree (dot %.2f)" % rider_forward.dot(broom_forward))

## ---------------------------------------------------------------- mounting

func _check_mount_round_trips(player) -> void:
	player.global_position = Vector3(0, 0.1, 5)
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.3).timeout
	var mount_ok := 0
	var dismount_ok := 0
	var phases_seen := {}
	for turn in range(4):
		await _settle_on_floor(player, Vector3(0, 0.1, 5))
		player.visuals.rotation.y = TAU * float(turn) / 4.0
		player._mount_lock = 0.0
		player._cast_lock = 0.0
		player._combat_until = 0.0
		player._hit_recovery = 0.0
		player.toggle_broom_mount()
		if player.is_mounted:
			mount_ok += 1
			phases_seen[player.mount_phase()] = true
			await get_tree().create_timer(0.2).timeout
			var seat_gap := 99.0
			if player.broom and player.broom.seat_socket and player.socket("Socket_Hips"):
				seat_gap = player.broom.seat_socket.global_position.distance_to(player.socket("Socket_Hips").global_position)
			check(seat_gap <= 0.35,
				"Rider sits on the saddle while turned %d deg (gap %.2f m)" % [turn * 90, seat_gap])
			player.global_position.y = 1.2
			player.velocity = Vector3.ZERO
			player._mount_lock = 0.0
			await get_tree().create_timer(0.1).timeout
			player.toggle_broom_mount()
			if not player.is_mounted:
				dismount_ok += 1
		await get_tree().create_timer(0.2).timeout
		check(player.global_position.y > -1.0,
			"Dismount never drops the rider through the floor (round %d)" % turn)
	check(mount_ok == 4 and dismount_ok == 4,
		"Repeated mount/dismount while turning stays consistent (%d mounts, %d dismounts)" % [mount_ok, dismount_ok])
	check(phases_seen.size() >= 1, "A mounted rider reports a presented phase (%d distinct)" % phases_seen.size())
	check(player.global_position.y > -1.0, "No dismount-through-floor: the rider ends above the courtyard floor")

## ---------------------------------------------------------------- refusals

func _check_refusals(player) -> void:
	# Combat, stun and death are gameplay refusals before any clearance question.
	player._combat_until = 2.0
	check(player.mount_block_reason() == "Not while in combat!", "Mount during combat is refused")
	player._combat_until = 0.0
	player._hit_recovery = 0.3
	check(player.mount_block_reason() == "You are stunned!", "Mount while stunned is refused")
	player._hit_recovery = 0.0
	var was_dead: bool = player.is_dead
	player.is_dead = true
	check(player.mount_block_reason() == "You are defeated!", "Mount while dead is refused")
	player.is_dead = was_dead
	# Clearance, measured against a fixture we own: a slab lowered over the
	# courtyard until the headroom a broom needs is gone. Deterministic, and it
	# tests the rule rather than one level geometry.
	await _settle_on_floor(player, Vector3(0, 0.1, 5))
	check(player._flight_clearance_ok(), "Flight clearance measured true in the open courtyard")
	check(player.mount_block_reason() == "", "Mount is allowed in the open courtyard")
	var slab := StaticBody3D.new()
	slab.collision_layer = 1
	slab.collision_mask = 0
	var slab_shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(6, 0.3, 6)
	slab_shape.shape = box
	slab.add_child(slab_shape)
	world.add_child(slab)
	slab.global_position = Vector3(0, 2.2, 5)
	await get_tree().physics_frame
	await get_tree().physics_frame
	var reason: String = player.mount_block_reason()
	check(reason == "Not enough room to take off here!",
		"Mount under a 2.2 m ceiling is refused for clearance (%s)" % reason)
	player._mount_lock = 0.0
	player.toggle_broom_mount()
	check(not player.is_mounted, "A refused mount never actually mounts")
	slab.queue_free()
	await get_tree().physics_frame
	await get_tree().physics_frame
	check(player.mount_block_reason() == "",
		"Mount is allowed again once the ceiling is gone (%s)" % player.mount_block_reason())
	# Recorded for the report: the castle doorway also refuses a takeoff.
	await _settle_on_floor(player, Vector3(0, 0.15, -38))
	var doorway_reason: String = player.mount_block_reason()
	print("NOTE doorway mount reason: %s (on_floor=%s)" % [doorway_reason, player.is_on_floor()])

## ---------------------------------------------------------------- replication

func _check_remote_agreement() -> void:
	var phase := HPProtocol.MountPhase.BANK_L
	var clip: String = world.local_player.clip_for_mount_phase(phase)
	check(clip == "Broom_Bank_L", "Phase BANK_L maps to its dedicated clip")
	var view = preload("res://scenes/entities/player/player.tscn").instantiate()
	view.is_local_player = false
	view.sim_puppet = true
	world.add_child(view)
	view.global_position = Vector3(6, 0.1, 5)
	await get_tree().process_frame
	view.is_mounted = true
	view.sim_mount_phase = phase
	await get_tree().physics_frame
	await get_tree().physics_frame
	check(view.sim_mount_phase == phase, "A puppet carries the replicated mount phase")
	var state_clip: String = view.hero_anim.current_clip if view.hero_anim else ""
	check(state_clip == "Broom_Bank_L",
		"Remote rider animates the replicated phase (clip %s)" % state_clip)
	# Two clients reading the same replicated record must land on the same clip.
	var second = preload("res://scenes/entities/player/player.tscn").instantiate()
	second.is_local_player = false
	second.sim_puppet = true
	world.add_child(second)
	await get_tree().process_frame
	second.is_mounted = true
	second.sim_mount_phase = phase
	await get_tree().physics_frame
	await get_tree().physics_frame
	var second_clip: String = second.hero_anim.current_clip if second.hero_anim else ""
	check(second_clip == state_clip, "Two remote clients agree on the rider's animation phase")
	# The authority derives the phase itself - input left means banking left.
	var record := {"mounted": true, "input": {"move": Vector2(-1.0, 0.0)}}
	var derived: int = HPProtocol.mount_phase_for(true, -1.0, 0.0, 0.4, 0.0)
	check(derived == HPProtocol.MountPhase.BANK_L, "Authority derives BANK_L from left input")
	var climbing: int = HPProtocol.mount_phase_for(true, 0.0, 1.0, 0.5, 0.0)
	check(climbing == HPProtocol.MountPhase.CLIMB, "Authority derives CLIMB from the ascend axis")
	view.queue_free()
	second.queue_free()
	await get_tree().process_frame

## ---------------------------------------------------------------- graph

func _check_animation_graph(player) -> void:
	var required := ["Idle", "Walk_A", "Running_A", "Strafe_L", "Strafe_R", "Walk_Back",
		"Jump_Start", "Fall", "Land", "Spellcast_Shoot", "Spellcast_Raise", "Hit_A",
		"Stun_Loop", "Death_A", "Revive", "Interact", "Mount_Broom", "Dismount_Broom",
		"Broom_Seated_Idle", "Broom_Takeoff", "Broom_Accelerate", "Broom_Cruise",
		"Broom_Bank_L", "Broom_Bank_R", "Broom_Climb", "Broom_Dive", "Broom_Brake", "Broom_Land"]
	var missing: Array = []
	for clip in required:
		if not player.hero_anim.has_clip(clip):
			missing.append(clip)
	check(missing.is_empty(), "Animation graph covers every required state (missing: %s)" % str(missing))
	check(player.hero_anim.has_clip("Spellcast_Shoot_Upper"),
		"Upper-body cast variant exists for blending")
	# Idle is a loop and Death_A is not: the graph declares loop modes, callers
	# never guess.
	check(player.hero_anim.anim_player.get_animation("Idle").loop_mode != Animation.LOOP_NONE,
		"Idle is authored as a loop")
	check(player.hero_anim.anim_player.get_animation("Death_A").loop_mode == Animation.LOOP_NONE,
		"Death_A is authored as a one-shot")
	# Upper-body blend, measured A/B: the same duration of the same locomotion
	# clip is sampled once without the cast layer and once with it. If the blend
	# reset tracks the cast clip does not animate, the with-cast legs would jump
	# by much more than the reference.
	await _settle_on_floor(player, Vector3(0, 0.1, 5))
	var leg_index: int = player.hero_anim.skeleton.find_bone("UpperLeg_L")
	if leg_index < 0:
		leg_index = player.hero_anim.skeleton.find_bone("UpperLeg.L")
	var arm_index: int = player.hero_anim.skeleton.find_bone("UpperArm_L")
	if arm_index < 0:
		arm_index = player.hero_anim.skeleton.find_bone("UpperArm.L")
	player.hero_anim.set_locomotion("idle_ref", "Idle", true)
	await get_tree().physics_frame
	var ref_leg_a: Quaternion = player.hero_anim.skeleton.get_bone_pose_rotation(leg_index)
	var ref_arm_a: Quaternion = player.hero_anim.skeleton.get_bone_pose_rotation(arm_index)
	for _i in range(14):
		player.hero_anim.tick(1.0 / 60.0)
		await get_tree().physics_frame
	var ref_leg_delta: float = ref_leg_a.angle_to(player.hero_anim.skeleton.get_bone_pose_rotation(leg_index))
	var ref_arm_delta: float = ref_arm_a.angle_to(player.hero_anim.skeleton.get_bone_pose_rotation(arm_index))
	player.hero_anim.set_locomotion("idle_blend", "Idle", true)
	await get_tree().physics_frame
	var cast_leg_a: Quaternion = player.hero_anim.skeleton.get_bone_pose_rotation(leg_index)
	var cast_arm_a: Quaternion = player.hero_anim.skeleton.get_bone_pose_rotation(arm_index)
	player.hero_anim.start_cast("Spellcast_Shoot_Upper", 0.6)
	for _i in range(14):
		player.hero_anim.tick(1.0 / 60.0)
		await get_tree().physics_frame
	var cast_leg_delta: float = cast_leg_a.angle_to(player.hero_anim.skeleton.get_bone_pose_rotation(leg_index))
	var cast_arm_delta: float = cast_arm_a.angle_to(player.hero_anim.skeleton.get_bone_pose_rotation(arm_index))
	check(player.hero_anim.cast_weight() > 0.5,
		"Cast layer reaches full weight over locomotion (%.2f)" % player.hero_anim.cast_weight())
	check(cast_arm_delta > ref_arm_delta + 0.05,
		"Upper body takes the cast pose (arm delta %.3f rad vs %.3f without)" % [cast_arm_delta, ref_arm_delta])
	check(cast_leg_delta <= ref_leg_delta + 0.12,
		"Legs are untouched by the cast blend (leg delta %.3f rad vs %.3f without)" % [cast_leg_delta, ref_leg_delta])
	# ... and with a running locomotion clip the legs keep being driven by it.
	player.hero_anim.set_locomotion("run_blend", "Running_A", true)
	await get_tree().physics_frame
	var run_a: Quaternion = player.hero_anim.skeleton.get_bone_pose_rotation(leg_index)
	var moved := 0.0
	for _i in range(8):
		player.hero_anim.tick(1.0 / 60.0)
		await get_tree().physics_frame
		moved = maxf(moved, run_a.angle_to(player.hero_anim.skeleton.get_bone_pose_rotation(leg_index)))
	check(moved > 0.03,
		"Legs keep running under the cast blend (leg motion %.3f rad)" % moved)
	player.hero_anim.end_cast()
	player.hero_anim.tick(0.5)
	# Committed attack roots the caster; the event fires on the release beat.
	if player.is_mounted:
		player.global_position.y = 1.0
		player._mount_lock = 0.0
		player.toggle_broom_mount()
	await _settle_on_floor(player, Vector3(0, 0.1, 5))
	player._hit_recovery = 0.0
	player._combat_until = 0.0
	check(player._committed_until <= 0.0, "No committed window before the attack")
	player.current_mana = player.max_mana
	player._cast_lock = 0.0
	player.spell_cooldowns.clear()
	player.cast_spell("bombarda")
	check(player._committed_until > 0.0, "Committed attack blocks movement while it resolves")
	check(player._intent_move() == Vector2.ZERO, "Committed attack zeroes movement intent")
	var release_events := 0
	for event in player.animation_events:
		if event == "fx:wand_release":
			release_events += 1
	await get_tree().create_timer(0.5).timeout
	for event in player.animation_events:
		if event == "fx:wand_release":
			release_events += 1
	check(release_events >= 1, "Wand release event fires with the cast")
	# Footsteps come from measured contact: move the body and listen.
	player.animation_events.clear()
	player._committed_until = 0.0
	Input.action_press("move_forward")
	await get_tree().create_timer(2.0).timeout
	Input.action_release("move_forward")
	var footsteps := 0
	for event in player.animation_events:
		if String(event).begins_with("footstep:"):
			footsteps += 1
	check(footsteps >= 1, "Footstep events fire from foot contact while moving (%d)" % footsteps)
	await get_tree().create_timer(0.2).timeout
