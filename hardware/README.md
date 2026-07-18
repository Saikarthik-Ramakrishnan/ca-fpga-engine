# Phase 2: ca_cell.v

One cell. Hardware twin of `update(alive, neighbors)` from `golden_rule.py`.

- One state register.
- Combinational next-state logic: 8-input popcount plus comparison.
- `load`/`seed_bit` path: `load` high selects `seed_bit` as the next state.
  Used for pattern injection and, since Phase 4.5, generation pacing.

## Verification

- 2^9 = 512 possible inputs. All 512 checked against `golden_rule.update()`.
- Separate test for the load path.

```bash
cd hardware/tests
make
```

# Phase 3: ca_grid.v

- `generate` block stamps out `ROWS*COLS` copies of `ca_cell`, wired by
  position, one shared clock.
- Toroidal neighbor wrap, matching `golden_rule.py`.

```
hardware/
├── rtl/
│   ├── ca_cell.v          # one cell
│   ├── ca_grid.v          # N cells, toroidal grid
│   ├── uart_tx.v          # byte out
│   ├── uart_rx.v          # byte in
│   ├── seed_loader.v      # UART bytes to grid seed
│   ├── grid_streamer.v    # grid snapshots to uart_tx
│   └── cellnet_top.v      # full chip, flashable
├── host/
│   └── send_seed.py       # PC seed sender
├── bitstreams/            # prebuilt .fs (gzipped)
├── synth/                 # resource analysis, constraints, bitstream build
└── tests/
    ├── Makefile             # ca_cell
    ├── Makefile.grid        # ca_grid
    ├── Makefile.uart        # uart_tx
    ├── Makefile.rx          # uart_rx
    ├── Makefile.loader      # seed_loader
    ├── Makefile.loopback    # full chip, seed in + frames out
    ├── Makefile.postsynth   # gate-level netlist
    ├── test_ca_cell.py
    ├── test_ca_grid.py
    ├── test_uart_tx.py
    ├── test_uart_rx.py
    ├── test_seed_loader.py
    ├── test_cellnet_loopback.py
    └── demos/               # capture + render a live run
```

## Verification

- Four random seeds at different densities, 15 generations each.
- Full grid checked against `golden_rule.step_golden()` after every
  generation, isolating the exact step of any divergence.
- All four trials passed on the first run.

```bash
cd hardware/tests
make -f Makefile.grid
```

## Synthesis cost

- Initial estimate: ~66 LUT4-equivalents per cell, grid capped near 22x22.
  The measured circuit was poorly mapped.
- Cause: `synth_gowin` default maps the count comparison to wide muxes
  (MUX2_LUT5/6/7 at 2/4/8 LUT4 each).
- `-nowidelut`: 13.6 LUT4 per cell, 4.9x saving, consistent at every size.
- Corrected bare-grid ceiling: 38x38 at 95% of budget. 32x32 sits at 67%.
- Gate-level netlist passes the grid testbench with Gowin primitive models.
- Critical path: 11 logic levels, independent of grid size.

Numbers and methodology: [`hardware/synth/README.md`](synth/README.md).

# Phase 4: uart_tx.v, grid_streamer.v

- `uart_tx.v`: one byte, 8N1 framing, LSB first.
- `grid_streamer.v`: latches a grid snapshot, sends sync byte `0xAA` plus the
  packed grid, latches again, repeats. Reports the current state each time the
  line is free; intermediate generations are skipped by design.

## Verification

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

## Demo capture

- `demos/` decodes real frames off `tx_serial` bit by bit and renders a GIF.
- Since Phase 4.5 the demo seeds the chip over `rx_serial` as well.

```bash
cd hardware/tests/demos
make -f Makefile.demo
python3 render_capture.py
```

Outputs `phase4_live_capture.gif` and `uart_capture.json` (loaded by the
console's Live tab).

# Phase 4.5: uart_rx.v, seed_loader.v, flashable cellnet_top.v

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

## Verification

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

## Full-chip cost

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

## Seeding the board

```bash
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --pattern glider --rows 16 --cols 16
```

Console equivalent: Live tab, Connect, Send Seed. Same `0x55` protocol
verified by the loopback test.

# Phase 5a: bitstreams on the open toolchain

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
