# test_cellnet_rules.py
#
# The Phase 5b end-to-end check: the rule itself arriving over the wire.
# Like test_cellnet_loopback.py, the chip is driven ONLY through its real
# pins (clk, rst_n, rx_serial, tx_serial). Nothing reaches inside. Every
# helper here that touches the wire is imported from the two proven
# codecs rather than rewritten.
#
#   this test --(rx_serial)--> uart_rx -> rule_loader -> [birth/survive]
#                                      `-> seed_loader -> [load/seed]
#   this test <--(tx_serial)-- uart_tx <- grid_streamer <- ca_grid_rule
#
# Three claims, in increasing order of how much they would embarrass the
# project if false:
#
#   1. rule_then_seed_runs_the_new_rule
#      Send 0x33 + B2/S, then seed a pattern. Every frame must follow the
#      SEEDS trajectory. If the rule never reached the fabric the frames
#      would follow Conway instead, and Conway and Seeds diverge on the
#      first generation from this seed.
#   2. rule_change_mid_run_without_reseeding
#      Seed a blinker under the reset-default Conway, watch it oscillate,
#      then send a rule change and nothing else. The grid must carry on
#      from whatever phase it was in, under the new rule. This is the
#      claim that the rule is live state on the fabric, not a build-time
#      constant.
#   3. rule_survives_a_reseed
#      Set a rule, then seed twice. The second seed must not reset the
#      rule to Conway. The two loaders share a byte stream; this is where
#      a gating mistake would surface end to end.
#
# Sim parameters match test_cellnet_loopback.py exactly, including the
# deliberately non-commensurate GEN_DIV: with the generation period an
# exact divisor of the frame period every frame latches the same phase and
# a period-2 pattern looks frozen. That alias is a real bug this suite's
# sibling caught, and test 2 below depends on not reintroducing it.

import sys
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.dirname(__file__))
from test_cellnet_loopback import (  # noqa: E402  proven wire helpers
    ROWS, COLS, NUM_BYTES, CLKS_PER_BIT, GEN_DIV,
    grid_to_bits, blinker_grid, glider_grid,
    assert_frames_follow, frame_collector, send_seed,
)
from test_uart_rx import send_uart_byte  # noqa: E402  proven wire encoder
from test_rule_loader import rule_to_bytes  # noqa: E402  the one encoder

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                 "software_prototype", "parallelism_ladder"),
)
from golden_rule import (  # noqa: E402
    rule_masks, mask_notation, step_golden_masked,
)

CMD_RULE = 0x33


def masked_trajectory(seed_grid, generations, birth, survive):
    """Every grid value the golden model produces under one rule,
    inclusive of generation 0."""
    log = [grid_to_bits(seed_grid, ROWS, COLS)]
    g = seed_grid
    for _ in range(generations):
        g = step_golden_masked(g, ROWS, birth, survive)
        log.append(grid_to_bits(g, ROWS, COLS))
    return log


def bits_to_grid(bits: int):
    return [[(bits >> (r * COLS + c)) & 1 for c in range(COLS)] for r in range(ROWS)]


async def send_rule(dut, name: str):
    """Push a 0x33 rule command onto rx_serial at real UART timing, with
    the same inter-byte idle a PC produces."""
    birth, survive = rule_masks(name)
    await send_uart_byte(dut, CMD_RULE, CLKS_PER_BIT)
    for b in rule_to_bytes(birth, survive):
        for _ in range(CLKS_PER_BIT * 2):
            await RisingEdge(dut.clk)
        await send_uart_byte(dut, b, CLKS_PER_BIT)
    return birth, survive


async def bring_up(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    dut.rx_serial.value = 1        # UART line idles high
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)

    frames = []
    cocotb.start_soon(frame_collector(dut, frames))
    return frames


@cocotb.test()
async def rule_then_seed_runs_the_new_rule(dut):
    """0x33 B2/S, then a seed. Frames must follow Seeds, not Conway."""
    frames = await bring_up(dut)

    birth, survive = await send_rule(dut, "seeds")
    conway_b, conway_s = rule_masks("conway")

    pattern = glider_grid(ROWS, COLS)
    await send_seed(dut, pattern)

    run_clks = GEN_DIV * 30
    for _ in range(run_clks):
        await RisingEdge(dut.clk)

    gens = run_clks // GEN_DIV + 4
    seeds_log = masked_trajectory(pattern, gens, birth, survive)
    conway_log = masked_trajectory(pattern, gens, conway_b, conway_s)
    assert seeds_log[1] != conway_log[1], (
        "test is vacuous: Seeds and Conway agree on generation 1 here"
    )

    first_live = next((i for i, f in enumerate(frames) if f != 0), None)
    assert first_live is not None, "no live frames after seeding"
    live = frames[first_live:]

    chosen = assert_frames_follow(live, seeds_log, "seeds")
    assert len(set(chosen)) >= 3, (
        f"pacer appears stuck: only generations {sorted(set(chosen))} seen"
    )
    dut._log.info(
        f"{mask_notation(birth, survive)} over the wire: {len(live)} frames "
        f"followed generations {chosen}"
    )


@cocotb.test()
async def rule_change_mid_run_without_reseeding(dut):
    """Blinker under the reset default, then a rule change and nothing
    else. The grid must continue from its live phase under the new rule."""
    frames = await bring_up(dut)

    conway_b, conway_s = rule_masks("conway")
    blinker = blinker_grid(ROWS, COLS)
    await send_seed(dut, blinker)

    for _ in range(GEN_DIV * 20):
        await RisingEdge(dut.clk)

    conway_log = masked_trajectory(blinker, 25, conway_b, conway_s)
    first_live = next((i for i, f in enumerate(frames) if f != 0), None)
    assert first_live is not None, "no live frames after seeding"
    pre = frames[first_live:]
    assert_frames_follow(pre, conway_log, "blinker/conway")
    assert len(set(pre)) >= 2, "blinker never oscillated before the rule change"

    # ---- the rule change, with no seed alongside it ----
    frames_at_switch = len(frames)
    birth, survive = await send_rule(dut, "seeds")

    for _ in range(GEN_DIV * 20):
        await RisingEdge(dut.clk)

    post = frames[frames_at_switch:]
    assert len(post) >= 4, f"too few frames after the rule change: {len(post)}"

    # The exact generation the change landed on is not observable from
    # outside, and a blinker has two phases, so accept either phase as the
    # launch point: build a Seeds trajectory from each and require the
    # frames to follow one of them.
    phases = [bits_to_grid(v) for v in dict.fromkeys(conway_log)]
    assert len(phases) == 2, f"blinker should have 2 phases, got {len(phases)}"

    errors = []
    for phase_index, phase in enumerate(phases):
        seeds_log = masked_trajectory(phase, 30, birth, survive)
        blinker_values = set(conway_log)
        start = 0
        # skip frames still showing the old rule's oscillation
        while start < min(4, len(post)) and post[start] in blinker_values:
            start += 1
        if start >= len(post):
            errors.append(f"phase {phase_index}: every frame still looks like a blinker")
            continue
        try:
            chosen = assert_frames_follow(post[start:], seeds_log, f"phase{phase_index}")
        except AssertionError as exc:
            errors.append(f"phase {phase_index}: {exc}")
            continue
        dut._log.info(
            f"Rule changed live to {mask_notation(birth, survive)} with no reseed: "
            f"{len(post) - start} frames followed generations {chosen} "
            f"from blinker phase {phase_index}"
        )
        return

    raise AssertionError(
        "frames after the rule change follow neither Seeds trajectory:\n  "
        + "\n  ".join(errors)
    )


@cocotb.test()
async def rule_survives_a_reseed(dut):
    """Seeding must not disturb the rule register. Two loaders, one byte
    stream: this is the end-to-end version of the gating guards."""
    frames = await bring_up(dut)

    birth, survive = await send_rule(dut, "maze")
    conway_b, conway_s = rule_masks("conway")

    await send_seed(dut, glider_grid(ROWS, COLS))
    for _ in range(GEN_DIV * 12):
        await RisingEdge(dut.clk)

    # second seed, a different pattern, under the same rule
    frames_at_reseed = len(frames)
    pattern = blinker_grid(ROWS, COLS)
    await send_seed(dut, pattern)
    for _ in range(GEN_DIV * 20):
        await RisingEdge(dut.clk)

    maze_log = masked_trajectory(pattern, 25, birth, survive)
    conway_log = masked_trajectory(pattern, 25, conway_b, conway_s)
    assert maze_log[1] != conway_log[1], (
        "test is vacuous: Maze and Conway agree on generation 1 here"
    )

    post = frames[frames_at_reseed:]
    assert len(post) >= 4, f"too few frames after reseed: {len(post)}"

    maze_values = set(maze_log)
    start = 0
    while start < min(3, len(post)) and post[start] not in maze_values:
        start += 1
    assert start < 3, (
        "no frame within 3 of the reseed follows the Maze trajectory: "
        f"got {[hex(f) for f in post[:3]]}"
    )
    chosen = assert_frames_follow(post[start:], maze_log, "maze/reseed")
    dut._log.info(
        f"Rule {mask_notation(birth, survive)} survived a reseed: "
        f"{len(post) - start} frames followed generations {chosen}"
    )
