"""Trackpad pinch gestures for the macOS viewer window.

pyglet forwards scrolling but not NSEvent magnification, so on macOS we add a
``magnifyWithEvent:`` method to pyglet's view class at runtime and dispatch it
as ``on_magnify(magnification)``. Best effort by design: on other platforms,
or if pyglet's internals move, the viewer simply runs without pinch zoom.
"""

from __future__ import annotations

import sys

EVENT = 'on_magnify'


def enable_pinch(window):
    """Send ``on_magnify`` events to ``window`` when the user pinches.

    Returns True when the gesture hook was installed. The window class must
    have registered the ``on_magnify`` event type beforehand (the app does it
    at import time, before any window exists).
    """
    if sys.platform != 'darwin':
        return False
    try:
        from pyglet.libs.darwin.cocoapy import runtime
        from pyglet.window.cocoa import pyglet_view
    except Exception:
        return False
    view_class = getattr(pyglet_view, 'PygletView', None)
    if view_class is None:
        return False

    def magnify_with_event(self_ptr, _cmd, event_ptr):
        try:
            view = runtime.ObjCInstance(self_ptr)
            event = runtime.ObjCInstance(event_ptr)
            view._window.dispatch_event(EVENT, float(event.magnification()))
        except Exception:
            pass    # a gesture must never break the event loop

    try:
        runtime.add_method(view_class.ptr, b'magnifyWithEvent:',
                           magnify_with_event, b'v@:@')
    except Exception:
        return False
    return True
