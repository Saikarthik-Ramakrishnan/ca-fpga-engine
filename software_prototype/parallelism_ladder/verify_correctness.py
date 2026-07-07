"""
verify_correctness.py — run this before trusting any benchmark number.

A fast wrong answer is worse than no answer. Every tier is checked against
golden_rule.step_golden on a small grid for several generations before the
benchmark suite will report any timings.
"""
from golden_rule import seed_grid, step_golden, grids_equal
from tier12_serial_threads import step_serial, step_threads
from tier3_numpy import to_numpy, step_numpy, to_list
from tier4_multiprocessing import step_multiprocess
from tier5_numba import step_numba, warmup


def check(name, fn):
    n = 16
    grid = seed_grid(n, density=0.3, seed=7)
    ref = grid
    got = grid
    for _ in range(5):
        ref = step_golden(ref, n)
        got = fn(got, n)
    ok = grids_equal(ref, got)
    print(f"{'PASS' if ok else 'FAIL':5} {name}")
    return ok


def check_numpy():
    n = 16
    grid = seed_grid(n, density=0.3, seed=7)
    ref = grid
    arr = to_numpy(grid)
    for _ in range(5):
        ref = step_golden(ref, n)
        arr = step_numpy(arr)
    ok = grids_equal(ref, to_list(arr))
    print(f"{'PASS' if ok else 'FAIL':5} numpy")
    return ok


def check_numba():
    n = 16
    grid = seed_grid(n, density=0.3, seed=7)
    ref = grid
    arr = to_numpy(grid)
    warmup()
    for _ in range(5):
        ref = step_golden(ref, n)
        arr = step_numba(arr)
    ok = grids_equal(ref, arr.tolist())
    print(f"{'PASS' if ok else 'FAIL':5} numba")
    return ok


def check_multiprocess():
    n = 16
    grid = seed_grid(n, density=0.3, seed=7)
    ref = grid
    for _ in range(5):
        ref = step_golden(ref, n)
    got = step_multiprocess(grid, n, gens=5, n_workers=4)
    ok = grids_equal(ref, got)
    print(f"{'PASS' if ok else 'FAIL':5} multiprocessing (4 workers)")
    return ok


if __name__ == "__main__":
    print("Verifying every tier against the golden model (16x16, 5 generations)\n")
    results = [
        check("serial", step_serial),
        check("threads (4)", lambda g, n: step_threads(g, n, n_threads=4)),
        check_numpy(),
        check_numba(),
        check_multiprocess(),
    ]
    print()
    if all(results):
        print("All tiers verified correct. Benchmark numbers can be trusted.")
    else:
        print("At least one tier FAILED correctness — fix before benchmarking.")
        raise SystemExit(1)
