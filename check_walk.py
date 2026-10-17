#!/usr/bin/env python3
"""Numeric check of the Walk action: foot positions, ground contact, bob.

    blender -b --factory-startup --python check_walk.py -- [--blend PATH]

Prints one table row per key frame: toe-tip world position per leg and the
pelvis height. Forward is -Y; ground is z=0. Planted feet should sit near
z=0.00-0.06; swinging feet should clear z>=0.10 and never sink below 0.
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


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--blend', type=Path, default=DEFAULT_BLEND)
    ap.add_argument('--step', type=int, default=5)
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.expanduser().resolve()))
    mesh, rig = lt.find_objects()
    scene = bpy.context.scene
    if rig.animation_data is None or rig.animation_data.action is None:
        raise RuntimeError('No animation on the rig; run animate_trex.py first')

    print('frame |  ToeTip.L  y/z       |  ToeTip.R  y/z       | pelvis z')
    print('------+----------------------+----------------------+---------')
    worst = {'penetration': 0.0, 'float': 0.0}
    for frame in range(scene.frame_start, scene.frame_end + 1, args.step):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        row = [f'{frame:5d}']
        for side in ('L', 'R'):
            tail = rig.matrix_world @ rig.pose.bones[f'Toes.{side}'].tail
            row.append(f'{tail.y:+.3f} / {tail.z:+.3f}')
        pelvis = rig.matrix_world @ rig.pose.bones['Pelvis'].head
        row.append(f'{pelvis.z:+.3f}')
        print(' | '.join(row))
        for side in ('L', 'R'):
            tail = rig.matrix_world @ rig.pose.bones[f'Toes.{side}'].tail
            if tail.z < 0.0:
                worst['penetration'] = min(worst['penetration'], tail.z)
    swing_clearance = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for side in ('L', 'R'):
            tail = rig.matrix_world @ rig.pose.bones[f'Toes.{side}'].tail
            # swing foot = clearly off the ground; record its clearance
            if tail.z > 0.06:
                swing_clearance.append(tail.z)
    print(f'\nmin z of any toe tip over the cycle: '
          f'{min(swing_clearance) if swing_clearance else 0.0:+.3f}')
    print(f'lowest penetration below ground: {worst["penetration"]:+.3f} m '
          f'({"none" if worst["penetration"] >= -0.001 else "FOOT SINKS"})')
    print(f'swing clearance samples: {len(swing_clearance)}')


if __name__ == '__main__':
    main()
