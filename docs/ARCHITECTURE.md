# Eden Overlay — Architecture

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
    │  motion_state[0/1] = { gyro, accel }  ← ONE value per joycon
    ▼
HID service (npad.cpp)
    │  controller.device->GetNpadButtons(), GetSticks(), GetMotions()
    ▼
Game
```

### 1.2 The UUID Ownership Problem

Each button stores exactly ONE `value` and ONE `uuid`:

```cpp
struct ButtonStatus {
    Common::UUID uuid{};   // who wrote last
    bool value{};          // current state
    bool toggle{};
    bool turbo{};
    bool locked{};
};
```

Multiple sources writing to the same button → UUID arbitration decides who wins:

```cpp
// SetButton logic (emulated_controller.cpp):
if (current.uuid != incoming.uuid) {
    if (!incoming.value) return;  // release from non-owner → ignored
}
current.uuid = incoming.uuid;     // press from anyone → steal ownership
current.value = incoming.value;
```

**What this can't do**: Two independent sources controlling the SAME button
simultaneously (e.g., user press + script press). UUID forces mutual exclusion.

### 1.3 Existing Workarounds

Eden has TAS and Virtual Gamepad — hardcoded UUIDs that coexist but still steal ownership:

| System | UUID | Purpose |
|--------|------|---------|
| Normal input | Device UUID | Player's mapping |
| TAS | TAS_UUID | Record/playback |
| Virtual Gamepad | VIRTUAL_UUID | Remote control |

Press A from TAS → TAS owns A. Press A from user → user steals it back. No true merging.

---

## 2. Solution: Per-Slot State + Final Merge

### 2.1 Core Idea

Instead of fighting UUID, overlay writes to **separate slots**. At end of each frame,
`ApplyOverlay()` merges all active slots into the final controller state.

```
Physical Input (SetButton → button_values, stick_values, motion_state)
    │
    ▼
EmulatedController (minimally modified)
    │
    ├── normal path: SetButton → npad_button_state (unchanged)
    │
    ├── overlay path:  OverlayEngine → overlay_slots[0..7] (new)
    │
    └── StatusUpdate():
          turbo + motion force-update (unchanged)
          ApplyOverlay():          ← NEW — one call, end of frame
            for each active slot:
              buttons: OR-merge
              sticks:  last-write-wins by timestamp
              motion:  last-write-wins by timestamp
```

### 2.2 OverlaySlotState

```cpp
struct OverlaySlotState {
    u32 button_mask{0};          // OR-merged
    f32 left_x{0},  left_y{0};   // last-write-wins
    f32 right_x{0}, right_y{0};
    f32 left_gyro_x{0}, ..., left_accel_z{0};   // 6 values × 2 joycons
    f32 right_gyro_x{0}, ..., right_accel_z{0};
    u64 last_update{0};          // timestamp for staleness + last-write-wins
    bool active{false};
};
```

Max 8 slots. Each Lua handle (`player.new` / `player.new_udp` / `player.new_script`)
occupies one slot. Slots are independent.

### 2.3 Merge Logic

**Buttons**: OR-merge. If ANY slot sets a button bit, it stays pressed.
Each script manages its own press/release lifecycle within its slot.

**Sticks**: Last-write-wins by `last_update` timestamp. Non-zero check prevents
zero-overwrite when a slot hasn't set a stick.

**Motion**: Same last-write-wins as sticks. Left/right joycons tracked independently.
Non-zero check across all 6 components (gyro x/y/z + accel x/y/z).

**Staleness**: Slot without update for >500ms → auto-deactivated.

---

## 3. Multi-Player: Global Engine Registry

### 3.1 Architecture

```
  Lua side (main.lua):
    p = player.new(1)  →  routes to engine[0], writes to controller[0] slot
    p = player.new(2)  →  routes to engine[1], writes to controller[1] slot

  C++ side:
    std::map<int, OverlayEngine*> g_engines;
    // player_id → OverlayEngine* (mutex-protected)
```

`player_id` is always explicit. No implicit "current player." Each
`OverlayEngine` binds to exactly one `EmulatedController`. Lua reaches
any player via `player:held(id, btn)`, `player:axis(id, stick)`, etc.

### 3.2 Per-Player Setup

```cpp
// HID service layer
auto& engine = engines[player_id];
engine.RegisterController(player_id, &controller, controller.overlay_slots);
engine.SetProgramId(title_id);
engine.SetGameName(name);
// engine.Tick(dt_ms) called each frame
```

Each engine owns one `lua_State*`. The first engine to register initializes
the Lua environment (creates `player`, `game` tables, handle metatable).
All engines share the global registry for cross-player access.

---

## 4. Lua Runtime

### 4.1 Object Model

```
player = module (factory + read)
  ├── player.new(id, [slot])       → handle (manual input)
  ├── player.new_udp(id, port, [slot]) → handle (UDP source)
  ├── player.new_script(id, path, [slot]) → handle (Lua coroutine)
  ├── player:held(id, btn)         → bool
  ├── player:axis(id, which)       → x, y
  └── player:motion(id, which)     → gx,gy,gz,ax,ay,az

handle = userdata (metatable: "OverlayHandle")
  ├── h:press(btn)
  ├── h:release(btn)
  ├── h:move(which, x, y)
  ├── h:motion(which, gx,gy,gz,ax,ay,az)
  ├── h:wait(ms)                  -- yield coroutine
  ├── h:recv() → string or nil    -- UDP only
  └── h:kill()                    -- release slot, stop UDP thread

game = table
  ├── game:id()   → u64
  └── game:name() → string

wait(ms)  -- global coroutine yield
```

### 4.2 Coroutine Model

`player.new_script(id, path)` loads a Lua file into a new coroutine:

```lua
-- Script file (e.g., turbo.lua)
-- Gets globals pre-bound to its slot:
--   press(btn), release(btn), move(which, x, y)
--   motion(which, gx,gy,gz,ax,ay,az), wait(ms)

while true do
    if player:held(1, "L") then
        press("A")
        wait(50)
        release("A")
        wait(50)
    end
    wait(16)
end
```

`wait(ms)` yields the coroutine. `OverlayEngine::Tick(dt_ms)` resumes coroutines
whose sleep has expired. If a coroutine exits (returns instead of yielding),
it's automatically wrapped in `while true do ... wait(0) end`.

### 4.3 UDP Bridge

`player.new_udp(id, port)` creates a handle with a background thread:

```
Lua:  u = player.new_udp(1, 26760)
C++:  UdpState { socket, worker thread, buffer, fresh flag }

Lua:  data = u:recv()   →  newest packet or nil
C++:  UdpState::take()  →  atomically swap buffer
```

The worker thread runs `recvfrom()` in a loop, storing the latest packet.
`u:recv()` drains the buffer. No Lua dependencies, no blocking.

### 4.4 Script Exit Behavior

If a script loaded by `new_script` returns (instead of yielding forever):

```lua
-- This returns after one iteration → engine wraps it
for i = 1, 3 do
    press("A"); wait(50); release("A"); wait(50)
end
-- Implicit return → engine wraps in: while true do loadfile(path) wait(0) end
```

---

## 5. Files Changed

### 5.1 New Files

| File | Purpose |
|------|---------|
| `overlay/overlay_types.h` | `OverlaySlotState` struct |
| `overlay/overlay_engine.h` | `OverlayEngine` class |
| `overlay/overlay_engine.cpp` | Lua bindings, coroutine engine, UDP bridge, global registry |
| `lua/examples/*.lua` | 8 example scripts covering all API |

### 5.2 Patched Files

| File | Change |
|------|--------|
| `emulated_controller.h` | `#include overlay_types.h`, `ApplyOverlay()`, `overlay_slots` member |
| `emulated_controller.cpp` | Call `ApplyOverlay()` at end of `StatusUpdate()`, implement ~70-line merge function |
| `cpmfile.json` | Add Lua v5.4.7 dependency |
| `externals/CMakeLists.txt` | Build Lua as static library via CPM |
| `hid_core/CMakeLists.txt` | Add overlay sources, link `lua` |

**Total C++ change: ~100 lines new, ~55 lines patched**

### 5.3 Build Integration

```bash
./scripts/apply_overlay.sh /path/to/eden/source
```

Applies 5 patches (`emulated_controller.h`, `emulated_controller.cpp`,
`cpmfile.json`, `externals/CMakeLists.txt`, `hid_core/CMakeLists.txt`)
and copies overlay source files. Lua is fetched via CPM (v5.4.7, SHA512
verified), built as static library, linked into `hid_core`.

---

## 6. What This Enables

- **Turbo / auto-fire**: Script repeatedly presses A while user holds L
- **Auto-potion**: Periodically presses X for health recovery
- **Combo macros**: Stick + button combos, direction-triggered sequences
- **Motion aim assist**: Read gyro, write counter-motion, nudge sticks
- **UDP remote input**: Custom protocol over UDP, 24-byte packet format
- **Per-game profiles**: `game:id()` / `game:name()` for game-specific logic
- **Cross-player coordination**: `player:held(2, "A")` to read another player

### Design Properties

- **Zero overhead when idle**: No scripts → no active slots → ApplyOverlay no-op
- **Hot-reload**: Scripts reloaded without restarting emulator
- **Sandboxed**: Each script in its own coroutine, cannot interfere with others
- **Minimal C++**: All logic in Lua; C++ is pure transport + merge
- **Non-breaking**: Existing input mappings continue to work unchanged
- **Last-write-wins**: Multiple slots writing same field → timestamp arbitration
