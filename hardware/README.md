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

# Phase 4: uart_tx.v, grid_streamer.v, cellnet_top.v

Getting live grid data off the chip. Three new pieces:

- `uart_tx.v`: sends one byte at a time, standard UART framing (start bit,
  8 data bits LSB-first, stop bit).
- `grid_streamer.v`: grabs a snapshot of the grid, sends a fixed sync byte
  (`0xAA`) followed by the grid packed into bytes, then immediately grabs
  a fresh snapshot and repeats. The grid can change every clock cycle but
  sending one snapshot takes many cycles, so this module never tries to
  report every generation. It reports whatever is current the instant
  it's free to send again.
- `cellnet_top.v`: wires `ca_grid` into `grid_streamer` into `uart_tx`.
  This is the whole chip, the actual pins a real board would expose.

```
hardware/
├── rtl/
│   ├── ca_cell.v          # one cell
│   ├── ca_grid.v          # N cells wired into a grid
│   ├── uart_tx.v          # sends one byte over one wire
│   ├── grid_streamer.v    # snapshots the grid, feeds bytes to uart_tx
│   └── cellnet_top.v      # the whole chip
└── tests/
    ├── Makefile            # ca_cell only
    ├── Makefile.grid        # ca_cell + ca_grid
    ├── Makefile.uart        # uart_tx only
    ├── Makefile.top         # the whole chip
    ├── test_ca_cell.py
    ├── test_ca_grid.py
    ├── test_uart_tx.py      # decodes real bytes off the wire
    └── test_cellnet_top.py  # decodes real grid snapshots off the wire
```

## Verification

`test_uart_tx.py` sends 8 known bytes, including edge cases like `0x00`,
`0xFF`, `0x01`, and `0x80`, and decodes each one straight off the simulated
serial wire the way a real receiving computer would: wait for the line to
fall, then sample the middle of each bit period. All 8 matched.

`test_cellnet_top.py` reuses that same decoder against the whole chip.
The grid is seeded with a glider, left to run freely, and a background
task continuously watches `tx_serial`, decodes frames, and rebuilds the
64-bit grid value each one represents. Every decoded frame is checked
against `golden_rule.step_golden()`'s full generation-by-generation log
for that run.

```bash
cd hardware/tests
make -f Makefile.uart   # uart_tx alone
make -f Makefile.top    # the whole chip, end to end
```


