extends Control

## Main Menu for PotterMetin MMO
## House Selection, Character Name, Singleplayer / Host / Join Game Modes

@onready var name_input: LineEdit = $VBoxContainer/NameRow/NameInput
@onready var house_desc_label: Label = $VBoxContainer/HouseDescLabel
@onready var host_btn: Button = $VBoxContainer/Buttons/HostButton
@onready var join_btn: Button = $VBoxContainer/Buttons/JoinButton
@onready var solo_btn: Button = $VBoxContainer/Buttons/SoloButton
@onready var ip_input: LineEdit = $VBoxContainer/NetworkRow/IpInput
@onready var port_input: LineEdit = $VBoxContainer/NetworkRow/PortInput
@onready var status_label: Label = $VBoxContainer/StatusLabel

# House selection buttons
@onready var gryf_btn: Button = $VBoxContainer/HouseSelection/GryffindorBtn
@onready var slyth_btn: Button = $VBoxContainer/HouseSelection/SlytherinBtn
@onready var raven_btn: Button = $VBoxContainer/HouseSelection/RavenclawBtn
@onready var huff_btn: Button = $VBoxContainer/HouseSelection/HufflepuffBtn

var selected_house: String = "Gryffindor"
var _is_connecting: bool = false

func _ready() -> void:
	gryf_btn.pressed.connect(func(): _select_house("Gryffindor"))
	slyth_btn.pressed.connect(func(): _select_house("Slytherin"))
	raven_btn.pressed.connect(func(): _select_house("Ravenclaw"))
	huff_btn.pressed.connect(func(): _select_house("Hufflepuff"))
	
	host_btn.pressed.connect(_on_host_pressed)
	join_btn.pressed.connect(_on_join_pressed)
	solo_btn.pressed.connect(_on_solo_pressed)
	
	NetworkManager.connection_status_changed.connect(_on_network_status)
	NetworkManager.connection_succeeded.connect(_on_connection_succeeded)
	NetworkManager.connection_failed.connect(_on_connection_failed)
	
	_select_house("Gryffindor")

func _exit_tree() -> void:
	if NetworkManager.connection_status_changed.is_connected(_on_network_status):
		NetworkManager.connection_status_changed.disconnect(_on_network_status)
	if NetworkManager.connection_succeeded.is_connected(_on_connection_succeeded):
		NetworkManager.connection_succeeded.disconnect(_on_connection_succeeded)
	if NetworkManager.connection_failed.is_connected(_on_connection_failed):
		NetworkManager.connection_failed.disconnect(_on_connection_failed)

func _select_house(h_name: String) -> void:
	selected_house = h_name
	NetworkManager.local_player_house = selected_house
	
	var data = GameData.HOUSES[h_name]
	house_desc_label.text = "%s - \"%s\"\nTrait: %s" % [data.name, data.motto, data.trait]
	house_desc_label.modulate = data.primary_color
	
	# Highlight selected button
	gryf_btn.flat = (h_name != "Gryffindor")
	slyth_btn.flat = (h_name != "Slytherin")
	raven_btn.flat = (h_name != "Ravenclaw")
	huff_btn.flat = (h_name != "Hufflepuff")

func _apply_player_settings() -> void:
	var c_name = name_input.text.strip_edges()
	if c_name.is_empty():
		c_name = "Wizard"
	NetworkManager.local_player_name = c_name
	NetworkManager.local_player_house = selected_house

func _set_buttons_enabled(enabled: bool) -> void:
	_is_connecting = not enabled
	host_btn.disabled = not enabled
	solo_btn.disabled = not enabled
	if enabled:
		join_btn.disabled = false
		join_btn.text = "Join Game"
	else:
		join_btn.disabled = false # Keep join button clickable as Cancel
		join_btn.text = "Cancel"

func _on_solo_pressed() -> void:
	if _is_connecting:
		NetworkManager.disconnect_game()
		_set_buttons_enabled(true)
	_apply_player_settings()
	NetworkManager.start_offline()
	if is_inside_tree() and get_tree():
		get_tree().change_scene_to_file("res://scenes/world/game_world.tscn")

func _on_host_pressed() -> void:
	if _is_connecting:
		NetworkManager.disconnect_game()
		_set_buttons_enabled(true)
	_apply_player_settings()
	var port = int(port_input.text) if not port_input.text.is_empty() else 7777
	var err = NetworkManager.host_game(port)
	if err == OK:
		if is_inside_tree() and get_tree():
			get_tree().change_scene_to_file("res://scenes/world/game_world.tscn")

func _on_join_pressed() -> void:
	if _is_connecting:
		# User pressed "Cancel"
		NetworkManager.disconnect_game()
		_set_buttons_enabled(true)
		status_label.text = "Connection cancelled."
		return
	
	_apply_player_settings()
	var ip = ip_input.text.strip_edges()
	if ip.is_empty():
		ip = "127.0.0.1"
	var port = int(port_input.text) if not port_input.text.is_empty() else 7777
	
	_set_buttons_enabled(false)
	status_label.text = "Connecting to %s:%d..." % [ip, port]
	
	var err = NetworkManager.join_game(ip, port)
	if err != OK:
		_set_buttons_enabled(true)
		status_label.text = "Failed to connect to %s:%d" % [ip, port]

func _on_connection_succeeded() -> void:
	if not is_inside_tree():
		return
	var tree := get_tree()
	if tree:
		tree.change_scene_to_file("res://scenes/world/game_world.tscn")

func _on_connection_failed() -> void:
	_set_buttons_enabled(true)

func _on_network_status(msg: String) -> void:
	status_label.text = msg
