# Massively Parallel Cellular Automaton Engine

A cellular automaton engine built to run natively in parallel hardware.
Every cell is its own independent logic unit, updating on the same clock
edge as every other cell. The endgame output is a real electromechanical
flip-dot display.

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

## Why an FPGA

A cell's next state depends only on itself and its eight neighbors. On a
CPU or GPU, every cell still gets visited one at a time, just in bigger or
smaller batches.

An FPGA writes the rule as combinational logic once, then stamps that same
block down once per cell across the whole fabric. Every cell updates on
the same clock edge, all at once.

That's the real argument for an FPGA over a microcontroller or a GPU here.
The hardware fabric mirrors the shape of the problem.

The flip-dot display extends the same idea into the physical world. Each
pixel is a bistable electromagnetic disc: one coil per cell, holding its
state with zero standing power once flipped. Same "one independent unit
per cell" principle, expressed mechanically. That's why this project ends
at flip-dots and not an LED matrix.

## Phase 1: software prototype and parallelism benchmark

`software_prototype/cellnet_console.html` is a single self-contained HTML
file. No dependencies, no build step. Open it in a browser.

What's in it:

- The update rule, `update(alive, neighbors)`, is a pure function of local
  state only. No grid access, no shared variables. That signature is
  exactly what becomes one Verilog module in hardware.
- Five selectable rulesets (Conway, HighLife, Day & Night, Seeds, Maze),
  each a different truth table and therefore different combinational logic.
- A pattern bank (glider, LWSS, pulsar, R-pentomino, acorn, Gosper glider
  gun) plus free-draw.
- A flip-dot operator's console look: dots squash-flip on state change,
  with an optional synthesized clack per generation, scaled to how many
  cells flipped.
- A Displays tab surveying real physical output media (flip-dot,
  split-flap, VFD, Nixie, LED matrix), with notes on how an FPGA would
  actually drive each one.

`software_prototype/parallelism_ladder/` benchmarks the same CA rule
across five software substrates: naive Python threads, NumPy,
multiprocessing, Numba. It shows what "parallel" does and doesn't mean on
a CPU, GIL included, as the baseline the FPGA fabric gets measured against.
Full results in that folder's README.

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Software prototype: rule and visual target nailed down | done |
| 2 | `ca_cell.v`: one cell's update rule as combinational Verilog, testbenched in isolation | done |
| 3 | Parallel fabric: `generate` block instantiating `ca_cell` across the grid, toroidal wraparound, one shared clock | done |
| 4 | UART streaming of live grid state off-chip to a PC visualizer | next |
| 5 | Flip-dot driver stage: swap the output from UART/PC to real coil-driven hardware | planned |
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
│   └── tests/                      # cocotb testbenches, cell + grid
├── docs/
│   └── media/
│       └── cellnet_demo.gif
└── LICENSE
```

## Motivation

The second-year step up from an FPGA MNIST inference accelerator built
earlier. That project proved a pipeline could run on an FPGA at all. This
one uses an FPGA for what it's actually good at: fine-grained parallelism,
pointed at a physical output medium built on the same idea.

## Author

Saikarthik Ramakrishnan, ECE, Shiv Nadar University Delhi.
