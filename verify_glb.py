#!/usr/bin/env python3
"""Verify the exported GLB without Blender (standard library only).

    python3 verify_glb.py [output/trex_blender_rig.glb]
"""

import json
import struct
import sys
from pathlib import Path

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def read_glb(path):
    data = Path(path).read_bytes()
    if len(data) < 12:
        raise ValueError('file too small to be a GLB')
    magic, version, length = struct.unpack_from('<III', data, 0)
    if magic != GLB_MAGIC:
        raise ValueError('not a GLB (bad magic)')
    if version != 2:
        raise ValueError(f'unsupported GLB version {version}')
    offset = 12
    chunks = []
    while offset < length:
        clen, ctype = struct.unpack_from('<II', data, offset)
        chunks.append((ctype, data[offset + 8:offset + 8 + clen]))
        offset += 8 + clen
    json_chunk = next((c for t, c in chunks if t == CHUNK_JSON), None)
    if json_chunk is None:
        raise ValueError('no JSON chunk found')
    has_bin = any(t == CHUNK_BIN for t, _ in chunks)
    return json.loads(json_chunk), has_bin, length


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                Path(__file__).resolve().parent / 'output' / 'trex_blender_rig.glb')
    gltf, has_bin, size = read_glb(path)

    meshes = gltf.get('meshes', [])
    skins = gltf.get('skins', [])
    images = gltf.get('images', [])
    animations = gltf.get('animations', [])
    primitives = sum(len(m.get('primitives', [])) for m in meshes)

    print(f'GLB: {path} ({size / 1e6:.2f} MB, bin chunk={"yes" if has_bin else "no"})')
    print(f'  nodes={len(gltf.get("nodes", []))} meshes={len(meshes)} '
          f'primitives={primitives} materials={len(gltf.get("materials", []))}')
    print(f'  skins={len(skins)} '
          f'joints={len(skins[0].get("joints", [])) if skins else 0} '
          f'images={len(images)}')

    durations = []
    for anim in animations:
        samplers = anim.get('samplers', [])
        duration = None
        if samplers:
            accessor = gltf['accessors'][samplers[0]['input']]
            duration = accessor.get('max', [None])[0]
        durations.append(duration)
        print(f'  animation "{anim.get("name")}": '
              f'channels={len(anim.get("channels", []))} '
              f'samplers={len(samplers)} duration={duration}s')

    expected_duration = 40 / 30.0  # CYCLE / FPS from animate_trex.py
    checks = [
        ('GLB has mesh data', len(meshes) == 1 and primitives == 7),
        ('one skin', len(skins) == 1),
        ('28 skeleton joints (27 deform + Root_CTRL)',
         bool(skins) and len(skins[0].get('joints', [])) == 28),
        ('6 texture images', len(images) == 6),
        ('animation "Walk" present', any(a.get('name') == 'Walk' for a in animations)),
        (f'duration ~{expected_duration:.2f}s (40f @ 30fps)',
         any(d is not None and abs(d - expected_duration) < 0.1 for d in durations)),
    ]
    failed = False
    for label, ok in checks:
        print(f'  [{"OK" if ok else "FAIL"}] {label}')
        failed |= not ok
    if failed:
        print('VERIFY: FAILED')
        return 1
    print('VERIFY: all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
