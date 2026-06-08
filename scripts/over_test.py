#!/usr/bin/env python3
"""
Diagnostic script for OVER protocol overlay.
Tests UDP connectivity without needing keyboard input.
"""

import socket
import struct
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 26760
PAD = int(sys.argv[3]) if len(sys.argv) > 3 else 0

def pack(pad, ctrl, btns, lx, ly, rx, ry):
    return struct.pack("<4sB3xIQ16f", b"OVER", pad, ctrl, btns,
        lx, ly, rx, ry,
        0,0,0, 0,0,1,   # left gyro=0, accel=(0,0,1)
        0,0,0, 0,0,1)   # right same

CTRL_B   = 1<<0
CTRL_LX  = 1<<1
CTRL_LY  = 1<<2
CTRL_RX  = 1<<3
CTRL_RY  = 1<<4

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Target: {HOST}:{PORT}  pad={PAD}")
print(f"Packet size: {struct.calcsize('<4sB3xIQ16f')} bytes")
print()

# ── Test 1: Send a button press (A) ──────────────────────────────────────
print("Test 1: Press A (button_mask=1, control_mask=1)")
data = pack(PAD, CTRL_B, 1, 0,0, 0,0)
sock.sendto(data, (HOST, PORT))
print(f"  Sent {len(data)} bytes: magic={data[:4]} pad={data[4]} ctrl=0x{struct.unpack_from('<I',data,8)[0]:x} btn=0x{struct.unpack_from('<Q',data,12)[0]:x}")
print("  Expected: A button held down")
time.sleep(0.5)

# ── Test 2: Release A ────────────────────────────────────────────────────
print("Test 2: Release A (button_mask=0, control_mask=1)")
data = pack(PAD, CTRL_B, 0, 0,0, 0,0)
sock.sendto(data, (HOST, PORT))
print("  Expected: A button released")
time.sleep(0.5)

# ── Test 3: Push left stick right ────────────────────────────────────────
print("Test 3: Left stick right (lx=1.0, control_mask=0x6)")
data = pack(PAD, CTRL_LX|CTRL_LY, 0, 1.0, 0.0, 0, 0)
sock.sendto(data, (HOST, PORT))
print("  Expected: character moves right")
time.sleep(1)

# ── Test 4: Center left stick ────────────────────────────────────────────
print("Test 4: Center left stick (lx=0, ly=0)")
data = pack(PAD, CTRL_LX|CTRL_LY, 0, 0.0, 0.0, 0, 0)
sock.sendto(data, (HOST, PORT))
print("  Expected: character stops moving")
time.sleep(0.5)

# ── Test 5: Right stick up ───────────────────────────────────────────────
print("Test 5: Right stick up (ry=1.0, control_mask=0x18)")
data = pack(PAD, CTRL_RX|CTRL_RY, 0, 0,0, 0.0, 1.0)
sock.sendto(data, (HOST, PORT))
print("  Expected: camera/aim moves up")
time.sleep(1)

# ── Test 6: Release everything ───────────────────────────────────────────
print("Test 6: Release everything")
data = pack(PAD, CTRL_B|CTRL_LX|CTRL_LY|CTRL_RX|CTRL_RY, 0, 0,0, 0,0)
sock.sendto(data, (HOST, PORT))
print("  Expected: all inputs released")
time.sleep(0.5)

# ── Done ─────────────────────────────────────────────────────────────────
print()
print("Tests complete.")
print()
print("If nothing happened in Eden:")
print("  1. Is 'Enable overlay input (UDP)' checked in Settings > Input > Advanced > Other?")
print("  2. Did you click Apply?")
print("  3. Is a GAME running? (overlay only works when a game is active)")
print("  4. Is the port correct? (default 26760)")
print("  5. Did Eden restart after setting the port? (lazy init on first game frame)")
sock.close()
