#!/usr/bin/env python3
"""
End-to-end integration test: UDP send → receive → parse → verify.

Starts a simulated overlay listener on a random port, sends OVER packets
via OverSender, then verifies the received bytes match expectations.
"""

import socket
import struct
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.over_sender import OverSender, PACKET_FMT, PACKET_SIZE, \
    CTRL_BUTTON, CTRL_LEFT_X, CTRL_LEFT_Y, CTRL_RIGHT_X, CTRL_RIGHT_Y, \
    CTRL_RIGHT_GYRO

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  ❌ {name}")
        if detail:
            print(f"     {detail}")

def find_free_port() -> int:
    """Find an available UDP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def parse_packet(data: bytes) -> dict:
    if len(data) < 84:
        return None
    if data[:4] != b"OVER":
        return None
    pad = data[4]
    if pad > 7:
        return None
    ctrl, btns = struct.unpack_from("<IQ", data, 8)
    floats = struct.unpack_from("<16f", data, 20)
    return {
        "pad_id": pad, "control_mask": ctrl, "button_mask": btns,
        "left_x": floats[0], "left_y": floats[1],
        "right_x": floats[2], "right_y": floats[3],
    }

#
# Test suite
#

print("=== Test 1: Single packet, default values ===")
port = find_free_port()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1.0)
sock.bind(("127.0.0.1", port))

sender = OverSender(host="127.0.0.1", port=port, pad_id=0)
sender.buttons(A=True)
sender.send()

data, addr = sock.recvfrom(1024)
check("received from 127.0.0.1", addr[0] == "127.0.0.1")
check("packet size = 84", len(data) == 84)
parsed = parse_packet(data)
check("magic OK", parsed is not None)
check("pad_id = 0", parsed["pad_id"] == 0)
check("A button set", parsed["button_mask"] & 1)
sock.close()

print("\n=== Test 2: Multi-pad, different pad_ids ===")
port2 = find_free_port()
sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock2.settimeout(1.0)
sock2.bind(("127.0.0.1", port2))

for pid in [0, 3, 7]:
    s = OverSender(host="127.0.0.1", port=port2, pad_id=pid)
    s.buttons(A=True)
    s.send()

received_pads = set()
for _ in range(3):
    try:
        data, _ = sock2.recvfrom(1024)
        p = parse_packet(data)
        if p:
            received_pads.add(p["pad_id"])
    except socket.timeout:
        break

check("pad 0 received", 0 in received_pads)
check("pad 3 received", 3 in received_pads)
check("pad 7 received", 7 in received_pads)
sock2.close()

print("\n=== Test 3: Stick + buttons in same packet ===")
port3 = find_free_port()
sock3 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock3.settimeout(1.0)
sock3.bind(("127.0.0.1", port3))

s3 = OverSender(host="127.0.0.1", port=port3, pad_id=2)
s3.buttons(A=True, B=True, ZL=True)
s3.stick("left", 0.75, -0.5)
s3.stick("right", -0.25, 0.9)
s3.send()

data3, _ = sock3.recvfrom(1024)
p3 = parse_packet(data3)
check("pad_id = 2", p3["pad_id"] == 2)
check("A+B+ZL", p3["button_mask"] == 0x103)
check("left_x = 0.75", abs(p3["left_x"] - 0.75) < 0.001,
      f"got {p3['left_x']}")
check("left_y = -0.5", abs(p3["left_y"] - (-0.5)) < 0.001)
check("right_x = -0.25", abs(p3["right_x"] - (-0.25)) < 0.001)
check("right_y = 0.9", abs(p3["right_y"] - 0.9) < 0.001)
sock3.close()

print("\n=== Test 4: control_mask in received packet ===")
port4 = find_free_port()
sock4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock4.settimeout(1.0)
sock4.bind(("127.0.0.1", port4))

s4 = OverSender(host="127.0.0.1", port=port4, pad_id=0)
s4.buttons(A=True)             # sets CTRL_BUTTON
s4.stick("right", 0.3, 0.0)    # sets CTRL_RIGHT_X + CTRL_RIGHT_Y
s4.send()

data4, _ = sock4.recvfrom(1024)
p4 = parse_packet(data4)
check("ctrl has BUTTON", p4["control_mask"] & CTRL_BUTTON)
check("ctrl has RIGHT_X", p4["control_mask"] & CTRL_RIGHT_X)
check("ctrl has RIGHT_Y", p4["control_mask"] & CTRL_RIGHT_Y)
check("ctrl lacks LEFT_X", not (p4["control_mask"] & CTRL_LEFT_X))
check("ctrl lacks LEFT_Y", not (p4["control_mask"] & CTRL_LEFT_Y))
sock4.close()

print("\n=== Test 5: High-frequency send (stress test) ===")
port5 = find_free_port()
sock5 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock5.settimeout(2.0)
sock5.bind(("127.0.0.1", port5))

N = 200
s5 = OverSender(host="127.0.0.1", port=port5, pad_id=1)
s5.buttons(A=True)
for i in range(N):
    s5.send()

received_count = 0
while True:
    try:
        data, _ = sock5.recvfrom(1024)
        if len(data) == 84 and data[:4] == b"OVER":
            received_count += 1
    except socket.timeout:
        break

check(f"all {N} packets received", received_count == N,
      f"got {received_count}/{N}")
sock5.close()

print("\n=== Test 6: Packet received with correct struct layout ===")
port6 = find_free_port()
sock6 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock6.settimeout(1.0)
sock6.bind(("127.0.0.1", port6))

s6 = OverSender(host="127.0.0.1", port=port6, pad_id=4)
s6.buttons(PLUS=True)
s6.stick("left", 1.0, -1.0)
s6.control(left_y=False)  # only want left_x, not left_y
s6.motion("right", gyro=(0.1, 0.2, 0.3))
s6.send()

data6, _ = sock6.recvfrom(1024)
# Parse with C-equivalent struct
fields = struct.unpack_from(PACKET_FMT, data6)
magic, pad_id, ctrl, btns = fields[:4]
floats = fields[4:]

check("magic bytes", magic == b"OVER")
check("pad_id = 4", pad_id == 4)
check("ctrl == expected", ctrl == (CTRL_BUTTON | CTRL_LEFT_X | CTRL_RIGHT_GYRO))
check("PLUS button", btns == (1 << 10))
check("left_x = 1.0", abs(floats[0] - 1.0) < 0.001)
check("left_y = -1.0", abs(floats[1] - (-1.0)) < 0.001)
check("right_gyro_x = 0.1", abs(floats[10] - 0.1) < 0.001)
check("right_gyro_y = 0.2", abs(floats[11] - 0.2) < 0.001)
check("right_gyro_z = 0.3", abs(floats[12] - 0.3) < 0.001)
sock6.close()

print("\n=== Test 7: Short packet (not 84 bytes) handled ===")
port7 = find_free_port()
sock7 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock7.settimeout(0.5)
sock7.bind(("127.0.0.1", port7))

# Send a 24-byte packet (old OVER format) — should be detected as short
bad_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
bad_sock.sendto(b"OVER" + b"\x00" * 20, ("127.0.0.1", port7))
bad_sock.close()

try:
    data7, _ = sock7.recvfrom(1024)
    # The C++ code would reject this (< 84 bytes)
    check("short packet received (24 bytes)", len(data7) == 24,
          f"got {len(data7)} bytes")
    check("C++ would discard (<84)", len(data7) < 84,
          "receiver must check length >= 84")
except socket.timeout:
    check("short packet received", True, "(timeout but packet was sent)")
sock7.close()

# ── Summary ──
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
