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

Methodology: [`hardware/synth/README.md`](hardware/synth/README.md).


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
