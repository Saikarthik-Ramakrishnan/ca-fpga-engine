# CELL·NET — Massively Parallel Cellular Automaton Engine

A cellular automaton engine designed to run natively in parallel hardware —
where every cell is its own independent logic unit, updating simultaneously
on a single clock edge — with a real electromechanical flip-dot display as
the eventual output target.

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

## The thesis

A cellular automaton's update rule is embarrassingly parallel by
construction: each cell's next state depends only on its own state and its
eight neighbors. Running that on a CPU or GPU means visiting every cell
sequentially (or in large-but-still-serial batches). Running it on an FPGA
means something different: instantiate the rule as combinational logic
*once*, then repeat that logic block once per cell across the fabric. The
entire grid — thousands of cells — updates in **one clock cycle**.

That's the whole argument for using an FPGA here instead of a
microcontroller or GPU: not raw speed, but genuine per-cell independence
that matches how the hardware fabric itself is built.

The output target follows the same logic one step further. A flip-dot
display is a grid of bistable electromagnetic discs — one coil per pixel,
each holding its state with **zero standing power**. That's a mechanical
echo of the same "one independent unit per cell" idea the compute fabric is
built on, which is why it's the display this project is aimed at rather than
an LED matrix.

## Current status: Phase 1 — software prototype (+ parallelism benchmark)

`software_prototype/cellnet_console.html` is a self-contained, dependency-free
console that:

- Implements the CA update rule as a pure function of local state only
  (`update(alive, neighbors)`) — written deliberately so it maps 1:1 onto a
  future Verilog module, instantiated once per cell
- Ships five selectable rulesets (Conway, HighLife, Day & Night, Seeds, Maze)
  — each one a different truth table, i.e. different combinational logic to
  eventually synthesize
- Includes a pattern bank (glider, LWSS, pulsar, R-pentomino, acorn, Gosper
  glider gun) and free-draw
- Renders as a flip-dot operator's console — dots physically squash-flip on
  state change, with an optional synthesized "clack" per generation, scaled
  to how many cells flipped
- Has a **Displays** tab surveying real physical output media (flip-dot,
  split-flap, VFD, Nixie, LED matrix) with honest notes on how an FPGA would
  actually drive each one

`software_prototype/parallelism_ladder/` benchmarks the same CA rule across
five software substrates — naive threads, NumPy, multiprocessing, Numba —
to concretely demonstrate what "parallel" does and doesn't mean in software
(including a measured GIL bottleneck) before any of it is compared to what
the FPGA fabric does in hardware. See its own README for full results and
methodology.

Open `cellnet_console.html` directly in any browser — no build step, no
server.

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Software prototype — rule + visual target nailed down | ✅ done |
| 2 | `ca_cell.v` — one cell's update rule as combinational Verilog, testbenched in isolation | ⏳ next |
| 3 | Parallel fabric — 2D `generate` block instantiating `ca_cell` across the grid, wired to 8 neighbors with toroidal wraparound, one shared clock | planned |
| 4 | UART streaming of live grid state off-chip to a PC visualizer | planned |
| 5 | Flip-dot driver stage — swap the output from UART/PC to real coil-driven hardware | planned |
| 6 | Novelty extension — continuous-state rule (Lenia-style) or a second competing species (predator/prey) | stretch |

## Repo structure

```
ca-fpga-engine/
├── README.md
├── software_prototype/
│   ├── cellnet_console.html      # Phase 1 — the console
│   └── parallelism_ladder/       # Phase 1.5 — GIL/parallelism benchmark suite
├── hardware/                     # Phase 2+ — Verilog lands here
├── docs/
│   └── media/
│       └── cellnet_demo.gif
└── LICENSE
```

## Why this project

Built as a second-year step up from an FPGA MNIST inference accelerator —
that project proved a pipeline could run on an FPGA; this one is about using
the FPGA for the one thing it's uniquely suited to: true fine-grained
parallelism, aimed at a physical output medium that shares the same design
philosophy.

## Author

Ram — ECE, Shiv Nadar University Delhi.
