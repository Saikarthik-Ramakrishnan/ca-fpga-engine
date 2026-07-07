"""
tier5_numba.py — JIT-compiled machine code, real multi-core parallelism
from ordinary-looking Python.

@njit(parallel=True) compiles the per-cell update loop to native machine
code ahead of time, and prange (parallel range) tells Numba's runtime to
split the outer loop across worker threads — crucially, these are threads
that do NOT hold the Python GIL while running, because they're not
executing Python bytecode anymore. This is the tier that most looks like
"just write a normal loop" while actually getting genuine multi-core
speedup, which is why it's worth knowing about even outside this project.
"""
from __future__ import annotations
import numpy as np
from numba import njit, prange


@njit(parallel=True, cache=True)
def _step_numba(grid: np.ndarray, out: np.ndarray, n: int) -> None:
    for y in prange(n):
        y_up = (y - 1) % n
        y_dn = (y + 1) % n
        for x in range(n):
            x_l = (x - 1) % n
            x_r = (x + 1) % n
            nb = (grid[y_up, x_l] + grid[y_up, x] + grid[y_up, x_r] +
                  grid[y, x_l]    +                  grid[y, x_r]    +
                  grid[y_dn, x_l] + grid[y_dn, x] + grid[y_dn, x_r])
            alive = grid[y, x]
            if alive:
                out[y, x] = 1 if (nb == 2 or nb == 3) else 0
            else:
                out[y, x] = 1 if nb == 3 else 0


def step_numba(arr: np.ndarray) -> np.ndarray:
    n = arr.shape[0]
    out = np.zeros_like(arr)
    _step_numba(arr, out, n)
    return out


def warmup(n: int = 8):
    """Numba compiles on first call — call this once before timing so the
    benchmark measures execution, not JIT compilation."""
    dummy = np.zeros((n, n), dtype=np.uint8)
    step_numba(dummy)
