#!/usr/bin/env python3
"""Basic source+weights preflight without Blender installed (Python standard library)."""
from pathlib import Path
from collections import Counter, defaultdict
import ast, math

base=Path(__file__).resolve().parent
script=base/'rig_trex_blender.py'
mod=ast.parse(script.read_text(encoding='utf8'))
functions=['smoothstep','axial_weights','limb_bands','split_foot_toes',
           'mesh_islands','jaw_vertex_sets','jaw_weights','blend_weights',
           'vertex_weights','parse_obj']
body=[node for node in mod.body
      if (isinstance(node,ast.FunctionDef) and node.name in functions)
      or (isinstance(node,ast.Assign)
          and getattr(node.targets[0],'id','') in
          ('TOE_LANES','JAW_MIN_Z','JAW_MAX_TOP','JAW_TIP_BAND','THROAT_BAND'))]
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
    for seg in ['Thigh','Shin','Tarsus','Foot','Toe1','Toe2','Toe3']:
        assert counts[f'{seg}.{side}']>5, f'Missing useful weights: {seg}.{side}'
print(f'PASS: {len(vertices)} original vertices, {len(faces)} triangles, {len(counts)} influenced bone groups')
print('Right/left leg vertex counts:')
for name in ('Thigh','Shin','Tarsus','Foot','Toe1','Toe2','Toe3'):
    print(f'  {name}: left {counts[name+".L"]}, right {counts[name+".R"]}')

# Lower jaw: the mouth is a topology split in the source mesh, so the jaw
# islands must be found, take nothing but Jaw/JawTip, and the skull side of
# the mouth line must stay off the jaw bones. The throat skin under the jaw
# blends into the jaw toward the chin so an open mouth shows no gap.
jaw,throat=env['jaw_vertex_sets'](vertices,faces)
assert len(jaw)==241, f'Jaw island set changed: {len(jaw)} vertices (expected 241)'
assert len(throat)==30, f'Throat island changed: {len(throat)} vertices (expected 30)'
for i in jaw:
    w=env['jaw_weights'](vertices[i][2])
    assert set(w)<={'Jaw','JawTip'}, f'Jaw vertex {i} leaks onto {sorted(w)}'
    assert abs(sum(w.values())-1)<1e-5
upper=[]
for island in env['mesh_islands'](len(vertices),faces):
    ys=[vertices[i][1] for i in island]
    zs=[vertices[i][2] for i in island]
    if min(zs)>=15.5 and min(ys)>21.2:
        upper.extend(island)
assert upper and not (set(upper)&jaw), 'Upper mouth pieces must stay off the jaw bones'
front=max(throat,key=lambda i: vertices[i][2])
assert env['smoothstep'](18.5,23.0,vertices[front][2])>0.9, 'Throat front must follow the jaw'
print(f'PASS: lower jaw {len(jaw)} vertices on Jaw/JawTip ({len(upper)} upper-mouth vertices kept off it), '
      f'throat {len(throat)} vertices blend toward the chin')

# Walk-cycle sanity without Blender: the foot-target table must stay above
# ground, start/end identical for the loop, and cover one full stride.
anim=ast.parse((base/'animate_trex.py').read_text(encoding='utf8'))
tables=[node for node in anim.body if isinstance(node,ast.Assign)
        and getattr(node.targets[0],'id','')=='FOOT_TARGETS']
assert tables, 'FOOT_TARGETS not found in animate_trex.py'
targets=ast.literal_eval(tables[0].value)
assert len(targets)==9, f'Expected 9 foot-target rows, got {len(targets)}'
assert targets[0]==targets[-1], 'FOOT_TARGETS must loop (first row == last row)'
assert all(row[1]>=0.005 for row in targets), 'A claw target would sink into the ground'
assert min(row[0] for row in targets)<=-0.45, 'No real forward reach in the stride'
print(f'PASS: FOOT_TARGETS has {len(targets)} rows, loops, claws stay >= '
      f'{min(row[1] for row in targets):.3f} m above ground')
print('NOTE: numeric tests cannot validate deformation quality in Blender.')
