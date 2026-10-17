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

echo "== 1/4 preflight (no Blender needed)"
python3 test_rig_math.py

echo "== 2/4 build rig"
"$BLENDER" --background --factory-startup --python rig_trex_blender.py -- --clean-scene

echo "== 3/4 animate walk + export GLB + preview sheet"
"$BLENDER" --background --factory-startup --python animate_trex.py -- --export-glb --preview

echo "== 4/4 verify GLB"
python3 verify_glb.py output/trex_blender_rig.glb

echo
echo "ALL DONE."
echo "  output/trex_editable.blend  -> open, select armature, Pose Mode, Space to play"
echo "  output/trex_blender_rig.glb -> 'Walk' clip, loops at 1.33 s"
echo "  diagnostics/walk/walk_contact_sheet.png -> rendered preview"
