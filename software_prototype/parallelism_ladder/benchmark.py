"""
benchmark.py — the parallelism ladder.

Measures generations/second for the same exact CA rule across five
substrates, from "written the way a beginner would write it" up to
genuine multi-core execution:

  1. serial          — pure Python, one thread, one core
  2. threads (4)      — pure Python, 4 threads, GIL-bound (expect ~no speedup)
  3. numpy            — vectorized, single core, no Python per-cell loop
  4. multiprocessing  — 4 real OS processes, halo exchange each generation
  5. numba            — JIT-compiled + prange, real multi-core machine code

Run: python3 benchmark.py
Output: results table to stdout, CSV to results.csv, chart to ladder.png
"""
from __future__ import annotations
import time
import csv
import os
import platform
import multiprocessing as mp

from golden_rule import seed_grid
from tier12_serial_threads import step_serial, step_threads
from tier3_numpy import to_numpy, step_numpy
from tier4_multiprocessing import step_multiprocess
from tier5_numba import step_numba, warmup


def timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - t0


def median(vals):
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def repeat_timing(bench_fn, reps, *args, **kwargs):
    """Run a whole bench_* call `reps` times and return the median total
    time. This exists because individual runs at small grid sizes finish
    in single-digit milliseconds, which makes them dominated by OS
    thread-scheduling noise rather than actual compute -- especially on
    heterogeneous-core CPUs (e.g. Apple Silicon's P+E cores), where a
    short-lived thread can land on a slow core essentially at random.
    Taking the median across several runs filters that noise out."""
    times = [bench_fn(*args, **kwargs) for _ in range(reps)]
    return median(times)


def bench_serial(grid, n, gens):
    g = grid
    t0 = time.perf_counter()
    for _ in range(gens):
        g = step_serial(g, n)
    return time.perf_counter() - t0


def bench_threads(grid, n, gens, n_threads=4):
    g = grid
    t0 = time.perf_counter()
    for _ in range(gens):
        g = step_threads(g, n, n_threads=n_threads)
    return time.perf_counter() - t0


def bench_numpy(grid, n, gens):
    arr = to_numpy(grid)
    t0 = time.perf_counter()
    for _ in range(gens):
        arr = step_numpy(arr)
    return time.perf_counter() - t0


def bench_multiprocess(grid, n, gens, n_workers=4):
    t0 = time.perf_counter()
    step_multiprocess(grid, n, gens=gens, n_workers=n_workers)
    return time.perf_counter() - t0


def bench_numba(grid, n, gens):
    arr = to_numpy(grid)
    warmup()  # compile before timing
    t0 = time.perf_counter()
    for _ in range(gens):
        arr = step_numba(arr)
    return time.perf_counter() - t0


# grid sizes to sweep, and how many generations to average over.
# smaller grids get more generations since each step is cheap and noisy;
# larger grids get fewer since serial/threads get very slow.
SWEEP = [
    (16,  200, 9),
    (32,  100, 7),
    (64,  40,  5),
    (128, 12,  5),
]

# serial and threads are pure-Python nested loops -- they get brutally
# slow past a certain grid size. Skip them above this to keep the whole
# suite finishing in a reasonable time; numpy/numba/multiprocessing still
# run at every size.
SKIP_SLOW_TIERS_ABOVE_N = 64


def main():
    cores = os.cpu_count()
    print(f"Python {platform.python_version()} on {platform.system()} | "
          f"os.cpu_count() = {cores}")
    if cores == 1:
        print("NOTE: this machine reports a single visible core. The "
              "threaded and multiprocessing tiers cannot show real "
              "speedup here regardless of their design -- there's only "
              "one core to schedule onto. Re-run this script on a "
              "multi-core machine (e.g. your laptop) to see the ladder "
              "actually climb.\n")

    rows = []
    for n, gens, reps in SWEEP:
        print(f"--- grid {n}x{n}, {gens} generations, median of {reps} runs ---")
        grid = seed_grid(n, density=0.28, seed=1)

        if n <= SKIP_SLOW_TIERS_ABOVE_N:
            t = repeat_timing(bench_serial, reps, grid, n, gens)
            print(f"  serial            {gens/t:8.1f} gen/s   ({t*1000:.2f}ms median)")
            rows.append(("serial", n, gens, t, gens / t))

            t = repeat_timing(bench_threads, reps, grid, n, gens, n_threads=4)
            print(f"  threads(4)        {gens/t:8.1f} gen/s   ({t*1000:.2f}ms median)")
            rows.append(("threads_4", n, gens, t, gens / t))
        else:
            print("  serial            skipped (grid too large for pure Python loops)")
            print("  threads(4)        skipped (same reason)")

        t = repeat_timing(bench_numpy, reps, grid, n, gens)
        print(f"  numpy             {gens/t:8.1f} gen/s   ({t*1000:.2f}ms median)")
        rows.append(("numpy", n, gens, t, gens / t))

        t = repeat_timing(bench_multiprocess, reps, grid, n, gens, n_workers=4)
        print(f"  multiprocess(4)   {gens/t:8.1f} gen/s   ({t*1000:.2f}ms median)")
        rows.append(("multiprocess_4", n, gens, t, gens / t))

        t = repeat_timing(bench_numba, reps, grid, n, gens)
        print(f"  numba             {gens/t:8.1f} gen/s   ({t*1000:.2f}ms median)")
        rows.append(("numba", n, gens, t, gens / t))
        print()

    with open("results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "grid_n", "generations", "seconds_total", "gen_per_sec"])
        w.writerows(rows)
    print("Wrote results.csv")

    make_chart(rows)


def make_chart(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available -- skipping chart, results.csv still written")
        return

    tiers = sorted(set(r[0] for r in rows))
    ns = sorted(set(r[1] for r in rows))

    plt.figure(figsize=(7, 4.5))
    colors = {
        "serial": "#8A8272", "threads_4": "#C9922B", "numpy": "#33C6E0",
        "multiprocess_4": "#FF7A34", "numba": "#F2C14E",
    }
    for tier in tiers:
        xs = [r[1] for r in rows if r[0] == tier]
        ys = [r[4] for r in rows if r[0] == tier]
        pairs = sorted(zip(xs, ys))
        xs, ys = zip(*pairs)
        plt.plot(xs, ys, marker="o", label=tier, color=colors.get(tier))

    plt.yscale("log")
    plt.xscale("log", base=2)
    plt.xlabel("grid size (N x N)")
    plt.ylabel("generations / second (log scale)")
    plt.title("Parallelism ladder: same CA rule, five substrates")
    plt.legend()
    plt.grid(True, which="both", alpha=0.25)
    plt.tight_layout()
    plt.savefig("ladder.png", dpi=150)
    print("Wrote ladder.png")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)  # matches golden/tier behavior on Linux
    main()
