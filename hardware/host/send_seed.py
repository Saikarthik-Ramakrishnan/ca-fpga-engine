#!/usr/bin/env python3
"""
send_seed.py

The PC half of the loop, for the real flashed board. Encodes a pattern
into the SEED protocol, or a ruleset into the RULE protocol, and writes it
to the serial port. The board answers by streaming the result back on the
same port, which the console's Live tab (Web Serial), `--watch` below, or
any 0xAA-sync decoder can read.

The encoding itself lives in protocol.py, which is also what the console
and the testbenches are pinned to. This file is transport only.

Usage:
  python3 send_seed.py --port /dev/ttyUSB1 --pattern glider
  python3 send_seed.py --port /dev/ttyUSB1 --pattern soup --density 0.25
  python3 send_seed.py --port /dev/ttyUSB1 --pattern blinker --rows 16 --cols 16

  # set the rule on a bitstream built with RULE_CFG=1 (the default)
  python3 send_seed.py --port /dev/ttyUSB1 --rule highlife
  python3 send_seed.py --port /dev/ttyUSB1 --rule seeds --pattern glider

  # print the packet without touching a serial port, for checking the
  # encoding against the testbenches or without a board attached
  python3 send_seed.py --dry-run --rule daynight --pattern glider

  # after sending, decode frames back off the wire as ASCII art
  python3 send_seed.py --port /dev/ttyUSB1 --pattern glider --watch 12

Needs pyserial for anything but --dry-run:  pip install pyserial

Note on the port: the Tang Primer 20K dock's BL616 exposes TWO serial
interfaces over one USB cable (one is the debugger). If nothing comes
back, try the other /dev/ttyUSB* / COM* it created.

Note on --rule: a bitstream built with RULE_CFG=0 has Conway welded into
the gates and ignores 0x33 entirely. There is no error to report in that
case, on the board or here; the rule simply does not change.
"""

import argparse
import random
import sys
import time

from protocol import (
    RULES, encode_seed, encode_rule_named, decode_frames, render,
    hex_bytes, payload_bytes, rule_masks, mask_notation,
)

# The bitstream's CLKS_PER_BIT and this number are one setting seen from
# two sides: 27,000,000 / CLKS_PER_BIT. A mismatch produces bytes with no
# sync rather than an error, so --baud must follow a rebuilt bitstream.
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


def main():
    ap = argparse.ArgumentParser(
        description="Send a seed and/or a rule to a flashed CELL-NET board.")
    ap.add_argument("--port", help="serial port; omit only with --dry-run")
    ap.add_argument("--pattern", choices=PATTERNS,
                    help="pattern to seed; omit to send only a rule")
    ap.add_argument("--rule", choices=sorted(RULES),
                    help="ruleset to load; needs a RULE_CFG=1 bitstream")
    ap.add_argument("--rows", type=int, default=16,
                    help="must match the ROWS the bitstream was built with")
    ap.add_argument("--cols", type=int, default=16)
    ap.add_argument("--density", type=float, default=0.25,
                    help="only used by --pattern soup")
    ap.add_argument("--watch", type=int, metavar="N", default=0,
                    help="after sending, decode and print N frames coming back")
    ap.add_argument("--baud", type=int, default=BAUD,
                    help=f"must match the bitstream: 27,000,000 divided by "
                         f"its CLKS_PER_BIT (default {BAUD}, from 234)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the packets instead of opening a port")
    args = ap.parse_args()

    if not args.pattern and not args.rule:
        ap.error("nothing to send: give --pattern, --rule, or both")
    if not args.port and not args.dry_run:
        ap.error("--port is required unless --dry-run is given")

    try:
        payload_bytes(args.rows, args.cols)
    except ValueError as exc:
        sys.exit(str(exc))

    packets = []

    # rule first: a rule sent after a seed would still apply, but sending
    # it first means the pattern's very first generation already runs
    # under the rule the user asked for.
    if args.rule:
        birth, survive = rule_masks(args.rule)
        packets.append((
            f"RULE {args.rule} {mask_notation(birth, survive)}",
            encode_rule_named(args.rule),
        ))

    if args.pattern:
        if args.pattern == "soup":
            grid = soup(args.rows, args.cols, args.density)
        else:
            grid = PATTERNS[args.pattern](args.rows, args.cols)
        packets.append((
            f"SEED {args.pattern} {args.rows}x{args.cols}",
            encode_seed(grid, args.rows, args.cols),
        ))

    for label, packet in packets:
        print(f"{label:<28} {len(packet):>3} bytes  {hex_bytes(packet[:12])}"
              + (" ..." if len(packet) > 12 else ""))

    if args.dry_run:
        print("\ndry run: nothing was written to a port")
        return

    try:
        import serial
    except ImportError:
        sys.exit("pyserial not installed: pip install pyserial")

    with serial.Serial(args.port, args.baud, timeout=1) as port:
        for label, packet in packets:
            port.write(packet)
            port.flush()
            # let the chip finish one transfer before the next command
            # starts; the loaders time out on a stall, not on a gap.
            time.sleep(0.05)
        print(f"\nsent to {args.port}")

        if args.watch:
            print(f"decoding {args.watch} frames back off the wire "
                  f"(Ctrl-C to stop)\n")
            n = payload_bytes(args.rows, args.cols)

            def byte_stream():
                while True:
                    chunk = port.read(max(1, (n + 1) * 4))
                    if not chunk:
                        return
                    for b in chunk:
                        yield b

            try:
                for i, bits in enumerate(decode_frames(
                        byte_stream(), args.rows, args.cols), start=1):
                    print(f"--- frame {i} ---")
                    print(render(bits, args.rows, args.cols))
                    print()
                    if i >= args.watch:
                        break
            except KeyboardInterrupt:
                print("stopped")


if __name__ == "__main__":
    main()
