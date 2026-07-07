"""
tier3_numpy.py — vectorized neighbor counting.

No per-cell Python loop at all: the 8 neighbor shifts are done with
np.roll (toroidal, matching the golden model's wraparound exactly) and
summed as whole-array operations. The heavy lifting happens inside NumPy's
C loops, which do release the GIL — but this is still fundamentally ONE
core doing SIMD-ish vectorized work, not N cores each independently
owning a cell. It's fast because it avoids Python's per-object overhead,
not because it's "parallel" in the hardware sense the FPGA fabric is.
That distinction is worth keeping straight when you write this up.
"""
from __future__ import annotations
import numpy as np


def to_numpy(grid: list[list[int]]) -> np.ndarray:
    return np.array(grid, dtype=np.uint8)


def step_numpy(arr: np.ndarray) -> np.ndarray:
    neighbors = np.zeros_like(arr, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            neighbors += np.roll(np.roll(arr, dy, axis=0), dx, axis=1)

    born = (neighbors == 3) & (arr == 0)
    survives = ((neighbors == 2) | (neighbors == 3)) & (arr == 1)
    return (born | survives).astype(np.uint8)


def to_list(arr: np.ndarray) -> list[list[int]]:
    return arr.tolist()
