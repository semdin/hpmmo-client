extends RefCounted
class_name TestGround

## Test placements on the grounds. Most suites were written against the old
## valley, whose courtyard was at the origin with the ground at y = 0. They keep
## their courtyard-relative coordinates through this helper: x stays, z is moved
## onto the new courtyard (old z = 5 is the paved south half of the new one,
## 25 m from the fountain, clear of its benches) and y becomes height above the
## real terrain.

const OLD_ORIGIN_Z := 5.0
const NEW_ORIGIN := Vector2(0.0, 90.0)


static func at(x: float, y: float, z: float) -> Vector3:
	var nx := NEW_ORIGIN.x + x
	var nz := NEW_ORIGIN.y + (z - OLD_ORIGIN_Z)
	var h := GroundsTerrain.height_at(nx, nz)
	return Vector3(nx, (0.0 if is_nan(h) else h) + y, nz)
