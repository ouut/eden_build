#!/usr/bin/env python3
"""
Interactive console for sending OVER protocol packets via keyboard.
Uses pynput for reliable cross-platform key handling.

Usage:
  pip install pynput
  python3 over_console.py                  # default: localhost:26760 pad 0
  python3 over_console.py -p 1              # pad 1
  python3 over_console.py --host 10.0.0.5   # remote Eden

Controls:
  W/A/S/D     left stick          U/J         A / B
  I/J/K/L     right stick         Y/H         X / Y
  Arrows      D-Pad               R/T         L / R
  TAB         cycle pad (0-7)     Q/E         ZL / ZR
  ESC         quit                1/2         L3/R3
  LSHIFT      half-stick          -/=         MINUS/PLUS
"""

import argparse
import socket
import struct
import sys
import time
import threading

try:
    from pynput.keyboard import Key, KeyCode, Listener
except ImportError:
    print("pynput not installed. Run: pip install pynput")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# OVER Protocol constants
# ═══════════════════════════════════════════════════════════════════════════════

PACKET_FMT = "<4sB3xIQ16f"
CTRL_BUTTON      = 1 << 0
CTRL_LEFT_X      = 1 << 1
CTRL_LEFT_Y      = 1 << 2
CTRL_RIGHT_X     = 1 << 3
CTRL_RIGHT_Y     = 1 << 4
CTRL_LEFT_GYRO   = 1 << 5
CTRL_LEFT_ACCEL  = 1 << 6
CTRL_RIGHT_GYRO  = 1 << 7
CTRL_RIGHT_ACCEL = 1 << 8

BUTTON_BITS = {
    "A": 1<<0, "B": 1<<1, "X": 1<<2, "Y": 1<<3,
    "STICK_L": 1<<4, "STICK_R": 1<<5,
    "L": 1<<6, "R": 1<<7, "ZL": 1<<8, "ZR": 1<<9,
    "PLUS": 1<<10, "MINUS": 1<<11,
    "LEFT": 1<<12, "UP": 1<<13, "RIGHT": 1<<14, "DOWN": 1<<15,
}

# ═══════════════════════════════════════════════════════════════════════════════
# Key → action mapping (pynput KeyCode/Key → overlay action)
# ═══════════════════════════════════════════════════════════════════════════════

def kc(char): return KeyCode.from_char(char)

KEY_MAP = {
    # Left stick
    kc('w'): ("stick", "left", "up"),     kc('s'): ("stick", "left", "down"),
    kc('a'): ("stick", "left", "left"),   kc('d'): ("stick", "left", "right"),
    # Right stick
    kc('i'): ("stick", "right", "up"),    kc('k'): ("stick", "right", "down"),
    kc('j'): ("stick", "right", "left"),  kc('l'): ("stick", "right", "right"),
    # Buttons
    kc('u'): ("button", "A"),  kc('j'): ("button", "B"),
    kc('y'): ("button", "X"),  kc('h'): ("button", "Y"),
    kc('r'): ("button", "L"),  kc('t'): ("button", "R"),
    kc('q'): ("button", "ZL"), kc('e'): ("button", "ZR"),
    kc('1'): ("button", "STICK_L"), kc('2'): ("button", "STICK_R"),
    kc('-'): ("button", "MINUS"), kc('='): ("button", "PLUS"),
    # D-Pad
    Key.up:    ("button", "UP"),    Key.down:  ("button", "DOWN"),
    Key.left:  ("button", "LEFT"),  Key.right: ("button", "RIGHT"),
}

STICK_FULL = 1.0
STICK_HALF = 0.5


class OverConsole:
    def __init__(self, host="127.0.0.1", port=26760, pad_id=0):
        self.host = host
        self.port = port
        self.active_pad = pad_id
        self._ctrl = 0; self._btns = 0
        self._lx = 0.0; self._ly = 0.0; self._rx = 0.0; self._ry = 0.0
        self._lg = (0.0,0.0,0.0); self._la = (0.0,0.0,1.0)
        self._rg = (0.0,0.0,0.0); self._ra = (0.0,0.0,1.0)
        self._keys = set()  # currently held KeyCode/Key
        self._shift = False
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _send(self):
        mod = Key.shift in self._keys or Key.shift_r in self._keys
        val = STICK_HALF if mod else STICK_FULL
        self._ctrl = CTRL_BUTTON | CTRL_LEFT_X | CTRL_LEFT_Y | CTRL_RIGHT_X | CTRL_RIGHT_Y
        self._btns = 0
        self._lx = self._ly = self._rx = self._ry = 0.0

        for k in self._keys:
            act = KEY_MAP.get(k)
            if not act: continue
            if act[0] == "stick":
                _, side, d = act
                if d == "up":    setattr(self, f"_{'l' if side=='left' else 'r'}{'y'}", val)
                elif d == "down":  setattr(self, f"_{'l' if side=='left' else 'r'}{'y'}", -val)
                elif d == "left":  setattr(self, f"_{'l' if side=='left' else 'r'}{'x'}", -val)
                elif d == "right": setattr(self, f"_{'l' if side=='left' else 'r'}{'x'}", val)
            elif act[0] == "button":
                self._btns |= BUTTON_BITS.get(act[1], 0)

        data = struct.pack(PACKET_FMT,
            b"OVER", self.active_pad, self._ctrl, self._btns,
            self._lx, self._ly, self._rx, self._ry,
            *self._lg, *self._la, *self._rg, *self._ra)
        self._sock.sendto(data, (self.host, self.port))

    def _on_press(self, key):
        if key == Key.esc:
            self._running = False
            return False  # stop listener
        if key == Key.tab:
            self.active_pad = (self.active_pad + 1) % 8
            print(f"\rpad={self.active_pad}  ", end="", flush=True)
            return
        if key in self._keys:
            return  # auto-repeat (shouldn't happen with pynput, but safe)
        self._keys.add(key)
        self._send()
        self._print_state()

    def _on_release(self, key):
        self._keys.discard(key)
        self._send()
        self._print_state()

    def _print_state(self):
        parts = []
        for k in sorted(self._keys, key=str):
            act = KEY_MAP.get(k)
            if act:
                if act[0] == "button": parts.append(act[1])
                elif act[0] == "stick": parts.append(f"{act[1][0].upper()}S-{act[2][:2]}")
        label = ",".join(parts) if parts else "(idle)"
        mod = " [HALF]" if (Key.shift in self._keys or Key.shift_r in self._keys) else ""
        print(f"\rpad={self.active_pad} [{label}]{mod}   ", end="", flush=True)

    def start(self):
        self._running = True
        print(f"OVER Console → {self.host}:{self.port}  pad={self.active_pad}")
        print("Press keys to control. ESC to quit, TAB to cycle pad.")
        print()
        with Listener(on_press=self._on_press, on_release=self._on_release) as listener:
            listener.join()
        self._sock.close()
        print("\nDone.")


def main():
    p = argparse.ArgumentParser(description="OVER Protocol Console (pynput)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=26760)
    p.add_argument("-p", "--pad", type=int, default=0)
    args = p.parse_args()
    OverConsole(host=args.host, port=args.port, pad_id=args.pad).start()


if __name__ == "__main__":
    main()
