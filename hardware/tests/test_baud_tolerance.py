# test_baud_tolerance.py
#
# How far apart can the two ends of the wire drift before the link
# breaks?
#
# test_link_speed.py sweeps the divider and every rate passes, down to
# nine million baud. That result is real but it is not the whole story:
# the testbench generates each bit at exactly the rate the receiver
# expects, so the sampling margin is never under any pressure. A real
# link never has that. The PC's bridge derives its baud from its own
# crystal and its own integer divider, and whatever error that leaves
# accumulates across the ten bits of a byte.
#
# So this test does the thing the sweep cannot: it drives the receiver
# with a bit period that deliberately differs from the one the receiver
# was built for, and finds the widest mismatch that still decodes. The
# sender is the project's proven encoder, called with a different
# clks_per_bit than the DUT's parameter, so the mismatch comes from the
# numbers rather than from a second, unproven codec.
#
# What sets the limit:
#
#   - A receiver that samples the middle of every bit and re-aligns only
#     on the start bit has a classic ceiling. The last thing it samples
#     is the stop bit, 9.5 bit times after it aligned, so a mismatch of
#     e per bit has grown to 9.5e by then and has to stay inside the
#     half bit of margin it started with. That puts the ceiling at
#     1 / 19, or 5.26%, shared between the two ends of the wire.
#   - Two effects eat into that: the receiver waits an integer number of
#     clocks, (CLKS_PER_BIT - 1) / 2, which is not exactly half a bit,
#     and the two-flop synchronizer shifts the whole picture by a fixed
#     couple of clocks. Both are constants in clocks, so both matter
#     more the fewer clocks a bit lasts.
#
# The sender's rate here is an integer number of clocks per bit, so the
# finest mismatch this test can apply is one clock, which is 0.4% at
# the deployed divider and 8% at a divider of 12. Below roughly 18 the
# window is narrower than one step and the sweep can only bound it,
# which the report says rather than printing a zero.
#
# The window is measured per divider rather than assumed.

import json
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_uart_rx import send_uart_byte, watch_for_byte  # noqa: E402

DUT_CPB = int(os.environ.get("DUT_CPB", "234"))
SPAN = int(os.environ.get("SPAN", "30"))
F_CLK = 27_000_000

# Patterns that put the transitions in different places: all low, all
# high, both alternations, and a single bit at each end of the byte.
PATTERNS = [0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80, 0x7F, 0xFE]


async def pulse_reset(dut):
    """Reset between trials. test_uart_rx.reset starts a clock of its own,
    which is right for a test that calls it once and wrong here: this
    test resets dozens of times against one clock."""
    dut.rx_serial.value = 1          # the wire idles high
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)


async def decodes_at(dut, host_cpb: int) -> bool:
    """Drive PATTERNS onto the wire at host_cpb clocks per bit and report
    whether the receiver published every one of them correctly."""
    await pulse_reset(dut)
    for value in PATTERNS:
        watcher = cocotb.start_soon(watch_for_byte(dut, host_cpb * 14 + 64))
        await send_uart_byte(dut, value, host_cpb)
        received = await watcher
        # watch_for_byte returns inside a read-only phase, so step an
        # edge before anything drives the wire again.
        await RisingEdge(dut.clk)
        if received != value:
            return False
    return True


@cocotb.test()
async def finds_the_mismatch_window(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())

    results = {}
    for host_cpb in range(max(2, DUT_CPB - SPAN), DUT_CPB + SPAN + 1):
        results[host_cpb] = await decodes_at(dut, host_cpb)

    assert results[DUT_CPB], (
        f"the receiver failed at its own rate (CLKS_PER_BIT={DUT_CPB}), "
        f"which is a regression rather than a tolerance limit")

    # widest run of passing dividers that contains the matched one
    low = DUT_CPB
    while low - 1 in results and results[low - 1]:
        low -= 1
    high = DUT_CPB
    while high + 1 in results and results[high + 1]:
        high += 1

    # A sender at host_cpb clocks per bit runs at a baud of
    # F_CLK / host_cpb, so the error it represents relative to the
    # receiver is DUT_CPB / host_cpb - 1. A slower sender (larger
    # host_cpb) is a negative error.
    err_slow = 100.0 * (DUT_CPB / high - 1.0)
    err_fast = 100.0 * (DUT_CPB / low - 1.0)
    edge_low = low - 1 if (low - 1) in results else None
    edge_high = high + 1 if (high + 1) in results else None

    # One clock per bit is the smallest step an integer sender can take.
    # When the window is a single divider wide, the tolerance is smaller
    # than that step and all this sweep can say is an upper bound.
    resolution = 100.0 / DUT_CPB
    fast_bounded = (low == DUT_CPB)    # not even one clock faster decodes
    slow_bounded = (high == DUT_CPB)   # not even one clock slower decodes
    bounded_only = fast_bounded and slow_bounded

    fast_text = (f"under {resolution:.2f}%" if fast_bounded
                 else f"{err_fast:.2f}%")
    slow_text = (f"under {resolution:.2f}%" if slow_bounded
                 else f"{abs(err_slow):.2f}%")

    dut._log.info(f"receiver built for CLKS_PER_BIT {DUT_CPB} "
                  f"({F_CLK / DUT_CPB:,.0f} baud)")
    dut._log.info(f"decodes from {low} to {high} clocks per bit "
                  f"(steps of {resolution:.2f}%)")
    dut._log.info(f"sender may run {fast_text} fast or {slow_text} slow")
    if edge_low is None or edge_high is None:
        dut._log.warning(
            f"the window reached the edge of the swept range; raise SPAN "
            f"above {SPAN} to close it")

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"baud_tolerance_cpb{DUT_CPB}.json")
    with open(path, "w") as fh:
        json.dump({
            "dut_clks_per_bit": DUT_CPB,
            "dut_baud": F_CLK / DUT_CPB,
            "f_clk_hz": F_CLK,
            "swept_span": SPAN,
            "window_low_clks_per_bit": low,
            "window_high_clks_per_bit": high,
            "tolerance_pct_sender_fast": err_fast,
            "tolerance_pct_sender_slow": err_slow,
            "resolution_pct": resolution,
            "fast_bounded_only": fast_bounded,
            "slow_bounded_only": slow_bounded,
            "bounded_only": bounded_only,
            "window_closed_inside_sweep": edge_low is not None and edge_high is not None,
            "per_divider": {str(k): v for k, v in sorted(results.items())},
            "patterns": [f"0x{p:02X}" for p in PATTERNS],
            "method": "cycle-accurate RTL simulation (Icarus), uart_rx driven "
                      "by the project encoder at a deliberately mismatched rate",
        }, fh, indent=2)
