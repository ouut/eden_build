// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "common/common_types.h"
#include "hid_core/hid_types.h"   // NpadIdType

namespace Core::HID {

struct ControllerStatus;

/**
 * Initialize the overlay UDP listener on the given port.
 * Creates a non-blocking socket bound to 0.0.0.0:<port>.
 * Call once at emulator startup.  Safe to call when overlay is disabled
 * (no socket is created).
 *
 * @param port  UDP port to listen on (1024-65535)
 */
void InitOverlayUdp(u16 port);

/**
 * Drain incoming OVER protocol packets for every pad and apply overlay
 * state to the controller.  Called once per frame from StatusUpdate().
 *
 * For each pad (0-7):
 *   1. Check staleness (100ms timeout) → reset if stale
 *   2. For each field whose control_mask bit is set, overwrite the
 *      corresponding ControllerStatus member:
 *        - button_mask  → OR into npad_button_state.raw
 *        - stick axes   → write analog_stick_state + direction bits
 *        - motion groups→ write motion_state
 *
 * @param npad_id     This controller's NpadIdType (Player1..Player8)
 * @param controller  The controller's status struct (read/write)
 */
void ApplyOverlay(NpadIdType npad_id, ControllerStatus& controller);

/**
 * Shut down the overlay UDP listener.
 * Closes the socket.  Safe to call multiple times.
 */
void ShutdownOverlayUdp();

} // namespace Core::HID
