## Massively Parallel Cellular Automaton Engine

[![verify](https://github.com/Saikarthik-Ramakrishnan/ca-fpga-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Saikarthik-Ramakrishnan/ca-fpga-engine/actions/workflows/ci.yml) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22905813.svg)](https://doi.org/10.5281/zenodo.22905813)

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

This is a cellular automaton engine built for an FPGA, in which every cell of the grid is its own small circuit and the whole grid advances by one generation on a single clock edge. A browser console drives the chip over a serial link, and the intended output is an electromechanical flip-dot display with one disc per cell. The project follows an earlier FPGA MNIST inference accelerator and asks what fine-grained parallelism is worth when every unit of work is identical and purely local.

## Why an FPGA

A cell's next state depends only on its own state and the states of its eight neighbors. A processor has to visit the cells in turn or in batches, while an FPGA can place a copy of the update rule beside every cell so that all of them compute at once. A flip-dot display carries the same structure into the physical world, because each disc is driven by its own coil and holds its position without power.

## System Overview

The chip runs on a Sipeed Tang Primer 20K board and gives every cell its own circuit, for grids of up to 32x32. A browser console sends patterns and rules to the board over USB and displays the grid that the board streams back. A Python reference model defines the correct behavior, and every part of the hardware and software is tested against it.

## Documentation

Start here, and follow any link for more detail.

| Document | Description |
|---|---|
| [Hardware design](hardware/README.md) | How the chip is built and tested. |
| [Performance](docs/PERFORMANCE.md) | Speed and latency of the FPGA compared with a laptop. |
| [Concurrency and correctness](docs/CONCURRENCY.md) | How the parallel software stays correct, with a proof. |
| [Verification](docs/VERIFICATION.md) | The test suites and how to run them. |
| [Board bring-up](hardware/FLASHING.md) | Programming the board and sending patterns to it. |
| [Status and roadmap](docs/ROADMAP.md) | What is finished and what comes next. |

## Quick Start

Open `software_prototype/cellnet_console.html` in any browser to use the console without hardware. To run the full verification suite, which requires Icarus Verilog, cocotb and a C++20 compiler:

```bash
cd hardware/tests && ./run_all.sh
cd software_prototype/cpp && make check
```

## Author

Saikarthik Ramakrishnan, Electronics and Communication Engineering, Shiv Nadar University, Delhi.
