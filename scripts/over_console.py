#!/usr/bin/env python3
"""
Interactive console for sending OVER protocol packets via keyboard.

Usage:
  python3 scripts/over_console.py                  # default: localhost:26760 pad 0
  python3 scripts/over_console.py -p 1              # pad 1
  python3 scripts/over_console.py --host 10.0.0.5   # remote Eden instance

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

Uses tkinter for proper key-down/key-up events.  Each key change
immediately sends an 84-byte OVER packet.
"""

import argparse
import struct
import socket
import sys
import os
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.over_sender import OverSender, PACKET_SIZE, \
    CTRL_BUTTON, CTRL_LEFT_X, CTRL_LEFT_Y, CTRL_RIGHT_X, CTRL_RIGHT_Y

# ── Key → overlay action mapping ──────────────────────────────────────────

# Each entry: (action_type, *args)
# action_type: "button" | "stick"
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

# Stick value when key pressed (full push)
STICK_FULL = 1.0
STICK_HALF = 0.5


class OverConsole:
    def __init__(self, host="127.0.0.1", port=26760, pad_id=0):
        self.host = host
        self.port = port
        self.pad_id = pad_id
        self.num_pads = 8
        self.active_pad = pad_id

        self._keys_held = set()       # currently pressed key names
        self._tk = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = False

        # Button aliases for canonical names
        self._button_names = {
            "a": "A", "b": "B", "x": "X", "y": "Y",
            "l": "L", "r": "R", "zl": "ZL", "zr": "ZR",
        }

    # ── Build & send packet ──────────────────────────────────────────────

    def _send(self):
        """Compute current state from held keys and send OVER packet."""
        sender = OverSender(host=self.host, port=self.port, pad_id=self.active_pad)

        stick_axes = {"left": [0.0, 0.0], "right": [0.0, 0.0]}  # [x, y]
        buttons = {}
        mod_active = "Shift_L" in self._keys_held or "Shift_R" in self._keys_held
        stick_val = STICK_HALF if mod_active else STICK_FULL

        for key in self._keys_held:
            if key not in KEY_MAP:
                continue
            action = KEY_MAP[key]

            if action[0] == "stick":
                _, side, direction = action
                if direction == "up":
                    stick_axes[side][1] = stick_val
                elif direction == "down":
                    stick_axes[side][1] = -stick_val
                elif direction == "left":
                    stick_axes[side][0] = -stick_val
                elif direction == "right":
                    stick_axes[side][0] = stick_val

            elif action[0] == "button":
                buttons[action[1]] = True

        # Apply stick positions
        sender.stick("left", *stick_axes["left"])
        sender.stick("right", *stick_axes["right"])

        # Apply buttons
        if buttons:
            sender.buttons(**buttons)

        sender._sock = self._sock  # reuse our socket
        sender.send()
        return sender.control_mask

    # ── tkinter UI ───────────────────────────────────────────────────────

    def start(self):
        self._tk = tk.Tk()
        self._tk.title(f"OVER Console — pad {self.active_pad} — {self.host}:{self.port}")
        self._tk.geometry("580x140")
        self._tk.resizable(False, False)

        frame = tk.Frame(self._tk)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(frame, text="OVER Protocol Console", font=("", 14, "bold")).pack()
        tk.Label(frame, text=f"UDP → {self.host}:{self.port}   pad={self.active_pad}").pack()

        self._status = tk.StringVar()
        self._status.set("Keep this window focused.  ESC=quit  TAB=cycle pad")
        tk.Label(frame, textvariable=self._status, fg="gray").pack()

        help_text = (
            "Sticks: WASD(left) IJKL(right) | Buttons: U/J=AB Y/H=XY R/T=LR Q/E=ZL/ZR "
            "1/2=L3/R3 -/= = MINUS/PLUS | DPad: Arrows | Shift=half"
        )
        tk.Label(frame, text=help_text, font=("", 9), fg="gray").pack()

        # Key bindings
        self._tk.bind("<KeyPress>", self._on_press)
        self._tk.bind("<KeyRelease>", self._on_release)
        self._tk.protocol("WM_DELETE_WINDOW", self.stop)
        self._tk.focus_force()

        self._running = True
        print(f"OVER Console → {self.host}:{self.port}  pad={self.active_pad}")
        print(f"Keep the 'OVER Console' window focused for keyboard input.")
        print()

        self._tk.mainloop()
        self._running = False
        self._sock.close()

    def stop(self):
        self._running = False
        if self._tk:
            self._tk.quit()

    def _on_press(self, event):
        if not self._running:
            return

        # ESC → quit
        if event.keysym == "Escape":
            self.stop()
            return

        # TAB → cycle pad
        if event.keysym == "Tab":
            self.active_pad = (self.active_pad + 1) % self.num_pads
            self._tk.title(f"OVER Console — pad {self.active_pad} — {self.host}:{self.port}")
            self._send()
            self._update_status()
            return

        name = self._key_name(event)
        if not name:
            return

        if name in self._keys_held:
            return  # auto-repeat

        if name in KEY_MAP or name in ("Shift_L", "Shift_R"):
            self._keys_held.add(name)
            mask = self._send()
            self._update_status()

    def _on_release(self, event):
        if not self._running:
            return

        name = self._key_name(event)
        if not name:
            return

        if name in self._keys_held:
            self._keys_held.discard(name)
            if self._keys_held:
                mask = self._send()
            else:
                # All keys released — send all-zero packet
                s = OverSender(host=self.host, port=self.port, pad_id=self.active_pad)
                s._sock = self._sock
                s.send()
            self._update_status()

    def _key_name(self, event) -> str:
        """Convert tkinter event to a key name matching KEY_MAP."""
        ks = event.keysym

        # Arrow keys → use DPad names
        if ks in ("Up", "Down", "Left", "Right"):
            return ks

        # Shift
        if ks in ("Shift_L", "Shift_R"):
            return ks

        # Special characters from tkinter
        special = {
            "period": ".", "semicolon": ";", "slash": "/",
            "quoteright": "'", "apostrophe": "'",
            "comma": ",", "bracketleft": "[", "bracketright": "]",
            "minus": "-", "equal": "=", "backslash": "\\",
            "grave": "`",
        }
        if ks.lower() in special:
            return special[ks.lower()]

        # Regular printable char
        if len(event.char) == 1 and event.char.isprintable():
            return event.char.lower()

        return ""

    def _update_status(self):
        """Show current state in the tkinter window."""
        parts = []
        for key in sorted(self._keys_held):
            if key in KEY_MAP:
                action = KEY_MAP[key]
                if action[0] == "button":
                    parts.append(action[1])
                elif action[0] == "stick":
                    parts.append(f"{action[1][0].upper()}S-{action[2][:2]}")
        label = ",".join(parts) if parts else "(idle)"
        shift = " [HALF]" if ("Shift_L" in self._keys_held or "Shift_R" in self._keys_held) else ""
        self._status.set(f"pad={self.active_pad} [{label}]{shift}")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OVER Protocol Interactive Console")
    parser.add_argument("--host", default="127.0.0.1", help="Eden IP (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=26760, help="Overlay UDP port (default: 26760)")
    parser.add_argument("-p", "--pad", type=int, default=0, help="Pad ID 0-7 (default: 0)")
    args = parser.parse_args()

    console = OverConsole(host=args.host, port=args.port, pad_id=args.pad)
    console.start()


if __name__ == "__main__":
    main()
