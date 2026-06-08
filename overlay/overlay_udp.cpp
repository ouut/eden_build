// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include "hid_core/frontend/overlay_udp.h"

#include <array>
#include <chrono>
#include <cstring>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
using socklen_t = int;
using ssize_t = SSIZE_T;
#define CLOSE_SOCKET closesocket
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <unistd.h>
#define CLOSE_SOCKET close
#endif

#include "common/logging.h"
#include "common/settings.h"
#include "hid_core/frontend/emulated_controller.h"
#include "hid_core/frontend/overlay_state.h"
#include "hid_core/hid_types.h"

namespace Core::HID {

// ═══════════════════════════════════════════════════════════════════════════════
// Global state
// ═══════════════════════════════════════════════════════════════════════════════

namespace {

/// Overlay state per pad (0-7).  One entry per player.
std::array<OverlayState, 8> overlay_states{};

/// Non-blocking UDP socket.  -1 when not initialized or disabled.
int overlay_socket = -1;

/// Manually pack the 84-byte OVER packet into an OverlayState.
/// Returns true on success.
bool ParsePacket(const u8* data, std::size_t len, OverlayState& out) {
    if (len < OverlayProtocol::PACKET_SIZE) {
        return false;
    }

    auto read_u32 = [&](std::size_t offset) -> u32 {
        u32 val;
        std::memcpy(&val, data + offset, sizeof(u32));
        return val;
    };
    auto read_u64 = [&](std::size_t offset) -> u64 {
        u64 val;
        std::memcpy(&val, data + offset, sizeof(u64));
        return val;
    };
    auto read_f32 = [&](std::size_t offset) -> f32 {
        f32 val;
        std::memcpy(&val, data + offset, sizeof(f32));
        return val;
    };

    // magic "OVER" at offset 0
    if (read_u32(0) != OverlayProtocol::MAGIC) {
        return false;
    }

    // pad_id at offset 4
    const u8 pad_id = data[4];
    if (pad_id > OverlayProtocol::PAD_ID_MAX) {
        return false; // Other, Handheld, or invalid
    }

    out.control_mask = read_u32(8);
    out.button_mask  = read_u64(12);

    out.left_x  = read_f32(20);
    out.left_y  = read_f32(24);
    out.right_x = read_f32(28);
    out.right_y = read_f32(32);

    out.left_gyro_x  = read_f32(36);
    out.left_gyro_y  = read_f32(40);
    out.left_gyro_z  = read_f32(44);
    out.left_accel_x = read_f32(48);
    out.left_accel_y = read_f32(52);
    out.left_accel_z = read_f32(56);

    out.right_gyro_x  = read_f32(60);
    out.right_gyro_y  = read_f32(64);
    out.right_gyro_z  = read_f32(68);
    out.right_accel_x = read_f32(72);
    out.right_accel_y = read_f32(76);
    out.right_accel_z = read_f32(80);

    out.active = true;
    return true;
}

/// Convert overlay f32 stick value to HID s32.
/// |v| < 0.01 → 0; otherwise v * 32767.
s32 ToStickS32(f32 v) {
    if (v > -OverlayProtocol::STICK_THRESHOLD && v < OverlayProtocol::STICK_THRESHOLD) {
        return 0;
    }
    return static_cast<s32>(v * 32767.0f);
}

/// Get current timestamp in microseconds from steady_clock.
u64 NowUs() {
    return static_cast<u64>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
}

} // anonymous namespace

// ═══════════════════════════════════════════════════════════════════════════════
// Public API
// ═══════════════════════════════════════════════════════════════════════════════

void InitOverlayUdp(u16 port) {
#ifdef _WIN32
    WSADATA wsa_data;
    WSAStartup(MAKEWORD(2, 2), &wsa_data);
#endif

    overlay_socket = static_cast<int>(socket(AF_INET, SOCK_DGRAM, 0));
    if (overlay_socket < 0) {
        LOG_ERROR(Service_HID, "Overlay: socket() failed");
        return;
    }

    // Non-blocking
#ifdef _WIN32
    u_long mode = 1;
    ioctlsocket(overlay_socket, FIONBIO, &mode);
#else
    const int flags = fcntl(overlay_socket, F_GETFL, 0);
    if (flags >= 0) {
        fcntl(overlay_socket, F_SETFL, flags | O_NONBLOCK);
    }
#endif

    // Reuse address (safe restart)
    const int reuse = 1;
    setsockopt(overlay_socket, SOL_SOCKET, SO_REUSEADDR,
#ifdef _WIN32
               reinterpret_cast<const char*>(&reuse),
#else
               &reuse,
#endif
               sizeof(reuse));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(overlay_socket, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        LOG_WARNING(Service_HID,
                    "Overlay: port {} is already in use, overlay disabled", port);
        CLOSE_SOCKET(overlay_socket);
        overlay_socket = -1;
        return;
    }

    LOG_INFO(Service_HID, "Overlay: listening on UDP 0.0.0.0:{}", port);
}

void ShutdownOverlayUdp() {
    if (overlay_socket >= 0) {
        CLOSE_SOCKET(overlay_socket);
        overlay_socket = -1;
        LOG_INFO(Service_HID, "Overlay: shut down");
    }
}

void ApplyOverlay(NpadIdType npad_id, ControllerStatus& controller) {
    // ── Lazy init: first call reads settings and starts UDP listener ────
    if (overlay_socket < 0) {
        if (Settings::values.overlay_enabled) {
            InitOverlayUdp(Settings::values.overlay_port);
        }
        // If still disabled (port in use or setting off), nothing to do
    }

    // ── Drain incoming UDP packets ──────────────────────────────────────
    if (overlay_socket >= 0) {
        u8 buf[OverlayProtocol::PACKET_SIZE];
        sockaddr_in from{};

        // Consume ALL buffered packets for this frame.
        // For each pad, only the last packet survives (later packets
        // overwrite earlier ones in overlay_states).
        while (true) {
            socklen_t addrlen = sizeof(from);
            const ssize_t n = recvfrom(overlay_socket,
#ifdef _WIN32
                                       reinterpret_cast<char*>(buf),
#else
                                       buf,
#endif
                                       sizeof(buf), 0,
                                       reinterpret_cast<sockaddr*>(&from), &addrlen);
            if (n <= 0) {
                break; // no more packets (EAGAIN/EWOULDBLOCK or error)
            }
            if (static_cast<std::size_t>(n) < OverlayProtocol::PACKET_SIZE) {
                continue; // runt packet, ignore
            }

            const u8 pad_id = buf[4];
            if (pad_id > OverlayProtocol::PAD_ID_MAX) {
                continue; // invalid pad
            }

            OverlayState state;
            if (ParsePacket(buf, static_cast<std::size_t>(n), state)) {
                state.last_update = NowUs();
                overlay_states[pad_id] = state;
            }
        }
    }

    // ── Map NpadIdType to pad index ─────────────────────────────────────
    const u32 pad_idx = static_cast<u32>(npad_id);
    if (pad_idx > OverlayProtocol::PAD_ID_MAX) {
        return; // Other, Handheld — no overlay
    }

    auto& state = overlay_states[pad_idx];
    if (!state.active) {
        return; // no overlay data, or stale
    }

    // ── Staleness check ─────────────────────────────────────────────────
    const u64 now = NowUs();
    if (now - state.last_update > OverlayProtocol::STALENESS_US) {
        state.active = false;
        return; // timed out — physical input fully in control
    }

    const u32 ctrl = state.control_mask;

    // ── Buttons: OR merge (bit 0) ───────────────────────────────────────
    if (ctrl & OverlayControl::BUTTON) {
        const u64 raw_val =
            static_cast<u64>(controller.npad_button_state.raw) | state.button_mask;
        controller.npad_button_state.raw = static_cast<NpadButton>(raw_val);
    }

    // ── Left stick ──────────────────────────────────────────────────────
    if (ctrl & OverlayControl::LEFT_X) {
        controller.analog_stick_state.left.x = ToStickS32(state.left_x);
    }
    if (ctrl & OverlayControl::LEFT_Y) {
        controller.analog_stick_state.left.y = ToStickS32(state.left_y);
    }

    // ── Right stick ─────────────────────────────────────────────────────
    if (ctrl & OverlayControl::RIGHT_X) {
        controller.analog_stick_state.right.x = ToStickS32(state.right_x);
    }
    if (ctrl & OverlayControl::RIGHT_Y) {
        controller.analog_stick_state.right.y = ToStickS32(state.right_y);
    }

    // ── Stick direction bits ────────────────────────────────────────────
    // Per-axis: only update direction bits for axes overlay controls.
    // Axes not controlled by overlay keep whatever Eden's SetStick wrote.
    if (ctrl & OverlayControl::LEFT_X) {
        const f32 lx = state.left_x;
        controller.npad_button_state.stick_l_right.Assign(lx > OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
        controller.npad_button_state.stick_l_left.Assign(lx < -OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
    }
    if (ctrl & OverlayControl::LEFT_Y) {
        const f32 ly = state.left_y;
        controller.npad_button_state.stick_l_up.Assign(ly > OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
        controller.npad_button_state.stick_l_down.Assign(ly < -OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
    }
    if (ctrl & OverlayControl::RIGHT_X) {
        const f32 rx = state.right_x;
        controller.npad_button_state.stick_r_right.Assign(rx > OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
        controller.npad_button_state.stick_r_left.Assign(rx < -OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
    }
    if (ctrl & OverlayControl::RIGHT_Y) {
        const f32 ry = state.right_y;
        controller.npad_button_state.stick_r_up.Assign(ry > OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
        controller.npad_button_state.stick_r_down.Assign(ry < -OverlayProtocol::STICK_DIRECTION_THRESHOLD ? 1 : 0);
    }

    // ── Left motion ─────────────────────────────────────────────────────
    if (ctrl & OverlayControl::LEFT_GYRO) {
        controller.motion_state[0].gyro.x = state.left_gyro_x;
        controller.motion_state[0].gyro.y = state.left_gyro_y;
        controller.motion_state[0].gyro.z = state.left_gyro_z;
    }
    if (ctrl & OverlayControl::LEFT_ACCEL) {
        controller.motion_state[0].accel.x = state.left_accel_x;
        controller.motion_state[0].accel.y = state.left_accel_y;
        controller.motion_state[0].accel.z = state.left_accel_z;
    }

    // ── Right motion ────────────────────────────────────────────────────
    if (ctrl & OverlayControl::RIGHT_GYRO) {
        controller.motion_state[1].gyro.x = state.right_gyro_x;
        controller.motion_state[1].gyro.y = state.right_gyro_y;
        controller.motion_state[1].gyro.z = state.right_gyro_z;
    }
    if (ctrl & OverlayControl::RIGHT_ACCEL) {
        controller.motion_state[1].accel.x = state.right_accel_x;
        controller.motion_state[1].accel.y = state.right_accel_y;
        controller.motion_state[1].accel.z = state.right_accel_z;
    }
}

} // namespace Core::HID
