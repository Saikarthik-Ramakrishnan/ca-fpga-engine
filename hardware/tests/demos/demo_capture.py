# demo_capture.py
#
# Not a correctness test -- this just runs the real simulated chip and
# records what actually comes out over tx_serial, so we can turn it into
# something you can watch. Same decoder proven in test_uart_tx.py and
# test_cellnet_top.py, just used here to capture a sequence instead of
# assert against it.

import sys
import os
import json
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_uart_tx import receive_uart_byte  # noqa: E402

ROWS = 8
COLS = 8
NUM_BYTES = (ROWS * COLS) // 8
CLKS_PER_BIT = 4
SYNC_BYTE = 0xAA
NUM_CYCLES = 12000  # long enough for a good number of frames


def grid_to_bits(grid, rows, cols) -> int:
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= (1 << (r * cols + c))
    return bits


def random_grid(rows, cols, density, seed):
    rng = random.Random(seed)
    return [[1 if rng.random() < density else 0 for _ in range(cols)] for _ in range(rows)]


async def frame_collector(dut, frames: list):
    while True:
        sync = await receive_uart_byte(dut, CLKS_PER_BIT)
        if sync != SYNC_BYTE:
            continue
        value = 0
        for byte_i in range(NUM_BYTES):
            b = await receive_uart_byte(dut, CLKS_PER_BIT)
            value |= (b << (byte_i * 8))
        frames.append(value)


@cocotb.test()
async def capture_live_stream(dut):
    clock = Clock(dut.clk, 2, unit="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.load.value = 0
    dut.seed.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    py_grid = random_grid(ROWS, COLS, density=0.25, seed=25)
    dut.load.value = 1
    dut.seed.value = grid_to_bits(py_grid, ROWS, COLS)
    await RisingEdge(dut.clk)
    dut.load.value = 0

    frames = []
    cocotb.start_soon(frame_collector(dut, frames))

    for _ in range(NUM_CYCLES):
        await RisingEdge(dut.clk)

    for _ in range(NUM_BYTES * 10 * CLKS_PER_BIT):
        await RisingEdge(dut.clk)

    out_path = os.path.join(os.path.dirname(__file__), "uart_capture.json")
    with open(out_path, "w") as f:
        # frame values go up to 2^64, and JavaScript's JSON.parse silently
        # loses precision on integers past 2^53 (JS numbers are IEEE754
        # doubles). Writing hex strings instead keeps every bit intact for
        # whatever eventually reads this file, in Python or JS.
        json.dump({
            "rows": ROWS,
            "cols": COLS,
            "frames": [f"0x{v:016x}" for v in frames],
        }, f)

    dut._log.info(f"Captured {len(frames)} real frames off tx_serial, wrote {out_path}")
