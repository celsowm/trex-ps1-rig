#!/usr/bin/env python3
"""Headless rig diagnostics for the PS1 T-Rex rig.

    blender -b --factory-startup --python diagnose_rig.py -- \
        [--blend output/trex_editable.blend] [--out-dir diagnostics/rig] [--no-render]

Prints:
  - mesh/material/texture status (packed images, point sampling)
  - full bone axis table in armature space (for planning animation channels)
  - which bones each test pose actually rotated

Renders orthographic side / front / three-quarter views of the rest pose and
a set of deliberately signed test poses. The +/- pairs exist to establish
which rotation SIGN tucks the knee, hock, and ankle correctly for this model;
those signs feed animate_trex.py.
"""

import argparse
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import lib_trex as lt

DEFAULT_BLEND = SCRIPT_DIR / 'output' / 'trex_editable.blend'
DEFAULT_OUT = SCRIPT_DIR / 'diagnostics' / 'rig'

POSES = [
    ('rest', {}),
    ('shinL_minus40', {'Shin.L': [('X', -40.0)]}),
    ('shinL_plus40', {'Shin.L': [('X', 40.0)]}),
    ('thighL_minus30', {'Thigh.L': [('X', -30.0)]}),
    ('thighL_plus30', {'Thigh.L': [('X', 30.0)]}),
    ('footL_minus25', {'Foot.L': [('X', -25.0)]}),
    ('toesL_plus35', {'Toes.L': [('X', 35.0)]}),
    ('tarsusL_plus20', {'Tarsus.L': [('X', 20.0)]}),
    ('head_minus20', {'Neck': [('X', -18.0)], 'Head': [('X', -16.0)]}),
    ('tail_yaw_plus', {'Tail_02': [('Z', 14.0)], 'Tail_04': [('Z', 16.0)]}),
    ('armL_minus30', {'UpperArm.L': [('X', -30.0)], 'ForeArm.L': [('X', -35.0)]}),
]

FRONT_EXTRA = {'rest', 'shinL_minus40', 'shinL_plus40'}
THREEQ_EXTRA = {'rest'}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--blend', type=Path, default=DEFAULT_BLEND)
    ap.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--no-render', action='store_true')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def report_scene(mesh, rig):
    print(f'DIAG: mesh verts={len(mesh.data.vertices)} '
          f'tris={len(mesh.data.polygons)} vgroups={len(mesh.vertex_groups)}')
    for mat in mesh.data.materials:
        image = None
        interpolation = None
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    image = node.image
                    interpolation = node.interpolation
        packed = bool(image.packed_file) if image else False
        print(f'DIAG: material {mat.name:22s} '
              f'image={image.name if image else "(none)":18s} '
              f'packed={packed} interp={interpolation or "-"}')
    deform = [b for b in rig.data.bones if b.use_deform]
    print(f'DIAG: bones total={len(rig.data.bones)} deform={len(deform)}')
    print('DIAG: bone axis table (armature space, unit vectors)')
    for b in rig.data.bones:
        m = b.matrix_local.to_3x3()
        x, z = m.col[0], m.col[2]
        print(f'  {b.name:14s} head=({b.head_local.x:+.3f},{b.head_local.y:+.3f},'
              f'{b.head_local.z:+.3f}) len={b.length:.3f} '
              f'X=({x.x:+.2f},{x.y:+.2f},{x.z:+.2f}) '
              f'Z=({z.x:+.2f},{z.y:+.2f},{z.z:+.2f})')


def run_renders(mesh, rig, out_dir):
    scene = bpy.context.scene
    engine = lt.pick_render_engine(scene)
    print(f'DIAG: render engine={engine}')
    lt.ensure_lighting()
    lt.add_ground()
    views = lt.camera_views(mesh, rig)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for i, (name, pose) in enumerate(POSES, start=1):
        lt.clear_pose(rig)
        lt.apply_pose(rig, pose)
        bpy.context.view_layer.update()
        moved = ', '.join(
            f'{n} {lt.angle_of(rig.pose.bones[n]):.1f}deg' for n in pose
        )
        print(f'DIAG: pose {name:16s} -> {moved if moved else "rest"}')
        summary.append((i, name, moved))
        tag = f'{i:02d}_{name}'
        lt.render_to(out_dir / f'{tag}_side.png', views['side'])
        if name in FRONT_EXTRA:
            lt.render_to(out_dir / f'{tag}_front.png', views['front'],
                         resolution=(640, 900))
        if name in THREEQ_EXTRA:
            lt.render_to(out_dir / f'{tag}_three_quarter.png',
                         views['three_quarter'], resolution=(1000, 720))
    lt.clear_pose(rig)
    print(f'DIAG: wrote {len(POSES)} pose renders to {out_dir}')


def main():
    args = parse_args()
    blend = args.blend.expanduser().resolve()
    if not blend.is_file():
        raise FileNotFoundError(
            f'{blend} not found. Run rig_trex_blender.py first.'
        )
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    removed = lt.strip_default_objects()
    if removed:
        print(f'DIAG: removed default objects: {", ".join(removed)}')
    mesh, rig = lt.find_objects()
    report_scene(mesh, rig)
    if not args.no_render:
        run_renders(mesh, rig, args.out_dir.expanduser().resolve())
    print('DIAG: done')


if __name__ == '__main__':
    main()
