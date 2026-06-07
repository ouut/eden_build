#!/usr/bin/env python3
"""
Verify the 84-byte OVER protocol packet format.

Tests: packet size, magic, field offsets, round-trip, control_mask bits,
stick range, u64 button_mask, pad_id validation, bad magic rejection.
"""

import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.over_sender import OverSender, PACKET_SIZE, PACKET_FMT, \
    CTRL_BUTTON, CTRL_LEFT_X, CTRL_LEFT_Y, CTRL_RIGHT_X, CTRL_RIGHT_Y, \
    CTRL_LEFT_GYRO, CTRL_LEFT_ACCEL, CTRL_RIGHT_GYRO, CTRL_RIGHT_ACCEL

PASS = 0; FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name}")
        if detail: print(f"     {detail}")

def parse(data: bytes):
    if len(data) < 84 or data[:4] != b"OVER": return None
    if data[4] > 7: return None
    ctrl, btns = struct.unpack_from("<IQ", data, 8)
    f = struct.unpack_from("<16f", data, 20)
    return {"pad_id": data[4], "control_mask": ctrl, "button_mask": btns,
        "lx": f[0], "ly": f[1], "rx": f[2], "ry": f[3],
        "lgx": f[4], "lgy": f[5], "lgz": f[6], "lax": f[7], "lay": f[8], "laz": f[9],
        "rgx": f[10], "rgy": f[11], "rgz": f[12], "rax": f[13], "ray": f[14], "raz": f[15]}

# ── Tests ──

print("=== 1. Packet size ===")
s = OverSender()
check("84 bytes", len(s.pack()) == 84)
check("PACKET_SIZE constant", PACKET_SIZE == 84)
check("struct calcsize", struct.calcsize(PACKET_FMT) == 84)

print("\n=== 2. Default values ===")
data = s.pack()
p = parse(data)
check("magic OVER", data[:4] == b"OVER")
check("pad_id=0", p["pad_id"] == 0)
check("ctrl=0", p["control_mask"] == 0)
check("btns=0", p["button_mask"] == 0)
check("sticks zero", (p["lx"],p["ly"],p["rx"],p["ry"]) == (0,0,0,0))
check("accel_z=1.0", abs(p["laz"]-1)<0.001 and abs(p["raz"]-1)<0.001)

print("\n=== 3. Field offsets ===")
s2 = OverSender(pad_id=5)
s2.control(buttons=True, left_x=True, right_y=True, right_gyro=True)
s2.buttons(A=True, B=True)
s2.stick("left", 0.5, -0.25)
data2 = s2.pack()
ctrl, btns = struct.unpack_from("<IQ", data2, 8)
# stick("left",...) auto-sets LEFT_X + LEFT_Y
expected_ctrl = CTRL_BUTTON | CTRL_LEFT_X | CTRL_LEFT_Y | CTRL_RIGHT_Y | CTRL_RIGHT_GYRO
check("pad_id @4", data2[4] == 5)
check("ctrl @8", ctrl == expected_ctrl, f"{ctrl:#x} vs {expected_ctrl:#x}")
check("btns @12", btns == 3)

print("\n=== 4. Round-trip ===")
s3 = OverSender(pad_id=3)
s3.control(buttons=True, left_x=True, left_gyro=True, left_accel=True)
s3.buttons(A=True, X=True, PLUS=True)
s3.stick("left", 0.123, -0.456)
s3.motion("left", gyro=(0.1,0.2,0.3), accel=(0.4,0.5,0.6))
p3 = parse(s3.pack())
check("pad_id", p3["pad_id"] == 3)
check("ctrl", p3["control_mask"] == s3.control_mask)
check("btns", p3["button_mask"] == 1|4|1024)
check("lx", abs(p3["lx"]-0.123)<0.001); check("ly", abs(p3["ly"]+0.456)<0.001)
check("lgx", abs(p3["lgx"]-0.1)<0.001); check("lgy", abs(p3["lgy"]-0.2)<0.001)
check("lgz", abs(p3["lgz"]-0.3)<0.001); check("lax", abs(p3["lax"]-0.4)<0.001)

print("\n=== 5. control_mask bits independent ===")
ctrl_keys = [
    ("buttons", CTRL_BUTTON), ("left_x", CTRL_LEFT_X), ("left_y", CTRL_LEFT_Y),
    ("right_x", CTRL_RIGHT_X), ("right_y", CTRL_RIGHT_Y),
    ("left_gyro", CTRL_LEFT_GYRO), ("left_accel", CTRL_LEFT_ACCEL),
    ("right_gyro", CTRL_RIGHT_GYRO), ("right_accel", CTRL_RIGHT_ACCEL),
]
for key, bit in ctrl_keys:
    s5 = OverSender(); s5.control(**{key: True})
    check(f"bit {key}", s5.control_mask == bit, f"{s5.control_mask:#x} vs {bit:#x}")

print("\n=== 6. Stick range [-1,1] ===")
for v in [-1.0, -0.5, 0.0, 0.5, 1.0]:
    s6 = OverSender(); s6.stick("left", v, v)
    p6 = parse(s6.pack())
    check(f"lx={v}", abs(p6["lx"]-v)<0.001); check(f"ly={v}", abs(p6["ly"]-v)<0.001)

print("\n=== 7. u64 button_mask high bits ===")
s7 = OverSender(); s7._button_mask = (1<<33)|1
p7 = parse(s7.pack())
check("bit33 survives", p7["button_mask"] == (1<<33)|1)

print("\n=== 8. pad_id validation ===")
for pid in range(8):
    check(f"pid={pid}", OverSender(pad_id=pid).pack()[4] == pid)
bad = bytearray(OverSender().pack()); bad[4] = 8
check("pid=8 rejected", parse(bytes(bad)) is None)
bad[4] = 0x10; check("pid=0x10 rejected", parse(bytes(bad)) is None)

print("\n=== 9. Bad inputs ===")
bad2 = bytearray(OverSender().pack()); bad2[0:4] = b"BAD!"
check("bad magic", parse(bytes(bad2)) is None)
check("83 bytes", parse(b"\x00"*83) is None)
check("empty", parse(b"") is None)

print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL: sys.exit(1)
