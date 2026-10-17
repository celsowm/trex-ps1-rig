#!/usr/bin/env python3
"""Shared helpers for the T-Rex PS1 Blender tooling.

Imported by diagnose_rig.py and animate_trex.py. Runs inside Blender.
Only bpy/mathutils plus the standard library are used.

Key idea: all pose math is expressed as rotations around WORLD axes,
converted into each bone's local rest space. That makes the scripts
independent of bone rolls.
"""

import math
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

SCRIPT_DIR = Path(__file__).resolve().parent

MESH_NAME = 'PS1_TREX_Original_Geometry'
RIG_NAME = 'TREX_EDITABLE_ARMATURE'
COLLECTION_NAME = 'T-Rex PS1 | Editable Rig'

AXIS = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
}


def find_objects():
    mesh = bpy.data.objects.get(MESH_NAME)
    rig = bpy.data.objects.get(RIG_NAME)
    if mesh is None or rig is None:
        raise RuntimeError(
            f'Scene is missing {MESH_NAME!r} or {RIG_NAME!r}; '
            'run rig_trex_blender.py first (or pass --blend).'
        )
    for ob in (mesh, rig):
        offset = max(
            abs(ob.matrix_world[i][j] - (1.0 if i == j else 0.0))
            for i in range(4) for j in range(4)
        )
        if offset > 1e-6:
            print(f'WARNING: {ob.name} has a non-identity object transform '
                  '(pose math assumes identity)')
    return mesh, rig


def strip_default_objects():
    """Remove Blender's factory-startup trio (Cube/Light/Camera) if present.

    They survive into scenes created with --factory-startup and pollute
    renders (the default Cube hides the legs)."""
    removed = []
    for name in ('Cube', 'Light', 'Camera'):
        ob = bpy.data.objects.get(name)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed.append(name)
    default_coll = bpy.data.collections.get('Collection')
    if default_coll is not None and not default_coll.objects:
        bpy.data.collections.remove(default_coll)
    return removed


def pick_render_engine(scene, prefer=('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE')):
    """Set the first engine name this Blender version accepts."""
    for candidate in tuple(prefer) + ('BLENDER_WORKBENCH',):
        try:
            scene.render.engine = candidate
            return candidate
        except TypeError:
            continue
    raise RuntimeError('No usable render engine found')


def wq(pbone, rotations):
    """Bone-local quaternion for a list of (world_axis, degrees) rotations.

    rotations = [('X', -40.0), ('Z', 12.0)] applies X first, then Z,
    both around world axes, then converts into the bone's rest space.
    Armature object transform must be identity (it is, by construction).
    """
    rest = pbone.bone.matrix_local.to_3x3()
    r_world = Matrix.Identity(3)
    for axis, degrees in rotations:
        vec = AXIS[axis] if isinstance(axis, str) else Vector(axis)
        r_world = Matrix.Rotation(math.radians(degrees), 3, vec) @ r_world
    return (rest.inverted() @ r_world @ rest).to_quaternion()


def wloc(pbone, world_vec):
    """Bone-local location for a desired world-space offset (parents at rest)."""
    rest = pbone.bone.matrix_local.to_3x3()
    return rest.inverted() @ Vector(world_vec)


def clear_pose(rig):
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def apply_pose(rig, rotations_by_bone):
    """rotations_by_bone: {bone_name: [(axis, degrees), ...]}"""
    for name, rotations in rotations_by_bone.items():
        pb = rig.pose.bones[name]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = wq(pb, rotations)


def angle_of(pbone):
    q = pbone.rotation_quaternion
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, abs(q.w)))))


def world_bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in objs:
        for corner in ob.bound_box:
            p = ob.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return lo, hi


def add_ground(size=9.0, name='DIAG_ground'):
    mesh = bpy.data.meshes.new(name)
    s = size
    mesh.from_pydata(
        [(-s, -s, 0.0), (s, -s, 0.0), (s, s, 0.0), (-s, s, 0.0)],
        [], [(0, 1, 2, 3)],
    )
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    mat = bpy.data.materials.new(name + ' material')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.30, 0.32, 0.30, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.9
    mat.diffuse_color = (0.30, 0.32, 0.30, 1.0)
    ob.data.materials.append(mat)
    return ob


def ensure_lighting(energy=3.0, world_rgb=(0.30, 0.32, 0.34)):
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new('DIAG_world')
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg is not None:
        bg.inputs[0].default_value = (*world_rgb, 1.0)
        bg.inputs[1].default_value = 1.0
    if not any(o.type == 'LIGHT' for o in scene.objects):
        data = bpy.data.lights.new('DIAG_sun', 'SUN')
        data.energy = energy
        sun = bpy.data.objects.new('DIAG_sun', data)
        scene.collection.objects.link(sun)
        sun.rotation_euler = (
            math.radians(52.0), math.radians(10.0), math.radians(30.0)
        )
    scene.render.film_transparent = False


def add_camera(name, direction, target, ortho_scale=None, lens=45.0, distance=10.0):
    data = bpy.data.cameras.new(name)
    if ortho_scale is not None:
        data.type = 'ORTHO'
        data.ortho_scale = ortho_scale
    else:
        data.type = 'PERSP'
        data.lens = lens
    cam = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(cam)
    d = Vector(direction).normalized()
    cam.location = Vector(target) + d * distance
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    return cam


def render_to(path, camera, resolution=(1200, 560), samples=12):
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = 'PNG'
    eevee = getattr(scene, 'eevee', None)
    if eevee is not None:
        try:
            eevee.taa_render_samples = samples
        except Exception:
            pass
    bpy.ops.render.render(write_still=True)


def camera_views(mesh, rig):
    """Standard diagnostic cameras framed on the rest mesh bounds."""
    lo, hi = world_bounds([mesh])
    center = (lo + hi) * 0.5
    length = (hi - lo).length
    target = (center.x, center.y, max(center.z, lo.z + (hi.z - lo.z) * 0.45))
    side = add_camera(
        'CAM_side', (1.0, 0.0, 0.12), target,
        ortho_scale=max((hi - lo).x, (hi - lo).y) * 1.15,
    )
    front = add_camera(
        'CAM_front', (0.0, -1.0, 0.07), target, ortho_scale=3.2,
    )
    threeq = add_camera(
        'CAM_three_quarter', (0.75, -0.75, 0.25), target,
        lens=45.0, distance=length * 1.15,
    )
    return {'side': side, 'front': front, 'three_quarter': threeq}
