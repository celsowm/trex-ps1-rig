#!/usr/bin/env python3
"""T-Rex native viewer: mesh + rig + Walk playback from the exported GLB.

Our own desktop viewer (no Blender, no browser): a GLB parser, a skinning
renderer and a pyglet window, all written in this repository.

    python3 viewer.py                     # open the interactive window
    python3 viewer.py --check             # headless validation, no window
    python3 viewer.py --screenshot out.png --time 0.667
                                          # render one frame to a PNG

Window controls:
    Space play/pause     Left/Right scrub one frame
    M mesh   R rig   W wireframe   T bones on top   G grid
    L cycle lighting     F reset view
    Mouse: drag to orbit, shift-drag (or right-drag) to pan, wheel to zoom

Requirements (see viewer/requirements.txt):
    python3 -m pip install -r viewer/requirements.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_GLB = ROOT / 'output' / 'trex_blender_rig.glb'
CHECK_JOINTS = ('Root_CTRL', 'Pelvis', 'Head', 'Tail_End',
                'Toe1.L', 'Toe2.L', 'Toe3.L', 'Toe1.R', 'Toe2.R', 'Toe3.R')
EXPECTED_JOINT_COUNT = 32
EXPECTED_DURATION = 40 / 30  # 40-frame cycle at 30 fps


def run_check(path):
    """Parse the GLB headlessly and validate the things the viewer relies on."""
    from viewer.scene import TrexScene

    scene = TrexScene(path)
    primitive_count = len(scene.primitives)
    joint_count = len(scene.joints)
    image_count = len(scene.gltf.get('images', []))
    print(f'viewer: parsed {path} ({path.stat().st_size / 1e6:.2f} MB)')
    print(f'  nodes={scene.node_count} primitives={primitive_count} '
          f'joints={joint_count} images={image_count} '
          f'materials={len(scene.materials)}')
    print(f'  animation "Walk": duration={scene.duration:.4f}s '
          f'channels={len(scene.channels)}')

    checks = [
        ('7 triangle primitives', primitive_count == 7),
        (f'{EXPECTED_JOINT_COUNT} skeleton joints',
         joint_count == EXPECTED_JOINT_COUNT),
        ('6 texture images', image_count == 6),
        ('animation "Walk" present',
         'Walk' in scene.animation_names),
        (f'duration ~{EXPECTED_DURATION:.3f}s (40 frames @ 30 fps)',
         abs(scene.duration - EXPECTED_DURATION) < 0.05),
        ('every vertex is skinned',
         all(primitive['joints'] is not None and primitive['weights'] is not None
             for primitive in scene.primitives)),
    ]
    failed = False
    for label, ok in checks:
        print(f'  [{"OK" if ok else "FAIL"}] {label}')
        failed = failed or not ok

    print('  joint world positions (glTF Y-up, meters; Blender frame -> t = f/30):')
    for frame in (0, 10, 20, 30):
        world = scene.world_matrices(frame / 30.0)
        parts = []
        for name in CHECK_JOINTS:
            index = scene.joint_index(name)
            position = world[scene.joints[index]][:3, 3]
            parts.append(f'{name}=({position[0]:+.3f},{position[1]:+.3f},'
                         f'{position[2]:+.3f})')
        print(f'  f{frame:02d}: ' + ' '.join(parts))

    if failed:
        print('VIEWER-CHECK FAILED')
        return 1
    print('VIEWER-CHECK OK')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Native desktop viewer for the rigged T-Rex GLB.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Window controls:')[1].split('Requirements')[0].strip())
    parser.add_argument('--glb', type=Path, default=None,
                        help='GLB to open (default: output/trex_blender_rig.glb)')
    parser.add_argument('--check', action='store_true',
                        help='headless validation of the GLB, no window')
    parser.add_argument('--screenshot', type=Path, default=None, metavar='PNG',
                        help='render one frame to PNG and exit')
    parser.add_argument('--time', type=float, default=0.0,
                        help='animation time for --screenshot, in seconds')
    parser.add_argument('--size', default='1600x1000',
                        help='window/screenshot size WxH (default: 1600x1000)')
    args = parser.parse_args(argv)

    path = (args.glb or DEFAULT_GLB).expanduser().resolve()
    if not path.is_file():
        print(f'viewer: {path} not found; run ./run_all.sh to build it',
              file=sys.stderr)
        return 1

    try:
        from viewer.glb import GlbError
    except ImportError:
        print('viewer: needs numpy. Install with:\n'
              '  python3 -m pip install -r viewer/requirements.txt',
              file=sys.stderr)
        return 1

    if args.check:
        try:
            return run_check(path)
        except GlbError as error:
            print(f'viewer: cannot read {path}: {error}', file=sys.stderr)
            return 1

    try:
        import numpy  # noqa: F401
        import pyglet  # noqa: F401
    except ImportError:
        print('viewer: needs pyglet and numpy. Install with:\n'
              '  python3 -m pip install -r viewer/requirements.txt',
              file=sys.stderr)
        return 1

    try:
        width, height = (int(value) for value in args.size.lower().split('x'))
    except ValueError:
        print(f'viewer: bad --size {args.size!r}; expected WxH, e.g. 1600x1000',
              file=sys.stderr)
        return 1

    if args.screenshot is not None:
        from viewer.app import screenshot
        out_path = args.screenshot.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            screenshot(path, out_path, args.time, width, height)
        except GlbError as error:
            print(f'viewer: cannot read {path}: {error}', file=sys.stderr)
            return 1
        print(f'viewer: screenshot saved to {out_path}')
        return 0

    from viewer.app import run
    try:
        run(path, width, height)
    except GlbError as error:
        print(f'viewer: cannot read {path}: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
