#!/usr/bin/env python3
"""Desktop viewer for the rigged PS1 T-Rex: mesh + skeleton + Walk playback.

This script runs INSIDE the Blender GUI. The cross-platform launcher
``viewer.py`` finds Blender for you:

    python3 viewer.py                 # imports output/trex_blender_rig.glb
    python3 viewer.py --blend         # opens output/trex_editable.blend
    python3 viewer.py --check         # headless validation (no window)

Direct use:

    blender --factory-startup --python trex_viewer.py -- \
        [--glb PATH | --blend PATH] [--check]

What you get
- The GLB is imported into a clean scene, which proves the file is
  self-contained (mesh, skin, materials, Walk action).
- Material Preview shading with the skeleton drawn in front of the mesh
  (stick bones), so the rig is visible over the model.
- The Walk cycle plays in a loop.
- N-sidebar -> "T-Rex Viewer" tab: mesh / skeleton visibility, wireframe
  overlay, shading mode, Play/Pause and Reset View buttons.
- Standard Blender controls still apply: Space play/pause, MMB orbit,
  wheel zoom, numpad views.

``--check`` runs all of the above headless (no window) for validation:
it imports the file, verifies armature/action, registers the UI classes and
prints a report ending in ``VIEWER-CHECK OK``.
"""

import argparse
import sys
import warnings
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import lib_trex as lt

DEFAULT_GLB = SCRIPT_DIR / 'output' / 'trex_blender_rig.glb'
DEFAULT_BLEND = SCRIPT_DIR / 'output' / 'trex_editable.blend'
CATEGORY = 'T-Rex Viewer'
VIEW_DIR = Vector((1.15, -1.0, 0.55))   # camera side, distance fraction of size

state = {'mesh': None, 'rig': None, 'action': None}


# ----------------------------------------------------------------- arguments

def parse_args():
    ap = argparse.ArgumentParser(description='T-Rex desktop viewer')
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--glb', type=Path, default=None,
                       help='GLB to import (default: output/trex_blender_rig.glb)')
    group.add_argument('--blend', type=Path, default=None,
                       help='.blend to open instead (output/trex_editable.blend)')
    ap.add_argument('--check', action='store_true',
                    help='headless validation, no window')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


# ------------------------------------------------------------------- loading

def load_target(args):
    """Import the GLB (default) or open the .blend; returns the path used."""
    lt.strip_default_objects()
    bpy.context.scene.render.fps = 30
    bpy.context.scene.render.fps_base = 1.0
    if args.blend is not None:
        path = args.blend.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f'{path} not found; run ./run_all.sh first')
        bpy.ops.wm.open_mainfile(filepath=str(path))
        lt.strip_default_objects()
    else:
        path = (args.glb or DEFAULT_GLB).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f'{path} not found; run ./run_all.sh first')
        bpy.ops.import_scene.gltf(filepath=str(path))
    return path


def pick_objects():
    """Find the armature and mesh, make sure the Walk action is assigned."""
    rig = next((ob for ob in bpy.context.scene.objects if ob.type == 'ARMATURE'), None)
    mesh = next((ob for ob in bpy.context.scene.objects if ob.type == 'MESH'), None)
    if rig is None or mesh is None:
        raise RuntimeError('viewer: no armature/mesh found in the file')
    state['mesh'], state['rig'] = mesh, rig

    rig.animation_data_create()
    action = rig.animation_data.action
    if action is None and bpy.data.actions:
        action = bpy.data.actions.get('Walk') or bpy.data.actions[0]
        try:
            rig.animation_data.action = action
        except Exception as exc:
            print(f'VIEWER: could not assign action: {exc}')
    state['action'] = action


def setup_scene(respect_scene_range=False):
    """Viewer-friendly scene: fps/range from the action, rig-friendly display."""
    scene = bpy.context.scene
    rig, mesh, action = state['rig'], state['mesh'], state['action']

    rig.data.display_type = 'STICK'
    rig.show_in_front = True
    rig.hide_viewport = False
    mesh.hide_viewport = False

    if respect_scene_range and scene.frame_end > scene.frame_start:
        pass  # e.g. the saved .blend already loops 0..40 (helper keys go beyond)
    elif action is not None:
        start, end = (int(round(v)) for v in action.frame_range)
        scene.frame_start, scene.frame_end = start, max(end, start + 1)
    else:
        scene.frame_start, scene.frame_end = 0, 40
    scene.frame_current = scene.frame_start

    world = bpy.data.worlds.get('T-Rex Viewer') or bpy.data.worlds.new('T-Rex Viewer')
    with warnings.catch_warnings():
        # World.use_nodes is deprecated in Blender 5.x (removed in 6.0).
        warnings.simplefilter('ignore', DeprecationWarning)
        try:
            world.use_nodes = True
        except AttributeError:
            pass
    node_tree = getattr(world, 'node_tree', None)
    background = node_tree.nodes.get('Background') if node_tree is not None else None
    if background is not None:
        background.inputs[0].default_value = (0.045, 0.05, 0.06, 1.0)
    scene.world = world
    try:
        lt.pick_render_engine(scene)
    except Exception as exc:
        print(f'VIEWER: engine setup skipped: {exc}')


# ------------------------------------------------------------------ viewport

def view3d_spaces():
    """Every VIEW_3D space of every open window (empty when running headless)."""
    spaces = []
    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        return spaces
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        spaces.append(space)
    return spaces


def model_bounds():
    mesh = state['mesh']
    if mesh is None or not mesh.data.vertices:
        return Vector((0, 0, 0)), 6.0
    corners = [mesh.matrix_world @ Vector(corner) for corner in mesh.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners),
                 min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners),
                 max(c.z for c in corners)))
    center = (lo + hi) / 2.0
    distance = max((hi - lo).length * 0.85, 2.0)
    return center, distance


def apply_view():
    """Three-quarter framing plus the current shading settings."""
    scene = bpy.context.scene
    center, distance = model_bounds()
    direction = VIEW_DIR.normalized()
    rotation = (-direction).to_track_quat('-Z', 'Y')
    for space in view3d_spaces():
        region = space.region_3d
        region.view_perspective = 'PERSP'
        region.view_location = center
        region.view_rotation = rotation
        region.view_distance = distance
        space.shading.type = scene.trex_shading
        space.shading.show_wireframes = scene.trex_wireframe
        space.overlay.show_overlays = True


# ------------------------------------------------------------------- UI panel

def update_visibility(self, context):
    mesh, rig = state['mesh'], state['rig']
    if mesh is not None:
        mesh.hide_viewport = not self.trex_show_mesh
    if rig is not None:
        rig.hide_viewport = not self.trex_show_rig


def update_wireframe(self, context):
    for space in view3d_spaces():
        space.shading.show_wireframes = self.trex_wireframe


def update_shading(self, context):
    for space in view3d_spaces():
        space.shading.type = self.trex_shading


class TREX_OT_play(bpy.types.Operator):
    bl_idname = 'trex_viewer.play'
    bl_label = 'Play / Pause'
    bl_description = 'Toggle timeline playback of the Walk cycle'

    def execute(self, context):
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


class TREX_OT_reset_view(bpy.types.Operator):
    bl_idname = 'trex_viewer.reset_view'
    bl_label = 'Reset View'
    bl_description = 'Frame the model from a three-quarter view'

    def execute(self, context):
        apply_view()
        return {'FINISHED'}


class TREX_PT_viewer(bpy.types.Panel):
    bl_label = 'T-Rex Viewer'
    bl_idname = 'TREX_PT_viewer'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY

    def draw(self, context):
        scene = context.scene
        column = self.layout.column(align=True)
        column.prop(scene, 'trex_show_mesh', toggle=True)
        column.prop(scene, 'trex_show_rig', toggle=True)
        column.prop(scene, 'trex_wireframe', toggle=True)
        self.layout.prop(scene, 'trex_shading')
        row = self.layout.row(align=True)
        row.operator('trex_viewer.play', icon='PLAY')
        row.operator('trex_viewer.reset_view', icon='HOME')


UI_CLASSES = (TREX_OT_play, TREX_OT_reset_view, TREX_PT_viewer)


def register_ui():
    for cls in UI_CLASSES:
        if not hasattr(bpy.types, cls.bl_idname):
            try:
                bpy.utils.register_class(cls)
            except Exception as exc:
                print(f'VIEWER: could not register {cls.__name__}: {exc}')
    scene_type = bpy.types.Scene
    if not hasattr(scene_type, 'trex_show_mesh'):
        scene_type.trex_show_mesh = bpy.props.BoolProperty(
            name='Mesh', description='Show the skinned mesh',
            default=True, update=update_visibility)
        scene_type.trex_show_rig = bpy.props.BoolProperty(
            name='Skeleton', description='Show the armature bones in front',
            default=True, update=update_visibility)
        scene_type.trex_wireframe = bpy.props.BoolProperty(
            name='Wireframe overlay', description='Draw the mesh wireframe',
            default=False, update=update_wireframe)
        scene_type.trex_shading = bpy.props.EnumProperty(
            name='Shading', description='Viewport shading mode', default='MATERIAL',
            update=update_shading,
            items=[('SOLID', 'Solid', 'Fast silhouette view, best for the rig'),
                   ('MATERIAL', 'Material Preview', 'Textured, lit preview'),
                   ('RENDERED', 'Rendered', 'Full render with lights'),
                   ('WIREFRAME', 'Wireframe', 'Edges only')])


# ------------------------------------------------------------------- startup

def _deferred_setup(attempt=1):
    """Applied once the GUI window exists: framing and autoplay."""
    try:
        apply_view()
        bpy.ops.screen.animation_play()
        print('VIEWER: window ready - Space play/pause, MMB orbit, '
              'N-panel "T-Rex Viewer" for controls')
    except Exception as exc:
        print(f'VIEWER: deferred setup attempt {attempt}: {exc}')
        if attempt < 3:
            bpy.app.timers.register(
                lambda: _deferred_setup(attempt + 1), first_interval=0.8)
    return None


def report(path):
    rig, mesh, action = state['rig'], state['mesh'], state['action']
    deform = sum(1 for bone in rig.data.bones if bone.use_deform)
    print(f'VIEWER: loaded {path}')
    print(f'VIEWER: mesh "{mesh.name}" verts={len(mesh.data.vertices)} '
          f'polys={len(mesh.data.polygons)}')
    print(f'VIEWER: rig "{rig.name}" bones={len(rig.data.bones)} deform={deform}')
    actions = ', '.join(
        f'{a.name}[{int(a.frame_range[0])}-{int(a.frame_range[1])}]'
        for a in bpy.data.actions) or 'none'
    print(f'VIEWER: actions: {actions}')
    scene = bpy.context.scene
    print(f'VIEWER: fps={scene.render.fps} '
          f'range={scene.frame_start}-{scene.frame_end} '
          f'playing="{action.name if action else "nothing"}"')


def main():
    args = parse_args()
    path = load_target(args)
    pick_objects()
    setup_scene(respect_scene_range=args.blend is not None)
    register_ui()
    report(path)
    if args.check:
        print('VIEWER-CHECK OK')
        return
    bpy.app.timers.register(_deferred_setup, first_interval=0.6)


if __name__ == '__main__':
    main()
