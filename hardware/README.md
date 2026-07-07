# Phase 2: ca_cell.v

One cell of the automaton, the hardware twin of `update(alive, neighbors)`
from `golden_rule.py` / the console. One register holds state; combinational
logic (an 8-input popcount plus a two-line comparison) computes the next
state. This is the exact block Phase 3 instantiates once per cell across
the whole grid.

```
hardware/
├── rtl/
│   └── ca_cell.v          # the cell itself
└── tests/
    ├── Makefile            # cocotb + Icarus Verilog wiring
    └── test_ca_cell.py     # exhaustive verification
```

## Verification

There are only 2^9 = 512 possible inputs to this cell (1 current-state bit
+ 8 neighbor bits), so I didn't sample a handful of cases. I checked all
512, each one compared against `golden_rule.update()`, the exact same
reference function every other tier in this project is checked against.

```bash
cd hardware/tests
make          # runs all 512 cases, PASS/FAIL for each
```

### The bug the exhaustive test actually caught

First run: 228 out of 512 cases failed. Before assuming the Verilog was
wrong, I wrote a small debug testbench that dumped the internal `count` and
`next_state` wires cycle-by-cycle for one known case (`state=0`,
`neighbors=00000111`, a clean birth case). That showed the RTL computing
`count=3, next_state=1` correctly, but my testbench was reading
`dut.state.value` **one cycle too early**, before the clocked register's
non-blocking assignment had actually committed for that edge. cocotb has a
`ReadOnly` trigger for exactly this: sampling after `await RisingEdge(...)`
without also awaiting `ReadOnly()` first can catch a register mid-update.
Adding that (plus a small `Timer` step afterward, since you can't issue new
writes while still inside the `ReadOnly` phase) fixed it: all 512 cases now
pass.

Worth being honest about in a writeup: the RTL was correct on the first
try. The bug was entirely in how the testbench sampled it, which is
exactly the kind of mistake an exhaustive, automated check catches and a
few hand-picked spot-checks probably wouldn't have.

## Next: Phase 3

Wire N² of these into a `generate` block, each one connected to its 8
actual neighbors (toroidal wraparound, matching the software prototype),
all sharing one clock.
