 Massively Parallel Cellular Automaton Engine

[![verify](https://github.com/Saikarthik-Ramakrishnan/ca-fpga-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Saikarthik-Ramakrishnan/ca-fpga-engine/actions/workflows/ci.yml)

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

This is a cellular automaton engine built for an FPGA, in which every cell of the grid is its own small circuit and the whole grid advances by one generation on a single clock edge. A browser console drives the chip over a serial link, and the intended output is an electromechanical flip-dot display with one disc per cell. The project follows an earlier FPGA MNIST inference accelerator and asks what fine-grained parallelism is worth when every unit of work is identical and purely local.

## Why an FPGA

A cell's next state depends only on its own state and the states of its eight neighbors. A processor has to visit the cells in turn or in batches, while an FPGA can place a copy of the update rule beside every cell so that all of them compute at once. A flip-dot display carries the same structure into the physical world, because each disc is driven by its own coil and holds its position without power.

## System Overview

The system has three parts, and all of them share a single definition of the rule.

- **Hardware.** A Verilog design for the Sipeed Tang Primer 20K places one cell at every grid position, accepts seeds and rule changes over UART, and streams the live grid back to the host. The default build is 16x16, and the largest grid that fits the device is 32x32.
- **Software.** A browser console draws patterns and displays the board, a Python reference model serves as the single source of truth, and a multithreaded C++20 engine provides the laptop baseline for performance measurements.
- **Verification.** Every layer is checked against the reference model, from exhaustive tests of a single cell to cycle-accurate simulation of the complete chip, together with a proof that the parallel C++ engine is free of data races.

At its 27 MHz board clock the fabric is 2.6 times faster than the best laptop configuration at 16x16 and 5.3 times faster at 32x32, and it completes every generation in exactly one clock cycle. The design is verified in simulation, and measurement on the physical board is the next milestone.

## Documentation

| Document | Description |
|---|---|
| [Hardware design](hardware/README.md) | How the cell, the grid, the serial interface and the top-level chip are built and verified. |
| [Performance evaluation](docs/PERFORMANCE.md) | Throughput and latency of the fabric compared with a multithreaded C++ engine on a laptop. |
| [Concurrency and correctness](docs/CONCURRENCY.md) | How the parallel C++ engine protects shared state, with a proof and the evidence behind it. |
| [Verification strategy](docs/VERIFICATION.md) | The hardware and software test suites, what each one establishes and how to run them. |
| [Resource utilization](docs/RESOURCES.md) | FPGA area and timing for each grid size, before and after place and route. |
| [Runtime rule configuration](docs/RULE_CONFIGURATION.md) | How the rule is loaded over the serial link so that one bitstream runs every ruleset. |
| [Serial protocol](docs/PROTOCOL.md) | The byte format of the seeds, rules and frames exchanged with the chip. |
| [Board bring-up](hardware/FLASHING.md) | Building the bitstream, programming the Tang Primer 20K and seeding the board. |
| [Synthesis](hardware/synth/README.md) | The open-source toolchain flow and how the resource figures were measured. |
| [C++ engine](software_prototype/cpp/README.md) | Building, testing and benchmarking the parallel C++ implementation. |
| [Software benchmark](software_prototype/parallelism_ladder/README.md) | The Python reference model and the earlier comparison of software parallelism techniques. |
| [Status and roadmap](docs/ROADMAP.md) | The completed phases, the current state of the project and the work that remains. |
| [Repository layout](docs/REPOSITORY_LAYOUT.md) | Where each part of the project lives in the source tree. |

Begin with the performance evaluation for the main results, then read the hardware design for how the chip is built.

## Quick Start

Open `software_prototype/cellnet_console.html` in any browser to use the console without hardware. To run the full verification suite, which requires Icarus Verilog, cocotb and a C++20 compiler:

```bash
cd hardware/tests && ./run_all.sh
cd software_prototype/cpp && make check
```

## Author

Saikarthik Ramakrishnan, Electronics and Communication Engineering, Shiv Nadar University, Delhi.
