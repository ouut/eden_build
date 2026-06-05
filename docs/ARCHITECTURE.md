# Eden Overlay — Architecture Document

## 1. Eden's Original Input Architecture

### 1.1 Data Flow

```
Physical Input (SDL/Joycon/Keyboard)
    │
    ▼
InputEngine subclass (SDLDriver, Keyboard, UDPClient, ...)
    │  SetButton(identifier, button_index, value)
    ▼
InputDevice (created from ParamPackage via factory)
    │  callback → EmulatedController::SetButton()
    ▼
EmulatedController
    │  button_values[N] = { value, uuid }   ← ONE value per button
    │  stick_values[N]  = { x, y, uuid }    ← ONE value per stick
    ▼
HID service (npad.cpp)
    │  controller.device->GetNpadButtons()
    ▼
Game
```

### 1.2 The UUID Ownership Problem

Each button (`ButtonStatus` in `common/input.h`) stores exactly ONE `value` and ONE `uuid`:

```cpp
struct ButtonStatus {
    Common::UUID uuid{};   // who wrote last
    bool value{};          // current state (only one!)
    bool toggle{};
    bool turbo{};
    bool locked{};
};
```

When multiple input sources write to the same button, UUID arbitration decides who wins:

```
SetButton logic (emulated_controller.cpp:774-779):

if (current.uuid != incoming.uuid) {
    if (!incoming.value) {
        return;  // release from non-owner → ignored
    }
}
// press from anyone → steal ownership
current.uuid = incoming.uuid;
current.value = incoming.value;
```

**Design intent**: One player uses multiple physical devices (keyboard + mouse + gamepad)
mapped to different buttons of a single emulated controller. UUID prevents crosstalk
between devices.

**What it can't do**: Two independent intent sources controlling the SAME button
simultaneously (e.g., user hand + UDP remote input). The single-value model forces
mutual exclusion.

### 1.3 Existing Multi-Source Attempts

Eden already has TAS and Virtual Gamepad — two overlay-like systems that work
around UUID via special hardcoded UUIDs:

| System | UUID | Purpose |
|--------|------|---------|
| Normal input | Device UUID | Player's mapping |
| TAS | TAS_UUID | Record/playback |
| Virtual Gamepad | VIRTUAL_UUID | Remote control |

These coexist by using their own UUIDs, but they still **steal ownership**
from each other. Press A from TAS → TAS owns A. Press A from user → user steals
it back. No true merging.

---

## 2. What We Changed

### 2.1 New Files

| File | Purpose |
|------|---------|
| `overlay/overlay_types.h` | `OverlaySlotState` struct — per-source input slot |
| `overlay/overlay_engine.h` | `OverlayEngine` class — Lua VM + script management |
| `overlay/overlay_engine.cpp` | Implementation: Lua bindings, coroutine execution |
| `lua/examples/*.lua` | Example scripts for auto-potion, turbo, combo macros |

### 2.2 Modified Files (via patch)

| File | Change | Lines |
|------|--------|-------|
| `emulated_controller.h` | Add `#include overlay_types.h` | +1 |
| | Add `void ApplyOverlay()` method | +3 |
| | Add `std::array<OverlaySlotState, 8> overlay_slots` member | +2 |
| `emulated_controller.cpp` | Call `ApplyOverlay()` at end of `StatusUpdate()` | +1 |
| | Implement `ApplyOverlay()` (~40 lines) | +40 |
| `hid_core/CMakeLists.txt` | Add overlay source files | +3 |

**Total C++ change: ~50 lines modified, ~130 lines new**

### 2.3 New Architecture

```
Physical Input (unchanged)
    │
    ▼
EmulatedController (minimally modified)
    │
    ├── normal path: callback → SetButton → npad_button_state (unchanged)
    │
    ├── overlay path: OverlayEngine → overlay_slots[N] (new)
    │       ▲
    │       │  press("A"), sleep(ms), ...
    │   Lua scripts (per-script coroutine, per-script slot)
    │
    └── StatusUpdate():
          turbo processing (unchanged)
          motion force-update (unchanged)
          ApplyOverlay():  ← NEW — one call at the end
            for each active overlay slot:
              npad_button_state.raw |= slot.button_mask
              // sticks: last-write-wins by timestamp
```

### 2.4 Merge Logic

**Buttons**: OR-merge. If ANY source presses a button, it stays pressed.
Each source is responsible for its own press/release lifecycle.
Two sources pressing the same button simultaneously works correctly.

**Sticks**: Last-write-wins by timestamp. If two overlay sources set the left
stick, the most recently written value takes effect. If no overlay source
has stick data, the normal (physical) stick value is preserved.

**Motion**: Not handled by overlay. Physical motion input passes through unchanged.

**Staleness**: Slots inactive for >500ms are automatically deactivated.

---

## 3. What This Achieves

### 3.1 reWASD-Style Multi-Source Composition

```
reWASD model:                         Eden Overlay equivalent:
                                      
  phys keyboard W ──┐                  normal path (SDL/Joycon)
  phys controller B ─┤                   │
  virtual macro    ──┤                  overlay slot 0 (Lua script 1)
                      ├→ virtual pad    overlay slot 1 (Lua script 2)
  All sources write    │                overlay slot 2 (UDP remote)
  independently.       │                  │
  Final = OR(active)   │                ApplyOverlay():
                       │                  final = normal | slot0 | slot1 | slot2
```

### 3.2 Use Cases Enabled

- **Turbo / auto-fire**: A Lua script that repeatedly presses A while user holds L
- **Auto-potion**: Periodically presses X for health recovery
- **Combo macros**: D-pad + stick triggers a sequence of button presses
- **UDP remote input**: External DSU data injected into overlay slots
- **AI agent input**: Any external system can write to an overlay slot

### 3.3 Design Properties

- **Zero overhead when idle**: No scripts loaded → no overlay slots active → ApplyOverlay is a no-op
- **Hot-reload**: Scripts can be reloaded without restarting the emulator
- **Sandboxed**: Each script runs in its own Lua coroutine, cannot interfere with other scripts
- **Minimal patch surface**: Changes are confined to 2 functions in emulated_controller
- **Non-breaking**: All existing input mappings continue to work unchanged

---

## 4. Lua Script API

### 4.1 Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `press(name)` | `press("A")` | Hold button in this script's slot |
| `release(name)` | `release("A")` | Release button in this script's slot |
| `sleep(ms)` | `sleep(100)` | Yield coroutine for N milliseconds |
| `get_button(name)` | `get_button("A")` → bool | Read FINAL button state (after merge) |
| `get_stick(which)` | `x, y = get_stick("left")` → f32, f32 | Read FINAL stick state (after merge), range [-1, 1] |
| `set_stick(which, x, y)` | `set_stick("left", 0.5, 0)` | Set stick position for this slot |
| `udp_bind(port)` | `udp_bind(26760)` → bool | Start UDP listener on port (built-in, no deps) |
| `udp_poll()` | `udp_poll()` → str or nil | Get latest received UDP payload, nil if none |

### 4.2 Button Names

`A`, `B`, `X`, `Y`, `L`, `R`, `ZL`, `ZR`, `Plus`, `Minus`,
`DUp`, `DDown`, `DLeft`, `DRight`, `LStick`, `RStick`,
`SLLeft`, `SLRight`, `SRLeft`, `SRRight`

### 4.3 Script Template

```lua
-- Script runs as an infinite loop
while true do
    press("A")
    sleep(50)
    release("A")
    sleep(100)
end
```

---

## 5. Build Integration

The overlay uses Lua 5.4 (or LuaJIT) with its C API. No additional C++
dependencies beyond `liblua`. The `apply_overlay.sh` script:

1. Copies `overlay_*.{h,cpp}` into `eden/src/hid_core/frontend/`
2. Applies patches to `emulated_controller.{h,cpp}`
3. Adds overlay sources to `hid_core/CMakeLists.txt`
4. Verifies Lua headers are available

GitHub Actions clones Eden source, runs `apply_overlay.sh`, then builds normally.
