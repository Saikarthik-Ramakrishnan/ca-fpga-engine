# Massively Parallel Cellular Automaton Engine

[![verify](https://github.com/Saikarthik-Ramakrishnan/ca-fpga-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Saikarthik-Ramakrishnan/ca-fpga-engine/actions/workflows/ci.yml)

Cellular automaton engine for parallel hardware. Every cell is an independent
logic unit; all cells update on the same clock edge. The target output is an
electromechanical flip-dot display.

![CELL·NET console running a Gosper glider gun](docs/media/cellnet_demo.gif)

## Why an FPGA

- A cell's next state depends on itself and its eight neighbors only.
- CPUs and GPUs visit cells in batches. An FPGA stamps the rule down once per
  cell as combinational logic; every cell updates simultaneously.
- Flip-dot displays extend the same structure into hardware: one bistable
  coil-driven disc per cell, zero standing power after a flip.

## What the parallelism is worth

Measured against a C++20 laptop engine that packs 64 cells into each machine word, on an Apple M2 Pro. The FPGA side is cycle-accurate RTL simulation converted at the 27 MHz dock clock; the board has not been measured yet.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="software_prototype/cpp/results/laptop_vs_fpga_dark.png">
  <img alt="Throughput against grid size, and per-generation latency at 16x16, laptop against FPGA fabric" src="software_prototype/cpp/results/laptop_vs_fpga.png">
</picture>

| grid | best laptop | FPGA at 27 MHz | FPGA at routed Fmax |
|---|---|---|---|
| 8x8 | 19.3 M gen/s | 27 M (1.4x) | not routed |
| 16x16 | 10.4 M gen/s | 27 M (2.6x) | 240 M (23x) |
| 24x24 | 6.72 M gen/s | 27 M (4.0x) | not routed |
| 32x32 | 5.10 M gen/s | 27 M (5.3x) | 176 M (35x) |
| 64x64 to 2048x2048 | 2.47 M to 9.46 k gen/s | does not fit | does not fit |

- The fabric runs one generation per clock at every size it holds. Measured, not assumed: 64 consecutive generations at 8x8, 16x16, 24x24 and 32x32.
- The laptop slows as the grid grows and the fabric does not, so the gap widens with size: 1.4x to 5.3x at the dock clock, 23x to 35x at the routed ceiling.
- Latency is where the two differ most. The fabric takes exactly one clock every generation. The laptop's best threaded run at 16x16 has a p50 of 625 ns and a p99.9 of 10.4 µs.
- The laptop wins on capacity. Past 32x32 the design does not fit this FPGA; six laptop cores keep scaling, 3.9x one core at 2048x2048.
- End to end, the UART sets the pace: 2.86 ms to report a frame against 37 ns to compute a generation.
- **Correction.** An earlier version of this section compared the fabric with the Python ladder's Numba tier and reported 195x at 16x16 and 408x at 32x32. The bit-sliced C++ engine is about 75x faster per core than that tier, and against it the dock-clock factors are 2.6x and 5.3x. The earlier numbers measured how slow the Numba tier is.
- Full tables, methodology and the mutex-versus-barrier costs: [`software_prototype/cpp/results/laptop_vs_fpga.md`](software_prototype/cpp/results/laptop_vs_fpga.md) and [`docs/CONCURRENCY.md`](docs/CONCURRENCY.md).

## Resource summary

Pre-route LUT4-equivalent, `synth_gowin -nowidelut`, Gowin GW2A-18
(20,736 LUT4, 15,552 FF):

| grid | cells | bare grid LUT4 | full chip LUT4 | budget used | fits |
|---|---|---|---|---|---|
| 8x8 | 64 | 874 | 1,951 | 9.4% | yes |
| 16x16 | 256 | 3,476 | 5,652 | 27.3% | yes |
| 24x24 | 576 | 7,830 | 11,675 | 56.3% | yes |
| 32x32 | 1,024 | 13,924 | 20,189 | 97.4% | yes |

Routed, nextpnr post-route static timing analysis, requirement 27 MHz:

| build | Fmax | LUT4 | ALU | FF |
|---|---|---|---|---|
| 16x16 | 240.38 MHz | 19% | 7% | 5% |
| 32x32 | 176.46 MHz | 72% | 27% | 20% |

- 13.6 LUT4-equivalents per cell, consistent at every grid size. `-nowidelut`
  is mandatory: the default mapping costs 66 per cell, a 4.9x difference.
- Bare-fabric ceiling 38x38, full-chip ceiling 32x32, default build 16x16.
- Routed numbers beat the pre-route estimate because nextpnr maps the adder
  trees onto dedicated ALU carry cells. Both accountings are reported;
  the routed one binds.
- Methodology: [`hardware/synth/README.md`](hardware/synth/README.md).
- The configurable-rule fabric has not been measured yet. It needs a yosys
  run: `cd hardware/synth && python3 measure_rule_cost.py`.

## The rule is data, not gates

A bitstream built with `RULE_CFG=1` (the default) holds the rule as two
9-bit masks in a register, settable over UART:

| rule | notation | packet |
|---|---|---|
| Conway | B3/S23 | `33 08 0C 00` |
| HighLife | B36/S23 | `33 48 0C 00` |
| Day & Night | B3678/S34678 | `33 C8 D8 03` |
| Seeds | B2/S | `33 04 00 00` |
| Maze | B3/S12345 | `33 08 3E 00` |

```bash
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --rule highlife --pattern glider
```

- All five rulesets the console ships now run on one bitstream, with no
  rebuild between them.
- The masks are broadcast constants, the same way `clk` and `load` already
  are. They move no information between cells, so the locality thesis is
  untouched: a cell still reads its own state and eight neighbor wires and
  nothing else.
- The chip resets to Conway, so a board nobody sends a rule to behaves
  exactly like the fixed-rule build. `RULE_CFG=0` builds that smaller
  fabric, and the same loopback testbench runs against both.
- Full wire spec: [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Verification

Everything below runs without an FPGA, and all of it checks against `golden_rule.py`, the single reference.

### Hardware: 32 cocotb tests across 14 suites

```bash
cd hardware/tests && ./run_all.sh
```

| suite | what it proves |
|---|---|
| `ca_cell` | all 512 inputs, exhaustive |
| `ca_cell_rule` | 15,360 cases: 512 inputs x 5 rulesets, plus 24 random rule masks x 512 |
| `ca_grid` | 4 seeds x 15 generations vs the golden model |
| `ca_grid_rule` | 300 full-grid comparisons across 5 rulesets, plus a live rule swap |
| `uart_tx`, `uart_rx` | bytes decoded off the simulated wire, glitch and framing errors |
| `seed_loader` | byte order, noise, timeout, back-to-back seeds |
| `rule_loader` | both cross-corruption guards, against the real seed loader |
| `loopback_cfg`, `loopback_fixed` | the chip through real pins only, both fabrics |
| `cellnet_rules` | rule over the wire, rule change mid-run, rule survives a reseed |
| `fabric_latency_16`, `_32` | one generation per clock, measured every clock for 64 generations |
| `link_latency` | seed-in and frame-out timing at the real 115200 baud |
| `postsynth`, `postsynth_rule` | the gate-level netlist, when yosys is present |

### Software: the C++ engine and its concurrency proof

```bash
cd software_prototype/cpp && make check
```

- 15,212,478 checks against `golden_rule.py` vectors, including every 4x4 torus under every row partition, exhaustively.
- The same suite under ThreadSanitizer: 4,724,098 checks, zero race reports.
- Every thread interleaving of small instances enumerated: the barrier protocol is correct on more than 10^20 schedules; removing the barrier or the second buffer makes 12% to 76% of schedules wrong.
- Negative controls that remove each protection in turn, with ThreadSanitizer's verdict beside the actual answer. The tool is wrong in both directions at least once, which is why there is a proof.
- Details, the theorem and its proof: [`docs/CONCURRENCY.md`](docs/CONCURRENCY.md).

### Everywhere

- CI runs all of it on every push: the cocotb suites, the C++ engines optimized and under ThreadSanitizer, the schedule proof, the software ladder's correctness check, the protocol encoders and a headless console check.
- The wire encoding is pinned by three independent implementations: the Verilog testbenches, `hardware/host/protocol.py`, and `software_prototype/check_console.js`.

## Repo structure

```
ca-fpga-engine/
├── README.md
├── .github/workflows/ci.yml         # runs everything on every push
├── docs/
│   ├── PROTOCOL.md                  # the wire protocol, both directions
│   ├── CONCURRENCY.md               # shared state, the proof, the evidence
│   └── media/cellnet_demo.gif
├── software_prototype/
│   ├── cellnet_console.html         # the console
│   ├── check_console.js             # headless jsdom checks
│   ├── cpp/                         # C++20 engines, proof tooling, laptop vs FPGA
│   └── parallelism_ladder/          # five Python tiers plus the fabric tier
├── hardware/
│   ├── rtl/ca_cell.v                  # one cell, fixed Conway
│   ├── rtl/ca_cell_rule.v             # one cell, rule as two 9-bit masks
│   ├── rtl/ca_grid.v                  # N cells, toroidal grid
│   ├── rtl/ca_grid_rule.v             # same fabric, rule broadcast in
│   ├── rtl/uart_tx.v                  # byte out
│   ├── rtl/uart_rx.v                  # byte in
│   ├── rtl/seed_loader.v              # 0x55, UART bytes to grid seed
│   ├── rtl/rule_loader.v              # 0x33, UART bytes to rule masks
│   ├── rtl/grid_streamer.v            # 0xAA, grid snapshots to uart_tx
│   ├── rtl/cellnet_top.v              # full chip, flashable, either fabric
│   ├── host/protocol.py               # the wire encoding, self-testing
│   ├── host/send_seed.py              # PC seed and rule sender
│   ├── bitstreams/                    # prebuilt .fs (gzipped)
│   ├── FLASHING.md                    # board bring-up
│   ├── synth/                         # resource analysis, constraints, build
│   └── tests/                         # cocotb testbenches, run_all.sh
└── LICENSE
```

## Status

| phase | content | status |
|---|---|---|
| 1 | software prototype, console, parallelism ladder | done |
| 2 | `ca_cell.v`, exhaustive 512-input verification | done |
| 3 | `ca_grid.v`, generate fabric, toroidal wrap | done |
| 4 | `uart_tx.v`, `grid_streamer.v`, live capture | done |
| 4.5 | `uart_rx.v`, `seed_loader.v`, pacer, flashable top | done |
| 5a | open-toolchain bitstreams, timing closed at 27 MHz | done |
| 5b | selectable rule over the wire, CI, protocol spec | done in simulation |
| 5b | C++ engine, concurrency proof, measured laptop vs FPGA | done, fabric in simulation |
| 5c | flash the board, close the loop against the console | needs the board |
| 6 | flip-dot driver stage | later |

Everything through 5b is verified in simulation and needs no FPGA. 5c is the
first step that does.

## Motivation

- Second-year follow-up to an FPGA MNIST inference accelerator.
- Uses the FPGA for fine-grained parallelism, matched to an output medium with
  the same one-unit-per-cell structure.

## Author

Saikarthik Ramakrishnan, ECE, Shiv Nadar University Delhi.
