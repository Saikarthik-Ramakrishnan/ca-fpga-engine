"""
verify_correctness.py: run this before trusting any benchmark number.

A fast wrong answer is worse than no answer. Every tier is checked against
golden_rule.step_golden on a small grid for several generations before the
benchmark suite will report any timings.
"""
import sys

from golden_rule import (
    seed_grid, step_golden, step_golden_masked, grids_equal,
    RULES, rule_masks, mask_notation, update, update_masked,
    CONWAY_BIRTH, CONWAY_SURVIVE,
)
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


def check_rule_bank():
    """The rule bank is shared with the Verilog (rule_loader.v resets to the
    Conway masks, ca_cell_rule.v indexes them) and with the console's RULES
    object. Three things have to hold or the hardware and the software stop
    describing the same automaton:

      1. every named rule round-trips through its Bxx/Sxx notation,
      2. the Conway masks reproduce the original hardwired update() over all
         512 cell inputs,
      3. step_golden and step_golden_masked agree under Conway, so the
         refactor that introduced masks changed no existing behavior.
    """
    ok = True

    for name in RULES:
        birth, survive = rule_masks(name)
        if mask_notation(birth, survive) != RULES[name]["notation"]:
            print(f"FAIL  rule bank: {name} notation mismatch "
                  f"({mask_notation(birth, survive)} vs {RULES[name]['notation']})")
            ok = False

    for alive in (0, 1):
        for neighbors in range(9):
            if update(alive, neighbors) != update_masked(
                    alive, neighbors, CONWAY_BIRTH, CONWAY_SURVIVE):
                print(f"FAIL  rule bank: Conway masks disagree with update() "
                      f"at alive={alive} neighbors={neighbors}")
                ok = False

    n = 16
    grid = seed_grid(n, density=0.3, seed=7)
    a, b = grid, grid
    for _ in range(5):
        a = step_golden(a, n)
        b = step_golden_masked(b, n, CONWAY_BIRTH, CONWAY_SURVIVE)
    if not grids_equal(a, b):
        print("FAIL  rule bank: step_golden and step_golden_masked diverge under Conway")
        ok = False

    print(f"{'PASS' if ok else 'FAIL':5} rule bank ({len(RULES)} rulesets, "
          f"masks vs hardwired Conway)")
    return ok


if __name__ == "__main__":
    print("Verifying every tier against the golden model (16x16, 5 generations)\n")
    results = [
        check("serial", step_serial),
        check("threads (4)", lambda g, n: step_threads(g, n, n_threads=4)),
        check_numpy(),
        check_numba(),
        check_multiprocess(),
        check_rule_bank(),
    ]
    print()
    if all(results):
        print("All tiers verified correct. Benchmark numbers can be trusted.")
    else:
        # exit non-zero so CI and shell pipelines actually notice
        print("At least one tier FAILED correctness. Fix before benchmarking.")
        sys.exit(1)
        raise SystemExit(1)
