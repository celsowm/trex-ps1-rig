"""The desktop window: camera input, key bindings, HUD and screenshots.

Run with ``python3 viewer.py``. ``--screenshot`` uses the same renderer but
renders a single frame into a hidden window and saves it as a PNG, which is
handy for documentation and automated checks.
"""

from __future__ import annotations

import numpy as np
import pyglet
from pyglet.gl import GL_DEPTH_TEST, glDisable
from pyglet.text import Label

from .renderer import OrbitCamera, Renderer, read_framebuffer
from .scene import TrexScene

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

HELP_LINES = (
    'Space play/pause   Left/Right scrub   M mesh   R rig   W wireframe   T bones on top',
    'G grid   L lighting   F reset view   Mouse: drag orbit, shift/right-drag pan, wheel zoom',
)

DEFAULT_YAW = 0.95
DEFAULT_PITCH = 0.12
DEFAULT_FRAME = 2.05  # camera distance = frame * model radius


def build_hud(width, height, margin_scale=1.0):
    """The status line (top-left) and key help (bottom-left).

    ``margin_scale`` compensates for high-DPI framebuffers: positions are in
    pixels, font sizes are in points (pyglet scales those itself).
    """
    margin = margin_scale
    status = Label('', font_name='Menlo', font_size=11, x=14 * margin,
                   y=height - 12 * margin, anchor_y='top',
                   color=(236, 240, 248, 255))
    help_text = Label('\n'.join(HELP_LINES), font_name='Menlo', font_size=9,
                      x=14 * margin, y=12 * margin, multiline=True,
                      width=max(width - 28 * margin, 200),
                      color=(150, 158, 172, 255))
    return status, help_text


class ViewerWindow(pyglet.window.Window):
    def __init__(self, glb_path, width=WINDOW_WIDTH, height=WINDOW_HEIGHT,
                 visible=True):
        config = pyglet.gl.Config(double_buffer=True, major_version=3,
                                  minor_version=3, forward_compatible=True)
        super().__init__(width=width, height=height,
                         caption='T-Rex native viewer | PS1 rig + Walk',
                         resizable=True, config=config, visible=visible)
        self.scene = TrexScene(glb_path)
        self.renderer = Renderer(self.scene)
        center, radius = self.scene.bounds_center_radius()
        self.camera = OrbitCamera(center, radius * DEFAULT_FRAME,
                                  yaw=DEFAULT_YAW, pitch=DEFAULT_PITCH)
        self.flags = {'mesh': True, 'rig': True, 'wireframe': False,
                      'grid': True, 'bones_on_top': True}
        self.light_mode = 0
        self.time = 0.0
        self.playing = True
        self.speed = 1.0
        self._status_age = 0.0
        self._build_hud()
        pyglet.clock.schedule_interval(self._tick, 1.0 / 120.0)

    # ---------------------------------------------------------------- HUD

    def _build_hud(self):
        self.status, self.hud = build_hud(self.width, self.height, self.scale)

    def _refresh_status(self):
        clip = self.scene.animation_names[0] if self.scene.animation_names else 'no clip'
        state = 'playing' if self.playing else 'paused'
        switches = ' '.join(
            f'{name}={"on" if value else "off"}'
            for name, value in self.flags.items())
        self.status.text = (f'T-Rex native viewer | {clip} {self.scene.duration:.2f}s '
                            f'{state} t={self.time:.2f}s | {switches}')

    def on_resize(self, width, height):
        super().on_resize(width, height)
        margin = self.scale
        self.status.x = 14 * margin
        self.status.y = height - 12 * margin
        self.hud.x = 14 * margin
        self.hud.y = 12 * margin
        self.hud.width = max(width - 28 * margin, 200)

    # -------------------------------------------------------------- frame

    def _tick(self, dt):
        if self.playing and self.scene.duration > 0.0:
            self.time = (self.time + dt * self.speed) % self.scene.duration
        self._status_age += dt
        if self._status_age >= 0.1:
            self._status_age = 0.0
            self._refresh_status()

    def on_draw(self):
        self.renderer.draw(self.scene, self.time, self.camera, self.flags,
                           self.light_mode, (self.width, self.height),
                           pixel_scale=self.scale)
        glDisable(GL_DEPTH_TEST)
        self.status.draw()
        self.hud.draw()

    # ------------------------------------------------------------- input

    def on_key_press(self, symbol, modifiers):
        key = pyglet.window.key
        duration = self.scene.duration
        frame = 1.0 / 30.0
        if symbol == key.SPACE:
            self.playing = not self.playing
        elif symbol == key.M:
            self.flags['mesh'] = not self.flags['mesh']
        elif symbol == key.R:
            self.flags['rig'] = not self.flags['rig']
        elif symbol == key.W:
            self.flags['wireframe'] = not self.flags['wireframe']
        elif symbol == key.T:
            self.flags['bones_on_top'] = not self.flags['bones_on_top']
        elif symbol == key.G:
            self.flags['grid'] = not self.flags['grid']
        elif symbol == key.L:
            self.light_mode = (self.light_mode + 1) % 3
        elif symbol == key.F:
            self.camera.reset()
        elif symbol in (key.LEFT, key.RIGHT):
            self.playing = False
            if duration > 0.0:
                step = frame if symbol == key.RIGHT else -frame
                self.time = (self.time + step) % duration
        self._refresh_status()

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        key = pyglet.window.key
        mouse = pyglet.window.mouse
        if (modifiers & key.MOD_SHIFT) or (buttons & mouse.RIGHT):
            self.camera.pan(dx, dy, self.height)
        else:
            self.camera.orbit(dx, dy)

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        self.camera.zoom(scroll_y)


def run(glb_path, width=WINDOW_WIDTH, height=WINDOW_HEIGHT):
    window = ViewerWindow(glb_path, width, height)
    window.activate()
    pyglet.app.run()


def _resample(pixels, width, height):
    """Downsample an RGBA uint8 array to exactly (width, height)."""
    source_height, source_width = pixels.shape[:2]
    if (source_width, source_height) == (width, height):
        return pixels
    if source_width % width == 0 and source_height % height == 0:
        # High-DPI framebuffer: box-average 2x2 (or NxN) blocks.
        factor_x = source_width // width
        factor_y = source_height // height
        return pixels.reshape(height, factor_y, width, factor_x, 4).mean(
            axis=(1, 3)).astype(np.uint8)
    xs = (np.arange(width) * source_width / width).astype(np.int64)
    ys = (np.arange(height) * source_height / height).astype(np.int64)
    return pixels[ys][:, xs]


def screenshot(glb_path, out_path, time, width, height):
    """Render one frame plus the HUD and save a PNG of exactly WxH pixels."""
    config = pyglet.gl.Config(double_buffer=True, major_version=3,
                              minor_version=3, forward_compatible=True)
    window = pyglet.window.Window(width=width, height=height, visible=False,
                                  config=config)
    window.switch_to()
    # On high-DPI screens the drawable is larger than the requested WxH.
    fb_width, fb_height = window.get_framebuffer_size()
    scene = TrexScene(glb_path)
    renderer = Renderer(scene)
    center, radius = scene.bounds_center_radius()
    camera = OrbitCamera(center, radius * DEFAULT_FRAME,
                         yaw=DEFAULT_YAW, pitch=DEFAULT_PITCH)
    flags = {'mesh': True, 'rig': True, 'wireframe': False,
             'grid': True, 'bones_on_top': True}
    renderer.draw(scene, time, camera, flags, 0, (fb_width, fb_height),
                  pixel_scale=window.scale)

    status, hud = build_hud(fb_width, fb_height, window.scale)
    clip = scene.animation_names[0] if scene.animation_names else 'no clip'
    status.text = (f'T-Rex native viewer | {clip} {scene.duration:.2f}s '
                   f'paused t={time:.2f}s | ' + ' '.join(
                       f'{name}=on' for name in ('mesh', 'rig', 'grid'))
                   + ' wireframe=off bones_on_top=on')
    glDisable(GL_DEPTH_TEST)
    status.draw()
    hud.draw()

    pixels = read_framebuffer(fb_width, fb_height)
    pixels = _resample(pixels, width, height)
    image = pyglet.image.ImageData(width, height, 'RGBA',
                                   pixels.tobytes(), pitch=width * 4)
    image.save(str(out_path))
    window.close()
