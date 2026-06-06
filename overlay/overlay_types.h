// SPDX-FileCopyrightText: Copyright 2026 Eden Overlay Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "common/common_types.h"

namespace Core::HID {

constexpr std::size_t MAX_OVERLAY_SOURCES = 8;

// One overlay source slot. Each Lua handle (player.new / player.new_udp /
// player.new_script) occupies one slot.  Slots are independent.
struct OverlaySlotState {
    // Buttons
    u32 button_mask{0};

    // Sticks (range [-1, 1])
    f32 left_x{0.0f},  left_y{0.0f};
    f32 right_x{0.0f}, right_y{0.0f};

    // Motion — left joycon
    f32 left_gyro_x{0.0f}, left_gyro_y{0.0f}, left_gyro_z{0.0f};
    f32 left_accel_x{0.0f}, left_accel_y{0.0f}, left_accel_z{0.0f};

    // Motion — right joycon
    f32 right_gyro_x{0.0f}, right_gyro_y{0.0f}, right_gyro_z{0.0f};
    f32 right_accel_x{0.0f}, right_accel_y{0.0f}, right_accel_z{0.0f};

    u64 last_update{0};  // microseconds, for staleness detection
    bool active{false};
};

} // namespace Core::HID
