#!/bin/bash
# apply_overlay.sh — Integrate the C++ overlay into an Eden build tree.
#
# Usage:
#   ./scripts/apply_overlay.sh /path/to/eden_build
#
# If no path is given, ../eden_build is assumed.
#
# What it does:
#   1. Copies NEW overlay files (overlay_state.h, overlay_udp.h, overlay_udp.cpp)
#      to eden/src/hid_core/frontend/
#   2. Replaces 6 EDEN files with our modified versions from patches_v0.2.1/files/:
#        emulated_controller.h   → eden/src/hid_core/frontend/
#        emulated_controller.cpp → eden/src/hid_core/frontend/
#        CMakeLists_hid_core.txt → eden/src/hid_core/CMakeLists.txt
#        settings.h              → eden/src/common/
#        configure_input_advanced.ui  → eden/src/yuzu/configuration/
#        configure_input_advanced.cpp → eden/src/yuzu/configuration/
#
# For a new Eden version:
#   1. Create patches_vX.X.X/files/ with modified copies of Eden source files
#   2. Update VERSION below

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

VERSION="v0.2.1"
FILES_DIR="$ROOT_DIR/patches_$VERSION/files"
OVERLAY_DIR="$ROOT_DIR/overlay"

EDEN_DIR="${1:-"$ROOT_DIR/../eden_build"}"
EDEN_SRC="$EDEN_DIR/eden/src"

if [ ! -d "$EDEN_SRC" ]; then
    echo "ERROR: Eden source directory not found: $EDEN_SRC"
    echo "Usage: $0 /path/to/eden_build"
    exit 1
fi

if [ ! -d "$FILES_DIR" ]; then
    echo "ERROR: patches directory not found: $FILES_DIR"
    echo "Make sure patches_$VERSION/files/ exists"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Copy new overlay source files
# ═══════════════════════════════════════════════════════════════════════════════
echo "=== Copying new overlay source files ==="
cp -v "$OVERLAY_DIR/overlay_state.h" "$EDEN_SRC/hid_core/frontend/"
cp -v "$OVERLAY_DIR/overlay_udp.h"   "$EDEN_SRC/hid_core/frontend/"
cp -v "$OVERLAY_DIR/overlay_udp.cpp" "$EDEN_SRC/hid_core/frontend/"

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Replace Eden files with modified versions
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=== Replacing Eden files (version $VERSION) ==="

replace() {
    local src="$FILES_DIR/$1"
    local dst="$EDEN_SRC/$2"
    if [ -f "$src" ]; then
        cp -v "$src" "$dst"
    else
        echo "WARNING: $src not found, skipping"
    fi
}

replace "emulated_controller.h"           "hid_core/frontend/emulated_controller.h"
replace "emulated_controller.cpp"         "hid_core/frontend/emulated_controller.cpp"
replace "CMakeLists_hid_core.txt"         "hid_core/CMakeLists.txt"
replace "settings.h"                      "common/settings.h"
replace "configure_input_advanced.ui"     "yuzu/configuration/configure_input_advanced.ui"
replace "configure_input_advanced.cpp"    "yuzu/configuration/configure_input_advanced.cpp"

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Verify
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=== Verification ==="
grep -q 'ApplyOverlay' "$EDEN_SRC/hid_core/frontend/emulated_controller.cpp" && \
    echo "✅ ApplyOverlay found in emulated_controller.cpp" || echo "❌ ApplyOverlay MISSING"
grep -q 'overlay_enabled' "$EDEN_SRC/yuzu/configuration/configure_input_advanced.cpp" && \
    echo "✅ overlay_enabled found in configure_input_advanced.cpp" || echo "❌ overlay_enabled MISSING"
grep -q 'overlay_udp' "$EDEN_SRC/hid_core/CMakeLists.txt" && \
    echo "✅ overlay_udp found in CMakeLists.txt" || echo "❌ overlay_udp MISSING"

echo ""
echo "=== Done ==="
echo "Overlay v0.2.1 integrated into $EDEN_SRC"
echo "Next: rebuild Eden"
