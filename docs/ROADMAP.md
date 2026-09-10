# Project Status and Roadmap

This document records the completed phases of the project and the work that remains.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Software prototype, browser console and software parallelism benchmark | Complete |
| 2 | A single cell in Verilog, verified against all 512 inputs | Complete |
| 3 | The parallel grid with toroidal wrap-around | Complete |
| 4 | Serial transmission of the live grid and a recorded capture | Complete |
| 4.5 | Serial reception, seed loading, generation pacing and a programmable top level | Complete |
| 5a | Bitstreams from the open-source toolchain, with timing met at 27 MHz | Complete |
| 5b | Runtime rule configuration, protocol specification and continuous integration | Complete in simulation |
| 5b | C++ engine, concurrency proof and laptop-to-FPGA measurements | Complete, with the fabric measured in simulation |
| 5c | Programming the board and connecting it to the console | Awaiting hardware |
| 6 | Driver stage for the flip-dot display | Planned |

## Current State

Every phase up to 5b has been verified in simulation and requires no FPGA. Phase 5c is the first step that needs the physical Tang Primer 20K board. It will replace the simulated timing figures with measurements from the running device.

## Next Steps

- Program the board and confirm that the live stream matches the simulation.
- Measure the configurable-rule build's area with the Yosys toolchain.
- Design the coil driver stage for the flip-dot display.
