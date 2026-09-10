# test_ca_cell_rule.py
#
# ca_cell.v was verified over all 512 of its inputs. ca_cell_rule.v has
# 512 * 2^18 possible inputs, so "exhaustive" has to be redefined rather
# than abandoned: exhaustive over the input space, for each rule that
# matters, plus a random sweep over rule space to catch a mask bit that
# was mis-wired in a way the five named rules happen not to exercise.
#
#   1. all_named_rules_exhaustive
#      512 (state, neighbors) combinations x 5 console rulesets = 2,560
#      cases, every one compared to golden_rule.update_masked().
#   2. random_rule_masks_exhaustive
#      24 random (birth, survive) mask pairs, drawn over the full 18-bit
#      space, each swept over all 512 inputs. 12,288 more cases. Seeds
#      0 and 0x1FF are forced in so "no rule at all" and "every rule at
#      once" are both covered.
#   3. conway_default_matches_fixed_cell
#      Driven with the Conway masks, this cell must agree with the
#      original hardwired golden_rule.update() on all 512 inputs. That is
#      the compatibility claim the whole RULE_CFG=1 default rests on.
#   4. load_path_overrides_rule
#      The seed/hold path still wins over the rule, for a rule that is
#      not Conway. This is the path the generation pacer reuses.

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
    RULES, rule_masks, mask_notation, update_masked, update as golden_update,
)


def neighbor_bits_to_count(neighbors: int) -> int:
    return bin(neighbors).count("1")


async def start_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.neighbors.value = 0
    dut.load.value = 0
    dut.seed_bit.value = 0
    dut.birth.value = 0
    dut.survive.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def sweep_all_512(dut, birth: int, survive: int, label: str) -> int:
    """Drive every (state, neighbors) pair for one fixed rule. Returns the
    number of cases checked; raises on the first batch of mismatches."""
    dut.birth.value = birth
    dut.survive.value = survive

    mismatches = []
    checked = 0

    for state in (0, 1):
        for neighbors in range(256):
            # poke the register directly so all 512 combinations are
            # reachable, not just the ones organically clocked into from
            # reset. Verification-only, same move as test_ca_cell.py.
            dut.state.value = state
            dut.neighbors.value = neighbors

            expected = update_masked(
                state, neighbor_bits_to_count(neighbors), birth, survive
            )

            await RisingEdge(dut.clk)
            await ReadOnly()

            got = int(dut.state.value)
            checked += 1
            if got != expected:
                mismatches.append((state, neighbors, expected, got))

            await Timer(1, unit="ns")

    assert checked == 512, f"[{label}] expected 512 cases, checked {checked}"

    if mismatches:
        lines = [
            f"  state={s} neighbors={n:08b} (count={neighbor_bits_to_count(n)}) "
            f"expected={e} got={g}"
            for s, n, e, g in mismatches[:20]
        ]
        raise AssertionError(
            f"[{label}] {len(mismatches)} / 512 cases mismatched "
            f"update_masked(birth=0b{birth:09b}, survive=0b{survive:09b}):\n"
            + "\n".join(lines)
        )
    return checked


@cocotb.test()
async def all_named_rules_exhaustive(dut):
    """All 512 inputs, for each of the five rulesets the console ships."""
    await start_and_reset(dut)

    total = 0
    for name in RULES:
        birth, survive = rule_masks(name)
        notation = mask_notation(birth, survive)
        total += await sweep_all_512(dut, birth, survive, f"{name} {notation}")
        dut._log.info(f"{name:9s} {notation:14s} 512/512 match")

    assert total == 512 * len(RULES)
    dut._log.info(
        f"All {total} cases ({len(RULES)} rulesets x 512 inputs) match "
        f"golden_rule.update_masked()."
    )


@cocotb.test()
async def random_rule_masks_exhaustive(dut):
    """Random points in the 18-bit rule space, each swept exhaustively.
    Catches a mask bit wired to the wrong index, which the five named
    rules can miss: none of them, for instance, uses birth[0]."""
    await start_and_reset(dut)

    rng = random.Random(20260825)
    # forced corners: no rule fires at all, and every rule fires at once.
    trials = [(0, 0), (0x1FF, 0x1FF)]
    while len(trials) < 24:
        trials.append((rng.getrandbits(9), rng.getrandbits(9)))

    total = 0
    for birth, survive in trials:
        total += await sweep_all_512(
            dut, birth, survive, f"random B=0b{birth:09b} S=0b{survive:09b}"
        )

    assert total == 512 * len(trials)
    dut._log.info(
        f"{len(trials)} random rule masks x 512 inputs = {total} cases, all match."
    )


@cocotb.test()
async def conway_default_matches_fixed_cell(dut):
    """Held at the Conway masks, ca_cell_rule must be indistinguishable
    from ca_cell.v over the whole input space. rule_loader resets to these
    masks, so this is what a freshly configured chip does before the PC
    ever speaks to it."""
    await start_and_reset(dut)

    birth, survive = rule_masks("conway")
    dut.birth.value = birth
    dut.survive.value = survive

    checked = 0
    for state in (0, 1):
        for neighbors in range(256):
            dut.state.value = state
            dut.neighbors.value = neighbors
            expected = golden_update(state, neighbor_bits_to_count(neighbors))

            await RisingEdge(dut.clk)
            await ReadOnly()
            assert int(dut.state.value) == expected, (
                f"Conway masks disagree with hardwired ca_cell.v at "
                f"state={state} neighbors={neighbors:08b}"
            )
            checked += 1
            await Timer(1, unit="ns")

    assert checked == 512
    dut._log.info(
        "512/512: with Conway masks, ca_cell_rule matches the hardwired rule exactly."
    )


@cocotb.test()
async def load_path_overrides_rule(dut):
    """Seeding still beats the rule, and releasing load hands control back.
    Run under Seeds (B2/S), whose survive mask is empty, so a live cell is
    guaranteed to die the moment the rule regains control: an accidental
    stuck-at-load would be visible rather than benign."""
    await start_and_reset(dut)

    birth, survive = rule_masks("seeds")
    assert survive == 0, "Seeds should have an empty survive mask"
    dut.birth.value = birth
    dut.survive.value = survive

    # rule would say "stay dead" (0 neighbors, dead cell); load a 1 over it
    dut.state.value = 0
    dut.neighbors.value = 0
    dut.load.value = 1
    dut.seed_bit.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.state.value) == 1, (
        "load=1 should force state to seed_bit regardless of the rule result"
    )
    await Timer(1, unit="ns")

    # hold: load stays high with seed_bit fed back. This is exactly what
    # the generation pacer does between ticks.
    for _ in range(5):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.state.value) == 1, "hold path let the cell change"
        await Timer(1, unit="ns")

    # release: under B2/S a live cell with 0 neighbors must die
    dut.load.value = 0
    dut.neighbors.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.state.value) == 0, (
        "once load=0 the rule should resume; Seeds has no survive case"
    )

    dut._log.info(
        "Load path verified under B2/S: overrides the rule, holds, then releases."
    )
