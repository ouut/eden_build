// SPDX-FileCopyrightText: Copyright 2026 Eden Overlay Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <string>
#include <vector>

#include "hid_core/frontend/overlay_types.h"
#include "hid_core/hid_types.h"

namespace Core::HID {

class EmulatedController;

// Lua-powered overlay input engine.
//
// Each loaded Lua script runs in its own coroutine and owns one OverlaySlotState.
// Multiple scripts can control the same buttons simultaneously — their masks are
// OR-merged at apply time. This gives reWASD-style multi-source composition.
//
// Usage:
//   OverlayEngine engine;
//   engine.RegisterController(&controller, controller.overlay_slots);
//   engine.LoadScript("scripts/turbo_attack.lua");
//   // ... each frame ...
//   engine.Tick(dt_ms);
//   // controller.ApplyOverlay() is called inside StatusUpdate
class OverlayEngine {
public:
    OverlayEngine();
    ~OverlayEngine();

    // Bind to an EmulatedController and its overlay slots array.
    // Must be called before LoadScript().
    void RegisterController(EmulatedController* controller,
                            std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>& slots);

    // Load a Lua script. Returns true on success.
    // Script should be an infinite loop using sleep() for timing:
    //
    //   while true do
    //       press("A"); sleep(50); release("A"); sleep(100)
    //   end
    bool LoadScript(const std::string& path);

    // Unload a script by path.
    void UnloadScript(const std::string& path);

    // Hot-reload all loaded scripts.
    void ReloadAll();

    // Called each frame. Resumes scripts whose sleep() has expired.
    void Tick(u32 dt_ms);

    // For internal use by Lua callbacks.
    EmulatedController* GetController() { return controller; }

private:
    int  AllocateSlot();
    void ReleaseSlot(int slot);

    struct ScriptState {
        std::string path;
        int  slot    = -1;   // index into overlay_slots
        int  wake_ms = 0;     // remaining sleep time
        int  thread_ref = -1; // Lua registry ref for the lua_State* thread
    };

    void* L = nullptr;  // lua_State*
    std::vector<ScriptState> scripts;
    EmulatedController* controller = nullptr;
    std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>* overlay_slots = nullptr;
};

} // namespace Core::HID
