#!/usr/bin/env python3
"""Reconstructed walk-in-place cycle for the PS1 T-Rex rig.

    blender -b --factory-startup --python animate_trex.py -- \
        [--blend output/trex_editable.blend] [--export-glb] [--preview] [--no-save]

Loads the rigged blend, builds a looping 40-frame "Walk" action at 30 fps
(left foot mid-stance at frame 0, right foot offset by half a cycle, frame 40
duplicates frame 0), saves the blend, exports a GLB with the animation, and
optionally renders a contact sheet into diagnostics/walk/.

LEG SOLUTION: each leg is solved with exact analytic 2-link IK (thigh + shin)
so the claw tips follow the FOOT_TARGETS table in world space; the tarsus is
counter-rotated to keep the foot unit at a chosen world angle (heel rise,
flat stance, claw lift). The hip position is read from Blender's evaluated
pose, so pelvis roll/yaw and the body bob feed into the solve automatically.
The body, tail, neck, head and arms use the parametric layers below.
Everything is in DEGREES around WORLD axes and converted by lib_trex.wq().

The original demo's clip data does not exist in the source OBJ, so this walk
is a reconstruction on the true 1:1 model. Every number below is a knob:
  - FOOT_TARGETS drives stride, ground contact and swing height
  - BOB / boolean layers drive the body
"""

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import lib_trex as lt

DEFAULT_BLEND = SCRIPT_DIR / 'output' / 'trex_editable.blend'
DEFAULT_OUT = SCRIPT_DIR / 'output'
PREVIEW_DIR = SCRIPT_DIR / 'diagnostics' / 'walk'

FPS = 30
CYCLE = 40          # frames for the full left+right cycle
KEY_STEP = 5        # a key every 5 frames, plus out-of-range helper keys
N_PHASES = 9        # FOOT_TARGETS rows, = CYCLE / KEY_STEP + 1

# ------------------------------------------------------------- rest geometry
# (y, z) of the leg joints in Blender space, from the rig script's JOINTS
# (source OBJ y/z scaled by 0.10, x ignored: the solve is in the YZ plane).
HIP_YZ = (0.32, 1.43)
KNEE_YZ = (-0.23, 0.98)
HOCK_YZ = (0.25, 0.375)
TOE_TIP_YZ = (-0.283, 0.001)   # middle claw tip, source (3.39, 0.01, 2.83) * 0.1

L1 = math.dist(HIP_YZ, KNEE_YZ)         # thigh
L2 = math.dist(KNEE_YZ, HOCK_YZ)        # shin
A1_REST = math.degrees(math.atan2(KNEE_YZ[1] - HIP_YZ[1],
                                  KNEE_YZ[0] - HIP_YZ[0]))
A2_REST = math.degrees(math.atan2(HOCK_YZ[1] - KNEE_YZ[1],
                                  HOCK_YZ[0] - KNEE_YZ[0]))
TOE_TO_HOCK = (HOCK_YZ[0] - TOE_TIP_YZ[0], HOCK_YZ[1] - TOE_TIP_YZ[1])

# ------------------------------------------------------- foot target table
# One row per 1/8 cycle, phase 0 = mid-stance under the body.
# Columns: claw-tip y (forward is negative), claw-tip z (middle claw tip;
# ~0.01 = claws just touching the ground) and the heel-rise delta: world
# angle of the whole foot unit vs. rest (flat = 0, positive = hock rises
# while the claws keep their spot -> heel-off roll).
FOOT_TARGETS = [
    # y      z      heel
    (-0.259, 0.008, 0.0),   # 0.000 mid-stance, sole flat
    (-0.159, 0.008, 4.0),   # 0.125 late stance, sweeping back
    (-0.019, 0.028, 18.0),  # 0.250 toe-off, heel high, claws planted
    (-0.119, 0.160, 14.0),  # 0.375 early swing, lifted
    (-0.299, 0.220, 16.0),  # 0.500 mid swing, highest
    (-0.439, 0.180, 12.0),  # 0.625 forward travel
    (-0.479, 0.085, 4.0),   # 0.750 reach, descending
    (-0.399, 0.020, -6.0),  # 0.875 touchdown, claws dipping
    (-0.259, 0.008, 0.0),   # 1.000 = mid-stance again (loop)
]

# ---------------------------------------------------------------- body knobs
BOB = 0.04                # Root_CTRL vertical travel, meters
PELVIS_YAW = 5.0          # hip advance/retreat
PELVIS_ROLL = 3.0         # hip drop over the swinging leg
CHEST_COUNTER = 0.65      # chest yaw counter-rotation vs pelvis
SPINE_PITCH = 1.5         # chest pitch bob
HEAD_BOB = 1.5            # neck/head counter-pitch
HEAD_YAW = 2.5            # head yaw sway
TAIL_YAW = [3.0, 4.5, 6.0, 7.0, 8.5]   # Tail_01 .. Tail_End side sway
TAIL_LAG = 0.045          # per-segment phase delay for the follow-through
TAIL_PITCH = 2.0
ARM_SWING = 6.0           # vestigial arms, contralateral with the legs
ARM_FORE = 4.0
TOE_CURL_SWING = 8.0      # claws lifted while airborne
TOE_DIP_LAND = 4.0        # claws reach slightly on touchdown

TAU = 2.0 * math.pi


def bell(t, center, width):
    """Wrapped gaussian bump on the unit cycle, peak 1.0 at t == center."""
    d = ((t - center + 0.5) % 1.0) - 0.5
    return math.exp(-(d * d) / (width * width))


def wrap_deg(x):
    return ((x + 180.0) % 360.0) - 180.0


def rot_plane(dy, dz, degrees):
    """Rotate an offset in the YZ plane (about +X)."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return (dy * c - dz * s, dy * s + dz * c)


def foot_target(p):
    """Table row for leg phase p (0..1), linearly blended between rows."""
    idx = (p % 1.0) * (N_PHASES - 1)
    i0 = int(math.floor(idx)) % (N_PHASES - 1)
    i1 = (i0 + 1) % (N_PHASES - 1)
    f = idx - math.floor(idx)
    row0, row1 = FOOT_TARGETS[i0], FOOT_TARGETS[i1]
    return tuple(a + (b - a) * f for a, b in zip(row0, row1))


def solve_leg(hip, toe, heel):
    """Analytic IK: angles (deg) for thigh/shin/tarsus so the claw tip lands
    on `toe` (world y,z) with the foot unit rotated by `heel` degrees."""
    off = rot_plane(TOE_TO_HOCK[0], TOE_TO_HOCK[1], heel)
    hock = Vector((toe[0] + off[0], toe[1] + off[1]))
    hip = Vector(hip)
    span = hock - hip
    d = span.length
    d = max(min(d, (L1 + L2) * 0.999), abs(L1 - L2) * 1.001)
    base = math.degrees(math.atan2(span.y, span.x))
    cos_a = (L1 * L1 + d * d - L2 * L2) / (2.0 * L1 * d)
    reach_a = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))

    best = None
    for sign in (+1.0, -1.0):
        phi1 = base + sign * reach_a
        knee = hip + Vector((math.cos(math.radians(phi1)),
                             math.sin(math.radians(phi1)))) * L1
        # prefer the knee forward (more negative world Y = component .x here)
        if best is None or knee.x < best[1].x:
            best = (phi1, knee, hock)
    phi1, knee, hock = best
    phi2 = math.degrees(math.atan2(hock.y - knee.y, hock.x - knee.x))

    thigh = wrap_deg(phi1 - A1_REST)
    shin = wrap_deg(phi2 - A2_REST - thigh)
    tarsus = wrap_deg(heel - (thigh + shin))
    return thigh, shin, tarsus


def leg_rotation_list(t, side):
    """Solved rotations for one leg at cycle time t."""
    p = (t + (0.0 if side == 'L' else 0.5)) % 1.0
    toe_y, toe_z, heel = foot_target(p)
    hip_pb = rig.pose.bones[f'Thigh.{side}']
    hip_world = rig.matrix_world @ hip_pb.head
    thigh, shin, tarsus = solve_leg((hip_world.y, hip_world.z), (toe_y, toe_z), heel)
    toes = (TOE_CURL_SWING * bell(p, 0.55, 0.22)
            - TOE_DIP_LAND * bell(p, 0.875, 0.10))
    return {
        f'Thigh.{side}': [('X', thigh)],
        f'Shin.{side}': [('X', shin)],
        f'Tarsus.{side}': [('X', tarsus)],
        f'Foot.{side}': [('X', 0.0)],
        # One bone per toe: the long inner toe curls a little more than the
        # short outer toe, so the claws move individually instead of as one
        # rigid slab hinged off a shared bone.
        f'Toe1.{side}': [('X', toes * 1.15)],
        f'Toe2.{side}': [('X', toes)],
        f'Toe3.{side}': [('X', toes * 0.85)],
    }


def body_pose(t):
    """Parametric layers for everything except the legs (and arms)."""
    rots = {}
    locs = {}

    for side in ('L', 'R'):
        arm_p = (t + (0.0 if side == 'L' else 0.5)) % 1.0
        rots[f'UpperArm.{side}'] = [('X', -ARM_SWING * math.cos(TAU * arm_p))]
        rots[f'ForeArm.{side}'] = [('X', -ARM_FORE * math.cos(TAU * arm_p) - 3.0)]

    bob = -BOB * math.cos(2.0 * TAU * (t - 0.10))
    locs['Root_CTRL'] = (0.0, 0.0, bob)

    pelvis_yaw = -PELVIS_YAW * math.sin(TAU * (t - 0.5))
    rots['Pelvis'] = [
        ('Z', pelvis_yaw),
        ('Y', -PELVIS_ROLL * math.sin(TAU * t)),
    ]
    pitch_bob = math.cos(2.0 * TAU * (t - 0.10))
    rots['Spine'] = [('X', SPINE_PITCH * pitch_bob)]
    rots['Chest'] = [
        ('Z', -CHEST_COUNTER * pelvis_yaw),
        ('X', SPINE_PITCH * 0.6 * pitch_bob),
    ]
    rots['Neck'] = [
        ('X', -HEAD_BOB * pitch_bob),
        ('Z', -HEAD_YAW * 0.6 * math.sin(TAU * (t - 0.58))),
    ]
    rots['Head'] = [
        ('X', -HEAD_BOB * 0.8 * pitch_bob),
        ('Z', -HEAD_YAW * math.sin(TAU * (t - 0.62))),
    ]

    tail_names = ['Tail_01', 'Tail_02', 'Tail_03', 'Tail_04', 'Tail_End']
    for i, (name, amp) in enumerate(zip(tail_names, TAIL_YAW)):
        lag = i * TAIL_LAG
        rots[name] = [
            ('Z', amp * math.sin(TAU * (t - 0.5 - lag))),
            ('X', TAIL_PITCH * 0.5 * math.cos(2.0 * TAU * (t - 0.10 - lag))),
        ]
    return rots, locs


def apply_pose(t):
    """Apply body first, then solve both legs against the evaluated hips."""
    rots, locs = body_pose(t)
    for name, rotations in rots.items():
        pb = rig.pose.bones[name]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = lt.wq(pb, rotations)
    for name, vec in locs.items():
        pb = rig.pose.bones[name]
        pb.location = lt.wloc(pb, vec)
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)

    bpy.context.view_layer.update()   # hips must reflect the body pose
    for side in ('L', 'R'):
        for name, rotations in leg_rotation_list(t, side).items():
            pb = rig.pose.bones[name]
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = lt.wq(pb, rotations)
            rots[name] = rotations
    return rots, locs


def iter_fcurves(action):
    """F-curves of an action across Blender versions.

    Blender <= 4.3 exposes action.fcurves directly; 4.4+ (slotted actions)
    stores them in layers -> strips -> channelbags."""
    fcurves = getattr(action, 'fcurves', None)
    if fcurves is not None:
        return list(fcurves)
    out = []
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in getattr(strip, 'channelbags', []):
                out.extend(channelbag.fcurves)
    return out


def build_action(rig):
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = CYCLE
    rig.animation_data_create()
    old = bpy.data.actions.get('Walk')
    if old is not None:
        bpy.data.actions.remove(old)
    action = bpy.data.actions.new('Walk')
    action.use_fake_user = True
    rig.animation_data.action = action

    keyed_bones = set()
    # Helper keys one step beyond each end keep the loop handles smooth:
    # values at -5/45 equal +35/5 by construction of the periodic pose.
    for frame in range(-KEY_STEP, CYCLE + KEY_STEP + 1, KEY_STEP):
        t = (frame / CYCLE) % 1.0
        rots, locs = apply_pose(t)
        for name in rots:
            pb = rig.pose.bones[name]
            pb.keyframe_insert('rotation_quaternion', frame=frame)
            keyed_bones.add(name)
        for name in locs:
            rig.pose.bones[name].keyframe_insert('location', frame=frame)
            keyed_bones.add(name)

    fcurves = iter_fcurves(action)
    for fcurve in fcurves:
        for kp in fcurve.keyframe_points:
            kp.interpolation = 'BEZIER'
            kp.handle_left_type = 'AUTO_CLAMPED'
            kp.handle_right_type = 'AUTO_CLAMPED'

    n_keys = sum(len(fc.keyframe_points) for fc in fcurves)
    print(f'WALK: action "Walk" {CYCLE} frames @ {FPS} fps '
          f'({CYCLE / FPS:.2f} s), fcurves={len(fcurves)} keys={n_keys} '
          f'bones={len(keyed_bones)}')
    return action


def export_glb(mesh, rig, path):
    bpy.ops.object.select_all(action='DESELECT')
    mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    wanted = {
        'filepath': str(path),
        'export_format': 'GLB',
        'use_selection': True,
        'export_animations': True,
        'export_animation_mode': 'ACTIONS',
        'export_force_sampling': True,
        'export_frame_range': True,
        'export_optimize_animation_size': False,
        'export_yup': True,
    }
    supported = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs = {k: v for k, v in wanted.items() if k in supported}
    dropped = sorted(set(wanted) - set(kwargs))
    if dropped:
        print(f'WALK: exporter does not support {dropped}; using supported subset')
    bpy.ops.export_scene.gltf(**kwargs)
    print(f'WALK: exported {path}')


def preview_sheet(mesh, rig):
    import numpy as np

    scene = bpy.context.scene
    lt.strip_default_objects()
    lt.pick_render_engine(scene)
    lt.ensure_lighting()
    lt.add_ground()
    views = lt.camera_views(mesh, rig)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    frames = list(range(0, CYCLE, KEY_STEP))
    paths = []
    for frame in frames:
        scene.frame_set(frame)
        path = PREVIEW_DIR / f'walk_f{frame:02d}.png'
        lt.render_to(path, views['side'], resolution=(760, 400), samples=10)
        paths.append(path)
    scene.frame_set(10)
    lt.render_to(PREVIEW_DIR / 'walk_three_quarter_f10.png',
                 views['three_quarter'], resolution=(900, 640), samples=10)
    scene.frame_set(0)
    lt.render_to(PREVIEW_DIR / 'walk_front_f00.png',
                 views['front'], resolution=(520, 720), samples=10)

    sheet = []
    for path in paths:
        img = bpy.data.images.load(str(path))
        w, h = img.size
        sheet.append(np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4))
        bpy.data.images.remove(img)
    h, w = sheet[0].shape[:2]
    cols = 4
    rows = (len(sheet) + cols - 1) // cols
    canvas = np.zeros((rows * h, cols * w, 4), dtype=np.float32)
    canvas[..., 3] = 1.0
    for i, tile in enumerate(sheet):
        r, c = divmod(i, cols)
        r = rows - 1 - r  # image pixels start bottom-left
        canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = tile
    out = bpy.data.images.new('walk_contact_sheet', width=cols * w,
                              height=rows * h, alpha=False)
    out.pixels = canvas.ravel()
    out.filepath_raw = str(PREVIEW_DIR / 'walk_contact_sheet.png')
    out.file_format = 'PNG'
    out.save()
    print(f'WALK: contact sheet -> {PREVIEW_DIR / "walk_contact_sheet.png"}')


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--blend', type=Path, default=DEFAULT_BLEND)
    ap.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--export-glb', action='store_true')
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--no-save', action='store_true')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return ap.parse_args(argv)


rig = None
mesh = None


def main():
    global rig, mesh
    args = parse_args()
    blend = args.blend.expanduser().resolve()
    if not blend.is_file():
        raise FileNotFoundError(f'{blend} not found; run rig_trex_blender.py first')
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    removed = lt.strip_default_objects()
    if removed:
        print(f'WALK: removed default objects: {", ".join(removed)}')
    mesh, rig = lt.find_objects()
    lt.clear_pose(rig)

    build_action(rig)
    bpy.context.scene['T-Rex PS1 note'] = (
        'Editable rig with the reconstructed in-place Walk action '
        f'({CYCLE} frames @ {FPS} fps). Original geometry, UVs and textures '
        'are untouched (1:1).'
    )
    out = args.out_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    bpy.context.scene.frame_set(0)
    if not args.no_save:
        path = out / 'trex_editable.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        print(f'WALK: saved {path}')
    if args.export_glb:
        export_glb(mesh, rig, out / 'trex_blender_rig.glb')
    if args.preview:
        preview_sheet(mesh, rig)
    print('WALK: done. Open the blend and press Space in Pose Mode to watch '
          'the Walk action on TREX_EDITABLE_ARMATURE.')


if __name__ == '__main__':
    main()
