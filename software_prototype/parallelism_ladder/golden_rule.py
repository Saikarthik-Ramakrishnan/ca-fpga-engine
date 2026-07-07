"""
golden_rule.py — the single source of truth for the CA update rule.

Every benchmark tier (naive Python, threads, NumPy, multiprocessing, Numba)
must produce bit-identical output to this reference for a given seed grid.
This mirrors the same B3/S23 rule and toroidal wraparound used in the
JS console (`update(alive, neighbors)` in cellnet_console.html) and in the
future ca_cell.v Verilog module — one rule, many substrates.
"""
from __future__ import annotations
import random


def update(alive: int, neighbors: int) -> int:
    """Pure, local update — same signature that becomes Verilog logic."""
    if alive:
        return 1 if neighbors in (2, 3) else 0
    return 1 if neighbors == 3 else 0


def neighbor_count(grid: list[list[int]], x: int, y: int, n: int) -> int:
    c = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            c += grid[(y + dy) % n][(x + dx) % n]
    return c


def step_golden(grid: list[list[int]], n: int) -> list[list[int]]:
    """Reference implementation: pure Python, nested loops, no tricks.
    Slow on purpose — it exists to be correct, not fast."""
    nxt = [[0] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            nxt[y][x] = update(grid[y][x], neighbor_count(grid, x, y, n))
    return nxt


def seed_grid(n: int, density: float = 0.28, seed: int = 42) -> list[list[int]]:
    rng = random.Random(seed)
    return [[1 if rng.random() < density else 0 for _ in range(n)] for _ in range(n)]


def grids_equal(a: list[list[int]], b: list[list[int]]) -> bool:
    return all(a[y][x] == b[y][x] for y in range(len(a)) for x in range(len(a)))
