shader_type spatial;
// The grounds' far tree band (GroundsImpostors): every tree past its LOD1, as
// the cooked impostor card (two crossed quads, a unit mesh scaled per
// instance), all eight variants in one MultiMesh per 256 m tile.
//
// The look is the cooked `<variant>_impostor` StandardMaterial3D's
// (cook_vegetation.gd: alpha scissor 0.45 with alpha-to-coverage, both sides,
// wrap diffuse, backlight, normal map at 0.6), with the variant's texture as a
// slice of one array and its tint from a uniform.
//
// Range: Terrain3D draws a tree's LOD0/LOD1 from one multimesh per 32 m cell
// and Godot measures that multimesh's visibility range from its AABB centre,
// so a tree hands over by its cell, not by its own position. INSTANCE_CUSTOM
// carries that centre (xyz) and the variant (w); the band fades in exactly
// where the cell's LOD1 starts to fade out (Godot's FADE_SELF smoothstep over
// 2 x the Terrain3D fade margin) and out at the far range. Outside it a card
// collapses to a point.

render_mode blend_mix, depth_draw_opaque, cull_disabled, diffuse_lambert_wrap, specular_schlick_ggx, alpha_to_coverage;

const int MAX_VARIANTS = 16;

uniform sampler2DArray albedo_array : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2DArray normal_array : hint_normal, filter_linear_mipmap_anisotropic, repeat_disable;
// Linear colours (GroundsImpostors converts the catalogue's sRGB tints).
uniform vec3 tints[MAX_VARIANTS];
// Per variant: x = the near range (where Terrain3D's LOD1 ends), y = the far range.
uniform vec2 ranges[MAX_VARIANTS];
uniform float fade_margin = 4.0;
uniform vec3 backlight_color = vec3(0.04, 0.06, 0.01);

varying flat float variant;
varying flat float fade;

void vertex() {
	int v = int(INSTANCE_CUSTOM.w + 0.5);
	variant = float(v);
	vec2 r = ranges[v];
	float m2 = 2.0 * fade_margin;
	float d = distance(CAMERA_POSITION_WORLD, INSTANCE_CUSTOM.xyz);
	float fade_in = smoothstep(0.0, 1.0, (d - (r.x - m2)) / m2);
	float fade_out = smoothstep(0.0, 1.0, 1.0 - (d - r.y) / m2);
	fade = min(fade_in, fade_out);
	if (fade <= 0.0) {
		VERTEX = vec3(0.0);
	}
}

void fragment() {
	vec3 uvw = vec3(UV, variant);
	vec4 albedo_tex = texture(albedo_array, uvw);
	ALBEDO = tints[int(variant)] * albedo_tex.rgb;
	METALLIC = 0.0;
	SPECULAR = 0.25;
	ROUGHNESS = 0.85;
	NORMAL_MAP = texture(normal_array, uvw).rgb;
	NORMAL_MAP_DEPTH = 0.6;
	// Fading thins the card from its sparse edges inward (alpha below the
	// scissor goes first) instead of a screen-door dither.
	ALPHA = albedo_tex.a * fade;
	ALPHA_SCISSOR_THRESHOLD = 0.45;
	ALPHA_ANTIALIASING_EDGE = 0.3;
	ALPHA_TEXTURE_COORDINATE = UV * vec2(textureSize(albedo_array, 0).xy);
	BACKLIGHT = backlight_color;
}
