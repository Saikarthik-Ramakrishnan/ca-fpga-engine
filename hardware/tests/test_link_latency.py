# test_link_latency.py
#
# The other half of the FPGA's latency: getting bits on and off the chip.
# Measured cycle-accurately at the real build parameters (16x16, 115200
# baud from 27 MHz, so CLKS_PER_BIT = 234), through the real pins only,
# with the project's proven bit codecs.
#
#   frame period    clocks between two consecutive frames completing
#   seed to frame   clocks from the seed's last stop bit to the end of the
#                   first frame carrying the seeded pattern
#
# GEN_DIV stays at the deployed 2,700,000 (10 generations per second), far
# longer than this simulation runs, so the grid does not step while it is
# being measured: the numbers are the link and nothing else.
#
# The seed can land anywhere inside a frame, so seed-to-frame is not one
# number: the frame already on the wire carries the old grid, and the next
# one latches the new grid. That puts it between one and two frame periods,
# less about one bit time, measured from the end of the seed's stop bit:
#   - uart_rx samples mid-bit, so the chip has the last seed byte half a
#     bit before its stop bit ends on the wire;
#   - this test's frame timestamp is the receiver's mid-stop-bit sample,
#     half a bit before the transmitter's frame boundary.
# The first version of this test asserted a window of exactly one to two
# periods and failed at period - 21 clocks. The measurement was right and
# the bound was not; the window below includes the one-bit offset and says
# why. The measured value is one point in it; the report gives both.

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
CLKS_PER_BIT = 234    # 27 MHz / 115200, the real build
PERIOD_NS = 2         # simulation clock period; results are reported in clocks
F_CLK = 27_000_000


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
async def link_latency_at_115200(dut):
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
    for b in packet:  # back to back, the way a PC's UART sends them
        await send_uart_byte(dut, b, CLKS_PER_BIT)
    t_seed_done = now_clocks()

    seed_bits = grid_to_bits(soup, ROWS, COLS)
    frame_clocks_estimate = (nbytes + 1) * 10 * CLKS_PER_BIT
    for _ in range(4 * frame_clocks_estimate // 1000):
        await Timer(1000 * PERIOD_NS, unit="ns")
        hits = [i for i, (_, v) in enumerate(frames) if v == seed_bits]
        if hits and len(frames) > hits[0] + 1:
            break
    else:
        raise AssertionError("the seeded pattern never came back on tx_serial")

    first = hits[0]
    t_first_seeded = frames[first][0]
    periods = [frames[i + 1][0] - frames[i][0] for i in range(len(frames) - 1)]
    assert len(set(periods)) == 1, f"frame period is not constant: {periods}"
    period = periods[0]
    seed_to_frame = t_first_seeded - t_seed_done
    bit = 10 * CLKS_PER_BIT // 10          # one bit time, in clocks
    lo, hi = period - bit, 2 * period      # see the note at the top
    assert lo <= seed_to_frame <= hi, (
        f"seed-to-frame {seed_to_frame} outside [{lo}, {hi}] (frame period {period})")

    ms = lambda clocks: 1e3 * clocks / F_CLK  # noqa: E731
    dut._log.info(f"seed transfer: {t_seed_done - t_seed_start} clocks = {ms(t_seed_done - t_seed_start):.3f} ms")
    dut._log.info(f"frame period:  {period} clocks = {ms(period):.3f} ms ({F_CLK / period:.1f} frames/s)")
    dut._log.info(f"seed to frame: {seed_to_frame} clocks = {ms(seed_to_frame):.3f} ms "
                  f"(window {lo} to {hi} clocks = {ms(lo):.3f} to {ms(hi):.3f} ms)")

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "link_latency_16x16.json"), "w") as fh:
        json.dump({
            "rows": ROWS, "cols": COLS, "clks_per_bit": CLKS_PER_BIT, "baud": 115200,
            "f_clk_hz": F_CLK, "payload_bytes": nbytes,
            "seed_transfer_clocks": t_seed_done - t_seed_start,
            "frame_period_clocks": period,
            "frames_observed": len(frames),
            "seed_to_frame_clocks_measured": seed_to_frame,
            "seed_to_frame_clocks_min": lo,
            "seed_to_frame_clocks_max": hi,
            "method": "cycle-accurate RTL simulation (Icarus), cellnet_top, real pins only",
        }, fh, indent=2)
