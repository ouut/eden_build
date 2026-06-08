#!/usr/bin/env python3
"""
Interactive console for sending OVER protocol packets via keyboard.
Standalone — no dependencies on other project files.

Usage:
  python3 over_console.py                  # default: localhost:26760 pad 0
  python3 over_console.py -p 1              # pad 1
  python3 over_console.py --host 10.0.0.5   # remote Eden instance

Controls (press to activate, release to deactivate):
  W/A/S/D     left stick
  I/J/K/L     right stick
  U/J         A / B
  Y/H         X / Y
  R/T         L / R
  Q/E         ZL / ZR
  1/2         L3 / R3
  -/=         MINUS / PLUS
  Arrows      D-Pad
  TAB         cycle active pad (0-7)
  ESC         quit

Hold LEFT SHIFT for half-stick (modifier, scale 0.5).

Uses tkinter for proper key-down/key-up events.
"""

import argparse
import socket
import struct
import sys
import tkinter as tk

# ═══════════════════════════════════════════════════════════════════════════════
# OVER Protocol constants
# ═══════════════════════════════════════════════════════════════════════════════

PACKET_FMT = "<4sB3xIQ16f"
PACKET_SIZE = struct.calcsize(PACKET_FMT)  # 84

# control_mask bits
CTRL_BUTTON      = 1 << 0
CTRL_LEFT_X      = 1 << 1
CTRL_LEFT_Y      = 1 << 2
CTRL_RIGHT_X     = 1 << 3
CTRL_RIGHT_Y     = 1 << 4
CTRL_LEFT_GYRO   = 1 << 5
CTRL_LEFT_ACCEL  = 1 << 6
CTRL_RIGHT_GYRO  = 1 << 7
CTRL_RIGHT_ACCEL = 1 << 8

# Switch NpadButton bit layout
BUTTON_BITS = {
    "A": 1 << 0,  "B": 1 << 1,  "X": 1 << 2,  "Y": 1 << 3,
    "STICK_L": 1 << 4,  "STICK_R": 1 << 5,
    "L": 1 << 6,  "R": 1 << 7,  "ZL": 1 << 8,  "ZR": 1 << 9,
    "PLUS": 1 << 10,  "MINUS": 1 << 11,
    "LEFT": 1 << 12,  "UP": 1 << 13,  "RIGHT": 1 << 14,  "DOWN": 1 << 15,
}

# ═══════════════════════════════════════════════════════════════════════════════
# Key → overlay action mapping
# ═══════════════════════════════════════════════════════════════════════════════

KEY_MAP = {
    # Left stick (WASD)
    "w": ("stick", "left",  "up"),     "s": ("stick", "left",  "down"),
    "a": ("stick", "left",  "left"),   "d": ("stick", "left",  "right"),
    # Right stick (IJKL)
    "i": ("stick", "right", "up"),     "k": ("stick", "right", "down"),
    "j": ("stick", "right", "left"),   "l": ("stick", "right", "right"),
    # Buttons
    "u": ("button", "A"),    "j": ("button", "B"),
    "y": ("button", "X"),    "h": ("button", "Y"),
    "r": ("button", "L"),    "t": ("button", "R"),
    "q": ("button", "ZL"),   "e": ("button", "ZR"),
    "1": ("button", "STICK_L"),  "2": ("button", "STICK_R"),
    "minus":     ("button", "MINUS"),    "equal":     ("button", "PLUS"),
    # D-Pad
    "Up":    ("button", "UP"),     "Down":  ("button", "DOWN"),
    "Left":  ("button", "LEFT"),   "Right": ("button", "RIGHT"),
}

STICK_FULL = 1.0
STICK_HALF = 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# OverConsole
# ═══════════════════════════════════════════════════════════════════════════════

class OverConsole:
    def __init__(self, host="127.0.0.1", port=26760, pad_id=0):
        self.host = host
        self.port = port
        self.active_pad = pad_id

        # Internal state
        self._ctrl = 0
        self._btns = 0
        self._lx = 0.0; self._ly = 0.0
        self._rx = 0.0; self._ry = 0.0
        self._lg = (0.0, 0.0, 0.0); self._la = (0.0, 0.0, 1.0)
        self._rg = (0.0, 0.0, 0.0); self._ra = (0.0, 0.0, 1.0)

        self._keys_held = set()
        self._tk = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = False

    # ── pack & send ──────────────────────────────────────────────────────

    def _pack(self) -> bytes:
        return struct.pack(PACKET_FMT,
            b"OVER", self.active_pad, self._ctrl, self._btns,
            self._lx, self._ly, self._rx, self._ry,
            *self._lg, *self._la, *self._rg, *self._ra)

    def _send(self):
        """Compute state from held keys and send OVER packet."""
        # Reset state
        self._ctrl = 0
        self._btns = 0
        stick = {"left": [0.0, 0.0], "right": [0.0, 0.0]}
        mod = "Shift_L" in self._keys_held or "Shift_R" in self._keys_held
        val = STICK_HALF if mod else STICK_FULL

        for key in self._keys_held:
            act = KEY_MAP.get(key)
            if not act:
                continue
            if act[0] == "stick":
                _, side, d = act
                if d == "up":       stick[side][1] = val
                elif d == "down":   stick[side][1] = -val
                elif d == "left":   stick[side][0] = -val
                elif d == "right":  stick[side][0] = val
            elif act[0] == "button":
                bit = BUTTON_BITS.get(act[1], 0)
                if bit:
                    self._btns |= bit
                    self._ctrl |= CTRL_BUTTON

        # Apply stick values and set control bits
        self._lx, self._ly = stick["left"]
        self._rx, self._ry = stick["right"]
        if self._lx != 0.0 or self._ly != 0.0:
            self._ctrl |= CTRL_LEFT_X | CTRL_LEFT_Y
        if self._rx != 0.0 or self._ry != 0.0:
            self._ctrl |= CTRL_RIGHT_X | CTRL_RIGHT_Y

        self._sock.sendto(self._pack(), (self.host, self.port))

    # ── tkinter UI ───────────────────────────────────────────────────────

    def start(self):
        self._tk = tk.Tk()
        self._tk.title(f"OVER Console — pad {self.active_pad} — {self.host}:{self.port}")
        self._tk.geometry("620x140")
        self._tk.resizable(False, False)

        f = tk.Frame(self._tk)
        f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(f, text="OVER Protocol Console", font=("", 14, "bold")).pack()
        tk.Label(f, text=f"UDP → {self.host}:{self.port}   pad={self.active_pad}").pack()

        self._status = tk.StringVar()
        self._status.set("Keep this window focused.  ESC=quit  TAB=cycle pad")
        tk.Label(f, textvariable=self._status, fg="gray").pack()

        help_text = (
            "Sticks: WASD(left) IJKL(right) | "
            "U/J=AB Y/H=XY R/T=LR Q/E=ZL/ZR 1/2=L3/R3 -/= = MINUS/PLUS | "
            "DPad: Arrows | Shift=half | Tab=pad | Esc=quit"
        )
        tk.Label(f, text=help_text, font=("", 9), fg="gray").pack()

        self._tk.bind("<KeyPress>", self._on_press)
        self._tk.bind("<KeyRelease>", self._on_release)
        self._tk.protocol("WM_DELETE_WINDOW", self.stop)
        self._tk.focus_force()

        self._running = True
        print(f"OVER Console → {self.host}:{self.port}  pad={self.active_pad}")
        print("Keep the 'OVER Console' window focused.")
        print()
        self._tk.mainloop()
        self._sock.close()

    def stop(self):
        self._running = False
        if self._tk:
            self._tk.quit()

    def _on_press(self, event):
        if not self._running:
            return
        if event.keysym == "Escape":
            self.stop(); return
        if event.keysym == "Tab":
            self.active_pad = (self.active_pad + 1) % 8
            self._tk.title(f"OVER Console — pad {self.active_pad} — {self.host}:{self.port}")
            self._send(); self._update_status(); return

        name = self._key_name(event)
        if not name or name in self._keys_held:
            return
        if name in KEY_MAP or name in ("Shift_L", "Shift_R"):
            self._keys_held.add(name)
            self._send(); self._update_status()

    def _on_release(self, event):
        if not self._running:
            return
        name = self._key_name(event)
        if not name:
            return
        if name in self._keys_held:
            self._keys_held.discard(name)
            self._send(); self._update_status()

    def _key_name(self, event) -> str:
        ks = event.keysym
        if ks in ("Up", "Down", "Left", "Right"):
            return ks
        if ks in ("Shift_L", "Shift_R"):
            return ks
        special = {
            "period": ".", "semicolon": ";", "slash": "/",
            "quoteright": "'", "apostrophe": "'",
            "comma": ",", "bracketleft": "[", "bracketright": "]",
            "minus": "-", "equal": "=", "backslash": "\\", "grave": "`",
        }
        if ks.lower() in special:
            return special[ks.lower()]
        if len(event.char) == 1 and event.char.isprintable():
            return event.char.lower()
        return ""

    def _update_status(self):
        parts = []
        for key in sorted(self._keys_held):
            act = KEY_MAP.get(key)
            if act:
                if act[0] == "button":
                    parts.append(act[1])
                elif act[0] == "stick":
                    parts.append(f"{act[1][0].upper()}S-{act[2][:2]}")
        label = ",".join(parts) if parts else "(idle)"
        shift = " [HALF]" if ("Shift_L" in self._keys_held or "Shift_R" in self._keys_held) else ""
        self._status.set(f"pad={self.active_pad} [{label}]{shift}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="OVER Protocol Interactive Console")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=26760)
    p.add_argument("-p", "--pad", type=int, default=0)
    args = p.parse_args()
    OverConsole(host=args.host, port=args.port, pad_id=args.pad).start()


if __name__ == "__main__":
    main()
