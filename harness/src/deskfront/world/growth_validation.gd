extends RefCounted
## Stateless validation helpers shared by the bounded world-growth lifecycle.

static func valid_count(value, minimum: int, maximum: int) -> bool:
	return (value is int or value is float) and is_finite(float(value)) and float(value) == floorf(float(value)) and value >= minimum and value <= maximum
