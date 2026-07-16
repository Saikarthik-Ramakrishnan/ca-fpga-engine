# test_seed_loader.py
#
# Verifies seed_loader.v at the byte level, below UART timing entirely:
# rx_dv/rx_byte are driven directly, as if a perfect receiver existed.
# (uart_rx's own test already proves the receiver; the loopback test
# proves the two glued together. This test isolates the protocol logic.)
#
# What must hold:
#   1. CMD 0x55 + NUM_BYTES payload -> exactly one load pulse, with the
#      payload assembled in grid_streamer's byte order (byte 0 = bits
#      [7:0]).
#   2. Junk bytes while waiting for a command are ignored completely.
#   3. A transfer that stalls mid-payload times out, loads nothing, and
#      the very next clean transfer works. This is the cable-pulled case.
#   4. Two seeds back-to-back both land, each with its own payload.

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

NUM_BYTES = 8
TIMEOUT_CLKS = 64   # tiny in sim; ~100 ms worth of clocks on hardware
CMD_SEED = 0x55


async def push_byte(dut, value: int, gap: int = 3):
    """Present one byte the way uart_rx would: rx_byte valid with a
    1-cycle rx_dv pulse, then a few idle cycles (a real UART byte has
    10 bit-times of spacing; the FSM must not care about the exact gap)."""
    dut.rx_byte.value = value
    dut.rx_dv.value = 1
    await RisingEdge(dut.clk)
    dut.rx_dv.value = 0
    for _ in range(gap):
        await RisingEdge(dut.clk)


async def expect_load(dut, within: int):
    """Watch for a load pulse within `within` clocks. Returns the seed
    value captured on the load cycle, or None."""
    for _ in range(within):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.load.value) == 1:
            return int(dut.seed.value)
    return None


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    dut.rx_dv.value = 0
    dut.rx_byte.value = 0
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)


def payload_to_int(payload):
    """Byte 0 lands in bits [7:0], byte 1 in [15:8], and so on: the same
    slicing grid_streamer uses on the way out."""
    value = 0
    for i, b in enumerate(payload):
        value |= b << (8 * i)
    return value


@cocotb.test()
async def loads_seed_in_streamer_byte_order(dut):
    await reset(dut)

    payload = [0x01, 0x80, 0xAA, 0x55, 0x00, 0xFF, 0x3C, 0xC3]
    watcher = cocotb.start_soon(expect_load(dut, 200))

    await push_byte(dut, CMD_SEED)
    for b in payload:
        await push_byte(dut, b)

    seed = await watcher
    assert seed is not None, "full transfer produced no load pulse"
    assert seed == payload_to_int(payload), (
        f"seed assembled wrong: got 0x{seed:016X}, "
        f"expected 0x{payload_to_int(payload):016X}"
    )


@cocotb.test()
async def ignores_noise_before_command(dut):
    await reset(dut)

    watcher = cocotb.start_soon(expect_load(dut, 300))

    # garbage first, including 0xAA (the OUTGOING sync byte, which must
    # not be mistaken for a command) and payload-looking values.
    for junk in [0xAA, 0x00, 0xFF, 0x54, 0x56]:
        await push_byte(dut, junk)

    # then a clean transfer.
    payload = [i * 17 & 0xFF for i in range(NUM_BYTES)]
    await push_byte(dut, CMD_SEED)
    for b in payload:
        await push_byte(dut, b)

    seed = await watcher
    assert seed == payload_to_int(payload), (
        "noise before the command corrupted the transfer"
    )


@cocotb.test()
async def stalled_transfer_times_out_and_recovers(dut):
    await reset(dut)

    # start a transfer, send half the payload, then go silent.
    await push_byte(dut, CMD_SEED)
    for b in [0xDE, 0xAD, 0xBE, 0xEF]:
        await push_byte(dut, b)

    # silence long past the timeout. No load may fire during it.
    leaked = await expect_load(dut, TIMEOUT_CLKS * 3)
    assert leaked is None, (
        f"half a payload produced a load with seed 0x{leaked:016X}"
    )
    await RisingEdge(dut.clk)  # step out of the read-only phase

    # loader must now be back at WAIT_CMD: a fresh transfer works, and
    # none of the abandoned bytes contaminate it.
    payload = [random.Random(7).randrange(256) for _ in range(NUM_BYTES)]
    watcher = cocotb.start_soon(expect_load(dut, 200))
    await push_byte(dut, CMD_SEED)
    for b in payload:
        await push_byte(dut, b)

    seed = await watcher
    assert seed == payload_to_int(payload), (
        "loader did not recover cleanly after a timed-out transfer"
    )


@cocotb.test()
async def two_seeds_back_to_back_both_land(dut):
    await reset(dut)

    first = [0xFF] * NUM_BYTES
    second = [0x0F] * NUM_BYTES

    watcher = cocotb.start_soon(expect_load(dut, 200))
    await push_byte(dut, CMD_SEED)
    for b in first:
        await push_byte(dut, b)
    seed1 = await watcher
    await RisingEdge(dut.clk)

    watcher = cocotb.start_soon(expect_load(dut, 200))
    await push_byte(dut, CMD_SEED)
    for b in second:
        await push_byte(dut, b)
    seed2 = await watcher

    assert seed1 == payload_to_int(first)
    assert seed2 == payload_to_int(second)
