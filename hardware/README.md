# Phase 2: ca_cell.v

One cell of the automaton, the hardware twin of `update(alive, neighbors)`
from `golden_rule.py` and the console.

- One register holds state.
- Combinational logic (an 8-input popcount plus a two-line comparison)
  computes the next state.
- A `load`/`seed_bit` path: when `load` is high, the cell takes `seed_bit`
  instead of computing the rule. That's how the grid gets an initial pattern.

## Verification

- Only 2^9 = 512 possible inputs exist (1 current-state bit + 8 neighbor
  bits), so all 512 are checked, not sampled.
- Each is compared against `golden_rule.update()`, the same reference every
  other tier in this project is checked against.
- A second test covers the load path on its own, since the exhaustive test
  holds `load` low throughout.

```bash
cd hardware/tests
make          # all 512 rule cases + the load-path test
```

# Phase 3: ca_grid.v

N cells wired into an actual grid, each connected to its real 8 neighbors,
sharing one clock.

- A `generate` block: a build-time instruction telling the synthesis tool to
  stamp out `ROWS*COLS` physical copies of `ca_cell` and wire each by position.
- Neighbor wrap is toroidal, matching the `%` wraparound in `golden_rule.py`
  and the console.

```
hardware/
├── rtl/
│   ├── ca_cell.v          # one cell
│   ├── ca_grid.v          # N cells wired into a grid
│   ├── uart_tx.v          # sends one byte over one wire
│   ├── grid_streamer.v    # snapshots the grid, feeds bytes to uart_tx
│   └── cellnet_top.v      # the whole chip
├── synth/                 # resource analysis, gate-level verification
└── tests/
    ├── Makefile            # ca_cell only
    ├── Makefile.grid        # ca_cell + ca_grid
    ├── Makefile.uart        # uart_tx only
    ├── Makefile.top         # the whole chip
    ├── Makefile.postsynth   # the synthesized netlist, not the RTL
    ├── test_ca_cell.py
    ├── test_ca_grid.py
    ├── test_uart_tx.py      # decodes real bytes off the wire
    ├── test_cellnet_top.py  # decodes real grid snapshots off the wire
    └── demos/               # capture + render a live run as a GIF
```

## Verification

- An 8x8 grid has 2^64 possible states, so exhaustive testing is off the table.
- Instead: four random starting patterns at different densities, each run
  forward 15 generations.
- The entire grid is checked against `golden_rule.step_golden()` after every
  single generation, not only at the end. That pins down exactly which step a
  divergence happens on.
- All four trials passed on the first run. The toroidal wraparound math and
  neighbor bit-packing were correct on the first attempt.

```bash
cd hardware/tests
make -f Makefile.grid
```

## What synthesis actually costs

- An earlier estimate here capped the grid at ~17x17 to ~22x22, based on a
  measured ~66 LUT4-equivalents per cell. That number was correct, and it was
  measuring a badly mapped circuit.
- `synth_gowin`'s default mapping builds a tree of wide muxes (costing 2, 4,
  and 8 LUT4s each) for the neighbor-count comparison, dominating the design.
- `-nowidelut` forbids that mapping: **~13.6 LUT4 per cell, a 4.9x saving**,
  verified at every grid size.
- Real ceiling is **38x38** (95% of LUT budget), not 22x22. 32x32 sits at 67%
  and is the safer first target to flash.
- Verified behavior-preserving, not just smaller: the grid testbench passes
  against the actual synthesized gate-level netlist, using Gowin's own
  primitive models.
- Critical path is 11 logic levels, independent of grid size. A bigger grid
  costs area, not clock speed.

Full methodology and numbers: [`hardware/synth/README.md`](synth/README.md).

# Phase 4: uart_tx.v, grid_streamer.v, cellnet_top.v

Getting live grid data off the chip.

- `uart_tx.v`: sends one byte at a time, standard UART framing (start bit, 8
  data bits LSB-first, stop bit).
- `grid_streamer.v`: snapshots the grid, sends a fixed sync byte (`0xAA`)
  followed by the grid packed into bytes, then immediately grabs a fresh
  snapshot and repeats. The grid can change every clock cycle but sending one
  snapshot takes many, so it never tries to report every generation. It
  reports whatever is current the instant it's free to send again.
- `cellnet_top.v`: wires `ca_grid` into `grid_streamer` into `uart_tx`. The
  whole chip, the actual pins a real board would expose.

## Verification

- `test_uart_tx.py` sends 8 known bytes (including `0x00`, `0xFF`, `0x01`,
  `0x80`) and decodes each straight off the simulated wire the way a real
  receiver would: wait for the line to fall, sample the middle of each bit
  period. All 8 matched.
- `test_cellnet_top.py` reuses that decoder against the whole chip. The grid is
  seeded with a glider, left to run freely, and a background task watches
  `tx_serial`, decodes frames, and rebuilds the 64-bit grid value each
  represents. Every decoded frame is checked against
  `golden_rule.step_golden()`'s full generation log for that run.

```bash
cd hardware/tests
make -f Makefile.uart   # uart_tx alone
make -f Makefile.top    # the whole chip, end to end
```

## Watching it run

`hardware/tests/demos/` captures real decoded UART frames from a live
simulation run and renders them into a GIF, styled like the console.

- Not a correctness test, just a way to watch Phase 4 work.
- Every frame comes from decoding `tx_serial` bit by bit, the same way a real
  PC receiver would, not from reading the simulated grid's internal state.

```bash
cd hardware/tests
PYTHONPATH="$(pwd)/demos:$PYTHONPATH" make -f Makefile.top MODULE=demo_capture
cd demos
python3 render_capture.py
```

Writes `phase4_live_capture.gif` into `hardware/tests/demos/`. The Live tab in
`cellnet_console.html` also loads the resulting `uart_capture.json` directly.
