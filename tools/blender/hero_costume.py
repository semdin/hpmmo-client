"""Wizard tailoring on the existing metric hero rig; no animation changes."""
import math
import bpy
import bmesh
from mathutils import Vector


def dress(arm, body):
    mats = {m.name: m for m in body.data.materials}

    def material(name, colour, roughness=0.85, metallic=0.0):
        mat = mats.get(name) or bpy.data.materials.new(name)
        mat.use_nodes = True
        mat.diffuse_color = (*colour, 1)
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*colour, 1)
        bsdf.inputs['Roughness'].default_value = roughness
        bsdf.inputs['Metallic'].default_value = metallic
        mat.roughness = roughness
        mat.metallic = metallic
        mats[name] = mat
        if mat.name not in body.data.materials:
            body.data.materials.append(mat)
        return list(body.data.materials).index(mat)

    robe = material('Hero_Robe', (0.028, 0.034, 0.049))
    dark = material('Hero_Dark', (0.019, 0.024, 0.034), 0.76)
    leather = material('Hero_Leather', (0.034, 0.022, 0.017), 0.48)
    trim = material('Hero_Trim', (0.32, 0.023, 0.038), 0.87)
    skin = material('Hero_Skin', (0.64, 0.40, 0.27), 0.82)
    hair = material('Hero_Hair', (0.065, 0.029, 0.015), 0.92)
    shirt = material('Hero_Shirt', (0.75, 0.71, 0.60), 0.95)
    gold = material('Hero_Brass', (0.46, 0.29, 0.09), 0.4, 0.62)
    vest = material('Hero_Waistcoat', (0.085, 0.105, 0.13), 0.96)

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.00001)
    # The hood and armour shoulders are separate shells in the source mesh.
    visited = set()
    remove = set()
    for seed in bm.verts:
        if seed in visited:
            continue
        stack, component = [seed], []
        visited.add(seed)
        while stack:
            v = stack.pop()
            component.append(v)
            for edge in v.link_edges:
                other = edge.other_vert(v)
                if other not in visited:
                    visited.add(other)
                    stack.append(other)
        faces = {f for v in component for f in v.link_faces}
        indices = {f.material_index for f in faces}
        lo = min(v.co.z for v in component)
        hi = max(v.co.z for v in component)
        if indices == {robe} and lo > 1.50 and hi > 1.85:
            remove.update(faces)
        if indices == {trim} and lo > 1.40 and hi < 1.60:
            remove.update(faces)
    for face in bm.faces:
        c = face.calc_center_median()
        # Keep the original face, hands, trousers and boots; replace the torso
        # and arm armour with tailored, continuously weighted cloth. The
        # waistcoat hem (z 0.94) covers the trouser top removed here.
        if 0.96 < c.z < 1.535 and abs(c.x) < 0.575:
            remove.add(face)
        elif c.z < 0.465 and face.material_index != dark:
            face.material_index = leather
        elif c.z < 1.10:
            face.material_index = dark
        elif c.z > 1.53 and face.material_index == list(body.data.materials).index(mats['Hero_Leather']):
            face.material_index = hair
        face.smooth = True
    bmesh.ops.delete(bm, geom=list(remove), context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    for v in bm.verts:
        if 0.34 < v.co.z < 1.04:
            side = 1 if v.co.x > 0 else -1
            taper = 0.65 + 0.35 * max(0, (v.co.z - 0.90) / 0.14)
            v.co.x = side * 0.097 + (v.co.x - side * 0.097) * taper
            v.co.y = -0.065 + (v.co.y + 0.065) * 0.76
    bm.to_mesh(body.data)
    bm.free()

    vertices, faces, face_mats, weights = [], [], [], []

    def vertex(co, groups):
        vertices.append(tuple(co))
        weights.append(groups)
        return len(vertices) - 1

    def face(indices, mat):
        faces.append(indices)
        face_mats.append(mat)

    def torso_weights(z):
        anchors = [(1.04, 'Hips'), (1.16, 'Abdomen'), (1.32, 'Torso'), (1.45, 'Chest')]
        for (a, first), (b, second) in zip(anchors, anchors[1:]):
            if z <= b:
                t = max(0, min(1, (z - a) / (b - a)))
                return {first: 1 - t, second: t}
        return {'Chest': 1.0}

    def shell(rows, mat, open_front=0, skirt=False):
        rings = []
        segments = 32
        for z, rx, ry, opening in rows:
            ring = []
            for j in range(segments + 1):
                angle = opening + (math.tau - opening * 2) * j / segments
                x, y = rx * math.sin(angle), -0.055 - ry * math.cos(angle)
                groups = torso_weights(z)
                if skirt and z <= 1.05:
                    # Split leg influence smoothly across the back seam.
                    leg = max(0, min(0.94, (1.05 - z) / 0.35))
                    left = max(0, min(1, (x + 0.07) / 0.14))
                    groups = {'Hips': 1-leg, 'UpperLeg.L': leg*left, 'UpperLeg.R': leg*(1-left)}
                    fold = math.cos(angle * 8) * 0.008 * max(0, (1.05-z)/0.6)
                    x += fold * math.sin(angle)
                    y -= fold * math.cos(angle)
                ring.append(vertex((x, y, z), groups))
            rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            for j in range(segments):
                face((a[j], a[j+1], b[j+1], b[j]), mat)
        # House-coloured narrow facing along the opening, sewn onto the cloth.
        if open_front:
            for edge in [0, segments]:
                band = []
                for ring in rings:
                    i = ring[edge]
                    v = Vector(vertices[i])
                    towards = Vector(vertices[ring[1 if edge == 0 else -2]]) - v
                    v += towards.normalized() * 0.012
                    v.y -= 0.002
                    band.append((vertex(Vector(vertices[i])+Vector((0,-0.002,0)),weights[i]), vertex(v,weights[i])))
                for a,b in zip(band,band[1:]):
                    face((a[0],a[1],b[1],b[0]),trim)
            # A second inset shell gives the open robe visible coloured lining.
            inner = []
            for ring in rings:
                out = []
                for i in ring:
                    v = Vector(vertices[i])
                    # A fixed inset (not a percentage) so leg-blended skirt
                    # quads cannot push the lining through the outer cloth.
                    radial = Vector((v.x, v.y + 0.055)).length
                    s = max(0.85, (radial - 0.013) / radial) if radial > 0 else 1
                    v.x *= s; v.y = -0.055+(v.y+0.055)*s
                    out.append(vertex(v, weights[i]))
                inner.append(out)
            for a,b in zip(inner,inner[1:]):
                for j in range(segments):
                    face((b[j],b[j+1],a[j+1],a[j]),trim)

    # Shirt/waistcoat, long robe, and a soft raised collar.
    # The waistcoat hem drops past the cut edge of the old tunic and follows the
    # thighs a little, so no seam shows between waistcoat and trousers.
    shell([(.94,.168,.12,0),(1.0,.162,.116,0),(1.055,.145,.104,0),(1.18,.126,.10,0),(1.34,.18,.117,0),(1.45,.155,.105,0),(1.515,.060,.064,0)],vest,0,True)
    shell([(1.04,.166,.125,.49),(1.17,.148,.121,.54),(1.34,.20,.138,.48),(1.445,.177,.129,.44),(1.50,.073,.08,.28)],robe,1)
    shell([(1.05,.165,.125,.49),(.92,.198,.146,.50),(.75,.235,.166,.52),(.58,.272,.186,.55),(.44,.285,.19,.58)],robe,1,True)
    shell([(1.49,.065,.072,.25),(1.55,.062,.067,.36)],robe,1)

    def patch(points, mat, group):
        ids = [vertex(p,torso_weights(p[2]) if group is None else {group:1.0}) for p in points]
        face(ids,mat)

    # Ivory shirt front, turned-down collar and a narrow house tie.
    patch([(-.051,-.175,1.475),(.051,-.175,1.475),(.039,-.180,1.355),(-.039,-.180,1.355)],shirt,None)
    for side in [-1,1]:
        patch([(side*.008,-.185,1.493),(side*.060,-.176,1.495),(side*.058,-.192,1.427),(side*.018,-.198,1.445)],shirt,'Chest')
    patch([(-.014,-.200,1.463),(.014,-.200,1.463),(.022,-.190,1.322),(0,-.192,1.296),(-.022,-.190,1.322)],trim,None)

    def tube(centres,radii,groups,mat):
        rings=[]
        for c,r,w in zip(centres,radii,groups):
            ring=[]
            for i in range(16):
                a=math.tau*i/16
                ring.append(vertex(Vector(c)+Vector((0,math.cos(a)*r,math.sin(a)*r)),w))
            rings.append(ring)
        for a,b in zip(rings,rings[1:]):
            for i in range(16):face((a[i],a[(i+1)%16],b[(i+1)%16],b[i]),mat)

    for side,suffix in [(1,'L'),(-1,'R')]:
        upper,lower,wrist = ['%s.%s'%(n,suffix) for n in ['UpperArm','LowerArm','Wrist']]
        start=arm.data.bones[upper].head_local.copy()
        elbow=arm.data.bones[lower].head_local.copy()
        hand=arm.data.bones[wrist].head_local.copy()
        centres=[start, start.lerp(elbow,.30),start.lerp(elbow,.78),elbow,elbow.lerp(hand,.25),elbow.lerp(hand,.85),hand]
        groups=[{upper:1},{upper:1},{upper:.8,lower:.2},{upper:.45,lower:.55},{lower:1},{lower:1},{lower:.8,wrist:.2}]
        tube(centres,[.079,.074,.062,.06,.062,.075,.070],groups,robe)
        tube([hand-Vector((side*.031,0,0)),hand-Vector((side*.019,0,0))],[.075,.073],[{lower:1},{lower:1}],trim)
        tube([hand,hand+Vector((side*.028,0,0))],[.047,.043],[{wrist:1},{wrist:1}],shirt)

    def bead(center, size, mat, group):
        rings=[]
        for j in range(7):
            p=math.pi*j/6
            ring=[]
            for i in range(12):
                a=math.tau*i/12
                ring.append(vertex(Vector(center)+Vector((math.sin(p)*math.cos(a)*size[0],math.sin(p)*math.sin(a)*size[1],math.cos(p)*size[2])),{group:1}))
            rings.append(ring)
        for a,b in zip(rings,rings[1:]):
            for i in range(12):face((a[i],a[(i+1)%12],b[(i+1)%12],b[i]),mat)

    bead((0,-.043,1.54),(.047,.048,.069),skin,'Neck')

    # Back-of-head hair: the removed hood used to hide the scalp. A partial
    # ellipsoid behind the face that drops into a short bob at the nape.
    cap=[]
    for j in range(9):
        p=2.3*j/8
        drop=1.5 if math.cos(p)<0 else 1.0
        ring=[]
        for i in range(17):
            a=math.pi/2-.35+(math.pi+.7)*i/16
            ring.append(vertex((math.sin(p)*math.sin(a)*.106,-.055-math.sin(p)*math.cos(a)*.113,1.69+math.cos(p)*.125*drop),{'Head':1}))
        cap.append(ring)
    for a,b in zip(cap,cap[1:]):
        for i in range(16):face((a[i],a[i+1],b[i+1],b[i]),hair)
    for suffix in ['L','R']:
        bone='UpperArm.'+suffix
        bead(arm.data.bones[bone].head_local,(.09,.080,.082),robe,bone)
    patch([(-.026,-.167,1.625),(0,-.171,1.621),(.026,-.167,1.625),(.024,-.168,1.622),(0,-.172,1.618),(-.024,-.168,1.622)],leather,'Head')
    for z in [1.28,1.215,1.15]:
        bead((0,-.166,z),(.008,.005,.008),gold,'Torso' if z>1.23 else 'Abdomen')
    # Small shield badge and its brass star; no oversized armour accents.
    patch([(.097,-.180,1.388),(.139,-.171,1.388),(.136,-.173,1.354),(.116,-.180,1.337),(.098,-.183,1.354)],trim,'Chest')
    patch([(.115,-.188,1.380),(.120,-.188,1.366),(.132,-.184,1.363),(.121,-.188,1.359),(.117,-.190,1.345),(.113,-.190,1.359),(.102,-.188,1.363),(.113,-.188,1.367)],gold,'Chest')

    data=bpy.data.meshes.new('Wizard_Tailoring')
    data.from_pydata(vertices,[],faces)
    data.update()
    obj=bpy.data.objects.new('Wizard_Tailoring',data)
    bpy.context.collection.objects.link(obj)
    for m in body.data.materials:data.materials.append(m)
    for p,mat in zip(data.polygons,face_mats):p.material_index=mat;p.use_smooth=True
    # Make normals consistent on each cloth shell before joining it to the skin.
    bm=bmesh.new();bm.from_mesh(data);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(data);bm.free()
    for i,weight in enumerate(weights):
        for name,value in weight.items():
            if value>0:
                vg=obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                vg.add([i],value,'REPLACE')
    obj.parent=arm
    modifier=obj.modifiers.new('Hero_Rig','ARMATURE');modifier.object=arm
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True);obj.select_set(True)
    bpy.context.view_layer.objects.active=body
    bpy.ops.object.join()
    body.name='Hero_Body'
    body.data.name='Hero_Body'
    print('[costume] Tailored robe, shirt, waistcoat, collar, cuffs, badge, hair and boots')
