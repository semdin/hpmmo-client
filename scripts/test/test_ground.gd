extends RefCounted
class_name TestGround

## Where the capture and preview tools stand, and who they play.
##
## Placements: the tools were written against the old valley, whose courtyard
## was at the origin with the ground at y = 0. `at` keeps those courtyard-
## relative coordinates: x stays, z is moved onto the new courtyard (old z = 5 is
## the paved south half of the new one, 25 m from the fountain, clear of its
## benches) and y becomes height above the real terrain. Hand-picked absolute
## spots go stale whenever the map moves - use `at`, `pack_spot` or a map's
## authored spawn (`HPMaps.spawn_point`) instead.
##
## Character: a tool that boots `game_world.tscn` must call
## `use_test_character()` from `_enter_tree` (before the world's `_ready`), or
## the world builds a fresh level-1 wizard - and the first-spell pick covers the
## middle of every shot.

const OLD_ORIGIN_Z := 5.0
const NEW_ORIGIN := Vector2(0.0, 90.0)


static func at(x: float, y: float, z: float) -> Vector3:
	var nx := NEW_ORIGIN.x + x
	var nz := NEW_ORIGIN.y + (z - OLD_ORIGIN_Z)
	var h := GroundsTerrain.height_at(nx, nz)
	return Vector3(nx, (0.0 if is_nan(h) else h) + y, nz)


## Play the capture as a geared `--test-char` wizard (all spells mastered, the
## quests below its level done), saved apart from the real solo character.
static func use_test_character(preset: String = "trial") -> void:
	DatabaseManager.offline_save_path = TestCharacter.SAVE_PATH
	var sheet: Dictionary = TestCharacter.build(preset)
	NetworkManager.local_character_data = sheet
	NetworkManager.local_player_name = String(sheet.get("name", "Tester"))
	NetworkManager.local_player_house = String(sheet.get("house", "Gryffindor"))


## Open ground in a creature pack's authored area (spawn_tables.json `area`,
## the one nearest the courtyard, outside every safe zone), on the terrain: a
## fight shot's stage.
static func pack_spot() -> Vector3:
	var best := Vector3.INF
	var courtyard := Vector2(NEW_ORIGIN.x, NEW_ORIGIN.y)
	for entry in HPRules.encounter_list():
		var area: Array = (entry as Dictionary).get("area", [])
		if area.size() < 2 or bool((entry as Dictionary).get("boss", false)):
			continue
		var h := GroundsTerrain.height_at(float(area[0]), float(area[1]))
		if is_nan(h):
			continue
		var p := Vector3(float(area[0]), h + 0.15, float(area[1]))
		if HPRules.is_protected_point(p):
			continue
		if not best.is_finite() or Vector2(p.x, p.z).distance_to(courtyard) < Vector2(best.x, best.z).distance_to(courtyard):
			best = p
	return best if best.is_finite() else at(0, 0.15, 5)
