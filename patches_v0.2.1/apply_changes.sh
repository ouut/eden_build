#!/bin/bash
# Apply overlay changes to a fresh Eden v0.2.1 source tree.
# Usage: ./apply_changes.sh /path/to/eden_v0.2.1_src
# This script is a reference for how the files/ directory was generated.

set -euo pipefail
SRC="${1:?Usage: $0 /path/to/eden_v0.2.1/src}"

# settings.h
sed -i '' '711a\
\
    // Overlay\
    Setting<bool> overlay_enabled{linkage, false, "overlay_enabled", Category::Overlay};\
    Setting<u16> overlay_port{linkage, 26760, "overlay_port", Category::Overlay};' "$SRC/common/settings.h"

# emulated_controller.h
sed -i '' '/^#include "hid_core\/irsensor\/irs_types.h"/a\
#include "hid_core/frontend/overlay_udp.h"' "$SRC/hid_core/frontend/emulated_controller.h"

# emulated_controller.cpp
sed -i '' '1920a\
\
    ApplyOverlay(npad_id_type, controller);' "$SRC/hid_core/frontend/emulated_controller.cpp"

# CMakeLists.txt
sed -i '' '/^    frontend\/emulated_controller.h$/a\
    frontend/overlay_state.h\
    frontend/overlay_udp.cpp\
    frontend/overlay_udp.h' "$SRC/hid_core/CMakeLists.txt"

# configure_input_advanced.ui
sed -i '' '2759a\
                   <item row="9" column="0">\
                     <widget class="QCheckBox" name="overlay_enabled">\
                      <property name="text"><string>Enable overlay input (UDP)</string></property>\
                     </widget>\
                   </item>\
                   <item row="9" column="2">\
                     <widget class="QSpinBox" name="overlay_port">\
                      <property name="minimum"><number>1024</number></property>\
                      <property name="maximum"><number>65535</number></property>\
                      <property name="value"><number>26760</number></property>\
                     </widget>\
                   </item>' "$SRC/yuzu/configuration/configure_input_advanced.ui"

# configure_input_advanced.cpp (includes + port test + load/save)
# Too complex for a single sed, see files/ for the result
echo "configure_input_advanced.cpp has complex changes — use the complete file from files/"
