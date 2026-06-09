#!/usr/bin/env python3
"""
Interactive console for sending OVER protocol packets via keyboard.
Uses tkinter (built into Python, zero dependencies).

Usage:
  python3 over_console.py                  # localhost:26760 pad 0
  python3 over_console.py -p 1              # pad 1
  python3 over_console.py --host 10.0.0.5   # remote Eden

Controls:
  W/A/S/D     left stick      U/J         A / B
  I/J/K/L     right stick     Y/H         X / Y
  Arrows      D-Pad           R/T         L / R
  TAB         cycle pad       Q/E         ZL / ZR
  ESC         quit            1/2         L3/R3
  LSHIFT      half-stick      -/=         MINUS/PLUS

macOS auto-repeat fix: 30ms debounce on KeyRelease events.
When auto-repeat fires KeyRelease-KeyPress pairs, the release is
cancelled by the subsequent press within the debounce window.
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
CTRL_BUTTON      = 1 << 0
CTRL_LEFT_X      = 1 << 1; CTRL_LEFT_Y      = 1 << 2
CTRL_RIGHT_X     = 1 << 3; CTRL_RIGHT_Y     = 1 << 4
CTRL_LEFT_GYRO   = 1 << 5; CTRL_LEFT_ACCEL  = 1 << 6
CTRL_RIGHT_GYRO  = 1 << 7; CTRL_RIGHT_ACCEL = 1 << 8

BUTTON_BITS = {
    "A": 1<<0, "B": 1<<1, "X": 1<<2, "Y": 1<<3,
    "STICK_L": 1<<4, "STICK_R": 1<<5,
    "L": 1<<6, "R": 1<<7, "ZL": 1<<8, "ZR": 1<<9,
    "PLUS": 1<<10, "MINUS": 1<<11,
    "LEFT": 1<<12, "UP": 1<<13, "RIGHT": 1<<14, "DOWN": 1<<15,
}

# ═══════════════════════════════════════════════════════════════════════════════
# Key map (keysym → action) + macOS auto-repeat debounce
# ═══════════════════════════════════════════════════════════════════════════════

KEY_MAP = {
    "w": ("stick","left","up"),    "s": ("stick","left","down"),
    "a": ("stick","left","left"),  "d": ("stick","left","right"),
    "i": ("stick","right","up"),   "k": ("stick","right","down"),
    "j": ("stick","right","left"), "l": ("stick","right","right"),
    "u": ("button","A"),  "j": ("button","B"),
    "y": ("button","X"),  "h": ("button","Y"),
    "r": ("button","L"),  "t": ("button","R"),
    "q": ("button","ZL"), "e": ("button","ZR"),
    "1": ("button","STICK_L"), "2": ("button","STICK_R"),
    "minus": ("button","MINUS"), "equal": ("button","PLUS"),
    "Up": ("button","UP"),    "Down":  ("button","DOWN"),
    "Left": ("button","LEFT"), "Right": ("button","RIGHT"),
}
STICK_FULL = 1.0; STICK_HALF = 0.5
DEBOUNCE_MS = 30 if sys.platform == "darwin" else 0

class OverConsole:
    def __init__(self, host="127.0.0.1", port=26760, pad_id=0):
        self.host = host; self.port = port; self.active_pad = pad_id
        self._ctrl=0; self._btns=0; self._lx=0.0; self._ly=0.0; self._rx=0.0; self._ry=0.0
        self._lg=(0,0,0); self._la=(0,0,1); self._rg=(0,0,0); self._ra=(0,0,1)
        self._keys_held = {}           # keycode → keysym
        self._pending_release = {}     # keycode → after_id (debounce)
        self._tk = None; self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = False

    def _send(self):
        mod = any(ks in ("Shift_L","Shift_R") for ks in self._keys_held.values())
        val = STICK_HALF if mod else STICK_FULL
        self._ctrl = CTRL_BUTTON|CTRL_LEFT_X|CTRL_LEFT_Y|CTRL_RIGHT_X|CTRL_RIGHT_Y
        self._btns = 0; self._lx=self._ly=self._rx=self._ry = 0.0
        for kc, ks in self._keys_held.items():
            act = KEY_MAP.get(ks)
            if not act: continue
            if act[0] == "stick":
                _, side, d = act
                v = val if d in ("up","right") else -val
                if side == "left":
                    if d in ("left","right"): self._lx = v
                    else: self._ly = v
                else:
                    if d in ("left","right"): self._rx = v
                    else: self._ry = v
            elif act[0] == "button":
                self._btns |= BUTTON_BITS.get(act[1], 0)
        data = struct.pack(PACKET_FMT, b"OVER", self.active_pad, self._ctrl, self._btns,
            self._lx,self._ly,self._rx,self._ry, *self._lg,*self._la,*self._rg,*self._ra)
        self._sock.sendto(data, (self.host, self.port))

    def _update_status(self):
        parts = []
        for ks in sorted(set(self._keys_held.values())):
            act = KEY_MAP.get(ks)
            if act:
                if act[0] == "button": parts.append(act[1])
                elif act[0] == "stick": parts.append(f"{act[1][0].upper()}S-{act[2][:2]}")
        label = ",".join(parts) if parts else "(idle)"
        self._status.set(f"pad={self.active_pad} [{label}]")

    # ── tkinter ──────────────────────────────────────────────────────────

    def start(self):
        self._tk = tk.Tk()
        self._tk.title(f"OVER Console — pad {self.active_pad} — {self.host}:{self.port}")
        self._tk.geometry("620x120"); self._tk.resizable(False, False)
        f = tk.Frame(self._tk); f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(f, text="OVER Protocol Console", font=("",14,"bold")).pack()
        tk.Label(f, text=f"UDP → {self.host}:{self.port}   pad={self.active_pad}").pack()
        self._status = tk.StringVar(); self._status.set("Focus this window. ESC=quit TAB=pad")
        tk.Label(f, textvariable=self._status, fg="gray").pack()
        tk.Label(f, text="WASD/IJKL=sticks U/J/Y/H/R/T/Q/E=buttons Arrows=DPad Shift=half Tab=pad Esc=quit",
                 font=("",9), fg="gray").pack()
        self._tk.bind("<KeyPress>", self._on_key)
        self._tk.bind("<KeyRelease>", self._on_key)
        self._tk.protocol("WM_DELETE_WINDOW", self.stop)
        self._tk.focus_force()
        self._running = True
        print(f"OVER Console → {self.host}:{self.port}  pad={self.active_pad}")
        self._tk.mainloop(); self._sock.close()

    def stop(self):
        self._running = False
        if self._tk: self._tk.quit()

    def _on_key(self, event):
        if not self._running: return
        kc = event.keycode; ks = event.keysym
        if len(ks) == 1 and ks.isalpha(): ks = ks.lower()
        is_press = (event.type == "2")

        if is_press:
            # Cancel any pending release for this key (auto-repeat defense)
            if kc in self._pending_release:
                self._tk.after_cancel(self._pending_release.pop(kc))
                return  # auto-repeat KeyPress re-acquired the key
            if ks == "Escape": self.stop(); return
            if ks == "Tab":
                self.active_pad = (self.active_pad + 1) % 8
                self._tk.title(f"OVER Console — pad {self.active_pad} — {self.host}:{self.port}")
                self._send(); self._update_status(); return
            if kc in self._keys_held: return
            if ks in KEY_MAP or ks in ("Shift_L", "Shift_R"):
                self._keys_held[kc] = ks
                self._send(); self._update_status()
        else:
            if kc not in self._keys_held: return
            if DEBOUNCE_MS > 0:
                # Schedule release check; auto-repeat KeyPress within
                # DEBOUNCE_MS will cancel it.
                aid = self._tk.after(DEBOUNCE_MS, lambda k=kc: self._do_release(k))
                self._pending_release[kc] = aid
            else:
                self._do_release(kc)

    def _do_release(self, kc):
        self._pending_release.pop(kc, None)
        if kc in self._keys_held:
            del self._keys_held[kc]
            self._send(); self._update_status()


def main():
    p = argparse.ArgumentParser(description="OVER Protocol Console")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=26760)
    p.add_argument("-p", "--pad", type=int, default=0)
    args = p.parse_args()
    OverConsole(host=args.host, port=args.port, pad_id=args.pad).start()

if __name__ == "__main__":
    main()
