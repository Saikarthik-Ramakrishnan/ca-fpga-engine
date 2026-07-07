# Parallelism Ladder

Same exact CA update rule (Conway's Life, B3/S23, toroidal wraparound —
identical to `../cellnet_console.html`), benchmarked across five substrates,
from "written the way a beginner would write it" up to genuine multi-core
execution. Built to answer one question concretely, before any Verilog is
written: *what does "parallel" actually mean in software, and where does it
fall short of what the FPGA fabric will do?*

## The tiers

| Tier | File | What it is |
|---|---|---|
| 1. Serial | `tier12_serial_threads.py` | Pure Python, nested loops, one thread. The baseline. |
| 2. Threads(4) | `tier12_serial_threads.py` | Pure Python, 4 `ThreadPoolExecutor` threads. Expected to **lose** to serial — this is the GIL, measured. |
| 3. NumPy | `tier3_numpy.py` | Vectorized neighbor-counting via `np.roll`. Fast, but still one core. |
| 4. Multiprocessing(4) | `tier4_multiprocessing.py` | 4 real OS processes, ring-topology halo exchange every generation. Genuine parallelism. |
| 5. Numba | `tier5_numba.py` | `@njit(parallel=True)` + `prange`. JIT-compiled machine code, real multi-core. |

`golden_rule.py` is the single source of truth every tier is checked against.
Run `verify_correctness.py` before trusting any timing — it's saved me from
reporting a wrong-but-fast number more than once.

## Results (Ram's machine — Apple Silicon Mac, 10 cores, Python 3.11.5)

| Grid | Serial | Threads(4) | NumPy | Multiprocess(4) | Numba |
|---|---|---|---|---|---|
| 16×16 | 6,145 gen/s | 3,228 gen/s | 18,435 gen/s | 14,921 gen/s | 111,055 gen/s |
| 32×32 | 1,526 gen/s | 1,254 gen/s | 16,210 gen/s | 7,157 gen/s | 75,063 gen/s |
| 64×64 | 394 gen/s | 367 gen/s | 12,565 gen/s | 2,586 gen/s | 80,503 gen/s |
| 128×128 | skipped¹ | skipped¹ | 7,209 gen/s | 655 gen/s | 51,046 gen/s |

¹ pure-Python nested loops become impractically slow past 64×64; skipped to
keep the full sweep finishing in reasonable time.

Each number is the **median of 5–9 repeated runs**, not a single sample —
early single-shot timings at small grid sizes were dominated by OS
thread-scheduling noise (worse on heterogeneous P+E-core silicon) rather
than real compute differences, and produced a misleading non-monotonic
curve. Repeating and taking the median fixed that; see git history / commit
messages for the before/after if you want to see the noise directly.

### Reading the results

- **Threads lose to serial at every single grid size**, on a real 10-core
  machine with no shortage of idle cores. That's the whole GIL argument in
  one row of numbers: CPython's global interpreter lock means only one
  thread executes Python bytecode at a time, so N threads doing CPU-bound
  pure-Python work buys you scheduling overhead, not parallelism.
- **Multiprocessing's advantage over serial grows with grid size**
  (2.4x → 4.7x → 6.6x from 16×16 to 64×64). Real OS processes, each with
  its own interpreter and GIL, genuinely run concurrently — but every
  generation pays a fixed halo-exchange cost (each process ships its edge
  rows to its neighbors over a pipe). At small grids that fixed cost
  dominates; as the grid grows, the compute-per-process grows faster than
  the communication cost, so the parallel tier's relative advantage
  increases. This is the same communication-vs-compute tradeoff real
  distributed/HPC simulations navigate.
- **Numba wins at every size** — JIT-compiled to native machine code with a
  parallelized loop, no Python interpreter overhead per cell at all once
  compiled.
- None of this is what the FPGA will do. Every tier above is still one or
  more CPU cores executing instructions sequentially per cell, just at
  different levels of overhead. The FPGA fabric (Phase 3) instantiates the
  rule as physical logic, once per cell, all evaluating simultaneously on
  one clock edge — a different mechanism, not a faster version of these.

## Reproducing

```bash
python3 verify_correctness.py   # must show all PASS before trusting timings
python3 benchmark.py            # writes results.csv + ladder.png
```

Note: `os.cpu_count()` matters a lot here — threads/multiprocessing tiers
need real cores to show their real behavior. Numba requires NumPy ≤ its
supported version for your installed `numba` release; if you hit an
`ImportError` about NumPy version compatibility, `pip install --upgrade numba`
first.
