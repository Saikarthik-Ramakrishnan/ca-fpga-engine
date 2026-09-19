# test_link_speed.py
#
# How fast can the link actually run?
#
# The latency measurement in test_link_latency.py found that the fabric
# computes a generation in 37 ns while the UART needs 2.86 ms to report
# one, so end-to-end timing is set by the link and by nothing else. The
# obvious lever is the baud rate, which on this chip is one parameter:
# CLKS_PER_BIT, the number of 27 MHz clocks the transmitter holds each
# bit. This test runs the whole chip at a given CLKS_PER_BIT, seeds it
# through the real pins, and checks that the seeded pattern comes back
# bit for bit. A frame that decodes correctly is the evidence that the
# rate is usable; the frame period it reports is what that rate buys.
#
# One test binary covers one rate. CLKS_PER_BIT arrives from the
# Makefile in the environment and is also passed to the DUT, so both
# ends of the wire agree by construction. run_link_speed.sh sweeps it.
#
# GEN_DIV stays at the deployed 2,700,000, far longer than this
# simulation runs, so the grid never steps while it is being measured
# and every frame must carry exactly the pattern that was seeded.

import json
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

try:
    from cocotb.utils import get_sim_time
except ImportError:  # pragma: no cover
    from cocotb.simtime import get_sim_time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_uart_tx import receive_uart_byte  # noqa: E402  proven decoder
from test_uart_rx import send_uart_byte     # noqa: E402  proven encoder

sys.path.insert(0, os.path.join(HERE, "..", "host"))
from protocol import SYNC_BYTE, encode_seed, grid_to_bits, payload_bytes  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "..", "software_prototype", "parallelism_ladder"))
from golden_rule import seed_grid  # noqa: E402

ROWS = COLS = 16
PERIOD_NS = 2
F_CLK = 27_000_000

CLKS_PER_BIT = int(os.environ.get("CPB", "234"))


def now_clocks() -> int:
    return int(round(float(get_sim_time(unit="ns")) / PERIOD_NS))


async def frame_collector(dut, frames: list, nbytes: int):
    while True:
        if await receive_uart_byte(dut, CLKS_PER_BIT) != SYNC_BYTE:
            continue
        value = 0
        for i in range(nbytes):
            value |= (await receive_uart_byte(dut, CLKS_PER_BIT)) << (8 * i)
        frames.append((now_clocks(), value))


@cocotb.test()
async def link_round_trips_at_this_rate(dut):
    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    dut.rx_serial.value = 1
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)

    nbytes = payload_bytes(ROWS, COLS)
    frames = []
    cocotb.start_soon(frame_collector(dut, frames, nbytes))

    soup = seed_grid(ROWS, density=0.35, seed=11)
    packet = encode_seed(soup, ROWS, COLS)
    t_seed_start = now_clocks()
    for b in packet:
        await send_uart_byte(dut, b, CLKS_PER_BIT)
    t_seed_done = now_clocks()

    seed_bits = grid_to_bits(soup, ROWS, COLS)
    frame_clocks_estimate = (nbytes + 1) * 10 * CLKS_PER_BIT
    hits = []
    for _ in range(max(1, 4 * frame_clocks_estimate // 1000)):
        await Timer(1000 * PERIOD_NS, unit="ns")
        hits = [i for i, (_, v) in enumerate(frames) if v == seed_bits]
        if hits and len(frames) > hits[0] + 1:
            break
    else:
        raise AssertionError(
            f"CLKS_PER_BIT={CLKS_PER_BIT}: the seeded pattern never came back. "
            f"{len(frames)} frames decoded, none matching.")

    periods = [frames[i + 1][0] - frames[i][0] for i in range(len(frames) - 1)]
    assert len(set(periods)) == 1, f"frame period is not constant: {periods}"
    period = periods[0]

    # Every frame after the first seeded one must still carry the seed:
    # the pacer is holding the grid still, so any difference would be a
    # decode error rather than a generation.
    for _, value in frames[hits[0]:]:
        assert value == seed_bits, (
            f"CLKS_PER_BIT={CLKS_PER_BIT}: a later frame decoded differently, "
            f"so the rate is not reliable")

    baud = F_CLK / CLKS_PER_BIT
    seed_clocks = t_seed_done - t_seed_start
    ms = lambda clocks: 1e3 * clocks / F_CLK  # noqa: E731
    dut._log.info(f"CLKS_PER_BIT {CLKS_PER_BIT} = {baud:,.0f} baud")
    dut._log.info(f"seed transfer: {seed_clocks} clocks = {ms(seed_clocks):.3f} ms")
    dut._log.info(f"frame period:  {period} clocks = {ms(period):.3f} ms "
                  f"({F_CLK / period:.1f} frames/s)")
    dut._log.info(f"frames decoded: {len(frames)}, all matching the seed")

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"link_speed_cpb{CLKS_PER_BIT}.json")
    with open(path, "w") as fh:
        json.dump({
            "rows": ROWS, "cols": COLS,
            "clks_per_bit": CLKS_PER_BIT,
            "baud": baud,
            "f_clk_hz": F_CLK,
            "payload_bytes": nbytes,
            "seed_transfer_clocks": seed_clocks,
            "frame_period_clocks": period,
            "frames_per_second": F_CLK / period,
            "frames_observed": len(frames),
            "round_trip_exact": True,
            "method": "cycle-accurate RTL simulation (Icarus), cellnet_top, real pins only",
        }, fh, indent=2)
