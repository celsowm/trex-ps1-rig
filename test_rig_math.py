#!/usr/bin/env python3
"""Basic source+weights preflight without Blender installed (Python standard library)."""
from pathlib import Path
from collections import Counter, defaultdict
import ast, math

base=Path(__file__).resolve().parent
script=base/'rig_trex_blender.py'
mod=ast.parse(script.read_text(encoding='utf8'))
functions=['smoothstep','axial_weights','limb_bands','vertex_weights','parse_obj']
body=[node for node in mod.body if isinstance(node,ast.FunctionDef) and node.name in functions]
env={'math':math,'defaultdict':defaultdict}
exec(compile(ast.Module(body=body,type_ignores=[]),str(script),'exec'),env)
vertices,faces,face_uv,face_mats=env['parse_obj'](base/'source'/'dino'/'dino.obj')
assert len(vertices)==2332, f'Unexpected original vertex count: {len(vertices)}'
assert len(faces)==2724, f'Unexpected original face count: {len(faces)}'
assert len(face_uv)==len(faces)==len(face_mats)
assert len(set(face_mats))==7
counts=Counter()
for v in vertices:
    w=env['vertex_weights'](v)
    assert 1<=len(w)<=4
    assert abs(sum(w.values())-1)<1e-5
    assert all(math.isfinite(x) and x>=0.0 for x in w.values())
    for name,weight in w.items():
        if weight>0.0001: counts[name]+=1
for side in ('L','R'):
    for seg in ['Thigh','Shin','Tarsus','Foot','Toes']:
        assert counts[f'{seg}.{side}']>5, f'Missing useful weights: {seg}.{side}'
print(f'PASS: {len(vertices)} original vertices, {len(faces)} triangles, {len(counts)} influenced bone groups')
print('Right/left leg vertex counts:')
for name in ('Thigh','Shin','Tarsus','Foot','Toes'):
    print(f'  {name}: left {counts[name+".L"]}, right {counts[name+".R"]}')
print('NOTE: numeric tests cannot validate deformation quality in Blender.')
