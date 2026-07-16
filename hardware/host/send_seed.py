#!/usr/bin/env python3
"""
send_seed.py

The PC half of the Phase 4.5 loop, for the real flashed board: encodes a
pattern into the SEED protocol (0x55 + one grid snapshot, byte 0 = grid
bits [7:0]) and writes it to the serial port. The board answers by
streaming the pattern's evolution back on the same port, which the
console's Live tab (Web Serial) or any 0xAA-sync decoder can watch.

This is byte-for-byte the transfer test_cellnet_loopback.py already
proved against the simulated chip; only the transport changes from
simulated wire to real /dev/tty*.

Usage:
  python3 send_seed.py --port /dev/ttyUSB1 --pattern glider
  python3 send_seed.py --port /dev/ttyUSB1 --pattern soup --density 0.25
  python3 send_seed.py --port /dev/ttyUSB1 --pattern blinker --rows 16 --cols 16

Needs pyserial:  pip install pyserial

Note on the port: the Tang Primer 20K dock's BL616 exposes TWO serial
interfaces over one USB cable (one is the debugger). If nothing comes
back, try the other /dev/ttyUSB* / COM* it created.
"""

import argparse
import random
import sys

try:
    import serial
except ImportError:
    sys.exit("pyserial not installed: pip install pyserial")

CMD_SEED = 0x55
BAUD = 115200


def glider(rows, cols, cx=2, cy=2):
    g = [[0] * cols for _ in range(rows)]
    for dx, dy in [(0, 0), (1, 0), (2, 0), (2, 1), (1, 2)]:
        g[(cy + dy) % rows][(cx + dx) % cols] = 1
    return g


def blinker(rows, cols):
    g = [[0] * cols for _ in range(rows)]
    for dx in range(3):
        g[rows // 2][(cols // 2 - 1 + dx) % cols] = 1
    return g


def soup(rows, cols, density, seed=None):
    rng = random.Random(seed)
    return [[1 if rng.random() < density else 0 for _ in range(cols)]
            for _ in range(rows)]


PATTERNS = {"glider": glider, "blinker": blinker, "soup": soup}


def grid_to_payload(grid, rows, cols):
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= 1 << (r * cols + c)
    num_bytes = (rows * cols) // 8
    return bytes((bits >> (8 * i)) & 0xFF for i in range(num_bytes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--pattern", choices=PATTERNS, default="glider")
    ap.add_argument("--rows", type=int, default=16,
                    help="must match the ROWS the bitstream was built with")
    ap.add_argument("--cols", type=int, default=16)
    ap.add_argument("--density", type=float, default=0.25,
                    help="only used by --pattern soup")
    args = ap.parse_args()

    if (args.rows * args.cols) % 8 != 0:
        sys.exit("rows*cols must be a multiple of 8")

    if args.pattern == "soup":
        grid = soup(args.rows, args.cols, args.density)
    else:
        grid = PATTERNS[args.pattern](args.rows, args.cols)

    payload = grid_to_payload(grid, args.rows, args.cols)

    with serial.Serial(args.port, BAUD, timeout=1) as port:
        port.write(bytes([CMD_SEED]) + payload)
        port.flush()

    print(f"sent SEED + {len(payload)} bytes ({args.pattern}, "
          f"{args.rows}x{args.cols}) to {args.port}")
    print("the board is now streaming this pattern's evolution back "
          "on the same port")


if __name__ == "__main__":
    main()
