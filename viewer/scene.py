"""Scene graph, animation evaluation and skinning for the T-Rex GLB.

Takes the raw glTF tree from :mod:`viewer.glb` and turns it into something a
renderer can use directly: node world matrices, joint matrices for skinning,
the mesh primitives with their attributes unpacked, and material info with
the embedded PNG bytes.

Pure numpy, no OpenGL - so ``viewer.py --check`` can validate the file
headless (no window, no GPU).
"""

from __future__ import annotations

import numpy as np

from .glb import Glb


def quat_matrix(quaternion):
    """xyzw quaternion -> 3x3 rotation matrix (row-major)."""
    x, y, z, w = (float(value) for value in quaternion)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array([
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
    ], dtype=np.float32)


def trs_matrix(translation, rotation, scale):
    """Build a 4x4 TRS matrix from glTF components (never transposes)."""
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, :3] = quat_matrix(rotation) * np.asarray(scale, np.float32)[None, :]
    matrix[:3, 3] = np.asarray(translation, np.float32)
    return matrix


def decompose_matrix(matrix):
    """4x4 -> (translation, quaternion xyzw, scale). Column scale only."""
    translation = matrix[:3, 3].copy()
    scale = np.linalg.norm(matrix[:3, :3], axis=0)
    safe = np.where(scale == 0.0, 1.0, scale)
    rotation = matrix[:3, :3] / safe[None, :]
    trace = rotation[0, 0] + rotation[1, 1] + rotation[2, 2]
    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (rotation[2, 1] - rotation[1, 2]) / s
        y = (rotation[0, 2] - rotation[2, 0]) / s
        z = (rotation[1, 0] - rotation[0, 1]) / s
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        s = np.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        w = (rotation[2, 1] - rotation[1, 2]) / s
        x = 0.25 * s
        y = (rotation[0, 1] + rotation[1, 0]) / s
        z = (rotation[0, 2] + rotation[2, 0]) / s
    elif rotation[1, 1] > rotation[2, 2]:
        s = np.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        w = (rotation[0, 2] - rotation[2, 0]) / s
        x = (rotation[0, 1] + rotation[1, 0]) / s
        y = 0.25 * s
        z = (rotation[1, 2] + rotation[2, 1]) / s
    else:
        s = np.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        w = (rotation[1, 0] - rotation[0, 1]) / s
        x = (rotation[0, 2] + rotation[2, 0]) / s
        y = (rotation[1, 2] + rotation[2, 1]) / s
        z = 0.25 * s
    return translation, np.array([x, y, z, w], dtype=np.float32), scale.astype(np.float32)


class TrexScene:
    """Everything the viewer needs from the GLB file."""

    def __init__(self, path):
        self.glb = Glb(path)
        self.path = self.glb.path
        self.gltf = self.glb.gltf
        self._load_nodes()
        self._load_skin()
        self._load_animation()
        self._load_materials()
        self._load_primitives()
        self._compute_bounds()

    # ------------------------------------------------------------- nodes

    def _load_nodes(self):
        nodes = self.gltf.get('nodes', [])
        self.node_count = len(nodes)
        self.node_names = [node.get('name', f'node{index}')
                           for index, node in enumerate(nodes)]
        self.parent = [-1] * self.node_count
        for index, node in enumerate(nodes):
            for child in node.get('children', []):
                self.parent[child] = index

        self.base_translation = np.zeros((self.node_count, 3), np.float32)
        self.base_rotation = np.zeros((self.node_count, 4), np.float32)
        self.base_rotation[:, 3] = 1.0
        self.base_scale = np.ones((self.node_count, 3), np.float32)
        for index, node in enumerate(nodes):
            if 'matrix' in node:
                matrix = np.array(node['matrix'], np.float32).reshape(4, 4).T
                translation, rotation, scale = decompose_matrix(matrix)
                self.base_translation[index] = translation
                self.base_rotation[index] = rotation
                self.base_scale[index] = scale
            if 'translation' in node:
                self.base_translation[index] = node['translation']
            if 'rotation' in node:
                self.base_rotation[index] = node['rotation']
            if 'scale' in node:
                self.base_scale[index] = node['scale']

        # Depth-first order with every parent before its children, so world
        # matrices can be accumulated in a single pass.
        scene_index = self.gltf.get('scene', 0)
        scenes = self.gltf.get('scenes', [])
        roots = list(scenes[scene_index].get('nodes', [])) if scenes else []
        if not roots:
            roots = [index for index in range(self.node_count)
                     if self.parent[index] < 0]
        order = []
        seen = set()
        stack = list(reversed(roots))
        while stack:
            index = stack.pop()
            if index in seen:
                continue
            seen.add(index)
            order.append(index)
            stack.extend(reversed(nodes[index].get('children', [])))
        order.extend(index for index in range(self.node_count)
                     if index not in seen)
        self.order = order

    # -------------------------------------------------------------- skin

    def _load_skin(self):
        skins = self.gltf.get('skins', [])
        self.has_skin = bool(skins)
        if not self.has_skin:
            self.joints = np.zeros(0, np.int64)
            self.inverse_bind = np.zeros((0, 4, 4), np.float32)
            self.joint_index_of_node = {}
            self.joint_parent = []
            return
        skin = skins[0]
        self.joints = np.array(skin.get('joints', []), dtype=np.int64)
        # glTF matrices are column-major in the file: reshape then transpose.
        raw = self.glb.accessor(skin['inverseBindMatrices']).astype(np.float32)
        self.inverse_bind = raw.reshape(-1, 4, 4).transpose(0, 2, 1)
        self.joint_index_of_node = {int(node): index
                                    for index, node in enumerate(self.joints)}
        # For skeleton lines: nearest ancestor that is also a joint.
        self.joint_parent = []
        for joint_node in self.joints:
            ancestor = self.parent[int(joint_node)]
            while ancestor >= 0 and ancestor not in self.joint_index_of_node:
                ancestor = self.parent[ancestor]
            self.joint_parent.append(
                self.joint_index_of_node.get(ancestor, -1))

    # --------------------------------------------------------- animation

    def _load_animation(self):
        animations = self.gltf.get('animations', [])
        self.animation_names = [animation.get('name', '')
                                for animation in animations]
        self.clips = []
        for animation in animations:
            channels, duration = self._parse_clip(animation)
            self.clips.append({'name': animation.get('name', ''),
                               'channels': channels,
                               'duration': duration})
        if not self.clips:
            self.clips = [{'name': '', 'channels': [], 'duration': 0.0}]
        # Present the Walk first (Blender exports the stashed action first):
        # keys 1/2 and the panel read the same order the viewer displays.
        order = sorted(range(len(self.clips)),
                       key=lambda i: (self.clips[i]['name'] != 'Walk', i))
        self.clips = [self.clips[i] for i in order]
        self.clip_index = 0
        self._use_clip(0)

    def _parse_clip(self, animation):
        channels = []
        duration = 0.0
        for channel in animation.get('channels', []):
            sampler = animation['samplers'][channel['sampler']]
            target = channel['target']
            path = target.get('path', '')
            if path not in ('translation', 'rotation', 'scale'):
                continue
            times = self.glb.accessor(sampler['input']).astype(np.float32)
            values = self.glb.accessor(sampler['output']).astype(np.float32)
            times = times.reshape(-1)
            channels.append({
                'node': int(target['node']),
                'path': path,
                'times': times,
                'values': values,
            })
            if len(times):
                duration = max(duration, float(times[-1]))
        return channels, duration

    def _use_clip(self, index):
        index = max(0, min(int(index), len(self.clips) - 1))
        self.clip_index = index
        clip = self.clips[index]
        self.channels = clip['channels']
        self.duration = clip['duration']

    def set_clip(self, index):
        """Switch the active animation clip by index or name."""
        if isinstance(index, str):
            names = [info['name'] for info in self.clips]
            index = names.index(index)
        self._use_clip(index)

    @property
    def clip_name(self):
        return self.clips[self.clip_index]['name']
    def sample_local(self, time):
        """Per-node local TRS at ``time`` (LINEAR/nlerp sampling)."""
        translation = self.base_translation.copy()
        rotation = self.base_rotation.copy()
        scale = self.base_scale.copy()
        if not self.channels or self.duration <= 0.0:
            return translation, rotation, scale
        time = float(time) % self.duration
        for channel in self.channels:
            times = channel['times']
            values = channel['values']
            index = int(np.searchsorted(times, time, side='right')) - 1
            index = min(max(index, 0), max(len(times) - 2, 0))
            next_index = min(index + 1, len(times) - 1)
            span = float(times[next_index]) - float(times[index])
            factor = 0.0 if span <= 0.0 else (float(time) - float(times[index])) / span
            factor = min(max(factor, 0.0), 1.0)
            first = values[index]
            second = values[next_index]
            if channel['path'] == 'rotation':
                # nlerp, then normalize: fine for densely keyed clips.
                value = first + (second - first) * factor
                norm = float(np.linalg.norm(value))
                value = value / norm if norm > 1e-8 else first
            else:
                value = first + (second - first) * factor
            node = channel['node']
            if channel['path'] == 'translation':
                translation[node] = value
            elif channel['path'] == 'rotation':
                rotation[node] = value
            else:
                scale[node] = value
        return translation, rotation, scale

    # ------------------------------------------------------- world/skin

    def world_matrices(self, time):
        """4x4 world matrix for every node at the given time."""
        translation, rotation, scale = self.sample_local(time)
        world = np.zeros((self.node_count, 4, 4), np.float32)
        for index in self.order:
            local = trs_matrix(translation[index], rotation[index], scale[index])
            parent = self.parent[index]
            if parent < 0:
                world[index] = local
            else:
                world[index] = world[parent] @ local
        return world

    def skin_matrices(self, time):
        """Joint matrices for the vertex shader: world @ inverse bind."""
        if not self.has_skin:
            return np.eye(4, dtype=np.float32)[None, :, :]
        world = self.world_matrices(time)
        return np.matmul(world[self.joints], self.inverse_bind)

    def joint_world_positions(self, time):
        """World-space origin of every joint (the skeleton vertices)."""
        world = self.world_matrices(time)
        return world[self.joints][:, :3, 3].copy()

    def joint_index(self, name):
        for index, node in enumerate(self.joints):
            if self.node_names[int(node)] == name:
                return index
        raise KeyError(f'no joint named {name!r}')

    # -------------------------------------------------------- materials

    def _load_materials(self):
        self.materials = []
        for material in self.gltf.get('materials', []):
            info = {'texture': None, 'color': (1.0, 1.0, 1.0),
                    'alpha': 1.0,
                    'alpha_mode': material.get('alphaMode', 'OPAQUE'),
                    'name': material.get('name', '')}
            pbr = material.get('pbrMetallicRoughness', {})
            if 'baseColorFactor' in pbr:
                factor = pbr['baseColorFactor']
                info['color'] = tuple(float(value) for value in factor[:3])
                info['alpha'] = float(factor[3])
            texture_ref = pbr.get('baseColorTexture')
            if texture_ref is not None:
                texture = self.gltf['textures'][texture_ref['index']]
                source = texture.get('source')
                if source is not None:
                    info['texture'] = self.glb.image_bytes(source)
            self.materials.append(info)

    # ------------------------------------------------------- primitives

    def _load_primitives(self):
        self.primitives = []
        for mesh in self.gltf.get('meshes', []):
            for primitive in mesh.get('primitives', []):
                if primitive.get('mode', 4) != 4:  # triangles only
                    continue
                attributes = primitive['attributes']
                entry = {
                    'position': self.glb.accessor(attributes['POSITION']).astype(np.float32),
                    'normal': None,
                    'uv': None,
                    'joints': None,
                    'weights': None,
                    'indices': None,
                    'material': int(primitive.get('material', -1)),
                }
                if 'NORMAL' in attributes:
                    entry['normal'] = self.glb.accessor(attributes['NORMAL']).astype(np.float32)
                if 'TEXCOORD_0' in attributes:
                    entry['uv'] = self.glb.accessor(attributes['TEXCOORD_0']).astype(np.float32)
                if 'JOINTS_0' in attributes:
                    entry['joints'] = self.glb.accessor(attributes['JOINTS_0']).astype(np.float32)
                if 'WEIGHTS_0' in attributes:
                    entry['weights'] = self.glb.accessor(attributes['WEIGHTS_0']).astype(np.float32)
                if 'indices' in primitive:
                    entry['indices'] = self.glb.accessor(primitive['indices']).astype(np.uint32).reshape(-1)
                else:
                    entry['indices'] = np.arange(len(entry['position']), dtype=np.uint32)
                self.primitives.append(entry)

    def _compute_bounds(self):
        if self.primitives:
            points = np.concatenate([primitive['position']
                                     for primitive in self.primitives])
            self.bounds_min = points.min(axis=0)
            self.bounds_max = points.max(axis=0)
        else:
            self.bounds_min = np.zeros(3, np.float32)
            self.bounds_max = np.zeros(3, np.float32)

    def bounds_center_radius(self):
        center = (self.bounds_min + self.bounds_max) / 2.0
        radius = float(np.linalg.norm(self.bounds_max - self.bounds_min)) / 2.0
        return center, max(radius, 0.5)
