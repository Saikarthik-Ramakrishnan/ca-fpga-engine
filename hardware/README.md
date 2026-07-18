# Phase 2: ca_cell.v

One cell of the automaton, the hardware twin of `update(alive, neighbors)`
from `golden_rule.py` and the console.

- One register holds state.
- Combinational logic (an 8-input popcount plus a two-line comparison)
  computes the next state.
- A `load`/`seed_bit` path: when `load` is high, the cell takes `seed_bit`
  instead of computing the rule. That's how the grid gets an initial pattern.

## Verification

- Only 2^9 = 512 possible inputs exist (1 current-state bit + 8 neighbor
  bits), so all 512 are checked, not sampled.
- Each is compared against `golden_rule.update()`, the same reference every
  other tier in this project is checked against.
- A second test covers the load path on its own, since the exhaustive test
  holds `load` low throughout.

```bash
cd hardware/tests
make          # all 512 rule cases + the load-path test
```

# Phase 3: ca_grid.v

N cells wired into an actual grid, each connected to its real 8 neighbors,
sharing one clock.

- A `generate` block: a build-time instruction telling the synthesis tool to
  stamp out `ROWS*COLS` physical copies of `ca_cell` and wire each by position.
- Neighbor wrap is toroidal, matching the `%` wraparound in `golden_rule.py`
  and the console.

```
hardware/
├── rtl/
│   ├── ca_cell.v          # one cell
│   ├── ca_grid.v          # N cells wired into a grid
│   ├── uart_tx.v          # sends one byte over one wire
│   ├── uart_rx.v          # receives one byte over one wire
│   ├── seed_loader.v      # turns received bytes into a grid seed
│   ├── grid_streamer.v    # snapshots the grid, feeds bytes to uart_tx
│   └── cellnet_top.v      # the whole chip, flashable as-is
├── host/
│   └── send_seed.py       # PC-side seed sender for the real board
├── synth/                 # resource analysis, pin constraints, netlist checks
└── tests/
    ├── Makefile             # ca_cell only
    ├── Makefile.grid        # ca_cell + ca_grid
    ├── Makefile.uart        # uart_tx only
    ├── Makefile.rx          # uart_rx only
    ├── Makefile.loader      # seed_loader only
    ├── Makefile.loopback    # the whole chip, seed in + frames out
    ├── Makefile.postsynth   # the synthesized netlist, not the RTL
    ├── test_ca_cell.py
    ├── test_ca_grid.py
    ├── test_uart_tx.py            # decodes real bytes off the wire
    ├── test_uart_rx.py            # feeds real bit timing into the wire
    ├── test_seed_loader.py        # protocol, byte order, timeout recovery
    ├── test_cellnet_loopback.py   # full loop through the chip's real pins
    └── demos/               # capture + render a live run as a GIF
```

## Verification

- An 8x8 grid has 2^64 possible states, so exhaustive testing is off the table.
- Instead: four random starting patterns at different densities, each run
  forward 15 generations.
- The entire grid is checked against `golden_rule.step_golden()` after every
  single generation, not only at the end. That pins down exactly which step a
  divergence happens on.
- All four trials passed on the first run. The toroidal wraparound math and
  neighbor bit-packing were correct on the first attempt.

```bash
cd hardware/tests
make -f Makefile.grid
```

## What synthesis actually costs

- An earlier estimate here capped the grid at ~17x17 to ~22x22, based on a
  measured ~66 LUT4-equivalents per cell. That number was correct, and it was
  measuring a badly mapped circuit.
- `synth_gowin`'s default mapping builds a tree of wide muxes (costing 2, 4,
  and 8 LUT4s each) for the neighbor-count comparison, dominating the design.
- `-nowidelut` forbids that mapping: **~13.6 LUT4 per cell, a 4.9x saving**,
  verified at every grid size.
- Real ceiling is **38x38** (95% of LUT budget), not 22x22. 32x32 sits at 67%
  and is the safer first target to flash.
- Verified behavior-preserving, not just smaller: the grid testbench passes
  against the actual synthesized gate-level netlist, using Gowin's own
  primitive models.
- Critical path is 11 logic levels, independent of grid size. A bigger grid
  costs area, not clock speed.

Full methodology and numbers: [`hardware/synth/README.md`](synth/README.md).

# Phase 4: uart_tx.v, grid_streamer.v, cellnet_top.v

Getting live grid data off the chip.

- `uart_tx.v`: sends one byte at a time, standard UART framing (start bit, 8
  data bits LSB-first, stop bit).
- `grid_streamer.v`: snapshots the grid, sends a fixed sync byte (`0xAA`)
  followed by the grid packed into bytes, then immediately grabs a fresh
  snapshot and repeats. The grid can change every clock cycle but sending one
  snapshot takes many, so it never tries to report every generation. It
  reports whatever is current the instant it's free to send again.
- `cellnet_top.v`: wires `ca_grid` into `grid_streamer` into `uart_tx`. The
  whole chip, the actual pins a real board would expose.

## Verification

- `test_uart_tx.py` sends 8 known bytes (including `0x00`, `0xFF`, `0x01`,
  `0x80`) and decodes each straight off the simulated wire the way a real
  receiver would: wait for the line to fall, sample the middle of each bit
  period. All 8 matched.
- The original `test_cellnet_top.py` seeded the grid through a test-only port
  and verified every decoded frame against `golden_rule.step_golden()`. Phase
  4.5 removed that port, so the test was retired and superseded by
  `test_cellnet_loopback.py`, which proves strictly more: the same frame
  checking, but seeded over the real UART wire.

```bash
cd hardware/tests
make -f Makefile.uart       # uart_tx alone
make -f Makefile.loopback   # the whole chip, end to end
```

## Watching it run

`hardware/tests/demos/` captures real decoded UART frames from a live
simulation run and renders them into a GIF, styled like the console.

- Not a correctness test, just a way to watch Phase 4 work.
- Every frame comes from decoding `tx_serial` bit by bit, the same way a real
  PC receiver would, not from reading the simulated grid's internal state.

```bash
cd hardware/tests/demos
make -f Makefile.demo
python3 render_capture.py
```

Writes `phase4_live_capture.gif` into `hardware/tests/demos/`. The Live tab in
`cellnet_console.html` also loads the resulting `uart_capture.json` directly.

# Phase 4.5: uart_rx.v, seed_loader.v, and a flashable cellnet_top.v

Closing the loop. Until now data only flowed off the chip; the grid was
seeded through a test-only input port that no real board exposes. Phase
4.5 makes the chip listen on the other UART wire, which removes the last
test-only port: `cellnet_top.v` now has exactly the pins the Tang Primer
20K dock physically has (27 MHz clock, reset key, two UART wires, two
LEDs) and can be flashed as-is with the constraints in
`hardware/synth/cellnet_primer20k.cst`. Pin numbers were taken from
Sipeed's own example projects for this dock, not guessed.

- `uart_rx.v`: receives one byte, the mirror of `uart_tx.v`, plus the two
  problems only a receiver has: a 2-flop synchronizer because the wire is
  asynchronous to our clock, and mid-bit sampling with start-bit
  confirmation so glitches and framing errors get dropped instead of
  decoded as garbage.
- `seed_loader.v`: the protocol. One `0x55` command byte, then a full
  grid snapshot in the exact byte order `grid_streamer.v` sends frames
  out (byte 0 = grid bits [7:0]). A stalled transfer times out and is
  abandoned cleanly, so a pulled cable can never wedge the chip.
- The generation pacer in `cellnet_top.v`: at 27 MHz the grid would run
  27 million generations a second, so the chip deliberately idles between
  steps. Instead of adding an enable pin to the exhaustively verified
  `ca_cell`, the pacer reuses its existing load path: feeding the grid's
  own state back through `seed` with `load` high freezes it in place, and
  dropping `load` for exactly one clock computes exactly one generation.
  `GEN_DIV` sets the rate (default 10 gen/s).

## Verification

- `test_uart_rx.py`: all 256 byte values sent back-to-back at exact bit
  timing, a sub-bit glitch that must not decode, and a framing-broken
  byte that must be dropped with clean recovery after. All pass.
- `test_seed_loader.py`: byte-order correctness against the streamer
  convention, noise ignored before the command byte (including `0xAA`,
  which must never be mistaken for a command), timeout mid-transfer with
  clean recovery, and back-to-back seeds. All pass.
- `test_cellnet_loopback.py`: the chip exercised only through its real
  pins. Frames before any seed must be all-zero; then a glider is
  bit-banged in over `rx_serial` and every frame decoded off `tx_serial`
  must match some generation of the golden model, in order (17 frames,
  generations 0 through 36 in the committed run); then a mid-run reseed
  with a blinker must take over the stream and visibly oscillate.
- The loopback test caught a real sampling alias on its first run: with
  the generation period an exact divisor of the frame period, every frame
  latched the same blinker phase and a period-2 oscillator looked frozen.
  The sim parameters now keep the two periods non-commensurate, and the
  same reasoning applies when picking `GEN_DIV` for hardware.

```bash
cd hardware/tests
make -f Makefile.rx
make -f Makefile.loader
make -f Makefile.loopback
```

One tooling note: each suite now builds in its own `sim_build_*`
directory. cocotb only rebuilds when RTL sources change, not when
Makefile parameters do, so suites sharing one build directory can
silently run a stale binary with old parameters. That exact failure
happened twice while building this phase.

## What the full chip costs

Measured with `hardware/synth/measure_top.py`, same LUT4-equivalent
accounting as before, `-nowidelut` throughout. Phase 4.5 is not free per
cell: the seed loader holds a full grid snapshot (one extra register per
cell) and the pacer's hold path puts a real mux behind every cell's seed
input.

| grid  | bare grid LUT4 | full chip LUT4 | delta/cell | FF   | budget used | fits |
|-------|----------------|----------------|------------|------|-------------|------|
| 8x8   | 874            | 1,951          | 16.8       | 343  | 9.4%        | yes  |
| 16x16 | 3,476          | 5,652          | 8.5        | 923  | 27.3%       | yes  |
| 24x24 | 7,830          | 11,675         | 6.7        | 1,885| 56.3%       | yes  |
| 32x32 | 13,924         | 20,189         | 6.1        | 3,231| 97.4%       | yes  |

So the flashable ceiling by the pre-route LUT4-equivalent accounting is
32x32 at 97.4%. Actual place and route (Phase 5a) came in kinder: nextpnr
maps the adder trees onto the chip's dedicated ALU carry cells, so the
routed 32x32 uses 72% of LUT4s plus 27% of ALUs and still closes timing
at 176 MHz. Both accountings are reported because they answer different
questions; the routed numbers are the ones that bind. The 38x38 figure
from the Phase 4 analysis still stands, but only for the bare fabric
without the seed path. 16x16 is the default build and the sensible first
flash.

## Talking to the real board

```bash
# seed the flashed board from the PC
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --pattern glider --rows 16 --cols 16
```

The console's Live tab does the same job in the browser: connect over
Web Serial, pick a pattern, Send Seed, and watch the pattern's evolution
stream back onto the board. Same `0x55` protocol, byte-for-byte what the
loopback test verified.

# Phase 5a: a real bitstream, no vendor tools

The full RTL-to-bitstream flow now runs on the open toolchain: Yosys
synthesis (`-nowidelut`, as always), nextpnr-himbaechel place and route
with Apicula's GW2A-18 support, and `gowin_pack` to the final `.fs`.
One script does all three and refuses to hand over a bitstream that
misses timing:

```bash
cd hardware
./synth/build_bitstream.sh          # 16x16 default
./synth/build_bitstream.sh 24 24    # any size
```

The shipped 16x16 build placed, routed, and closed timing with a
reported Fmax of 240.38 MHz against the 27 MHz dock clock, a margin of
almost 9x. That number is nextpnr's post-route static timing analysis,
not an estimate. The prebuilt bitstream lives in
`bitstreams/cellnet_16x16_tangprimer20k.fs.gz` (the `.fs` format is
ASCII bits, so it compresses 45:1), and `FLASHING.md` walks through
loading it, what the LEDs and the serial stream should look like, and
how to seed the running chip from `send_seed.py` or the console's Live
tab. The 32x32 ceiling build was also placed and routed: 72% LUT4, 27% ALU,
20% FF, Fmax 176.46 MHz, and its bitstream ships alongside the 16x16.
The only step left in Phase 5 that needs anything other than this repo
is plugging the board in.
