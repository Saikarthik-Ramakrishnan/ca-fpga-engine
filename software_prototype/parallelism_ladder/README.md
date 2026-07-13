# Parallelism Ladder

Same CA update rule as the console (Conway's Life, B3/S23, toroidal
wraparound), run across five different substrates. Built before touching
Verilog, to get a real numeric answer to a question that's easy to hand-wave:
what does "parallel" actually mean in software, and where does it fall short of
what the FPGA fabric does?

## The tiers

| Tier | File | What it is |
|---|---|---|
| 1. Serial | `tier12_serial_threads.py` | Pure Python, nested loops, one thread. The baseline. |
| 2. Threads(4) | `tier12_serial_threads.py` | Pure Python, 4 `ThreadPoolExecutor` threads. Expected to lose to serial, and it does. This is the GIL, measured. |
| 3. NumPy | `tier3_numpy.py` | Vectorized neighbor-counting via `np.roll`. Fast, still one core. |
| 4. Multiprocessing(4) | `tier4_multiprocessing.py` | 4 real OS processes, ring-topology halo exchange every generation. Real parallelism. |
| 5. Numba | `tier5_numba.py` | `@njit(parallel=True)` + `prange`. JIT-compiled machine code, genuinely multi-core. |

`golden_rule.py` is the one source of truth every tier is checked against. Run
`verify_correctness.py` before trusting any timing number.

## Results (Apple Silicon Mac, 10 cores, Python 3.11.5)

| Grid | Serial | Threads(4) | NumPy | Multiprocess(4) | Numba |
|---|---|---|---|---|---|
| 16×16 | 6,145 gen/s | 3,228 gen/s | 18,435 gen/s | 14,921 gen/s | 111,055 gen/s |
| 32×32 | 1,526 gen/s | 1,254 gen/s | 16,210 gen/s | 7,157 gen/s | 75,063 gen/s |
| 64×64 | 394 gen/s | 367 gen/s | 12,565 gen/s | 2,586 gen/s | 80,503 gen/s |
| 128×128 | skipped¹ | skipped¹ | 7,209 gen/s | 655 gen/s | 51,046 gen/s |

¹ pure-Python nested loops get impractically slow past 64×64, skipped to keep
the sweep fast.

Methodology note:

- Every number is the median of 5 to 9 repeated runs.
- A first pass used single-shot timing and produced a misleading curve: Numba
  looked 50x faster on a 32×32 grid than on 16×16.
- At these sizes single runs finish in single-digit milliseconds, so timing was
  picking up OS thread-scheduling noise more than real compute (worse on Apple
  Silicon's mixed performance and efficiency cores).
- Repeating each measurement and taking the median fixed it.

## Reading the numbers

- **Threads lose to serial at every grid size**, on a machine with ten real
  cores mostly idle. That's the GIL, directly measured. CPython's global
  interpreter lock means only one thread executes Python bytecode at a time, so
  four threads doing CPU-bound work just adds scheduling overhead on top of the
  same single-threaded work.
- **Multiprocessing's edge over serial grows with grid size**: 2.4x at 16×16,
  up to 6.6x by 64×64. Each process runs concurrently with its own interpreter
  and its own GIL, but every generation pays a fixed cost to ship edge rows to
  neighboring processes over a pipe. At small grids that fixed cost dominates.
  As the grid grows, compute per process grows faster than the communication
  cost, so the payoff improves. A small-scale version of the
  compute-versus-communication tradeoff real distributed simulations deal with.
- **Numba wins at every size tested**: compiled to native machine code with a
  parallelized loop, no interpreter overhead per cell once compiled.
- **The FPGA fabric is a different mechanism entirely.** The rule becomes
  physical logic gates, instantiated once per cell, all evaluating at the same
  instant on one clock edge.

## Running it yourself

```bash
python3 verify_correctness.py   # should show all PASS before you trust anything
python3 benchmark.py            # writes results.csv + ladder.png
```

- `os.cpu_count()` matters a lot for the threads and multiprocessing tiers to
  show real behavior. A first run in a single-core sandbox told a much less
  interesting story than the real laptop run above.
- Numba needs a NumPy version it supports. On `ImportError` about NumPy
  compatibility, `pip install --upgrade numba` first before downgrading NumPy.
