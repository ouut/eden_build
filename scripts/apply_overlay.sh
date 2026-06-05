#!/bin/bash
# Eden Overlay — Apply overlay patch to Eden source tree
# Usage: ./scripts/apply_overlay.sh <path-to-eden-source>

set -euo pipefail

EDEN_ROOT="${1:?Usage: $0 <path-to-eden-source>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERLAY_DIR="$SCRIPT_DIR/../overlay"

echo "=== Eden Overlay Patch ==="
echo "Target: $EDEN_ROOT"
echo "Overlay: $OVERLAY_DIR"
echo ""

FRONTEND="$EDEN_ROOT/src/hid_core/frontend"

# 1. Copy new overlay source files into Eden
echo "[1/3] Copying overlay source files..."
cp -v "$OVERLAY_DIR/overlay_types.h"  "$FRONTEND/"
cp -v "$OVERLAY_DIR/overlay_engine.h" "$FRONTEND/"
cp -v "$OVERLAY_DIR/overlay_engine.cpp" "$FRONTEND/"

# 2. Apply patches to emulated_controller
echo "[2/3] Applying patches..."
patch -d "$EDEN_ROOT" -p0 < "$OVERLAY_DIR/patches/emulated_controller.h.patch"
patch -d "$EDEN_ROOT" -p0 < "$OVERLAY_DIR/patches/emulated_controller.cpp.patch"

# 3. Add overlay sources to CMakeLists.txt (if not already present)
echo "[3/3] Updating CMakeLists.txt..."
CMAKE_FILE="$EDEN_ROOT/src/hid_core/CMakeLists.txt"
if ! grep -q "overlay_engine.cpp" "$CMAKE_FILE"; then
    sed -i '/frontend\/emulated_controller\.cpp/a\
    frontend/overlay_engine.cpp\
    frontend/overlay_engine.h\
    frontend/overlay_types.h' "$CMAKE_FILE"
    echo "  Added overlay sources to CMakeLists.txt"
else
    echo "  Overlay sources already in CMakeLists.txt"
fi

echo ""
echo "=== Done ==="
echo "You can now build Eden with overlay support."
