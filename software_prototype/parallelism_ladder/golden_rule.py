"""
golden_rule.py: the single source of truth for the CA update rule.

Every benchmark tier (naive Python, threads, NumPy, multiprocessing, Numba)
must produce bit-identical output to this reference for a given seed grid.
This mirrors the same rule and toroidal wraparound used in the JS console
(`update(alive, neighbors)` in cellnet_console.html) and in the Verilog
(`ca_cell.v`, `ca_cell_rule.v`). One rule, many substrates.

Rule representation
-------------------
A totalistic outer-rule is two 9-bit masks over the live-neighbor count:

    birth_mask   bit k set -> a dead cell with k live neighbors becomes alive
    survive_mask bit k set -> a live cell with k live neighbors stays alive

Conway's B3/S23 is birth_mask = 0b000001000, survive_mask = 0b000001100.
Those masks are exactly what `rule_loader.v` latches off the UART wire and
broadcasts to every `ca_cell_rule` on the fabric, so a rule named here, a
rule selected in the console, and a rule running on the FPGA are the same
18 bits.

`update()` and `step_golden()` keep their original Conway-only signatures
and are thin wrappers over the masked versions: one implementation, no
second reference.
"""
from __future__ import annotations
import random

# ---------------------------------------------------------------- rule bank
# Mirrors RULES in software_prototype/cellnet_console.html exactly.
RULES = {
    "conway":   {"label": "CONWAY",    "notation": "B3/S23",
                 "birth": (3,),          "survive": (2, 3)},
    "highlife": {"label": "HIGHLIFE",  "notation": "B36/S23",
                 "birth": (3, 6),        "survive": (2, 3)},
    "daynight": {"label": "DAY&NIGHT", "notation": "B3678/S34678",
                 "birth": (3, 6, 7, 8),  "survive": (3, 4, 6, 7, 8)},
    "seeds":    {"label": "SEEDS",     "notation": "B2/S",
                 "birth": (2,),          "survive": ()},
    "maze":     {"label": "MAZE",      "notation": "B3/S12345",
                 "birth": (3,),          "survive": (1, 2, 3, 4, 5)},
}


def counts_to_mask(counts) -> int:
    """(3,) -> 0b000001000. Nine valid neighbor counts, 0 through 8."""
    mask = 0
    for k in counts:
        if not 0 <= k <= 8:
            raise ValueError(f"neighbor count {k} out of range 0..8")
        mask |= 1 << k
    return mask


def mask_to_counts(mask: int) -> tuple[int, ...]:
    return tuple(k for k in range(9) if (mask >> k) & 1)


def rule_masks(name: str) -> tuple[int, int]:
    """Named rule -> (birth_mask, survive_mask), the 18 bits the wire carries."""
    try:
        spec = RULES[name]
    except KeyError:
        raise ValueError(
            f"unknown rule {name!r}; known: {', '.join(sorted(RULES))}"
        ) from None
    return counts_to_mask(spec["birth"]), counts_to_mask(spec["survive"])


def mask_notation(birth_mask: int, survive_mask: int) -> str:
    """(0b1000, 0b1100) -> 'B3/S23'. Used in logs and testbench failures."""
    b = "".join(str(k) for k in mask_to_counts(birth_mask))
    s = "".join(str(k) for k in mask_to_counts(survive_mask))
    return f"B{b}/S{s}"


CONWAY_BIRTH, CONWAY_SURVIVE = rule_masks("conway")


# -------------------------------------------------------------- the rule
def update_masked(alive: int, neighbors: int,
                  birth_mask: int, survive_mask: int) -> int:
    """Pure, local update. The hardware twin is these two lines of
    ca_cell_rule.v: pick a mask with `state`, index it with `count`."""
    mask = survive_mask if alive else birth_mask
    return (mask >> neighbors) & 1


def update(alive: int, neighbors: int) -> int:
    """Conway B3/S23, the original signature every existing tier calls."""
    return update_masked(alive, neighbors, CONWAY_BIRTH, CONWAY_SURVIVE)


def neighbor_count(grid: list[list[int]], x: int, y: int, n: int) -> int:
    c = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            c += grid[(y + dy) % n][(x + dx) % n]
    return c


def step_golden_masked(grid: list[list[int]], n: int,
                       birth_mask: int, survive_mask: int) -> list[list[int]]:
    """Reference implementation: pure Python, nested loops, no tricks.
    Slow on purpose: it exists to be correct, not fast."""
    nxt = [[0] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            nxt[y][x] = update_masked(
                grid[y][x], neighbor_count(grid, x, y, n),
                birth_mask, survive_mask,
            )
    return nxt


def step_golden(grid: list[list[int]], n: int) -> list[list[int]]:
    """Conway B3/S23, the original signature every existing tier calls."""
    return step_golden_masked(grid, n, CONWAY_BIRTH, CONWAY_SURVIVE)


def seed_grid(n: int, density: float = 0.28, seed: int = 42) -> list[list[int]]:
    rng = random.Random(seed)
    return [[1 if rng.random() < density else 0 for _ in range(n)] for _ in range(n)]


def grids_equal(a: list[list[int]], b: list[list[int]]) -> bool:
    return all(a[y][x] == b[y][x] for y in range(len(a)) for x in range(len(a)))
