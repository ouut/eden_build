# Eden Overlay C++

A pure C++ external input overlay layer. Receives OVER protocol packets via UDP, merges them with physical controller input in real time, and drives any player slot in the Eden Switch emulator.

**Core scenario**: Player holds a physical Joy-Con while a phone/script sends UDP to supplement extra sticks, buttons, or motion. Physical and overlay inputs blend seamlessly, with per-axis independent control.

## Protocol

```
84-byte UDP packet, little-endian
┌──────┬──────┬──────────┬──────────────┬──────────────┬──────────────┬──────────────────────────┐
│ OVER │ pad  │ reserved │ control_mask │ button_mask  │ left_x left_y│ left/right gyro + accel │
│ 4B   │ 1B   │ 3B       │ u32          │ u64          │ right_x ry   │ 12×f32 = 48B            │
└──────┴──────┴──────────┴──────────────┴──────────────┴──────────────┴──────────────────────────┘
```

`control_mask` declares which fields the overlay controls (bit 0=buttons, 1-4=4 stick axes, 5-8=motion groups). Set bits take effect from overlay; unset bits preserve physical input.

See [CLAUDE.md](CLAUDE.md) for details.

## Directory Structure

```
overlay_cpp/
├── overlay/                    # New files — copy into Eden
│   ├── overlay_state.h         #   OverlayState struct + constants
│   ├── overlay_udp.h           #   InitOverlayUdp / ApplyOverlay declarations
│   └── overlay_udp.cpp         #   UDP socket + protocol parsing + merge logic
├── patches_v0.2.1/             # Modified files for Eden v0.2.1 (full replacement)
│   ├── files/                  #   6 modified Eden source files (direct cp)
│   └── apply_changes.sh        #   Modification reference (sed script)
├── scripts/
│   ├── over_console.py         #   Keyboard → OVER protocol interactive console (tkinter)
│   ├── over_sender.py          #   OVER protocol packet builder/sender library
│   ├── over_test.py            #   Auto diagnostics script (6 test packets)
│   └── apply_overlay.sh        #   One-click integration script (cp files into eden_build)
├── tests/                      #   Python test suite (113 tests)
└── CLAUDE.md                   #   Complete design documentation
```

## Quick Start

### 1. Download Build Artifacts

From GitHub Actions → **Overlay C++ v0.2.1** workflow, download the build artifact for your platform.

### 2. Enable Overlay

- Eden → Settings → Input → Advanced → Other
- Check **"Enable overlay input (UDP)"**
- Default port 26760
- Click Apply
- Launch a game

### 3. Send Input

**Interactive console (keyboard emulation):**

```bash
python3 scripts/over_console.py                  # pad 0, localhost
python3 scripts/over_console.py -p 1              # pad 1
python3 scripts/over_console.py --host 10.0.0.5   # remote host
```

| Key | Action |
|------|------|
| WASD | Left stick |
| IJKL | Right stick |
| U/J | A / B |
| Y/H | X / Y |
| R/T | L / R |
| Q/E | ZL / ZR |
| 1/2 | L3 / R3 |
| -/= | MINUS / PLUS |
| Arrow keys | D-Pad |
| Shift | Half-tilt stick |
| Tab | Switch pad (0-7) |
| Esc | Quit |

**Diagnostics script (no keyboard needed):**

```bash
python3 scripts/over_test.py                    # Auto-send 6 test packets
python3 scripts/over_test.py 192.168.1.5 26760  # Specify IP and port
```

**As a Python library:**

```python
from scripts.over_sender import OverSender

s = OverSender(pad_id=0, host="127.0.0.1", port=26760)
s.buttons(A=True, B=True)          # Buttons
s.stick("left", 0.5, 0)            # Left stick half-tilt right
s.stick("right", 0, 0.8)           # Right stick upward
s.motion("left", gyro=(0.1,0,0))   # Left gyro
s.send()                            # Send 84-byte packet
```

## Local Integration (Developers)

Integrate overlay into a local Eden source tree:

```bash
./scripts/apply_overlay.sh /path/to/eden_build
```

Performs 9 file operations: 3 new files (overlay/*.h *.cpp) + 6 file replacements (patches_v0.2.1/files/).

## CI Builds

3 independent workflows, each on its own branch:

| Workflow | Branch | Description |
|----------|------|------|
| **DSU Build** | `master` | Eden + DSU protocol patch |
| **Overlay Build** | `overlay` | Eden + Lua overlay |
| **Overlay C++ v0.2.1** | `overlay_cpp` | Eden v0.2.1 + C++ overlay |

Each workflow is manually triggered. Download build artifacts from the Actions page. No automatic releases.

## Adapting to New Versions

When Eden releases a new version (e.g. v0.3.0):

```bash
# 1. Get the new source
git clone --branch v0.3.0 https://git.eden-emu.dev/eden-emu/eden.git

# 2. Create the corresponding directory
mkdir -p patches_v0.3.0/files

# 3. Copy the 6 source files that need modification
cp eden/src/common/settings.h                         patches_v0.3.0/files/
cp eden/src/hid_core/frontend/emulated_controller.h   patches_v0.3.0/files/
cp eden/src/hid_core/frontend/emulated_controller.cpp patches_v0.3.0/files/
cp eden/src/hid_core/CMakeLists.txt                   patches_v0.3.0/files/CMakeLists_hid_core.txt
cp eden/src/yuzu/configuration/configure_input_advanced.ui  patches_v0.3.0/files/
cp eden/src/yuzu/configuration/configure_input_advanced.cpp patches_v0.3.0/files/

# 4. Apply modifications manually, referencing patches_v0.2.1/apply_changes.sh
# 5. Create an overlay_cpp_v0.3.0.yml workflow
```

## Design Decisions

| # | Question | Answer |
|---|------|------|
| 1 | button_mask type | u64 (matches Eden NpadButtonState.raw) |
| 2 | OverlayState location | Global array, not owned by controller |
| 3 | Physical/overlay timestamps | Not used — overlay active → direct write, staleness is the exit |
| 4 | Stick direction bits | ApplyOverlay syncs with threshold 0.5 |
| 5 | Motion write path | Direct write to ControllerStatus.motion_state |
| 6 | Thread safety | Single-threaded, non-blocking recvfrom |
| 7 | Socket lifecycle | Module-level static, lazy init via InitOverlayUdp |
| 8 | Integration method | Full file replacement, no diff patches |
| 9 | Port conflict detection | Test bind on UI Apply, alert on failure |
| 10 | pad_id out of range | Clamp 0-7 |

See [CLAUDE.md](CLAUDE.md) for details.

## License

GPLv3. Based on [Eden Emulator](https://git.eden-emu.dev/eden-emu/eden).
