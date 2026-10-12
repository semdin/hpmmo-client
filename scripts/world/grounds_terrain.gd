extends Terrain3D
class_name GroundsTerrain

## The outdoor map's terrain (Terrain3D, 2 x 2 km, 1 m cells, lake surface y = 0).
##
## Source: art/map (layout.json -> heightfield.py / control.py) built into
## assets/terrain/grounds/ by tools/terrain/build_grounds.gd. See docs/grounds-map.md.
##
## Collision: the dedicated server simulates every player's body wherever it is,
## so it needs the whole heightfield as colliders (FULL_GAME). A client only needs
## the ground around its own camera (DYNAMIC_GAME, Terrain3D's default for games).
## Dynamic collision cannot work headless (there is no camera to follow), so
## headless runs (server, tests) always get FULL_GAME.

const GROUND_LAYER := 1
## Client dynamic-collision radius around the camera, in metres. The broom camera
## sits within ~12 m of the hero, so this covers the hero with a wide margin.
const CLIENT_COLLISION_RADIUS := 96

static var _active: GroundsTerrain


func _enter_tree() -> void:
	_active = self


func _exit_tree() -> void:
	if _active == self:
		_active = null


func _ready() -> void:
	collision.layer = GROUND_LAYER
	collision.mask = 0
	if DisplayServer.get_name() == "headless":
		collision.mode = Terrain3DCollision.FULL_GAME
		# Terrain3D follows a camera for mesh LOD and stops (with an error) when it
		# finds none. Headless nothing is drawn, so give it a fixed one.
		var anchor := Camera3D.new()
		anchor.name = "HeadlessAnchor"
		add_child(anchor)
		set_camera(anchor)
	else:
		collision.mode = Terrain3DCollision.DYNAMIC_GAME
		collision.radius = CLIENT_COLLISION_RADIUS


## The loaded grounds terrain, or null when the current map has none.
static func active() -> GroundsTerrain:
	return _active if is_instance_valid(_active) else null


## Ground height at (x, z), or NAN outside the terrain or with no terrain loaded.
static func height_at(x: float, z: float) -> float:
	var t := active()
	if t == null or t.data == null:
		return NAN
	return t.data.get_height(Vector3(x, 0.0, z))
