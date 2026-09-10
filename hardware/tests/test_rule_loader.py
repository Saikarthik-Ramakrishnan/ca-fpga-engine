# test_rule_loader.py
#
# rule_loader.v listens to the same rx_dv/rx_byte stream seed_loader does,
# so most of what matters here is not "does it decode 0x33", it is "can
# the two loaders corrupt each other". Six tests:
#
#   1. all_named_rules_decode
#      Each of the five console rulesets encoded to 3 bytes, sent, and
#      read back off birth/survive. Byte order is asserted explicitly,
#      not just round-tripped, so an encoder and decoder that are wrong
#      in the same direction cannot both pass.
#   2. reset_default_is_conway
#      Out of reset, before any byte, the masks must be B3/S23. A chip
#      nobody talks to has to behave like the fixed-rule build.
#   3. noise_before_command_ignored
#      0x00, 0xFF, 0xAA (the outgoing sync byte) and 0x55 (the SEED
#      command) must not start a rule transfer.
#   4. rule_bytes_are_gated_from_seed_loader
#      The guard that matters most. A rule payload containing 0x55 is
#      sent; `consuming` must be high on all three payload bytes so the
#      top level can gate them away, and seed_loader must never see them.
#      Driven against the real seed_loader, wired exactly as cellnet_top
#      wires it, rather than against an assumption about it.
#   5. rule_command_inside_seed_payload_ignored
#      The mirror guard. A grid seed whose payload contains 0x33 must
#      load as data; the rule must not change.
#   6. timeout_abandons_partial_rule
#      A transfer cut off after one byte must not corrupt the live rule,
#      and the loader must accept a clean rule afterwards.

import sys
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

sys.path.insert(0, os.path.dirname(__file__))
from test_uart_rx import send_uart_byte  # noqa: E402  proven wire encoder

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                 "software_prototype", "parallelism_ladder"),
)
from golden_rule import RULES, rule_masks, mask_notation  # noqa: E402

CMD_RULE = 0x33
CMD_SEED = 0x55
SYNC_BYTE = 0xAA
NUM_BYTES = 8          # 8x8 grid, matching the seed_loader parameter below
TIMEOUT_CLKS = 2000


def rule_to_bytes(birth: int, survive: int) -> list:
    """The wire encoding, written once here and mirrored in
    hardware/host/send_seed.py and the console. Byte 0 = birth[7:0],
    byte 1 = survive[7:0], byte 2 = {6'b0, survive[8], birth[8]}."""
    return [
        birth & 0xFF,
        survive & 0xFF,
        ((birth >> 8) & 1) | (((survive >> 8) & 1) << 1),
    ]


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    dut.rx_serial.value = 1
    dut.rst_n.value = 0
    for _ in range(6):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(6):
        await RisingEdge(dut.clk)


async def idle(dut, clks: int):
    for _ in range(clks):
        await RisingEdge(dut.clk)


async def send_bytes(dut, values, clks_per_bit=4, gap=8):
    for v in values:
        await send_uart_byte(dut, v, clks_per_bit)
        await idle(dut, gap)


async def watch_consuming(dut, values, clks_per_bit=4, gap=8):
    """Send bytes while sampling `consuming` on every clock a byte is
    published. Returns the list of (byte, consuming) observations."""
    seen = []

    async def sampler():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(dut.rx_dv.value) == 1:
                seen.append((int(dut.rx_byte.value), int(dut.consuming.value)))

    task = cocotb.start_soon(sampler())
    await send_bytes(dut, values, clks_per_bit, gap)
    await idle(dut, 40)
    task.cancel()
    return seen


@cocotb.test()
async def reset_default_is_conway(dut):
    """Before any byte arrives the fabric must already be running Life."""
    await start(dut)
    await ReadOnly()
    birth, survive = int(dut.birth.value), int(dut.survive.value)
    expected_b, expected_s = rule_masks("conway")
    assert (birth, survive) == (expected_b, expected_s), (
        f"reset rule is {mask_notation(birth, survive)}, expected B3/S23"
    )
    dut._log.info("Reset default is Conway B3/S23.")


@cocotb.test()
async def all_named_rules_decode(dut):
    """Every console ruleset survives the wire round trip, byte order
    asserted explicitly."""
    await start(dut)

    for name in RULES:
        birth, survive = rule_masks(name)
        payload = rule_to_bytes(birth, survive)

        assert payload[0] == birth & 0xFF
        assert payload[1] == survive & 0xFF
        assert payload[2] == ((birth >> 8) & 1) | (((survive >> 8) & 1) << 1)

        await send_bytes(dut, [CMD_RULE] + payload)
        await idle(dut, 20)
        await ReadOnly()
        got_b, got_s = int(dut.birth.value), int(dut.survive.value)
        assert (got_b, got_s) == (birth, survive), (
            f"{name}: sent {mask_notation(birth, survive)}, "
            f"loader holds {mask_notation(got_b, got_s)}"
        )
        await Timer(1, unit="ns")
        dut._log.info(f"{name:9s} {mask_notation(birth, survive):14s} decoded off the wire")

    dut._log.info(f"All {len(RULES)} rulesets decode correctly.")


@cocotb.test()
async def noise_before_command_ignored(dut):
    """Nothing but 0x33 may start a rule transfer, including the project's
    two other magic bytes."""
    await start(dut)

    # put a known non-Conway rule in place first so a spurious load shows up
    daynight_b, daynight_s = rule_masks("daynight")
    await send_bytes(dut, [CMD_RULE] + rule_to_bytes(daynight_b, daynight_s))
    await idle(dut, 20)

    for noise in (0x00, 0xFF, SYNC_BYTE, CMD_SEED, 0x32, 0x34):
        await send_bytes(dut, [noise])
    await idle(dut, 40)

    await ReadOnly()
    got_b, got_s = int(dut.birth.value), int(dut.survive.value)
    assert (got_b, got_s) == (daynight_b, daynight_s), (
        f"noise changed the rule to {mask_notation(got_b, got_s)}"
    )
    dut._log.info("0x00, 0xFF, 0xAA, 0x55, 0x32, 0x34 all correctly ignored.")


@cocotb.test()
async def rule_bytes_are_gated_from_seed_loader(dut):
    """A rule payload containing 0x55 must not reach seed_loader. Checked
    against the real seed_loader instance, wired the way cellnet_top wires
    it (rx_dv gated by `consuming`)."""
    await start(dut)

    # Maze is B3/S12345: birth[7:0] = 0x08, survive[7:0] = 0x3E. Force a
    # payload that literally contains the SEED command byte instead, by
    # picking masks whose low bytes are 0x55.
    birth, survive = 0x55, 0x55           # B0246/S0246, a legal rule
    payload = rule_to_bytes(birth, survive)
    assert CMD_SEED in payload, "this test needs a 0x55 in the rule payload"

    seen = await watch_consuming(dut, [CMD_RULE] + payload)

    assert len(seen) == 4, f"expected 4 bytes on the wire, saw {seen}"
    assert seen[0] == (CMD_RULE, 0), (
        f"consuming should be low on the command byte itself, got {seen[0]}"
    )
    for i, (value, consuming) in enumerate(seen[1:], start=1):
        assert consuming == 1, (
            f"payload byte {i} (0x{value:02X}) was not gated: consuming=0. "
            f"seed_loader would have seen it."
        )

    await ReadOnly()
    assert (int(dut.birth.value), int(dut.survive.value)) == (birth, survive)
    assert int(dut.seed_load.value) == 0, "seed_loader fired on rule payload"
    assert int(dut.seed_receiving.value) == 0, (
        "the 0x55 inside the rule payload started a seed transfer"
    )

    dut._log.info(
        "Rule payload containing 0x55 was fully gated; seed_loader never moved."
    )


@cocotb.test()
async def rule_command_inside_seed_payload_ignored(dut):
    """The mirror guard: 0x33 inside a grid seed is data, not a command."""
    await start(dut)

    maze_b, maze_s = rule_masks("maze")
    await send_bytes(dut, [CMD_RULE] + rule_to_bytes(maze_b, maze_s))
    await idle(dut, 20)

    # a full 8-byte grid seed, every byte 0x33
    payload = [CMD_RULE] * NUM_BYTES
    await send_bytes(dut, [CMD_SEED] + payload)
    await idle(dut, 60)

    await ReadOnly()
    got_b, got_s = int(dut.birth.value), int(dut.survive.value)
    assert (got_b, got_s) == (maze_b, maze_s), (
        f"0x33 inside a seed payload changed the rule to "
        f"{mask_notation(got_b, got_s)}"
    )
    expected_seed = int.from_bytes(bytes(payload), "little")
    assert int(dut.seed.value) == expected_seed, (
        f"seed loaded as 0x{int(dut.seed.value):016x}, expected "
        f"0x{expected_seed:016x}: rule_loader ate part of the payload"
    )
    dut._log.info(
        "0x33 x 8 loaded as grid data; the rule was untouched."
    )


@cocotb.test()
async def timeout_abandons_partial_rule(dut):
    """A transfer that dies after one byte must leave the live rule alone
    and must not swallow the next command."""
    await start(dut)

    highlife_b, highlife_s = rule_masks("highlife")
    await send_bytes(dut, [CMD_RULE] + rule_to_bytes(highlife_b, highlife_s))
    await idle(dut, 20)

    # command plus one byte, then silence past the timeout
    await send_bytes(dut, [CMD_RULE, 0xFF])
    await idle(dut, TIMEOUT_CLKS + 200)

    await ReadOnly()
    got_b, got_s = int(dut.birth.value), int(dut.survive.value)
    assert (got_b, got_s) == (highlife_b, highlife_s), (
        f"a partial transfer corrupted the live rule: "
        f"{mask_notation(got_b, got_s)}"
    )
    await Timer(1, unit="ns")

    # a clean rule must still land afterwards
    seeds_b, seeds_s = rule_masks("seeds")
    await send_bytes(dut, [CMD_RULE] + rule_to_bytes(seeds_b, seeds_s))
    await idle(dut, 20)
    await ReadOnly()
    assert (int(dut.birth.value), int(dut.survive.value)) == (seeds_b, seeds_s), (
        "loader did not recover after a timed-out transfer"
    )

    dut._log.info(
        "Partial transfer abandoned, live rule preserved, next rule accepted."
    )
