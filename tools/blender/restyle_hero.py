"""Tailor a pre-costume hero GLB, preserving its clips.
blender --background --python restyle_hero.py -- source.glb output.glb render_dir
Fresh build_hero.py builds also invoke hero_costume.dress.
"""
import bpy, sys, os
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hero_costume

source, output, renders = sys.argv[sys.argv.index('--')+1:]
renders=os.path.abspath(renders)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(source))
arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
body=next(o for o in bpy.data.objects if o.type=='MESH' and 'Hero_Body' in o.name)
arm.animation_data.action=None
for bone in arm.pose.bones:bone.matrix_basis.identity()
bpy.context.view_layer.update()
hero_costume.dress(arm,body)
for action in bpy.data.actions:action.use_fake_user=True
bpy.ops.export_scene.gltf(filepath=os.path.abspath(output),export_format='GLB',export_yup=True,
    export_animations=True,export_animation_mode='ACTIONS',export_apply=False)
print('[costume] Exported',output)

scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.samples=24
scene.cycles.use_denoising=True
scene.render.resolution_x=900
scene.render.resolution_y=1000
scene.render.resolution_percentage=100
scene.world=bpy.data.worlds.new('Studio World')
scene.world.color=(0.18,0.18,0.18)
scene.view_settings.view_transform='AgX'
idle=next((a for a in bpy.data.actions if a.name=='Idle'),None)
if idle:
    arm.animation_data.action=idle
    if idle.slots:arm.animation_data.action_slot=idle.slots[0]
scene.frame_set(8)
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.012))
plane=bpy.context.object
mat=bpy.data.materials.new('Studio');mat.diffuse_color=(.055,.071,.10,1);plane.data.materials.append(mat)
for name,loc,power,size,col in [('Key',(3,-4,5),450,4,(1,.87,.72)),('Fill',(-3,-2,2.8),260,3,(.70,.82,1)),('Rim',(1,3,4),600,3,(.85,.90,1))]:
    light=bpy.data.lights.new(name,'AREA');light.energy=power;light.shape='DISK';light.size=size;light.color=col
    obj=bpy.data.objects.new(name,light);scene.collection.objects.link(obj);obj.location=loc
    obj.rotation_euler=(Vector((0,0,1))-obj.location).to_track_quat('-Z','Y').to_euler()
data=bpy.data.cameras.new('Camera');cam=bpy.data.objects.new('Camera',data);scene.collection.objects.link(cam)
scene.camera=cam;data.type='ORTHO';data.ortho_scale=2.25
os.makedirs(renders,exist_ok=True)
for name,loc in [('front',(0,-4,1.55)),('three-quarter',(2.7,-4,1.8)),('back',(2.5,4,1.8))]:
    cam.location=loc;cam.rotation_euler=(Vector((0,-.03,.94))-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=os.path.join(renders,'wizard-'+name+'.png')
    bpy.ops.render.render(write_still=True)
