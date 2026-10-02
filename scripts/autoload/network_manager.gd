extends Node

## NetworkManager Autoload - Multiplayer ENet Host/Client Management
## Handles connection lifecycle, peer registry, chat replication, state relaying, and dedicated server mode

signal player_connected_signal(peer_id: int, player_info: Dictionary)
signal player_disconnected_signal(peer_id: int)
signal connection_status_changed(status: String)
signal chat_message_received(sender_name: String, sender_house: String, message: String)
signal remote_spell_cast(peer_id: int, spell_id: String, from_pos: Vector3, dir: Vector3)

const DEFAULT_PORT: int = 7777
const MAX_PLAYERS: int = 32

var peer: ENetMultiplayerPeer = null
var is_server: bool = false
var is_dedicated_server: bool = false
var is_connected_to_game: bool = false
var _sync_timer: float = 0.0

var local_player_name: String = "Harry"
var local_player_house: String = "Gryffindor"
var connected_players: Dictionary = {}
var remote_states: Dictionary = {} # peer_id -> {pos, rot_y, mounted, hp, level}

func _ready() -> void:
	multiplayer.peer_connected.connect(_on_peer_connected)
	multiplayer.peer_disconnected.connect(_on_peer_disconnected)
	multiplayer.connected_to_server.connect(_on_connected_to_server)
	multiplayer.connection_failed.connect(_on_connection_failed)
	multiplayer.server_disconnected.connect(_on_server_disconnected)

## Start Authoritative Dedicated Server (for Linux VPS)
func start_dedicated_server(port: int = DEFAULT_PORT) -> Error:
	peer = ENetMultiplayerPeer.new()
	var error := peer.create_server(port, MAX_PLAYERS)
	if error != OK:
		print("[Server ERROR] Failed to bind UDP port %d: Error %d" % [port, error])
		emit_signal("connection_status_changed", "Failed to start dedicated server on port %d" % port)
		return error
	
	multiplayer.multiplayer_peer = peer
	is_server = true
	is_dedicated_server = true
	is_connected_to_game = true
	print("=========================================================")
	print("[Dedicated Server] PotterMetin MMO Running on Port %d" % port)
	print("[Dedicated Server] Ready for incoming player connections!")
	print("=========================================================")
	emit_signal("connection_status_changed", "Dedicated Server active on port %d" % port)
	return OK

## Host a new game (Server + Local Player)
func host_game(port: int = DEFAULT_PORT) -> Error:
	peer = ENetMultiplayerPeer.new()
	var error := peer.create_server(port, MAX_PLAYERS)
	if error != OK:
		emit_signal("connection_status_changed", "Failed to host on port %d" % port)
		return error
	
	multiplayer.multiplayer_peer = peer
	is_server = true
	is_dedicated_server = false
	is_connected_to_game = true
	
	var local_info := {
		"name": local_player_name,
		"house": local_player_house,
		"level": 1,
		"wand_tier": 0
	}
	connected_players[1] = local_info
	emit_signal("connection_status_changed", "Server started on port %d" % port)
	return OK

## Join an existing game via IP and port
func join_game(address: String = "213.250.145.75", port: int = DEFAULT_PORT) -> Error:
	peer = ENetMultiplayerPeer.new()
	var error := peer.create_client(address, port)
	if error != OK:
		emit_signal("connection_status_changed", "Failed to connect to %s:%d" % [address, port])
		return error
		
	multiplayer.multiplayer_peer = peer
	is_server = false
	is_dedicated_server = false
	emit_signal("connection_status_changed", "Connecting to %s:%d..." % [address, port])
	return OK

## Start singleplayer / offline session
func start_offline() -> void:
	is_server = true
	is_dedicated_server = false
	is_connected_to_game = true
	connected_players[1] = {
		"name": local_player_name,
		"house": local_player_house,
		"level": 1,
		"wand_tier": 0
	}
	emit_signal("connection_status_changed", "Offline mode active")

func _on_peer_connected(id: int) -> void:
	print("[Network] Peer connected: ID %d" % id)
	if multiplayer.is_server():
		# Sync all currently connected players to the new peer
		for p_id in connected_players:
			_sync_player_info.rpc_id(id, p_id, connected_players[p_id])

func _on_peer_disconnected(id: int) -> void:
	print("[Network] Peer disconnected: ID %d" % id)
	if connected_players.has(id):
		var p_info = connected_players[id]
		print("[Server] Player left: %s [%s]" % [p_info.get("name", "Wizard"), p_info.get("house", "Gryffindor")])
		connected_players.erase(id)
	remote_states.erase(id)
	emit_signal("player_disconnected_signal", id)

func _on_connected_to_server() -> void:
	is_connected_to_game = true
	var my_id := multiplayer.get_unique_id()
	var my_info := {
		"name": local_player_name,
		"house": local_player_house,
		"level": 1,
		"wand_tier": 0
	}
	connected_players[my_id] = my_info
	emit_signal("connection_status_changed", "Connected to server as ID %d" % my_id)
	_register_my_info.rpc(my_info)

func _on_connection_failed() -> void:
	multiplayer.multiplayer_peer = null
	is_connected_to_game = false
	emit_signal("connection_status_changed", "Connection failed! Check server IP & firewall.")

func _on_server_disconnected() -> void:
	multiplayer.multiplayer_peer = null
	is_connected_to_game = false
	is_server = false
	is_dedicated_server = false
	connected_players.clear()
	remote_states.clear()
	emit_signal("connection_status_changed", "Disconnected from server.")

func _process(delta: float) -> void:
	if not is_connected_to_game or not multiplayer.has_multiplayer_peer():
		return
	if is_dedicated_server:
		return
	
	# 15 Hz transform broadcast from local player to server
	_sync_timer -= delta
	if _sync_timer <= 0.0:
		_sync_timer = 1.0 / 15.0
		var lp := _find_local_player()
		if lp:
			rpc_broadcast_state.rpc(lp.global_position, lp.rotation.y, lp.is_mounted, lp.current_hp, lp.level)

func _find_local_player() -> Node3D:
	var players := get_tree().get_nodes_in_group("players")
	for p in players:
		if is_instance_valid(p) and p.get("is_local_player") == true:
			return p
	return null

## Player movement broadcast & server relay
@rpc("any_peer", "unreliable")
func rpc_broadcast_state(pos: Vector3, rot_y: float, mounted: bool, hp: int, level: int) -> void:
	var sender := multiplayer.get_remote_sender_id()
	if sender == 0:
		sender = multiplayer.get_unique_id()
	remote_states[sender] = {"pos": pos, "rot_y": rot_y, "mounted": mounted, "hp": hp, "level": level}
	
	# Server relays this player's position to all other connected peers!
	if multiplayer.is_server():
		for p_id in multiplayer.get_peers():
			if p_id != sender:
				rpc_relay_state.rpc_id(p_id, sender, pos, rot_y, mounted, hp, level)

@rpc("authority", "unreliable")
func rpc_relay_state(peer_id: int, pos: Vector3, rot_y: float, mounted: bool, hp: int, level: int) -> void:
	remote_states[peer_id] = {"pos": pos, "rot_y": rot_y, "mounted": mounted, "hp": hp, "level": level}

## Player spell broadcast & server relay
@rpc("any_peer", "reliable")
func rpc_broadcast_spell(spell_id: String, from_pos: Vector3, dir: Vector3) -> void:
	var sender := multiplayer.get_remote_sender_id()
	emit_signal("remote_spell_cast", sender, spell_id, from_pos, dir)
	if multiplayer.is_server():
		for p_id in multiplayer.get_peers():
			if p_id != sender:
				rpc_relay_spell.rpc_id(p_id, sender, spell_id, from_pos, dir)

@rpc("authority", "reliable")
func rpc_relay_spell(caster_id: int, spell_id: String, from_pos: Vector3, dir: Vector3) -> void:
	emit_signal("remote_spell_cast", caster_id, spell_id, from_pos, dir)

func broadcast_spell(spell_id: String, from_pos: Vector3, dir: Vector3) -> void:
	if multiplayer.has_multiplayer_peer() and is_connected_to_game and not is_server_only_offline():
		rpc_broadcast_spell.rpc(spell_id, from_pos, dir)

func is_server_only_offline() -> bool:
	return not multiplayer.has_multiplayer_peer()

@rpc("any_peer", "reliable")
func _register_my_info(info: Dictionary) -> void:
	var sender_id := multiplayer.get_remote_sender_id()
	connected_players[sender_id] = info
	print("[Server] Registered player %d: %s [%s]" % [sender_id, info.get("name", "Wizard"), info.get("house", "Gryffindor")])
	emit_signal("player_connected_signal", sender_id, info)
	if multiplayer.is_server():
		_sync_player_info.rpc(sender_id, info)

@rpc("authority", "reliable")
func _sync_player_info(id: int, info: Dictionary) -> void:
	connected_players[id] = info
	emit_signal("player_connected_signal", id, info)

## Chat message replication
@rpc("any_peer", "call_local", "reliable")
func rpc_send_chat(sender_name: String, sender_house: String, message: String) -> void:
	emit_signal("chat_message_received", sender_name, sender_house, message)

func send_chat(message: String) -> void:
	if message.strip_edges().is_empty():
		return
	if multiplayer.has_multiplayer_peer() and is_connected_to_game:
		rpc_send_chat.rpc(local_player_name, local_player_house, message)
	else:
		emit_signal("chat_message_received", local_player_name, local_player_house, message)
