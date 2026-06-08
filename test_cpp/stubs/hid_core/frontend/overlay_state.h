// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "common/common_types.h"

namespace Core::HID {

/// control_mask bit definitions for the OVER protocol
namespace OverlayControl {
constexpr u32 BUTTON     = 1u << 0;   ///< button_mask
constexpr u32 LEFT_X     = 1u << 1;   ///< left_x
constexpr u32 LEFT_Y     = 1u << 2;   ///< left_y
constexpr u32 RIGHT_X    = 1u << 3;   ///< right_x
constexpr u32 RIGHT_Y    = 1u << 4;   ///< right_y
constexpr u32 LEFT_GYRO  = 1u << 5;   ///< left gyro (xyz as a group)
constexpr u32 LEFT_ACCEL = 1u << 6;   ///< left accel (xyz as a group)
constexpr u32 RIGHT_GYRO = 1u << 7;   ///< right gyro (xyz as a group)
constexpr u32 RIGHT_ACCEL= 1u << 8;   ///< right accel (xyz as a group)
} // namespace OverlayControl

/// Per-pad state updated by incoming OVER protocol packets.
struct OverlayState {
    u32 control_mask{0};    ///< sender-declared field ownership (OverlayControl bits)
    u64 button_mask{0};     ///< NpadButton bitmask, matches NpadButtonState.raw width

    // Analog sticks — f32, range [-1.0, 1.0]
    f32 left_x{0}, left_y{0};
    f32 right_x{0}, right_y{0};

    // Left motion — 6 fields
    f32 left_gyro_x{0}, left_gyro_y{0}, left_gyro_z{0};   // rad/s
    f32 left_accel_x{0}, left_accel_y{0}, left_accel_z{0}; // G

    // Right motion — 6 fields
    f32 right_gyro_x{0}, right_gyro_y{0}, right_gyro_z{0};   // rad/s
    f32 right_accel_x{0}, right_accel_y{0}, right_accel_z{0}; // G

    // Merge tracking
    u64 button_mask_prev{0};///< previous frame's button_mask (for clearing stale OR bits)
    u64 last_update{0};     ///< steady_clock timestamp (us) of last received packet
    bool active{false};     ///< false when stale — ApplyOverlay skips this pad
};

/// OVER protocol constants
namespace OverlayProtocol {
constexpr u32 PACKET_SIZE  = 84;       ///< total wire size
constexpr u32 MAGIC        = 0x5245564F; ///< "OVER" in little-endian
constexpr u8  PAD_ID_MAX   = 7;        ///< Player1..Player8
constexpr u32 STALENESS_US = 100'000;  ///< 100ms timeout
constexpr f32 STICK_THRESHOLD = 0.01f; ///< below this → treat as 0
constexpr f32 STICK_DIRECTION_THRESHOLD = 0.5f; ///< for setting stick digitals
} // namespace OverlayProtocol

} // namespace Core::HID
