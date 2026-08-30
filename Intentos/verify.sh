#!/usr/bin/env bash
set -euo pipefail

# Verify script for Unix-like systems. Requires 'blender' in PATH.
SCRIPTDIR="$(cd "$(dirname "$0")" && pwd)"
EXAMPLE_STL="$SCRIPTDIR/example/colored_example_binary.stl"
OUT_FBX="$SCRIPTDIR/example/colored_example_binary.fbx"

if ! command -v blender >/dev/null 2>&1; then
  echo "Blender not found in PATH. Install Blender and add it to PATH, or run the command with the full path to the blender executable."
  exit 1
fi

# Generate example STLs (python must be available)
python3 "$SCRIPTDIR/example/generate_colored_stl.py"

# Find blender in PATH
if ! command -v blender >/dev/null 2>&1; then
  echo "Blender not found in PATH. Set BLENDER_EXE to the full path to the blender executable and rerun."
  exit 1
fi

BLENDER_EXE=$(command -v blender)
LAUNCHER="$SCRIPTDIR/blender_launcher.py"
LOGDIR="$SCRIPTDIR/logs"

python3 "$LAUNCHER" --blender "$BLENDER_EXE" --script "$SCRIPTDIR/convert_stl_to_fbx.py" --input "$EXAMPLE_STL" --output "$OUT_FBX" --log-dir "$LOGDIR" --retries 2 --timeout 60 --retry-delay 2 --fallback-gltf -- --force-parse

if [ -f "$OUT_FBX" ]; then
  echo "Success: $OUT_FBX created"
  exit 0
else
  echo "Failed: $OUT_FBX not created. Check logs in $LOGDIR"
  exit 2
fi
