"""T-Rex native viewer package.

Our own desktop viewer for the rigged PS1 T-Rex GLB: a GLB container reader
(glb.py), scene graph/skinning/animation evaluation (scene.py), an OpenGL
renderer written from scratch (renderer.py) and the pyglet application
window (app.py). pyglet provides only the window and the OpenGL bindings;
all parsing and rendering logic lives here.
"""
