# Phase 2: ca_cell.v

One cell of the automaton, the hardware twin of `update(alive, neighbors)`
from `golden_rule.py` / the console. One register holds state; combinational
logic (an 8-input popcount plus a two-line comparison) computes the next
state. `ca_cell` also has a `load`/`seed_bit` path: when `load` is high, the
cell takes `seed_bit` instead of computing the rule, which is how the grid
below gets an initial pattern written into it.

## Verification

There are only 2^9 = 512 possible inputs to this cell (1 current-state bit
+ 8 neighbor bits), so I didn't sample a handful of cases. I checked all
512, each one compared against `golden_rule.update()`, the exact same
reference function every other tier in this project is checked against.
A second test checks the load path separately, since the exhaustive test
holds `load` low the whole time and never touches it.

```bash
cd hardware/tests
make          # runs all 512 rule cases + the load-path test
```

# Phase 3: ca_grid.v

N cells wired into an actual grid, each one connected to its real 8
neighbors, all sharing one clock. This is a `generate` block: not a loop
that runs on the chip, but a build-time instruction telling the synthesis
tool to stamp out `ROWS*COLS` physical copies of `ca_cell` and wire each
one up according to its position. Neighbor wrap is toroidal, matching the
`%` wraparound in `golden_rule.py` and the console exactly.

```
hardware/
├── rtl/
│   ├── ca_cell.v          # one cell
│   └── ca_grid.v          # N cells wired into a grid
└── tests/
    ├── Makefile            # cocotb + Icarus, ca_cell only
    ├── Makefile.grid        # cocotb + Icarus, ca_cell + ca_grid
    ├── test_ca_cell.py      # exhaustive + load-path verification
    └── test_ca_grid.py      # full-grid, multi-generation verification
```

## Verification

An 8x8 grid has 2^64 possible states, so exhaustive testing the way
`ca_cell` got tested isn't an option here. Instead: four different random
starting patterns (different densities, from sparse to dense), each run
forward 15 generations, checking the **entire grid** against
`golden_rule.step_golden()` after every single generation rather than only
at the end. That matters: if only the final grid were checked, a mismatch
tells you something went wrong somewhere in 15 steps; checking every
generation tells you exactly which one.

```bash
cd hardware/tests
make -f Makefile.grid
```

All four trials passed on the first real run, no debugging needed this
time. The toroidal wraparound math and the neighbor bit-packing were
correct on the first attempt.

## What synthesis actually costs

Running the design through Yosys's real Gowin-targeted synthesis pass
(`synth_gowin`) gives real primitive counts, not estimates. For the 8x8
grid: 64 DFFC (one register per cell, as expected), 256 ALU (exactly 4 per
cell, matching a single cell's isolated synthesis exactly), plus the rest
of the logic. Working through the LUT-equivalent math puts real usage at
roughly the same per-cell cost estimated from a single isolated cell
earlier, meaning the ~17x17 to ~22x22 realistic grid ceiling on the Primer
20K (out of its ~20,736 LUT4 budget) holds up at real scale, not just as a
single-cell guess.

## Next: Phase 4

Stream live grid state off-chip over UART to a PC visualizer, so a real
FPGA running this can actually be watched, not just simulated.
