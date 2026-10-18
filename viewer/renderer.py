"""OpenGL renderer for the T-Rex viewer.

Written from scratch for this project: pyglet only supplies the window and
the GL function bindings. Here we have the shaders (skinned mesh, unlit
lines/points), buffers, textures, the ground grid, the skeleton overlay and
an orbit camera. PS1 look: nearest-neighbour textures, vertex-lit shading,
unlit skeleton on top.
"""

from __future__ import annotations

import ctypes
import io
import math

import numpy as np
import pyglet
from pyglet.gl import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CLAMP_TO_EDGE, GL_COLOR_BUFFER_BIT,
    GL_COMPILE_STATUS, GL_CULL_FACE, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
    GL_DYNAMIC_DRAW, GL_ELEMENT_ARRAY_BUFFER, GL_FALSE, GL_FILL, GL_FLOAT,
    GL_FRAGMENT_SHADER, GL_FRONT_AND_BACK, GL_LEQUAL, GL_LINE, GL_LINES,
    GL_LINK_STATUS, GL_NEAREST, GL_ONE_MINUS_SRC_ALPHA, GL_POINTS,
    GL_PROGRAM_POINT_SIZE, GL_SRC_ALPHA, GL_STATIC_DRAW,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_TRUE,
    GL_UNSIGNED_INT, GL_VERTEX_SHADER, glActiveTexture, glBindBuffer,
    glBindTexture, glBindVertexArray, glBlendFunc, glBufferData, glClear,
    glClearColor, glCompileShader, glCreateProgram, glCreateShader,
    glDeleteShader, glDepthFunc, glDisable, glDrawArrays, glDrawElements,
    glEnable, glEnableVertexAttribArray, glGenBuffers, glGenVertexArrays,
    glGetProgramInfoLog, glGetProgramiv, glGetShaderInfoLog, glGetShaderiv,
    glGetUniformLocation, glLinkProgram, glPolygonMode, glShaderSource,
    glTexParameteri, glUniform1f, glUniform1i, glUniform2f, glUniform3f,
    glUniform4f, glUniformMatrix4fv, glUseProgram, glVertexAttribPointer,
    glViewport,
)

BACKGROUND = (0.052, 0.058, 0.072, 1.0)
BONE_COLOR = (1.0, 0.52, 0.08, 1.0)
JOINT_COLOR = (1.0, 0.83, 0.30, 1.0)
GRID_COLOR = (0.130, 0.140, 0.165, 1.0)
GRID_MAJOR_COLOR = (0.190, 0.205, 0.240, 1.0)
WIRE_COLOR = (0.25, 1.0, 0.55, 1.0)

MESH_VERTEX = """
#version 330 core
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec3 in_normal;
layout(location = 2) in vec2 in_uv;
layout(location = 3) in vec4 in_joints;
layout(location = 4) in vec4 in_weights;
uniform mat4 u_view_proj;
uniform mat4 u_joints[__JOINTS__];
out vec2 v_uv;
out vec3 v_normal;
out vec3 v_world;
void main() {
    mat4 skin = u_joints[int(in_joints.x)] * in_weights.x
              + u_joints[int(in_joints.y)] * in_weights.y
              + u_joints[int(in_joints.z)] * in_weights.z
              + u_joints[int(in_joints.w)] * in_weights.w;
    vec4 world = skin * vec4(in_position, 1.0);
    v_world = world.xyz;
    v_normal = mat3(skin) * in_normal;
    v_uv = in_uv;
    gl_Position = u_view_proj * world;
}
"""

MESH_FRAGMENT = """
#version 330 core
in vec2 v_uv;
in vec3 v_normal;
in vec3 v_world;
uniform sampler2D u_texture;
uniform int u_has_texture;
uniform int u_wireframe;
uniform int u_light_mode;
uniform vec3 u_base_color;
uniform float u_alpha;
uniform vec3 u_eye;
out vec4 out_color;
void main() {
    if (u_wireframe == 1) {
        out_color = vec4(__WIRE_COLOR__);
        return;
    }
    vec3 base = u_base_color;
    float alpha = u_alpha;
    if (u_has_texture == 1) {
        vec4 texel = texture(u_texture, v_uv);
        base *= texel.rgb;
        alpha *= texel.a;
    }
    vec3 normal = normalize(v_normal);
    if (!gl_FrontFacing) {
        normal = -normal;   // the model is double-sided
    }
    vec3 color = base;
    if (u_light_mode != 2) {
        vec3 light = normalize(u_eye - v_world);
        float diffuse = max(dot(normal, light), 0.0);
        float sky = 0.5 + 0.5 * normal.y;
        float ambient = (u_light_mode == 1) ? 0.38 : (0.30 + 0.34 * sky);
        color = base * (ambient + 0.62 * diffuse);
    }
    out_color = vec4(color, alpha);
}
"""

LINE_VERTEX = """
#version 330 core
layout(location = 0) in vec3 in_position;
uniform mat4 u_view_proj;
uniform float u_point_size;
void main() {
    gl_Position = u_view_proj * vec4(in_position, 1.0);
    gl_PointSize = u_point_size;
}
"""

LINE_FRAGMENT = """
#version 330 core
uniform vec4 u_color;
uniform int u_round_points;
out vec4 out_color;
void main() {
    if (u_round_points == 1) {
        vec2 offset = gl_PointCoord - vec2(0.5);
        if (dot(offset, offset) > 0.25) {
            discard;
        }
    }
    out_color = u_color;
}
"""

THICK_LINE_VERTEX = """
#version 330 core
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec3 in_other;
layout(location = 2) in float in_side;
uniform mat4 u_view_proj;
uniform vec2 u_viewport;    // framebuffer size in pixels
uniform float u_half_width; // line half width in pixels
void main() {
    vec4 clip_a = u_view_proj * vec4(in_position, 1.0);
    vec4 clip_b = u_view_proj * vec4(in_other, 1.0);
    vec2 screen_a = clip_a.xy / max(clip_a.w, 1e-5) * 0.5 * u_viewport;
    vec2 screen_b = clip_b.xy / max(clip_b.w, 1e-5) * 0.5 * u_viewport;
    vec2 direction = screen_b - screen_a;
    vec2 normal = (length(direction) < 1e-5)
        ? vec2(0.0, 1.0) : normalize(vec2(-direction.y, direction.x));
    vec2 offset = normal * in_side * u_half_width * 2.0 / u_viewport * clip_a.w;
    gl_Position = vec4(clip_a.xy + offset, clip_a.z, clip_a.w);
}
"""

THICK_LINE_FRAGMENT = """
#version 330 core
uniform vec4 u_color;
out vec4 out_color;
void main() {
    out_color = u_color;
}
"""


# ------------------------------------------------------------------ math


def perspective(field_of_view, aspect, near, far):
    factor = 1.0 / math.tan(math.radians(field_of_view) / 2.0)
    matrix = np.zeros((4, 4), np.float32)
    matrix[0, 0] = factor / max(aspect, 1e-6)
    matrix[1, 1] = factor
    matrix[2, 2] = (far + near) / (near - far)
    matrix[2, 3] = (2.0 * far * near) / (near - far)
    matrix[3, 2] = -1.0
    return matrix


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye = np.asarray(eye, np.float32)
    target = np.asarray(target, np.float32)
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.asarray(up, np.float32))
    right /= max(np.linalg.norm(right), 1e-8)
    true_up = np.cross(right, forward)
    view = np.eye(4, dtype=np.float32)
    view[0, :3] = right
    view[1, :3] = true_up
    view[2, :3] = -forward
    view[:3, 3] = -view[:3, :3] @ eye
    return view


class OrbitCamera:
    """Orbit/pan/zoom camera. Yaw 0 looks from +Z, positive yaw from +X."""

    def __init__(self, target, distance, yaw=0.95, pitch=0.24, fov=42.0):
        self.target = np.asarray(target, np.float32).copy()
        self.distance = float(distance)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov = float(fov)
        self._home = (self.target.copy(), self.distance, self.yaw, self.pitch)

    def reset(self):
        target, distance, yaw, pitch = self._home
        self.target = target.copy()
        self.distance = distance
        self.yaw = yaw
        self.pitch = pitch

    def eye(self, distance=None):
        distance = self.distance if distance is None else distance
        cos_pitch = math.cos(self.pitch)
        offset = np.array([
            math.sin(self.yaw) * cos_pitch,
            math.sin(self.pitch),
            math.cos(self.yaw) * cos_pitch,
        ], np.float32) * distance
        return self.target + offset

    def view_proj(self, aspect, distance=None):
        distance = self.distance if distance is None else distance
        eye = self.eye(distance)
        near = max(distance * 0.002, 0.02)
        far = distance * 40.0 + 50.0
        return perspective(self.fov, aspect, near, far) @ look_at(eye, self.target)

    def orbit(self, dx, dy):
        self.yaw -= dx * 0.0075
        self.pitch = float(np.clip(self.pitch + dy * 0.0075, -1.40, 1.40))

    def pan(self, dx, dy, viewport_height, distance=None):
        distance = self.distance if distance is None else distance
        forward = self.target - self.eye()
        forward /= max(np.linalg.norm(forward), 1e-8)
        right = np.cross(forward, np.array([0.0, 1.0, 0.0], np.float32))
        right /= max(np.linalg.norm(right), 1e-8)
        up = np.cross(right, forward)
        world_per_pixel = (2.0 * math.tan(math.radians(self.fov) / 2.0)
                           * distance / max(viewport_height, 1))
        self.target += (-right * dx + up * dy) * world_per_pixel

    def zoom(self, amount):
        self.distance = float(np.clip(self.distance * (0.9 ** amount), 0.4, 200.0))


# ------------------------------------------------------------- GL helpers


def _float_pointer(array):
    return array.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def _compile_shader(source, kind):
    shader = glCreateShader(kind)
    data = source.encode('utf-8')
    string_pointer = ctypes.cast(ctypes.c_char_p(data),
                                 ctypes.POINTER(ctypes.c_char))
    sources = (ctypes.POINTER(ctypes.c_char) * 1)(string_pointer)
    glShaderSource(shader, 1, sources, None)
    glCompileShader(shader)
    status = ctypes.c_int(0)
    glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
    if not status.value:
        log = ctypes.create_string_buffer(8192)
        glGetShaderInfoLog(shader, 8192, None, log)
        raise RuntimeError('shader compile failed: '
                           + log.value.decode('utf-8', 'replace'))
    return shader


def _link_program(vertex_source, fragment_source):
    vertex = _compile_shader(vertex_source, GL_VERTEX_SHADER)
    fragment = _compile_shader(fragment_source, GL_FRAGMENT_SHADER)
    program = glCreateProgram()
    from pyglet.gl import glAttachShader  # local: only needed here
    glAttachShader(program, vertex)
    glAttachShader(program, fragment)
    glLinkProgram(program)
    glDeleteShader(vertex)
    glDeleteShader(fragment)
    status = ctypes.c_int(0)
    glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
    if not status.value:
        log = ctypes.create_string_buffer(8192)
        glGetProgramInfoLog(program, 8192, None, log)
        raise RuntimeError('shader link failed: '
                           + log.value.decode('utf-8', 'replace'))
    return program


def _create_buffer(target, array, usage=GL_STATIC_DRAW):
    buffer_id = ctypes.c_uint(0)
    glGenBuffers(1, ctypes.byref(buffer_id))
    glBindBuffer(target, buffer_id)
    array = np.ascontiguousarray(array)
    glBufferData(target, array.nbytes, ctypes.c_void_p(array.ctypes.data), usage)
    return buffer_id.value


def _upload_buffer(buffer_id, target, array, usage=GL_DYNAMIC_DRAW):
    array = np.ascontiguousarray(array)
    glBindBuffer(target, buffer_id)
    glBufferData(target, array.nbytes, ctypes.c_void_p(array.ctypes.data), usage)


class Shader:
    def __init__(self, vertex_source, fragment_source):
        self.program = _link_program(vertex_source, fragment_source)
        self._locations = {}

    def use(self):
        glUseProgram(self.program)

    def location(self, name):
        if name not in self._locations:
            self._locations[name] = glGetUniformLocation(self.program,
                                                         name.encode('utf-8'))
        return self._locations[name]

    def set_int(self, name, value):
        location = self.location(name)
        if location >= 0:
            glUniform1i(location, int(value))

    def set_float(self, name, value):
        location = self.location(name)
        if location >= 0:
            glUniform1f(location, float(value))

    def set_vec3(self, name, value):
        location = self.location(name)
        if location >= 0:
            glUniform3f(location, float(value[0]), float(value[1]),
                        float(value[2]))

    def set_vec2(self, name, value):
        location = self.location(name)
        if location >= 0:
            glUniform2f(location, float(value[0]), float(value[1]))

    def set_vec4(self, name, value):
        location = self.location(name)
        if location >= 0:
            glUniform4f(location, float(value[0]), float(value[1]),
                        float(value[2]), float(value[3]))

    def set_mat4(self, name, matrix):
        location = self.location(name)
        if location >= 0:
            array = np.ascontiguousarray(matrix, np.float32)
            glUniformMatrix4fv(location, 1, GL_TRUE, _float_pointer(array))

    def set_mat4_array(self, name, matrices):
        location = self.location(name)
        if location >= 0:
            count = len(matrices)
            flat = np.ascontiguousarray(matrices, np.float32).reshape(-1)
            glUniformMatrix4fv(location, count, GL_TRUE, _float_pointer(flat))


class MeshPrimitive:
    """One glTF primitive: its VAO, vertex buffers, texture and material."""

    def __init__(self, primitive, material):
        self.color = tuple(material.get('color', (1.0, 1.0, 1.0)))
        self.alpha = float(material.get('alpha', 1.0))
        self.blended = material.get('alpha_mode') == 'BLEND'
        self.count = int(len(primitive['indices']))

        self._buffers = []
        vao = ctypes.c_uint(0)
        glGenVertexArrays(1, ctypes.byref(vao))
        self.vao = vao.value
        glBindVertexArray(self.vao)

        self._attribute(0, 3, primitive['position'])
        if primitive['normal'] is not None:
            self._attribute(1, 3, primitive['normal'])
        if primitive['uv'] is not None:
            # glTF UVs have V pointing down from the top of the image;
            # pyglet uploads image rows bottom-up, so flip V to compensate.
            uv = primitive['uv'].copy()
            uv[:, 1] = 1.0 - uv[:, 1]
            self._attribute(2, 2, uv)
        if primitive['joints'] is not None:
            self._attribute(3, 4, primitive['joints'])
        if primitive['weights'] is not None:
            self._attribute(4, 4, primitive['weights'])
        self._buffers.append(_create_buffer(GL_ELEMENT_ARRAY_BUFFER,
                                            primitive['indices']))
        glBindVertexArray(0)

        self.texture = None
        png = material.get('texture')
        if png is not None:
            image = pyglet.image.load('embedded.png', file=io.BytesIO(png))
            texture = image.get_texture()
            glBindTexture(GL_TEXTURE_2D, texture.id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            self.texture = texture

    def _attribute(self, location, size, data):
        array = np.ascontiguousarray(data, np.float32).reshape(len(data), size)
        self._buffers.append(_create_buffer(GL_ARRAY_BUFFER, array))
        glEnableVertexAttribArray(location)
        glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, 0,
                              ctypes.c_void_p(0))

    def draw(self, shader, wireframe=False):
        glBindVertexArray(self.vao)
        use_texture = self.texture is not None and not wireframe
        shader.set_int('u_has_texture', 1 if use_texture else 0)
        if use_texture:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.texture.id)
        shader.set_vec3('u_base_color', self.color)
        shader.set_float('u_alpha', self.alpha)
        glDrawElements(GL_TRIANGLES, self.count, GL_UNSIGNED_INT,
                       ctypes.c_void_p(0))


class LineBatch:
    """A VAO/VBO holding dynamic 3-component vertices for GL_LINES/GL_POINTS."""

    def __init__(self, capacity_vertices):
        self.capacity = int(capacity_vertices)
        vao = ctypes.c_uint(0)
        glGenVertexArrays(1, ctypes.byref(vao))
        self.vao = vao.value
        glBindVertexArray(self.vao)
        self.vbo = _create_buffer(GL_ARRAY_BUFFER,
                                  np.zeros((self.capacity, 3), np.float32),
                                  GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindVertexArray(0)
        self.count = 0

    def update(self, vertices):
        vertices = np.ascontiguousarray(vertices, np.float32).reshape(-1, 3)
        self.count = min(len(vertices), self.capacity)
        if self.count:
            _upload_buffer(self.vbo, GL_ARRAY_BUFFER,
                           vertices[:self.count])

    def draw(self, mode):
        if not self.count:
            return
        glBindVertexArray(self.vao)
        glDrawArrays(mode, 0, self.count)


class ThickLineBatch:
    """Bone segments as screen-space quads, so they stay visible at any DPI.

    Each segment becomes two triangles whose vertices carry the opposite
    endpoint; the vertex shader extrudes them perpendicular to the segment
    in pixel space (macOS core profile only supports 1px GL_LINES).
    """

    def __init__(self, capacity_segments):
        self.capacity = max(int(capacity_segments) * 6, 12)
        vao = ctypes.c_uint(0)
        glGenVertexArrays(1, ctypes.byref(vao))
        self.vao = vao.value
        glBindVertexArray(self.vao)
        self.vbo = _create_buffer(
            GL_ARRAY_BUFFER,
            np.zeros((self.capacity, 7), np.float32),  # pos3, other3, side
            GL_DYNAMIC_DRAW)
        stride = 7 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(12))
        glEnableVertexAttribArray(2)
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(24))
        glBindVertexArray(0)
        self.count = 0

    def update(self, segments):
        vertices = []
        for first, second in segments:
            vertices.append((*first, *second, -1.0))
            vertices.append((*first, *second, 1.0))
            vertices.append((*second, *first, -1.0))
            vertices.append((*first, *second, 1.0))
            vertices.append((*second, *first, -1.0))
            vertices.append((*second, *first, 1.0))
        array = np.array(vertices, np.float32).reshape(-1, 7)
        self.count = min(len(array), self.capacity)
        if self.count:
            _upload_buffer(self.vbo, GL_ARRAY_BUFFER, array[:self.count])

    def draw(self):
        if not self.count:
            return
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLES, 0, self.count)


def _grid_vertices(extent=10.0, step=1.0, major_every=5.0):
    minor = []
    major = []
    value = -extent
    while value <= extent + 1e-6:
        target = major if abs(value % major_every) < 1e-6 else minor
        target.extend([(-extent, 0.0, value), (extent, 0.0, value)])
        target.extend([(value, 0.0, -extent), (value, 0.0, extent)])
        value += step
    return (np.array(minor, np.float32).reshape(-1, 3),
            np.array(major, np.float32).reshape(-1, 3))


class Renderer:
    """Draws the skinned mesh, the ground grid and the skeleton overlay."""

    def __init__(self, scene):
        self.scene = scene
        joint_count = max(len(scene.joints), 1)
        mesh_fragment = MESH_FRAGMENT.replace(
            '__WIRE_COLOR__',
            ', '.join(f'{channel:.2f}' for channel in WIRE_COLOR[:3]) + ', 1.0')
        self.mesh_shader = Shader(
            MESH_VERTEX.replace('__JOINTS__', str(joint_count)),
            mesh_fragment)
        self.line_shader = Shader(LINE_VERTEX, LINE_FRAGMENT)
        self.bone_shader = Shader(THICK_LINE_VERTEX, THICK_LINE_FRAGMENT)

        self.primitives = []
        for primitive in scene.primitives:
            index = primitive['material']
            material = (scene.materials[index]
                        if 0 <= index < len(scene.materials) else {})
            self.primitives.append(MeshPrimitive(primitive, material))

        minor, major = _grid_vertices()
        self.grid_minor = LineBatch(len(minor))
        self.grid_minor.update(minor)
        self.grid_major = LineBatch(len(major))
        self.grid_major.update(major)

        self.bones = ThickLineBatch(joint_count)
        self.joints = LineBatch(joint_count)

    def update_skeleton(self, time):
        scene = self.scene
        positions = scene.joint_world_positions(time)
        segments = []
        for index, parent in enumerate(scene.joint_parent):
            if parent >= 0:
                segments.append((positions[parent], positions[index]))
        self.bones.update(segments)
        self.joints.update(positions)

    def draw(self, scene, time, camera, flags, light_mode, viewport,
             pixel_scale=1.0, distance_scale=1.0):
        width, height = viewport
        glViewport(0, 0, max(width, 1), max(height, 1))
        glClearColor(*BACKGROUND)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDisable(GL_CULL_FACE)  # every material is double-sided

        aspect = width / max(height, 1)
        view_proj = camera.view_proj(aspect, camera.distance * distance_scale)
        eye = camera.eye()

        if flags['grid']:
            self.line_shader.use()
            self.line_shader.set_mat4('u_view_proj', view_proj)
            self.line_shader.set_float('u_point_size', 1.0)
            self.line_shader.set_int('u_round_points', 0)
            glDisable(GL_BLEND)
            self.line_shader.set_vec4('u_color', GRID_COLOR)
            self.grid_minor.draw(GL_LINES)
            self.line_shader.set_vec4('u_color', GRID_MAJOR_COLOR)
            self.grid_major.draw(GL_LINES)

        mesh_drawn = False
        if flags['mesh']:
            self.mesh_shader.use()
            self.mesh_shader.set_mat4('u_view_proj', view_proj)
            self.mesh_shader.set_mat4_array('u_joints', scene.skin_matrices(time))
            self.mesh_shader.set_vec3('u_eye', eye)
            self.mesh_shader.set_int('u_light_mode', light_mode)
            self.mesh_shader.set_int('u_wireframe', 0)

            glDisable(GL_BLEND)
            for primitive in self.primitives:
                if not primitive.blended:
                    primitive.draw(self.mesh_shader)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            for primitive in self.primitives:
                if primitive.blended:
                    primitive.draw(self.mesh_shader)
            glDisable(GL_BLEND)
            mesh_drawn = True

            if flags['wireframe']:
                self.mesh_shader.set_int('u_wireframe', 1)
                glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
                for primitive in self.primitives:
                    primitive.draw(self.mesh_shader, wireframe=True)
                glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        if flags['rig'] and len(scene.joints):
            self.update_skeleton(time)
            if flags['bones_on_top']:
                glDisable(GL_DEPTH_TEST)

            self.bone_shader.use()
            self.bone_shader.set_mat4('u_view_proj', view_proj)
            self.bone_shader.set_vec2('u_viewport', (width, height))
            self.bone_shader.set_float('u_half_width', 1.15 * pixel_scale)
            self.bone_shader.set_vec4('u_color', BONE_COLOR)
            self.bones.draw()

            self.line_shader.use()
            self.line_shader.set_mat4('u_view_proj', view_proj)
            glEnable(GL_PROGRAM_POINT_SIZE)
            self.line_shader.set_vec4('u_color', JOINT_COLOR)
            self.line_shader.set_float('u_point_size', 7.0 * pixel_scale)
            self.line_shader.set_int('u_round_points', 1)
            self.joints.draw(GL_POINTS)
            glDisable(GL_PROGRAM_POINT_SIZE)
            if flags['bones_on_top']:
                glEnable(GL_DEPTH_TEST)
        return mesh_drawn


def read_framebuffer(width, height):
    """Read the current back buffer as RGBA uint8 (bottom-up, GL order).

    pyglet's ImageData also stores rows bottom-up, so no flip is needed here.
    """
    from pyglet.gl import GL_RGBA, GL_UNSIGNED_BYTE, glFinish, glReadPixels
    glFinish()
    buffer = (ctypes.c_ubyte * (width * height * 4))()
    glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, buffer)
    pixels = np.frombuffer(buffer, np.uint8).reshape(height, width, 4)
    return pixels.copy()
