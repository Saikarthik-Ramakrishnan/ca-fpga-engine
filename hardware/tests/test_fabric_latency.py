# test_fabric_latency.py
#
# The fabric's generation latency, measured in clock cycles through the
# real top level, cycle-accurately. software_prototype/cpp/tools/
# compare_fpga.py turns the cycle count into time at the 27 MHz dock clock
# for the laptop-vs-FPGA comparison.
#
# Setup: cellnet_top with GEN_DIV=1, so the pacer never holds the grid and
# the rule runs on every clock. A soup is seeded over rx_serial with the
# project's one wire encoder (hardware/host/protocol.py) and the proven bit
# codec. From the clock the seed lands, the design is advanced one clock at
# a time and the number of clocks until grid_state equals golden_rule.py's
# next generation is counted, for 64 generations in a row.
#
# What passing means: every one of those counts is 1. One generation per
# clock, no stall, no skip, zero jitter across the window. That number is
# measured here, not assumed.
#
# White-box on purpose: frames on tx_serial skip generations by design, so
# per-clock state is visible only inside. test_cellnet_loopback.py and
# test_cellnet_rules.py cover the pins-only view.
#
# Grid size comes from the Makefile (CELLNET_ROWS, CELLNET_COLS) so the same
# test measures both FPGA builds: make -f Makefile.fabric_latency ROWS=32 COLS=32

import json
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_uart_rx import send_uart_byte  # noqa: E402  proven wire encoder

sys.path.insert(0, os.path.join(HERE, "..", "host"))
from protocol import encode_seed, grid_to_bits  # noqa: E402  the one wire encoding

sys.path.insert(0, os.path.join(HERE, "..", "..", "software_prototype", "parallelism_ladder"))
from golden_rule import rule_masks, seed_grid, step_golden_masked  # noqa: E402

ROWS = int(os.environ.get("CELLNET_ROWS", "16"))
COLS = int(os.environ.get("CELLNET_COLS", "16"))
CLKS_PER_BIT = 4      # must match Makefile.fabric_latency; only the seed's speed
WINDOW = 64           # consecutive generations measured
MAX_WAIT = 8          # clocks to wait for a generation before calling it missing


@cocotb.test()
async def one_generation_per_clock(dut):
    assert ROWS == COLS, "golden_rule.py is square-only"
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    dut.rx_serial.value = 1
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)

    birth, survive = rule_masks("conway")  # rule_loader's reset default
    soup = seed_grid(ROWS, density=0.35, seed=7)
    for b in encode_seed(soup, ROWS, COLS):
        await send_uart_byte(dut, b, CLKS_PER_BIT)

    # the clock the seed lands: before it the grid is empty, so no false match
    seed_bits = grid_to_bits(soup, ROWS, COLS)
    for _ in range(64 * CLKS_PER_BIT):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.grid_state.value) == seed_bits:
            break
    else:
        raise AssertionError("the seed never appeared on grid_state")

    cycles = []
    grid = soup
    for k in range(1, WINDOW + 1):
        grid = step_golden_masked(grid, ROWS, birth, survive)
        want = grid_to_bits(grid, ROWS, COLS)
        for waited in range(1, MAX_WAIT + 1):
            await Timer(1, unit="ns")  # step out of ReadOnly
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(dut.grid_state.value) == want:
                break
        else:
            raise AssertionError(f"generation {k} did not appear within {MAX_WAIT} clocks")
        cycles.append(waited)

    assert all(c == 1 for c in cycles), f"clocks per generation: {cycles}"
    dut._log.info(f"{ROWS}x{COLS}: {WINDOW} consecutive generations, clocks per generation "
                  f"min {min(cycles)} max {max(cycles)}: one generation per clock, zero jitter")

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"fabric_latency_{ROWS}x{COLS}.json"), "w") as fh:
        json.dump({
            "rows": ROWS, "cols": COLS, "gen_div": 1, "rule": "conway B3/S23",
            "generations_measured": WINDOW,
            "clocks_per_generation_min": min(cycles),
            "clocks_per_generation_max": max(cycles),
            "method": "cycle-accurate RTL simulation (Icarus), cellnet_top, grid_state "
                      "compared with golden_rule.py every clock",
        }, fh, indent=2)
