# test_uart_rx.py
#
# Verifies uart_rx.v by playing the role of the PC's transmitter: wiggle
# rx_serial by hand at exact bit timing, then check what the receiver
# publishes on rx_dv / rx_byte.
#
# `send_uart_byte` here is the transmit twin of test_uart_tx.py's
# `receive_uart_byte`, and it gets reused the same way: the loopback test
# leans on it to push whole seed transfers into the full chip.
#
# Three behaviors matter, so three tests:
#   1. Every one of the 256 possible byte values decodes correctly,
#      sent back-to-back with no idle gap (the hardest timing case).
#   2. A glitch shorter than half a bit must NOT produce a byte. The
#      mid-start-bit confirmation exists exactly for this.
#   3. A byte with a broken stop bit (framing error) must be silently
#      dropped, and the receiver must still decode the next clean byte.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

CLKS_PER_BIT = 8  # small for sim speed; > 4 so "half a bit" is meaningful


async def send_uart_byte(dut, value: int, clks_per_bit: int,
                         break_stop_bit: bool = False):
    """Drive one 8N1 byte onto dut.rx_serial: start bit, 8 data bits LSB
    first, stop bit. Optionally hold the stop bit low to fake a framing
    error."""
    dut.rx_serial.value = 0                      # start bit
    for _ in range(clks_per_bit):
        await RisingEdge(dut.clk)

    for bit_index in range(8):                   # data, LSB first
        dut.rx_serial.value = (value >> bit_index) & 1
        for _ in range(clks_per_bit):
            await RisingEdge(dut.clk)

    dut.rx_serial.value = 0 if break_stop_bit else 1   # stop bit
    for _ in range(clks_per_bit):
        await RisingEdge(dut.clk)
    dut.rx_serial.value = 1                      # back to idle


async def watch_for_byte(dut, cycles: int):
    """Watch rx_dv for up to `cycles` clocks. Returns the byte if one is
    published, or None if rx_dv never pulses."""
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.rx_dv.value) == 1:
            return int(dut.rx_byte.value)
    return None


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    dut.rx_serial.value = 1   # wire idles high
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)


@cocotb.test()
async def decodes_all_256_values_back_to_back(dut):
    await reset(dut)

    for value in range(256):
        watcher = cocotb.start_soon(
            watch_for_byte(dut, CLKS_PER_BIT * 14))
        await send_uart_byte(dut, value, CLKS_PER_BIT)
        received = await watcher
        assert received == value, (
            f"sent 0x{value:02X}, receiver published "
            f"{'nothing' if received is None else f'0x{received:02X}'}"
        )


@cocotb.test()
async def rejects_sub_bit_glitch(dut):
    await reset(dut)

    # yank the line low for a quarter of a bit, then release: line noise,
    # not a start bit. The receiver must confirm mid-start and bail.
    dut.rx_serial.value = 0
    for _ in range(CLKS_PER_BIT // 4):
        await RisingEdge(dut.clk)
    dut.rx_serial.value = 1

    published = await watch_for_byte(dut, CLKS_PER_BIT * 14)
    assert published is None, (
        f"a {CLKS_PER_BIT // 4}-clock glitch produced byte "
        f"0x{published:02X}; it should have been rejected"
    )

    # watch_for_byte returns during a read-only phase; step one edge so
    # the wire can legally be driven again.
    await RisingEdge(dut.clk)

    # and the receiver must still be alive: a clean byte right after
    # the glitch decodes normally.
    watcher = cocotb.start_soon(watch_for_byte(dut, CLKS_PER_BIT * 14))
    await send_uart_byte(dut, 0x5A, CLKS_PER_BIT)
    assert await watcher == 0x5A


@cocotb.test()
async def drops_framing_error_and_recovers(dut):
    await reset(dut)

    # broken byte: stop bit held low. Must publish nothing.
    watcher = cocotb.start_soon(watch_for_byte(dut, CLKS_PER_BIT * 14))
    await send_uart_byte(dut, 0xC3, CLKS_PER_BIT, break_stop_bit=True)
    published = await watcher
    assert published is None, (
        f"framing-broken byte was published as 0x{published:02X}"
    )

    # give the line a moment of clean idle, then a good byte.
    for _ in range(CLKS_PER_BIT * 2):
        await RisingEdge(dut.clk)
    watcher = cocotb.start_soon(watch_for_byte(dut, CLKS_PER_BIT * 14))
    await send_uart_byte(dut, 0x3C, CLKS_PER_BIT)
    assert await watcher == 0x3C, "receiver did not recover after framing error"
