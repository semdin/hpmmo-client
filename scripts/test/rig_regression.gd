extends Node

## Rig headless regression (exit checks, mechanically).
##
## Asserts, without a rendering server: the body scale and socket contract, the
## broom's measured axes (no backward riding), seat alignment, mount/dismount
## under turning, refusal with no clearance and while in combat/stun/death, the
## animated phase a remote client would show for a replicated mount state, the
## upper-body cast blend, footstep contact events and the wand-release event.
##
## Run: godot --headless --path . res://scenes/test/rig_regression.tscn \
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
	await _check_clip_metrics(player)
	await _check_wand_grip(player)
	await _check_broom_axes(player)
	await _check_mount_round_trips(player)
	await _check_broom_grip(player)
	await _check_cast_aim(player)
	await _check_refusals(player)
	await _check_remote_agreement()
	await _check_animation_graph(player)
	print("RIG RESULT: %d checks, %d failures" % [checks, failures.size()])
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

## ---------------------------------------------------------------- clip metrics

## The exported clips must already be in metric bone space. This rig positions
## `Foot.L`, `Foot.R`, `PT.L` and `PT.R` by their own translation only (they hang
## off `Root`, which does not move), so a channel left in the unit the body pack
## authors it in pins the boots in space while the shins swing through them.
## `tools/blender/build_hero.py` re-units those channels inside the build
## (hero_common.reunit_pose_translations); nothing repairs them at runtime, so
## the shipped GLB is measured here both on the resource and through the pose.
func _check_clip_metrics(player) -> void:
	var skeleton: Skeleton3D = player._find_skeleton()
	var player_anim: AnimationPlayer = player.hero_anim.anim_player
	# The artifact first: a band, so neither the un-reunited residue nor a double
	# scale can pass. Measured on the shipped asset: 0.612 m running, 0.512 m
	# walking.
	var run_dev := _track_deviation(player_anim, skeleton, "Running_A", "Foot.L")
	check(run_dev > 0.4 and run_dev < 1.0,
		"The shipped Running_A foot track is in metres (%.3f m from rest)" % run_dev)
	var walk_dev := _track_deviation(player_anim, skeleton, "Walk_A", "Foot.L")
	check(walk_dev > 0.3 and walk_dev < 0.9,
		"The shipped Walk_A foot track is in metres (%.3f m from rest)" % walk_dev)
	for clip in ["Running_A", "Walk_A"]:
		var travel := await _ankle_travel(player, skeleton, clip)
		check(travel > 0.12 and travel < 1.3,
			"The ankle travels a real stride in %s (%.3f m over one cycle)" % [clip, travel])
	# A clip that legitimately does not move the feet must stay still: the boots
	# are planted in idle, so an over-scaled or mis-targeted track cannot hide
	# behind the stride checks above.
	var idle_travel := await _ankle_travel(player, skeleton, "Idle")
	check(idle_travel < 0.05, "Idle keeps its feet planted (%.3f m)" % idle_travel)

## The largest deviation from its rest of `bone`'s position track in `clip`, read
## off the shipped Animation resource rather than the pose it drives.
func _track_deviation(player_anim: AnimationPlayer, skeleton: Skeleton3D, clip: String, bone: String) -> float:
	if player_anim == null or skeleton == null or not player_anim.has_animation(clip):
		return -1.0
	var index := skeleton.find_bone(bone)
	if index < 0:
		index = skeleton.find_bone(bone.replace(".", "_"))
	if index < 0:
		return -1.0
	var rest: Vector3 = skeleton.get_bone_rest(index).origin
	var animation := player_anim.get_animation(clip)
	var sanitised := bone.replace(".", "_")
	var peak := 0.0
	for track in range(animation.get_track_count()):
		if animation.track_get_type(track) != Animation.TYPE_POSITION_3D:
			continue
		var track_bone := String(animation.track_get_path(track)).split(":")[-1]
		if track_bone != bone and track_bone != sanitised:
			continue
		for key in range(animation.track_get_key_count(track)):
			peak = maxf(peak, (animation.track_get_key_value(track, key) - rest).length())
	return peak

## The vertical + horizontal travel of the left ankle over one cycle of `clip`,
## played straight on the AnimationPlayer so the state machine cannot interfere.
func _ankle_travel(player, skeleton: Skeleton3D, clip: String) -> float:
	var player_anim: AnimationPlayer = player.hero_anim.anim_player
	if not player_anim.has_animation(clip):
		return -1.0
	var was_enabled: bool = player.hero_anim.enabled
	player.hero_anim.enabled = false
	var was_active: bool = player.hero_anim.tree.active
	player.hero_anim.tree.active = false
	var animation := player_anim.get_animation(clip)
	var index := skeleton.find_bone("Foot.L")
	if index < 0:
		index = skeleton.find_bone("Foot_L")
	var low := Vector3(1e9, 1e9, 1e9)
	var high := Vector3(-1e9, -1e9, -1e9)
	for step in range(25):
		player_anim.play(clip)
		player_anim.seek(animation.length * float(step) / 24.0, true)
		await get_tree().process_frame
		var point: Vector3 = skeleton.get_bone_global_pose(index).origin
		low = low.min(point)
		high = high.max(point)
	player_anim.stop()
	player.hero_anim.enabled = was_enabled
	player.hero_anim.tree.active = was_active
	return maxf((high - low).y, Vector2(high.x - low.x, high.z - low.z).length())

## ---------------------------------------------------------------- wand

## The wand has to sit IN the fist and point the way the hand does. Both are
## measured from the live rig, so the grip transform is checked rather than
## trusted.
func _check_wand_grip(player) -> void:
	await get_tree().create_timer(1.2).timeout
	var skeleton: Skeleton3D = player._find_skeleton()
	var holder: Node = player.visuals.find_child("EquippedWand", true, false)
	check(holder != null, "The equipped wand is attached")
	if holder == null or skeleton == null:
		return
	var wand := holder.get_child(0) as Node3D
	check(wand is Node3D, "The wand prop hangs off its holder")
	if wand == null:
		return
	var wrist := skeleton.find_bone("Wrist.R")
	if wrist < 0:
		wrist = skeleton.find_bone("Wrist_R")
	# The prop follows the hand's final pose, not a stale clip pose: this is the
	# bug that left the wand behind whenever a cast aimed the arm.
	var before: Vector3 = wand.global_position
	player.hero_anim.play_oneshot("Hit_A")
	await get_tree().create_timer(0.25).timeout
	var moved := wand.global_position.distance_to(before)
	check(moved > 0.01, "The wand follows the animated hand (moved %.3f m during a hit)" % moved)
	var axis := wand.global_transform.basis.y.normalized()
	var fist := _grip_centre(skeleton, "R")
	if fist != Vector3.INF:
		var fist_world: Vector3 = skeleton.global_transform * fist
		check(holder.global_position.distance_to(fist_world) < 0.06,
			"The wand's grip sits in the fist (%.3f m from the finger centres)" % holder.global_position.distance_to(fist_world))
		check(RigIK.distance_to_line(fist_world, holder.global_position,
			axis) < 0.07, "The handle runs through the closed fingers")
	# Compared in SKELETON space: the holder is a child of the skeleton, so its
	# local basis is the skeleton-space orientation, and the bone pose is too.
	var hand_axis: Vector3 = RigIK.hand_axis(skeleton, "Wrist.R")
	var wrist_pose := skeleton.get_bone_global_pose(wrist)
	var hand_world: Vector3 = (wrist_pose.basis * hand_axis).normalized()
	var wand_skel: Vector3 = holder.transform.basis.y.normalized()
	check(wand_skel.dot(hand_world) > 0.9,
		"The wand points the way the hand does (dot %.2f)" % wand_skel.dot(hand_world))

func _grip_centre(skeleton: Skeleton3D, side: String) -> Vector3:
	var acc := Vector3.ZERO
	var counted := 0
	for bone in ["Index1", "Middle1", "Ring1", "Pinky1", "Thumb1"]:
		var index := RigIK.bone_index(skeleton, "%s.%s" % [bone, side])
		if index < 0:
			continue
		acc += skeleton.get_bone_global_pose(index).origin
		counted += 1
	if counted == 0:
		return Vector3.INF
	return acc / float(counted)

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

## ---------------------------------------------------------------- broom grip

## How far a hand may sit from the shaft's centreline and still count as holding
## it. The shaft is a few centimetres across and the palm rides on top of it, so a
## hand inside this envelope is on the broom rather than floating beside it - the
## shaft is about 0.08 m across. A settled ride measures 0.027-0.032 m; the
## allowance is for a hard bank in progress, where the grip is re-solved each frame
## and trails the roll by one.
const GRIP_TOLERANCE := 0.09

## The rider's hands must actually hold the shaft, on the local body and on a
## replicated view alike. Driven through the real inputs (a bank is a held turn),
## because `_update_flight_pose` and the mount state machine rewrite the visual
## bank and the mounted clip every frame.
func _check_broom_grip(player) -> void:
	await _settle_on_floor(player, Vector3(0, 0.1, 5))
	player.visuals.rotation.y = 0.0
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player._combat_until = 0.0
	player._hit_recovery = 0.0
	player.toggle_broom_mount()
	await get_tree().create_timer(1.0).timeout
	check(player.is_mounted, "Rider is mounted for the grip measurement")
	if not player.is_mounted or player.broom_grip == null:
		return
	# The grip yields while the get-on one-shot plays, so wait for it to engage
	# before measuring instead of reading a vacuous zero.
	for _i in range(180):
		if player.broom_grip.engaged():
			break
		await get_tree().physics_frame
	check(player.broom_grip.engaged(), "The grip engages once the rider is seated")
	var settled: float = player.broom_grip.hand_error()
	check(settled >= 0.0 and settled <= GRIP_TOLERANCE,
		"Both hands sit on the shaft while cruising (%.3f m from its centreline)" % settled)
	check(player.broom_grip.hand_alignment() >= 0.8,
		"The hands lie along the shaft (alignment %.2f)" % player.broom_grip.hand_alignment())
	# A banking turn: the hips roll and the rider leans, and the hands must stay on.
	Input.action_press("move_left")
	await get_tree().create_timer(0.8).timeout
	var banking: float = player.broom_grip.hand_error()
	check(banking >= 0.0 and banking <= GRIP_TOLERANCE,
		"The grip survives a banking turn (%.3f m from the shaft)" % banking)
	check(absf(player.visuals.rotation.z) > 0.02, "The bank is actually being driven (roll %.3f)" % player.visuals.rotation.z)
	Input.action_release("move_left")
	await get_tree().create_timer(0.4).timeout
	# Climbing: the pitch changes and the rider still holds on.
	Input.action_press("jump")
	await get_tree().create_timer(0.9).timeout
	var climbing: float = player.broom_grip.hand_error()
	Input.action_release("jump")
	check(climbing >= 0.0 and climbing <= GRIP_TOLERANCE,
		"The grip survives a climb (%.3f m from the shaft)" % climbing)
	# A remote view solves the same way, so two clients agree on the pose.
	var view = preload("res://scenes/entities/player/player.tscn").instantiate()
	view.is_local_player = false
	view.sim_puppet = true
	world.add_child(view)
	view.global_position = Vector3(6, 0.1, 5)
	await get_tree().process_frame
	view.is_mounted = true
	view.sim_mount_phase = HPProtocol.MountPhase.CRUISE
	await get_tree().create_timer(1.0).timeout
	if view.broom_grip != null:
		check(view.broom_grip.hand_error() >= 0.0 and view.broom_grip.hand_error() <= GRIP_TOLERANCE,
			"A replicated rider's hands hold the shaft too (%.3f m)" % view.broom_grip.hand_error())
	else:
		check(false, "A replicated rider carries the grip solver")
	view.queue_free()
	await get_tree().process_frame
	player.global_position.y = 1.0
	player.velocity = Vector3.ZERO
	player._mount_lock = 0.0
	await get_tree().create_timer(0.1).timeout
	player.toggle_broom_mount()
	await get_tree().create_timer(0.4).timeout

## ---------------------------------------------------------------- cast aim

## At the release moment the wand must point at the target, not down the leg.
func _check_cast_aim(player) -> void:
	await _settle_on_floor(player, Vector3(0, 0.1, 5))
	player.visuals.rotation.y = 0.0
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player._combat_until = 0.0
	player._hit_recovery = 0.0
	await get_tree().create_timer(0.4).timeout
	var skeleton: Skeleton3D = player._find_skeleton()
	var holder: Node = player.visuals.find_child("EquippedWand", true, false)
	if holder == null or skeleton == null:
		check(false, "The caster carries a wand to aim")
		return
	player.current_mana = player.max_mana
	player.spell_cooldowns.clear()
	player.cast_spell("basic_cast")
	# Sampled through the hold: the arm reaches, then the wrist lands the wand on
	# whatever aim the body is using (the player refreshes it per frame, exactly as
	# it does in play).
	var best := -1.0
	# Where the wand sits while the arm aims: the grip has to survive the cast
	# layer as well as the idle pose (`_check_wand_grip` covers the hit clip).
	var held_worst := 0.0
	var wrist_bone := RigIK.bone_index(skeleton, "Wrist.R")
	for _i in range(40):
		await get_tree().physics_frame
		var wand := holder.get_child(0) as Node3D
		if wand == null:
			continue
		var aim: Vector3 = player.get_mouse_aim_point()
		var axis := wand.global_transform.basis.y.normalized()
		var to_aim: Vector3 = (aim - wand.global_position).normalized()
		best = maxf(best, axis.dot(to_aim))
		if player.hero_anim.cast_aiming() and wrist_bone >= 0:
			var wrist := skeleton.global_transform * skeleton.get_bone_global_pose(wrist_bone).origin
			held_worst = maxf(held_worst, wand.global_position.distance_to(wrist))
	check(best > 0.9, "The wand points at the target on a cast (best dot %.2f)" % best)
	check(held_worst > 0.0 and held_worst < 0.1,
		"The wand stays in the fist while the arm aims (%.3f m from the wrist at worst)" % held_worst)
	for _i in range(180):
		if not player.hero_anim.cast_aiming():
			break
		await get_tree().physics_frame
	check(not player.hero_anim.cast_aiming(), "The aim is released when the cast ends")

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
	# Drive the run through the real input: `_update_animation_state` re-selects the
	# locomotion clip from the body's state every physics frame, so a bare
	# `set_locomotion` would be replaced by Idle on the next one.
	Input.action_press("move_forward")
	await get_tree().create_timer(0.4).timeout
	var run_a: Quaternion = player.hero_anim.skeleton.get_bone_pose_rotation(leg_index)
	var moved := 0.0
	for _i in range(8):
		await get_tree().physics_frame
		moved = maxf(moved, run_a.angle_to(player.hero_anim.skeleton.get_bone_pose_rotation(leg_index)))
	Input.action_release("move_forward")
	await get_tree().create_timer(0.3).timeout
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
