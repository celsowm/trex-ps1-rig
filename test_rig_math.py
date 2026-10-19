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
           'down_tooth_tips','vertex_weights','parse_obj','jaw_shell_shares']
body=[node for node in mod.body
      if (isinstance(node,ast.FunctionDef) and node.name in functions)
      or (isinstance(node,ast.Assign)
          and getattr(node.targets[0],'id','') in
          ('TOE_LANES','JAW_MIN_Z','JAW_MAX_TOP','JAW_TIP_BAND','THROAT_BAND',
           'TEETH_TIP_MARGIN','TEETH_TIP_MIN','JAW_SHELL_SEAM','JAW_SHELL_BAND',
           'JAW_SHELL_CORNER'))]
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
# the mouth line must stay off the jaw bones - including the upper tooth
# row, whose fangs hang into the jaw's box but must ride the skull or both
# rows would move together and the closed mouth would never open. The
# throat skin under the jaw blends into the jaw toward the chin so an open
# mouth shows no gap.
jaw,throat=env['jaw_vertex_sets'](vertices,faces)
assert len(jaw)==158, f'Jaw island set changed: {len(jaw)} vertices (expected 158)'
assert len(throat)==30, f'Throat island changed: {len(throat)} vertices (expected 30)'
for i in jaw:
    w=env['jaw_weights'](vertices[i][2])
    assert set(w)<={'Jaw','JawTip'}, f'Jaw vertex {i} leaks onto {sorted(w)}'
    assert abs(sum(w.values())-1)<1e-5
adjacency=defaultdict(set)
for face in faces:
    for a,b in zip(face,face[1:]+face[:1]):
        adjacency[a].add(b)
        adjacency[b].add(a)
teeth=[]
for island in env['mesh_islands'](len(vertices),faces):
    if len(env['down_tooth_tips'](island,vertices,adjacency))>=env['TEETH_TIP_MIN']:
        ys=[vertices[i][1] for i in island]
        zs=[vertices[i][2] for i in island]
        if min(zs)>=15.5 and min(ys)<=21.2:
            teeth.append(island)
assert len(teeth)==1 and len(teeth[0])==83, \
    f'Upper tooth row island changed: {[len(t) for t in teeth]} (expected one with 83)'
assert not (set(teeth[0])&jaw), 'Upper tooth row must stay off the jaw bones'
upper=[]
for island in env['mesh_islands'](len(vertices),faces):
    ys=[vertices[i][1] for i in island]
    zs=[vertices[i][2] for i in island]
    if min(zs)>=15.5 and min(ys)>21.2:
        upper.extend(island)
assert upper and not (set(upper)&jaw), 'Upper mouth pieces must stay off the jaw bones'
front=max(throat,key=lambda i: vertices[i][2])
assert env['smoothstep'](18.5,23.0,vertices[front][2])>0.9, 'Throat front must follow the jaw'

# The outer head shell closes the mouth seamlessly, so the chin and the
# lower-lip skin below the tooth line are not islands of their own: they
# must be found as a blended skin region that rides the jaw, or the closed
# chin stays on the skull while the thin inner jaw drops away.
shell=env['jaw_shell_shares'](vertices,faces,jaw,throat)
assert len(shell)==76, f'Jaw shell changed: {len(shell)} vertices (expected 76)'
assert not (set(shell)&(set(jaw)|set(throat))), 'Jaw shell must not overlap jaw/throat'
for i,share in shell.items():
    x,y,z=vertices[i]
    assert 0.0<share<=1.0, f'Shell vertex {i} share {share} out of range'
    assert 18.5<=y<=21.6 and z>=17.4, f'Shell vertex {i} escapes the mouth band'
chin=min((i for i in shell if vertices[i][2]>=21.4),key=lambda i: vertices[i][1])
assert shell[chin]>0.99, 'Chin bottom must ride the jaw fully'
mouth=env['blend_weights'](env['vertex_weights'](vertices[chin]),
                           env['jaw_weights'](vertices[chin][2]),
                           shell[chin])
assert abs(sum(mouth.values())-1.0)<1e-5 and 'JawTip' in mouth, \
    'Blended chin weights must land on Jaw/JawTip'
print(f'PASS: lower jaw {len(jaw)} vertices on Jaw/JawTip ({len(upper)} upper-mouth vertices kept off it, '
      f'upper tooth row {len(teeth[0])} vertices on Head), '
      f'throat {len(throat)} vertices blend toward the chin, '
      f'chin/lip shell {len(shell)} vertices blend onto the jaw')

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
