extends Node3D

## GameWorld - Main 3D World for PotterMetin MMO
## Spawns local & remote players, Dark Monoliths, mob packs, and binds UI layers

@onready var players_container: Node3D = $Players
@onready var mobs_container: Node3D = $Mobs
@onready var monoliths_container: Node3D = $Monoliths
@onready var hud: Control = $CanvasLayer/HUD
@onready var inventory_ui: Control = $CanvasLayer/InventoryUI
@onready var ollivander_ui: Control = $CanvasLayer/OllivanderUI

const PLAYER_SCENE = preload("res://scenes/entities/player/player.tscn")
const MONOLITH_SCENE = preload("res://scenes/entities/monolith/dark_monolith.tscn")
const INFERI_SCENE = preload("res://scenes/entities/mobs/mob_inferi.tscn")
const ACROMANTULA_SCENE = preload("res://scenes/entities/mobs/mob_acromantula.tscn")
const SNATCHER_SCENE = preload("res://scenes/entities/mobs/mob_darksnatcher.tscn")

var local_player: Node3D = null

func _ready() -> void:
	_spawn_local_player()
	_setup_monoliths_and_mobs()
	_connect_ui_signals()
	
	# Multiplayer hooks
	NetworkManager.player_connected_signal.connect(_on_remote_player_connected)
	NetworkManager.player_disconnected_signal.connect(_on_remote_player_disconnected)
	
	# Spawn any peers that were already connected
	for peer_id in NetworkManager.connected_players.keys():
		if peer_id != 1 and peer_id != multiplayer.get_unique_id():
			_spawn_remote_player(peer_id, NetworkManager.connected_players[peer_id])

func _spawn_local_player() -> void:
	local_player = PLAYER_SCENE.instantiate()
	local_player.is_local_player = true
	local_player.player_name = NetworkManager.local_player_name
	local_player.house = NetworkManager.local_player_house
	players_container.add_child(local_player)
	local_player.global_position = Vector3(0, 0.5, 5.0)
	
	# Bind HUD & UI
	hud.bind_player(local_player)

func _connect_ui_signals() -> void:
	hud.inventory_button.pressed.connect(_toggle_inventory)
	hud.ollivander_button.pressed.connect(_toggle_ollivander)

func _input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_inventory"):
		_toggle_inventory()
	elif event.is_action_pressed("toggle_ollivander"):
		_toggle_ollivander()
	elif event.is_action_pressed("toggle_chat"):
		hud.chat_input.grab_focus()

func _toggle_inventory() -> void:
	if inventory_ui.visible:
		inventory_ui.hide()
	else:
		inventory_ui.open_for_player(local_player)

func _toggle_ollivander() -> void:
	if ollivander_ui.visible:
		ollivander_ui.hide()
	else:
		ollivander_ui.open_for_player(local_player)

func _setup_monoliths_and_mobs() -> void:
	# Spawn Metin Stones (Dark Monoliths) across the landscape
	var monolith_locations = [
		Vector3(0, 0, -32.0),
		Vector3(45.0, 0, -25.0),
		Vector3(-45.0, 0, -28.0)
	]
	
	for pos in monolith_locations:
		var monolith = MONOLITH_SCENE.instantiate()
		monoliths_container.add_child(monolith)
		monolith.global_position = pos
	
	# Spawn roaming creature packs
	_spawn_mob_pack(INFERI_SCENE, 4, Vector3(18.0, 0, -18.0))
	_spawn_mob_pack(ACROMANTULA_SCENE, 4, Vector3(-22.0, 0, -20.0))
	_spawn_mob_pack(SNATCHER_SCENE, 3, Vector3(32.0, 0, -42.0))
	_spawn_mob_pack(INFERI_SCENE, 4, Vector3(-35.0, 0, -45.0))

func _spawn_mob_pack(scene: PackedScene, count: int, center_pos: Vector3) -> void:
	for i in range(count):
		var mob = scene.instantiate()
		mobs_container.add_child(mob)
		var angle := randf() * TAU
		var dist := randf_range(1.5, 5.0)
		mob.global_position = center_pos + Vector3(cos(angle) * dist, 0.2, sin(angle) * dist)

func _on_remote_player_connected(peer_id: int, info: Dictionary) -> void:
	_spawn_remote_player(peer_id, info)

func _spawn_remote_player(peer_id: int, info: Dictionary) -> void:
	var existing = players_container.get_node_or_null(str(peer_id))
	if existing:
		return
	
	var remote_p = PLAYER_SCENE.instantiate()
	remote_p.name = str(peer_id)
	remote_p.is_local_player = false
	remote_p.player_name = info.get("name", "Wizard")
	remote_p.house = info.get("house", "Gryffindor")
	players_container.add_child(remote_p)
	remote_p.global_position = Vector3(randf_range(-2, 2), 0.5, randf_range(3, 7))
	NetworkManager.send_chat("[Server] %s [%s] joined the realm!" % [remote_p.player_name, remote_p.house])

func _on_remote_player_disconnected(peer_id: int) -> void:
	var node = players_container.get_node_or_null(str(peer_id))
	if node:
		node.queue_free()
