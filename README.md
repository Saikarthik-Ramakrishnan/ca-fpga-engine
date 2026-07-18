# Massively Parallel Cellular Automaton Engine

A cellular automaton engine built to run natively in parallel hardware. Every
cell is its own independent logic unit, updating on the same clock edge as
every other cell. The endgame output is a real electromechanical flip-dot
display.

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

## Why an FPGA

- A cell's next state depends only on itself and its eight neighbors.
- On a CPU or GPU, every cell still gets visited one at a time, just in bigger
  or smaller batches.
- An FPGA writes the rule as combinational logic once, then stamps that block
  down once per cell across the fabric. Every cell updates on the same clock
  edge, all at once.
- The hardware fabric mirrors the shape of the problem. That's the argument
  for an FPGA over a microcontroller or a GPU.
- The flip-dot display extends the idea into the physical world: each pixel is
  a bistable electromagnetic disc, one coil per cell, holding state with zero
  standing power once flipped.

## Phase 1: software prototype and parallelism benchmark

`software_prototype/cellnet_console.html`, a single self-contained HTML file.
No dependencies, no build step. Open it in a browser.

- Update rule `update(alive, neighbors)` is a pure function of local state
  only. No grid access, no shared variables. That signature is exactly what
  becomes one Verilog module in hardware.
- Five selectable rulesets (Conway, HighLife, Day & Night, Seeds, Maze), each
  a different truth table and therefore different combinational logic.
- Pattern bank (glider, LWSS, pulsar, R-pentomino, acorn, Gosper glider gun)
  plus free-draw.
- Flip-dot operator's console look: dots squash-flip on state change, with an
  optional synthesized clack per generation, scaled to how many cells flipped.
- Displays tab surveying real physical output media (flip-dot, split-flap,
  VFD, Nixie, LED matrix), with notes on how an FPGA would drive each one.
- Live tab replays real decoded UART captures from the simulated chip,
  connects to real hardware over Web Serial, and (since Phase 4.5) sends
  seeds back to the chip over the same cable.
- Wildfire tab: the Drossel-Schwabl forest fire model, the console's first
  multi-state, probabilistic rule. Trees grow, lightning strikes, fire
  spreads to neighbors and burns out. Still purely local (each cell reads
  only its eight neighbors), so it maps onto the same fabric: 2 bits of
  state per cell, an 8-input OR instead of Life's popcount, and an LFSR
  for the randomness.

`software_prototype/parallelism_ladder/` benchmarks the same CA rule across
five software substrates: naive Python threads, NumPy, multiprocessing, Numba.
Full results in that folder's README.

## What actually fits on the chip

Verified in simulation and analyzed against the real target (Gowin GW2A-18,
Tang Primer 20K: 20,736 LUT4).

| | per cell | max grid on GW2A-18 |
|---|---|---|
| default mapping | 66 LUT4 | ~22x22 |
| `-nowidelut` | 13.6 LUT4 | **38x38** |

- Early estimate capped the grid at ~22x22, based on ~66 LUT4-equivalents per
  cell.
- One 9-input boolean function costing 66 LUTs made no sense. Cause:
  `synth_gowin`'s default mapping builds a tree of wide muxes (costing 2, 4,
  and 8 LUT4s each) for the neighbor-count comparison.
- Forbidding that with `-nowidelut` drops the cost to **13.6 LUT4 per cell, a
  4.9x saving**, consistent at every grid size.
- Verified **at the gate level**: the grid testbench runs against the actual
  synthesized netlist, using Gowin's own primitive models, and matches
  `golden_rule.py` bit for bit.
- Critical path is 11 logic levels and **independent of grid size**. Every
  cell reads registers and writes registers, so no signal crosses more than
  one cell per clock. Growing the grid costs area, not clock speed. Software
  doing the same work gets linearly slower; this does not.

Details and methodology: [`hardware/synth/README.md`](hardware/synth/README.md).

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Software prototype: rule and visual target nailed down | done |
| 2 | `ca_cell.v`: one cell's update rule as combinational Verilog, testbenched in isolation | done |
| 3 | Parallel fabric: `generate` block instantiating `ca_cell` across the grid, toroidal wraparound, one shared clock | done |
| 4 | UART streaming of live grid state off-chip to a PC visualizer | done |
| 4.5 | UART seed path in, generation pacer, flashable top with real pin constraints, full loopback verification | done |
| 5a | Real bitstream built with the open toolchain (Yosys + nextpnr + Apicula), timing verified at 27 MHz, prebuilt .fs shipped in the repo with a flashing guide | done |
| 5b | Physically flash the Tang Primer 20K and close the loop against the console | next, needs the board |
| 6 | Flip-dot driver stage: swap the output from UART/PC to real coil-driven hardware | later |
| 6 | Novelty extension: continuous-state rule (Lenia-style) or a second competing species (predator/prey) | stretch |

## Repo structure

```
ca-fpga-engine/
├── README.md
├── software_prototype/
│   ├── cellnet_console.html      # Phase 1: the console
│   └── parallelism_ladder/       # Phase 1.5: GIL/parallelism benchmark suite
├── hardware/                      # Phase 2+: the actual Verilog
│   ├── rtl/ca_cell.v               # one cell, verified against golden_rule.py
│   ├── rtl/ca_grid.v               # N cells wired into a real grid
│   ├── rtl/uart_tx.v               # sends one byte over one wire
│   ├── rtl/uart_rx.v               # receives one byte over one wire
│   ├── rtl/seed_loader.v           # turns received bytes into a grid seed
│   ├── rtl/grid_streamer.v         # snapshots the grid, feeds uart_tx
│   ├── rtl/cellnet_top.v           # the whole chip, flashable as-is
│   ├── host/send_seed.py           # PC-side seed sender for the real board
│   ├── bitstreams/                 # prebuilt, ready-to-flash .fs (gzipped)
│   ├── FLASHING.md                 # board bring-up guide
│   ├── synth/                      # resource analysis, pin constraints, netlists
│   └── tests/                      # cocotb testbenches for every module above
├── docs/
│   └── media/
│       └── cellnet_demo.gif
└── LICENSE
```

## Motivation

- The second-year step up from an FPGA MNIST inference accelerator built
  earlier, which proved a pipeline could run on an FPGA at all.
- This one uses an FPGA for what it's actually good at: fine-grained
  parallelism, pointed at a physical output medium built on the same idea.

## Author

Saikarthik Ramakrishnan, ECE, Shiv Nadar University Delhi.
