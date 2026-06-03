#!/usr/bin/env python3
"""
DSU Server for Eden Switch Emulator input testing.

A clean, extensible DSU (Cemuhook) protocol server. Eden/Citron connects as a
DSU client over UDP; this server responds to its polls and instantly pushes
data on every state change.

Keyboard mapping is loaded from keyboard_config.json at startup.

Usage:
  python3 dsu_server.py                        # Interactive keyboard mode
  python3 dsu_server.py -c my_config.json      # Custom config
  python3 dsu_server.py --pads 4               # 4-player support
  python3 dsu_server.py --no-keyboard          # DSU server only

Extend with custom logic:
  from dsu_server import DsuServer

  server = DsuServer(port=26760, num_pads=1, keyboard=False)

  server.press("A")             # hold A
  server.press("A", "B")        # hold A + B combo
  server.release()              # release all
  server.stick("left", 200, 128)   # left stick (0-255, 128=center)
  server.motion(gyro=(0.1, 0, 0), accel=(0, 0, 1))

  server.start()   # blocks, runs UDP + keyboard event loop
"""

import atexit
import json
import os
import selectors
import socket
import struct
import sys
import termios
import time
import tty


# ═══════════════════════════════════════════════════════════════════════════════
# DSU Protocol constants
# ═══════════════════════════════════════════════════════════════════════════════

SERVER_MAGIC  = 0x53555344
CLIENT_MAGIC  = 0x43555344
PROTO_VERSION = 1001
TYPE_VERSION   = 0x00100000
TYPE_PORT_INFO = 0x00100001
TYPE_PAD_DATA  = 0x00100002

BUTTON_BIT = {
    "Share": 1 << 0,  "L3": 1 << 1,  "R3": 1 << 2,  "Options": 1 << 3,
    "DUp": 1 << 4,  "DRight": 1 << 5,  "DDown": 1 << 6,  "DLeft": 1 << 7,
    "L2": 1 << 8,  "R2": 1 << 9,  "L1": 1 << 10,  "R1": 1 << 11,
    "Triangle": 1 << 12, "Circle": 1 << 13, "Cross": 1 << 14, "Square": 1 << 15,
}

ALIASES = {
    "A": "Circle", "B": "Cross", "X": "Triangle", "Y": "Square",
    "L": "L1", "R": "R1", "ZL": "L2", "ZR": "R2",
    "L3": "L3", "R3": "R3",
    "UP": "DUp", "DOWN": "DDown", "LEFT": "DLeft", "RIGHT": "DRight",
    "PLUS": "Options", "MINUS": "Share", "HOME": None, "SHARE": "Share",
    "Circle": "Circle", "Cross": "Cross", "Triangle": "Triangle", "Square": "Square",
    "DUp": "DUp", "DDown": "DDown", "DLeft": "DLeft", "DRight": "DRight",
    "L1": "L1", "R1": "R1", "L2": "L2", "R2": "R2",
    "Options": "Options",
}

DSU_NAMES = {  # friendly name → display label for status line
    "A": "A", "B": "B", "X": "X", "Y": "Y",
    "L": "L", "R": "R", "ZL": "ZL", "ZR": "ZR",
    "L3": "L3", "R3": "R3",
    "UP": "Up", "DOWN": "Dn", "LEFT": "Lt", "RIGHT": "Rt",
    "PLUS": "+", "MINUS": "-", "HOME": "Home", "SHARE": "Share",
}

ARROW_KEY = {'A': "UP", 'B': "DOWN", 'C': "RIGHT", 'D': "LEFT"}

_fd = sys.stdin.fileno()
_orig_termios = None


# ═══════════════════════════════════════════════════════════════════════════════
# CRC-32 (matching boost::crc_32_type)
# ═══════════════════════════════════════════════════════════════════════════════

def _crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


# ═══════════════════════════════════════════════════════════════════════════════
# DSU Packet builders
# ═══════════════════════════════════════════════════════════════════════════════

def _make_header(msg_type: int, payload_len: int, sender_id: int = 0) -> bytes:
    return struct.pack("<IHHII", SERVER_MAGIC, PROTO_VERSION, payload_len + 4, 0, sender_id)

def _seal(msg: bytes) -> bytes:
    c = _crc32(msg)
    return msg[:8] + struct.pack("<I", c) + msg[12:]

def _build_version(req_id: int) -> bytes:
    data = struct.pack("<H", PROTO_VERSION)
    header = _make_header(TYPE_VERSION, 2, req_id)
    return _seal(header + struct.pack("<I", TYPE_VERSION) + data)

def _build_port_info(req_id: int, pad_count: int) -> bytes:
    entries = b''.join(
        struct.pack("<BBBB6sBB", i, 2, 2, 1, b'\x11\x22\x33\x44\x55\x66', 5, 1)
        for i in range(pad_count))
    data = struct.pack("<B", pad_count) + entries
    header = _make_header(TYPE_PORT_INFO, len(data), req_id)
    return _seal(header + struct.pack("<I", TYPE_PORT_INFO) + data)

def _build_pad_data(req_id: int, pad_id: int, counter: int,
                    buttons: int = 0, home: int = 0, touch: int = 0,
                    lx: int = 128, ly: int = 128, rx: int = 128, ry: int = 128,
                    gyro: tuple = (0.0, 0.0, 0.0), accel: tuple = (0.0, 0.0, 1.0)) -> bytes:
    port_info = struct.pack("<BBBB6sBB", pad_id, 2, 2, 1, b'\x11\x22\x33\x44\x55\x66', 5, 1)
    pad_data = struct.pack("<IHBBBBBB", counter, buttons, home, touch, lx, ly, rx, ry)
    pad_data += b'\x00' * 12
    pad_data += b'\x00' * 12
    pad_data += struct.pack("<Q", int(time.time() * 1_000_000))
    pad_data += struct.pack("<fff", *accel)
    pad_data += struct.pack("<fff", *gyro)
    full = port_info + pad_data
    header = _make_header(TYPE_PAD_DATA, len(full), req_id)
    return _seal(header + struct.pack("<I", TYPE_PAD_DATA) + full)

def _parse_request(data: bytes):
    if len(data) < 20:
        return None
    if struct.unpack_from("<I", data, 0)[0] != CLIENT_MAGIC:
        return None
    return (struct.unpack_from("<I", data, 12)[0],
            struct.unpack_from("<I", data, 16)[0])


# ═══════════════════════════════════════════════════════════════════════════════
# Keyboard config loader
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_config_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    # Look next to the script first, then cwd
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for base in (script_dir, os.getcwd()):
        full = os.path.join(base, path)
        if os.path.exists(full):
            return full
    return os.path.join(os.getcwd(), path)


def load_keyboard_config(path: str = "keyboard_config.json") -> dict:
    """Load keyboard mapping from JSON. Returns config dict."""
    full = _resolve_config_path(path)
    with open(full) as f:
        cfg = json.load(f)

    kb = cfg["keyboard"]
    result = {
        "port": cfg.get("port", 26760),
        "num_pads": cfg.get("num_pads", 1),
        # char → button name (for buttons and dpad combined)
        "button_map": {},
        # stick axis conflicts: char → conflicting char (removed when this key pressed)
        "conflicts": {},
        # char → (side, axis, direction, full_value, half_value)
        "stick_map": {},
        # modifier key char and scale
        "mod_left": kb["sticks"]["left"].get("modifier"),
        "mod_right": kb["sticks"]["right"].get("modifier"),
        "mod_scale": kb["sticks"]["left"].get("scale", 0.5),
        # All known chars (for help display)
        "all_chars": set(),
    }

    # Button keys: char → button name
    for ch, name in kb.get("buttons", {}).items():
        result["button_map"][ch] = name
        result["all_chars"].add(ch)

    # DPad: arrow keys handled separately in stdin handler
    for ch, name in kb.get("dpad", {}).items():
        result["button_map"][ch] = name
        result["all_chars"].add(ch)

    # Stick mappings
    for side_key, stick_key in [("left", "left"), ("right", "right")]:
        stick = kb["sticks"].get(stick_key, {})
        for dir_ in ("up", "down", "left", "right"):
            ch = stick.get(dir_)
            if not ch:
                continue
            full_val = _stick_value(dir_, 1.0)
            half_val = _stick_value(dir_, result["mod_scale"])
            result["stick_map"][ch] = (side_key, dir_, full_val, half_val)
            result["all_chars"].add(ch)

        # Conflicts: up/down and left/right on the same stick
        for a, b in (("up", "down"), ("left", "right")):
            ca, cb = stick.get(a), stick.get(b)
            if ca and cb:
                result["conflicts"][ca] = cb
                result["conflicts"][cb] = ca

    return result


def _stick_value(direction: str, scale: float) -> int:
    """Compute stick byte value for a direction with given scale."""
    delta = int(127 * scale)
    if direction == "up":
        return 128 - delta
    if direction == "down":
        return 128 + delta
    if direction == "left":
        return 128 - delta
    if direction == "right":
        return 128 + delta
    return 128


def _format_key_help(cfg: dict) -> str:
    """Build compact key legend from config."""
    lines = []
    btn = [(ch, name) for ch, name in cfg["button_map"].items()
           if name not in ("UP", "DOWN", "LEFT", "RIGHT")]
    if btn:
        lines.append("  Buttons: " + " ".join(
            f"{ch}={DSU_NAMES.get(name, name)}" for ch, name in sorted(btn)))
    sticks = {}
    for ch, (side, dir_, full, half) in cfg["stick_map"].items():
        sticks.setdefault(side, []).append(f"{ch}={dir_[:2]}")
    for side, entries in sticks.items():
        lines.append(f"  {side.capitalize()} stick: " + " ".join(sorted(entries)))
    lines.append(f"  Space=release  Tab=cycle pad  :=cmd  Esc=quit")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# DsuServer
# ═══════════════════════════════════════════════════════════════════════════════

class DsuServer:
    """
    DSU server that Eden/Citron connects to as a client.

    Public methods:

        press(*names, pad=0)       — hold button(s), replaces previous
        release(pad=None)          — release all (pad=None → all pads)
        stick(side, x, y, pad=0)   — set stick (side='left'/'right', 0-255)
        motion(gyro, accel, pad=0) — set motion (3-tuples)
        touch(x, y, pressed, pad=0) — set touchscreen

        start()   — run the event loop (blocking)
        stop()    — stop the event loop
    """

    def __init__(self, port: int = 26760, num_pads: int = 1,
                 keyboard: bool = True, config_path: str = "keyboard_config.json"):
        self.port = port
        self.num_pads = max(1, min(4, num_pads))
        self.keyboard_enabled = keyboard

        self._pads = [dict(buttons=0, lx=128, ly=128, rx=128, ry=128,
                           home=0, touch=0, touch_x=0, touch_y=0,
                           gyro=(0.0, 0.0, 0.0), accel=(0.0, 0.0, 1.0))
                      for _ in range(self.num_pads)]

        self._client_addr = None
        self._last_req_id = 0
        self._counter = 0
        self._pad_round_robin = 0

        self._sock = None
        self._sel = selectors.DefaultSelector()
        self._running = False
        self._active_pad = 0

        # Keyboard state
        self._keys_active = set()      # currently toggled-on key chars
        self._kbd_cfg = None
        if keyboard:
            self._kbd_cfg = load_keyboard_config(config_path)
            self.port = self._kbd_cfg.get("port", self.port)
            self.num_pads = max(1, min(4, self._kbd_cfg.get("num_pads", self.num_pads)))
            # Re-allocate pads if num_pads changed
            while len(self._pads) < self.num_pads:
                self._pads.append(dict(buttons=0, lx=128, ly=128, rx=128, ry=128,
                                       home=0, touch=0, touch_x=0, touch_y=0,
                                       gyro=(0.0, 0.0, 0.0), accel=(0.0, 0.0, 1.0)))
            self._pads = self._pads[:self.num_pads]

    # ── Public API ───────────────────────────────────────────────────────

    def press(self, *names, pad: int = 0):
        """Press and hold button(s). Replaces any previously held buttons."""
        p = self._pads[pad]
        p["buttons"] = 0
        p["home"] = 0
        for name in names:
            dsu_name = ALIASES.get(name.upper(), name)
            if dsu_name is None:
                p["home"] = 1
            elif dsu_name in BUTTON_BIT:
                p["buttons"] |= BUTTON_BIT[dsu_name]
            else:
                raise ValueError(f"Unknown button: {name}")
        self._push()

    def release(self, pad: int = None):
        """Release all buttons. pad=None releases all pads."""
        if pad is None:
            for p in self._pads:
                p.update(buttons=0, home=0, touch=0)
        else:
            self._pads[pad].update(buttons=0, home=0, touch=0)
        self._push()

    def stick(self, side: str, x: int, y: int, pad: int = 0):
        """Set stick position. side='left' or 'right'. x,y: 0-255 (128=center)."""
        p = self._pads[pad]
        if side == "left":
            p["lx"], p["ly"] = x, y
        elif side == "right":
            p["rx"], p["ry"] = x, y
        else:
            raise ValueError(f"Unknown stick side: {side} (use 'left' or 'right')")
        self._push()

    def motion(self, gyro: tuple = None, accel: tuple = None, pad: int = 0):
        """Set motion data. gyro and accel are (x, y, z) tuples."""
        p = self._pads[pad]
        if gyro is not None:
            p["gyro"] = gyro
        if accel is not None:
            p["accel"] = accel
        self._push()

    def touch(self, x: int, y: int, pressed: bool = True, pad: int = 0):
        """Set touchscreen position and state."""
        p = self._pads[pad]
        p["touch_x"] = x
        p["touch_y"] = y
        p["touch"] = 1 if pressed else 0
        self._push()

    # ── Server lifecycle ─────────────────────────────────────────────────

    def start(self):
        """Start the DSU server. Blocks until stop() is called or SIGINT."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.setblocking(False)
        self._sel.register(self._sock, selectors.EVENT_READ, data="udp")

        if self.keyboard_enabled:
            self._enter_raw()
            self._sel.register(sys.stdin, selectors.EVENT_READ, data="stdin")
            self._print_banner()

        self._running = True
        try:
            self._loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            for key, _mask in self._sel.select(timeout=0.1):
                tag = key.data
                if tag == "udp":
                    self._handle_udp()
                elif tag == "stdin":
                    self._handle_stdin()

    def _shutdown(self):
        if self.keyboard_enabled:
            self._exit_raw()
        if self._sock:
            self._sock.close()
        self._sel.close()

    # ── UDP DSU protocol ─────────────────────────────────────────────────

    def _handle_udp(self):
        try:
            while True:
                data, addr = self._sock.recvfrom(128)
                self._on_dsu_packet(data, addr)
        except BlockingIOError:
            pass

    def _on_dsu_packet(self, data: bytes, addr: tuple):
        parsed = _parse_request(data)
        if parsed is None:
            return
        req_id, msg_type = parsed
        self._client_addr = addr
        self._last_req_id = req_id

        if msg_type == TYPE_VERSION:
            self._sock.sendto(_build_version(req_id), addr)
        elif msg_type == TYPE_PORT_INFO:
            self._sock.sendto(_build_port_info(req_id, self.num_pads), addr)
        elif msg_type == TYPE_PAD_DATA:
            pid = self._pad_round_robin % self.num_pads
            self._pad_round_robin += 1
            self._send_pad(pid)

    def _send_pad(self, pad_id: int):
        p = self._pads[pad_id]
        resp = _build_pad_data(
            self._last_req_id, pad_id, self._counter,
            buttons=p["buttons"], home=p["home"], touch=p["touch"],
            lx=p["lx"], ly=p["ly"], rx=p["rx"], ry=p["ry"],
            gyro=p["gyro"], accel=p["accel"])
        self._sock.sendto(resp, self._client_addr)
        self._counter += 1

    def _push(self):
        if not self._client_addr:
            return
        for pid in range(self.num_pads):
            self._send_pad(pid)

    # ── Keyboard: raw terminal ───────────────────────────────────────────

    def _enter_raw(self):
        global _orig_termios
        if _orig_termios is not None:
            return
        _orig_termios = termios.tcgetattr(_fd)
        atexit.register(self._exit_raw)
        tty.setraw(_fd)

    def _exit_raw(self):
        global _orig_termios
        if _orig_termios is None:
            return
        termios.tcsetattr(_fd, termios.TCSADRAIN, _orig_termios)
        _orig_termios = None

    def _print_banner(self):
        cfg = self._kbd_cfg
        sys.stdout.write(
            f"\r[DSU Server] UDP 0.0.0.0:{self.port}  {self.num_pads} pad(s)  "
            f"config: {self._config_name}\n"
            f"{_format_key_help(cfg) if cfg else ''}\n"
            f"\r  {self._status()}\n")
        sys.stdout.flush()

    @property
    def _config_name(self):
        return "keyboard_config.json"  # simplified

    def _status(self):
        p = self._pads[self._active_pad]
        if self._keys_active:
            btn = self._active_keys_label()
        else:
            btn = self._mask_label(p["buttons"])
        pad_info = f"[pad {self._active_pad}/{self.num_pads}] " if self.num_pads > 1 else ""
        client = " [connected]" if self._client_addr else ""
        return f"{pad_info}[{btn}]  L=({p['lx']},{p['ly']}) R=({p['rx']},{p['ry']}){client}"

    def _active_keys_label(self):
        """Build label showing which keys are currently active."""
        cfg = self._kbd_cfg
        if not cfg:
            return "(none)"
        parts = []
        for ch in sorted(self._keys_active):
            if ch in cfg["button_map"]:
                name = cfg["button_map"][ch]
                parts.append(DSU_NAMES.get(name, name))
            elif ch in cfg["stick_map"]:
                side, dir_, _, _ = cfg["stick_map"][ch]
                parts.append(f"{side[:1].upper()}S-{dir_[:2]}")
        return ",".join(parts) if parts else "(none)"

    def _mask_label(self, mask):
        if mask == 0:
            return "(none)"
        rev = {}
        for friendly, dsu in ALIASES.items():
            if dsu and friendly == friendly.upper() and len(friendly) <= 5:
                rev[dsu] = friendly
        names = []
        for dsu, bit in BUTTON_BIT.items():
            if mask & bit:
                names.append(rev.get(dsu, dsu))
        return ",".join(names)

    # ── Keyboard: input handler (toggle model) ───────────────────────────

    def _handle_stdin(self):
        ch, is_arrow, arrow_dir = _read_key()
        if ch is None:
            return

        # Arrow keys → dpad
        if is_arrow:
            name = ARROW_KEY.get(arrow_dir)
            if name:
                self.press(name, pad=self._active_pad)
                self._echo(f"arrow -> {name}")
            return

        if ch in ('\x03', '\x1b'):    # Ctrl+C / Esc
            self._running = False
            return

        if ch == ' ':                  # Space = release all
            self._keys_active.clear()
            self.release()
            self._echo("all released")
            return

        if ch == '\t':                 # Tab = cycle pad
            self._active_pad = (self._active_pad + 1) % self.num_pads
            self._echo(f"pad {self._active_pad}")
            return

        if ch == '?':                  # Help
            self._print_help()
            return

        if ch == ':':                  # Text command
            self._exit_raw()
            try:
                print()
                cmd = input("  cmd> ").strip()
                if cmd:
                    self._run_command(cmd)
            finally:
                self._enter_raw()
            self._echo("")
            return

        # Toggle key in active set
        cfg = self._kbd_cfg
        if cfg is None:
            return

        if ch in cfg["button_map"] or ch in cfg["stick_map"] or ch in (cfg.get("mod_left"), cfg.get("mod_right")):
            self._toggle_key(ch)
            self._apply_key_state()

    def _toggle_key(self, ch):
        """Toggle a key in/out of the active set, handling conflicts."""
        cfg = self._kbd_cfg
        if ch in self._keys_active:
            self._keys_active.remove(ch)
            return

        # Remove conflicting key (same axis, opposite direction)
        conflict = cfg["conflicts"].get(ch)
        if conflict:
            self._keys_active.discard(conflict)

        self._keys_active.add(ch)

    def _apply_key_state(self):
        """Recompute pad button mask and stick positions from active keys."""
        cfg = self._kbd_cfg
        p = self._pads[self._active_pad]

        mask = 0
        home = 0
        lx, ly = 128, 128
        rx, ry = 128, 128

        # Check modifier keys
        mod_active = (cfg.get("mod_left") in self._keys_active or
                      cfg.get("mod_right") in self._keys_active)
        use_scale = cfg["mod_scale"] if mod_active else 1.0

        for ch in self._keys_active:
            # Button key
            if ch in cfg["button_map"]:
                name = cfg["button_map"][ch]
                dsu_name = ALIASES.get(name.upper(), name)
                if dsu_name is None:
                    home = 1
                elif dsu_name in BUTTON_BIT:
                    mask |= BUTTON_BIT[dsu_name]

            # Stick key
            elif ch in cfg["stick_map"]:
                side, dir_, full_val, half_val = cfg["stick_map"][ch]
                val = half_val if mod_active else full_val
                if side == "left":
                    if dir_ in ("up", "down"):
                        ly = val
                    else:
                        lx = val
                else:
                    if dir_ in ("up", "down"):
                        ry = val
                    else:
                        rx = val

        p["buttons"] = mask
        p["home"] = home
        p["lx"] = lx
        p["ly"] = ly
        p["rx"] = rx
        p["ry"] = ry
        self._push()
        self._echo("")

    # ── Text commands ────────────────────────────────────────────────────

    def _run_command(self, cmd: str):
        parts = cmd.split()
        if not parts:
            return
        c = parts[0].upper()

        if c in ("Q", "QUIT"):
            self._running = False
        elif c in ("RELEASE", "NONE"):
            self._keys_active.clear()
            self.release()
            print(f"  {self._status()}")
        elif c in ALIASES or c == "HOME":
            self.press(c)
            self._keys_active.clear()
            print(f"  {self._status()}")
        elif c == "STICK":
            if len(parts) >= 4:
                side, x, y = parts[1].lower(), int(parts[2]), int(parts[3])
                self.stick(side, x, y, self._active_pad)
                print(f"  {self._status()}")
            else:
                print("  Usage: stick left|right <x> <y>")
        elif c == "PAD":
            if len(parts) < 2:
                print("  Usage: pad <N> [command]")
                return
            try:
                n = int(parts[1])
            except ValueError:
                print(f"  Invalid pad: {parts[1]}")
                return
            if not 0 <= n < self.num_pads:
                print(f"  Pad must be 0-{self.num_pads - 1}")
                return
            if len(parts) == 2:
                self._active_pad = n
                print(f"  Active pad: {n}")
            else:
                saved = self._active_pad
                self._active_pad = n
                self._run_command(" ".join(parts[2:]))
                self._active_pad = saved
        elif c == "STATE":
            for i, p in enumerate(self._pads):
                btn = self._mask_label(p["buttons"])
                print(f"  Pad {i}: [{btn}]  "
                      f"L=({p['lx']},{p['ly']}) R=({p['rx']},{p['ry']})")
        elif c == "HELP":
            self._print_cmd_help()
        else:
            print(f"  Unknown: {c}  (try 'help')")

    def _echo(self, msg):
        sys.stdout.write(f"\r\x1b[K{msg}  {self._status()}\n")
        sys.stdout.flush()

    def _print_help(self):
        self._exit_raw()
        cfg = self._kbd_cfg
        print(f"\n{_format_key_help(cfg) if cfg else '  (no keyboard config)'}")
        print("""
  ?           This help
  :           Text command mode (stick, pad N, etc.)
  Esc         Quit
""")
        input("  Press Enter to continue...")
        self._enter_raw()
        self._echo("")

    @staticmethod
    def _print_cmd_help():
        print("""
  Commands:
    A, B, X, Y, L, R, ZL, ZR, L3, R3   — hold button
    UP, DOWN, LEFT, RIGHT              — d-pad
    PLUS, MINUS, HOME                  — system
    release | none                     — release all
    state                              — show all pads
    stick left|right <x> <y>           — set stick (0-255)
    pad <N>                            — switch active pad
    pad <N> <command>                  — run command on specific pad
    quit                               — stop server
""")

    @property
    def client_connected(self) -> bool:
        return self._client_addr is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal raw-mode helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _read_key():
    c = os.read(_fd, 1)
    if not c:
        return None, False, None
    ch = c.decode('utf-8', errors='replace')
    if ch == '\x1b':
        import select
        if select.select([sys.stdin], [], [], 0.05)[0]:
            c2 = os.read(_fd, 1).decode('utf-8', errors='replace')
            if c2 == '[':
                c3 = os.read(_fd, 1).decode('utf-8', errors='replace')
                if c3 in ARROW_KEY:
                    return ch, True, c3
    return ch, False, None


# ═══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="DSU Server for Eden Switch Emulator input testing")
    parser.add_argument("--port", type=int, default=None,
                        help="UDP port (default: from config or 26760)")
    parser.add_argument("--pads", type=int, default=None, metavar="N",
                        help="Number of virtual pads (1-4)")
    parser.add_argument("-c", "--config", type=str, default="keyboard_config.json",
                        help="Keyboard config JSON (default: keyboard_config.json)")
    parser.add_argument("--no-keyboard", dest="keyboard", action="store_false",
                        default=True, help="Disable keyboard input")
    args = parser.parse_args()

    server = DsuServer(
        port=args.port or 26760,
        num_pads=args.pads or 1,
        keyboard=args.keyboard,
        config_path=args.config,
    )
    server.start()


if __name__ == "__main__":
    main()
