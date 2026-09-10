# Repository Layout

This document shows where each part of the project is located.

```
ca-fpga-engine/
├── README.md
├── .github/workflows/ci.yml           continuous integration for every push
├── docs/                              project-level documentation
│   ├── PERFORMANCE.md                 laptop and FPGA measurements
│   ├── CONCURRENCY.md                 shared state, proof and evidence
│   ├── VERIFICATION.md                test suites and what they establish
│   ├── RESOURCES.md                   FPGA area and timing
│   ├── RULE_CONFIGURATION.md          loading the rule at run time
│   ├── PROTOCOL.md                    serial protocol specification
│   └── ROADMAP.md                     status and next steps
├── software_prototype/
│   ├── cellnet_console.html           browser console
│   ├── check_console.js               headless console checks
│   ├── cpp/                           C++20 engine, proof tooling, benchmarks
│   └── parallelism_ladder/            Python reference model and benchmark
└── hardware/
    ├── rtl/                           Verilog: cell, grid, serial interface, top level
    ├── host/                          host-side protocol encoder and seed sender
    ├── synth/                         synthesis scripts, constraints, resource analysis
    ├── tests/                         cocotb testbenches and run_all.sh
    ├── bitstreams/                    prebuilt bitstreams, compressed
    └── FLASHING.md                    board bring-up
```

## Key Hardware Files

| File | Purpose |
|---|---|
| `rtl/ca_cell.v` | A single cell with Conway's rule built into its logic. |
| `rtl/ca_cell_rule.v` | A single cell whose rule is supplied as two 9-bit masks. |
| `rtl/ca_grid.v`, `rtl/ca_grid_rule.v` | The grid of cells with toroidal wrap-around, in each build. |
| `rtl/uart_tx.v`, `rtl/uart_rx.v` | Serial transmission and reception of single bytes. |
| `rtl/seed_loader.v` | Assembles a seed from the serial stream. |
| `rtl/rule_loader.v` | Assembles a rule from the serial stream. |
| `rtl/grid_streamer.v` | Sends snapshots of the grid to the host. |
| `rtl/cellnet_top.v` | The complete chip, in either build. |
