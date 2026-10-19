#!/usr/bin/env python3
"""PS1 Developer's Demo CD T-Rex: EDITABLE Blender rig, version 1.

This is not the old glTF joint-matrix rig. Blender builds the armature,
vertex groups, modifier, weight-paintable geometry and exports itself.

Blender 3.6 LTS / 4.x (desktop or -b):
    blender -b --python rig_trex_blender.py -- --export-glb

Can also run inside Blender's Scripting editor (new, empty file recommended).
All file paths are resolved relative to this script unless overridden.
"""

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
DEFAULT_OBJ = SCRIPT_DIR / 'source' / 'dino' / 'dino.obj'
DEFAULT_OUT = SCRIPT_DIR / 'output'
SCALE = 0.10
MESH_NAME = 'PS1_TREX_Original_Geometry'
RIG_NAME = 'TREX_EDITABLE_ARMATURE'
COLLECTION_NAME = 'T-Rex PS1 | Editable Rig'

# Source model: X=left/right, Y=up, Z=forward (head faces +Z).
# Blender:      X=left/right, Y=-source Z, Z=source Y.
# Positions are in ORIGINAL OBJ units, not Blender units.
# Check diagnostics/leg_joint_overlay.png before adjusting leg pivots.
# The knee is FORWARD (+source Z), hock is BEHIND (-source Z).
# Change values here, rerun. Bones are also movable in Armature Edit Mode.
JOINTS = {
    'Root':       ( 0.00, 15.40, -4.10),
    'Pelvis':     ( 0.00, 15.30, -3.60),
    'Spine':      ( 0.00, 18.20,  2.00),
    'Chest':      ( 0.00, 20.25,  8.10),
    'Neck':       ( 0.00, 21.30, 13.15),
    'Head':       ( 0.00, 22.25, 17.40),
    # The mouth is a topological split in the source mesh: the lower jaw is a
    # separate island set (hinge plates, lips, chin, snout cap). The hinge
    # sits at the back-top of the hinge plates, the tip joint at the chin,
    # so Jaw/JawTip can open the mouth without touching the skull.
    'Jaw':        ( 0.00, 22.70, 16.60),
    'JawMid':     ( 0.00, 21.15, 20.80),
    'Tail01':     ( 0.00, 17.00, -11.50),
    'Tail02':     ( 0.00, 17.40, -19.40),
    'Tail03':     ( 0.00, 16.80, -27.30),
    'Tail04':     ( 0.00, 16.35, -34.20),
    'TailTip':    ( 0.00, 15.95, -38.15),
    'HeadTip':    ( 0.00, 21.75,  24.25),
    'JawTip':     ( 0.00, 20.70,  24.60),
}
for _side, _x in [('L',1.0), ('R',-1.0)]:
    JOINTS.update({
        f'Hip.{_side}':      (3.05 * _x, 14.30, -3.20),
        f'Knee.{_side}':     (3.45 * _x,  9.80,  2.30),
        f'Hock.{_side}':     (3.00 * _x,  3.75, -2.50),
        f'Ankle.{_side}':    (3.25 * _x,  1.80, -2.70),
        f'Ball.{_side}':     (3.55 * _x,  0.50,  1.10),
        # Three toes per foot, measured on the source geometry: the inner
        # (medial) toe is the longest, the outer one is short and set back.
        # Each toe gets its own bone so no claw has to shear between the
        # foot and a shared "Toes" bone.
        f'Toe1.{_side}':     (1.05 * _x,  0.40,  1.40),
        f'Toe1Tip.{_side}':  (1.05 * _x,  0.03,  3.23),
        f'Toe2.{_side}':     (3.05 * _x,  0.40,  1.05),
        f'Toe2Tip.{_side}':  (3.39 * _x,  0.02,  2.83),
        f'Toe3.{_side}':     (5.05 * _x,  0.40,  0.80),
        f'Toe3Tip.{_side}':  (5.69 * _x,  0.02,  2.27),
        f'Shoulder.{_side}':(3.30 * _x, 18.40,  9.65),
        f'Elbow.{_side}':   (4.05 * _x, 14.65, 10.15),
        f'Wrist.{_side}':   (4.35 * _x, 11.70, 10.90),
        f'HandTip.{_side}': (4.45 * _x, 10.95, 11.30),
    })

# (name, parent bone, head joint, tail joint, deform)
BONE_DEF = [
    ('Root_CTRL',None,      'Root','Pelvis',False),
    ('Pelvis',   'Root_CTRL','Pelvis','Spine',True),
    ('Spine',    'Pelvis',  'Spine','Chest',True),
    ('Chest',    'Spine',   'Chest','Neck',True),
    ('Neck',     'Chest',   'Neck','Head',True),
    ('Head',     'Neck',    'Head','HeadTip',True),
    ('Jaw',      'Head',    'Jaw','JawMid',True),
    ('JawTip',   'Jaw',     'JawMid','JawTip',True),
    ('Tail_01',  'Pelvis',  'Pelvis','Tail01',True),
    ('Tail_02',  'Tail_01', 'Tail01','Tail02',True),
    ('Tail_03',  'Tail_02', 'Tail02','Tail03',True),
    ('Tail_04',  'Tail_03', 'Tail03','Tail04',True),
    ('Tail_End', 'Tail_04', 'Tail04','TailTip',True),
]
for side in ('L','R'):
    BONE_DEF += [
        # This chain is projected onto the REAL foot/leg silhouette.
        (f'Thigh.{side}',   'Pelvis',             f'Hip.{side}',   f'Knee.{side}', True),
        (f'Shin.{side}',    f'Thigh.{side}',      f'Knee.{side}',  f'Hock.{side}', True),
        (f'Tarsus.{side}',  f'Shin.{side}',       f'Hock.{side}',  f'Ankle.{side}',True),
        (f'Foot.{side}',    f'Tarsus.{side}',     f'Ankle.{side}', f'Ball.{side}', True),
        (f'Toe1.{side}',    f'Foot.{side}',       f'Toe1.{side}',  f'Toe1Tip.{side}', True),
        (f'Toe2.{side}',    f'Foot.{side}',       f'Toe2.{side}',  f'Toe2Tip.{side}', True),
        (f'Toe3.{side}',    f'Foot.{side}',       f'Toe3.{side}',  f'Toe3Tip.{side}', True),
        (f'UpperArm.{side}', 'Chest',            f'Shoulder.{side}',f'Elbow.{side}',True),
        (f'ForeArm.{side}', f'UpperArm.{side}',  f'Elbow.{side}', f'Wrist.{side}',True),
        (f'Hand.{side}',    f'ForeArm.{side}',   f'Wrist.{side}', f'HandTip.{side}',True),
    ]


def src_to_blender(p):
    x, y, z = p
    return (SCALE * x, -SCALE * z, SCALE * y)


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t*t*(3.0-2.0*t)


def axial_weights(z):
    # ONLY neighboring spinal/tail controls can influence a vertex.
    controls = [
        ('Tail_End', -37.3), ('Tail_04', -32.0),
        ('Tail_03', -25.5), ('Tail_02', -17.0),
        ('Tail_01', -10.0), ('Pelvis', -3.7),
        ('Spine', 2.0), ('Chest', 8.5),
        ('Neck', 13.5), ('Head', 18.6),
    ]
    if z <= controls[0][1]:
        return {controls[0][0]: 1.0}
    if z >= controls[-1][1]:
        return {controls[-1][0]: 1.0}
    for (a, az), (b, bz) in zip(controls, controls[1:]):
        if az <= z <= bz:
            t = smoothstep(az, bz, z)
            return {a: 1.0-t, b: t}
    raise RuntimeError('Invalid axial interval')


def limb_bands(y, z, side, is_arm=False):
    # Each segment owns most of its mesh span, with blending only near joints.
    # Do not weight the thigh to the KNEE bone as the older rig did.
    if is_arm:
        a = smoothstep(14.0, 16.8, y)
        b = (1.0-a)*smoothstep(11.5, 13.3, y)
        c = max(0.0,1.0-a-b)
        return {f'UpperArm.{side}':a, f'ForeArm.{side}':b, f'Hand.{side}':c}
    thigh = smoothstep(8.8,10.8,y)
    shin = (1.0-thigh)*smoothstep(3.0,4.8,y)
    tarsus = (1.0-thigh-shin)*smoothstep(1.3,2.65,y)
    foot = max(0.0,1.0-thigh-shin-tarsus)
    return {f'Thigh.{side}':thigh, f'Shin.{side}':shin,
            f'Tarsus.{side}':tarsus, f'Foot.{side}':foot}


# Toe lanes: (|x| centre, knuckle z) per toe, measured on the source mesh.
TOE_LANES = ((1.05, 1.40), (3.05, 1.05), (5.05, 0.80))


def split_foot_toes(weights, x, y, z, side):
    """Move the forward part of the Foot weight onto the matching toe bone.

    Each toe owns the mesh inside its lateral lane once the geometry passes
    that toe's knuckle, so every claw follows its own bone instead of shearing
    between the foot and a single shared Toes bone.
    """
    foot = weights.pop(f'Foot.{side}', 0.0)
    lane = [max(0.0, 1.0 - abs(abs(x) - centre) / 1.55)
            for centre, _ in TOE_LANES]
    lane_total = sum(lane)
    height = 1.0 - smoothstep(2.4, 3.6, y)
    if foot <= 1e-6:
        return
    if lane_total <= 1e-6 or height <= 1e-6:
        weights[f'Foot.{side}'] = foot
        return
    moved = 0.0
    for number, ((centre, knuckle), share) in enumerate(
            zip(TOE_LANES, lane), start=1):
        along = smoothstep(knuckle, knuckle + 0.85, z)
        amount = foot * height * along * (share / lane_total) * 0.95
        if amount <= 1e-7:
            continue
        name = f'Toe{number}.{side}'
        weights[name] = weights.get(name, 0.0) + amount
        moved += amount
    weights[f'Foot.{side}'] = foot - moved


# Lower-jaw gates ---------------------------------------------------------
# The mouth is a topological split in the source mesh: the lower jaw is a
# handful of separate islands (hinge plates, lips, chin, lower snout cap).
# Islands keep the split exact - no positional gate can separate the upper
# lip from the lower one at |y| ~ 21.3 without leaking. Measured on the OBJ:
# every jaw island stays in front of JAW_MIN_Z and dips below JAW_MAX_TOP,
# while the throat skin is the piece that reaches back into the neck.
# The upper tooth row sits in that same box - its fangs hang down past the
# lower lip - but it belongs to the skull. It is the one island in the box
# whose tips point down, and keeping it on Head is what lets the two rows
# actually separate when the mouth opens.
JAW_MIN_Z = 15.5
JAW_MAX_TOP = 21.2
JAW_TIP_BAND = (21.5, 24.0)      # Jaw -> JawTip blend along the mouth
THROAT_BAND = (15.0, 18.0)       # throat skin: neck behind the hinge, jaw floor in front
TEETH_TIP_MARGIN = 0.02          # a tooth tip clears its whole base by this
TEETH_TIP_MIN = 4                # this many down-tips make the upper row
# The outer head shell closes the mouth continuously, so its chin and lower
# lip are not separate islands: they are a skin region of the big head island.
# That region blends onto the jaw so the closed-mouth chin and the lip below
# the tooth line descend with the teeth instead of hanging on the skull.
# Blend ramps along y around the tooth line and fades out behind the corner.
# Lower lip rim of the source mesh, right side, back to front (x, y, z).
LOWER_RIM = ((1.14, 21.17, 20.22), (1.26, 21.21, 20.83), (1.19, 21.15, 21.23),
             (1.11, 21.09, 21.64), (1.04, 21.02, 22.04), (0.96, 20.96, 22.44),
             (0.84, 20.95, 23.12), (0.77, 20.98, 23.52), (0.70, 21.00, 23.91),
             (0.63, 21.02, 24.31), (0.58, 21.03, 24.58), (0.34, 21.04, 24.77),
             (0.00, 21.06, 24.96))
LOWER_TEETH = 11                 # new cone teeth per side along the rim
LOWER_TEETH_SPAN = (0.12, 0.93)  # rim arc fraction the row covers (back, front)
LOWER_TEETH_INSET = 0.06         # cone axis sits this far inboard of the rim
LOWER_TEETH_SINK = 0.06          # cone base sinks below the rim
LOWER_TEETH_HEIGHT = (0.65, 0.85, 0.55)  # back, middle, front tooth height
LOWER_TEETH_RADIUS = 0.11        # cone base radius
LOWER_TEETH_UV_FACE = 1880       # bright upper-tooth triangle: (base, base, tip) UVs
TONGUE_STEPS = 9                 # sections along the mouth floor
TONGUE_Z = (20.8, 24.4)          # tongue root -> tip
TONGUE_WIDTH = (0.95, 0.30)      # half-width at root and tip
TONGUE_BASE = 20.85              # sunk just under the floor strip (y ~ 21.0)
TONGUE_TOP = (21.40, 21.15)      # crest height at root and tip
TONGUE_UV_FACE = 2268            # source triangle whose texel colours the tongue
CURTAIN_HIGH = 0.5               # share of the lower-rim end of a curtain sliver
CURTAIN_LOW = 0.35               # share of its head-side end
JAW_SHELL_BAND = 0.004           # skin blend half-width around the cut lip line
JAW_SHELL_PROBE = 20.7           # a jaw-shell island dips below this y up front
LIP_CUT_LIFT = 0.06              # mouth cut runs this far above LOWER_RIM
LIP_CUT_GAP = 0.005              # half-gap between the two copies of a cut point
JAW_SHELL_CORNER = (17.4, 21.4)  # the blend fades out behind this z band
WELD_LIP = (0.3, 0.6)            # lip-rim share band: skin weights -> jaw weights


def mesh_islands(vertex_count, faces):
    """Connected-vertex components of the source mesh (union-find)."""
    parent = list(range(vertex_count))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for face in faces:
        for i in range(len(face)):
            a, b = find(face[i]), find(face[i - 1])
            if a != b:
                parent[a] = b
    groups = defaultdict(list)
    for index in range(vertex_count):
        groups[find(index)].append(index)
    return list(groups.values())


def down_tooth_tips(island, vertices, adjacency):
    """Island vertices whose every neighbour sits above: teeth pointing down."""
    tips = []
    for index in island:
        neighbours = adjacency.get(index, ())
        if len(neighbours) < 3:
            continue
        y = vertices[index][1]
        if all(vertices[other][1] > y + TEETH_TIP_MARGIN
               for other in neighbours):
            tips.append(index)
    return tips


def jaw_vertex_sets(vertices, faces):
    """(jaw, throat) vertex indices: lower jaw islands and throat skin.

    Jaw islands sit entirely in front of JAW_MIN_Z and dip below the mouth
    line (JAW_MAX_TOP). The upper tooth row fits that same box, so it is
    excluded explicitly: it is the island in the box whose tips point down
    and it stays on Head. The throat island stays under the jaw while
    reaching back into the neck (min z < JAW_MIN_Z).
    """
    adjacency = defaultdict(set)
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            adjacency[a].add(b)
            adjacency[b].add(a)
    jaw = set()
    throat = set()
    for island in mesh_islands(len(vertices), faces):
        ys = [vertices[i][1] for i in island]
        zs = [vertices[i][2] for i in island]
        in_jaw_box = min(zs) >= JAW_MIN_Z and min(ys) <= JAW_MAX_TOP
        upper_teeth = (len(down_tooth_tips(island, vertices, adjacency))
                       >= TEETH_TIP_MIN)
        if in_jaw_box and not upper_teeth:
            jaw.update(island)
        elif max(ys) <= 20.6 and max(zs) >= 19.0 and min(zs) < JAW_MIN_Z:
            throat.update(island)
    return jaw, throat


def lip_line_y(z):
    """y of the mouth line at depth z: just above the lower lip rim."""
    rim = sorted(LOWER_RIM, key=lambda p: p[2])
    if z <= rim[0][2]:
        return rim[0][1] + LIP_CUT_LIFT
    for (_, y0, z0), (_, y1, z1) in zip(rim, rim[1:]):
        if z <= z1:
            return y0 + (y1 - y0) * (z - z0) / (z1 - z0) + LIP_CUT_LIFT
    return rim[-1][1] + LIP_CUT_LIFT


def split_lip_line(vertices, faces, uvs, mats):
    """Cut the head skin along the mouth line so the lips can part.

    PS1 triangles are big: many shell faces span the closed mouth with one
    corner on the upper lip and another on the lower, so they stretch into
    cheek membranes that wall in the lower teeth however the weights fall.
    Every shell face in front of the corner that crosses lip_line_y() is
    split at the line; each cut point gets an upper and a lower copy a hair
    apart (LIP_CUT_GAP), so the skull side and the jaw side become separate
    edges. Returns new (vertices, faces, uvs, mats).
    """
    jaw, throat = jaw_vertex_sets(vertices, faces)
    shell = jaw_shell_shares(vertices, faces, jaw, throat)
    skin = set()
    for island in mesh_islands(len(vertices), faces):
        if shell.keys() & set(island):
            skin.update(island)
    vertices = list(vertices)
    out_f, out_uv, out_m = [], [], []
    cache = {}

    def side(i):
        return vertices[i][1] < lip_line_y(vertices[i][2])

    def cut(i, j, lower):
        key = (min(i, j), max(i, j), lower)
        if key not in cache:
            p, q = vertices[i], vertices[j]
            gp = p[1] - lip_line_y(p[2])
            gq = q[1] - lip_line_y(q[2])
            t = gp / (gp - gq)
            x, _, z = (a + (b - a) * t for a, b in zip(p, q))
            # snap onto the (piecewise) line so each copy lands on its side
            y = lip_line_y(z) + (-LIP_CUT_GAP if lower else LIP_CUT_GAP)
            cache[key] = (len(vertices), t)
            vertices.append((x, y, z))
        index, t = cache[key]
        return index, (t if i < j else 1.0 - t)

    for face, uv, mat in zip(faces, uvs, mats):
        sides = [side(i) for i in face]
        if (not set(face) <= skin or len(set(sides)) == 1
                or min(vertices[i][2] for i in face) < JAW_SHELL_CORNER[0]):
            out_f.append(face); out_uv.append(uv); out_m.append(mat)
            continue
        # rotate so corner 0 is the lone side
        k = [n for n in range(3) if sides.count(sides[n]) == 1][0]
        a, b, c = face[k], face[(k + 1) % 3], face[(k + 2) % 3]
        ua, ub, uc = uv[k], uv[(k + 1) % 3], uv[(k + 2) % 3]
        lone = sides[k]
        p_lone, tp = cut(a, b, lone)
        q_lone, tq = cut(a, c, lone)
        p_pair, _ = cut(a, b, not lone)
        q_pair, _ = cut(a, c, not lone)
        lerp = lambda s, e, t: tuple(m + (n - m) * t for m, n in zip(s, e))
        up, uq = lerp(ua, ub, tp), lerp(ua, uc, tq)
        out_f += [(a, p_lone, q_lone), (p_pair, b, c), (p_pair, c, q_pair)]
        out_uv += [(ua, up, uq), (up, ub, uc), (up, uc, uq)]
        out_m += [mat] * 3
    return vertices, out_f, out_uv, out_m


def jaw_shell_shares(vertices, faces, jaw, throat):
    """{vertex: jaw share} for the closed-mouth head skin around the jaw.

    The big outer shell island wraps the whole head, so the chin and the
    lower-lip skin below the tooth line cannot be split off by islands. They
    prove themselves by dipping below the mouth line in front of the corner;
    those vertices get a share of Jaw/JawTip: 1 below the lip line (which
    split_lip_line() has cut the skin along) and 0 above it, fading to 0
    behind the mouth corner so the gape closes smoothly into the corner. The upper tooth row is
    excluded like in jaw_vertex_sets: its fangs dip past the line too.
    """
    adjacency = defaultdict(set)
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            adjacency[a].add(b)
            adjacency[b].add(a)
    probe_z = JAW_SHELL_PROBE
    shares = {}
    for island in mesh_islands(len(vertices), faces):
        if set(island) & (jaw | throat) or len(island) < 20:
            continue
        ys = [vertices[i][1] for i in island]
        zs = [vertices[i][2] for i in island]
        in_jaw_box = min(zs) >= JAW_MIN_Z and min(ys) <= JAW_MAX_TOP
        upper_teeth = (len(down_tooth_tips(island, vertices, adjacency))
                       >= TEETH_TIP_MIN)
        if in_jaw_box and upper_teeth:
            continue
        if not any(vertices[i][2] > probe_z and 18.0 < vertices[i][1] < probe_z
                   and abs(vertices[i][0]) < 2.5 for i in island):
            continue
        for i in island:
            x, y, z = vertices[i]
            lip = lip_line_y(z)
            below = 1.0 - smoothstep(lip - JAW_SHELL_BAND, lip + JAW_SHELL_BAND, y)
            front = smoothstep(*JAW_SHELL_CORNER, z)
            share = below * front
            if share > 1e-6:
                shares[i] = share
    return shares


def mouth_curtain_faces(vertices, faces):
    """Indices of the thin triangles that sew the closed mouth shut.

    In the source the lip skin between the mouth corner and the lower rim is
    a fan of slivers joining head-side vertices (jaw share <= CURTAIN_LOW)
    to the lower rim (share >= CURTAIN_HIGH). Closed they are invisible; open
    they stretch into a curtain across the gape that hides the lower teeth,
    so build_mesh drops them and the mouth really opens.
    """
    jaw, throat = jaw_vertex_sets(vertices, faces)
    shell = jaw_shell_shares(vertices, faces, jaw, throat)

    def share(v):
        return 1.0 if v in jaw or v in throat else shell.get(v, 0.0)

    cut = []
    for index, face in enumerate(faces):
        if min(vertices[v][2] for v in face) < JAW_MIN_Z + 4.0:
            continue
        shares = [share(v) for v in face]
        if (max(shares) >= CURTAIN_HIGH and min(shares) <= CURTAIN_LOW
                and any(v in shell for v in face)):
            cut.append(index)
    return cut


def tongue_geometry(first_index):
    """(vertices, faces) of a tongue ridge lying on the mouth floor.

    Cutting the mouth curtain leaves the head hollow behind the lips; this
    closed prism (rounded top, tapering toward the tip) fills the gap between
    the lower tooth rows. It is a new island inside the jaw box, so
    jaw_vertex_sets() puts it on Jaw/JawTip with no extra rules.
    """
    sections = []
    for k in range(TONGUE_STEPS + 1):
        t = k / TONGUE_STEPS
        z = TONGUE_Z[0] + (TONGUE_Z[1] - TONGUE_Z[0]) * t
        w = TONGUE_WIDTH[0] + (TONGUE_WIDTH[1] - TONGUE_WIDTH[0]) * t
        top = TONGUE_TOP[0] + (TONGUE_TOP[1] - TONGUE_TOP[0]) * t
        sections.append([(-w, TONGUE_BASE, z), (-0.8 * w, top - 0.12, z),
                         (0.0, top, z), (0.8 * w, top - 0.12, z),
                         (w, TONGUE_BASE, z)])
    verts = [p for section in sections for p in section]
    faces = []
    n = len(sections[0])
    for k in range(TONGUE_STEPS):
        for j in range(n - 1):
            a = first_index + k * n + j
            b = a + 1
            c = a + n
            d = c + 1
            # winding so the top faces +y and the sides face away from the axis
            faces += [(a, c, b), (b, c, d)]
    last = first_index + TONGUE_STEPS * n
    faces += [(last, last + 2, last + 1), (last, last + 3, last + 2),
              (last, last + 4, last + 3)]
    return verts, faces


def lower_teeth_geometry(first_index):
    """(vertices, faces) of two rows of cone teeth on the lower lip rim.

    The source lower rows are ~0.5-tall slivers that sit behind the lip wall
    and read as a toothless jaw once the mouth opens; scaling them only
    pushed them through the lip. These are new three-sided cones standing on
    LOWER_RIM, inboard of the upper fangs so the closed mouth hides them.
    Each cone is its own island inside the jaw box, so jaw_vertex_sets()
    puts it on Jaw/JawTip like the tongue. Faces are (base, base, tip) to
    match the LOWER_TEETH_UV_FACE UVs.
    """
    seg = [math.dist(a, b) for a, b in zip(LOWER_RIM, LOWER_RIM[1:])]
    total = sum(seg)

    def rim_at(f):
        d = f * total
        for (a, b), length in zip(zip(LOWER_RIM, LOWER_RIM[1:]), seg):
            if d <= length:
                t = d / length
                return tuple(p + (q - p) * t for p, q in zip(a, b))
            d -= length
        return LOWER_RIM[-1]

    verts, faces = [], []
    for k in range(LOWER_TEETH):
        t = k / (LOWER_TEETH - 1)
        f = LOWER_TEETH_SPAN[0] + (LOWER_TEETH_SPAN[1] - LOWER_TEETH_SPAN[0]) * t
        x, y, z = rim_at(f)
        back, mid, front = LOWER_TEETH_HEIGHT
        h = back + (mid - back) * t * 2 if t < 0.5 else mid + (front - mid) * (t - 0.5) * 2
        r = LOWER_TEETH_RADIUS
        for side in (1.0, -1.0):
            cx = side * max(abs(x) - LOWER_TEETH_INSET, 0.12)
            by = y - LOWER_TEETH_SINK
            base = [(cx, by, z + r), (cx + side * 0.8 * r, by, z - 0.6 * r),
                    (cx - side * 0.8 * r, by, z - 0.6 * r)]
            tip = (cx, by + h, z - 0.04)
            i = first_index + len(verts)
            verts += base + [tip]
            for j in range(3):
                a, b = i + j, i + (j + 1) % 3
                faces.append((a, b, i + 3) if side > 0 else (b, a, i + 3))
    return verts, faces


def jaw_weights(z):
    """Jaw/JawTip split: hinge plates ride Jaw, the tip curls with JawTip."""
    tip = smoothstep(*JAW_TIP_BAND, z)
    return {'Jaw': 1.0 - tip, 'JawTip': tip}


def blend_weights(base, extra, share):
    """Linear blend between two normalized weight dicts (share of `extra`)."""
    out = {name: value * (1.0 - share) for name, value in base.items()}
    for name, value in extra.items():
        out[name] = out.get(name, 0.0) + value * share
    return {name: value for name, value in out.items() if value > 1e-7}


def vertex_weights(src):
    x,y,z = src
    out = axial_weights(z)
    side = 'L' if x >= 0.0 else 'R'
    ax = abs(x)

    # Envelopes fade continuously toward hips and shoulders to avoid cracks.
    leg_gate = (smoothstep(1.15,2.65,ax)
                * (1.0-smoothstep(10.9,16.2,y))
                * smoothstep(-9.8,-7.0,z)
                * (1.0-smoothstep(4.2,6.4,z)))
    # The foot is much wider than the leg: the inner toes sit almost on the
    # body centre line, so they need their own gate or their claws end up
    # weighted to the spine. Only geometry under the body can pass this one.
    foot_gate = (smoothstep(0.20,0.60,ax)
                 * (1.0-smoothstep(2.4,3.6,y))
                 * smoothstep(-2.2,-0.4,z))
    # The legs are thick: their medial wall sits at |x|~0.6-1.4 and no body
    # geometry exists between them below y~10, so underneath the hips that
    # wall belongs to its own leg. Without this the wall kept spine weights
    # and a swinging leg sheared through its own width (2.4x stretch at the
    # heel). It fades out towards the hips so the leg/body junction stays put.
    wall_gate = ((1.0-smoothstep(4.6,10.0,y))
                 * smoothstep(0.30,0.65,ax)
                 * smoothstep(-9.8,-7.0,z)
                 * (1.0-smoothstep(4.2,6.4,z)))
    # The underbelly itself stays with the body, but the hip surface wrapping
    # around it has to lean into the thigh: the groin sheet only has vertices
    # near |x|~1.5 and |x|~2.4 while the bridge between them crosses three
    # units, so a hard pelvis/thigh jump there tore on every step.
    hip_gate = (smoothstep(0.6,2.4,ax)
                * smoothstep(9.0,10.0,y)
                * (1.0-smoothstep(10.8,12.4,y))
                * smoothstep(-5.5,-3.5,z)
                * (1.0-smoothstep(0.5,2.5,z)))
    leg_gate = max(leg_gate, foot_gate, wall_gate, hip_gate)
    arm_gate = (smoothstep(1.7,3.4,ax)
                * smoothstep(8.0,9.5,z)
                * (1.0-smoothstep(13.4,15.2,z))
                * smoothstep(9.7,11.0,y)
                * (1.0-smoothstep(17.0,20.6,y)))

    def mix(new, gate):
        nonlocal out
        if gate <= 1e-6:
            return
        temp = defaultdict(float)
        for k,v in out.items(): temp[k] += (1.0-gate)*v
        for k,v in new.items(): temp[k] += gate*v
        out = dict(temp)

    mix(limb_bands(y,z,side),leg_gate)
    mix(limb_bands(y,z,side,True),arm_gate)

    split_foot_toes(out, x, y, z, side)

    # The lower jaw is a separate topology island set: bind() routes those
    # vertices to Jaw/JawTip via jaw_vertex_sets(), so vertex_weights() only
    # ever sees skull, throat (partially blended) and body vertices.

    # Retain strongest four influences and renormalize for glTF compatibility.
    selected = sorted(out.items(),key=lambda kv:kv[1],reverse=True)[:4]
    total = sum(v for _,v in selected)
    if not math.isfinite(total) or total < 0.999e-6:
        raise ValueError(f'Invalid weights for vertex at {src}')
    return {name:weight/total for name,weight in selected if weight/total > 1e-7}


def parse_obj(path):
    vertices=[]; uv=[]; faces=[]; face_uv=[]; face_material=[]
    active='Untextured_faces'
    with path.open('r',encoding='utf-8',errors='replace') as f:
        for line in f:
            s=line.strip()
            if not s or s.startswith('#'): continue
            parts=s.split(); tag=parts[0]
            if tag=='v': vertices.append(tuple(float(v) for v in parts[1:4]))
            elif tag=='vt': uv.append(tuple(float(v) for v in parts[1:3]))
            elif tag=='usemtl': active=' '.join(parts[1:])
            elif tag=='f':
                corners=[]
                for item in parts[1:]:
                    bits=item.split('/')
                    vi=int(bits[0]); vi=vi-1 if vi>0 else len(vertices)+vi
                    ti=int(bits[1]) if len(bits)>1 and bits[1] else 0
                    ti=ti-1 if ti>0 else len(uv)+ti if ti<0 else -1
                    corners.append((vi,ti))
                for i in range(1,len(corners)-1):
                    tri=(corners[0],corners[i],corners[i+1])
                    faces.append(tuple(c[0] for c in tri))
                    face_uv.append(tuple(uv[c[1]] if c[1]>=0 else (0,0) for c in tri))
                    face_material.append(active)
    return vertices, faces, face_uv, face_material


def make_material(name, path):
    mat=bpy.data.materials.new('PS1 | '+name)
    mat.use_nodes=True
    tree=mat.node_tree
    tree.nodes.clear()
    tex=tree.nodes.new('ShaderNodeTexImage'); tex.location=(-500,0)
    tex.interpolation='Closest'
    bsdf=tree.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location=(-140,0)
    bsdf.inputs['Metallic'].default_value=0.0
    bsdf.inputs['Roughness'].default_value=1.0
    surface=tree.nodes.new('ShaderNodeOutputMaterial'); surface.location=(200,0)
    tree.links.new(bsdf.outputs['BSDF'],surface.inputs['Surface'])
    if path and path.exists():
        img=bpy.data.images.load(str(path),check_existing=True)
        img.pack()
        tex.image=img
        tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
        # The source's first texture has transparent palette index 0.
        # Connect alpha only there, not on the five opaque VRAM pages.
        if name == 'VRAM_page_#10':
            tree.links.new(tex.outputs['Alpha'],bsdf.inputs['Alpha'])
            if hasattr(mat,'blend_method'):
                try: mat.blend_method='CLIP'
                except Exception: pass
            elif hasattr(mat,'surface_render_method'):
                try: mat.surface_render_method='DITHERED'
                except Exception: pass
    else:
        bsdf.inputs['Base Color'].default_value=(0.21,0.16,0.11,1.0)
    mat.diffuse_color=(0.65,0.56,0.40,1.0)
    return mat


def build_mesh(obj_path, parent_collection):
    vertices,faces,uv_coords,face_mats=parse_obj(obj_path)
    if not vertices or not faces:
        raise RuntimeError('OBJ did not contain vertices/faces')
    uv_src=list(uv_coords)
    face_mats_src=list(face_mats)
    mouth_material=face_mats[TONGUE_UV_FACE]
    cut=set(mouth_curtain_faces(vertices,faces))
    keep=[i for i in range(len(faces)) if i not in cut]
    faces=[faces[i] for i in keep]
    uv_coords=[uv_coords[i] for i in keep]
    face_mats=[face_mats[i] for i in keep]
    print(f'MOUTH: dropped {len(cut)} curtain triangles that sew the mouth shut')
    before=len(faces)
    vertices,faces,uv_coords,face_mats=split_lip_line(vertices,faces,uv_coords,face_mats)
    print(f'MOUTH: cut the skin along the lip line ({(len(faces)-before)//2} faces split)')
    t_verts,t_faces=tongue_geometry(len(vertices))
    centre=tuple(sum(c)/3.0 for c in zip(*uv_src[TONGUE_UV_FACE]))
    vertices=list(vertices)+t_verts
    faces=faces+t_faces
    uv_coords=uv_coords+[(centre,)*3]*len(t_faces)
    face_mats=face_mats+[mouth_material]*len(t_faces)
    print(f'MOUTH: added a {len(t_faces)}-triangle tongue')
    n_verts,n_faces=lower_teeth_geometry(len(vertices))
    vertices=vertices+n_verts
    faces=faces+n_faces
    uv_coords=uv_coords+[uv_src[LOWER_TEETH_UV_FACE]]*len(n_faces)
    face_mats=face_mats+[face_mats_src[LOWER_TEETH_UV_FACE]]*len(n_faces)
    print(f'MOUTH: added {len(n_faces)//3} lower cone teeth')
    mesh=bpy.data.meshes.new('Dino PS1 source topology and UVs')
    mesh.from_pydata([src_to_blender(v) for v in vertices],[],faces)
    mesh.update()
    uvlayer=mesh.uv_layers.new(name='Original PS1 UV')
    for poly, tri_uv in zip(mesh.polygons,uv_coords):
        poly.use_smooth=False
        for i,li in enumerate(poly.loop_indices):
            uvlayer.data[li].uv=tri_uv[i]
    mat_to_img={
        f'VRAM_page_#{n}': obj_path.parent / f'DINO[{i}]_p00.png'
        for i,n in enumerate((10,12,14,26,28,30))
    }
    names=list(dict.fromkeys(face_mats))
    for name in names:
        mesh.materials.append(make_material(name,mat_to_img.get(name)))
    index={name:i for i,name in enumerate(names)}
    for poly,name in zip(mesh.polygons,face_mats):
        poly.material_index=index[name]
    obj=bpy.data.objects.new(MESH_NAME,mesh)
    parent_collection.objects.link(obj)
    obj['source']=str(obj_path)
    obj['source_vertices']=len(vertices)
    obj['source_triangles']=len(faces)
    return obj,vertices,faces


def build_armature(parent_collection):
    datablock=bpy.data.armatures.new('Dino editable bones')
    obj=bpy.data.objects.new(RIG_NAME,datablock)
    parent_collection.objects.link(obj)
    datablock.display_type='STICK'
    obj.show_in_front=True
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    bpy.ops.object.mode_set(mode='EDIT')
    for name,parent,head,tail,deforms in BONE_DEF:
        bone=datablock.edit_bones.new(name)
        bone.head=src_to_blender(JOINTS[head])
        bone.tail=src_to_blender(JOINTS[tail])
        if (bone.tail-bone.head).length<0.0005:
            raise ValueError('Zero-length bone '+name)
        bone.use_deform=deforms
        bone.use_connect=False
    for name,parent,_,_,_ in BONE_DEF:
        if parent:
            datablock.edit_bones[name].parent=datablock.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    obj['guide']='Numpad 3 for right side, TAB into Edit Mode to move joints.'
    obj['knee_note']='Knee is forward (+OBJ Z); Hock is backward (-OBJ Z).'
    obj['weight_note']='Skin weights are initial envelopes. Refine in Weight Paint before animation.'
    return obj


def vertex_weight_table(src_vertices,jaw=frozenset(),throat=frozenset(),shell=None):
    """Per-vertex weight dicts, with coincident mouth vertices welded."""
    table=[]
    for i,v in enumerate(src_vertices):
        if i in jaw:
            # Lower-jaw islands are fully jaw-driven; the mouth split is real
            # topology, so nothing else may pull on them.
            weights=jaw_weights(v[2])
        elif i in throat:
            # Under-jaw skin: anchored to the neck at the back, following the
            # jaw toward the chin so an open mouth never shows through.
            weights=blend_weights(vertex_weights(v),jaw_weights(v[2]),
                                  smoothstep(*THROAT_BAND,v[2]))
        elif shell and i in shell:
            # Closed-mouth head skin below the tooth line: the chin and the
            # lower-lip skin ride the jaw with a share that fades above the
            # line and behind the mouth corner (see jaw_shell_shares).
            weights=blend_weights(vertex_weights(v),jaw_weights(v[2]),shell[i])
        else:
            weights=vertex_weights(v)
        table.append(weights)
    return weld_coincident(src_vertices,table,jaw,shell or {})


def weld_coincident(src_vertices,table,jaw,shell):
    """Give vertices that share a position the same weights.

    The mouth is a topological split, so the outer lip skin and the inner rim
    strip sit at identical positions with different weights and tear into
    dark cracks when the jaw turns. A cluster that holds a jaw-island vertex
    and lip-shell vertices follows the jaw along the front lip and the skin
    near the corner (WELD_LIP); any other cluster (the hinge,
    where skull and jaw plates meet) takes the mean of its members.
    """
    clusters=defaultdict(list)
    for i,v in enumerate(src_vertices):
        clusters[tuple(round(c,3) for c in v)].append(i)
    out=list(table)
    for members in clusters.values():
        if len(members)<2:
            continue
        names=set().union(*(table[i] for i in members))
        if all(abs(table[i].get(n,0.0)-table[members[0]].get(n,0.0))<1e-3
               for i in members for n in names):
            continue
        jaw_members=[i for i in members if i in jaw]
        skin=[i for i in members if i in shell]
        if jaw_members and all(i in jaw or i in shell for i in members):
            merged=table[jaw_members[0]]
            if skin:
                # Front lip rim rides the jaw; toward the corner the rim
                # takes the skin's own share so the corner stretches
                # gradually instead of tearing the cheek open.
                t=smoothstep(*WELD_LIP,shell[skin[0]])
                merged=blend_weights(table[skin[0]],merged,t)
        else:
            merged={n:sum(table[i].get(n,0.0) for i in members)/len(members)
                    for n in names}
        top=sorted(merged.items(),key=lambda kv:-kv[1])[:4]
        total=sum(w for _,w in top)
        merged={n:w/total for n,w in top if w>1e-7}
        for i in members:
            out[i]=merged
    return out


def bind(mesh_obj,src_vertices,rig_obj,jaw=frozenset(),throat=frozenset(),shell=None):
    deform_names=[name for name,_,_,_,deform in BONE_DEF if deform]
    vgroups={name:mesh_obj.vertex_groups.new(name=name) for name in deform_names}
    stats=defaultdict(int)
    total_bad=0
    table=vertex_weight_table(src_vertices,jaw,throat,shell)
    for i,weights in enumerate(table):
        if abs(sum(weights.values())-1.0)>1e-5:
            total_bad+=1
        for name,w in weights.items():
            if name not in vgroups:
                raise RuntimeError(f'Weight references missing deform bone {name}')
            vgroups[name].add([i],float(w),'REPLACE')
            stats[name]+=1
    if total_bad:
        raise RuntimeError(f'{total_bad} vertices with invalid weight sums')
    # Both mesh and armature use identity object transforms and their coordinates
    # are already in Blender Z-up. No inverse-bind-matrix hand calculation.
    mesh_obj.parent=rig_obj
    modifier=mesh_obj.modifiers.new('TREX ARMATURE | weight-paintable', 'ARMATURE')
    modifier.object=rig_obj
    modifier.use_vertex_groups=True
    mesh_obj['rigging_strategy']='4-influence anatomical bands; manual painting still needed'
    return dict(stats)


def set_viewport(mesh,rig):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type!='VIEW_3D': continue
            space=area.spaces.active
            space.overlay.show_floor=True
            space.overlay.show_bones=True
            space.shading.type='MATERIAL' if not bpy.app.background else 'SOLID'
            space.region_3d.view_distance=8
            space.region_3d.view_location=(0,0,1.35)
            # Side-view user can press Numpad 3, then Numpad 5 for orthographic.
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active=rig


def argument_parser():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,default=DEFAULT_OBJ)
    ap.add_argument('--out-dir',type=Path,default=DEFAULT_OUT)
    ap.add_argument('--export-glb',action='store_true',help='Export Blender-made GLB (no animation clips)')
    ap.add_argument('--no-save',action='store_true')
    ap.add_argument('--clean-scene',action='store_true',
                    help='Delete every existing object before building (removes the factory-startup Cube/Light/Camera)')
    args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    return ap.parse_args(args)


def main():
    args=argument_parser()
    obj_path=args.source.expanduser().resolve()
    out=args.out_dir.expanduser().resolve()
    if not obj_path.is_file():
        raise FileNotFoundError(f'OBJ not found: {obj_path}')
    if args.clean_scene:
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob,do_unlink=True)
        default_collection=bpy.data.collections.get('Collection')
        if default_collection is not None:
            bpy.data.collections.remove(default_collection)
        print('CLEAN SCENE: removed all pre-existing objects/collection')
    out.mkdir(parents=True,exist_ok=True)
    coll=bpy.data.collections.new(COLLECTION_NAME)
    bpy.context.scene.collection.children.link(coll)
    mesh,verts,faces=build_mesh(obj_path,coll)
    rig=build_armature(coll)
    jaw,throat=jaw_vertex_sets(verts,faces)
    shell=jaw_shell_shares(verts,faces,jaw,throat)
    print(f'JAW: lower-jaw islands cover {len(jaw)} vertices, '
          f'upper tooth row stays on Head, throat skin blends over {len(throat)}, '
          f'chin/lip skin blends over {len(shell)}')
    stats=bind(mesh,verts,rig,jaw,throat,shell)
    set_viewport(mesh,rig)
    bpy.context.scene.frame_set(1)
    # Keep the render engine supplied by the installed Blender version.
    bpy.context.scene.unit_settings.system='METRIC'
    bpy.context.scene.unit_settings.scale_length=1.0
    bpy.context.scene['T-Rex PS1 note']='Real OBJ, preserved UV/texture; joints are editable. Run animate_trex.py to add the reconstructed Walk cycle.'
    print('TREX BLENDER RIG: original vertices=',len(verts),'triangles=',len(mesh.data.polygons))
    print('TREX BLENDER RIG: deform bones=',len([b for b in rig.data.bones if b.use_deform]))
    print('TREX BLENDER RIG: strongest influenced groups=',sorted(stats.items(),key=lambda p:-p[1])[:8])
    if not args.no_save:
        path=out/'trex_editable.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        print('SAVED BLEND:',path)
    if args.export_glb:
        path=out/'trex_blender_rig.glb'
        bpy.ops.object.select_all(action='DESELECT')
        mesh.select_set(True);rig.select_set(True)
        bpy.context.view_layer.objects.active=rig
        try:
            bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_animations=False)
        except TypeError:
            bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True)
        print('SAVED GLB:',path)
    print('READY: select armature -> Pose Mode. For joint positions: Edit Mode.')

if __name__=='__main__':
    main()
