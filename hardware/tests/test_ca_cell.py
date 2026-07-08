# test_ca_cell.py
#
# Exhaustive verification of ca_cell.v against golden_rule.py.
#
# There are only 2^9 = 512 possible inputs to one cell (1 current-state bit
# + 8 neighbor bits), so "exhaustive" is not an exaggeration -- this test
# checks every single one, not a sample. If this passes, ca_cell.v is
# provably correct for all reachable inputs, not just the cases someone
# thought to write down.
#
# This is also the concrete answer to "does Python touch the FPGA": it
# doesn't. Python here drives the *simulator*, feeding inputs and checking
# outputs -- the DUT (ca_cell.v) is doing 100% of the actual computation,
# same as it will when it's real silicon instead of a simulation.

import sys
import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

# reuse the exact same rule the whole rest of the project is checked
# against -- not a re-typed copy of it.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                  "software_prototype", "parallelism_ladder"),
)
from golden_rule import update as golden_update  # noqa: E402


def neighbor_bits_to_count(neighbors: int) -> int:
    return bin(neighbors).count("1")


@cocotb.test()
async def exhaustive_truth_table(dut):
    """Drive all 512 (state, neighbors) combinations, compare to golden_rule.update()."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # hold reset once at the start
    dut.rst_n.value = 0
    dut.neighbors.value = 0
    dut.load.value = 0        # exercising the rule path, not the seed path
    dut.seed_bit.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    mismatches = []
    checked = 0

    for state in (0, 1):
        for neighbors in range(256):
            # force the cell into the exact state we want to test FROM.
            # this is a verification-only move (not something you'd do in
            # real hardware) -- poking the register directly so we can
            # test all 512 combinations rather than only the ones we could
            # organically reach by clocking from reset.
            dut.state.value = state
            dut.neighbors.value = neighbors

            expected = golden_update(state, neighbor_bits_to_count(neighbors))

            await RisingEdge(dut.clk)
            await ReadOnly()  # let the non-blocking assignment settle before we sample

            got = int(dut.state.value)
            checked += 1
            if got != expected:
                mismatches.append((state, neighbors, expected, got))

            await Timer(1, unit="ns")  # step out of ReadOnly before next iteration writes

    assert checked == 512, f"expected to check 512 cases, checked {checked}"

    if mismatches:
        lines = [
            f"  state={s} neighbors={n:08b} (count={neighbor_bits_to_count(n)}) "
            f"expected={e} got={g}"
            for s, n, e, g in mismatches[:20]
        ]
        raise AssertionError(
            f"{len(mismatches)} / 512 cases mismatched golden_rule.update():\n"
            + "\n".join(lines)
        )

    dut._log.info(f"All {checked} cases match golden_rule.update(). ca_cell.v is correct.")


@cocotb.test()
async def load_path_overrides_rule(dut):
    """The exhaustive test above holds load=0 the whole time, so it never
    touches the seed path. Check that separately: when load=1, the cell
    must take seed_bit regardless of what the rule would have computed."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.neighbors.value = 0
    dut.load.value = 0
    dut.seed_bit.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # set up a case where the rule would clearly say "stay dead"
    # (0 neighbors alive, cell dead -> rule says stay 0), then load a 1
    # over it and confirm the load wins.
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

    # now drop load and confirm the rule takes back over on the next edge
    dut.load.value = 0
    dut.neighbors.value = 0  # 0 neighbors, cell currently alive -> rule kills it
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.state.value) == 0, (
        "once load=0, the rule should resume controlling next state"
    )

    dut._log.info("Load path verified: overrides the rule when high, releases control when low.")
