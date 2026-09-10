# Parallelism Ladder

Same rule as the console (Conway B3/S23, toroidal wrap) run on five software
substrates. Built before the Verilog to put numbers on software parallelism
limits.

## Tiers

| Tier | File | Description |
|---|---|---|
| 1. Serial | `tier12_serial_threads.py` | Pure Python, nested loops, one thread. Baseline. |
| 2. Threads(4) | `tier12_serial_threads.py` | Pure Python, 4 `ThreadPoolExecutor` threads. |
| 3. NumPy | `tier3_numpy.py` | Vectorized neighbor count via `np.roll`. One core. |
| 4. Multiprocessing(4) | `tier4_multiprocessing.py` | 4 OS processes, ring-topology halo exchange per generation. |
| 5. Numba | `tier5_numba.py` | `@njit(parallel=True)` + `prange`. JIT-compiled, multi-core. |
| 6. FPGA fabric | `tier6_fabric.py` | One generation per clock edge. A throughput model built from measured numbers, not a run. |

`golden_rule.py` is the single reference. Run `verify_correctness.py` before
trusting any timing.

## Results (Apple Silicon Mac, 10 cores, Python 3.11.5)

| Grid | Serial | Threads(4) | NumPy | Multiprocess(4) | Numba |
|---|---|---|---|---|---|
| 16x16 | 6,145 gen/s | 3,228 gen/s | 18,435 gen/s | 14,921 gen/s | 111,055 gen/s |
| 32x32 | 1,526 gen/s | 1,254 gen/s | 16,210 gen/s | 7,157 gen/s | 75,063 gen/s |
| 64x64 | 394 gen/s | 367 gen/s | 12,565 gen/s | 2,586 gen/s | 80,503 gen/s |
| 128x128 | skipped¹ | skipped¹ | 7,209 gen/s | 655 gen/s | 51,046 gen/s |

¹ pure-Python loops are impractically slow past 64x64.

**These prose figures and `results.csv` are from different runs and do not
agree.** `results.csv` reports 138,430 gen/s for Numba at 16x16 against the
111,055 above, and 7,349 at 128x128 against 51,046. `results.csv` is the
machine-written artifact and is what `tier6_fabric.py` reads, so the Tier 6
table below is consistent with the CSV and not with this one. Re-run
`benchmark.py` to reconcile them; until then treat the CSV as the data of
record and this table as stale.

Methodology:

- Each number is the median of 5 to 9 runs.
- Single-shot timing produced a misleading curve: runs finish in single-digit
  milliseconds, so measurements captured OS scheduling noise, worse on mixed
  performance/efficiency cores. Median-of-repeats fixed it.

## Observations

- Threads(4) is slower than serial at every size on a 10-core machine. Cause:
  the GIL serializes CPU-bound Python bytecode; four threads add scheduling
  overhead to single-threaded work.
- Multiprocessing gains grow with grid size: 2.4x at 16x16, 6.6x at 64x64.
  Per-generation pipe cost for edge rows is fixed; compute per process grows
  with the grid. Standard compute-vs-communication tradeoff.
- Numba is fastest at every size: native code, parallel loop, no per-cell
  interpreter overhead after compilation.
- The FPGA fabric evaluates every cell in the same clock edge: the rule as
  physical gates, one instance per cell. `tier6_fabric.py` puts a number on
  that.

## Tier 6: the fabric

**Superseded as a speed comparison.** This tier sets the fabric against the Python tiers below, and the fastest of them, Numba, is about 75x slower per core than the bit-sliced C++ engine in [`../cpp`](../cpp/README.md). Against that engine the fabric's advantage at the 27 MHz dock clock is 2.6x at 16x16 and 5.3x at 32x32, where this table says 195x and 408x. The shape of the argument holds: the fabric's rate is flat in grid size and every software rate falls. The size of the gap here does not. Use [`../cpp/results/laptop_vs_fpga.md`](../cpp/results/laptop_vs_fpga.md) for numbers.

```bash
python3 tier6_fabric.py            # table to stdout
python3 tier6_fabric.py --csv --plot
```

| grid | fastest software | software gen/s | fabric gen/s at 27 MHz | speedup | fits on GW2A-18 |
|---|---|---|---|---|---|
| 16x16 | numba | 138,430 | 27,000,000 | 195x | yes |
| 32x32 | numba | 66,141 | 27,000,000 | 408x | yes |
| 64x64 | numba | 25,190 | n/a | n/a | no, 2.7x the LUT4 budget |
| 128x128 | numba | 7,349 | n/a | n/a | no, 10.7x the LUT4 budget |

- The fabric row is flat because one generation takes one clock edge whatever
  the grid size. Adding cells adds area, not time. Every software row slopes
  down. That divergence is the whole argument.
- Where the fabric loses is capacity, and the table says so: past 32x32 it
  does not fit on this part at all, while software just gets slower.
- Headroom, from routed timing rather than the dock clock: 240.38 MHz at
  16x16 and 176.46 MHz at 32x32, both far above the 27 MHz requirement. The
  oscillator binds on this board, not the fabric.
- What you can watch is far slower on purpose: the UART carries about 350
  frames/s at 16x16, and `GEN_DIV` holds the fabric to 10 generations/s.

This is a model, and it is labelled as one everywhere it appears. The
software figures are timings from a running CPU. The fabric figures come
from post-route static timing analysis of a design that has not been flashed
yet. The one modelling step is structural rather than estimated: one
generation per clock edge, independent of grid size.

Every input comes from a number already recorded in this repo: `results.csv`,
the 27 MHz dock oscillator, the Phase 5a routed Fmax figures, and the 13.6
LUT4-equivalents per cell from `measure_resources.py`.

## Running it

```bash
python3 verify_correctness.py   # all PASS required first, exits non-zero on failure
python3 benchmark.py            # writes results.csv + ladder.png
python3 tier6_fabric.py --csv --plot   # writes fabric_comparison.csv + ladder_with_fabric.png
```

`verify_correctness.py` also checks the rule bank: that every named ruleset
round-trips through its Bxx/Sxx notation, that the Conway masks reproduce the
original hardwired `update()` over all 512 cell inputs, and that
`step_golden` and `step_golden_masked` agree. Those masks are shared with
`rule_loader.v` and the console, so drift there desynchronises the hardware
from the software.

- Thread and multiprocessing tiers need real cores to show real behavior;
  a single-core sandbox flattens the curves.
- Numba requires a supported NumPy version. On a compatibility ImportError,
  `pip install --upgrade numba` first.
