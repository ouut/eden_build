#!/usr/bin/env python3
"""
DSU Protocol Test Server for Eden/Citron Switch Emulators.

Spoofs a DSU (Cemuhook) controller server to test whether the emulator
correctly receives and processes all button, stick, and motion inputs.

Usage:
  python3 dsu_test.py                  # Cycle through all buttons
  python3 dsu_test.py -i               # Interactive mode
  python3 dsu_test.py --button A       # Hold button A
  python3 dsu_test.py --button A,B     # Hold A and B together
  python3 dsu_test.py --list           # List all button names
  python3 dsu_test.py --stick-left 128 0    # Left stick full right
  python3 dsu_test.py --pads 4              # 4-player test
"""

import argparse
import selectors
import socket
import struct
import time
import sys

# ─── DSU Protocol Constants ───────────────────────────────────────────
SERVER_MAGIC    = 0x53555344   # "DSUS"
CLIENT_MAGIC    = 0x43555344   # "DSUC"
PROTO_VERSION   = 1001
TYPE_VERSION    = 0x00100000
TYPE_PORT_INFO  = 0x00100001
TYPE_PAD_DATA   = 0x00100002

# DSU button bit positions
DSU_BUTTON = {
    "Share":        1 << 0,   "L3":           1 << 1,
    "R3":           1 << 2,   "Options":      1 << 3,
    "DUp":          1 << 4,   "DRight":       1 << 5,
    "DDown":        1 << 6,   "DLeft":        1 << 7,
    "L2":           1 << 8,   "R2":           1 << 9,
    "L1":           1 << 10,  "R1":           1 << 11,
    "Triangle":     1 << 12,  "Circle":       1 << 13,
    "Cross":        1 << 14,  "Square":       1 << 15,
}

DSUSWITCH = {
    "Share":     "Minus (-)",      "L3":        "Left Stick Press",
    "R3":        "Right Stick Press", "Options":   "Plus (+)",
    "DUp":       "D-Pad Up",       "DRight":    "D-Pad Right",
    "DDown":     "D-Pad Down",     "DLeft":     "D-Pad Left",
    "L2":        "ZL",             "R2":        "ZR",
    "L1":        "L",              "R1":        "R",
    "Triangle":  "X",              "Circle":    "A",
    "Cross":     "B",              "Square":    "Y",
}

# Interactive mode command aliases (shortcuts → DSU button names)
CMD_ALIASES = {
    "a":       "Circle",     "b":       "Cross",
    "x":       "Triangle",   "y":       "Square",
    "l":       "L1",         "r":       "R1",
    "zl":      "L2",         "zr":      "R2",
    "l3":      "L3",         "r3":      "R3",
    "+":       "Options",    "-":       "Share",
    "up":      "DUp",        "down":    "DDown",
    "left":    "DLeft",      "right":   "DRight",
    "home":    "Home",       "share":   "Share",
    "options": "Options",    "none":    None,
}


# ─── Button Parser ────────────────────────────────────────────────────

def parse_button_names(raw: str):
    """Parse comma-separated button names, case-insensitive. Returns (mask, labels)."""
    mask = 0
    labels = []
    for name in raw.split(","):
        name = name.strip()
        if not name:
            continue
        match = None
        for dsu_name in DSU_BUTTON:
            if dsu_name.lower() == name.lower():
                match = dsu_name
                break
        if match:
            mask |= DSU_BUTTON[match]
            labels.append(f"{match} -> {DSUSWITCH[match]}")
        else:
            print(f"Warning: Unknown button '{name}'. Use --list to see all names.")
    return mask, labels


# ─── Packet Builders ──────────────────────────────────────────────────

def crc32(data: bytes) -> int:
    """CRC-32 matching boost::crc_32_type."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF


def build_header(msg_type: int, payload_len: int, sender_id: int = 0) -> bytes:
    header = struct.pack("<IHHII",
        SERVER_MAGIC,          # magic
        PROTO_VERSION,         # protocol_version
        payload_len + 4,       # payload_length (includes type field)
        0,                     # crc placeholder
        sender_id,             # id
    )
    return header


def build_version_response(request_id: int) -> bytes:
    data = struct.pack("<H", PROTO_VERSION)
    header = build_header(TYPE_VERSION, 2, request_id)
    msg = header + struct.pack("<I", TYPE_VERSION) + data
    crc = crc32(msg)
    return msg[:8] + struct.pack("<I", crc) + msg[12:]


def build_port_info_response(request_id: int, pad_count: int = 1) -> bytes:
    entries = b''
    for i in range(pad_count):
        entries += struct.pack("<BBBB6sBB",
            i, 2, 2, 1, b'\x11\x22\x33\x44\x55\x66', 5, 1)
    data = struct.pack("<B", pad_count) + entries
    header = build_header(TYPE_PORT_INFO, 1 + 12 * pad_count, request_id)
    msg = header + struct.pack("<I", TYPE_PORT_INFO) + data
    crc = crc32(msg)
    return msg[:8] + struct.pack("<I", crc) + msg[12:]


def build_pad_data_response(request_id: int, buttons: int = 0,
                             home: int = 0, touch: int = 0,
                             lx: int = 128, ly: int = 128,
                             rx: int = 128, ry: int = 128,
                             counter: int = 0, pad_id: int = 0) -> bytes:
    port_info = struct.pack("<BBBB6sBB",
        pad_id, 2, 2, 1, b'\x11\x22\x33\x44\x55\x66', 5, 1)

    pad_data = struct.pack("<IHBBBBBB",
        counter,      # packet_counter (4)
        buttons,      # digital_button (2)
        home,         # home (1)
        touch,        # touch_hard_press (1)
        lx,           # left_stick_x (1)
        ly,           # left_stick_y (1)
        rx,           # right_stick_x (1)
        ry,           # right_stick_y (1)
    )
    pad_data += b'\x00' * 12                              # analog buttons
    pad_data += b'\x00' * 12                              # touch data
    pad_data += struct.pack("<Q", int(time.time() * 1_000_000))  # motion timestamp
    pad_data += struct.pack("<fff", 0.0, 0.0, 1.0)        # accel
    pad_data += struct.pack("<fff", 0.0, 0.0, 0.0)        # gyro

    full_pad = port_info + pad_data
    header = build_header(TYPE_PAD_DATA, len(full_pad), request_id)
    msg = header + struct.pack("<I", TYPE_PAD_DATA) + full_pad
    crc = crc32(msg)
    return msg[:8] + struct.pack("<I", crc) + msg[12:]


# ─── Request Parser ───────────────────────────────────────────────────

def parse_request(data: bytes, addr) -> tuple:
    if len(data) < 20:
        return None
    magic, proto, payload_len, crc, req_id = struct.unpack_from("<IHHII", data, 0)
    if magic != CLIENT_MAGIC:
        return None
    msg_type = struct.unpack_from("<I", data, 16)[0]
    return msg_type, req_id


# ─── Interactive Command Handler ──────────────────────────────────────

def _pad_configs(state, pad_id):
    """Get or create config for a pad."""
    while len(state["pads"]) <= pad_id:
        state["pads"].append({"buttons": 0, "lx": 128, "ly": 128, "rx": 128, "ry": 128})
    return state["pads"][pad_id]


def _set_buttons(state, pad_id, mask):
    """Set button mask for a specific pad."""
    cfg = _pad_configs(state, pad_id)
    cfg["buttons"] = mask
    state["auto"] = False


def _cmd_help():
    print("""
  Interactive commands (Eden polls every ~3s):

  BUTTONS (press one, release others):
    a  b  x  y          Face buttons
    l  r  zl  zr        Shoulder / triggers
    up  down  left  right  D-Pad
    +  -                 Plus / Minus (= Options / Share)
    l3  r3               Stick presses
    home  share          System buttons

  COMBOS:
    a,b     Hold A and B together
    l,zr    Hold L and ZR together

  STICKS:
    stick 128 0          Left stick up
    stick 255 128        Left stick right
    rstick 128 255       Right stick down

  CONTROL:
    pad 1 a              Target pad 1, press A
    pads                 Show current state
    none                 Release all buttons, center sticks
    auto                 Toggle auto-cycling mode
    auto 0.5             Auto-cycle at 0.5s interval
    list                 List all button names
    quit / q             Exit
""")


def handle_command(cmd: str, state):
    """Parse and execute an interactive command. Returns True to continue, False to quit."""
    cmd = cmd.strip()
    if not cmd:
        return True
    if cmd in ("quit", "q"):
        return False

    # Help
    if cmd in ("help", "?"):
        _cmd_help()
        return True

    # List all button names
    if cmd == "list":
        print(f"{'Shortcut':<10} {'DSU':<14} {'Switch'}")
        print("-" * 40)
        for short, dsu in sorted(CMD_ALIASES.items()):
            if dsu:
                sw = DSUSWITCH.get(dsu, "?")
                print(f"  {short:<8}  {dsu:<12}  {sw}")
        return True

    # Show current state
    if cmd == "pads":
        for i, cfg in enumerate(state["pads"]):
            names = _button_names(cfg["buttons"])
            label = ", ".join(names) if names else "(none)"
            print(f"  Pad {i}: [{label}]  L=({cfg['lx']},{cfg['ly']}) R=({cfg['rx']},{cfg['ry']})")
        print(f"  Auto: {'on' if state['auto'] else 'off'}  interval={state['interval']}s")
        return True

    # Auto toggle
    if cmd == "auto":
        state["auto"] = not state["auto"]
        state["auto_idx"] = 0
        print(f"  Auto mode: {'ON' if state['auto'] else 'OFF'}")
        return True

    # Auto with interval
    if cmd.startswith("auto "):
        try:
            state["interval"] = float(cmd.split()[1])
            state["auto"] = True
            state["auto_idx"] = 0
            print(f"  Auto mode ON, interval={state['interval']}s")
        except (ValueError, IndexError):
            print("  Usage: auto <seconds>")
        return True

    # Release all
    if cmd == "none":
        for cfg in state["pads"]:
            cfg["buttons"] = 0
            cfg["lx"] = cfg["ly"] = cfg["rx"] = cfg["ry"] = 128
        state["auto"] = False
        print("  All released")
        return True

    # Stick commands
    if cmd.startswith("stick ") or cmd.startswith("rstick "):
        parts = cmd.split()
        is_right = parts[0] == "rstick"
        pad_id = state["active_pad"]
        try:
            x, y = int(parts[1]), int(parts[2])
            x = max(0, min(255, x))
            y = max(0, min(255, y))
        except (ValueError, IndexError):
            print("  Usage: stick <x> <y>  or  rstick <x> <y>")
            return True
        cfg = _pad_configs(state, pad_id)
        if is_right:
            cfg["rx"], cfg["ry"] = x, y
        else:
            cfg["lx"], cfg["ly"] = x, y
        side = "R" if is_right else "L"
        print(f"  Pad {pad_id} {side}-Stick -> ({x}, {y})")
        return True

    # Pad target switch
    if cmd.startswith("pad "):
        parts = cmd.split()
        if len(parts) < 2:
            print("  Usage: pad <N> [command]")
            return True
        try:
            new_pad = int(parts[1])
        except ValueError:
            print(f"  Invalid pad: {parts[1]}")
            return True
        if new_pad < 0 or new_pad >= state["num_pads"]:
            print(f"  Pad must be 0-{state['num_pads'] - 1}")
            return True
        # "pad N" alone → switch active pad
        if len(parts) == 2:
            state["active_pad"] = new_pad
            print(f"  Active pad: {new_pad}")
            return True
        # "pad N <command>" → run command on that pad
        saved = state["active_pad"]
        state["active_pad"] = new_pad
        handle_command(" ".join(parts[2:]), state)
        state["active_pad"] = saved
        return True

    # Button commands
    btn_mask = 0
    btn_names = []
    raw_names = cmd.split(",")
    for name in raw_names:
        name = name.strip()
        if not name:
            continue
        # Try alias first, then direct DSU name
        dsu_name = CMD_ALIASES.get(name, name)
        if dsu_name is None:
            continue  # "none" as button name → skip
        if dsu_name in DSU_BUTTON:
            btn_mask |= DSU_BUTTON[dsu_name]
            btn_names.append(f"{dsu_name} -> {DSUSWITCH[dsu_name]}")
        else:
            print(f"  Unknown: '{name}'")

    _set_buttons(state, state["active_pad"], btn_mask)
    label = ", ".join(btn_names) if btn_names else "(none)"
    print(f"  Pad {state['active_pad']}: [{label}]")
    return True


def _button_names(mask):
    """Convert button mask to list of shortcut names."""
    names = []
    rev = {v: k for k, v in CMD_ALIASES.items() if v}
    for dsu_name, bit in DSU_BUTTON.items():
        if mask & bit:
            names.append(rev.get(dsu_name, dsu_name))
    return names


# ─── DSU Request Handler (shared by interactive and normal mode) ──────

def handle_dsu_request(sock, data, addr, state):
    """Process one DSU request and send response. Returns True if a PadData was sent."""
    result = parse_request(data, addr)
    if result is None:
        return False

    msg_type, req_id = result

    if msg_type == TYPE_VERSION:
        resp = build_version_response(req_id)
        print(f"[->] Version -> {addr}")
    elif msg_type == TYPE_PORT_INFO:
        resp = build_port_info_response(req_id, state["num_pads"])
        print(f"[->] PortInfo ({state['num_pads']} pads) -> {addr}")
    elif msg_type == TYPE_PAD_DATA:
        pid = state["pad_idx"] % state["num_pads"]
        state["pad_idx"] += 1
        cfg = _pad_configs(state, pid)

        buttons = cfg["buttons"]
        lx, ly, rx, ry = cfg["lx"], cfg["ly"], cfg["rx"], cfg["ry"]

        if state["auto"]:
            names = list(DSU_BUTTON.keys())
            name = names[state["auto_idx"] % len(names)]
            buttons = DSU_BUTTON[name]
            state["auto_idx"] += 1
            if state["auto_idx"] % state["num_pads"] == 0:
                time.sleep(state["interval"])

        resp = build_pad_data_response(req_id, buttons,
                                       lx=lx, ly=ly, rx=rx, ry=ry,
                                       counter=state["counter"], pad_id=pid)
        state["counter"] += 1

        names = _button_names(buttons)
        label = ", ".join(names) if names else "(none)"
        print(f"[->] PadData #{state['counter']}  pad={pid}  [{label}] -> {addr}")
    else:
        print(f"[?]  Unknown type 0x{msg_type:08x} from {addr}")
        return False

    sock.sendto(resp, addr)
    return True


# ─── Server Modes ─────────────────────────────────────────────────────

def serve(args):
    """Non-interactive mode (original behavior)."""
    state = _init_state(args)
    sock = _create_socket(args.port)

    print(f"[DSU] UDP 0.0.0.0:{args.port}  {state['num_pads']} pad(s)  Ctrl+C to stop")
    _print_state(state)

    try:
        while True:
            try:
                data, addr = sock.recvfrom(128)
            except socket.timeout:
                continue
            handle_dsu_request(sock, data, addr, state)
    except KeyboardInterrupt:
        print("\n[DSU] Stopped.")


def push_pad_data(sock, state):
    """Immediately send PadData for all pads to the cached client address."""
    addr = state.get("client_addr")
    if not addr:
        return
    for pid in range(state["num_pads"]):
        cfg = _pad_configs(state, pid)
        resp = build_pad_data_response(state.get("last_req_id", 0),
                                       cfg["buttons"],
                                       lx=cfg["lx"], ly=cfg["ly"],
                                       rx=cfg["rx"], ry=cfg["ry"],
                                       counter=state["counter"], pad_id=pid)
        sock.sendto(resp, addr)
        state["counter"] += 1
    # Show only the active pad
    cfg = _pad_configs(state, state["active_pad"])
    names = _button_names(cfg["buttons"])
    label = ", ".join(names) if names else "(none)"
    print(f"[push] Pad 0-{state['num_pads']-1}  [{label}]")


def serve_interactive(args):
    """Interactive mode: multiplex stdin and UDP socket with push on command."""
    state = _init_state(args)
    sock = _create_socket(args.port)
    sock.settimeout(0.1)

    sel = selectors.DefaultSelector()
    sel.register(sock, selectors.EVENT_READ, data="socket")
    sel.register(sys.stdin, selectors.EVENT_READ, data="stdin")

    print(f"[DSU] Interactive mode  UDP 0.0.0.0:{args.port}  {state['num_pads']} pad(s)")
    print("[DSU] Waiting for Eden to connect...")
    print("[DSU] Commands push instantly once connected (type help, or quit)")
    _print_state(state)

    try:
        while True:
            events = sel.select(timeout=0.5)
            for key, _mask in events:
                if key.data == "socket":
                    try:
                        data, addr = sock.recvfrom(128)
                    except socket.timeout:
                        continue
                    result = parse_request(data, addr)
                    if result is None:
                        continue
                    msg_type, req_id = result
                    state["client_addr"] = addr
                    state["last_req_id"] = req_id

                    if msg_type == TYPE_VERSION:
                        resp = build_version_response(req_id)
                        sock.sendto(resp, addr)
                        print(f"[->] Version -> {addr}")
                    elif msg_type == TYPE_PORT_INFO:
                        resp = build_port_info_response(req_id, state["num_pads"])
                        sock.sendto(resp, addr)
                        print(f"[->] PortInfo ({state['num_pads']} pads) -> {addr}")
                    elif msg_type == TYPE_PAD_DATA:
                        handle_dsu_request(sock, data, addr, state)
                    else:
                        print(f"[?] Unknown type 0x{msg_type:08x} from {addr}")
                elif key.data == "stdin":
                    line = sys.stdin.readline()
                    if not line:
                        break
                    if not handle_command(line, state):
                        print("[DSU] Stopped.")
                        return
                    # Push immediately — no waiting for poll
                    push_pad_data(sock, state)
    except KeyboardInterrupt:
        print("\n[DSU] Stopped.")


# ─── State Management ─────────────────────────────────────────────────

def _init_state(args):
    pads = []
    for i in range(args.num_pads):
        mask, _labels = args.pad_buttons[i] if args.pad_buttons[i] else (args.buttons_mask, args.buttons_arg)
        pads.append({
            "buttons": mask,
            "lx": args.stick_left_x,
            "ly": args.stick_left_y,
            "rx": args.stick_right_x,
            "ry": args.stick_right_y,
        })
    return {
        "pads": pads,
        "num_pads": args.num_pads,
        "pad_idx": 0,
        "counter": 0,
        "active_pad": 0,
        "auto": args.auto,
        "interval": args.interval,
        "auto_idx": 0,
    }


def _create_socket(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)
    return sock


def _print_state(state):
    for i, cfg in enumerate(state["pads"]):
        names = _button_names(cfg["buttons"])
        label = ", ".join(names) if names else "(none)"
        print(f"  Pad {i}: [{label}]  L=({cfg['lx']},{cfg['ly']}) R=({cfg['rx']},{cfg['ry']})")
    if state["auto"]:
        print(f"  Auto: ON  interval={state['interval']}s")
    print()


# ─── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DSU Protocol Test Server for Switch Emulators",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -i                            Interactive mode
  %(prog)s                               Cycle all buttons automatically
  %(prog)s --button A                    Hold A
  %(prog)s --button A,B,L                Hold A + B + L
  %(prog)s --pads 4                      Cycle buttons on 4 pads
  %(prog)s --pads 2 --button A           Hold A on both pads
  %(prog)s --pad-button 0:A --pad-button 1:B   Pad 0 holds A, pad 1 holds B
  %(prog)s --list                        List all button names
        """,
    )

    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Interactive mode: type button commands in real-time")
    parser.add_argument("--port", type=int, default=26760, help="UDP port (default: 26760)")
    parser.add_argument("--list", action="store_true", help="List all button names and exit")
    parser.add_argument("--pads", type=int, default=1, metavar="N",
                        help="Number of virtual pads, max 4 (default: 1)")
    parser.add_argument("--button", type=str, default="",
                        help="Buttons for ALL pads, comma-separated (e.g. A,B,DUp)")
    parser.add_argument("--pad-button", type=str, action="append", default=[],
                        metavar="PAD:BTNS",
                        help="Buttons for a specific pad (e.g. 0:A,B). Can be repeated.")
    parser.add_argument("--auto", action="store_true",
                        help="Automatically cycle through all buttons")
    parser.add_argument("--interval", type=float, default=1.5,
                        help="Seconds between button cycles in --auto mode (default: 1.5)")
    parser.add_argument("--stick-left", nargs=2, type=int, metavar=("X", "Y"), default=[128, 128],
                        help="Left stick position (0-255, default: 128 128 = center)")
    parser.add_argument("--stick-right", nargs=2, type=int, metavar=("X", "Y"), default=[128, 128],
                        help="Right stick position (0-255, default: 128 128 = center)")

    args = parser.parse_args()

    if args.list:
        print("DSU Button Names and their Switch equivalents:")
        print(f"{'DSU Name':<14} {'Bit':<6} {'Switch Button'}")
        print("-" * 42)
        for name, bitmask in DSU_BUTTON.items():
            switch_name = DSUSWITCH.get(name, "?")
            print(f"  {name:<12}  0x{bitmask:04x}  {switch_name}")
        return

    # Parse global buttons
    args.buttons_mask = 0
    args.buttons_arg = []
    if args.button:
        args.buttons_mask, args.buttons_arg = parse_button_names(args.button)

    # Parse per-pad buttons
    args.num_pads = max(1, min(4, args.pads))
    args.pad_buttons = [None] * args.num_pads
    for entry in args.pad_button:
        if ":" not in entry:
            print(f"Warning: --pad-button format is 'PAD:BTNS', got '{entry}'. Skipping.")
            continue
        pad_str, btns_str = entry.split(":", 1)
        try:
            pid = int(pad_str)
        except ValueError:
            print(f"Warning: Invalid pad ID '{pad_str}'. Skipping.")
            continue
        if pid < 0 or pid >= args.num_pads:
            print(f"Warning: Pad ID {pid} out of range (0-{args.num_pads - 1}). Skipping.")
            continue
        args.pad_buttons[pid] = parse_button_names(btns_str)

    # Parse stick positions
    args.stick_left_x = max(0, min(255, args.stick_left[0]))
    args.stick_left_y = max(0, min(255, args.stick_left[1]))
    args.stick_right_x = max(0, min(255, args.stick_right[0]))
    args.stick_right_y = max(0, min(255, args.stick_right[1]))

    # Default to auto if no buttons specified (non-interactive only)
    if not args.interactive and not args.button and not args.pad_button and not args.auto:
        args.auto = True
        print("[*] No button specified, defaulting to --auto mode.\n")

    if args.interactive:
        serve_interactive(args)
    else:
        serve(args)


if __name__ == "__main__":
    main()
