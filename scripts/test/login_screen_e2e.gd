extends Node

## Drives the real login screen against a running stack (account service +
## world server), the way a player would: type, press the button, watch.
##
##   godot --headless --path client res://scenes/test/login_screen_e2e.tscn \
##       --ip 127.0.0.1 --port <world udp> --no-autologin
##   env: HPMMO_API_URL=http://127.0.0.1:<api>   LOGIN_E2E_MODE=register|maintenance
##        LOGIN_E2E_USER / LOGIN_E2E_PASS
##
## register    -> create an account on the "Hesap Oluştur" tab; the screen must log
##                straight in, join the world and open character selection.
## maintenance -> the service refuses the login (maintenance.flag): the screen must
##                say so and show the maintenance notice, and stay on the login screen.
## Prints one "LOGIN_E2E PASS|FAIL: ..." line per check and exits 0 only when all pass.

const MENU := "res://scenes/main/main_menu.tscn"
const SELECT := "res://scenes/main/character_select.tscn"
const TIMEOUT := 40.0

var _failures := 0
var _menu: Control = null

func _ready() -> void:
	# This node is a child of the root; once the menu is the current scene,
	# the menu's own change_scene frees the menu and leaves the driver alive.
	var root := get_tree().root
	await get_tree().process_frame
	_menu = (load(MENU) as PackedScene).instantiate()
	root.add_child(_menu)
	get_tree().current_scene = _menu
	await get_tree().create_timer(0.5).timeout
	# A login saves the remembered username; keep the developer's own choice.
	var prefs_path: String = (_menu.get_script() as Script).get_script_constant_map()["PREFS_PATH"]
	var saved_prefs = FileAccess.get_file_as_string(prefs_path) if FileAccess.file_exists(prefs_path) else null
	var mode := OS.get_environment("LOGIN_E2E_MODE")
	if mode == "maintenance":
		await _run_maintenance()
	else:
		await _run_register()
	if saved_prefs == null:
		DirAccess.remove_absolute(ProjectSettings.globalize_path(prefs_path))
	else:
		var f := FileAccess.open(prefs_path, FileAccess.WRITE)
		if f != null:
			f.store_string(saved_prefs)
	print("LOGIN_E2E RESULT: %d failure(s)" % _failures)
	get_tree().quit(1 if _failures > 0 else 0)

func check(ok: bool, what: String) -> void:
	print("LOGIN_E2E %s: %s" % ["PASS" if ok else "FAIL", what])
	if not ok:
		_failures += 1

func _type_credentials(register: bool) -> void:
	if register:
		_menu.call("_set_mode", true)
	_menu.get("username_input").text = OS.get_environment("LOGIN_E2E_USER")
	_menu.get("password_input").text = OS.get_environment("LOGIN_E2E_PASS")
	if register:
		_menu.get("confirm_input").text = OS.get_environment("LOGIN_E2E_PASS")
	(_menu.get("submit_btn") as Button).pressed.emit()

func _run_register() -> void:
	_type_credentials(true)
	var waited := 0.0
	var reached := false
	while waited < TIMEOUT:
		var scene := get_tree().current_scene
		if scene != null and scene.scene_file_path == SELECT:
			reached = true
			break
		await get_tree().create_timer(0.25).timeout
		waited += 0.25
	var status := ""
	if is_instance_valid(_menu) and _menu.get("status_label") != null:
		status = (_menu.get("status_label") as Label).text
	check(reached, "register + login + world join opens character selection (last status: '%s')" % status)
	check(NetworkManager.is_connected_to_game, "the client is connected to the world server")
	check(DatabaseManager.session_active and not DatabaseManager.session_token.is_empty(),
		"a session token is held in memory")

func _run_maintenance() -> void:
	_type_credentials(false)
	var waited := 0.0
	var label: Label = _menu.get("status_label")
	while waited < TIMEOUT and not label.text.contains("bakımda"):
		await get_tree().create_timer(0.25).timeout
		waited += 0.25
	check(label.text.contains("bakımda"), "a refused login says the server is under maintenance ('%s')" % label.text)
	check((_menu.get("notice_panel") as Control).visible, "the maintenance notice is shown")
	check(str(_menu.get("server_state")) == "MAINTENANCE", "the server pill switches to maintenance")
	check(get_tree().current_scene == _menu, "the player stays on the login screen")
	check(not DatabaseManager.session_active, "no session was created")
	check(not (_menu.get("submit_btn") as Button).disabled, "the button is usable again for a retry")
