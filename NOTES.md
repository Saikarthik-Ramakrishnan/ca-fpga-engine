# CELL-NET Handoff Notes

These notes are for a Claude instance that has this repository but not the conversation that produced it. They cover the state as of 2026-09-24, the tip of `main` at commit `63bb850`.

## 1. What the project is and where it stands

CELL-NET is a cellular automaton engine for the Sipeed Tang Primer 20K (Gowin GW2A-LV18PG256C8/I7). Every cell is its own circuit and the whole grid advances one generation per clock edge. A browser console or a Python script drives it over UART, and a multithreaded C++20 engine serves as the laptop baseline.

- **Works on hardware:** nothing has been confirmed. The board has never been programmed. The user does not have it yet.
- **Works in simulation:** every RTL module, the full chip through its real pins, and gate-level simulation of the synthesized 8x8 grid netlist (fixed and configurable). All 16 cocotb suites (34 tests) and the 2 gate-level suites pass locally and in CI.
- **Built but untested:** bitstreams exist in `hardware/bitstreams/` and are attached to GitHub releases, but have never been loaded onto a board. The configurable-rule chip (`RULE_CFG=1`, the default) has never been placed and routed.

## 2. Architecture

### RTL (`hardware/rtl/`)

| File | Module | What it does |
|---|---|---|
| `ca_cell.v` | `ca_cell` | One cell. Takes 8 separate neighbour wires, counts them inside the cell, and applies Conway B3/S23 in gates. `load`/`seed_bit` overwrite the state. Has no enable pin. |
| `ca_cell_rule.v` | `ca_cell_rule` | The same cell, but it looks the rule up from two 9-bit masks, `birth` and `survive`. |
| `ca_grid.v` | `ca_grid` | A `generate` grid of `ca_cell`, `ROWS` x `COLS`, with toroidal wrap. |
| `ca_grid_rule.v` | `ca_grid_rule` | The same grid built from `ca_cell_rule`. The masks are broadcast to every cell. |
| `uart_rx.v` | `uart_rx` | 8N1 receiver: a 2-flop synchronizer, then mid-bit sampling. A byte whose stop bit is low is dropped silently. |
| `uart_tx.v` | `uart_tx` | 8N1 transmitter, LSB first, with a `tx_busy` handshake. |
| `seed_loader.v` | `seed_loader` | Waits for `0x55`, collects `NUM_BYTES` payload bytes, then pulses `load` for one clock. Abandons a stalled transfer after `TIMEOUT_CLKS`. |
| `rule_loader.v` | `rule_loader` | Waits for `0x33` (only while `seed_busy` is low) and collects 3 bytes into `birth`/`survive`. Raises `consuming` while doing so. Resets to Conway. |
| `grid_streamer.v` | `grid_streamer` | Latches a snapshot of the grid, sends `0xAA` then the payload, and repeats forever. |
| `cellnet_top.v` | `cellnet_top` | The full chip. It contains the generation pacer and `RULE_CFG` selects which fabric is built. Ports are the real pins only. |

`cellnet_top` parameters and defaults: `ROWS=16`, `COLS=16`, `CLKS_PER_BIT=234` (27 MHz / 115200), `GEN_DIV=2700000` (10 generations/s), `TIMEOUT_CLKS=2700000` (about 100 ms), `RULE_CFG=1`.

Pins (`hardware/synth/cellnet_primer20k.cst`): clk H11, rst_n T5, tx_serial M11, rx_serial T13, led[0] L16, led[1] L14. The LEDs are assumed active low.

### Data flow

```
PC --rx_serial--> uart_rx --+--> seed_loader --(load, seed)--> ca_grid / ca_grid_rule
                            +--> rule_loader --(birth, survive)-->      |
PC <--tx_serial-- uart_tx <---- grid_streamer <----- grid_state --------+
```

- `seed_loader` receives `rx_dv && !rule_consuming`, so rule payload bytes never reach it.
- **Generation pacer:** `grid_load = seed_load || !gen_tick` and `grid_seed = seed_load ? seed_data : grid_state`. The grid reloads its own state every clock, which holds it still, except on the one `gen_tick` clock in every `GEN_DIV`. A seed takes priority and restarts the counter.
- **LEDs:** `led[0]` latches on after the first accepted seed or rule command. `led[1]` is lit while a transfer is in progress.

### UART protocol (full spec in `docs/PROTOCOL.md`)

- 115200 baud, 8N1.
- Cell `(r, c)` is bit `r*COLS + c`. Payload byte 0 carries bits `[7:0]`, byte 1 carries `[15:8]`, and so on. `ROWS*COLS` must be a multiple of 8.
- **SEED**, PC to chip: `0x55 P0 .. P(N-1)`, where `N = ROWS*COLS/8`. That is 32 payload bytes at 16x16.
- **RULE**, PC to chip: `0x33 B S X`. `B = birth[7:0]`, `S = survive[7:0]`, `X = {6'b0, survive[8], birth[8]}`. Conway is `33 08 0C 00`.
- **FRAME**, chip to PC: `0xAA P0 .. P(N-1)`, repeated continuously. A 16x16 frame is 33 bytes.

### Grid sizes

- The default build is 16x16.
- The fixed-rule chip was placed and routed at 16x16 and 32x32.
- The configurable-rule chip fits up to 25x25 by pre-route estimate (section 7).

### Software

- `software_prototype/parallelism_ladder/golden_rule.py` is the reference model. `step_golden_masked` holds the rule, and `RULES` holds the 5 rulesets: conway, highlife, daynight, seeds, maze. The other files in that directory are the Python tiers from Phase 1. `tier6_fabric.py` prints a caveat that its baseline is Numba.
- `software_prototype/cellnet_console.html` is a single-file browser console with four tabs: Engine, Wildfire, Live and Displays. The Live tab replays captures and connects to the board over Web Serial. `software_prototype/check_console.js` checks it headlessly under jsdom.
- `hardware/host/protocol.py` holds the wire encoders and runs a self-test (`python3 protocol.py`). `hardware/host/send_seed.py` sends seeds and rules. Its flags are `--port --pattern --rule --rows --cols --density --watch --baud --dry-run`.
- `software_prototype/cpp/` is the C++20 engine. It has two kernels (`scalar`, `bitslice`) and four synchronization methods (`serial`, `mutex`, `barrier` using `std::barrier`, and `atomic` using the hand-written `AtomicBarrier` in `include/cellnet/engines.hpp`). The shared-state table is in the header comment of `engines.hpp`.

## 3. Design decisions and why

Older decisions, from the code and docs:

- **Neighbours arrive as 8 wires.** The count is computed inside the cell so the wiring matches the physical grid.
- **`ca_cell` has no enable pin.** The pacer freezes the grid through the existing load path so the exhaustively verified cell never changed. `ca_cell.v` was also left untouched when the configurable rule was added, and `ca_cell_rule.v` was added beside it instead.
- **The streamer reports the current state and skips generations.** Reporting every generation over UART is impossible.
- **The rule masks are broadcast constants.** They carry no information between cells, so the locality property is preserved.
- **Two loaders share one byte stream.** A second loader with two guards was chosen over adding a second command to `seed_loader`, which would have reopened a verified module.

Decisions made in this session:

- **Protecting shared data (C++ engine):**
  - Two grid buffers, disjoint row ownership per thread, and one barrier per generation. The grid has no lock.
  - The population count uses a padded private slot per thread (`alignas(128)`), summed in the barrier's completion step.
  - The mutex version is kept only for comparison. It is correct but 13x slower at p50 and 37x slower at p99 than `AtomicBarrier` (16x16, 4 threads, M2 Pro).
- **`AtomicBarrier` was written by hand.** On macOS, ThreadSanitizer reports races on the correct `std::barrier` engine because libc++ implements the arrival tree in the uninstrumented `libc++.dylib`. The gated TSan run therefore uses the mutex and atomic families. `std::barrier` runs separately (`make tsan-stdbarrier`) and does not gate. The Linux CI job reports it clean.
- **Correctness evidence:**
  - A written induction proof (`docs/CONCURRENCY.md`).
  - Exhaustive interleaving exploration (`tools/prove_schedules.py`), which found 0 wrong results over 1.776 x 10^20 schedules for the barrier protocol, and counterexamples for the no-barrier and in-place variants.
  - TSan was judged insufficient on its own: it passes `split_atomic`, which is wrong, and flags `barrier_std`, which is correct.
- **Laptop baseline:**
  - The bit-sliced C++ kernel is about 75x faster per core than the Numba tier. The old headline speedups (195x at 16x16, 408x at 32x32) were computed against Numba and were replaced with 2.6x and 5.3x.
  - FPGA figures are labelled as cycle-accurate simulation everywhere.
- **Serial link rate:**
  - The default stays at 115200 (`CLKS_PER_BIT=234`).
  - 1,000,000 baud (`CLKS_PER_BIT=27`, an exact divisor of 27 MHz) was verified in simulation with a measured receiver margin of about 3.8% fast and 3.6% slow.
  - The default was not changed because it has not been confirmed that the dock's BL616 bridge runs at that rate. Both ends must change together.
  - Rejected: choosing a rate from the round-trip sweep alone. Every divider down to 3 passes that sweep because the testbench sends at exactly the receiver's rate, so it says nothing about margin. `test_baud_tolerance.py` measures the margin.
- **Resource measurement** parses `stat -json` written through `tee -o` to a temp file, with a fallback parser for the older text format.
- **Commit messages:** the user requires GitHub's generic web messages, `Add files via upload` or `Update <file>`, followed by the Co-Authored-By trailer.

## 4. Bugs hit and how they were fixed

Known traps, documented in the code and docs before this session:

- **`synth_gowin` without `-nowidelut`** maps the neighbour-count comparison to MUX2_LUT5/6/7 and multiplies per-cell cost (4.9x with the older Yosys, 3.7x with Yosys 0.69). Every synthesis command must pass `-nowidelut`.
- **`yosys ltp` overreports the critical path** on the full grid, because the torus wraps through every cell. The real depth is 11 logic levels inside one cell.
- **Shared `sim_build` directories** make cocotb run stale binaries when only Makefile parameters change. Every suite has its own `SIM_BUILD`, and parameterized suites include the parameter in the name, for example `sim_build_link_speed_$(CPB)`. Use `./run_all.sh --clean` when in doubt.
- **`GEN_DIV` must not divide the frame period evenly.** If it does, every frame latches the same phase and a period-2 blinker looks frozen. The loopback test caught this.
- **`grid_streamer` tearing race.** Found and fixed by the Phase 4 testbench. The snapshot is latched atomically.
- **`CLKS_PER_BIT` mismatch** between the chip and the host produces garbage with no `0xAA` sync.
- **Toroidal wrap** uses `(r+ROWS-1)%ROWS` and `(r+1)%ROWS` (and the same for columns) in `ca_grid.v`. This matches the `%` wrap in `golden_rule.py`.

Hit during this session:

- **Link latency bound too tight.** `test_link_latency.py` first asserted a seed-to-frame time of 1 to 2 frame periods. The measurement was 21 clocks under one period, because `uart_rx` and the test's receiver both sample mid-bit. The bound is now `[period - bit, 2*period]`, with the reason explained in the test.
- **Yosys 0.69 changed its `stat` text format.** `measure_resources.py` silently returned 0 for everything. Fixed by parsing `stat -json`. The first JSON attempt then broke because stdout log text contains braces, so the JSON is now written to its own file with `tee -q -o`.
- **Gate-level suites skipped silently.** `Makefile.postsynth` and `Makefile.postsynth_rule` hardcoded `/usr/share/yosys/gowin/cells_sim.v`, which only exists under oss-cad-suite, so the suites were skipped under any other install. They now use `$(shell yosys-config --datdir)` and can be overridden with `GOWIN_CELLS_SIM`.
- **`test_baud_tolerance.py` harness errors:**
  - `test_uart_rx.reset()` starts its own `Clock`, so calling it repeatedly stacks clock drivers. The test now uses a local `pulse_reset`.
  - `watch_for_byte` returns in a ReadOnly phase, so the test must `await RisingEdge(dut.clk)` before driving `rx_serial` again. Otherwise it raises "Attempting settings a value during the ReadOnly phase".
- **`run_link_speed.sh` unbound array.** `${failed[@]}` on an empty array failed under `set -u`. It now uses `${failed[@]+"${failed[@]}"}`.
- **TSan exit code on macOS.** The default `abort_on_error=1` turns exit code 66 into SIGABRT 134, so the Makefile sets `TSAN_ENV := abort_on_error=0 exitcode=66`.
- **Stale benchmark binary.** Running `./build/bench` after editing `bench.cpp` without rebuilding produced results missing the atomic family. Run it through `make bench`.
- **Schedule explorer hang.** `prove_schedules.py` on 4x4, 4 threads, in-place ran for more than 9 minutes and was removed from the default set.
- **Rejected pushes.** Pushes were rejected twice because the user was editing `README.md` on GitHub at the same time. Resolved with `git pull --rebase`, keeping the user's wording. Never force-push.

## 5. Correctness rules the code depends on

- **`golden_rule.py` is the only reference.** Do not add a second one.
  - `test_ca_grid.py` and `test_ca_grid_rule.py` compare the entire grid after every generation (4 seeds x 15 generations), and the same testbench runs against the gate-level netlist.
  - `test_ca_cell.py` checks all 512 inputs.
  - The C++ tests use vectors generated from `golden_rule.py` by `tools/gen_vectors.py`. `serial/scalar` is pinned to those vectors and is only then used as the oracle for stress tests and benchmarks.
  - `bench.cpp` refuses to time an engine whose output differs.
- **Never assert that frame N equals generation N.** Tests assert a consistent, non-decreasing assignment of golden generations to frames.
- **One byte order in both directions.** `seed_loader.v`, `grid_streamer.v`, `hardware/host/protocol.py` and the console's Live tab must agree on it.
- **`0x55` (seed), `0x33` (rule) and `0xAA` (sync) are fixed.** `0xAA` must never be accepted as a command.
- **Both ends must use the same `CLKS_PER_BIT`/baud.**
- **Rule and seed are independent registers.** `birth`/`survive` only change on the clock the third rule byte lands.
- **Wire codecs:** `test_uart_tx.receive_uart_byte` and `test_uart_rx.send_uart_byte` are the proven codecs. New tests reuse them instead of writing new ones.
- **Proof assumptions** (in `docs/CONCURRENCY.md`): the kernel writes only rows `[r0, r1)` of the output buffer. Nothing writes the read buffer during a phase. `cur`, generation and trace change only in the barrier completion step.

## 6. Build and run

### Toolchain versions

These are the versions on the user's Mac (Apple M2 Pro), where this session's results were produced:

- Yosys 0.69 (Homebrew)
- Icarus Verilog 13.0
- cocotb 2.0.1
- Python 3.11
- Apple clang 21.0.0
- Node 26

Not installed on this Mac: nextpnr-himbaechel, Apicula/`gowin_pack` and `openFPGALoader`. The routed figures in the repo (240.38 MHz at 16x16, 176.46 MHz at 32x32) came from an earlier oss-cad-suite build. **Uncertain:** which oss-cad-suite version that was.

CI (`.github/workflows/ci.yml`) runs on ubuntu-latest and installs Icarus, cocotb, Yosys from apt, numpy/numba, g++ and jsdom@24. **Uncertain:** the exact apt Yosys version, which may give different LUT counts from 0.69.

### Simulation

```bash
cd hardware/tests
./run_all.sh --clean          # 16 suites, 34 tests, plus gate-level if yosys is on PATH
./run_link_speed.sh           # baud sweep: round trip and receiver tolerance

cd ../synth
python3 emit_netlist.py && RULE=1 python3 emit_netlist.py   # needed for the gate-level suites
```

### Resource estimates (Yosys only)

```bash
cd hardware/synth
python3 measure_resources.py
python3 measure_rule_cost.py --sizes 8 16 24 25 26 32 --json results/rule_cost.json
```

### Synthesis, place and route, bitstream

This needs oss-cad-suite on PATH. It has not been run in this session.

```bash
cd hardware
./synth/build_bitstream.sh                    # 16x16, RULE_CFG=1
./synth/build_bitstream.sh 32 32
RULE_CFG=0 ./synth/build_bitstream.sh 32 32   # fixed Conway
# output: synth/build/cellnet_<R>x<C>[_fixed].fs; fails if 27 MHz timing is missed
```

The script runs `synth_gowin -nowidelut`, then `nextpnr-himbaechel --device GW2A-LV18PG256C8/I7 --vopt family=GW2A-18 --vopt cst=synth/cellnet_primer20k.cst --freq 27`, then `gowin_pack -d GW2A-18`.

### Programming the board (untested, from `hardware/FLASHING.md`)

```bash
openFPGALoader -b tangprimer20k cellnet_16x16.fs      # SRAM, volatile
openFPGALoader -b tangprimer20k -f cellnet_16x16.fs   # flash, persistent
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --pattern glider --rows 16 --cols 16
python3 hardware/host/send_seed.py --dry-run --rule daynight --pattern glider
```

Expected state after configuration, according to `FLASHING.md`: both LEDs off and all-zero frames streaming at 115200. The BL616 exposes two serial ports, and if one is empty the other is usually the right one.

### Console

- Open `software_prototype/cellnet_console.html` in Chrome or Edge.
- Web Serial needs the page served over `http://localhost`. It does not work from `file://`. Any static server works, for example `python3 -m http.server` from `software_prototype/`.
- In the Live tab, connect at 115200 with rows and cols set to 16.
- To check it headlessly: `npm install jsdom@24 && node software_prototype/check_console.js`.

### C++ engine

```bash
cd software_prototype/cpp
make test | make tsan | make tsan-matrix | make prove | make bench | make check
python3 tools/compare_fpga.py   # regenerates results/laptop_vs_fpga.md and figures
```

## 7. Open issues and known limitations

- **No hardware results.** Every FPGA timing figure comes from cycle-accurate Icarus simulation converted at 27 MHz.
- **The configurable-rule chip is large.** Measured with Yosys 0.69 and `-nowidelut`, a cell costs 26.0 LUT4 against 11.0 for the fixed cell. The configurable full chip fits up to 25x25 (87.3% of the device) and not at 26x26 (100.7%) or 32x32 (137.7%). These are pre-route figures. `RULE_CFG=1` is the default. **Uncertain:** whether 26x26 or larger would route, because the fixed build routed well below its pre-route estimate.
- **Prebuilt bitstreams.** `hardware/bitstreams/*.fs.gz` was committed on 2026-07-18, before `rule_loader.v` was added on 2026-09-10, so it is taken to be the fixed-rule (Conway) build at 115200. This is inferred from commit dates and was not verified by inspecting the bitstreams.
- **Stale docs, not yet updated:**
  - The "Cost of a runtime-selectable rule" section in `hardware/synth/README.md` still says "Not measured".
  - The header comment in `ca_cell_rule.v` still says the numbers need a Yosys run.
  - The first table in `hardware/synth/README.md` and in `docs/RESOURCES.md` uses the older oss-cad-suite Yosys figures (13.6 LUT4 per cell). `docs/RESOURCES.md` records the 0.69 figures separately.
- **1 Mbaud is unconfirmed on the real BL616 bridge.** The tolerance sweep steps by one whole clock per bit, so below a divider of about 18 it can only report an upper bound.
- **Laptop data quirk.** The latency row for 32x32 on a single laptop core was 2.6x slower than its throughput runs. It is shown as measured and flagged in `results/laptop_vs_fpga.md`.
- **Threads and core count.** Threads only beat one core from 128x128 upward. Six threads beat ten on the M2 Pro, because the barrier waits for the slow efficiency cores.
- **`std::barrier` under TSan** on macOS reports false positives, and that run is not gating.
- **Untracked files.** `ladder.png` and `results.csv` at the repo root belong to the user and were intentionally left uncommitted.
- **Phase 6 (flip-dot driver)** has not been started.

## 8. Next steps the user stated

- The user plans to meet Prof. Archit Somani this week. He had asked for four things:
  - protecting shared variables while keeping concurrency;
  - showing the algorithm and proving the results correct;
  - using C++;
  - comparing throughput and latency between the laptop and the FPGA.
- For that meeting, a meeting-request email and a 13-slide deck were drafted. The deck is `~/Downloads/CELL-NET_Archit_Somani.pptx`, outside the repo. Neither was sent by Claude.
- The user asked for an r/FPGA post draft. It was drafted in chat and has not been posted.
- The user asked where to submit the project. The venues discussed were Zenodo, r/FPGA, Hacker News, the Hackaday tips line, an arXiv preprint, and a short paper for ACM/SIGDA FPGA 2027 (abstract due 2026-10-01, paper due 2026-10-08 AoE). The user acted only on Zenodo. No decision was recorded on the others.
- Done during the session:
  - GitHub releases `v1.0.0` and `v1.0.1` are published, with both bitstreams attached.
  - Zenodo archived `v1.0.1`. The concept DOI, which points to the latest version, is 10.5281/zenodo.22905813. The v1.0.1 DOI is 10.5281/zenodo.22905814.
  - A DOI badge is in `README.md` and `CITATION.cff` is at the repo root.

The user did not state any technical next steps. The list in `docs/ROADMAP.md` was written by Claude and is not a user instruction.

## Working conventions the user asked for

- Plain, precise writing with no promotional phrasing, no "not X but Y" constructions, and no em or en dashes.
- When the user gives feedback, apply only that change. Do not add sections or notes describing the feedback or the fix.
- Commit messages must be generic: `Add files via upload`, or `Update <file>`.
- The user sometimes edits files on GitHub directly. Fetch and rebase before pushing.
