"""Art pass Gothic kit — project-original modular architecture and props.

Run headless:
    blender -b --factory-startup --python kit_models.py -- --out <dir>

Everything is authored parametrically in Blender (bmesh) and exported as GLB,
one file per module, in metres, +Y up (glTF standard; Godot imports Y-up).
Materials are placeholders by slot name; the game assigns its PBR materials by
slot index through `client/scripts/assets/pbr_kit.gd`.

Module grid (documented, checked by tools/run_art_checks.ps1):
  * primary wall bay 4.00 m wide, storey 6.00 m tall, wall 0.45 m thick
  * doorway clear 2.40 x 3.40 m; arcade clear 6.00 x 5.00 m
  * floor module 4.00 x 4.00 m; stair rise 0.20 m
  * column height 6.00 m, shaft radius 0.35 m
  * rail 1.10 m high (matches the castle railing standard)

All geometry is flat-shaded low poly with a small chamfer; there are no
UV-dependent tricks in the shader queue — the stone materials sample in world
space (triplanar), so these modules do not need art-directed UVs to avoid
stretching. Trim modules are still box-projected for the trim sheet.
"""

import math
import os
import sys
import argparse

import bpy
import bmesh
from mathutils import Matrix, Vector, Euler


# ------------------------------------------------------------------ scaffolding

MATERIAL_COLORS = {
    "stone":      (0.52, 0.48, 0.42, 1.0),
    "stone_dark": (0.30, 0.29, 0.27, 1.0),
    "slate":      (0.16, 0.19, 0.26, 1.0),
    "wood":       (0.30, 0.19, 0.10, 1.0),
    "wood_dark":  (0.16, 0.10, 0.05, 1.0),
    "iron":       (0.09, 0.095, 0.11, 1.0),
    "glass":      (0.55, 0.68, 0.80, 1.0),
    "cloth":      (0.42, 0.10, 0.12, 1.0),
    "wax":        (0.86, 0.83, 0.74, 1.0),
    "books":      (0.28, 0.16, 0.12, 1.0),
    "foliage":    (0.10, 0.24, 0.08, 1.0),
    "grass":      (0.14, 0.28, 0.08, 1.0),
    "metal_soft": (0.55, 0.50, 0.42, 1.0),
    "flame":      (1.0, 0.65, 0.22, 1.0),
}
MATERIAL_ORDER = list(MATERIAL_COLORS.keys())


def material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = MATERIAL_COLORS[name]
            bsdf.inputs["Roughness"].default_value = 0.8
            if name == "iron":
                bsdf.inputs["Metallic"].default_value = 0.9
                bsdf.inputs["Roughness"].default_value = 0.45
            if name == "metal_soft":
                bsdf.inputs["Metallic"].default_value = 0.85
                bsdf.inputs["Roughness"].default_value = 0.35
            if name == "glass":
                bsdf.inputs["Roughness"].default_value = 0.15
                bsdf.inputs["Alpha"].default_value = 0.5
                mat.blend_method = 'BLEND'
            if name == "flame":
                bsdf.inputs["Emission Color"].default_value = MATERIAL_COLORS[name]
                bsdf.inputs["Emission Strength"].default_value = 3.0
    return mat


class Builder:
    """Small bmesh helper set for flat-shaded, chamfered stone/wood pieces."""

    def __init__(self, name: str):
        self.name = name
        self.bm = bmesh.new()
        self.mat_slots: list = []

    # -- material handling -------------------------------------------------
    def use(self, *names: str) -> int:
        """Register material slots in order; returns the index of the last."""
        for name in names:
            if name not in self.mat_slots:
                self.mat_slots.append(name)
        return self.mat_slots.index(names[-1])

    def _tag(self, faces, slot: int) -> None:
        for f in faces:
            f.material_index = slot

    # -- primitives ---------------------------------------------------------
    def box(self, center, size, slot: int = 0, tag: bool = True):
        mat = Matrix.Translation(Vector(center)) @ Matrix.Diagonal(
            Vector((size[0], size[1], size[2], 1.0)))
        before = set(self.bm.faces)
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=mat)
        if tag:
            self._tag([f for f in self.bm.faces if f not in before], slot)
        return self

    def cylinder(self, center, radius, depth, segments: int = 12,
                 slot: int = 0, axis: str = "y", radius_top=None,
                 cap: bool = True, tag: bool = True):
        """A capped cylinder. `axis` is the module-local axis it runs along;
        the default is "y" because every module is authored with local +Y up
        (trees, columns, candles and legs all grow upward)."""
        before = set(self.bm.faces)
        if radius_top is None:
            radius_top = radius
        bmesh.ops.create_cone(
            self.bm, cap_ends=cap, cap_tris=False, segments=segments,
            radius1=radius, radius2=radius_top, depth=depth,
            matrix=Matrix.Translation(Vector(center)))
        new_faces = [f for f in self.bm.faces if f not in before]
        if axis != "z":
            rot = Matrix.Rotation(math.pi / 2.0, 4, "Y" if axis == "x" else "X")
            center_v = Vector(center)
            verts = list({v for f in new_faces for v in f.verts})
            bmesh.ops.rotate(self.bm, verts=verts, cent=center_v, matrix=rot.to_3x3())
        if tag:
            self._tag(new_faces, slot)
        return self

    def lathe(self, profile, center=(0, 0, 0), segments: int = 12, slot: int = 0,
              tag: bool = True):
        """Revolve a profile [(radius, y), ...] around the Y axis."""
        before = set(self.bm.faces)
        verts = []
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            ring = []
            for r, y in profile:
                ring.append(self.bm.verts.new((math.sin(angle) * r, y, math.cos(angle) * r)))
            verts.append(ring)
        cx, cy, cz = center
        for ring in verts:
            for v in ring:
                v.co += Vector((cx, cy, cz))
        for i in range(segments):
            a = verts[i]
            b = verts[(i + 1) % segments]
            for j in range(len(profile) - 1):
                self.bm.faces.new([a[j], b[j], b[j + 1], a[j + 1]])
        # Caps (flat rings need a fan; use the profile ends).
        if profile[0][0] > 0.0001:
            self.bm.faces.new([ring[0] for ring in reversed(verts)])
        if profile[-1][0] > 0.0001:
            self.bm.faces.new([ring[-1] for ring in verts])
        new_faces = [f for f in self.bm.faces if f not in before]
        for f in new_faces:
            f.normal_update()
        if tag:
            self._tag(new_faces, slot)
        return self

    def arch_ring(self, inner: list, thickness: float, depth: float,
                  slot: int = 0, center=(0.0, 0.0, 0.0), tag: bool = True):
        """A closed arch surround: an inner profile offset outward by
        `thickness`, extruded through `depth`.

        Built in the XY plane (depth on Z) then left in place; callers rotate.
        Both loops carry the same vertex count, so the rings bridge cleanly.
        """
        before = set(self.bm.faces)
        outer = _offset_loop(inner, thickness)

        def ring(points, z):
            return [self.bm.verts.new((x, y, z)) for x, y in points]

        inner_front = ring(inner, 0.0)
        inner_back = ring(inner, depth)
        outer_front = ring(outer, 0.0)
        outer_back = ring(outer, depth)
        self._bridge(inner_front, outer_front)          # front face
        self._bridge(outer_back, inner_back)            # back face
        self._bridge(outer_front, outer_back, flip=True)  # outer rim
        self._bridge(inner_back, inner_front, flip=True)  # inner soffit
        new_faces = [f for f in self.bm.faces if f not in before]
        for f in new_faces:
            f.normal_update()
        if tag:
            self._tag(new_faces, slot)
        offset = Vector(center)
        if offset.length > 0.0:
            for f in new_faces:
                for v in f.verts:
                    v.co += offset
        return self

    def _bridge(self, loop_a, loop_b, flip: bool = False):
        n = len(loop_a)
        for i in range(n):
            a0 = loop_a[i]
            a1 = loop_a[(i + 1) % n]
            b0 = loop_b[i]
            b1 = loop_b[(i + 1) % n]
            quad = [a0, a1, b1, b0]
            if flip:
                quad.reverse()
            try:
                self.bm.faces.new(quad)
            except ValueError:
                pass  # duplicate face; skip

    # -- finishing -----------------------------------------------------------
    def bevel(self, width: float = 0.012, segments: int = 1, angle_limit: float = 0.5):
        bmesh.ops.bevel(self.bm, geom=list(self.bm.verts) + list(self.bm.edges)
                        + list(self.bm.faces), offset=width, offset_type='OFFSET',
                        segments=segments, profile=0.7, affect='EDGES',
                        clamp_overlap=True)
        return self

    def displace(self, amount: float, frequency: float, seed: int):
        from mathutils import noise
        for v in self.bm.verts:
            v.co += v.normal * (noise.noise(v.co * frequency) * amount)
        return self

    def uv_box(self, scale: float = 0.25):
        """Per-face box projection: UV = (metres * scale) on the dominant axes."""
        uv_layer = self.bm.loops.layers.uv.verify()
        for face in self.bm.faces:
            n = face.normal
            axis = max(range(3), key=lambda i: abs(n[i]))
            for loop in face.loops:
                co = loop.vert.co
                if axis == 0:
                    u, v = co.z, co.y
                elif axis == 1:
                    u, v = co.x, co.z
                else:
                    u, v = co.x, co.y
                loop[uv_layer].uv = (u * scale, v * scale)
        return self

    def transform(self, matrix: Matrix):
        bmesh.ops.transform(self.bm, matrix=matrix, verts=list(self.bm.verts))
        return self

    def finish(self) -> bpy.types.Object:
        # Outward-consistent normals: bridged arch rings and merged pieces can
        # otherwise end up with faces lit from the wrong side in the engine.
        bmesh.ops.recalc_face_normals(self.bm, faces=list(self.bm.faces))
        mesh = bpy.data.meshes.new(self.name)
        self.bm.normal_update()
        self.bm.to_mesh(mesh)
        self.bm.free()
        obj = bpy.data.objects.new(self.name, mesh)
        for slot_name in self.mat_slots:
            obj.data.materials.append(material(slot_name))
        bpy.context.scene.collection.objects.link(obj)
        return obj


def _offset_loop(points: list, thickness: float) -> list:
    """Offset a closed 2D polyline outward along its local normals."""
    n = len(points)
    out = []
    for i in range(n):
        prev = Vector(points[(i - 1) % n])
        cur = Vector(points[i])
        nxt = Vector(points[(i + 1) % n])
        tangent = (nxt - prev)
        if tangent.length < 1e-8:
            tangent = nxt - cur
        normal = Vector((tangent.y, -tangent.x)).normalized()
        out.append((cur.x + normal.x * thickness, cur.y + normal.y * thickness))
    return out


# ------------------------------------------------------------------- profiles

def pointed_arch_hole(width: float, bottom: float, spring: float, apex: float,
                      segments: int = 10):
    """A true two-centred pointed-arch profile (counter-clockwise, y up).

    Both arcs spring from the jamb tops and meet at the apex. The arc centre is
    solved so the curve passes exactly through (0, apex) and the jamb points,
    which is what makes the apex read as a point rather than a notch. The
    profile starts at the bottom-left corner, runs along the sill, up the right
    jamb, over the right arc, down the left arc and back to the left jamb.
    """
    w2 = width / 2.0
    h = apex - spring
    centre_x = (w2 * w2 - h * h) / (2.0 * w2)
    radius = abs(w2 - centre_x)

    points = [(-w2, bottom), (w2, bottom), (w2, spring)]
    a0 = math.atan2(0.0, w2 - centre_x)
    a1 = math.atan2(h, -centre_x)
    for i in range(1, segments):
        t = i / float(segments)
        angle = a0 + (a1 - a0) * t
        points.append((centre_x + math.cos(angle) * radius,
                       spring + math.sin(angle) * radius))
    for i in range(1, segments):
        t = i / float(segments)
        angle = (math.pi - a1) + ((math.pi - a0) - (math.pi - a1)) * t
        points.append((-centre_x + math.cos(angle) * radius,
                       spring + math.sin(angle) * radius))
    points.append((-w2, spring))
    return points


def _arch_curve_x(y: float, spring: float, apex: float, width: float) -> float:
    """The right-hand half of the arch curve at height y (inches from centre)."""
    w2 = width / 2.0
    h = apex - spring
    centre_x = (w2 * w2 - h * h) / (2.0 * w2)
    radius = abs(w2 - centre_x)
    dy = y - spring
    if abs(dy) > radius:
        return 0.0
    return centre_x + math.sqrt(max(0.0, radius * radius - dy * dy))


def arch_panel(b: Builder, rect_w: float, rect_h: float, clear_w: float,
               spring_frac: float, apex_margin: float, depth: float,
               slot: int, band: float = 0.26, steps: int = 3,
               fill_depth: float | None = None) -> list:
    """A pointed-arch surround that fills its rectangle exactly.

    Built from a moulded arch band, jamb infill and stepped spandrels so the
    module can simply be scaled to an existing rectangular wall opening: no
    see-through corners, no re-cutting the wall. Returns the inner clear
    profile (for a glazing or a second surface).
    """
    bottom = -rect_h / 2.0
    spring = bottom + spring_frac * rect_h
    apex = rect_h / 2.0 - apex_margin
    inner = pointed_arch_hole(clear_w, bottom, spring, apex)
    b.arch_ring(inner, thickness=band, depth=depth, slot=slot)
    if fill_depth is None:
        fill_depth = max(0.05, depth - 0.06)
    half = rect_w / 2.0
    # Jamb infill from the band edge to the rectangle edge.
    for side in (-1.0, 1.0):
        x_inner = side * (clear_w / 2.0 + band)
        b.box((side * (abs(x_inner) + half) / 2.0, (bottom + spring) / 2.0, fill_depth / 2.0),
              (half - abs(x_inner), spring - bottom, fill_depth), slot)
    # Stepped spandrels: each step is flat-topped and starts where the arch
    # curve is at its innermost inside that band.
    for k in range(steps):
        y0 = spring + (apex - spring) * float(k) / float(steps)
        y1 = spring + (apex - spring) * float(k + 1) / float(steps)
        x_edge = _arch_curve_x(y1, spring, apex, clear_w)
        width = half - x_edge
        if width <= 0.02:
            continue
        for side in (-1.0, 1.0):
            b.box((side * (x_edge + half) / 2.0, (y0 + y1) / 2.0, fill_depth / 2.0),
                  (width, y1 - y0, fill_depth), slot)
    # Strip above the apex.
    if rect_h / 2.0 - apex > 0.02:
        b.box((0.0, (apex + rect_h / 2.0) / 2.0, fill_depth / 2.0),
              (rect_w, rect_h / 2.0 - apex, fill_depth), slot)
    return inner


def round_arch_hole(width: float, clear_height: float, spring: float,
                    segments: int = 9):
    w2 = width / 2.0
    points = [(-w2, -clear_height / 2.0), (w2, -clear_height / 2.0),
              (w2, -clear_height / 2.0 + spring)]
    centre = Vector((0.0, -clear_height / 2.0 + spring))
    radius = w2
    for i in range(1, segments):
        angle = (math.pi * i) / float(segments)
        points.append((centre.x + math.cos(angle) * radius,
                       centre.y + math.sin(angle) * radius))
    points.append((-w2, -clear_height / 2.0 + spring))
    return points


# --------------------------------------------------------------------- kit

def wall_module(damaged: bool = False) -> Builder:
    b = Builder("wall_module_4x6_damaged" if damaged else "wall_module_4x6")
    stone = b.use("stone")
    b.box((0.0, 3.0, 0.0), (4.0, 6.0, 0.45), stone)
    # Plinth and cornice bands give the panel a silhouette at gameplay distance.
    b.box((0.0, 0.22, 0.0), (4.06, 0.44, 0.55), stone)
    b.box((0.0, 5.80, 0.0), (4.08, 0.40, 0.58), stone)
    if damaged:
        # Collapse the upper right corner into stepped rubble and scatter debris.
        b.box((1.75, 5.42, 0.0), (0.55, 1.15, 0.44), stone)
        b.box((1.35, 5.05, 0.0), (0.85, 0.50, 0.44), stone)
        b.box((0.85, 4.85, 0.06), (0.45, 0.30, 0.36), stone)
        b.box((1.55, 4.60, -0.05), (0.32, 0.24, 0.30), stone)
    b.uv_box().bevel(0.012)
    return b


def corner_module() -> Builder:
    b = Builder("corner_4x6")
    stone = b.use("stone")
    b.box((0.0, 3.0, -2.0), (4.0, 6.0, 0.45), stone)
    b.box((2.0, 3.0, 0.0), (0.45, 6.0, 4.0), stone)
    # Quoin stones at the corner: alternating blocks read as dressed masonry.
    for i in range(6):
        size_x = 0.5 if i % 2 == 0 else 0.36
        size_z = 0.5 if i % 2 == 0 else 0.36
        b.box((2.0, 0.5 + i * 1.0, -2.0), (size_x, 0.85, size_z + 0.5), stone)
    b.uv_box().bevel(0.012)
    return b


def arch_module(name: str, rect_w: float, rect_h: float, clear_w: float,
                spring_frac: float, apex_margin: float, depth: float,
                jamb_shafts: bool = False) -> Builder:
    """A pointed-arch surround that fills a rectangular wall opening.

    Authored in the local frame (x = width, y = height, z = depth); the shared
    export rotation lifts every module into Blender's Z-up world. Scale it to
    the opening and it dresses the reveal instead of re-cutting the wall.
    """
    b = Builder(name)
    stone = b.use("stone")
    spring = -rect_h / 2.0 + spring_frac * rect_h
    apex = rect_h / 2.0 - apex_margin
    arch_panel(b, rect_w, rect_h, clear_w, spring_frac, apex_margin, depth, stone)
    # A keystone at the apex.
    b.box((0.0, apex - 0.10, depth * 0.55), (0.34, 0.42, depth * 1.15), stone)
    if jamb_shafts:
        jamb_len = spring + rect_h / 2.0 - 0.2
        for side in (-1.0, 1.0):
            b.cylinder((side * (clear_w / 2.0 + 0.30), -rect_h / 2.0 + jamb_len / 2.0 + 0.1, 0.0),
                       0.22, jamb_len, segments=10, slot=stone, axis="y")
            b.box((side * (clear_w / 2.0 + 0.30), -rect_h / 2.0 + 0.16, 0.0),
                  (0.62, 0.32, depth * 1.05), stone)
    b.uv_box().bevel(0.014)
    return b


def column_module(height: float = 6.0, broken: bool = False) -> Builder:
    b = Builder("column_broken_2_2" if broken else "column_6")
    stone = b.use("stone")
    h = 2.2 if broken else height
    # Base: two chamfered steps.
    b.lathe([(0.55, 0.0), (0.55, 0.18), (0.46, 0.18), (0.46, 0.42), (0.40, 0.42),
             (0.40, 0.52), (0.0, 0.52)], segments=12, slot=stone)
    # Shaft with slight entasis.
    profile = []
    steps = 6
    for i in range(steps + 1):
        t = i / float(steps)
        y = 0.5 + t * (h - 1.3)
        r = 0.35 - 0.035 * t
        profile.append((r, y))
    b.lathe(profile, segments=12, slot=stone, tag=True)
    if broken:
        # Jagged broken shaft top: a ring of uneven little blocks.
        for i in range(8):
            angle = 2.0 * math.pi * i / 8.0
            b.box((math.sin(angle) * 0.22, h - 0.85 + (i % 3) * 0.09,
                   math.cos(angle) * 0.22), (0.26, 0.30, 0.26), stone)
    else:
        # Capital: collar, bell, abacus.
        b.lathe([(0.35, h - 0.8), (0.38, h - 0.7), (0.30, h - 0.52), (0.30, h - 0.35),
                 (0.44, h - 0.22), (0.44, h - 0.12), (0.52, h - 0.12), (0.52, h - 0.03),
                 (0.0, h - 0.03)], segments=12, slot=stone)
    b.uv_box().bevel(0.008)
    return b


def buttress_module() -> Builder:
    b = Builder("buttress_1x6")
    stone = b.use("stone")
    # Stepped profile: wide base, two offsets, then a plain shaft.
    b.box((0.0, 0.9, 0.0), (1.40, 1.8, 1.05), stone)
    b.box((0.0, 2.6, 0.0), (1.05, 1.6, 0.90), stone)
    b.box((0.0, 5.0, -0.05), (0.72, 3.4, 0.80), stone)
    # Weathering slopes (rotated slabs) at the top of each offset.
    slope = Matrix.Rotation(math.radians(-38.0), 4, "X")
    for (y, z) in ((2.7, 0.52), (1.7, 0.62)):
        b.box((0.0, y + 0.16, z), (1.1, 0.14, 0.66), stone)
        slab = Builder("slope")
        slab.use("stone")
        slab.box((0.0, 0.0, 0.0), (1.06, 0.22, 0.60), 0)
        slab.transform(Matrix.Translation(Vector((0.0, y, z))) @ slope)
        slab.uv_box()
        _merge(b, slab)
    b.uv_box().bevel(0.012)
    return b


def _merge(target: Builder, other: Builder) -> None:
    """Copy another builder's geometry into this one (material names merged)."""
    slot_map = {}
    for i, slot_name in enumerate(other.mat_slots):
        if slot_name not in target.mat_slots:
            target.mat_slots.append(slot_name)
        slot_map[i] = target.mat_slots.index(slot_name)
    mesh = bpy.data.meshes.new("merge_tmp")
    other.bm.normal_update()
    other.bm.to_mesh(mesh)
    other.bm.free()
    for polygon in mesh.polygons:
        polygon.material_index = slot_map.get(polygon.material_index, 0)
    target.bm.from_mesh(mesh)   # from_mesh appends to the existing bmesh
    bpy.data.meshes.remove(mesh)


def window_module() -> Builder:
    b = Builder("window_lancet_2x4")
    stone = b.use("stone")
    glass = b.use("glass")
    # A complete lancet panel: masonry fills its rectangle, the light is a
    # glazed pointed head with mullion and transom. Drawn on a solid wall as
    # clerestory, so it never changes the walkable route.
    rect_w, rect_h = 2.4, 4.6
    inner = arch_panel(b, rect_w, rect_h, 1.5, 0.62, 0.75, 0.42, stone)
    bottom = -rect_h / 2.0
    spring = bottom + 0.62 * rect_h
    apex = rect_h / 2.0 - 0.75
    # Glass: a quad inset behind the tracery, sized to the light.
    b.box((0.0, (bottom + apex) / 2.0 - 0.05, 0.12), (1.42, apex - bottom - 0.25, 0.05), glass)
    # Mullion and transom: the tracery silhouette.
    b.box((0.0, (bottom + apex) / 2.0 - 0.05, 0.17), (0.09, apex - bottom - 0.3, 0.18), stone)
    b.box((0.0, (bottom + spring) / 2.0 + 0.2, 0.17), (1.44, 0.09, 0.18), stone)
    # Sill.
    b.box((0.0, bottom + 0.06, 0.20), (rect_w + 0.3, 0.16, 0.56), stone)
    b.uv_box().bevel(0.01)
    return b


def door_module() -> Builder:
    b = Builder("door_double_2_4x3")
    wood = b.use("wood")
    iron = b.use("iron")
    # Frame.
    for side in (-1.0, 1.0):
        b.box((side * 1.32, 1.75, 0.0), (0.24, 3.5, 0.48), wood)
    b.box((0.0, 3.62, 0.0), (2.88, 0.30, 0.48), wood)
    # Two leaves swung open into the room (about 105 degrees), hinged at the jambs.
    for side in (-1.0, 1.0):
        leaf = Builder("leaf")
        leaf.use("wood")
        leaf.box((0.55, 1.6, 0.0), (1.10, 3.2, 0.09), 0)
        for band in (0.7, 2.6):
            leaf.box((0.55, band, 0.0), (1.0, 0.12, 0.12), leaf.use("iron"))
        leaf.box((0.55, 1.6, 0.0), (0.12, 2.6, 0.02), leaf.use("wood_dark"))
        leaf.transform(Matrix.Translation(Vector((side * 1.2, 0.0, 0.1)))
                       @ Matrix.Rotation(math.radians(-105.0 if side < 0 else 105.0)
                                         + (0.0 if side > 0 else math.pi), 4, "Y"))
        leaf.uv_box()
        _merge(b, leaf)
    b.uv_box().bevel(0.006)
    return b


def floor_module() -> Builder:
    b = Builder("floor_flag_4")
    stone = b.use("stone")
    b.box((0.0, -0.06, 0.0), (4.0, 0.12, 4.0), stone)
    # A few missing corner chips sell age; they sit below walking height.
    for (x, z) in ((1.9, 1.9), (-1.95, 0.4)):
        b.box((x, -0.02, z), (0.5, 0.10, 0.5), stone)
    b.uv_box().bevel(0.01)
    return b


def stair_tread_module() -> Builder:
    b = Builder("stair_tread_0_2x4")
    stone = b.use("stone")
    b.box((0.0, -0.10, 0.0), (4.0, 0.20, 0.34), stone)
    b.box((0.0, -0.03, 0.14), (4.0, 0.06, 0.08), stone)   # nosing
    b.uv_box().bevel(0.008)
    return b


def balustrade_module() -> Builder:
    b = Builder("balustrade_4")
    stone = b.use("stone")
    b.box((0.0, 0.08, 0.0), (4.0, 0.16, 0.22), stone)      # plinth rail
    b.box((0.0, 1.02, 0.0), (4.0, 0.16, 0.26), stone)      # handrail
    for i in range(5):
        x = -1.6 + i * 0.8
        b.lathe([(0.09, 0.16), (0.11, 0.28), (0.07, 0.60), (0.11, 0.86), (0.09, 0.95)],
                center=(x, 0.0, 0.0), segments=8, slot=stone)
    b.uv_box().bevel(0.006)
    return b


def newel_module() -> Builder:
    b = Builder("newel_post_1_2")
    stone = b.use("stone")
    b.lathe([(0.20, 0.0), (0.22, 0.14), (0.16, 0.20), (0.17, 0.95), (0.20, 1.02),
             (0.14, 1.10), (0.06, 1.22), (0.0, 1.26)], segments=8, slot=stone)
    b.uv_box().bevel(0.006)
    return b


def roof_slope_module() -> Builder:
    b = Builder("roof_slope_4x6")
    slate = b.use("slate")
    # Overlapping courses: three stepped slabs so the silhouette reads as slate.
    for i in range(3):
        y = 6.0 - i * 2.0
        b.box((0.0, y - 1.0, i * 0.055), (4.0, 2.05, 0.10), slate)
    b.uv_box().bevel(0.008)
    return b


def tower_cap_module() -> Builder:
    b = Builder("tower_cap_7")
    slate = b.use("slate")
    b.lathe([(7.3, 0.0), (7.3, 0.35), (7.0, 0.45), (0.25, 3.4), (0.12, 3.5),
             (0.30, 3.7), (0.0, 4.1)], segments=16, slot=slate)
    b.uv_box().bevel(0.01)
    return b


def trim_band_module() -> Builder:
    b = Builder("trim_band_4")
    stone = b.use("stone")
    # Cavetto-ish string course: three slabs stepping out.
    b.box((0.0, 0.0, 0.0), (4.0, 0.20, 0.30), stone)
    b.box((0.0, 0.14, 0.0), (4.0, 0.10, 0.40), stone)
    b.box((0.0, 0.24, 0.0), (4.0, 0.08, 0.48), stone)
    b.uv_box().bevel(0.008)
    return b


def rubble_module() -> Builder:
    b = Builder("rubble_pile_1")
    stone = b.use("stone")
    pieces = [
        (0.0, 0.16, 0.0, 0.55, 0.30, 0.42, 0.4),
        (0.42, 0.12, 0.28, 0.40, 0.22, 0.34, 1.1),
        (-0.36, 0.10, 0.22, 0.34, 0.18, 0.28, 2.2),
        (0.10, 0.10, -0.40, 0.30, 0.18, 0.26, 0.7),
        (-0.18, 0.26, -0.05, 0.34, 0.22, 0.30, 2.9),
    ]
    for (x, y, z, sx, sy, sz, rot) in pieces:
        piece = Builder("rock")
        piece.use("stone")
        piece.box((0, 0, 0), (sx, sy, sz), 0)
        piece.transform(Matrix.Translation(Vector((x, y, z)))
                        @ Matrix.Rotation(rot, 4, "Y") @ Matrix.Rotation(rot * 0.6, 4, "Z"))
        piece.uv_box()
        _merge(b, piece)
    b.uv_box().bevel(0.01)
    return b


# ------------------------------------------------------------------- props

def long_table_module() -> Builder:
    b = Builder("long_table_8")
    wood = b.use("wood")
    dark = b.use("wood_dark")
    # Three plank top, 8 m x 1.7 m, 0.78 m high.
    for i in range(3):
        b.box((0.0, 0.76, -0.55 + i * 0.55), (7.6, 0.08, 0.52), wood)
    # Trestle legs at both ends.
    for x in (-3.3, 3.3):
        b.box((x, 0.36, 0.0), (0.22, 0.72, 0.14), dark)
        b.box((x, 0.05, 0.0), (0.30, 0.10, 1.30), dark)
        b.box((x, 0.70, 0.0), (0.24, 0.10, 1.45), wood)
    b.uv_box().bevel(0.006)
    return b


def bench_module() -> Builder:
    b = Builder("bench_4")
    wood = b.use("wood")
    dark = b.use("wood_dark")
    b.box((0.0, 0.46, 0.0), (3.8, 0.09, 0.42), wood)
    for x in (-1.6, 1.6):
        b.box((x, 0.22, 0.0), (0.16, 0.45, 0.34), dark)
    b.uv_box().bevel(0.005)
    return b


def bookshelf_module() -> Builder:
    b = Builder("bookshelf_4x3")
    wood = b.use("wood")
    books = b.use("books")
    b.box((0.0, 1.5, -0.25), (4.0, 0.10, 0.55), wood)          # top
    b.box((0.0, 1.5, 0.02), (4.0, 3.0, 0.08), wood)            # back
    for side in (-1.96, 1.96):
        b.box((side, 1.5, -0.02), (0.10, 3.0, 0.60), wood)
    for shelf in range(4):
        y = 0.35 + shelf * 0.75
        b.box((0.0, y, -0.05), (3.9, 0.07, 0.52), wood)
        # A row of book blocks with varied heights.
        x = -1.75
        seed = shelf * 7
        while x < 1.6:
            width = 0.10 + ((seed * 37) % 5) * 0.035
            height = 0.34 + ((seed * 53) % 4) * 0.05
            b.box((x + width / 2.0, y + height / 2.0 + 0.04, -0.02),
                  (width, height, 0.34), books)
            x += width + 0.025
            seed += 1
    b.uv_box().bevel(0.005)
    return b


def ladder_module() -> Builder:
    b = Builder("ladder_3")
    wood = b.use("wood")
    for side in (-1.0, 1.0):
        b.box((side * 0.22, 1.5, 0.0), (0.09, 3.0, 0.09), wood)
    for i in range(7):
        b.box((0.0, 0.28 + i * 0.4, 0.0), (0.40, 0.06, 0.06), wood)
    b.uv_box().bevel(0.004)
    return b


def desk_module() -> Builder:
    b = Builder("desk_1_6")
    wood = b.use("wood")
    dark = b.use("wood_dark")
    b.box((0.0, 0.74, 0.0), (1.6, 0.07, 0.9), wood)
    b.box((0.0, 0.86, -0.28), (1.6, 0.30, 0.34), wood)         # sloped lid block
    b.box((0.0, 0.36, 0.0), (0.18, 0.70, 0.7), dark)
    b.box((0.0, 0.45, 0.72), (0.6, 0.08, 0.5), wood)           # stool
    b.box((0.0, 0.22, 0.72), (0.16, 0.44, 0.4), dark)
    b.uv_box().bevel(0.005)
    return b


def lectern_module() -> Builder:
    b = Builder("lectern_1")
    wood = b.use("wood")
    books = b.use("books")
    b.box((0.0, 0.55, 0.0), (1.3, 0.10, 0.5), wood)
    b.box((0.0, 1.05, 0.0), (1.1, 0.10, 0.6), wood)
    b.box((0.0, 0.90, 0.02), (0.16, 0.90, 0.3), wood)
    b.box((0.0, 1.16, 0.0), (0.7, 0.16, 0.5), books)
    b.uv_box().bevel(0.005)
    return b


def armour_module() -> Builder:
    b = Builder("armour_stand_2")
    iron = b.use("iron")
    cloth = b.use("cloth")
    # Chunky but readable: legs, skirt, torso, pauldrons, helm, plume, sword.
    for side in (-1.0, 1.0):
        b.cylinder((side * 0.16, 0.45, 0.0), 0.10, 0.9, segments=8, slot=iron)
        b.box((side * 0.16, 0.03, 0.0), (0.24, 0.08, 0.34), iron)
    b.lathe([(0.30, 0.85), (0.36, 1.05), (0.32, 1.45), (0.36, 1.62), (0.30, 1.70),
             (0.0, 1.72)], segments=10, slot=iron)
    for side in (-1.0, 1.0):
        b.box((side * 0.38, 1.48, 0.0), (0.28, 0.22, 0.36), iron)
        b.box((side * 0.42, 1.30, 0.0), (0.14, 0.30, 0.16), iron)
    b.box((0.0, 1.86, 0.0), (0.26, 0.3, 0.26), iron)           # helm
    b.box((0.0, 2.14, -0.02), (0.10, 0.30, 0.12), cloth)       # plume
    b.box((0.62, 1.05, 0.1), (0.06, 1.3, 0.06), iron)          # sword
    b.box((0.0, 1.02, 0.30), (0.5, 0.08, 0.5), iron)           # plinth
    b.uv_box().bevel(0.006)
    return b


def banner_module() -> Builder:
    b = Builder("banner_1_2x3")
    cloth = b.use("cloth")
    wood = b.use("wood")
    b.box((0.0, 3.1, 0.0), (1.5, 0.08, 0.08), wood)            # rod
    b.box((0.0, 1.55, 0.02), (1.2, 2.9, 0.03), cloth)          # field
    b.box((0.0, 2.75, 0.05), (1.2, 0.3, 0.02), cloth)          # header
    b.box((0.0, 0.12, 0.05), (1.2, 0.24, 0.02), cloth)         # tail
    b.uv_box().bevel(0.004)
    return b


def portrait_module() -> Builder:
    b = Builder("portrait_1x1_5")
    wood = b.use("wood_dark")
    books = b.use("books")
    b.box((0.0, 0.0, 0.0), (1.0, 1.5, 0.10), wood)
    b.box((0.0, 0.0, 0.04), (0.78, 1.28, 0.06), books)
    b.uv_box().bevel(0.012)
    return b


def candelabra_module() -> Builder:
    b = Builder("candelabra_1_6")
    iron = b.use("iron")
    wax = b.use("wax")
    flame = b.use("flame")
    b.lathe([(0.20, 0.0), (0.22, 0.06), (0.10, 0.10), (0.05, 1.35), (0.10, 1.42),
             (0.04, 1.46)], segments=8, slot=iron)
    for i, angle in enumerate((0.0, 2.1, 4.2)):
        x = math.sin(angle) * 0.28
        z = math.cos(angle) * 0.28
        b.box((x, 1.36, z), (0.06, 0.05, 0.5), iron)
        b.cylinder((x, 1.46, z), 0.045, 0.22, segments=6, slot=wax)
        b.box((x, 1.60, z), (0.05, 0.09, 0.05), flame)
    b.uv_box().bevel(0.004)
    return b


def candle_cluster_module() -> Builder:
    b = Builder("candle_cluster")
    wax = b.use("wax")
    flame = b.use("flame")
    spots = [(0.0, 0.0, 0.30), (0.14, 0.08, 0.22), (-0.13, 0.06, 0.36), (0.05, -0.14, 0.26)]
    for (x, z, h) in spots:
        b.cylinder((x, h / 2.0, z), 0.035, h, segments=6, slot=wax)
        b.box((x, h + 0.035, z), (0.035, 0.07, 0.035), flame)
    b.uv_box().bevel(0.003)
    return b


# ------------------------------------------------------------- vegetation

def _card_piece(centre: Vector, size, angle: float, material: str,
                scale: float = 0.5) -> Builder:
    """One rotated double/single card piece as its own builder (for merging)."""
    piece = Builder("card")
    piece.use(material)
    piece.box((0.0, 0.0, 0.0), size, 0)
    piece.transform(Matrix.Translation(centre) @ Matrix.Rotation(angle, 4, "Y"))
    piece.uv_box(scale=scale)
    return piece


def tree_pine_module() -> Builder:
    b = Builder("tree_pine_8")
    trunk = b.use("wood_dark")
    b.use("foliage")
    # Tapered trunk (8 m).
    b.cylinder((0.0, 3.6, 0.0), 0.36, 7.2, segments=8, slot=trunk, radius_top=0.10)
    # Five tiers of drooping branch cards, each a fresh piece so rotations
    # never accumulate across pieces.
    tiers = [(7.4, 3.4, 2.6), (6.1, 2.8, 2.1), (4.8, 2.2, 1.7), (3.6, 1.6, 1.3), (2.5, 1.1, 0.9)]
    for (y, spread, size) in tiers:
        for angle in (0.0, math.pi / 3.0, 2.0 * math.pi / 3.0):
            _merge(b, _card_piece(Vector((0.0, y, 0.0)), (spread, size, 0.02), angle, "foliage"))
    return b


def tree_broad_module() -> Builder:
    b = Builder("tree_broad_8")
    trunk = b.use("wood_dark")
    b.use("foliage")
    b.cylinder((0.0, 2.4, 0.0), 0.42, 4.8, segments=8, slot=trunk, radius_top=0.20)
    # Three forks reaching into the canopy.
    for angle in (0.0, 2.1, 4.2):
        piece = Builder("branch")
        piece.use("wood_dark")
        piece.box((0.0, 0.0, 0.0), (0.18, 2.6, 0.18), 0)
        piece.transform(Matrix.Translation(Vector((0.0, 5.4, 0.0)))
                        @ Matrix.Rotation(angle, 4, "Y")
                        @ Matrix.Rotation(math.radians(26.0), 4, "X"))
        piece.uv_box(scale=0.5)
        _merge(b, piece)
    # Canopy: several smaller crossed cards at staggered heights, so the
    # silhouette is a canopy rather than one billboard.
    cards = [
        (6.6, 0.0, 4.4, 3.6), (7.6, 0.8, 4.0, 3.2), (7.1, 1.9, 4.6, 3.4),
        (8.3, 2.8, 3.2, 2.6), (6.2, 3.6, 3.4, 2.8), (7.8, 4.5, 3.8, 3.0),
    ]
    for (y, phase, w, h) in cards:
        _merge(b, _card_piece(Vector((0.0, y, 0.0)), (w, h, 0.02),
                              phase, "foliage", scale=0.42))
    return b


def bush_module() -> Builder:
    b = Builder("bush_1")
    b.use("foliage")
    for i in range(3):
        _merge(b, _card_piece(Vector((0.0, 0.48, 0.0)), (1.15, 0.95, 0.02),
                              i * (math.pi / 3.0), "foliage", scale=0.8))
    return b


def grass_clump_module() -> Builder:
    b = Builder("grass_clump_1")
    b.use("grass")
    for i in range(2):
        _merge(b, _card_piece(Vector((0.0, 0.45, 0.0)), (1.0, 0.9, 0.02),
                              i * math.pi / 2.0, "grass", scale=1.0))
    return b


def rock_module(index: int) -> Builder:
    b = Builder("rock_0%d" % (index + 1))
    stone = b.use("stone")
    # Low-poly boulder: a subdivide-displaced icosphere, flattened.
    bmesh.ops.create_icosphere(b.bm, subdivisions=2, radius=1.0)
    for f in b.bm.faces:
        f.material_index = stone
    rng = __import__("random").Random(1000 + index)
    for v in b.bm.verts:
        v.co.x *= 1.0 + rng.uniform(-0.25, 0.25)
        v.co.z *= 1.0 + rng.uniform(-0.25, 0.25)
        v.co.y = v.co.y * 0.62 + 0.45
        if v.co.y < 0.02:
            v.co.y = 0.02
    b.uv_box(scale=0.4).bevel(0.02)
    return b


def plaque_module() -> Builder:
    b = Builder("plaque_0_8x0_5")
    stone = b.use("stone")
    b.box((0.0, 0.0, 0.0), (0.8, 0.5, 0.08), stone)
    b.box((0.0, 0.0, 0.05), (0.68, 0.38, 0.02), stone)
    b.uv_box().bevel(0.008)
    return b


# ------------------------------------------------------------------- export

MODULES = {
    "wall_module_4x6": lambda: wall_module(False),
    "wall_module_4x6_damaged": lambda: wall_module(True),
    "corner_4x6": corner_module,
    "arch_pointed_2_4x3_4": lambda: arch_module("arch_pointed_2_4x3_4", 2.4, 3.4, 1.9, 0.52, 0.42, 0.36),
    "arch_arcade_6x5": lambda: arch_module("arch_arcade_6x5", 6.8, 5.4, 5.6, 0.50, 0.60, 0.62, True),
    "column_6": lambda: column_module(6.0, False),
    "column_broken_2_2": lambda: column_module(2.2, True),
    "buttress_1x6": buttress_module,
    "window_lancet_2x4": window_module,
    "door_double_2_4x3": door_module,
    "floor_flag_4": floor_module,
    "stair_tread_0_2x4": stair_tread_module,
    "balustrade_4": balustrade_module,
    "newel_post_1_2": newel_module,
    "roof_slope_4x6": roof_slope_module,
    "tower_cap_7": tower_cap_module,
    "trim_band_4": trim_band_module,
    "rubble_pile_1": rubble_module,
    "long_table_8": long_table_module,
    "bench_4": bench_module,
    "bookshelf_4x3": bookshelf_module,
    "ladder_3": ladder_module,
    "desk_1_6": desk_module,
    "lectern_1": lectern_module,
    "armour_stand_2": armour_module,
    "banner_1_2x3": banner_module,
    "portrait_1x1_5": portrait_module,
    "candelabra_1_6": candelabra_module,
    "candle_cluster": candle_cluster_module,
    "tree_pine_8": tree_pine_module,
    "tree_broad_8": tree_broad_module,
    "bush_1": bush_module,
    "grass_clump_1": grass_clump_module,
    "rock_01": lambda: rock_module(0),
    "rock_02": lambda: rock_module(1),
    "rock_03": lambda: rock_module(2),
    "plaque_0_8x0_5": plaque_module,
}


def export_module(name: str, builder: Builder, out_dir: str) -> None:
    # A clean scene per module keeps the GLB to exactly one mesh object.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Every module is authored with local +Y as "up"; one shared rotation lifts
    # it into Blender's Z-up world (and therefore Godot's Y-up glTF import).
    builder.transform(Matrix.Rotation(math.pi / 2.0, 4, "X"))
    obj = builder.finish()
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    path = os.path.join(out_dir, name + ".glb")
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB', use_selection=True,
        export_apply=True, export_yup=True, export_animations=False,
        export_skins=False, export_morph=False, export_cameras=False,
        export_lights=False)
    dims = obj.dimensions
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    print("[kit-models] %-26s %6.2f x %6.2f x %6.2f m  %5d tris" % (
        name, dims.x, dims.y, dims.z, tris))
    bpy.data.objects.remove(obj)


def main() -> None:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    parsed = parser.parse_args(args)
    os.makedirs(parsed.out, exist_ok=True)
    names = [parsed.only] if parsed.only else list(MODULES.keys())
    for name in names:
        export_module(name, MODULES[name](), parsed.out)


if __name__ == "__main__":
    main()
