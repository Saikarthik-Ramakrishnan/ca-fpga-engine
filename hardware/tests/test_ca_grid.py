# test_ca_grid.py
#
# Verifies ca_grid.v (the real parallel fabric, N cells wired to their
# actual neighbors and updating simultaneously) against golden_rule.py's
# step_golden, which is the same "obviously correct, deliberately slow"
# reference every other tier in this project has been checked against.
#
# Unlike test_ca_cell.py, we can't test this exhaustively -- an 8x8 grid
# has 2^64 possible states, not 512. So instead we run several different
# random seeds forward for many generations each, checking the ENTIRE grid
# after every single generation (not just the final one), so a divergence
# gets caught at the exact generation it first appears rather than buried
# in a final mismatched grid with no idea which step went wrong.

import sys
import os
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                  "software_prototype", "parallelism_ladder"),
)
from golden_rule import step_golden  # noqa: E402

ROWS = 8
COLS = 8
GENERATIONS = 15


def grid_to_bits(grid: list[list[int]], rows: int, cols: int) -> int:
    """Pack a golden_rule-style [row][col] grid into the same flattened
    bit layout ca_grid.v uses: bit index = r*cols + c."""
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= (1 << (r * cols + c))
    return bits


def bits_to_grid(bits: int, rows: int, cols: int) -> list[list[int]]:
    return [[(bits >> (r * cols + c)) & 1 for c in range(cols)] for r in range(rows)]


def random_grid(rows: int, cols: int, density: float, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[1 if rng.random() < density else 0 for _ in range(cols)] for _ in range(rows)]


async def seed_and_settle(dut, bits: int):
    """Load `bits` into the grid via the load path, one clock edge, then
    release load so the rule takes over from the next edge on."""
    dut.load.value = 1
    dut.seed.value = bits
    await RisingEdge(dut.clk)
    dut.load.value = 0
    await ReadOnly()


async def run_one_seed(dut, seed_value: int, density: float):
    py_grid = random_grid(ROWS, COLS, density, seed_value)
    await seed_and_settle(dut, grid_to_bits(py_grid, ROWS, COLS))

    for gen in range(1, GENERATIONS + 1):
        py_grid = step_golden(py_grid, max(ROWS, COLS)) if ROWS == COLS else None
        # step_golden assumes a square N x N grid (matches every other use
        # in this project); ca_grid.v supports rectangular grids too, but
        # we only cross-check against golden_rule on the square case here.
        assert ROWS == COLS, "golden_rule.step_golden expects a square grid"

        await RisingEdge(dut.clk)
        await ReadOnly()

        hw_bits = int(dut.grid_out.value)
        hw_grid = bits_to_grid(hw_bits, ROWS, COLS)

        if hw_grid != py_grid:
            diff_cells = [
                (r, c) for r in range(ROWS) for c in range(COLS)
                if hw_grid[r][c] != py_grid[r][c]
            ]
            raise AssertionError(
                f"seed={seed_value} generation={gen}: grid mismatch at "
                f"{len(diff_cells)} cells. First few: {diff_cells[:10]}"
            )

        await Timer(1, unit="ns")

    dut._log.info(f"seed={seed_value}: {GENERATIONS} generations matched golden_rule.py exactly.")


@cocotb.test()
async def grid_matches_golden_model(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.load.value = 0
    dut.seed.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # several different random starting patterns, several densities --
    # not just one lucky seed. A sparse grid dies out fast (tests the
    # "mostly dead, occasional birth" path); a dense one stresses many
    # simultaneous births/deaths every generation.
    trials = [
        (1, 0.10),
        (2, 0.28),
        (3, 0.45),
        (4, 0.65),
    ]

    for seed_value, density in trials:
        await run_one_seed(dut, seed_value, density)
        # reset between trials so each starts from a clean, known state
        dut.rst_n.value = 0
        await RisingEdge(dut.clk)
        dut.rst_n.value = 1
        await RisingEdge(dut.clk)

    dut._log.info(f"All {len(trials)} trials x {GENERATIONS} generations matched. "
                  f"ca_grid.v is correct for {ROWS}x{COLS}.")
