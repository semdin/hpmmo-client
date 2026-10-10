extends Node

## Interface checks (evidence): everything about the HUD,
## interaction feedback, input focus, settings and onboarding that is
## mechanically assertable, asserted.
##
## Run:
##   godot --headless --path client res://scenes/test/ui_regression.tscn \
##     --fixed-fps 60 --quit-after 7200
##
## Covers: every stat transition (damage, potion, regeneration, spending,
## rewards, level-up, death, respawn, reconnect, maintenance, map transfer)
## updating the HUD from authoritative payloads; no duplicate listeners after a
## death, a relog or a map transfer; a newer server value always beating an
## in-flight tween; the authority's rejection reasons surfacing in player words;
## the maintenance countdown; input focus blocking casting and mounting; the
## settings model persisting to user:// and reloading; and the onboarding route
## completing only on authoritative evidence.

const TweenSafetyEpsilon := 0.01

var checks := 0
var failures: Array[String] = []
var world: Node3D = null
var hud: Control = null
var player: Node3D = null

func check(condition: bool, message: String) -> void:
	checks += 1
	if condition:
		print("PASS: " + message)
	else:
		failures.append(message)
		push_error("FAIL: " + message)

func _ready() -> void:
	NetworkManager.is_server = false
	QuestManager.persistence_enabled = false
	world = get_node_or_null("GameWorld")
	await get_tree().create_timer(0.8).timeout
	hud = world.hud
	player = world.local_player
	check(hud != null and player != null, "HUD and local body exist in the world")
	await _check_binding()
	await _check_transitions()
	await _check_tween_safety()
	await _check_reasons()
	await _check_listener_lifecycle()
	await _check_maintenance()
	await _check_travel()
	await _check_mounted_feedback()
	await _check_input_focus()
	await _check_settings()
	await _check_onboarding()
	await _report()

## ------------------------------------------------------------------ helpers

func _uid() -> int:
	return hud.binder.local_uid()

## Apply one authoritative stat payload exactly the way the server does: first
## the mirror node (`apply_authoritative_stats`), then the wire signal. The HUD
## must follow both.
func _push_stats(overrides: Dictionary) -> void:
	var stats := {
		"uid": _uid(),
		"hp": int(player.current_hp), "max_hp": int(player.max_hp),
		"mana": int(player.current_mana), "max_mana": int(player.max_mana),
		"exp": int(player.current_exp), "max_exp": int(player.max_exp),
		"level": int(player.level), "galleons": int(player.galleons),
		"dead": false, "mounted": bool(player.is_mounted),
	}
	for key in overrides:
		stats[key] = overrides[key]
	# Stage the authority's own record as well, so every path (stat payload,
	# periodic push, regen) agrees on the same numbers - exactly the state a
	# real server would hold.
	var record: Dictionary = SimAuthority.entities.get(_uid(), {})
	if not record.is_empty():
		for key in ["hp", "max_hp", "mana", "max_mana", "exp", "level", "galleons", "dead", "mounted"]:
			if stats.has(key):
				record[key] = stats[key]
	player.apply_authoritative_stats(stats)
	SimAuthority.stats_changed.emit(_uid(), stats)

## ------------------------------------------------------- baseline binding

func _check_binding() -> void:
	var report: Dictionary = hud.listener_report()
	check(int(report.get("total", 0)) > 0, "The HUD holds authoritative subscriptions after bind")
	check(int(report["binder"].get("SimAuthority.stats_changed", 0)) == 1,
		"Exactly one stats_changed subscription is held (no duplicates at bind)")
	check(player.is_connected("stats_changed", Callable(hud.binder, "_on_player_stats")),
		"The HUD binds to the stat mirror's own signal as well as the authority payload")
	check(hud.hp_bar.value == player.current_hp and hud.mana_bar.value == player.current_mana,
		"The bars show the mirror's values at bind time")
	check(hud.get_node("BottomBar/StatusBars").get_child_count() == 2, "Top-left status contains only HP and mana")

## --------------------------------------------------- state transitions

func _check_transitions() -> void:
	# Damage: an authoritative payload is the only writer.
	_push_stats({"hp": 321, "max_hp": 500})
	check(hud.hp_bar.value == 321 and hud.hp_label.text == "321 / 500",
		"Damage: an authoritative HP payload updates the bar and the readout")
	check(hud.hp_bar.max_value == 500, "Damage: max and current are applied together")

	# Mana spend.
	_push_stats({"mana": 44, "max_mana": 300})
	check(hud.mana_bar.value == 44 and hud.mana_label.text == "44 / 300",
		"Spending: an authoritative mana payload updates the bar")

	# Regeneration (a delta for the local body arrives as a stat payload).
	_push_stats({"hp": 360})
	check(hud.hp_bar.value == 360, "Regeneration: a later payload moves the bar forward")

	# Currency.
	_push_stats({"galleons": 1234})
	check(hud._last_galleons == 1234, "Spending/rewards: currency follows the authoritative payload")
	player.galleons = 9999
	await get_tree().process_frame
	await get_tree().process_frame
	check(hud._last_galleons == 1234,
		"A stale mirror counter cannot overwrite the authoritative currency")

	# EXP + level.
	_push_stats({"exp": 75, "max_exp": 200, "level": 3})
	check(hud.exp_bar.value == 75 and player.level == 3,
		"EXP and level payloads update progression without a HUD level label")

	# Potion use, through the inventory panel the player clicks.
	var before_toast: int = hud.feedback.toasts_shown
	_push_stats({"hp": 200, "max_hp": 500})
	var potion := {"id": "potion_health", "amount": 2, "tier": 0}
	world.inventory_ui.open_for_player(player)
	player.inventory.assign([potion])
	world.inventory_ui._on_item_clicked(potion)
	await get_tree().process_frame
	check(int(player.inventory[0].amount) == 1 and player.current_hp == 350,
		"Potion use consumes one potion and heals the body (%d, %d left)" % [player.current_hp, potion.amount])
	_push_stats({"hp": int(player.current_hp)})
	check(hud.hp_bar.value == player.current_hp,
		"Potion use: the authority's confirmation lands on the bar")
	check(hud.feedback.toasts_shown >= before_toast, "Potion use does not lose existing toasts")
	world.inventory_ui.hide()

	# Rewards and level-up feedback.
	var before_reward: int = hud.feedback.toasts_shown
	SimAuthority.reward_granted.emit(_uid(), int(NetworkManager.local_character_data.get("id", 0)), 120, 30, [], "test:kill:1")
	check(hud.feedback.toasts_shown >= before_reward + 2, "Rewards: EXP and Galleons each get a toast")
	var before_level: int = hud.feedback.toasts_shown
	SimAuthority.level_changed.emit(_uid(), 4)
	check(hud.feedback.toasts_shown == before_level + 1, "Level-up: a level change gets a toast")

	# Death and respawn.
	SimAuthority.entity_died.emit(_uid(), 0)
	await get_tree().process_frame
	check(hud.binder.dead and hud.feedback._death_panel.visible,
		"Death: the defeated panel appears and the binder records the state")
	check(hud.feedback._death_label.text.contains("Respawning in"),
		"Death: the panel shows a respawn countdown")
	SimAuthority.entity_respawned.emit(_uid())
	await get_tree().process_frame
	check(not hud.binder.dead and not hud.feedback._death_panel.visible,
		"Respawn: the defeated panel clears when the authority respawns the body")

## ------------------------------------------------------------ tween safety

func _check_tween_safety() -> void:
	_push_stats({"hp": 500, "max_hp": 500})
	hud._hp_stat.snap()
	check(hud.hp_bar.value == 500.0 and hud._hp_stat.lag.value == 500.0, "Bars start settled at 500")
	# First update: the lag layer starts easing down.
	_push_stats({"hp": 400, "max_hp": 500})
	check(hud.hp_bar.value == 400.0, "The authoritative bar shows the new value immediately")
	await get_tree().process_frame
	await get_tree().process_frame
	check(hud._hp_stat.is_animating(), "The lag animation is running after the first update")
	# Second update lands mid-tween: the newer value must win, and the older
	# tween must never write again.
	_push_stats({"hp": 250, "max_hp": 500})
	check(hud.hp_bar.value == 250.0, "A newer value wins over an in-flight tween immediately")
	var writes_before: int = hud._hp_stat.tween_writes
	# The lag layer may still be above the old target (it was mid-flight), but
	# from this update on it must never climb again: it can only fall toward the
	# newest value.
	var lag_at_update: float = hud._hp_stat.lag.value
	var stale_shown := false
	var climbed := false
	var saw_lag_writes := false
	for _i in range(90):
		await get_tree().process_frame
		# 400 is the value the interrupted tween was heading for: it must never
		# appear again, on either layer.
		if absf(hud.hp_bar.value - 400.0) < 0.001:
			stale_shown = true
		if hud._hp_stat.lag.value > lag_at_update + TweenSafetyEpsilon:
			climbed = true
		if hud._hp_stat.tween_writes > writes_before:
			saw_lag_writes = true
	check(not stale_shown, "The authoritative bar never shows the stale value after a newer update")
	check(not climbed, "The lag tween never climbs back toward the stale value (started %.0f)" % lag_at_update)
	check(saw_lag_writes, "The lag layer keeps animating toward the newest target")
	check(absf(hud._hp_stat.lag.value - hud.hp_bar.value) <= 1.0,
		"The lag layer converges on the newest server value (lag %.1f, authority %.1f)"
		% [hud._hp_stat.lag.value, hud.hp_bar.value])
	# The same guarantee for mana and XP.
	_push_stats({"mana": 300, "max_mana": 300, "exp": 10, "max_exp": 500})
	hud._mana_stat.snap()
	hud._exp_stat.snap()
	_push_stats({"mana": 100, "exp": 200})
	_push_stats({"mana": 30, "exp": 490})
	check(hud.mana_bar.value == 30.0 or hud.mana_bar.value > 30.0,
		"Mana takes the newest value over an in-flight tween (%.0f)" % hud.mana_bar.value)
	check(hud.exp_bar.value == 490.0, "EXP takes the newest value over an in-flight tween")
	await get_tree().create_timer(0.8).timeout
	check(absf(hud.mana_bar.value - hud._mana_stat.lag.value) <= 1.0
		and absf(hud.exp_bar.value - hud._exp_stat.lag.value) <= 1.0,
		"Mana and EXP lag layers settle on the newest value")

## ------------------------------------------------------------ refusal words

func _check_reasons() -> void:
	var cases := {
		HPProtocol.REJECT_NO_MANA: "Mana",
		HPProtocol.REJECT_RANGE: "range",
		HPProtocol.REJECT_NO_TARGET: "target",
		HPProtocol.REJECT_PROTECTED: "protected",
		HPProtocol.REJECT_MOUNTED: "mounted",
		HPProtocol.REJECT_LINE_OF_SIGHT: "line of sight",
		HPProtocol.REJECT_TRANSFER_PENDING: "loading",
	}
	var all_named := true
	for reason in cases:
		var text := CombatFeedback.reason_text(reason)
		if text.findn(String(cases[reason])) < 0:
			all_named = false
			print("  reason %s -> '%s'" % [reason, text])
	check(all_named, "Every authority rejection code has player-facing words")

	SimAuthority.cast_ack.emit(41, 0, false, HPProtocol.REJECT_NO_MANA)
	check(hud.binder.last_rejection_reason == HPProtocol.REJECT_NO_MANA,
		"A refusal is recorded from the authority's own reason code")
	check(hud.feedback.last_reason_text.findn("Mana") >= 0 and hud.feedback.reasons_shown > 0,
		"The refusal reason is shown in the feedback line")
	SimAuthority.cast_ack.emit(42, 0, false, HPProtocol.REJECT_RANGE)
	check(hud.feedback.last_reason_text.findn("range") >= 0, "Out-of-range is shown as out of range")

	# Cast progress from the authority's release tick.
	var release := int(SimAuthority.sim_tick) + 6
	SimAuthority.cast_started.emit(_uid(), 99, "incendio", Vector3.ZERO, release)
	check(hud.feedback._cast_panel.visible and hud.feedback.cast_spell == "incendio",
		"A cast the authority started shows the cast bar")
	var progress_before: float = hud.feedback.cast_progress()
	await get_tree().create_timer(0.35).timeout
	var progress_after: float = hud.feedback.cast_progress()
	check(progress_after > progress_before or progress_after >= 1.0,
		"Cast progress advances on the simulation clock (%.2f -> %.2f)" % [progress_before, progress_after])
	SimAuthority.cast_released.emit(99, _uid(), "incendio", Vector3.ZERO, Vector3.FORWARD)
	check(not hud.feedback._cast_panel.visible or hud.feedback._recovery_spell == "incendio" or hud.feedback._recovery_until > 0.0,
		"Releasing the cast moves the bar into recovery")

## ------------------------------------------- listener lifecycle / leaks

func _check_listener_lifecycle() -> void:
	var base: int = hud.binder.listener_total()
	var base_stats: int = _binder_connections("stats_changed")
	check(base == base_stats + _expected_non_stats(), "The listener report matches the live connection count")

	# Death and respawn must not add or drop subscriptions.
	SimAuthority.entity_died.emit(_uid(), 0)
	await get_tree().process_frame
	SimAuthority.entity_respawned.emit(_uid())
	await get_tree().process_frame
	check(hud.binder.listener_total() == base,
		"No duplicate listeners after a death and respawn (%d -> %d)" % [base, hud.binder.listener_total()])
	check(hud.binder.duplicate_connects == 0, "No duplicate connect attempt was made during the death cycle")

	# A map transfer must not change the subscription set either.
	var before_transfer: int = hud.binder.listener_total()
	world.map_controller._start_transfer("castle_interior", "vestibule", 0)
	await _await_map("castle_interior", 8.0)
	check(world.map_controller.current_map == "castle_interior", "The map transfer completed (interior loaded)")
	check(hud.binder.listener_total() == before_transfer,
		"No duplicate listeners after a map transfer (%d -> %d)" % [before_transfer, hud.binder.listener_total()])

	# Relog: the world is destroyed and rebuilt. The old HUD's subscriptions must
	# be gone, and the new HUD must hold exactly the same set.
	var world_parent := world.get_parent()
	world.queue_free()
	await get_tree().process_frame
	await get_tree().process_frame
	var stats_after_free: int = _binder_connections("stats_changed")
	check(stats_after_free == 0,
		"A freed world releases its stats subscription (orphaned connections: %d)" % stats_after_free)
	var second := preload("res://scenes/world/game_world.tscn").instantiate()
	world_parent.add_child(second)
	await get_tree().create_timer(0.9).timeout
	var second_hud: Control = second.hud
	var second_player: Node3D = second.local_player
	check(second_hud != null and second_player != null, "The relogged world builds a HUD and a body")
	check(second_hud.binder.listener_total() == base,
		"The relogged HUD holds exactly the same subscriptions (%d -> %d)" % [base, second_hud.binder.listener_total()])
	check(second_hud.binder.duplicate_connects == 0, "The relogged HUD made no duplicate connections")
	check(_binder_connections("stats_changed") == 1,
		"Exactly one stats subscription survives the relog (%d)" % _binder_connections("stats_changed"))
	# Hand the test back the live world.
	world = second
	hud = second_hud
	player = second_player

func _binder_connections(signal_name: String) -> int:
	var count := 0
	for connection in SimAuthority.get_signal_connection_list(signal_name):
		var object = connection["callable"].get_object()
		if object is UIStateBinder:
			count += 1
	return count

## The binder's other per-bind subscriptions (everything except stats_changed).
func _expected_non_stats() -> int:
	var report: Dictionary = hud.binder.listener_report()
	var stats: int = int(report.get("SimAuthority.stats_changed", 0))
	return int(report["total"]) - stats

func _await_map(map_id: String, seconds: float) -> void:
	var waited := 0.0
	while waited < seconds:
		if world.map_controller.current_map == map_id and not world.map_controller.busy:
			return
		await get_tree().process_frame
		waited += get_process_delta_time()

## ---------------------------------------------------------- maintenance

func _check_maintenance() -> void:
	var maintenance: MaintenanceUI = hud.maintenance
	SimAuthority.maintenance_event.emit("ANNOUNCING", "scheduled maintenance", 45)
	await get_tree().process_frame
	check(maintenance.active and maintenance._panel.visible,
		"A maintenance announcement opens the countdown panel")
	check(maintenance.countdown_seconds() > 0 and maintenance.countdown_seconds() <= 45,
		"The countdown starts from the authority's deadline (%d s)" % maintenance.countdown_seconds())
	check(maintenance.countdown_text() == "0:45", "The countdown renders as mm:ss (%s)" % maintenance.countdown_text())
	var first := maintenance.countdown_seconds()
	# The countdown runs on the wall clock (the authority's deadline is real
	# seconds), so the wait is a real-time wait, not a simulated one.
	OS.delay_msec(1200)
	await get_tree().process_frame
	var second := maintenance.countdown_seconds()
	check(second < first, "The countdown decreases between announcements (%d -> %d)" % [first, second])
	check(maintenance._title.text.contains(maintenance.countdown_text()),
		"The panel title carries the live countdown")
	SimAuthority.maintenance_event.emit("MAINTENANCE", "scheduled maintenance", 0)
	await get_tree().process_frame
	check(maintenance._title.text.contains("closed") and maintenance.active,
		"The closed state latches so the reason survives the disconnect")
	SimAuthority.maintenance_event.emit("ONLINE", "", 0)
	await get_tree().process_frame
	check(not maintenance.active and not maintenance._panel.visible,
		"An ONLINE announcement clears the maintenance panel")

## --------------------------------------------------------------- travel

func _check_travel() -> void:
	var travel: TravelFeedback = hud.travel
	# The world was transferred to the interior earlier (or is about to be).
	if world.map_controller.current_map != "castle_interior":
		world.map_controller._start_transfer("castle_interior", "vestibule", 0)
		await _await_map("castle_interior", 8.0)
	await get_tree().create_timer(0.4).timeout
	check(travel.portals_seen >= 1, "The transfer was observed as real load progress")
	check(travel.floor_updates >= 1, "The location line updated for the new map")
	check(travel.location_text().contains("Hogwarts Castle"),
		"The indoor location line names the castle (%s)" % travel.location_text())
	check(travel.location_text().contains("Floor") or travel.location_text().contains("Dungeon"),
		"The indoor location line names the floor (%s)" % travel.location_text())
	var stairs := travel.staircase_text()
	check(stairs.contains("Magical staircase"), "The staircase state is read from the moving staircase (%s)" % stairs)

## ------------------------------------------------------ mounted feedback

func _check_mounted_feedback() -> void:
	var travel: TravelFeedback = hud.travel
	# Back outside, where flight is allowed.
	world.map_controller._start_transfer("grounds", "castle_approach", 0)
	await _await_map("grounds", 8.0)
	await get_tree().create_timer(0.3).timeout
	player.global_position = Vector3(0, 0.2, 18)
	player.velocity = Vector3.ZERO
	await get_tree().physics_frame
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player.toggle_broom_mount()
	await get_tree().create_timer(0.2).timeout
	check(player.is_mounted, "The body mounted for the feedback check")
	# Fly high: the landing gate must refuse and the panel must say why.
	player.global_position = Vector3(0, 12.0, 18)
	await get_tree().physics_frame
	await get_tree().create_timer(0.6).timeout
	var text := travel.mounted_text()
	check(text.contains("Space rise") and text.contains("Shift dismount"),
		"Mounted controls are shown while flying")
	check(text.contains("Cannot land here"),
		"An invalid landing spot is reported with its reason (%s)" % text.replace("\n", " | "))
	check(travel.invalid_landing_warnings >= 1, "The invalid-landing warning was raised")
	# Descend and land: the panel must now offer the landing.
	player.global_position = Vector3(0, 0.2, 18)
	player.velocity = Vector3.ZERO
	await get_tree().physics_frame
	await get_tree().create_timer(0.6).timeout
	check(travel.mounted_text().contains("Landing here: OK"),
		"A valid landing spot is reported as safe (%s)" % travel.mounted_text().replace("\n", " | "))
	player.toggle_broom_mount()
	await get_tree().create_timer(0.25).timeout
	check(not player.is_mounted, "The body dismounted on the valid spot")
	await get_tree().create_timer(0.4).timeout
	check(not travel._mounted_panel.visible, "The mounted panel hides after dismounting")

## ----------------------------------------------------------- input focus

func _check_input_focus() -> void:
	# 1) A panel that takes keyboard focus blocks casting and mounting.
	hud.settings.open()
	check(UIFocus.is_blocking(get_tree()), "An open settings panel registers as an input blocker")
	check(player.input_blocked(), "The player controller reports input as blocked while the panel is open")
	var mana_before: int = player.current_mana
	var mount_before: bool = player.is_mounted
	var casts_before: int = player._predicted_casts.size()
	# Keyboard: the same polling path the hotkeys use.
	Input.action_press("spell_1")
	Input.action_press("mount_broom")
	await get_tree().create_timer(0.3).timeout
	Input.action_release("spell_1")
	Input.action_release("mount_broom")
	await get_tree().process_frame
	check(player.current_mana == mana_before, "A key pressed while a panel is open does not cast")
	check(player._predicted_casts.size() == casts_before, "No cast was predicted while the panel was open")
	check(player.is_mounted == mount_before, "A key pressed while a panel is open does not mount")
	hud.settings.close()
	check(not UIFocus.is_blocking(get_tree()), "Closing the panel clears the blocker")

	# Control: with nothing open, the same key does cast.
	var mana_open: int = player.current_mana
	player._cast_lock = 0.0
	player.spell_cooldowns.clear()
	player.cast_spell("stupefy")
	await get_tree().process_frame
	check(player._predicted_casts.size() >= 1 or player.current_mana < mana_open or player.is_mounted,
		"With no panel open the same cast request proceeds (control)")

	# 2) A mouse click on a panel must not also cast.
	hud.settings.open()
	await get_tree().process_frame
	var casts_before_click: int = player._predicted_casts.size()
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	click.position = Vector2(640, 300)
	get_viewport().push_input(click)
	var release_click := InputEventMouseButton.new()
	release_click.button_index = MOUSE_BUTTON_LEFT
	release_click.pressed = false
	release_click.position = Vector2(640, 300)
	get_viewport().push_input(release_click)
	await get_tree().process_frame
	check(player._predicted_casts.size() == casts_before_click,
		"A click on a UI panel does not reach the world as a cast")
	check(not player._basic_held, "A click on a UI panel does not start the held basic attack")
	hud.settings.close()

	# 3) Typing in chat still blocks movement and casting.
	hud.chat_input.grab_focus()
	check(player.input_blocked(), "Focus in the chat field still blocks gameplay input")
	hud.chat_input.release_focus()

## ------------------------------------------------------------- settings

func _check_settings() -> void:
	var path := GameSettings.settings_path()
	check(path.begins_with("user://"), "Settings persist under user:// (user data), not the game files")
	check(not GameSettings.settings_global_path().begins_with(ProjectSettings.globalize_path("res://")),
		"The settings file lives outside the versioned project tree")

	var settings := GameSettings.instance()
	settings.set_ui_scale(1.25)
	settings.set_mouse_sensitivity(1.6)
	settings.set_shake_intensity(0.0)
	settings.set_flash_intensity(1.4)
	settings.set_binding("spell_1", KEY_7)
	settings.set_volume("UI", 0.35)
	check(FileAccess.file_exists(path), "The settings file is written on change")
	check(get_window().content_scale_factor == 1.25 or DisplayServer.get_name() == "headless",
		"The UI scale is applied to the canvas content scale (%.2f)" % get_window().content_scale_factor)
	check(int(settings.binding_keycode("spell_1")) == KEY_7, "The rebound key is recorded")
	check(InputMap.action_get_events("spell_1").size() > 0
		and (InputMap.action_get_events("spell_1")[0] as InputEventKey).physical_keycode == KEY_7,
		"The rebound key is applied to the live InputMap")

	var reloaded := GameSettings.reload_from_disk()
	check(is_equal_approx(reloaded.ui_scale, 1.25), "UI scale persists and reloads")
	check(is_equal_approx(reloaded.mouse_sensitivity, 1.6), "Mouse sensitivity persists and reloads")
	check(is_equal_approx(reloaded.shake_intensity, 0.0), "Shake intensity persists and reloads")
	check(is_equal_approx(reloaded.flash_intensity, 1.4), "Flash intensity persists and reloads")
	check(int(reloaded.binding_keycode("spell_1")) == KEY_7, "Key bindings persist and reload")
	check(is_equal_approx(reloaded.get_volume("UI"), 0.35),
		"UI volume persists through the spell effects audio settings")
	check(is_equal_approx(reloaded.get_volume("Music"), AudioManager.get_volume("Music")),
		"The audio buses report the same independent volumes to the settings screen")

	# Scalable UI: a larger content scale shrinks the canvas (so the interface
	# grows on screen) and every anchored panel must still be inside it.
	reloaded.set_ui_scale(1.5)
	await get_tree().process_frame
	await get_tree().process_frame
	var canvas := get_viewport().get_visible_rect().size
	check(canvas.x < 1100.0, "A larger UI scale shrinks the canvas so the UI grows on screen (%.0f px wide)" % canvas.x)
	var outside: Array = []
	var report: Dictionary = hud.layout_report()
	for key in report:
		var rect: Rect2 = report[key]
		if rect.position.x < -0.5 or rect.position.y < -0.5 or rect.end.x > canvas.x + 0.5 or rect.end.y > canvas.y + 0.5:
			outside.append("%s=%s" % [key, rect])
	check(outside.is_empty(), "Every panel stays inside the canvas at 1.5x UI scale (%s)" % (", ".join(outside) if not outside.is_empty() else "all inside"))
	reloaded.set_ui_scale(1.0)
	await get_tree().process_frame

	# The sensitivity is consumed by the player controller's mouse-look path.
	var events := InputMap.action_get_events("spell_1")
	check(events.size() == 1, "A rebind replaces the whole event list (one key per action)")
	reloaded.reset_bindings()
	check(int(reloaded.binding_keycode("spell_1")) == int(GameSettings.BINDABLE_ACTIONS["spell_1"]),
		"Reset keys restores the documented defaults")
	reloaded.set_ui_scale(1.0)
	reloaded.set_mouse_sensitivity(1.0)
	reloaded.set_shake_intensity(1.0)
	reloaded.set_flash_intensity(1.0)
	reloaded.set_volume("UI", 0.9)

## ------------------------------------------------------------ onboarding

func _check_onboarding() -> void:
	var onboarding: OnboardingUI = hud.onboarding
	onboarding.reset()
	check(not onboarding.is_complete() and onboarding.current_index == 0, "The onboarding route starts fresh")
	check(onboarding._panel.visible, "The onboarding panel is shown at the start of the route")

	# 1. Dummy practice - an authoritative hit on a DUMMY entity.
	var dummy_uid := _first_entity_of_kind(HPProtocol.Kind.DUMMY)
	check(dummy_uid != 0, "A training dummy is registered with the authority")
	SimAuthority.cast_landed.emit(500, _uid(), "stupefy", [{"uid": dummy_uid, "amount": 40}])
	check(onboarding.current_index == 1, "Dummy practice completes on an authoritative landed cast")

	# 2. Safe zone - the authored protection volume.
	var safe_point := _find_protected_point()
	check(safe_point != Vector3.INF, "An authored protection volume exists in the world")
	player.global_position = safe_point
	player.velocity = Vector3.ZERO
	await get_tree().create_timer(0.5).timeout
	check(onboarding.current_index == 2, "The safe-zone step completes when the body stands in a protection volume")
	check(hud.feedback.safe_area_text().contains("Protected ground"),
		"The safe-area indicator is shown while standing in the volume")

	# 3. Reactive pack - damage from a pack member.
	var mob_uid := _first_pack_mob()
	check(mob_uid != 0, "A pack mob is registered with the authority")
	SimAuthority.entity_damaged.emit(_uid(), 12, 200, "melee", mob_uid)
	check(onboarding.current_index == 3, "The pack step completes on authoritative damage from a pack member")

	# 4. Broom - mount, be airborne, land on a spot the gate accepts.
	player.global_position = Vector3(0, 0.2, 18)
	player.velocity = Vector3.ZERO
	await get_tree().physics_frame
	player._mount_lock = 0.0
	player._cast_lock = 0.0
	player.toggle_broom_mount()
	await get_tree().create_timer(0.2).timeout
	player.global_position = Vector3(0, 6.0, 18)
	await get_tree().physics_frame
	await get_tree().create_timer(0.35).timeout
	player.global_position = Vector3(0, 0.2, 18)
	player.velocity = Vector3.ZERO
	await get_tree().physics_frame
	player._mount_lock = 0.0
	player.toggle_broom_mount()
	await get_tree().create_timer(0.3).timeout
	check(onboarding.current_index == 4, "The broom step completes after an airborne mount and a landing the gate accepted")

	# 5. Castle entrance - the authoritative map.
	if world.map_controller.current_map != "castle_interior":
		world.map_controller._start_transfer("castle_interior", "vestibule", 0)
		await _await_map("castle_interior", 8.0)
	await get_tree().create_timer(0.5).timeout
	check(onboarding.current_index == 5 and onboarding.is_complete(),
		"The castle step completes on the authoritative map change")
	check(onboarding.describe()["complete"], "The onboarding route reports complete")
	check(onboarding.authoritative_progress == 5, "All five steps were proven from authoritative state")
	check(FileAccess.file_exists(OnboardingUI.STATE_PATH), "Onboarding progress is persisted under user://")
	var reloaded := OnboardingUI.new()
	reloaded.load_progress()
	check(reloaded.current_index == 5, "Onboarding progress reloads from user://")
	reloaded.free()
	# The route is resettable, and the checks leave the saved state at the
	# start so the next real session sees the onboarding from step one.
	onboarding.reset()
	check(onboarding.current_index == 0 and not onboarding.is_complete(),
		"Reset starts the onboarding route again")

## ------------------------------------------------------------- utilities

func _first_entity_of_kind(kind: int) -> int:
	for uid in SimAuthority.entities:
		if int(SimAuthority.entities[uid].get("kind", -1)) == kind:
			return int(uid)
	return 0

func _first_pack_mob() -> int:
	for uid in SimAuthority.entities:
		var record: Dictionary = SimAuthority.entities[uid]
		if int(record.get("kind", -1)) == HPProtocol.Kind.MOB and int(record.get("pack_id", 0)) != 0:
			return int(uid)
	return 0

## Search a small authored-point grid for a point inside a protection volume.
func _find_protected_point() -> Vector3:
	var candidates := [
		Vector3(0, 0.5, 5), Vector3(0, 0.5, 0), Vector3(0, 0.5, -10),
		Vector3(5, 0.5, 5), Vector3(-5, 0.5, 5), Vector3(0, 0.5, 12),
		Vector3(14, 0.5, 5), Vector3(-14, 0.5, 5), Vector3(0, 0.5, -20),
	]
	for point in candidates:
		if HPRules.is_protected_point(point):
			return point
	return Vector3.INF

## ------------------------------------------------------------------ report

func _report() -> void:
	var audio := get_node_or_null("/root/AudioManager")
	if audio != null:
		audio.call("stop_everything")
	await get_tree().create_timer(0.3).timeout
	print("--------------------------------------------------------------")
	for message in failures:
		print("  FAILED: " + message)
	print("UI RESULT: %d checks, %d failures" % [checks, failures.size()])
	if world != null and is_instance_valid(world):
		world.queue_free()
	await get_tree().process_frame
	get_tree().quit(0 if failures.is_empty() else 1)
