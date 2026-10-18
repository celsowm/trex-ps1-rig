#!/usr/bin/env bash
# One-shot pipeline: preflight test -> rig -> animate -> export -> verify.
# Everything is regenerated from source/dino/dino.obj; nothing is hand-edited.
set -euo pipefail
cd "$(dirname "$0")"

BLENDER="${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}"
if [[ ! -x "$BLENDER" ]]; then
  if command -v blender >/dev/null 2>&1; then
    BLENDER="$(command -v blender)"
  else
    echo "Blender not found. Install the app in /Applications or set BLENDER_BIN." >&2
    exit 1
  fi
fi

echo "== 1/5 preflight (no Blender needed)"
python3 test_rig_math.py

echo "== 2/5 build rig"
"$BLENDER" --background --factory-startup --python rig_trex_blender.py -- --clean-scene

echo "== 3/5 animate walk + roar, export GLB, render preview sheets"
"$BLENDER" --background --factory-startup --python animate_trex.py -- --export-glb --preview

echo "== 4/5 verify GLB"
python3 verify_glb.py output/trex_blender_rig.glb

echo "== 5/5 viewer check (GLB parse + joint table)"
if python3 -c 'import numpy' 2>/dev/null; then
  python3 viewer.py --check
else
  echo "numpy not installed - skipping; pip install -r viewer/requirements.txt"
fi

echo
echo "ALL DONE."
echo "  output/trex_editable.blend  -> open, select armature, Pose Mode, Space to play"
echo "  output/trex_blender_rig.glb -> 'Walk' (loops) + 'Roar' (one-shot), 1.33 s each"
echo "  python3 viewer.py           -> native desktop viewer: mesh + rig + walk + roar (keys 1/2)"
echo "  diagnostics/walk/walk_contact_sheet.png -> rendered walk preview"
echo "  diagnostics/walk/roar_contact_sheet.png -> rendered roar preview"
