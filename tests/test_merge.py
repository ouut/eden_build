#!/usr/bin/env python3
"""
Simulate the C++ ApplyOverlay merge logic in Python.

Covers: staleness, buttons OR, per-axis stick overwrite, direction bits,
motion groups, control_mask gating, noise threshold.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.over_sender import OverSender, \
    CTRL_BUTTON, CTRL_LEFT_X, CTRL_LEFT_Y, CTRL_RIGHT_X, CTRL_RIGHT_Y, \
    CTRL_LEFT_GYRO, CTRL_LEFT_ACCEL, CTRL_RIGHT_GYRO, CTRL_RIGHT_ACCEL

PASS = 0; FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f"  ❌ {name}"); detail and print(f"     {detail}")

# ── Python replica of C++ ApplyOverlay ──
STICK_THR = 0.01; DIR_THR = 0.5; STALE_US = 100_000

class Ctrl:
    def __init__(self):
        self.btns = 0; self.lx=0; self.ly=0; self.rx=0; self.ry=0
        self.slr=0; self.sll=0; self.slu=0; self.sld=0
        self.srr=0; self.srl=0; self.sru=0; self.srd=0
        self.lg=(0,0,0); self.la=(0,0,1); self.rg=(0,0,0); self.ra=(0,0,1)

class Ovl:
    def __init__(self):
        self.ctrl=0; self.btns=0; self.lx=0.0; self.ly=0.0; self.rx=0.0; self.ry=0.0
        self.lg=(0,0,0); self.la=(0,0,1); self.rg=(0,0,0); self.ra=(0,0,1)
        self.last=0; self.active=False

    def load(self, sender, ts):
        self.ctrl=sender.control_mask; self.btns=sender._button_mask
        self.lx=sender._left[0]; self.ly=sender._left[1]
        self.rx=sender._right[0]; self.ry=sender._right[1]
        self.lg=sender._left_gyro; self.la=sender._left_accel
        self.rg=sender._right_gyro; self.ra=sender._right_accel
        self.last=ts; self.active=True

def to_s32(v):
    if -STICK_THR < v < STICK_THR: return 0
    return int(v * 32767.0)

def apply(c: Ctrl, o: Ovl, now):
    if not o.active: return
    if now - o.last > STALE_US: o.active=False; return
    ctrl = o.ctrl
    # buttons
    if ctrl & CTRL_BUTTON: c.btns |= o.btns
    # sticks
    if ctrl & CTRL_LEFT_X: c.lx = to_s32(o.lx)
    if ctrl & CTRL_LEFT_Y: c.ly = to_s32(o.ly)
    if ctrl & CTRL_RIGHT_X: c.rx = to_s32(o.rx)
    if ctrl & CTRL_RIGHT_Y: c.ry = to_s32(o.ry)
    # direction bits (per-axis!)
    if ctrl & CTRL_LEFT_X: c.slr = 1 if o.lx > DIR_THR else 0; c.sll = 1 if o.lx < -DIR_THR else 0
    if ctrl & CTRL_LEFT_Y: c.slu = 1 if o.ly > DIR_THR else 0; c.sld = 1 if o.ly < -DIR_THR else 0
    if ctrl & CTRL_RIGHT_X: c.srr = 1 if o.rx > DIR_THR else 0; c.srl = 1 if o.rx < -DIR_THR else 0
    if ctrl & CTRL_RIGHT_Y: c.sru = 1 if o.ry > DIR_THR else 0; c.srd = 1 if o.ry < -DIR_THR else 0
    # motion
    if ctrl & CTRL_LEFT_GYRO: c.lg = o.lg
    if ctrl & CTRL_LEFT_ACCEL: c.la = o.la
    if ctrl & CTRL_RIGHT_GYRO: c.rg = o.rg
    if ctrl & CTRL_RIGHT_ACCEL: c.ra = o.ra

# ── Tests ──
print("=== 1. Inactive → no effect ===")
c = Ctrl(); c.btns=0xFF; c.lx=10000; o = Ovl(); apply(c, o, 1000)
check("btns preserved", c.btns==0xFF); check("stick preserved", c.lx==10000)

print("\n=== 2. Staleness timeout ===")
c2=Ctrl(); o2=Ovl(); o2.active=True; o2.ctrl=CTRL_BUTTON; o2.btns=0xAA; o2.last=1000
apply(c2, o2, 200_000)
check("stale→active=false", o2.active==False); check("btns unchanged", c2.btns==0)

print("\n=== 3. Buttons OR merge ===")
c3=Ctrl(); c3.btns=1; s=OverSender(); s.buttons(B=True); o3=Ovl(); o3.load(s,1000)
apply(c3,o3,1001)
check("A (phys) + B (overlay)", c3.btns==3)

print("\n=== 4. Stick full overwrite ===")
c4=Ctrl(); c4.lx=16384; s4=OverSender(); s4.stick("left", 0.8, -0.6); o4=Ovl(); o4.load(s4,1000)
apply(c4,o4,1001)
check("lx overwritten", c4.lx==to_s32(0.8)); check("ly overwritten", c4.ly==to_s32(-0.6))
check("stick_l_right", c4.slr==1); check("stick_l_down", c4.sld==1)

print("\n=== 5. Per-axis gate (only left_x) ===")
c5=Ctrl(); c5.lx=16384; c5.ly=-16384  # phys: right+down
s5=OverSender(); s5.stick("left", 0.51, 0.0); s5.control(left_y=False)  # unset left_y
o5=Ovl(); o5.load(s5,1000)
apply(c5,o5,1001)
check("lx overwritten", c5.lx==to_s32(0.51)); check("ly preserved (phys -16384)", c5.ly==-16384, f"got {c5.ly}")
check("stick_l_right from overlay", c5.slr==1)
# overlay Y=0 but ctrl bit NOT set, so direction bit preserved from physical SetStick
# (physical had ly=-16384 which is -0.5, so stick_l_down should still be whatever phys set)
check("stick_l_down from phys", c5.sld==0)

print("\n=== 6. Zero = intentional release ===")
c6=Ctrl(); c6.lx=16384; s6=OverSender(); s6.stick("left",0.0,0.0); o6=Ovl(); o6.load(s6,1000)
apply(c6,o6,1001)
check("release→lx=0", c6.lx==0); check("release→slr=0", c6.slr==0)

print("\n=== 7. Threshold 0.01 ===")
check("0.009→0", to_s32(0.009)==0); check("-0.009→0", to_s32(-0.009)==0)
check("0.011→non0", to_s32(0.011)!=0); check("0.5→16383", to_s32(0.5)==16383, f"g={to_s32(0.5)}")

print("\n=== 8. Direction threshold 0.5 ===")
c8=Ctrl()
s8=OverSender(); s8.stick("left",0.51,-0.51); o8=Ovl(); o8.load(s8,1000)
apply(c8,o8,1001)
check("0.51→slr", c8.slr==1); check("-0.51→sld", c8.sld==1)
s8b=OverSender(); s8b.stick("left",0.49,-0.49); o8b=Ovl(); o8b.load(s8b,2000)
apply(c8,o8b,2001)
check("0.49→no slr", c8.slr==0); check("-0.49→no sld", c8.sld==0)

print("\n=== 9. Motion groups ===")
c9=Ctrl(); s9=OverSender(); s9.motion("left",gyro=(0.5,0.3,0.1)); o9=Ovl(); o9.load(s9,1000)
apply(c9,o9,1001)
check("gyro overwritten", c9.lg==(0.5,0.3,0.1)); check("accel preserved", c9.la==(0,0,1))

print("\n=== 10. Right stick independent ===")
c10=Ctrl(); c10.lx=16384
s10=OverSender(); s10.stick("right",0.7,-0.8); o10=Ovl(); o10.load(s10,1000)
apply(c10,o10,1001)
check("lx preserved", c10.lx==16384, f"got {c10.lx}")
check("rx overwritten", c10.rx==to_s32(0.7)); check("ry overwritten", c10.ry==to_s32(-0.8))

print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL: sys.exit(1)
