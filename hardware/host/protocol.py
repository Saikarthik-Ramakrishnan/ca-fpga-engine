#!/usr/bin/env python3
"""
protocol.py

The CELL-NET wire protocol, in one place, with no serial dependency so it
can be imported and tested anywhere.

Three magic bytes, chosen to be far apart and none a rotation of another:

    0x55  SEED, PC -> chip. Followed by rows*cols/8 payload bytes.
    0x33  RULE, PC -> chip. Followed by 3 payload bytes.
    0xAA  SYNC, chip -> PC. Followed by rows*cols/8 frame bytes.

One byte-order convention in both directions: payload byte 0 carries grid
bits [7:0], byte 1 carries bits [15:8], and so on. Cell (r, c) is bit
r*cols + c. seed_loader.v, grid_streamer.v and this file must agree, and
`python3 protocol.py` asserts they do against the same vectors
hardware/tests/test_rule_loader.py and software_prototype/check_console.js
check, so the Verilog, the browser and the host tools are pinned to one
encoding by three independent tests.
"""
from __future__ import annotations

import sys
import os

CMD_SEED = 0x55
CMD_RULE = 0x33
SYNC_BYTE = 0xAA

RULE_PAYLOAD_BYTES = 3

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                 "software_prototype", "parallelism_ladder"),
)
from golden_rule import RULES, rule_masks, mask_notation  # noqa: E402


# ------------------------------------------------------------------ grids
def grid_to_bits(grid, rows: int, cols: int) -> int:
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= 1 << (r * cols + c)
    return bits


def bits_to_grid(bits: int, rows: int, cols: int):
    return [[(bits >> (r * cols + c)) & 1 for c in range(cols)] for r in range(rows)]


def payload_bytes(rows: int, cols: int) -> int:
    if (rows * cols) % 8 != 0:
        raise ValueError("rows*cols must be a multiple of 8")
    return (rows * cols) // 8


# ---------------------------------------------------------------- encoders
def encode_seed(grid, rows: int, cols: int) -> bytes:
    """0x55 plus one full grid snapshot, low bits in the low byte."""
    n = payload_bytes(rows, cols)
    bits = grid_to_bits(grid, rows, cols)
    return bytes([CMD_SEED]) + bytes((bits >> (8 * i)) & 0xFF for i in range(n))


def encode_rule(birth: int, survive: int) -> bytes:
    """0x33, birth[7:0], survive[7:0], {6'b0, survive[8], birth[8]}."""
    if not 0 <= birth <= 0x1FF or not 0 <= survive <= 0x1FF:
        raise ValueError("masks are 9 bits, one per neighbor count 0..8")
    return bytes([
        CMD_RULE,
        birth & 0xFF,
        survive & 0xFF,
        ((birth >> 8) & 1) | (((survive >> 8) & 1) << 1),
    ])


def encode_rule_named(name: str) -> bytes:
    return encode_rule(*rule_masks(name))


def hex_bytes(packet: bytes) -> str:
    return " ".join(f"{b:02X}" for b in packet)


# ---------------------------------------------------------------- decoder
def decode_frames(stream, rows: int, cols: int):
    """Yield one integer grid value per complete frame found in `stream`,
    an iterable of ints. Resyncs on 0xAA, so starting mid-stream is fine.

    This is the host twin of the console's Live tab reader and of
    test_uart_tx.receive_uart_byte's caller in the loopback test."""
    n = payload_bytes(rows, cols)
    collecting = False
    buf = []
    for byte in stream:
        if not collecting:
            if byte == SYNC_BYTE:
                collecting = True
                buf = []
            continue
        buf.append(byte)
        if len(buf) == n:
            value = 0
            for i, b in enumerate(buf):
                value |= b << (8 * i)
            yield value
            collecting = False


def render(bits: int, rows: int, cols: int, on: str = "#", off: str = ".") -> str:
    grid = bits_to_grid(bits, rows, cols)
    return "\n".join("".join(on if v else off for v in row) for row in grid)


# ------------------------------------------------------------- self-test
def _self_test() -> int:
    failures = []

    def eq(got, want, label):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # rule packets, the exact vectors check_console.js and
    # test_rule_loader.py assert
    eq(hex_bytes(encode_rule_named("conway")), "33 08 0C 00", "conway rule packet")
    eq(hex_bytes(encode_rule_named("daynight")), "33 C8 D8 03", "daynight rule packet")
    eq(len(encode_rule_named("seeds")), 1 + RULE_PAYLOAD_BYTES, "rule packet length")

    # every named rule round-trips through the wire encoding
    for name in RULES:
        birth, survive = rule_masks(name)
        packet = encode_rule(birth, survive)
        got_b = packet[1] | ((packet[3] & 1) << 8)
        got_s = packet[2] | (((packet[3] >> 1) & 1) << 8)
        eq((got_b, got_s), (birth, survive), f"{name} round trip")

    # seed packets: cell (0,0) is bit 0, cell (1,0) is bit `cols`
    rows = cols = 8
    empty = [[0] * cols for _ in range(rows)]
    eq(hex_bytes(encode_seed(empty, rows, cols)),
       "55 00 00 00 00 00 00 00 00", "empty seed packet")

    two = [[0] * cols for _ in range(rows)]
    two[0][0] = 1
    two[1][0] = 1
    eq(hex_bytes(encode_seed(two, rows, cols)),
       "55 01 01 00 00 00 00 00 00", "two-cell seed packet")

    # a frame decodes back to the grid it encoded
    import random
    rng = random.Random(11)
    grid = [[rng.randint(0, 1) for _ in range(cols)] for _ in range(rows)]
    frame = bytes([SYNC_BYTE]) + encode_seed(grid, rows, cols)[1:]
    decoded = list(decode_frames(frame, rows, cols))
    eq(len(decoded), 1, "frame count")
    if decoded:
        eq(bits_to_grid(decoded[0], rows, cols), grid, "frame round trip")

    # a decoder that starts mid-stream must resync on the next 0xAA
    noisy = bytes([0x01, 0x02, 0x03]) + frame + frame
    eq(len(list(decode_frames(noisy, rows, cols))), 2, "resync after leading noise")

    print(f"protocol.py self-test: {len(RULES)} rulesets, "
          f"{'FAILED' if failures else 'all vectors match'}")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_self_test())
