#!/usr/bin/env python3
"""Cross-platform launcher for the T-Rex desktop viewer (mesh + rig + walk).

    python3 viewer.py                  # opens the viewer on the exported GLB
    python3 viewer.py --blend          # opens output/trex_editable.blend instead
    python3 viewer.py --glb PATH       # any other GLB
    python3 viewer.py --check          # headless validation, prints a report

The viewer itself is trex_viewer.py, a Blender GUI script. This launcher only
locates Blender (macOS / Linux / Windows) and starts it. Blender is found via,
in order: the BLENDER_BIN environment variable, ``blender`` on PATH, then the
standard install locations for the current OS.
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'trex_viewer.py'
DEFAULT_GLB = HERE / 'output' / 'trex_blender_rig.glb'
DEFAULT_BLEND = HERE / 'output' / 'trex_editable.blend'


def blender_candidates():
    """Yield candidate command lists, most likely first."""
    env = os.environ.get('BLENDER_BIN')
    if env:
        yield [env]
    which = shutil.which('blender')
    if which:
        yield [which]
    if sys.platform == 'darwin':
        for path in ('/Applications/Blender.app/Contents/MacOS/Blender',
                     str(Path.home() / 'Applications/Blender.app/Contents/MacOS/Blender')):
            if Path(path).is_file():
                yield [path]
    elif sys.platform.startswith('win'):
        patterns = [
            r'C:\Program Files\Blender Foundation\Blender*\blender.exe',
            r'C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe',
        ]
        program_files = os.environ.get('PROGRAMFILES')
        if program_files:
            patterns.insert(0, os.path.join(program_files, 'Blender Foundation',
                                            'Blender*', 'blender.exe'))
        for pattern in patterns:
            matches = sorted(glob.glob(pattern))
            if matches:
                yield [matches[-1]]
    else:
        for path in ('/snap/bin/blender',
                     '/var/lib/flatpak/exports/bin/org.blender.Blender'):
            if Path(path).is_file():
                yield [path]
        if shutil.which('flatpak'):
            yield ['flatpak', 'run', 'org.blender.Blender']


def find_blender():
    for candidate in blender_candidates():
        executable = candidate[0]
        if Path(executable).is_file() or shutil.which(executable):
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--glb', type=Path, default=None,
                        help='GLB to view (default: output/trex_blender_rig.glb)')
    parser.add_argument('--blend', action='store_true',
                        help='view output/trex_editable.blend instead of the GLB')
    parser.add_argument('--check', action='store_true',
                        help='run headless, validate, and exit')
    args = parser.parse_args()

    blender = find_blender()
    if blender is None:
        print('viewer: Blender not found. Install it (https://www.blender.org) '
              'or set BLENDER_BIN to its executable.', file=sys.stderr)
        return 1

    command = list(blender)
    if args.check:
        command.append('--background')
    command += ['--factory-startup', '--python', str(SCRIPT), '--']
    if args.blend:
        command += ['--blend', str(DEFAULT_BLEND)]
    else:
        command += ['--glb', str(args.glb.expanduser() if args.glb else DEFAULT_GLB)]
    if args.check:
        command.append('--check')

    print('viewer: launching:', ' '.join(command), flush=True)
    if args.check:
        return subprocess.call(command)
    subprocess.Popen(command, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    print('viewer: Blender window starting - Space plays, mouse orbits, '
          'N-panel "T-Rex Viewer" for toggles.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
