#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
BLENDER="${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}"
if [[ ! -x "$BLENDER" ]]; then
  if command -v blender >/dev/null 2>&1; then
    BLENDER="$(command -v blender)"
  else
    echo "Blender não encontrado. Instale com: brew install --cask blender" >&2
    exit 1
  fi
fi
"$BLENDER" --background --factory-startup --python rig_trex_blender.py -- --clean-scene --export-glb
printf '\nSaídas esperadas: output/trex_editable.blend e output/trex_blender_rig.glb\n'
