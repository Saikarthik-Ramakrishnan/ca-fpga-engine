# Phase 2: ca_cell.v

One cell of the automaton, the hardware twin of `update(alive, neighbors)`
from `golden_rule.py` and the console. One register holds state.
Combinational logic (an 8-input popcount plus a two-line comparison)
computes the next state.

`ca_cell` also has a `load`/`seed_bit` path. When `load` is high, the cell
takes `seed_bit` instead of computing the rule. That's how the grid below
gets an initial pattern written into it.

## Verification

There are only 2^9 = 512 possible inputs to this cell: 1 current-state bit
plus 8 neighbor bits. All 512 are checked, each compared against
`golden_rule.update()`, the same reference function every other tier in
this project is checked against.

A second test checks the load path on its own, since the exhaustive test
holds `load` low the whole time.

```bash
cd hardware/tests
make          # runs all 512 rule cases + the load-path test
```

# Phase 3: ca_grid.v

N cells wired into an actual grid, each connected to its real 8 neighbors,
sharing one clock.

This is a `generate` block. It's a build-time instruction telling the
synthesis tool to stamp out `ROWS*COLS` physical copies of `ca_cell` and
wire each one up by position. Neighbor wrap is toroidal, matching the `%`
wraparound in `golden_rule.py` and the console.

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

An 8x8 grid has 2^64 possible states, so exhaustive testing is off the
table here. Instead: four random starting patterns at different densities,
each run forward 15 generations.

The entire grid is checked against `golden_rule.step_golden()` after every
single generation, not only at the end. Checking every generation pins
down exactly which step a divergence happens on, if one happens.

```bash
cd hardware/tests
make -f Makefile.grid
```

All four trials passed on the first run. The toroidal wraparound math and
neighbor bit-packing were correct on the first attempt.

## What synthesis actually costs

Yosys's Gowin-targeted synthesis pass (`synth_gowin`) gives real primitive
counts for the 8x8 grid: 64 DFFC (one register per cell, as expected), 256
ALU (exactly 4 per cell, matching a single cell's isolated synthesis).

Working through the LUT-equivalent math, real usage per cell at this scale
lands close to the earlier single-cell estimate. The ~17x17 to ~22x22
realistic grid ceiling on the Primer 20K (out of its ~20,736 LUT4 budget)
holds up, not just as a single-cell guess.

## Next: Phase 4

Stream live grid state off-chip over UART to a PC visualizer, so a real
FPGA running this can be watched directly.
