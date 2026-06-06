#!/bin/bash
# Eden Overlay — Apply overlay patch to Eden source tree
# Usage: ./scripts/apply_overlay.sh <path-to-eden-source>

set -euo pipefail

EDEN_ROOT="${1:?Usage: $0 <path-to-eden-source>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERLAY_DIR="$SCRIPT_DIR/../overlay"
PATCHES="$OVERLAY_DIR/patches"

echo "=== Eden Overlay Patch ==="
echo "Target: $EDEN_ROOT"
echo "Overlay: $OVERLAY_DIR"
echo ""

FRONTEND="$EDEN_ROOT/src/hid_core/frontend"

# 1. Copy new overlay source files into Eden
echo "[1/4] Copying overlay source files..."
cp -v "$OVERLAY_DIR/overlay_types.h"  "$FRONTEND/"
cp -v "$OVERLAY_DIR/overlay_engine.h" "$FRONTEND/"
cp -v "$OVERLAY_DIR/overlay_engine.cpp" "$FRONTEND/"

# 2. Apply patches to emulated_controller
echo "[2/4] Applying emulated_controller patches..."
patch -d "$EDEN_ROOT" -p0 < "$PATCHES/emulated_controller.h.patch"
patch -d "$EDEN_ROOT" -p0 < "$PATCHES/emulated_controller.cpp.patch"

# 3. Add Lua dependency (cpmfile + externals build)
echo "[3/4] Adding Lua dependency..."
patch -d "$EDEN_ROOT" -p0 < "$PATCHES/cpmfile.json.patch"
patch -d "$EDEN_ROOT" -p0 < "$PATCHES/CMakeLists.txt.patch"

# 4. Add overlay sources to hid_core CMakeLists + link lua
echo "[4/4] Updating hid_core CMakeLists..."
patch -d "$EDEN_ROOT" -p0 < "$PATCHES/CMakeLists_hid_core.txt.patch"

echo ""
echo "=== Done ==="
echo "You can now build Eden with overlay support."
