// SPDX-FileCopyrightText: Copyright 2026 Eden Overlay Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "common/common_types.h"

namespace Core::HID {

constexpr std::size_t MAX_OVERLAY_SOURCES = 8;

// One overlay source slot. Each script/UDP/input injector occupies one slot.
// Slots are independent — they do not interfere with each other.
struct OverlaySlotState {
    u32 button_mask{0};    // bitmap of NativeButton::Values
    f32 left_x{0.0f};      // left stick, range [-1.0, 1.0]
    f32 left_y{0.0f};
    f32 right_x{0.0f};     // right stick
    f32 right_y{0.0f};
    u64 last_update{0};     // microseconds since epoch, for staleness detection
    bool active{false};     // whether this slot is occupied
};

} // namespace Core::HID
