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
  physical gates, one instance per cell.

## Running it

```bash
python3 verify_correctness.py   # all PASS required first
python3 benchmark.py            # writes results.csv + ladder.png
```

- Thread and multiprocessing tiers need real cores to show real behavior;
  a single-core sandbox flattens the curves.
- Numba requires a supported NumPy version. On a compatibility ImportError,
  `pip install --upgrade numba` first.
