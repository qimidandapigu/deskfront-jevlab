extends RefCounted
## Pure projectile geometry shared by the combat presentation layer.
##
## This helper deliberately knows nothing about Game, Unit, Field or damage.
## It owns only deterministic spread and incoming-explosive warning geometry;
## combat_fx.gd remains responsible for collision queries and VFX/audio.

var rng: RandomNumberGenerator = RandomNumberGenerator.new()

const BASE_CONES: Dictionary = {
	"rifle": .075,
	"smg": .083,
	"pistol": .075,
	"rocket": .018,
	"cannon": .020,
	"at_cannon": .016,
	"mortar": .032,
	"grenade": .038,
}

func dispersed_endpoint(origin: Vector3, aim: Vector3, accuracy: float, pressure: float, weapon: String = "rifle") -> Vector3:
	var forward: Vector3 = (aim - origin).normalized()
	var right: Vector3 = forward.cross(Vector3.UP).normalized()
	if right.length_squared() < .01:
		right = Vector3.RIGHT
	var up: Vector3 = right.cross(forward).normalized()
	# 这是角度参数，accuracy 不是额外的命中概率；爆炸武器保持独立散射。
	var base: float = float(BASE_CONES.get(weapon, .012))
	var cone: float = (base + .055 * (1 - clampf(accuracy, 0, 1))) * (1 + clampf(pressure, 0, 1) * .8)
	var angle: float = rng.randf() * TAU
	var radius: float = sqrt(rng.randf()) * origin.distance_to(aim) * tan(cone)
	return aim + (right * cos(angle) + up * sin(angle)) * radius

func warning_estimate(target: Vector3, grid: float = .06) -> Vector2:
	return Vector2(snappedf(target.x, grid), snappedf(target.z, grid))

func warning_radius(splash: float) -> float:
	return splash + .06

func warning_remaining(duration: float, age: float) -> float:
	return duration - age

func warning_corridor_contains(unit_aim: Vector3, unit_pos: Vector2, current: Vector3, target: Vector3, radius: float) -> bool:
	var nearest: Vector3 = Geometry3D.get_closest_point_to_segment(unit_aim, current, target)
	return Vector2(nearest.x, nearest.z).distance_to(unit_pos) <= radius or warning_estimate(target).distance_to(unit_pos) <= radius
