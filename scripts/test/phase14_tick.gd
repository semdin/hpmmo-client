extends Node

## Phase 14 server tick headroom (plan.md Phase 14: "Select a server tick rate
## from measurement... Track p95/p99 tick time and leave scheduling headroom
## under the chosen budget").
##
## This is the production world-server boot (`world_server.gd`'s exact steps:
## DEDICATED role, host the ENet transport, build the real world scene, bridge
## authority events) with ONE addition: the simulation loop is driven here
## instead of by the authority's own `_physics_process`, so every step's
## wall-clock cost can be measured around the exact function the production
## loop calls (`SimAuthority._step`).
##
## The step is invoked on the same 50 ms cadence the production accumulator
## uses, so the measurement is of the production work at the production rate.
##
## Every REPORT_INTERVAL seconds it prints one JSON line:
##   TICK {"epoch": ..., "t": ..., "players": ..., "entities": ...,
##         "steps": ..., "p50_us": ..., "p95_us": ..., "p99_us": ..., "max_us": ...}
##
## Usage:
##   godot --headless --path client res://scenes/test/phase14_tick.tscn -- \
##     --port=7810 --out=tick.jsonl --seconds=420

const HPProtocol = preload("res://addons/hpmmo_sim/protocol.gd")

const REPORT_INTERVAL := 5.0

var port := 7810
var out_path := ""
var duration := 420.0
var world: Node3D = null
var _samples: Array = []
var _report_t := 0.0
var _t := 0.0
var _accumulator := 0.0
var _steps := 0
var _file: FileAccess = null
var _boot_epoch := 0

func _ready() -> void:
	_parse_args()
	if out_path != "":
		_file = FileAccess.open(out_path, FileAccess.WRITE)
	NetworkManager.is_dedicated_server = true
	NetworkManager.is_server = true
	NetworkManager.is_connected_to_game = true
	SimAuthority.configure(SimAuthority.Role.DEDICATED, HPRules.debug_seed())
	var error := SimNet.host(port)
	if error != OK:
		print("TICK ERROR: cannot host UDP %d (%d)" % [port, error])
		get_tree().quit(1)
		return
	SimNet.bridge_authority()
	world = load("res://scenes/world/game_world.tscn").instantiate()
	add_child(world)
	# The loop is driven here: the authority's own physics step is switched off so
	# there is exactly one driver and every step is timed.
	SimAuthority.set_physics_process(false)
	_boot_epoch = int(Time.get_unix_time_from_system())
	print("TICK READY port=%d tick_hz=%d protocol=%d" % [port, HPProtocol.SIM_HZ, HPProtocol.PROTOCOL_VERSION])

func _parse_args() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--port="):
			port = int(arg.substr(7))
		elif arg.begins_with("--out="):
			out_path = arg.substr(6)
		elif arg.begins_with("--seconds="):
			duration = float(arg.substr(10))

## The production cadence: accumulate real frame time and step while a full
## SIM_DT is available (the authority allows at most five catch-up steps; the
## same cap is kept here so a stall cannot turn into a burst).
func _physics_process(delta: float) -> void:
	_t += delta
	_accumulator += delta
	var steps := 0
	while _accumulator >= HPProtocol.SIM_DT and steps < 5:
		_accumulator -= HPProtocol.SIM_DT
		var start := Time.get_ticks_usec()
		SimAuthority.call("_step")
		var cost := int(Time.get_ticks_usec() - start)
		_samples.append(cost)
		_steps += 1
		steps += 1
	_report_t += delta
	if _report_t >= REPORT_INTERVAL:
		_report_t = 0.0
		_report()
	if _t >= duration and _steps > 0:
		_report()
		_finish()

func _report() -> void:
	if _samples.is_empty():
		return
	var times: Array = _samples.duplicate()
	times.sort()
	var count := times.size()
	var line := {
		"epoch": int(Time.get_unix_time_from_system()),
		"t": snappedf(_t, 0.1),
		"players": SimAuthority.players_by_peer.size(),
		"entities": SimAuthority.entities.size(),
		"steps": count,
		"p50_us": _percentile(times, 0.50),
		"p95_us": _percentile(times, 0.95),
		"p99_us": _percentile(times, 0.99),
		"max_us": int(times[-1]),
		"budget_us": int(HPProtocol.SIM_DT * 1000000.0),
	}
	_samples.clear()
	print("TICK " + JSON.stringify(line))
	if _file != null:
		_file.store_line(JSON.stringify(line))
		_file.flush()

func _percentile(sorted_times: Array, fraction: float) -> int:
	if sorted_times.is_empty():
		return 0
	var index := int(clampf(floorf(fraction * float(sorted_times.size())), 0.0, float(sorted_times.size() - 1)))
	return int(sorted_times[index])

func _finish() -> void:
	if _file != null:
		_file.close()
	print("TICK DONE steps=%d seconds=%.1f" % [_steps, _t])
	SimNet.leave()
	get_tree().quit(0)
