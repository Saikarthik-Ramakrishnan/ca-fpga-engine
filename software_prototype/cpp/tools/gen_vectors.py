#!/usr/bin/env python3
"""
gen_vectors.py

Writes the test vectors the C++ engines are checked against, computed by
golden_rule.py and nothing else. golden_rule.py stays the project's single
reference: the C++ port never checks itself against itself, it checks
against what this script wrote.

Three files, little-endian, grids packed the way the UART packs them
(cell i = r*cols + c lives in bit i % 8 of byte i // 8):

  cell.bin          per rule: birth u16, survive u16, then 18 bytes, the
                    next state for alive in (0, 1) and count in 0..8
  exhaustive4.bin   per rule: birth u16, survive u16, then 65536 u16, the
                    next state of every 4x4 torus indexed by its current
                    state (bit r*4 + c is cell (r, c))
  trajectories.bin  u32 case count, then per case: side u16, birth u16,
                    survive u16, gens u16, seed u32, density_milli u16, the
                    initial grid, then the grid after every generation

  python3 gen_vectors.py OUTDIR
"""
from __future__ import annotations

import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "parallelism_ladder"))
from golden_rule import (  # noqa: E402
    RULES, rule_masks, update_masked, step_golden_masked, seed_grid,
)

# (side, [(seed, density)], generations). Sides cover the degenerate tori
# (1, 2, 3, where neighbors repeat), every FPGA build size (8, 16, 24, 32),
# one word per row (64) and a row spanning two words (128), which is the
# only place the bit-sliced kernel carries the wrap across words.
PLAN = [
    (1,   [(1, 0.5), (2, 0.9)], 6),
    (2,   [(1, 0.5), (2, 0.3)], 8),
    (3,   [(1, 0.4), (2, 0.6)], 12),
    (4,   [(1, 0.3), (2, 0.5)], 16),
    (5,   [(1, 0.3), (2, 0.5)], 20),
    (8,   [(1, 0.10), (2, 0.28), (3, 0.45), (4, 0.65)], 40),
    (16,  [(1, 0.10), (2, 0.28), (3, 0.45), (4, 0.65)], 40),
    (24,  [(1, 0.28), (2, 0.45)], 40),
    (32,  [(1, 0.28), (2, 0.45), (3, 0.65)], 40),
    (64,  [(1, 0.28), (2, 0.45)], 24),
    (128, [(1, 0.35)], 12),
]


def pack(grid, n: int) -> bytes:
    bits = 0
    for r in range(n):
        row = grid[r]
        for c in range(n):
            if row[c]:
                bits |= 1 << (r * n + c)
    return bits.to_bytes((n * n + 7) // 8, "little")


def write_cell(path: str) -> int:
    with open(path, "wb") as fh:
        for name in RULES:
            b, s = rule_masks(name)
            fh.write(struct.pack("<HH", b, s))
            fh.write(bytes(update_masked(alive, count, b, s)
                           for alive in (0, 1) for count in range(9)))
    return len(RULES) * 18


def write_exhaustive4(path: str) -> int:
    n = 4
    with open(path, "wb") as fh:
        for name in RULES:
            b, s = rule_masks(name)
            fh.write(struct.pack("<HH", b, s))
            out = bytearray()
            for state in range(1 << 16):
                grid = [[(state >> (r * n + c)) & 1 for c in range(n)] for r in range(n)]
                nxt = step_golden_masked(grid, n, b, s)
                v = 0
                for r in range(n):
                    for c in range(n):
                        if nxt[r][c]:
                            v |= 1 << (r * n + c)
                out += struct.pack("<H", v)
            fh.write(out)
    return len(RULES) * (1 << 16)


def write_trajectories(path: str) -> tuple[int, int]:
    cases = []
    for side, seeds, gens in PLAN:
        for name in RULES:
            for seed, density in seeds:
                cases.append((side, name, seed, density, gens))

    steps = 0
    with open(path, "wb") as fh:
        fh.write(struct.pack("<I", len(cases)))
        for side, name, seed, density, gens in cases:
            b, s = rule_masks(name)
            grid = seed_grid(side, density=density, seed=seed)
            fh.write(struct.pack("<HHHHIH", side, b, s, gens, seed, int(round(density * 1000))))
            fh.write(pack(grid, side))
            for _ in range(gens):
                grid = step_golden_masked(grid, side, b, s)
                fh.write(pack(grid, side))
                steps += 1
    return len(cases), steps


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)

    t0 = time.time()
    n_cell = write_cell(os.path.join(out, "cell.bin"))
    n_ex = write_exhaustive4(os.path.join(out, "exhaustive4.bin"))
    n_cases, n_steps = write_trajectories(os.path.join(out, "trajectories.bin"))
    print(f"golden_rule.py vectors in {out}  ({time.time() - t0:.1f} s)")
    print(f"  cell.bin          {n_cell} cell-rule cases")
    print(f"  exhaustive4.bin   {n_ex:,} single-step 4x4 cases ({len(RULES)} rules x 65,536 states)")
    print(f"  trajectories.bin  {n_cases} trajectories, {n_steps:,} golden generations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
