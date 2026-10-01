extends StaticBody3D

const MaterialKitScript = preload("res://scripts/assets/material_kit.gd")

## Quest NPC — robed professor / shopkeeper with nameplate, idle bob,
## click-to-talk (E or left-click), dialogue panel, and ! marker.

var npc_name: String = "Professor Fig"
var dialogue: Array = ["Welcome to Hogwarts, young wizard."]
var shop_items: Array = []
var _marker: MeshInstance3D = null
var _t: float = 0.0
var _rig: Node3D = null

func setup(p_name: String, p_dialogue: Array, robe_color: Color) -> void:
	npc_name = p_name
	dialogue = p_dialogue
	_build(robe_color)
	_update_label()

func _build(robe_color: Color) -> void:
	add_to_group("npcs")
	add_to_group("targetable")
	collision_layer = 2
	collision_mask = 1
	var col := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.45
	cap.height = 1.8
	col.shape = cap
	col.position.y = 0.9
	add_child(col)

	_rig = Node3D.new()
	add_child(_rig)
	var robe_mat := 	MaterialKitScript.robe_material(robe_color)
	var skin_mat := 	MaterialKitScript.skin_material()
	var robe := MeshInstance3D.new()
	var rm := CylinderMesh.new()
	rm.top_radius = 0.32
	rm.bottom_radius = 0.6
	rm.height = 1.4
	rm.material = robe_mat
	robe.mesh = rm
	robe.position.y = 0.7
	_rig.add_child(robe)
	var head := MeshInstance3D.new()
	var hm := SphereMesh.new()
	hm.radius = 0.21
	hm.height = 0.42
	hm.material = skin_mat
	head.mesh = hm
	head.position.y = 1.75
	_rig.add_child(head)
	# pointed hat for professors
	var hat := MeshInstance3D.new()
	var cm := CylinderMesh.new()
	cm.top_radius = 0.03
	cm.bottom_radius = 0.28
	cm.height = 0.55
	var dm := StandardMaterial3D.new()
	dm.albedo_color = robe_color.darkened(0.5)
	cm.material = dm
	hat.mesh = cm
	hat.position.y = 2.2
	_rig.add_child(hat)

	var label := Label3D.new()
	label.name = "NpcLabel"
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.font_size = 36
	label.outline_size = 8
	label.outline_modulate = Color(0, 0, 0)
	label.position = Vector3(0, 2.7, 0)
	add_child(label)

	# golden ! quest marker
	_marker = MeshInstance3D.new()
	var sm := SphereMesh.new()
	sm.radius = 0.12
	sm.height = 0.24
	var gm := 	MaterialKitScript.gold_material()
	sm.material = gm
	_marker.mesh = sm
	_marker.position = Vector3(0, 3.1, 0)
	add_child(_marker)
	var ml := OmniLight3D.new()
	ml.light_color = Color(1.0, 0.85, 0.3)
	ml.light_energy = 0.8
	ml.omni_range = 5.0
	ml.position = Vector3(0, 3.1, 0)
	add_child(ml)

func _update_label() -> void:
	var label := get_node_or_null("NpcLabel") as Label3D
	if label:
		label.text = "%s\n< click to talk >" % npc_name
		label.modulate = Color(1.0, 0.9, 0.5)

func _process(delta: float) -> void:
	_t += delta
	if _rig:
		_rig.position.y = sin(_t * 2.0) * 0.03
	if _marker:
		_marker.position.y = 3.1 + sin(_t * 3.0) * 0.12
		_marker.rotation.y += delta * 2.0

func talk(player: Node3D) -> Array:
	var qm := get_node_or_null("/root/QuestManager")
	if qm and qm.has_method("add_talk"):
		qm.add_talk(npc_name)
	return dialogue

func take_damage(_amount: int, _spell: String, _attacker: Node3D) -> void:
	pass # NPCs are peaceful
