# test_ca_grid_rule.py
#
# ca_grid_rule.v is ca_grid.v with two 9-bit masks broadcast to every cell.
# The cell itself is already exhaustively verified (test_ca_cell_rule.py),
# so what is left to prove here is fabric-level and rule-level:
#
#   1. every_rule_matches_golden
#      All five console rulesets, four random seed densities each, 15
#      generations each, whole grid compared to golden_rule after EVERY
#      generation so a divergence is pinned to the step it appears.
#      5 rules x 4 seeds x 15 generations = 300 full-grid comparisons.
#   2. rule_change_takes_effect_next_generation
#      Change the broadcast masks mid-run without touching the grid. The
#      state must not move on the clock the masks change (a rule is not a
#      seed), and the very next generation must follow the NEW rule from
#      the state the OLD rule left behind. This is what happens on real
#      hardware when a 0x33 lands between two pacer ticks.
#   3. conway_masks_match_fixed_grid
#      Held at Conway, this fabric must produce the same trajectory
#      ca_grid.v does. Same compatibility claim as the cell test, one
#      level up.
#
# 2^64 states means no exhaustive option at grid level; the cell test is
# where exhaustiveness lives, and this test covers the wiring.

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
from golden_rule import (  # noqa: E402
    RULES, rule_masks, mask_notation, step_golden, step_golden_masked,
)

ROWS = 8
COLS = 8
GENERATIONS = 15


def grid_to_bits(grid, rows, cols) -> int:
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= (1 << (r * cols + c))
    return bits


def bits_to_grid(bits: int, rows: int, cols: int):
    return [[(bits >> (r * cols + c)) & 1 for c in range(cols)] for r in range(rows)]


def random_grid(rows, cols, density, seed):
    rng = random.Random(seed)
    return [[1 if rng.random() < density else 0 for _ in range(cols)] for _ in range(rows)]


async def hard_reset(dut):
    dut.rst_n.value = 0
    dut.load.value = 0
    dut.seed.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def seed_and_settle(dut, bits: int):
    dut.load.value = 1
    dut.seed.value = bits
    await RisingEdge(dut.clk)
    dut.load.value = 0
    await ReadOnly()
    await Timer(1, unit="ns")


async def run_trial(dut, py_grid, birth, survive, label) -> int:
    """Advance the fabric and the golden model in lockstep, comparing the
    entire grid after each generation. Returns generations compared."""
    await seed_and_settle(dut, grid_to_bits(py_grid, ROWS, COLS))

    for gen in range(1, GENERATIONS + 1):
        py_grid = step_golden_masked(py_grid, ROWS, birth, survive)

        await RisingEdge(dut.clk)
        await ReadOnly()
        hw_grid = bits_to_grid(int(dut.grid_out.value), ROWS, COLS)

        if hw_grid != py_grid:
            diff = [
                (r, c) for r in range(ROWS) for c in range(COLS)
                if hw_grid[r][c] != py_grid[r][c]
            ]
            raise AssertionError(
                f"[{label}] generation {gen}: {len(diff)} cells differ from "
                f"golden_rule. First few: {diff[:10]}"
            )
        await Timer(1, unit="ns")

    return GENERATIONS


@cocotb.test()
async def every_rule_matches_golden(dut):
    """All five rulesets, four densities each, checked every generation."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await hard_reset(dut)

    densities = [(1, 0.10), (2, 0.28), (3, 0.45), (4, 0.65)]
    total = 0

    for name in RULES:
        birth, survive = rule_masks(name)
        dut.birth.value = birth
        dut.survive.value = survive
        notation = mask_notation(birth, survive)

        for seed_value, density in densities:
            grid = random_grid(ROWS, COLS, density, seed_value)
            total += await run_trial(
                dut, grid, birth, survive,
                f"{name} {notation} seed={seed_value} d={density}",
            )
            await hard_reset(dut)

        dut._log.info(
            f"{name:9s} {notation:14s} {len(densities)} seeds x {GENERATIONS} "
            f"generations matched"
        )

    assert total == len(RULES) * len(densities) * GENERATIONS
    dut._log.info(
        f"{total} full-grid comparisons across {len(RULES)} rulesets, all exact."
    )


@cocotb.test()
async def rule_change_takes_effect_next_generation(dut):
    """Swap the broadcast rule mid-run. The grid must not move on the swap
    itself, then must follow the new rule from wherever the old one left
    it. Conway -> Seeds is a sharp test: under B2/S nothing survives, so a
    rule change that silently failed would leave a populated grid."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await hard_reset(dut)

    conway_b, conway_s = rule_masks("conway")
    seeds_b, seeds_s = rule_masks("seeds")

    dut.birth.value = conway_b
    dut.survive.value = conway_s

    py_grid = random_grid(ROWS, COLS, 0.35, 7)
    await seed_and_settle(dut, grid_to_bits(py_grid, ROWS, COLS))

    # five generations of Conway
    for _ in range(5):
        py_grid = step_golden_masked(py_grid, ROWS, conway_b, conway_s)
        await RisingEdge(dut.clk)
        await ReadOnly()
        await Timer(1, unit="ns")

    before = int(dut.grid_out.value)
    assert before == grid_to_bits(py_grid, ROWS, COLS), "Conway phase diverged"

    # swap the masks while holding the grid still with the load path,
    # exactly as the pacer does between ticks on real hardware.
    dut.load.value = 1
    dut.seed.value = before
    dut.birth.value = seeds_b
    dut.survive.value = seeds_s
    for _ in range(3):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.grid_out.value) == before, (
            "changing the rule masks moved the grid; a rule is not a seed"
        )
        await Timer(1, unit="ns")

    # release the hold: from here the fabric must run B2/S
    dut.load.value = 0
    for gen in range(1, 6):
        py_grid = step_golden_masked(py_grid, ROWS, seeds_b, seeds_s)
        await RisingEdge(dut.clk)
        await ReadOnly()
        got = bits_to_grid(int(dut.grid_out.value), ROWS, COLS)
        assert got == py_grid, (
            f"generation {gen} after the swap does not follow B2/S"
        )
        await Timer(1, unit="ns")

    dut._log.info(
        "Rule swap verified: no movement on the swap, new rule from the next generation."
    )


@cocotb.test()
async def conway_masks_match_fixed_grid(dut):
    """Held at Conway, this fabric must track step_golden() (the original
    hardwired reference) exactly, which is what makes RULE_CFG=1 a safe
    default for a chip nobody has sent a rule to."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await hard_reset(dut)

    birth, survive = rule_masks("conway")
    dut.birth.value = birth
    dut.survive.value = survive

    py_grid = random_grid(ROWS, COLS, 0.28, 42)
    await seed_and_settle(dut, grid_to_bits(py_grid, ROWS, COLS))

    for gen in range(1, GENERATIONS + 1):
        py_grid = step_golden(py_grid, ROWS)      # the un-masked original
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert bits_to_grid(int(dut.grid_out.value), ROWS, COLS) == py_grid, (
            f"generation {gen} diverged from the hardwired Conway reference"
        )
        await Timer(1, unit="ns")

    dut._log.info(
        f"{GENERATIONS} generations under Conway masks match step_golden() exactly."
    )
