extends Node3D

## Client-only preview of the Grand Staircase's moving flights (blockout F1).
##
## Reads the `moving_stairs` block of assets/castle/castle_layout.json (written by
## art/castle/scripts/make_layout.py, clash-checked by stair_solver.py). Every
## storey has one 30 m flight that swings 90 deg about the tower axis between two
## docks. Adjacent storeys never move at the same time - that is the condition the
## solver checked, so the schedule below keeps it:
##   even storeys swing during [0, SWING) and [HALF, HALF + SWING) of the cycle,
##   odd storeys during the same windows shifted by a quarter cycle.
## A gate closes every tongue whose flight is not docked against it.
##
## This is a preview, not the authority: the server-side version replaces the
## single-platform HPStaircase in F1b (docs/castle-interior.md).

const CYCLE := 32.0
const SWING := 7.0
const DECK_T := 0.4
const RAIL_H := 1.1
const STEP_H := 0.2

var map_y := 200.0
var paused := false
var time := 0.0

var _spec: Dictionary = {}
var _flights: Array = []          # [{body, storey, offset, docks, yaw}]
var _gates: Array = []            # [{flight, dock, body}]
var _mat_deck: Material
var _mat_step: Material
var _mat_rail: Material
var _mat_gate: Material


func setup(spec: Dictionary, level_y: float, materials: Dictionary) -> void:
	_spec = spec
	map_y = level_y
	_mat_deck = materials.get("deck")
	_mat_step = materials.get("step")
	_mat_rail = materials.get("rail")
	_mat_gate = materials.get("gate")
	for f in spec.get("flights", []):
		_flights.append(_build_flight(f))
	for i in _flights.size():
		var f: Dictionary = _flights[i]
		for dock in f["docks"]:
			for end in [-1, 1]:
				var level := int(f["storey"]) + (1 if end > 0 else 0)
				if level == 0:
					continue  # the well floor: nothing to fall from
				_gates.append({"flight": i, "dock": float(dock), "body": _build_gate(f, float(dock), end, level)})
	_apply(0.0)


## Yaw of storey `k` at cycle time t, plus whether it is docked (and where).
func pose(k: int, t: float) -> Dictionary:
	var f: Dictionary = _flights[k]
	var a0 := float(f["docks"][0])
	var a1 := float(f["docks"][1])
	var shift := 0.0 if k % 2 == 0 else CYCLE * 0.25
	var u := fposmod(t - shift, CYCLE)
	var half := CYCLE * 0.5
	if u < SWING:
		return {"yaw": lerpf(a0, a1, smoothstep(0.0, 1.0, u / SWING)), "docked": -1.0}
	if u < half:
		return {"yaw": a1, "docked": a1}
	if u < half + SWING:
		return {"yaw": lerpf(a1, a0, smoothstep(0.0, 1.0, (u - half) / SWING)), "docked": -1.0}
	return {"yaw": a0, "docked": a0}


## Freeze every flight at one of its docks (0 or 1) - used by the walk checks.
func dock_all(which: int) -> void:
	paused = true
	for k in _flights.size():
		var f: Dictionary = _flights[k]
		_place(k, float(f["docks"][which]), float(f["docks"][which]))


func flight_count() -> int:
	return _flights.size()


## Bottom and top of storey k's deck centre line at a yaw, in map-local coords.
func flight_ends(k: int, yaw: float) -> Array:
	var f: Dictionary = _flights[k]
	var axis: Array = _spec["axis"]
	var half := float(_spec["run"]) * 0.5
	var d := float(f["offset"])
	var u := Vector3(sin(deg_to_rad(yaw)), 0, -cos(deg_to_rad(yaw)))
	var l := Vector3(-u.z, 0, u.x)
	var c := Vector3(float(axis[0]), 0, float(axis[1])) + l * d
	var y0 := float(f["storey"]) * float(_spec["rise"])
	return [c - u * half + Vector3(0, y0, 0), c + u * half + Vector3(0, y0 + float(_spec["rise"]), 0)]


func _physics_process(delta: float) -> void:
	if paused:
		return
	time += delta
	_apply(time)


func _apply(t: float) -> void:
	for k in _flights.size():
		var p := pose(k, t)
		_place(k, float(p["yaw"]), float(p["docked"]))


func _place(k: int, yaw: float, docked: float) -> void:
	var f: Dictionary = _flights[k]
	var body: AnimatableBody3D = f["body"]
	body.global_transform = Transform3D(Basis(Vector3.UP, -deg_to_rad(yaw)), body.global_position)
	f["docked"] = docked
	for g in _gates:
		if int(g["flight"]) == k:
			var open: bool = absf(float(g["dock"]) - docked) < 0.01
			var gate: StaticBody3D = g["body"]
			gate.visible = not open
			(gate.get_child(0) as CollisionShape3D).disabled = open


func _build_flight(f: Dictionary) -> Dictionary:
	var axis: Array = _spec["axis"]
	var run := float(_spec["run"])
	var rise := float(_spec["rise"])
	var w := float(_spec["width"])
	var d := float(f["offset"])
	var body := AnimatableBody3D.new()
	body.name = "MovingStair%d" % int(f["storey"])
	# Moved from _physics_process (and from setup/dock_all); sync_to_physics would
	# discard a transform set outside a physics step and leave the deck at the origin.
	body.sync_to_physics = false
	body.collision_layer = 1
	body.collision_mask = 0
	add_child(body)
	body.global_position = Vector3(float(axis[0]), map_y + float(f["storey"]) * rise, float(axis[1]))
	# Local frame: the deck climbs toward -Z, its centre line at x = d.
	var angle := atan2(rise, run)
	var length := sqrt(run * run + rise * rise)
	var tilt := Basis(Vector3.RIGHT, angle)
	var normal := tilt * Vector3.UP
	var mid := Vector3(d, rise * 0.5, 0)
	_shape(body, Vector3(w, DECK_T, length), mid - normal * (DECK_T * 0.5), tilt)
	_mesh(body, Vector3(w, DECK_T, length), mid - normal * (DECK_T * 0.5), tilt, _mat_deck)
	var steps := int(round(rise / STEP_H))
	var tread := run / steps
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	var box := BoxMesh.new()
	box.size = Vector3(w - 0.1, STEP_H, tread)
	box.material = _mat_step
	mm.mesh = box
	mm.instance_count = steps
	for i in steps:
		mm.set_instance_transform(i, Transform3D(Basis(), Vector3(d, (i + 0.5) * STEP_H, run * 0.5 - (i + 0.5) * tread)))
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	body.add_child(mmi)
	for side in [-1.0, 1.0]:
		var pos := mid + normal * (RAIL_H * 0.5) + Vector3(side * (w * 0.5 - 0.1), 0, 0)
		_shape(body, Vector3(0.2, RAIL_H, length), pos, tilt)
		_mesh(body, Vector3(0.2, RAIL_H, length), pos, tilt, _mat_rail)
	return {"body": body, "storey": int(f["storey"]), "offset": d, "docks": f["docks"], "docked": -1.0}


## A gate across the tip of the tongue at one end of one dock.
func _build_gate(f: Dictionary, dock: float, end: int, level: int) -> StaticBody3D:
	var axis: Array = _spec["axis"]
	var half := float(_spec["run"]) * 0.5
	var w := float(_spec["width"])
	var u := Vector3(sin(deg_to_rad(dock)), 0, -cos(deg_to_rad(dock)))
	var l := Vector3(-u.z, 0, u.x)
	var tip := Vector3(float(axis[0]), 0, float(axis[1])) + l * float(f["offset"]) + u * (half + 0.15) * end
	var gate := StaticBody3D.new()
	gate.collision_layer = 1
	add_child(gate)
	gate.global_transform = Transform3D(Basis(Vector3.UP, -deg_to_rad(dock)),
		Vector3(tip.x, map_y + level * float(_spec["rise"]) + 0.6, tip.z))
	var cs := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(w, 1.2, 0.3)
	cs.shape = shape
	gate.add_child(cs)
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = shape.size
	bm.material = _mat_gate
	mi.mesh = bm
	gate.add_child(mi)
	return gate


func _shape(parent: Node3D, size: Vector3, pos: Vector3, rot: Basis) -> void:
	var cs := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	cs.shape = shape
	cs.transform = Transform3D(rot, pos)
	parent.add_child(cs)


func _mesh(parent: Node3D, size: Vector3, pos: Vector3, rot: Basis, mat: Material) -> void:
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = size
	bm.material = mat
	mi.mesh = bm
	mi.transform = Transform3D(rot, pos)
	parent.add_child(mi)
