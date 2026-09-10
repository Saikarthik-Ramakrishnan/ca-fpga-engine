# Hardware Design and Verification

This document describes how the chip is built, one phase at a time, from a single cell to the complete programmable design, together with the tests that verify each stage.

## Phase 2: ca_cell.v

One cell. Hardware twin of `update(alive, neighbors)` from `golden_rule.py`.

- One state register.
- Combinational next-state logic: 8-input popcount plus comparison.
- `load`/`seed_bit` path: `load` high selects `seed_bit` as the next state.
  Used for pattern injection and, since Phase 4.5, generation pacing.

### Verification

- 2^9 = 512 possible inputs. All 512 checked against `golden_rule.update()`.
- Separate test for the load path.

```bash
cd hardware/tests
make
```

## Phase 3: ca_grid.v

- `generate` block stamps out `ROWS*COLS` copies of `ca_cell`, wired by
  position, one shared clock.
- Toroidal neighbor wrap, matching `golden_rule.py`.

```
hardware/
├── rtl/
│   ├── ca_cell.v            # one cell, fixed Conway
│   ├── ca_cell_rule.v       # one cell, rule as two 9-bit masks
│   ├── ca_grid.v            # N cells, toroidal grid
│   ├── ca_grid_rule.v       # same fabric, rule broadcast in
│   ├── uart_tx.v            # byte out
│   ├── uart_rx.v            # byte in
│   ├── seed_loader.v        # 0x55, UART bytes to grid seed
│   ├── rule_loader.v        # 0x33, UART bytes to rule masks
│   ├── grid_streamer.v      # 0xAA, grid snapshots to uart_tx
│   └── cellnet_top.v        # full chip, flashable, either fabric
├── host/
│   ├── protocol.py          # the wire encoding, self-testing
│   └── send_seed.py         # PC seed and rule sender
├── bitstreams/              # prebuilt .fs (gzipped)
├── synth/                   # resource analysis, constraints, bitstream build
└── tests/
    ├── run_all.sh             # every suite, one command
    ├── Makefile               # ca_cell
    ├── Makefile.cellrule      # ca_cell_rule
    ├── Makefile.grid          # ca_grid
    ├── Makefile.gridrule      # ca_grid_rule
    ├── Makefile.uart          # uart_tx
    ├── Makefile.rx            # uart_rx
    ├── Makefile.loader        # seed_loader
    ├── Makefile.ruleloader    # rule_loader vs seed_loader, shared byte stream
    ├── Makefile.loopback      # full chip, configurable fabric
    ├── Makefile.loopback_fixed# full chip, fixed-Conway fabric
    ├── Makefile.rules         # rule over the wire, end to end
    ├── Makefile.postsynth     # gate-level netlist
    ├── Makefile.postsynth_rule# gate-level netlist, configurable fabric
    ├── tb_command_stack.v     # sim harness for the two loaders
    ├── test_*.py
    └── demos/                 # capture + render a live run
```

### Verification

- Four random seeds at different densities, 15 generations each.
- Full grid checked against `golden_rule.step_golden()` after every
  generation, isolating the exact step of any divergence.
- All four trials passed on the first run.

```bash
cd hardware/tests
make -f Makefile.grid
```

### Synthesis cost

- Initial estimate: ~66 LUT4-equivalents per cell, grid capped near 22x22.
  The measured circuit was poorly mapped.
- Cause: `synth_gowin` default maps the count comparison to wide muxes
  (MUX2_LUT5/6/7 at 2/4/8 LUT4 each).
- `-nowidelut`: 13.6 LUT4 per cell, 4.9x saving, consistent at every size.
- Corrected bare-grid ceiling: 38x38 at 95% of budget. 32x32 sits at 67%.
- Gate-level netlist passes the grid testbench with Gowin primitive models.
- Critical path: 11 logic levels, independent of grid size.

Numbers and methodology: [`hardware/synth/README.md`](synth/README.md).

## Phase 4: uart_tx.v, grid_streamer.v

- `uart_tx.v`: one byte, 8N1 framing, LSB first.
- `grid_streamer.v`: latches a grid snapshot, sends sync byte `0xAA` plus the
  packed grid, latches again, repeats. Reports the current state each time the
  line is free; intermediate generations are skipped by design.

### Verification

- `test_uart_tx.py`: 8 known bytes (`0x00`, `0xFF`, `0x01`, `0x80` included)
  decoded off the simulated wire with mid-bit sampling. All matched.
- The Phase 4 top-level test seeded through a test-only port. Phase 4.5
  removed that port; `test_cellnet_loopback.py` supersedes it and covers a
  strict superset.

```bash
cd hardware/tests
make -f Makefile.uart
make -f Makefile.loopback
```

### Demo capture

- `demos/` decodes real frames off `tx_serial` bit by bit and renders a GIF.
- Since Phase 4.5 the demo seeds the chip over `rx_serial` as well.

```bash
cd hardware/tests/demos
make -f Makefile.demo
python3 render_capture.py
```

Outputs `phase4_live_capture.gif` and `uart_capture.json` (loaded by the
console's Live tab).

## Phase 4.5: uart_rx.v, seed_loader.v, flashable cellnet_top.v

- `cellnet_top.v` exposes exactly the Tang Primer 20K dock pins: 27 MHz
  clock, reset key, two UART wires, two LEDs. Zero test-only ports.
- Pin constraints: `synth/cellnet_primer20k.cst`. Pin numbers sourced from
  Sipeed's example projects for this dock.
- `uart_rx.v`: 2-flop synchronizer, mid-bit sampling with start-bit
  confirmation. Glitches and framing errors are dropped.
- `seed_loader.v`: protocol is command byte `0x55` plus a full grid snapshot,
  byte 0 = grid bits [7:0], identical ordering to `grid_streamer.v`. Stalled
  transfers time out and reset the loader.
- Generation pacer: `load` held high with `seed = grid_state` freezes the
  grid; `load` dropped for one clock computes one generation. `GEN_DIV` sets
  the rate, default 10 gen/s at 27 MHz. `ca_cell` is unchanged.

### Verification

- `test_uart_rx.py`: 256 byte values back-to-back at exact bit timing,
  sub-bit glitch rejection, framing-error drop with recovery. 3/3.
- `test_seed_loader.py`: byte order, noise rejection before the command
  (`0xAA` included), mid-transfer timeout with recovery, back-to-back
  seeds. 4/4.
- `test_cellnet_loopback.py`: chip driven through real pins only. Pre-seed
  frames all zero; glider bit-banged in over `rx_serial`; 17 decoded frames
  matched golden generations 0 to 36 in order; mid-run blinker reseed took
  over the stream and oscillated. 1/1.
- Bug found by the loopback test: with the generation period an exact divisor
  of the frame period, every frame latched the same blinker phase. Sim
  periods are now non-commensurate. Same constraint applies when choosing
  `GEN_DIV` for hardware.
- Tooling: each suite builds in its own `sim_build_*` directory. cocotb skips
  rebuilds when only Makefile parameters change; shared build directories ran
  stale binaries twice during this phase.

```bash
cd hardware/tests
make -f Makefile.rx
make -f Makefile.loader
make -f Makefile.loopback
```

### Full-chip cost

`synth/measure_top.py`, LUT4-equivalent accounting, `-nowidelut`. Per-cell
overhead above the bare grid: one seed-snapshot register plus the pacer's
hold mux.

| grid  | bare grid LUT4 | full chip LUT4 | delta/cell | FF   | budget used | fits |
|-------|----------------|----------------|------------|------|-------------|------|
| 8x8   | 874            | 1,951          | 16.8       | 343  | 9.4%        | yes  |
| 16x16 | 3,476          | 5,652          | 8.5        | 923  | 27.3%       | yes  |
| 24x24 | 7,830          | 11,675         | 6.7        | 1,885| 56.3%       | yes  |
| 32x32 | 13,924         | 20,189         | 6.1        | 3,231| 97.4%       | yes  |

- Pre-route accounting puts the full-chip ceiling at 32x32 (97.4%).
- Routed numbers (Phase 5a): 32x32 uses 72% LUT4 + 27% ALU. nextpnr maps the
  adder trees onto dedicated ALU carry cells.
- 38x38 applies to the bare fabric without the seed path.
- Default build: 16x16.

### Seeding the board

```bash
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --pattern glider --rows 16 --cols 16
```

Console equivalent: Live tab, Connect, Send Seed. Same `0x55` protocol
verified by the loopback test.

## Phase 5a: Bitstreams on the Open Toolchain

Flow: Yosys `synth_gowin -nowidelut`, nextpnr-himbaechel (Apicula GW2A-18),
`gowin_pack`. One script runs all three and fails if 27 MHz timing is missed.

```bash
cd hardware
./synth/build_bitstream.sh          # 16x16 default
./synth/build_bitstream.sh 24 24    # any size
```

Results, nextpnr post-route static timing analysis:

| build | Fmax | LUT4 | ALU | FF |
|---|---|---|---|---|
| 16x16 | 240.38 MHz | 19% | 7% | 5% |
| 32x32 | 176.46 MHz | 72% | 27% | 20% |

- Requirement: 27 MHz. Both builds pass.
- Prebuilt bitstreams: `bitstreams/*.fs.gz`. The `.fs` format is ASCII bits;
  gzip ratio 45:1.
- Bring-up procedure: [`FLASHING.md`](FLASHING.md).
- Remaining Phase 5 dependency: the physical board.

## Phase 5b: Runtime Rule Configuration

The rule was two comparators welded into `ca_cell.v`. It is now 18 bits in a
register, loadable over the same UART the seeds arrive on, so all five
rulesets the console ships run on one bitstream.

- `ca_cell_rule.v`: the rule as two 9-bit masks. `birth[k]` means a dead cell
  with k live neighbors becomes alive; `survive[k]` means a live cell with k
  live neighbors stays alive. Conway is `birth = 9'b000001000`,
  `survive = 9'b000001100`.
- `ca_grid_rule.v`: the Phase 3 fabric with those masks broadcast to every
  cell.
- `rule_loader.v`: command byte `0x33` plus 3 payload bytes.
- `cellnet_top.v` parameter `RULE_CFG` picks the fabric. 1 is the default and
  builds the configurable one; 0 builds the original fixed-Conway chip.

Why this does not break the locality thesis:

- `birth` and `survive` are broadcast constants, in the same sense `clk`,
  `rst_n` and `load` already are. They carry no information about any other
  cell.
- No shared accumulator, no global reduction, no sequential scan. A cell
  still reads its own state and eight neighbor wires, and the whole grid
  still resolves on one clock edge.
- `ca_cell.v` is untouched. It passed exhaustive 512-input verification and
  remains the smallest cell to build when only Life is needed.

### Sharing one byte stream between two loaders

`seed_loader` and `rule_loader` both watch the same `rx_dv`/`rx_byte` pair,
so each has to stay out of the other's payload. Two symmetric guards:

1. `rule_loader` recognises `0x33` only while `seed_loader` reports it is not
   mid-transfer. A `0x33` inside a grid seed is data.
2. While `rule_loader` consumes its three payload bytes it raises
   `consuming`, and `cellnet_top` gates `rx_dv` away from `seed_loader`. A
   `0x55` inside a rule payload never reaches the seed loader.

That keeps `seed_loader.v` byte-for-byte unchanged and still covered by its
own testbench, and keeps a second command out of a verified module.

### Verification

- `test_ca_cell_rule.py`: 512 inputs x 5 rulesets = 2,560 cases, plus 24
  random rule masks over the full 18-bit space x 512 inputs = 12,288 more.
  15,360 cases, all matched `golden_rule.update_masked()`. Corners 0 and
  0x1FF forced in. 4/4.
- `test_ca_grid_rule.py`: 5 rulesets x 4 seed densities x 15 generations =
  300 full-grid comparisons, plus a mid-run mask swap asserting the grid does
  not move on the swap and follows the new rule from the next generation.
  3/3.
- `test_rule_loader.py`: both guards above, checked against the real
  `seed_loader` instance itself, plus byte order, reset
  default, noise rejection and timeout recovery. 6/6.
- `test_cellnet_rules.py`: the chip through real pins only. Rule over the
  wire then a seed; rule changed mid-run with no reseed; rule survived a
  reseed. 3/3.
- `test_cellnet_loopback.py` now runs against both fabrics
  (`Makefile.loopback` and `Makefile.loopback_fixed`) unchanged, which is
  what makes "a chip nobody sends a rule to behaves like the old one" a
  checked claim.

```bash
cd hardware/tests
./run_all.sh          # all 14 suites, 32 tests
```

### Cost

Not measured yet. The configurable cell replaces two comparators with a
2-to-1 mux over 9 bits feeding a 9-to-1 mux; the popcount adder tree that
dominates the cell is identical in both. That predicts a small per-cell
delta, and prediction is not measurement:

```bash
cd hardware/synth && python3 measure_rule_cost.py    # needs yosys
```

No resource or Fmax figure for `RULE_CFG=1` appears anywhere in this repo
until that script has been run on a machine with the toolchain.

### Protocol

Full wire spec, both directions, with packet vectors:
[`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

The encoding is pinned by three independent implementations that assert the
same vectors: the cocotb testbenches, `host/protocol.py` (`python3
protocol.py` self-tests it) and `software_prototype/check_console.js`.

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request:

- all 14 cocotb suites against Icarus Verilog on a clean runner, including
  the two cycle-accurate timing measurements,
- the software ladder's correctness check against `golden_rule.py`,
- the protocol encoders' self-test,
- a headless jsdom check of the console,
- the C++ engines against `golden_rule.py`, optimized and under
  ThreadSanitizer, plus the exhaustive schedule proof
  ([`docs/CONCURRENCY.md`](../docs/CONCURRENCY.md)).

None of it needs an FPGA. What it catches that a local run does not: a
testbench passing only because of a stale `sim_build_*` directory, a Python
version assumption, or an RTL file edited but never added to a Makefile's
sources.

## Phase 5b: Fabric Timing Measurements

The laptop-vs-FPGA comparison needs the FPGA's latency as a number that was
measured directly. Two cycle-accurate testbenches supply it, both
against the real `cellnet_top`. Board timing (Phase 5c) is still to come;
everything below is RTL simulation, reported in clocks and converted at the
27 MHz dock oscillator.

### Generation latency: `test_fabric_latency.py`

- `GEN_DIV=1`, so the pacer never holds the grid and the rule runs every clock.
- A soup is seeded over `rx_serial` with `hardware/host/protocol.py`'s encoder
  and the proven bit codec.
- From the clock the seed lands, the design advances one clock at a time and
  the test counts clocks until `grid_state` equals `golden_rule.py`'s next
  generation, for 64 generations in a row.
- White-box by necessity: frames on `tx_serial` skip generations by design,
  so per-clock state exists only inside. The loopback tests cover pins-only.

| build | generations measured | clocks per generation | time at 27 MHz |
|---|---|---|---|
| 8x8 | 64 | 1 every time | 37.04 ns |
| 16x16 | 64 | 1 every time | 37.04 ns |
| 24x24 | 64 | 1 every time | 37.04 ns |
| 32x32 | 64 | 1 every time | 37.04 ns |

- One generation per clock at every build size, zero jitter across the
  window. This is the "one clock edge" claim, now a measurement.

### Link latency: `test_link_latency.py`

- The real 16x16 build: `CLKS_PER_BIT=234` (115200 baud from 27 MHz),
  deployed `GEN_DIV`, pins only.

| quantity | clocks | time at 27 MHz |
|---|---|---|
| seed transfer in (33 bytes) | 77,220 | 2.860 ms |
| frame period out | 77,320 | 2.864 ms (349 frames/s) |
| seed to first frame carrying it, measured | 77,299 | 2.863 ms |

- The frame period was identical on every frame observed.
- Seed-to-frame depends on where in a frame the seed lands: between one and
  two frame periods, less about one bit time. The first version of this test
  asserted exactly one to two periods and failed at period minus 21 clocks.
  The measurement was right and the bound was wrong: `uart_rx` samples
  mid-bit, so the chip has the last seed byte half a bit before its stop bit
  ends, and the test's frame timestamp is half a bit before the
  transmitter's frame boundary. The bound now includes that offset and the
  test says why.
- The fabric computes a generation in 37 ns; the link needs 2.86 ms to report
  one. End-to-end latency is set by the UART, by a factor of 77,320.

```bash
cd hardware/tests
make -f Makefile.fabric_latency ROWS=16 COLS=16   # and 8, 24, 32
make -f Makefile.link_latency
```

Both run in `run_all.sh` and CI. The comparison against the laptop is in
[`software_prototype/cpp/results/laptop_vs_fpga.md`](../software_prototype/cpp/results/laptop_vs_fpga.md).

