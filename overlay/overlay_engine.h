// SPDX-FileCopyrightText: Copyright 2026 Eden Overlay Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "hid_core/frontend/overlay_types.h"
#include "hid_core/hid_types.h"

namespace Core::HID {

class EmulatedController;

// Lua-powered overlay input engine — one per EmulatedController (player).
//
// Public Lua API (see CLAUDE.md):
//   p = player.new(id [, slot])        → handle
//   u = player.new_udp(id, port [, slot]) → handle
//   s = player.new_script(id, path [, slot]) → handle
//   player:held(id, btn) → bool
//   player:axis(id, stick) → x,y
//   player:motion(id, stick) → gx,gy,gz,ax,ay,az
//   game:id() → u64    game:name() → str
//   wait(ms)
//
// Handle methods:
//   h:press(btn)   h:release(btn)   h:move(which, x, y)
//   h:motion(which, gx,gy,gz,ax,ay,az)   h:wait(ms)   h:kill()
class OverlayEngine {
public:
    OverlayEngine();
    ~OverlayEngine();

    OverlayEngine(const OverlayEngine&) = delete;
    OverlayEngine& operator=(const OverlayEngine&) = delete;

    // ---- C++ integration (called by HID service layer) ----

    // Bind this engine to a controller & its slots. Sets player_id from controller.
    void RegisterController(int player_id, EmulatedController* controller,
                            std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>& slots);

    // Set current game info. Call when game changes.
    void SetProgramId(u64 id)       { program_id = id; }
    void SetGameName(const std::string& n) { game_name = n; }

    // Called each frame. Resumes coroutines whose sleep() has expired.
    void Tick(u32 dt_ms);

    // ---- Internal use by Lua callbacks ----

    EmulatedController* GetController() const { return controller; }
    u64  GetProgramId()   const { return program_id; }
    std::string GetGameName() const { return game_name; }
    int  GetPlayerId()    const { return player_id; }

    std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>& overlay_slots_ref() { return *overlay_slots; }
    std::vector<ScriptState>& scripts_ref() { return scripts; }
    void* get_lua_state() { return L; }

    int  AllocateSlot();
    void ReleaseSlot(int slot);

    // Load a script file into a coroutine in the given slot.
    bool LoadScriptToSlot(const std::string& path, int slot);

    // ---- Global engine registry (for cross-player Lua access) ----

    static void RegisterGlobal(int player_id, OverlayEngine* engine);
    static void UnregisterGlobal(int player_id);
    static OverlayEngine* FindGlobal(int player_id);

private:
    void* L = nullptr;  // lua_State*
    EmulatedController* controller = nullptr;
    std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>* overlay_slots = nullptr;
    int player_id = 0;
    u64 program_id = 0;
    std::string game_name;

    struct ScriptState {
        std::string path;
        int  slot    = -1;
        int  wake_ms = 0;
        int  thread_ref = -1;
    };
    std::vector<ScriptState> scripts;
};

} // namespace Core::HID
