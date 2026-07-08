# test_uart_tx.py
#
# Verifies uart_tx.v by actually decoding its serial output, the same way
# a real PC's UART receiver would: watch the wire, catch the falling edge
# that means "start bit", then sample the middle of each subsequent bit
# period.
#
# `receive_uart_byte` here is the one piece of code this whole Phase 4
# effort leans on: it gets reused, unchanged, in test_cellnet_top.py to
# decode whole grid snapshots. Getting it right against a simple,
# byte-at-a-time test here means we trust it later against more complex
# data.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer, FallingEdge

CLKS_PER_BIT = 4  # tiny on purpose, just to keep simulation time short


async def receive_uart_byte(dut, clks_per_bit: int) -> int:
    """Wait for a start bit on dut.tx_serial, then sample 8 data bits and
    the stop bit, exactly the way a real UART receiver does it: wait for
    the line to fall, then sample once per bit period from there."""
    await FallingEdge(dut.tx_serial)  # start bit begins

    # sample in the middle of the start bit just to confirm it's really 0
    for _ in range(clks_per_bit // 2):
        await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.tx_serial.value) == 0, "expected start bit to read 0 mid-bit"

    value = 0
    for bit_index in range(8):
        for _ in range(clks_per_bit):
            await RisingEdge(dut.clk)
        await ReadOnly()
        bit = int(dut.tx_serial.value)
        value |= (bit << bit_index)  # LSB first

    for _ in range(clks_per_bit):
        await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.tx_serial.value) == 1, "expected stop bit to read 1"

    return value


@cocotb.test()
async def sends_known_bytes_correctly(dut):
    clock = Clock(dut.clk, 2, unit="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.tx_start.value = 0
    dut.tx_byte.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    test_bytes = [0x00, 0xFF, 0xAA, 0x55, 0x3C, 0x81, 0x01, 0x80]

    for expected_byte in test_bytes:
        assert int(dut.tx_busy.value) == 0, "should be idle before we start a send"

        dut.tx_byte.value = expected_byte
        dut.tx_start.value = 1
        await RisingEdge(dut.clk)
        dut.tx_start.value = 0

        received = await receive_uart_byte(dut, CLKS_PER_BIT)
        assert received == expected_byte, (
            f"sent 0x{expected_byte:02X}, decoded 0x{received:02X} off the wire"
        )

        # let tx_busy actually drop before starting the next byte
        while int(dut.tx_busy.value) == 1:
            await RisingEdge(dut.clk)
            await ReadOnly()
        await Timer(1, unit="ns")

    dut._log.info(f"All {len(test_bytes)} bytes sent and decoded correctly off the wire.")
