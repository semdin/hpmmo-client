extends Node

## Phase 10 performance route (plan.md Phase 10: "performance, measured not
## claimed"). Same fixed camera stops outdoor and indoor, same metrics printed
## each run, so the greybox run and the finished run are comparable numbers.
##
##   godot --path client res://scenes/test/phase10_perf.tscn --quit-after 3600
##
## Metrics per stop: draw calls, visible primitives (triangles = primitives),
## texture memory, video memory, and a transparent-overdraw index measured by
## rendering the viewport with the engine's overdraw debug mode and counting
## the fraction of non-black pixels. The overdraw index is relative, not
## physical: only the before/after delta is meaningful.

@onready var world = $GameWorld

var _camera: Camera3D
var _rows: Array = []

const STOPS := [
	# [label, is_interior, camera pos, target]
	["out-approach", false, Vector3(0, 3.4, -16), Vector3(0, 9.5, -70)],
	["out-courtyard", false, Vector3(13, 6.5, 27), Vector3(-2, 2, -12)],
	["out-terrain", false, Vector3(-30, 16, 30), Vector3(-70, 2, -24)],
	["in-great-hall", true, Vector3(-52, 203.4, 2), Vector3(-16, 204.5, -2)],
	["in-stair-hall", true, Vector3(8, 202.2, -16), Vector3(42, 205.0, -14)],
	["in-library", true, Vector3(-24, 207.6, -33), Vector3(-52, 208.2, -44)],
]

func _ready() -> void:
	await get_tree().create_timer(1.2).timeout
	world.get_node("CanvasLayer").hide()
	if world.overlay:
		world.overlay.hide()
	_camera = Camera3D.new()
	_camera.fov = 65
	world.add_child(_camera)
	_camera.current = true
	var interior: Node3D = null
	for stop in STOPS:
		var label := String(stop[0])
		var wants_interior: bool = stop[1]
		if wants_interior and interior == null:
			interior = load("res://scenes/world/castle_interior.tscn").instantiate()
			interior.name = "Phase10Interior"
			world.add_child(interior)
			await get_tree().create_timer(0.8).timeout
		if not wants_interior and interior != null:
			# Outdoor stops all come first; this is a guard, not a route.
			pass
		_camera.global_position = stop[2]
		_camera.look_at(stop[3])
		await get_tree().create_timer(0.5).timeout
		await _measure(label)
	_report()
	world.queue_free()
	await get_tree().process_frame
	get_tree().quit()

func _measure(label: String) -> void:
	var draw_calls: int = Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)
	var prims: int = Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)
	var tex_mem: float = Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)
	var vid_mem: float = Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)
	var fps: int = Engine.get_frames_per_second()
	# Transparent overdraw index: engine overdraw visualisation, then a
	# luminance count over the captured frame.
	var viewport := get_viewport()
	var restore: int = viewport.debug_draw
	viewport.debug_draw = Viewport.DEBUG_DRAW_OVERDRAW
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	viewport.debug_draw = restore
	var lit := 0
	var total := image.get_width() * image.get_height()
	var step := 4
	for y in range(0, image.get_height(), step):
		for x in range(0, image.get_width(), step):
			var c := image.get_pixel(x, y)
			if c.r + c.g + c.b > 0.05:
				lit += 1
	var sampled := (image.get_width() / step) * (image.get_height() / step)
	var overdraw_pct := 100.0 * float(lit) / float(maxi(1, sampled))
	_rows.append({
		"label": label, "draw_calls": draw_calls, "prims": prims,
		"tex_mib": tex_mem / 1048576.0, "vid_mib": vid_mem / 1048576.0,
		"overdraw_pct": overdraw_pct, "fps": fps, "pixels": total,
	})
	print("PERF %-16s draw_calls=%-6d prims=%-9d tex_mib=%-7.1f vid_mib=%-7.1f overdraw=%.1f%% fps=%d" % [
		label, draw_calls, prims, tex_mem / 1048576.0, vid_mem / 1048576.0, overdraw_pct, fps])

func _report() -> void:
	var dc := 0
	var pr := 0
	var ov := 0.0
	for row in _rows:
		dc += int(row["draw_calls"])
		pr += int(row["prims"])
		ov += float(row["overdraw_pct"])
	print("PERF RESULT stops=%d avg_draw_calls=%.1f avg_prims=%.1f avg_overdraw=%.2f%%" % [
		_rows.size(), float(dc) / maxf(1.0, float(_rows.size())),
		float(pr) / maxf(1.0, float(_rows.size())), ov / maxf(1.0, float(_rows.size()))])
