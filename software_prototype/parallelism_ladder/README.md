# Parallelism Ladder

Same exact CA update rule as the console (Conway's Life, B3/S23, toroidal
wraparound), run across five different substrates. I built
this before touching Verilog because I wanted a real answer, with numbers,
to a question I kept hand-waving past: what does "parallel" actually mean
in software, and where does it fall short of what the FPGA fabric is going
to do?

## The tiers

| Tier | File | What it is |
|---|---|---|
| 1. Serial | `tier12_serial_threads.py` | Pure Python, nested loops, one thread. The baseline everything else is judged against. |
| 2. Threads(4) | `tier12_serial_threads.py` | Pure Python, 4 `ThreadPoolExecutor` threads. I expected this to lose to serial, and it does. That's the point: this is the GIL, measured instead of just asserted. |
| 3. NumPy | `tier3_numpy.py` | Vectorized neighbor-counting via `np.roll`. Fast, but still fundamentally one core. |
| 4. Multiprocessing(4) | `tier4_multiprocessing.py` | 4 real OS processes, ring-topology halo exchange every generation. Actual parallelism. |
| 5. Numba | `tier5_numba.py` | `@njit(parallel=True)` + `prange`. JIT-compiled machine code, genuinely multi-core. |

`golden_rule.py` is the one source of truth every tier gets checked
against. Run `verify_correctness.py` before trusting any timing number.

## What I actually found (my machine: Apple Silicon Mac, 10 cores, Python 3.11.5)

| Grid | Serial | Threads(4) | NumPy | Multiprocess(4) | Numba |
|---|---|---|---|---|---|
| 16×16 | 6,145 gen/s | 3,228 gen/s | 18,435 gen/s | 14,921 gen/s | 111,055 gen/s |
| 32×32 | 1,526 gen/s | 1,254 gen/s | 16,210 gen/s | 7,157 gen/s | 75,063 gen/s |
| 64×64 | 394 gen/s | 367 gen/s | 12,565 gen/s | 2,586 gen/s | 80,503 gen/s |
| 128×128 | skipped¹ | skipped¹ | 7,209 gen/s | 655 gen/s | 51,046 gen/s |

¹ pure-Python nested loops get impractically slow past 64×64, so I skipped
them there to keep the full sweep finishing in reasonable time.

Every number above is the median of 5–9 repeated runs.
My first pass at this used single-shot timing and produced a genuinely
misleading non-monotonic curve: Numba looked 50x faster on a 32×32 grid
than on a 16×16 one, which makes no sense on its face. Turned out that at
these grid sizes, individual runs finish in single-digit milliseconds,
which means the timing was picking up OS thread-scheduling noise more than
real compute differences (made worse by Apple Silicon's mixed performance
and efficiency cores). Repeating each measurement and taking the median
fixed it.

### What the numbers actually say

Threads lose to serial at every single grid size, on a machine with ten
real cores sitting mostly idle. That's the whole GIL argument, no longer
something I have to argue for. CPython's global interpreter lock means
only one thread executes Python bytecode at a time, so four threads doing
CPU-bound pure-Python work just buys you scheduling overhead on top of the
same single-threaded work.

Multiprocessing's edge over serial actually grows as the grid gets bigger,
from 2.4x at 16×16 up to 6.6x by 64×64. Each process genuinely runs
concurrently, with its own interpreter and its own GIL, but every
generation pays a fixed cost to ship edge rows to its neighbors over a
pipe. At small grids that fixed cost dominates; as the grid grows, the
compute each process is doing grows faster than the communication cost
does, so the relative payoff improves. It's a small-scale version of the
exact compute-vs-communication tradeoff real distributed simulations have
to deal with.

Numba wins at every size I tested. Compiled to native machine code with
a parallelized loop, no interpreter overhead per cell once it's compiled.

The FPGA fabric (Phase 3) turns the rule into physical logic gates, instantiated
once per cell, all evaluating at the same instant on one clock edge, which is a different mechanism entirely.

## Running it yourself

```bash
python3 verify_correctness.py   # should show all PASS before you trust anything
python3 benchmark.py            # writes results.csv + ladder.png
```

Worth knowing: `os.cpu_count()` matters a lot for the threads and
multiprocessing tiers to show their real behavior. I first ran this in a
single-core sandbox and got a very different (much less interesting) story
than on my actual laptop. Also, Numba needs a NumPy version it supports;
if you hit an `ImportError` about NumPy compatibility, `pip install
--upgrade numba` first before trying to downgrade NumPy.
