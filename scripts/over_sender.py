#!/usr/bin/env python3
"""
OVER protocol test sender.  Sends 76-byte UDP packets matching the
Eden Overlay C++ protocol.

Usage:
  python3 scripts/over_sender.py A B              # press A+B on pad 0, send once
  python3 scripts/over_sender.py -p 1 A            # press A on pad 1
  python3 scripts/over_sender.py -H A              # hold A (sends at 60Hz until Ctrl-C)
  python3 scripts/over_sender.py stick left 0.5 0  # left stick half-right
  python3 scripts/over_sender.py motion gyro 0 0.1 0  # left gyro Y=0.1 rad/s
  python3 scripts/over_sender.py --host 192.168.1.100 --port 26760 A

As a module:
  from scripts.over_sender import OverSender

  sender = OverSender(pad_id=0)
  sender.buttons(A=True, B=True)
  sender.stick(side="left", x=0.5, y=0)
  sender.send()
"""

import argparse
import socket
import struct
import sys
import time

PACKET_FMT = "<4sB3xI16f"
PACKET_SIZE = struct.calcsize(PACKET_FMT)  # 76

# ═══════════════════════════════════════════════════════════════════════════════
# Switch NpadButton bit layout  (matches Eden hid_types.h NpadButton enum)
# ═══════════════════════════════════════════════════════════════════════════════

BUTTON_BITS = {
    "A": 1 << 0,  "B": 1 << 1,  "X": 1 << 2,  "Y": 1 << 3,
    "STICK_L": 1 << 4,  "STICK_R": 1 << 5,
    "L": 1 << 6,  "R": 1 << 7,  "ZL": 1 << 8,  "ZR": 1 << 9,
    "PLUS": 1 << 10,  "MINUS": 1 << 11,
    "LEFT": 1 << 12,  "UP": 1 << 13,  "RIGHT": 1 << 14,  "DOWN": 1 << 15,
    "STICK_L_LEFT": 1 << 16,  "STICK_L_UP": 1 << 17,
    "STICK_L_RIGHT": 1 << 18,  "STICK_L_DOWN": 1 << 19,
    "STICK_R_LEFT": 1 << 20,  "STICK_R_UP": 1 << 21,
    "STICK_R_RIGHT": 1 << 22,  "STICK_R_DOWN": 1 << 23,
    "LEFT_SL": 1 << 24,  "LEFT_SR": 1 << 25,
    "RIGHT_SL": 1 << 26,  "RIGHT_SR": 1 << 27,
    "PALMA": 1 << 28,
    "VERIFICATION": 1 << 29,
    "HANDHELD_LEFT_B": 1 << 30,
}

# Convenience aliases (lowercase)
ALIASES = {
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "l": "L", "r": "R", "zl": "ZL", "zr": "ZR",
    "plus": "PLUS", "minus": "MINUS", "+": "PLUS", "-": "MINUS",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
}

ALL_BUTTONS = set(BUTTON_BITS.keys())  # canonical names for the help text


# ═══════════════════════════════════════════════════════════════════════════════
# OverSender
# ═══════════════════════════════════════════════════════════════════════════════

class OverSender:
    """Build and send OVER protocol packets."""

    def __init__(self, host: str = "127.0.0.1", port: int = 26760, pad_id: int = 0):
        self.host = host
        self.port = port
        self.pad_id = pad_id

        self._button_mask = 0
        self._left = (0.0, 0.0)
        self._right = (0.0, 0.0)
        self._left_gyro = (0.0, 0.0, 0.0)
        self._left_accel = (0.0, 0.0, 1.0)   # gravity on Z by default
        self._right_gyro = (0.0, 0.0, 0.0)
        self._right_accel = (0.0, 0.0, 1.0)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # ── fluent helpers ────────────────────────────────────────────────────

    def buttons(self, **kwargs) -> "OverSender":
        """
        Set button mask.  Pass button names as keyword args:
            sender.buttons(A=True, B=True, L=False)
        Omitting a button leaves it at its current state.
        """
        for name, state in kwargs.items():
            canon = ALIASES.get(name.lower(), name.upper())
            if canon not in BUTTON_BITS:
                raise ValueError(f"Unknown button: {name}")
            if state:
                self._button_mask |= BUTTON_BITS[canon]
            else:
                self._button_mask &= ~BUTTON_BITS[canon]
        return self

    def clear_buttons(self) -> "OverSender":
        self._button_mask = 0
        return self

    def stick(self, side: str, x: float, y: float) -> "OverSender":
        """Set stick position.  side='left' or 'right'.  x,y: -1.0..1.0"""
        if side == "left":
            self._left = (x, y)
        elif side == "right":
            self._right = (x, y)
        else:
            raise ValueError(f"Unknown stick side: {side!r} (use 'left' or 'right')")
        return self

    def motion(self, source: str, gyro: tuple = None, accel: tuple = None) -> "OverSender":
        """
        Set motion data.  source='left' or 'right'.
        gyro:  (x, y, z) in rad/s
        accel: (x, y, z) in G
        """
        if source == "left":
            if gyro is not None:
                self._left_gyro = gyro
            if accel is not None:
                self._left_accel = accel
        elif source == "right":
            if gyro is not None:
                self._right_gyro = gyro
            if accel is not None:
                self._right_accel = accel
        else:
            raise ValueError(f"Unknown motion source: {source!r} (use 'left' or 'right')")
        return self

    # ── build & send ──────────────────────────────────────────────────────

    def pack(self) -> bytes:
        """Build the 76-byte packet.  Returns bytes."""
        return struct.pack(
            PACKET_FMT,
            b"OVER", self.pad_id, self._button_mask,
            *self._left, *self._right,
            *self._left_gyro, *self._left_accel,
            *self._right_gyro, *self._right_accel,
        )

    def send(self) -> None:
        """Send one packet.  Raises OSError on network error."""
        self._sock.sendto(self.pack(), (self.host, self.port))

    def close(self) -> None:
        self._sock.close()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_stick(args: list) -> dict:
    """Parse 'stick left 0.5 -0.3' → dict for OverSender.stick()"""
    if len(args) < 4:
        raise SystemExit("Usage: over_sender.py stick <left|right> <x> <y>")
    return {"side": args[1], "x": float(args[2]), "y": float(args[3])}


def _parse_motion(args: list) -> dict:
    """Parse 'motion left gyro 0 0.1 0 accel 0 0 1' → dict"""
    result = {"source": args[1]}
    i = 2
    while i < len(args):
        kind = args[i]
        i += 1
        if i + 2 >= len(args):
            raise SystemExit(f"Usage: ... motion <left|right> gyro <x> <y> <z> [accel <x> <y> <z>]")
        vals = (float(args[i]), float(args[i + 1]), float(args[i + 2]))
        i += 3
        result[kind] = vals
    return result


def _parse_buttons(args: list) -> dict:
    """Parse button names → dict for OverSender.buttons(**kwargs)"""
    result = {}
    for name in args:
        canon = ALIASES.get(name.lower(), name.upper())
        if canon not in BUTTON_BITS:
            raise SystemExit(f"Unknown button: {name!r}")
        result[canon] = True
    return result


def _hold_loop(sender: OverSender, interval: float = 1.0 / 60) -> None:
    """Send packets at ~60 Hz until interrupted."""
    print(f"Sending to {sender.host}:{sender.port} pad={sender.pad_id} "
          f"every {interval*1000:.0f}ms  (Ctrl-C to stop)")
    try:
        while True:
            sender.send()
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def _button_names() -> str:
    """Compact list of supported button names."""
    names = sorted(BUTTON_BITS.keys())
    return ", ".join(names)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="OVER protocol test sender (76-byte packets)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  over_sender.py A B                  press A + B on pad 0 (single shot)\n"
            "  over_sender.py -p 1 A               press A on pad 1\n"
            "  over_sender.py -H A                 hold A (60 Hz until Ctrl-C)\n"
            "  over_sender.py -H stick left 0.5 0  hold left stick half-right\n"
            "  over_sender.py --host 10.0.0.5 A    send to remote host\n"
            "\nSupported buttons:\n"
            f"  {_button_names()}"
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="Target IP (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=26760, help="Target UDP port (default: 26760)")
    parser.add_argument("-p", "--pad", type=int, default=0, metavar="ID",
                        help="Pad ID 0-7 (default: 0)")
    parser.add_argument("-H", "--hold", action="store_true",
                        help="Hold mode: send continuously at ~60 Hz until Ctrl-C")
    parser.add_argument("action", nargs=argparse.REMAINDER,
                        help="'A B' (buttons) | 'stick left 0.5 0' | 'motion left gyro 0 0.1 0'")

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    sender = OverSender(host=args.host, port=args.port, pad_id=args.pad)

    cmd = args.action[0].lower()

    if cmd in ("stick", "st"):
        kwargs = _parse_stick(args.action)
        sender.stick(**kwargs)
    elif cmd in ("motion", "mot", "mo"):
        kwargs = _parse_motion(args.action)
        sender.motion(**kwargs)
    else:
        # All positional args are button names
        kwargs = _parse_buttons(args.action)
        sender.buttons(**kwargs)

    if args.hold:
        _hold_loop(sender)
    else:
        sender.send()
        btn_display = ", ".join(args.action) or "(no buttons)"
        print(f"Sent 1 packet to {sender.host}:{sender.port}  pad={sender.pad_id}  [{btn_display}]")

    sender.close()


if __name__ == "__main__":
    main()
