"""The desktop window: camera input, key bindings, HUD and screenshots.

Run with ``python3 viewer.py``. ``--screenshot`` uses the same renderer but
renders a single frame into a hidden window and saves it as a PNG, which is
handy for documentation and automated checks.
"""

from __future__ import annotations

import sys
import time
from functools import partial
from pathlib import Path

import numpy as np
import pyglet
from pyglet import shapes
from pyglet.gl import (GL_BLEND, GL_DEPTH_TEST, GL_ONE_MINUS_SRC_ALPHA,
                       GL_SRC_ALPHA, glBlendFunc, glDisable, glEnable,
                       glViewport)
from pyglet.math import Mat4
from pyglet.text import Label

from .renderer import OrbitCamera, Renderer, read_framebuffer
from .scene import TrexScene
from . import mac_gestures

# Pinch gestures arrive through our own Cocoa hook (see viewer/mac_gestures.py),
# so the event type has to exist before any window is built.
pyglet.window.Window.register_event_type(mac_gestures.EVENT)

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

HELP_LINES = (
    'Space play/pause   Left/Right scrub   M mesh   R rig   W wireframe   T bones on top',
    'G grid   L lighting   F reset view   P panel   S screenshot   1 Walk / 2 Roar   Mouse: drag orbit, shift/right-drag pan, scroll/pinch zoom',
)

DEFAULT_YAW = 0.95
DEFAULT_PITCH = 0.12
DEFAULT_FRAME = 2.05  # camera distance = frame * model radius

# Zoom response. A mouse wheel arrives as whole notches (one per click) while a
# Mac trackpad sends a fast stream of precise fractional deltas plus momentum
# after a flick. Notches take a fixed step; precise deltas scale with the
# movement but are clamped per event, so momentum zooms smoothly instead of
# jumping straight to the limits.
WHEEL_ZOOM_STEP = 0.12        # distance factor per wheel notch
WHEEL_MAX_NOTCHES = 3         # bigger integer deltas are momentum, not clicks
PRECISE_ZOOM_PER_POINT = 0.05
MAX_PRECISE_ZOOM_STEP = 0.07
PINCH_ZOOM_RATE = 1.5         # per unit of pinch magnification
MAX_PINCH_STEP = 0.25

# Control panel palette (RGBA 0-255)
PANEL_WIDTH = 252          # in points; multiplied by the display scale
PANEL_MARGIN = 18
PANEL_BG = (12, 15, 22, 238)
TITLE_COLOR = (244, 246, 251, 255)
SUBTITLE_COLOR = (142, 150, 166, 255)
HEADER_COLOR = (120, 128, 148, 255)
IDLE_BG = (33, 39, 51, 255)
HOVER_BG = (48, 55, 70, 255)
ACTIVE_BG = (233, 150, 34, 255)
TEXT_COLOR = (222, 227, 237, 255)
TEXT_ACTIVE = (28, 22, 10, 255)
STATE_COLOR = (150, 158, 174, 255)
TRACK_BG = (40, 47, 60, 255)



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


class ControlPanel:
    """Right-hand control panel: playback, display toggles, lighting, camera.

    Widgets are plain pyglet rectangles and labels with our own hit testing in
    window pixels. While the panel is visible the 3D viewport shrinks by
    ``panel_w`` so the model stays centred in the free area instead of hiding
    behind the panel.
    """

    def __init__(self, window):
        self.window = window
        self.visible = True
        self.hovered = None
        self.items = []
        self.texts = []
        self.panel_w = 0
        self.panel_x = 0
        self.build()

    # ------------------------------------------------------------- layout

    def build(self):
        window = self.window
        scale = window.scale
        width, height = window.width, window.height
        self.items = []
        self.texts = []
        self.hovered = None
        self.panel_w = int(PANEL_WIDTH * scale)
        self.panel_x = width - self.panel_w
        self.bg = shapes.Rectangle(self.panel_x, 0, self.panel_w, height,
                                   color=PANEL_BG)

        x = self.panel_x + PANEL_MARGIN * scale
        inner = self.panel_w - 2 * PANEL_MARGIN * scale
        gap = 7 * scale

        def label(text, size, color, y, weight='normal', anchor_x='left',
                  anchor_y='top', x_pos=x):
            item = Label(text, font_name='Menlo', font_size=size, weight=weight,
                         x=x_pos, y=y, anchor_x=anchor_x, anchor_y=anchor_y,
                         color=color)
            self.texts.append(item)
            return item

        def header(text, y):
            label(text, 8, HEADER_COLOR, y, weight='bold')
            return y - 18 * scale

        def button(text, y, on_click, is_active=None, height=28 * scale,
                   width=inner, x_pos=x, hint='', with_state=False,
                   advance=True):
            rect = (x_pos, y - height, width, height)
            shape = shapes.Rectangle(rect[0], rect[1], rect[2], rect[3],
                                     color=IDLE_BG)
            caption = f'{text}  ({hint})' if hint else text
            caption_label = Label(caption, font_name='Menlo', font_size=10,
                                  x=x_pos + 10 * scale, y=y - height / 2,
                                  anchor_y='center', color=TEXT_COLOR)
            state = None
            if with_state:
                state = Label('off', font_name='Menlo', font_size=8,
                              x=x_pos + width - 10 * scale, y=y - height / 2,
                              anchor_x='right', anchor_y='center',
                              color=STATE_COLOR)
            self.items.append({'rect': rect, 'shape': shape,
                               'label': caption_label, 'state': state,
                               'on_click': on_click, 'active': is_active})
            return y - height - gap if advance else y

        # ------------------------------------------------------- content
        y = height - 20 * scale
        label('T-REX VIEWER', 13, TITLE_COLOR, y, weight='bold')
        y -= 19 * scale
        clip = window.scene.clip_name or 'clip'
        label(f'PS1 rig - {clip}', 9, SUBTITLE_COLOR, y)
        y -= 24 * scale

        y = header('PLAYBACK', y)
        button('Pause' if window.playing else 'Play', y,
               window.toggle_play, hint='Space')
        self.play_item = self.items[-1]
        y = y - 28 * scale - gap
        half = (inner - gap) / 2
        button('- 1 frame', y, partial(window.step_frame, -1), width=half,
               advance=False)
        button('+ 1 frame', y, partial(window.step_frame, 1), width=half,
               x_pos=x + half + gap)
        y = y - 28 * scale - gap
        track_height = 8 * scale
        self.fill_w = inner
        self.track = shapes.Rectangle(x, y - track_height, inner,
                                      track_height, color=TRACK_BG)
        self.fill = shapes.Rectangle(x, y - track_height, 1.0, track_height,
                                     color=ACTIVE_BG)
        self.time_label = Label('', font_name='Menlo', font_size=9, x=x,
                                y=y - track_height - 5 * scale,
                                anchor_y='top', color=STATE_COLOR)
        y = y - track_height - 24 * scale

        y = header('CLIP', y)
        count = max(len(window.scene.clips), 1)
        clip_w = (inner - gap * (count - 1)) / count
        for index, info in enumerate(window.scene.clips):
            button(info['name'] or f'Clip {index + 1}', y,
                   partial(window.set_clip, index),
                   is_active=partial(window.is_clip, index),
                   hint=str(index + 1), height=26 * scale, width=clip_w,
                   x_pos=x + index * (clip_w + gap), advance=False)
        y = y - 26 * scale - gap

        y = header('DISPLAY', y)
        for flag, name, hint in (
                ('mesh', 'Mesh', 'M'),
                ('rig', 'Skeleton', 'R'),
                ('wireframe', 'Wireframe', 'W'),
                ('bones_on_top', 'Bones on top', 'T'),
                ('grid', 'Grid', 'G')):
            y = button(name, y, partial(window.toggle_flag, flag), hint=hint,
                       is_active=partial(window.flag, flag), with_state=True)

        y = header('LIGHTING', y)
        third = (inner - 2 * gap) / 3
        for mode, name in enumerate(('Shaded', 'Direct', 'Unlit')):
            button(name, y, partial(window.set_light_mode, mode),
                   is_active=partial(window.is_light_mode, mode),
                   height=26 * scale, width=third,
                   x_pos=x + mode * (third + gap))
        y = y - 26 * scale - gap

        y = header('CAMERA', y)
        button('Reset view', y, window.reset_view, hint='F')

        label(f'{clip} in place - {window.scene.duration:.2f} s at 30 fps', 8,
              STATE_COLOR, 14 * scale, anchor_y='bottom')

    # -------------------------------------------------------- interaction

    def control_at(self, x, y):
        if not self.visible or x < self.panel_x:
            return None
        for item in self.items:
            rx, ry, rw, rh = item['rect']
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return item
        return None

    def on_press(self, x, y):
        item = self.control_at(x, y)
        if item is None:
            return False
        item['on_click']()
        return True

    def on_motion(self, x, y):
        self.hovered = self.control_at(x, y)

    # -------------------------------------------------------------- draw

    def draw(self):
        if not self.visible:
            return
        window = self.window
        self.bg.draw()

        self.play_item['label'].text = ('Pause  (Space)' if window.playing
                                        else 'Play  (Space)')
        duration = max(window.scene.duration, 1e-6)
        progress = (window.time % duration) / duration
        self.fill.width = max(1.0, self.fill_w * progress)
        self.time_label.text = f'{window.time:.2f} / {duration:.2f} s'

        for text in self.texts:
            text.draw()
        for item in self.items:
            active = bool(item['active']()) if item['active'] else False
            if active:
                item['shape'].color = ACTIVE_BG
            elif item is self.hovered:
                item['shape'].color = HOVER_BG
            else:
                item['shape'].color = IDLE_BG
            item['shape'].draw()
            item['label'].color = TEXT_ACTIVE if active else TEXT_COLOR
            item['label'].draw()
            if item['state'] is not None:
                item['state'].text = 'on' if active else 'off'
                item['state'].color = TEXT_ACTIVE if active else STATE_COLOR
                item['state'].draw()
        self.track.draw()
        self.fill.draw()
        self.time_label.draw()


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
        self._shot_request = False
        self._shot_count = 0
        self._notice = ''
        self._notice_until = 0.0
        self._build_hud()
        self.panel = ControlPanel(self)
        self._camera_drag = False
        self.pinch_zoom = mac_gestures.enable_pinch(self)
        pyglet.clock.schedule_interval(self._tick, 1.0 / 120.0)

    # ------------------------------------------------------------ actions

    def toggle_play(self):
        self.playing = not self.playing
        self._refresh_status()

    def set_clip(self, index):
        self.scene.set_clip(index)
        if self.scene.duration > 0.0:
            self.time %= self.scene.duration
        self.set_caption(f'T-Rex native viewer | PS1 rig - {self.scene.clip_name}')
        self._refresh_status()

    def is_clip(self, index):
        return self.scene.clip_index == index

    def step_frame(self, direction):
        self.playing = False
        if self.scene.duration > 0.0:
            step = direction / 30.0
            self.time = (self.time + step) % self.scene.duration
        self._refresh_status()

    def toggle_flag(self, name):
        self.flags[name] = not self.flags[name]
        self._refresh_status()

    def flag(self, name):
        return self.flags[name]

    def set_light_mode(self, mode):
        self.light_mode = mode
        self._refresh_status()

    def is_light_mode(self, mode):
        return self.light_mode == mode

    def reset_view(self):
        self.camera.reset()

    # ---------------------------------------------------------------- HUD

    def _build_hud(self):
        self.status, self.hud = build_hud(self.width, self.height, self.scale)

    def _refresh_status(self):
        clip = self.scene.clip_name or 'no clip'
        state = 'playing' if self.playing else 'paused'
        switches = ' '.join(
            f'{name}={"on" if value else "off"}'
            for name, value in self.flags.items())
        self.status.text = (f'T-Rex native viewer | {clip} {self.scene.duration:.2f}s '
                            f'{state} t={self.time:.2f}s | {switches}')
        if time.monotonic() < self._notice_until:
            self.status.text += f' | {self._notice}'

    def _sync_layout(self):
        """Rebuild HUD/panel positions when the framebuffer size changes.

        Done from ``on_draw`` rather than relying only on ``on_resize``:
        pyglet does not always deliver a resize event for every backend, and
        its ``window.projection`` (which shapes and labels draw with) can lag
        behind a programmatic resize, so it is pinned to our pixel space here.
        """
        size = (self.width, self.height)
        if getattr(self, '_layout_size', None) == size:
            return
        self._layout_size = size
        self.projection = Mat4.orthogonal_projection(
            0, max(self.width, 1), 0, max(self.height, 1), -8192, 8192)
        margin = self.scale
        self.status.x = 14 * margin
        self.status.y = self.height - 12 * margin
        self.hud.x = 14 * margin
        self.hud.y = 12 * margin
        self.hud.width = max(self.width - 28 * margin, 200)
        self.panel.build()

    def on_resize(self, width, height):
        super().on_resize(width, height)
        if hasattr(self, 'status'):
            self._sync_layout()

    # -------------------------------------------------------------- frame

    def _tick(self, dt):
        if self.playing and self.scene.duration > 0.0:
            self.time = (self.time + dt * self.speed) % self.scene.duration
        self._status_age += dt
        if self._status_age >= 0.1:
            self._status_age = 0.0
            self._refresh_status()

    def _view_settings(self):
        """(viewport width, camera distance scale) for the current panel state.

        The reduced viewport keeps the full-window horizontal coverage, so the
        model never gets cropped and panning stays in sync with the cursor.
        """
        if not self.panel.visible or self.panel.panel_w <= 0:
            return self.width, 1.0
        view_width = max(self.width - self.panel.panel_w, 1)
        return view_width, self.width / view_width

    def on_draw(self):
        self._sync_layout()
        view_width, distance_scale = self._view_settings()
        self.renderer.draw(self.scene, self.time, self.camera, self.flags,
                           self.light_mode, (view_width, self.height),
                           pixel_scale=self.scale,
                           distance_scale=distance_scale)
        glViewport(0, 0, self.width, self.height)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self.status.draw()
        self.hud.draw()
        self.panel.draw()
        if self._shot_request:
            self._shot_request = False
            self._save_screenshot()

    def _save_screenshot(self):
        """Save exactly what is on screen (HUD and panel included)."""
        folder = Path('viewer_shots')
        folder.mkdir(exist_ok=True)
        self._shot_count += 1
        path = folder / f'shot_{self._shot_count:03d}.png'
        while path.exists():
            self._shot_count += 1
            path = folder / f'shot_{self._shot_count:03d}.png'
        pixels = read_framebuffer(self.width, self.height)
        image = pyglet.image.ImageData(self.width, self.height, 'RGBA',
                                       pixels.tobytes(), pitch=self.width * 4)
        image.save(str(path))
        self._notice = f'screenshot saved: {path}'
        self._notice_until = time.monotonic() + 4.0
        print(f'viewer: screenshot saved to {path.resolve()}')

    # ------------------------------------------------------------- input

    def on_key_press(self, symbol, modifiers):
        key = pyglet.window.key
        if symbol == key.SPACE:
            self.toggle_play()
        elif symbol == key.M:
            self.toggle_flag('mesh')
        elif symbol == key.R:
            self.toggle_flag('rig')
        elif symbol == key.W:
            self.toggle_flag('wireframe')
        elif symbol == key.T:
            self.toggle_flag('bones_on_top')
        elif symbol == key.G:
            self.toggle_flag('grid')
        elif symbol == key.L:
            self.set_light_mode((self.light_mode + 1) % 3)
        elif symbol == key.F:
            self.reset_view()
        elif symbol == key.P:
            self.panel.visible = not self.panel.visible
        elif symbol == key.S:
            self._shot_request = True
        elif symbol in (key._1, key.NUM_1):
            self.set_clip(0)
        elif symbol in (key._2, key.NUM_2):
            self.set_clip(1)
        elif symbol in (key.LEFT, key.RIGHT):
            self.step_frame(1 if symbol == key.RIGHT else -1)
        self._refresh_status()

    def _ui_mouse(self, x, y):
        """Mouse coordinates in window pixels (the space the UI is laid out in).

        pyglet reports pixels on macOS and X11 but points on Windows, where the
        window draws in pixels (``window.size`` is the DPI-scaled drawable).
        """
        if sys.platform.startswith('win'):
            return x * self.scale, y * self.scale
        return x, y

    def on_mouse_press(self, x, y, button, modifiers):
        px, py = self._ui_mouse(x, y)
        in_panel = self.panel.visible and px >= self.panel.panel_x
        self._camera_drag = not in_panel
        if in_panel and button == pyglet.window.mouse.LEFT:
            self.panel.on_press(px, py)

    def on_mouse_release(self, x, y, button, modifiers):
        self._camera_drag = False

    def on_mouse_motion(self, x, y, dx, dy):
        px, py = self._ui_mouse(x, y)
        self.panel.on_motion(px, py)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        if not self._camera_drag:
            return
        key = pyglet.window.key
        mouse = pyglet.window.mouse
        _, distance_scale = self._view_settings()
        if (modifiers & key.MOD_SHIFT) or (buttons & mouse.RIGHT):
            self.camera.pan(dx, dy, self.height,
                            self.camera.distance * distance_scale)
        else:
            self.camera.orbit(dx, dy)

    @staticmethod
    def zoom_step(scroll_y):
        """Distance factor for one scroll event, wheel and trackpad alike.

        Small whole notches (a mouse wheel, or a smooth-scrolling mouse that
        reports line deltas) take a fixed step. Fractional deltas and large
        momentum spikes (Mac trackpad) zoom proportionally but never jump
        more than ``MAX_PRECISE_ZOOM_STEP`` per event.
        """
        delta = float(scroll_y)
        notches = (abs(delta) >= 0.99 and abs(delta - round(delta)) < 1e-6
                   and abs(delta) <= WHEEL_MAX_NOTCHES)
        if notches:
            step = WHEEL_ZOOM_STEP * delta
        else:
            step = PRECISE_ZOOM_PER_POINT * delta
            step = max(-MAX_PRECISE_ZOOM_STEP, min(MAX_PRECISE_ZOOM_STEP, step))
        return step

    def _over_panel(self, x, y):
        if not self.panel.visible:
            return False
        px, _ = self._ui_mouse(x, y)
        return px >= self.panel.panel_x

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if self._over_panel(x, y):
            return
        self.camera.zoom_scale(1.0 + self.zoom_step(scroll_y))

    def on_magnify(self, magnification):
        """Trackpad pinch (see viewer/mac_gestures.py)."""
        step = max(-MAX_PINCH_STEP, min(MAX_PINCH_STEP,
                                        PINCH_ZOOM_RATE * float(magnification)))
        self.camera.zoom_scale(1.0 + step)


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


def screenshot(glb_path, out_path, time, width, height, clip=None):
    """Render one frame plus the HUD and save a PNG of exactly WxH pixels."""
    config = pyglet.gl.Config(double_buffer=True, major_version=3,
                              minor_version=3, forward_compatible=True)
    window = pyglet.window.Window(width=width, height=height, visible=False,
                                  config=config)
    window.switch_to()
    # On high-DPI screens the drawable is larger than the requested WxH.
    fb_width, fb_height = window.get_framebuffer_size()
    scene = TrexScene(glb_path)
    if clip:
        scene.set_clip(clip)
    renderer = Renderer(scene)
    center, radius = scene.bounds_center_radius()
    camera = OrbitCamera(center, radius * DEFAULT_FRAME,
                         yaw=DEFAULT_YAW, pitch=DEFAULT_PITCH)
    flags = {'mesh': True, 'rig': True, 'wireframe': False,
             'grid': True, 'bones_on_top': True}
    renderer.draw(scene, time, camera, flags, 0, (fb_width, fb_height),
                  pixel_scale=window.scale)

    status, hud = build_hud(fb_width, fb_height, window.scale)
    clip = scene.clip_name or 'no clip'
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
