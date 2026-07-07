"""
tier1_serial.py + tier2_threads.py combined — the two "software as you'd
naively write it" tiers.

Tier 1 is just golden_rule.step_golden — included here again as the named
"tier" for the benchmark table.

Tier 2 splits the grid into row-chunks and hands one chunk to each of N
threads via ThreadPoolExecutor. Each thread does the exact same pure-Python
nested-loop work as Tier 1, just on a slice of rows.

The point of Tier 2 is that it should NOT be faster than Tier 1, despite
using multiple threads on presumably-multiple cores. CPython's GIL means
only one thread runs Python bytecode at a time; the others block waiting
for it. You're paying thread-scheduling overhead for zero real parallelism.
This is the tier that makes the GIL bottleneck a *measurement*, not just
a claim.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from golden_rule import update, neighbor_count


def step_serial(grid: list[list[int]], n: int) -> list[list[int]]:
    nxt = [[0] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            nxt[y][x] = update(grid[y][x], neighbor_count(grid, x, y, n))
    return nxt


def _compute_rows(grid, n, y_start, y_end):
    """Pure-Python CPU-bound work handed to one thread."""
    out_rows = []
    for y in range(y_start, y_end):
        row = [0] * n
        for x in range(n):
            row[x] = update(grid[y][x], neighbor_count(grid, x, y, n))
        out_rows.append(row)
    return y_start, out_rows


def step_threads(grid: list[list[int]], n: int, n_threads: int = 4) -> list[list[int]]:
    nxt = [[0] * n for _ in range(n)]
    chunk = max(1, n // n_threads)
    ranges = [(y, min(y + chunk, n)) for y in range(0, n, chunk)]

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(_compute_rows, grid, n, a, b) for a, b in ranges]
        for fut in futures:
            y_start, rows = fut.result()
            for i, row in enumerate(rows):
                nxt[y_start + i] = row
    return nxt
