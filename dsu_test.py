#!/usr/bin/env python3
"""
DSU Protocol Test Server for Eden/Citron Switch Emulators.

Spoofs a DSU (Cemuhook) controller server to test whether the emulator
correctly receives and processes all button, stick, and motion inputs.

Supports multiple virtual pads (up to 4 per DSU server).

Usage:
  python3 dsu_test.py                  # Cycle through all buttons
  python3 dsu_test.py --button A       # Hold button A
  python3 dsu_test.py --button A,B     # Hold A and B together
  python3 dsu_test.py --list           # List all button names
  python3 dsu_test.py --stick-left 128 0    # Left stick full right
  python3 dsu_test.py --stick-right 128 128 # Right stick bottom-right
  python3 dsu_test.py --pads 4              # 4-player test (all same buttons)
"""

import argparse
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

# DSU button bit positions in the 16-bit digital_button field
# Byte 0 (bits 0-7): Share, L3, R3, Options, D-Up, D-Right, D-Down, D-Left
# Byte 1 (bits 8-15): L2, R2, L1, R1, Triangle, Circle, Cross, Square
DSU_BUTTON = {
    "Share":        1 << 0,
    "L3":           1 << 1,
    "R3":           1 << 2,
    "Options":      1 << 3,
    "DUp":          1 << 4,
    "DRight":       1 << 5,
    "DDown":        1 << 6,
    "DLeft":        1 << 7,
    "L2":           1 << 8,
    "R2":           1 << 9,
    "L1":           1 << 10,
    "R1":           1 << 11,
    "Triangle":     1 << 12,
    "Circle":       1 << 13,
    "Cross":        1 << 14,
    "Square":       1 << 15,
}

# Human-readable mapping: DSU button -> Switch equivalent
DSUSWITCH = {
    "Share":     "Minus (-)",  "L3":        "Left Stick Press",
    "R3":        "Right Stick Press", "Options":   "Plus (+)",
    "DUp":       "D-Pad Up",   "DRight":    "D-Pad Right",
    "DDown":     "D-Pad Down", "DLeft":     "D-Pad Left",
    "L2":        "ZL",         "R2":        "ZR",
    "L1":        "L",          "R1":        "R",
    "Triangle":  "X",          "Circle":    "A",
    "Cross":     "B",          "Square":    "Y",
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
            labels.append(f"{match} → {DSUSWITCH[match]}")
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
    """Build a 20-byte DSU message header (without CRC)."""
    header = struct.pack("<IHHII",
        SERVER_MAGIC,          # magic
        PROTO_VERSION,         # protocol_version
        payload_len + 4,       # payload_length (includes type field)
        0,                     # crc placeholder
        sender_id,             # id
    )
    return header


def build_version_response(request_id: int) -> bytes:
    """Response: Version (type 0x00100000)"""
    data = struct.pack("<H", PROTO_VERSION)  # 2 byte payload
    header = build_header(TYPE_VERSION, 2, request_id)
    msg = header + struct.pack("<I", TYPE_VERSION) + data
    crc = crc32(msg)
    return msg[:8] + struct.pack("<I", crc) + msg[12:]


def build_port_info_response(request_id: int, pad_count: int = 1) -> bytes:
    """Response: PortInfo (type 0x00100001) - list connected controllers"""
    # Each port info entry: id(1) + state(1) + model(1) + conn_type(1) + mac(6) + battery(1) + active(1) = 12 bytes
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
    """Response: PadData (type 0x00100002) - full controller state"""
    # PortInfo (12 bytes)
    port_info = struct.pack("<BBBB6sBB",
        pad_id, 2, 2, 1, b'\x11\x22\x33\x44\x55\x66', 5, 1)

    # PadData body (68 bytes after port_info, total PadData = 80 bytes)
    pad_data = struct.pack("<IHBBBBBB",
        counter,      # packet_counter (4)
        buttons,      # digital_button (2)
        home,         # home (1)
        touch,        # touch_hard_press (1)
        lx,           # left_stick_x (1)  0=left, 255=right, 128=center
        ly,           # left_stick_y (1)  0=top, 255=bottom, 128=center
        rx,           # right_stick_x (1)
        ry,           # right_stick_y (1)
    )

    # Analog buttons (12 bytes) - pressure-sensitive, 0-255
    analog = b'\x00' * 12
    pad_data += analog

    # Touch pad data (2 * 6 = 12 bytes) - inactive
    touch_data = b'\x00' * 12
    pad_data += touch_data

    # Motion timestamp (8 bytes)
    pad_data += struct.pack("<Q", int(time.time() * 1_000_000))

    # Accelerometer (12 bytes): x, y, z as float
    pad_data += struct.pack("<fff", 0.0, 0.0, 1.0)

    # Gyroscope (12 bytes): pitch, yaw, roll as float
    pad_data += struct.pack("<fff", 0.0, 0.0, 0.0)

    full_pad = port_info + pad_data
    header = build_header(TYPE_PAD_DATA, len(full_pad), request_id)
    msg = header + struct.pack("<I", TYPE_PAD_DATA) + full_pad
    crc = crc32(msg)
    return msg[:8] + struct.pack("<I", crc) + msg[12:]


# ─── Request Parser ───────────────────────────────────────────────────

def parse_request(data: bytes, addr) -> tuple:
    """Parse an incoming DSU request. Returns (msg_type, request_id) or None."""
    if len(data) < 20:
        return None
    magic, proto, payload_len, crc, req_id = struct.unpack_from("<IHHII", data, 0)
    if magic != CLIENT_MAGIC:
        return None
    msg_type = struct.unpack_from("<I", data, 16)[0]
    return msg_type, req_id


# ─── Main Loop ────────────────────────────────────────────────────────

def serve(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.5)
    print(f"[DSU Test Server] Listening on UDP 0.0.0.0:{args.port}")
    print(f"[DSU Test Server] {args.num_pads} pad(s) configured")
    print(f"[DSU Test Server] Press Ctrl+C to stop.\n")

    # Per-pad config
    pad_configs = []
    for i in range(args.num_pads):
        mask, labels = args.pad_buttons[i] if args.pad_buttons[i] else (args.buttons_mask, args.buttons_arg)
        pad_configs.append({
            "buttons": mask,
            "labels": labels or ["(none)"],
            "lx": args.stick_left_x,
            "ly": args.stick_left_y,
            "rx": args.stick_right_x,
            "ry": args.stick_right_y,
        })

    # Print per-pad config
    for i, cfg in enumerate(pad_configs):
        print(f"[Pad {i}]  buttons: {', '.join(cfg['labels'])}")
        print(f"         L-Stick: x={cfg['lx']}, y={cfg['ly']}  R-Stick: x={cfg['rx']}, y={cfg['ry']}")
    print()

    counter = 0
    pad_idx = 0
    all_button_names = list(DSU_BUTTON.keys())
    auto_idx = 0

    try:
        while True:
            try:
                data, addr = sock.recvfrom(128)
            except socket.timeout:
                continue

            result = parse_request(data, addr)
            if result is None:
                continue

            msg_type, req_id = result

            if msg_type == TYPE_VERSION:
                resp = build_version_response(req_id)
                print(f"[->] Version response sent to {addr}")
            elif msg_type == TYPE_PORT_INFO:
                resp = build_port_info_response(req_id, args.num_pads)
                print(f"[->] PortInfo response ({args.num_pads} pads) sent to {addr}")
            elif msg_type == TYPE_PAD_DATA:
                pid = pad_idx % args.num_pads
                cfg = pad_configs[pid]
                cur_buttons = cfg["buttons"]
                cur_labels = cfg["labels"]

                if args.auto:
                    name = all_button_names[auto_idx % len(all_button_names)]
                    for c in pad_configs:
                        c["buttons"] = DSU_BUTTON[name]
                    cur_buttons = DSU_BUTTON[name]
                    cur_labels = [f"{name} → {DSUSWITCH[name]}"]
                    auto_idx += 1
                    time.sleep(args.interval)

                resp = build_pad_data_response(req_id, cur_buttons,
                                               lx=cfg["lx"], ly=cfg["ly"],
                                               rx=cfg["rx"], ry=cfg["ry"],
                                               counter=counter, pad_id=pid)
                counter += 1
                pad_idx += 1
                label_str = ", ".join(cur_labels)
                print(f"[->] PadData #{counter}  pad={pid}  {label_str}  to {addr}")
            else:
                print(f"[?]  Unknown message type 0x{msg_type:08x} from {addr}")
                continue

            sock.sendto(resp, addr)

    except KeyboardInterrupt:
        print("\n[DSU Test Server] Stopped.")


# ─── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DSU Protocol Test Server for Switch Emulators",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Cycle all buttons automatically
  %(prog)s --button A                   Hold A
  %(prog)s --button A,B,L               Hold A + B + L
  %(prog)s --button DUp                 Press D-Pad Up
  %(prog)s --pads 4                     Cycle buttons on 4 pads
  %(prog)s --pads 2 --button A          Hold A on both pads
  %(prog)s --pad-button 0:A --pad-button 1:B   Pad 0 holds A, pad 1 holds B
  %(prog)s --list                       List all button names
  %(prog)s --stick-left 255 128         Left stick full right
  %(prog)s --button A --auto             Hold A, also cycle all buttons
        """,
    )

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

    # Parse per-pad buttons (overrides global for specified pads)
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

    # If no buttons specified and no auto, default to auto mode
    if not args.button and not args.pad_button and not args.auto:
        args.auto = True
        print("[*] No button specified, defaulting to --auto mode.\n")

    serve(args)


if __name__ == "__main__":
    main()
