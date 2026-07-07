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


## Next: Phase 3

Wire N² of these into a `generate` block, each one connected to its 8
actual neighbors (toroidal wraparound, matching the software prototype),
all sharing one clock.
