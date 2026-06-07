#!/bin/bash
# apply_overlay.sh — Integrate the C++ overlay into an Eden build tree.
#
# Usage:
#   ./scripts/apply_overlay.sh /path/to/eden_build
#
# If no path is given, ../eden_build is assumed (overlay_cpp is a sibling
# of eden_build by convention).
#
# What it does:
#   1. Copies overlay/*.h and overlay/*.cpp into eden/src/hid_core/frontend/
#   2. Applies patches/emulated_controller.h.patch to add #include
#   3. Applies patches/emulated_controller.cpp.patch to add ApplyOverlay() call
#
# All patches use --forward so they are idempotent (safe to run twice).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"            # overlay_cpp root

EDEN_DIR="${1:-"$ROOT_DIR/../eden_build"}"
EDEN_SRC="$EDEN_DIR/eden/src/hid_core/frontend"
PATCH_DIR="$ROOT_DIR/patches"

if [ ! -d "$EDEN_SRC" ]; then
    echo "ERROR: Eden source directory not found: $EDEN_SRC"
    echo "Usage: $0 /path/to/eden_build"
    exit 1
fi

echo "=== Copying overlay source files ==="
cp -v "$ROOT_DIR/overlay/overlay_state.h"  "$EDEN_SRC/"
cp -v "$ROOT_DIR/overlay/overlay_udp.h"    "$EDEN_SRC/"
cp -v "$ROOT_DIR/overlay/overlay_udp.cpp"  "$EDEN_SRC/"

echo ""
echo "=== Patching emulated_controller.h ==="
patch --forward -p1 -d "$EDEN_DIR/eden" < "$PATCH_DIR/emulated_controller.h.patch" \
    && echo "  .h patch applied" || echo "  .h patch already applied (skipped)"

echo ""
echo "=== Patching emulated_controller.cpp ==="
patch --forward -p1 -d "$EDEN_DIR/eden" < "$PATCH_DIR/emulated_controller.cpp.patch" \
    && echo "  .cpp patch applied" || echo "  .cpp patch already applied (skipped)"

echo ""
echo "=== Patching CMakeLists.txt (add overlay to build) ==="
patch --forward -p1 -d "$EDEN_DIR/eden" < "$PATCH_DIR/CMakeLists_hid_core.txt.patch" \
    && echo "  CMakeLists patch applied" || echo "  CMakeLists patch already applied (skipped)"

echo ""
echo "=== Done ==="
echo "Overlay source files integrated into $EDEN_SRC"
echo "Next: rebuild Eden"
