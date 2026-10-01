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

func _ready() -> void:
	gryf_btn.pressed.connect(func(): _select_house("Gryffindor"))
	slyth_btn.pressed.connect(func(): _select_house("Slytherin"))
	raven_btn.pressed.connect(func(): _select_house("Ravenclaw"))
	huff_btn.pressed.connect(func(): _select_house("Hufflepuff"))
	
	host_btn.pressed.connect(_on_host_pressed)
	join_btn.pressed.connect(_on_join_pressed)
	solo_btn.pressed.connect(_on_solo_pressed)
	
	NetworkManager.connection_status_changed.connect(_on_network_status)
	_select_house("Gryffindor")

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

func _on_solo_pressed() -> void:
	_apply_player_settings()
	NetworkManager.start_offline()
	get_tree().change_scene_to_file("res://scenes/world/game_world.tscn")

func _on_host_pressed() -> void:
	_apply_player_settings()
	var port = int(port_input.text) if not port_input.text.is_empty() else 7777
	var err = NetworkManager.host_game(port)
	if err == OK:
		get_tree().change_scene_to_file("res://scenes/world/game_world.tscn")

func _on_join_pressed() -> void:
	_apply_player_settings()
	var ip = ip_input.text.strip_edges()
	if ip.is_empty():
		ip = "127.0.0.1"
	var port = int(port_input.text) if not port_input.text.is_empty() else 7777
	var err = NetworkManager.join_game(ip, port)
	if err == OK:
		status_label.text = "Connecting to %s:%d..." % [ip, port]
		# Scene transition will trigger on connected_to_server
		NetworkManager.multiplayer.connected_to_server.connect(func():
			get_tree().change_scene_to_file("res://scenes/world/game_world.tscn")
		)

func _on_network_status(msg: String) -> void:
	status_label.text = msg
