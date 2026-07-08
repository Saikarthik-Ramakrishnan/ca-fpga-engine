# test_cellnet_top.py
#
# The end-to-end check for Phase 4: seed the whole chip with a known
# pattern, let it run freely, and confirm that whatever comes out over
# tx_serial is genuine, bit-exact grid data, not garbage or stale frames.
#
# Two things happen at once in this test, the same way they would with
# real hardware and a real PC:
#   1. The chip just runs. Every clock edge, the grid computes its next
#      generation, same as it always has.
#   2. A background "pretend to be a PC" task continuously watches
#      tx_serial, decodes bytes the same way test_uart_tx.py already
#      proved works, and reconstructs whatever grid snapshot was sent.
#
# We can't know in advance exactly which generation each snapshot will
# correspond to (grid_streamer.v grabs whatever's current whenever it's
# free, by design). So instead of predicting an exact answer, we check
# that every decoded snapshot exactly matches SOME generation the golden
# model actually produced during the run, and that snapshots arrive in
# non-decreasing generation order (repeats are fine -- Game of Life
# settles into still lifes and oscillators -- going backward is not).

import sys
import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.dirname(__file__))
from test_uart_tx import receive_uart_byte  # noqa: E402 - reuse the proven receiver

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                  "software_prototype", "parallelism_ladder"),
)
from golden_rule import step_golden  # noqa: E402

ROWS = 8
COLS = 8
NUM_BYTES = (ROWS * COLS) // 8
CLKS_PER_BIT = 4
SYNC_BYTE = 0xAA
NUM_CYCLES = 4000  # long enough to observe several full frames


def grid_to_bits(grid, rows, cols) -> int:
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= (1 << (r * cols + c))
    return bits


def glider_grid(rows, cols, cx=2, cy=2):
    """A glider placed near the corner. On a small torus it never settles;
    it just loops around forever, which is exactly the kind of ongoing
    change we want to actually exercise the frame-ordering check with
    (a random soup can easily settle into a static still life almost
    immediately, which technically passes but never really tests
    anything -- every frame would just report the same generation)."""
    grid = [[0] * cols for _ in range(rows)]
    for dx, dy in [(0, 0), (1, 0), (2, 0), (2, 1), (1, 2)]:
        grid[(cy + dy) % rows][(cx + dx) % cols] = 1
    return grid


async def frame_collector(dut, frames: list):
    """Runs forever in the background: finds the sync byte, reads the
    payload that follows it, and records the reconstructed grid value."""
    while True:
        sync = await receive_uart_byte(dut, CLKS_PER_BIT)
        if sync != SYNC_BYTE:
            continue  # not aligned yet, keep scanning

        value = 0
        for byte_i in range(NUM_BYTES):
            b = await receive_uart_byte(dut, CLKS_PER_BIT)
            value |= (b << (byte_i * 8))
        frames.append(value)


@cocotb.test()
async def grid_reported_correctly_over_uart(dut):
    clock = Clock(dut.clk, 2, unit="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.load.value = 0
    dut.seed.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    py_grid = glider_grid(ROWS, COLS, cx=2, cy=2)

    # grid_streamer starts snapshotting the instant reset releases, one
    # cycle before the seed value actually lands in ca_grid (both update
    # on the same clock edge using non-blocking assignments, so the
    # streamer's very first latch reads the grid's PRE-seed value: all
    # zeros). That means the real, honest first frame off the wire is
    # legitimately all-zero. This is a real hardware sequencing detail,
    # not a test artifact, so it's accounted for here rather than hidden.
    golden_log = [0]

    dut.load.value = 1
    dut.seed.value = grid_to_bits(py_grid, ROWS, COLS)
    await RisingEdge(dut.clk)
    dut.load.value = 0

    golden_log.append(grid_to_bits(py_grid, ROWS, COLS))

    frames = []
    cocotb.start_soon(frame_collector(dut, frames))

    for _ in range(NUM_CYCLES):
        await RisingEdge(dut.clk)
        py_grid = step_golden(py_grid, ROWS)
        golden_log.append(grid_to_bits(py_grid, ROWS, COLS))

    # let the collector finish any byte it's mid-way through
    for _ in range(NUM_BYTES * 10 * CLKS_PER_BIT):
        await RisingEdge(dut.clk)

    assert len(frames) >= 3, (
        f"expected several complete frames over {NUM_CYCLES} cycles, only got {len(frames)}"
    )

    # A glider on a small torus is periodic: it eventually repeats its
    # entire trajectory exactly, so the same 64-bit pattern legitimately
    # recurs many generations apart. That means "first occurrence in the
    # log" is not a safe proxy for "when this frame was actually sent" --
    # a later frame can validly match an EARLIER occurrence's index than
    # a previous frame did, simply because the pattern looped around.
    #
    # What we actually want to know is simpler: does there exist SOME
    # consistent, non-decreasing assignment of generation numbers to the
    # frames we observed? If yes, the data is genuine and in order. If
    # no valid assignment exists at all, something really is wrong.
    import bisect
    from collections import defaultdict

    occurrences = defaultdict(list)
    for gen_index, value in enumerate(golden_log):
        occurrences[value].append(gen_index)  # already ascending

    seen_generations = []
    last_chosen = -1
    for i, frame_value in enumerate(frames):
        assert frame_value in occurrences, (
            f"frame {i} (0x{frame_value:016x}) does not match any generation "
            f"the golden model actually produced during this run"
        )
        candidates = occurrences[frame_value]
        pos = bisect.bisect_left(candidates, last_chosen)
        assert pos < len(candidates), (
            f"frame {i} (0x{frame_value:016x}) only occurred at generations "
            f"{candidates}, none of which come at or after generation "
            f"{last_chosen} (the previous frame's position): streaming went backward"
        )
        last_chosen = candidates[pos]
        seen_generations.append(last_chosen)

    dut._log.info(
        f"Captured {len(frames)} real frames over UART. "
        f"Generation indices reported, in order: {seen_generations}"
    )
