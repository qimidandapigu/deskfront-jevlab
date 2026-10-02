shader_type spatial;
render_mode cull_back;

uniform vec4 base_color : source_color = vec4(0.65, 0.25, 0.18, 1.0);
uniform vec3 bounds_min = vec3(0.0);
uniform vec3 bounds_size = vec3(1.0);
uniform vec3 scar_center = vec3(0.5);
uniform vec3 scar_radius = vec3(0.3);
uniform float burn_strength = 0.0;
uniform float wreck_strength = 0.0;
varying vec3 part_point;

void vertex() {
	// Normalize each imported part's own bounds so the mark stays on the part.
	part_point = (VERTEX - bounds_min) / bounds_size;
}

void fragment() {
	vec3 radius = scar_radius * (1.0 + wreck_strength * 0.12);
	float distance_to_hit = length((part_point - scar_center) / radius);
	float rough_edge = 0.075 * sin(part_point.x * 31.0 + part_point.z * 9.0)
		* cos(part_point.y * 27.0 - part_point.z * 13.0);
	float outline = distance_to_hit + rough_edge;
	float heat_stain = 1.0 - smoothstep(0.80, 1.22, outline);
	float soot = 1.0 - smoothstep(0.69, 0.87, outline);
	vec3 paint = base_color.rgb;
	vec3 scorched_paint = paint * vec3(0.40, 0.29, 0.24);
	vec3 carbon = vec3(0.035, 0.032, 0.029);
	paint = mix(paint, scorched_paint, heat_stain * burn_strength * 0.78);
	paint = mix(paint, carbon, soot * burn_strength);
	ALBEDO = paint;
	ROUGHNESS = mix(0.73, 0.93, soot * burn_strength);
}
