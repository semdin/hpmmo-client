extends Node

## Layout probe: the UI counterpart of the capture harnesses.
##
## The HUD, the runtime MMORPG overlay and the map controller's status layer are
## three separate node trees that draw one screen between them, so nothing in any
## single file can prove they do not land on top of each other. This walks all
## three, prints every visible text-bearing Control's rect, and reports every pair
## whose rects intersect.
##
##   godot --path client res://scenes/test/ui_layout_probe.tscn
##
## Exits non-zero when a collision is found, so it can gate a check script. It
## reads `OVERLAP COUNT 0` at 1280x720; the interface regression independently
## asserts that every panel in `hud.layout_report()` stays inside the canvas when
## the UI is scaled up.

@onready var world = $GameWorld

var _entries: Array = []


func _ready() -> void:
	await get_tree().create_timer(2.0).timeout
	var player = world.local_player
	# The same staging the capture harnesses use, so the probe measures the layout
	# the screenshots show.
	player.global_position = Vector3(0, 0.15, -30)
	player.camera_rot_y = 0
	await get_tree().create_timer(1.0).timeout

	print("UI LAYOUT PROBE - canvas %s" % get_viewport().get_visible_rect().size)
	_collect(world.get_node("CanvasLayer"))
	if world.overlay != null:
		_collect(world.overlay)
	var map_status := world.get_node_or_null("MapStatusUI")
	if map_status != null:
		_collect(map_status)
	for entry in _entries:
		print("BOX | %-64s | %s | %s" % [entry["path"], entry["rect"], entry["text"]])

	var overlaps := _overlaps()
	print("--- OVERLAPS ---")
	for line in overlaps:
		print(line)
	print("UI LAYOUT RESULT: %d labelled controls, %d overlaps" % [_entries.size(), overlaps.size()])
	get_tree().quit(1 if not overlaps.is_empty() else 0)


## Every visible text-bearing Control under `root`. Hidden controls are skipped: a
## panel that is not on screen cannot collide with one that is.
func _collect(root: Node) -> void:
	for node in _walk(root):
		var control := node as Control
		if control == null or not control.is_visible_in_tree():
			continue
		var text := ""
		if node is Label or node is Button or node is RichTextLabel or node is LineEdit:
			text = String(node.get("text")).replace("\n", " / ")
		if text == "":
			continue
		_entries.append({
			"path": String(control.get_path()),
			"rect": Rect2(control.global_position, control.size),
			"text": text.substr(0, 34),
		})


## Pairs of labelled controls whose rects share more than a pixel. A label nested
## inside another is skipped: a caption inside its own panel is not a collision.
func _overlaps() -> Array:
	var out: Array = []
	for i in range(_entries.size()):
		for j in range(i + 1, _entries.size()):
			var a: Dictionary = _entries[i]
			var b: Dictionary = _entries[j]
			var a_path := String(a["path"])
			var b_path := String(b["path"])
			if a_path.begins_with(b_path) or b_path.begins_with(a_path):
				continue
			var inter: Rect2 = (a["rect"] as Rect2).intersection(b["rect"] as Rect2)
			if inter.size.x > 1.0 and inter.size.y > 1.0:
				out.append("OVERLAP | %s %s  <->  %s %s | %s" % [a_path, a["rect"], b_path, b["rect"], inter])
	return out


func _walk(node: Node) -> Array:
	var out: Array = [node]
	for child in node.get_children():
		out.append_array(_walk(child))
	return out
