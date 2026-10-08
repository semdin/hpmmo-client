extends RefCounted
class_name HeroAppearance

## The hero body, and the one house-tint rule that dresses it.
##
## The in-game player and the character-select preview both spawn `MODEL` and
## tint it through here, so the wizard a player picks on the podium is the wizard
## they then play. Before this helper existed the preview loaded a different
## KayKit model (`wizard.glb`) and tinted a `Mage_Cape` node that only that model
## has, so the podium showed a character nobody could ever play.
##
## The tint is material-only and keyed on material name, so it survives a
## re-export of the GLB: `Hero_Trim` takes the house primary, `Hero_Robe` a
## darkened house primary. Nothing is duplicated onto the rig.

const MODEL := preload("res://assets/models/characters/hero_wizard.glb")

const BODY_SURFACE := "Hero_Body"
const MATERIAL_TRIM := "Hero_Trim"
const MATERIAL_ROBE := "Hero_Robe"

## A stationary hero's breathing clip, in preference order. The body carries
## `Idle`; the others are seat/loop fallbacks if the animation set changes.
const IDLE_CLIPS := ["Idle", "Cast_Idle_Loop", "Broom_Seated_Idle"]

## The clip an idle body should play, or "" when it carries none of them.
static func idle_clip(player: AnimationPlayer) -> String:
	if player == null:
		return ""
	for clip in IDLE_CLIPS:
		if player.has_animation(clip):
			return clip
	return ""


## Spawn the hero body under `anchor` and return it, already tinted with `primary`
## and (when the body carries one) playing its idle clip.
##
## `anchor` is any Node3D: the player's `Visuals`, or the podium's `ModelAnchor`.
## The caller resolves `primary` from the house, so this helper stays free of
## game data and is just as usable from a test.
static func spawn(anchor: Node3D, primary: Color) -> Node3D:
	var body := MODEL.instantiate() as Node3D
	if body == null:
		return null
	anchor.add_child(body)
	body.position = Vector3.ZERO
	body.rotation = Vector3.ZERO
	apply_house_tint(body, primary)
	var player := find_anim_player(body)
	var clip := idle_clip(player)
	if clip != "":
		player.play(clip)
	return body


## Tint the robe and trim surfaces of the `Hero_Body` mesh inside `visuals`.
##
## House variation is material-only, so this is the single definition of what a
## house looks like on the body. `visuals` may be the model root or any ancestor
## of it; the body node is found by name.
static func apply_house_tint(visuals: Node, primary: Color) -> void:
	if visuals == null:
		return
	var body := visuals.find_child(BODY_SURFACE, true, false)
	if not (body is MeshInstance3D):
		return
	var mesh_instance := body as MeshInstance3D
	var mesh: Mesh = mesh_instance.mesh
	if mesh == null:
		return
	for surface in range(mesh.get_surface_count()):
		var material := mesh.surface_get_material(surface)
		if not (material is StandardMaterial3D):
			continue
		var base := material as StandardMaterial3D
		match base.resource_name:
			MATERIAL_TRIM:
				var trim := base.duplicate() as StandardMaterial3D
				trim.albedo_color = primary
				trim.metallic = 0.35
				trim.roughness = 0.45
				mesh_instance.set_surface_override_material(surface, trim)
			MATERIAL_ROBE:
				var robe := base.duplicate() as StandardMaterial3D
				robe.albedo_color = primary.darkened(0.72)
				mesh_instance.set_surface_override_material(surface, robe)


## The body's animation player, wherever the importer put it.
static func find_anim_player(node: Node) -> AnimationPlayer:
	if node == null:
		return null
	var found := node.find_child("AnimationPlayer", true, false)
	if found is AnimationPlayer:
		return found as AnimationPlayer
	return null
