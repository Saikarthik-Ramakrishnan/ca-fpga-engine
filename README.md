# Massively Parallel Cellular Automaton Engine

Cellular automaton engine for parallel hardware. Every cell is an independent
logic unit; all cells update on the same clock edge. The Target output is an
electromechanical flip-dot display.

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

## Why an FPGA

- A cell's next state depends on itself and its eight neighbors only.
- CPUs and GPUs visit cells in batches. An FPGA stamps the rule down once per
  cell as combinational logic; every cell updates simultaneously.
- Flip-dot displays extend the same structure into hardware: one bistable
  coil-driven disc per cell, zero standing power after a flip.


## Resource summary

Target: Gowin GW2A-18, Tang Primer 20K. 20,736 LUT4.

| | per cell | max grid |
|---|---|---|
| default mapping | 66 LUT4 | ~22x22 |
| `-nowidelut` | 13.6 LUT4 | 38x38 |

- Default `synth_gowin` maps the neighbor-count comparison to wide muxes
  (2/4/8 LUT4 each). `-nowidelut` forces plain LUT decomposition: 4.9x saving.
- Verified at gate level: synthesized netlist passes the grid testbench
  against `golden_rule.py`, using Gowin primitive models.
- Critical path: 11 logic levels, independent of grid size. Every cell reads
  and writes registers. Grid growth costs area; Fmax is unchanged.

Methodology: [`hardware/synth/README.md`](hardware/synth/README.md).

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Software prototype: rule and visual target | done |
| 2 | `ca_cell.v`: one cell as combinational Verilog, testbenched | done |
| 3 | Parallel fabric: `generate` grid, toroidal wrap, one clock | done |
| 4 | UART streaming of live grid state to a PC visualizer | done |
| 4.5 | UART seed path, generation pacer, flashable top, loopback verification | done |
| 5a | Bitstreams built on the open toolchain, timing closed at 27 MHz, prebuilt .fs in repo | done |
| 5b | Flash the Tang Primer 20K, close the loop against the console | next, needs board |
| 6 | Flip-dot driver stage: coil-driven output | later |
| 7 | Continuous-state rule (Lenia-style) or competing species | stretch |

## Repo structure

```
ca-fpga-engine/
├── README.md
├── software_prototype/
│   ├── cellnet_console.html      # Phase 1: the console
│   └── parallelism_ladder/       # software parallelism benchmark
├── hardware/
│   ├── rtl/ca_cell.v               # one cell
│   ├── rtl/ca_grid.v               # N cells, toroidal grid
│   ├── rtl/uart_tx.v               # byte out
│   ├── rtl/uart_rx.v               # byte in
│   ├── rtl/seed_loader.v           # UART bytes to grid seed
│   ├── rtl/grid_streamer.v         # grid snapshots to uart_tx
│   ├── rtl/cellnet_top.v           # full chip, flashable
│   ├── host/send_seed.py           # PC seed sender
│   ├── bitstreams/                 # prebuilt .fs (gzipped)
│   ├── FLASHING.md                 # board bring-up
│   ├── synth/                      # resource analysis, constraints, bitstream build
│   └── tests/                      # cocotb testbenches, all modules
├── docs/media/cellnet_demo.gif
└── LICENSE
```

## Motivation

- Second-year follow-up to an FPGA MNIST inference accelerator.
- Uses the FPGA for fine-grained parallelism, matched to an output medium with
  the same one-unit-per-cell structure.

## Author

Saikarthik Ramakrishnan, ECE, Shiv Nadar University Delhi.
