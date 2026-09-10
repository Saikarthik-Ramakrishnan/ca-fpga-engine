#!/usr/bin/env python3
"""
prove_schedules.py

Exhaustive schedule exploration. ThreadSanitizer and the stress tests
sample schedules; this enumerates every one of them, for every initial grid
of a small torus, and checks each outcome against golden_rule.py.

Model (faithful to engines.hpp)
  - A torus of side n, T threads, the static row partition of partition().
  - Thread t's program, per generation: one UPDATE per owned cell, row-major,
    then BARRIER if the protocol has one.
  - UPDATE(cell) reads the cell's neighborhood from the read buffer and
    writes the cell into the write buffer, as one atomic step.
  - BARRIER(k) lets a thread through once every thread has reached barrier
    k. That is std::barrier's semantics, including the part where a released
    thread may run ahead while slower ones are still waking up.
  - The second buffer starts zeroed, as blank_like() leaves it, so a read of
    a cell nobody has written yet sees exactly what the C++ would see.

Protocols
  barrier     double buffer + barrier    engines.hpp BarrierEngine
  no_barrier  double buffer, no barrier  races.cpp no_barrier
  in_place    one buffer + barrier       races.cpp in_place

Why atomic UPDATE steps are enough
  - barrier: inside a phase no operation conflicts with another thread's.
    Reads hit the read buffer, which nobody writes; writes hit disjoint
    cells of the write buffer. Operations that do not conflict commute, so
    every finer-grained interleaving (single loads and stores) is
    equivalent to one of the coarse interleavings enumerated here. Zero
    wrong schedules here means zero at any granularity (Lipton's reduction).
  - no_barrier and in_place: coarse interleavings are a subset of fine
    ones, so every wrong outcome found here is reachable by the real code.

Exit status is non-zero if the barrier protocol has a single wrong
schedule, or if either broken protocol yields no counterexample at all
(that would mean the explorer cannot see bugs, and its clean result for
the barrier protocol would be worthless).

  python3 prove_schedules.py            CI budget, about 40 s on an M2 Pro
  python3 prove_schedules.py --full     larger samples, a third generation, and
                                        4x4 with 4 threads and no barrier (the
                                        last alone takes about 90 s)
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "parallelism_ladder"))
from golden_rule import (  # noqa: E402
    RULES, rule_masks, update_masked, step_golden_masked,
)

PROTOCOLS = ("barrier", "no_barrier", "in_place")


def partition(rows: int, T: int, t: int) -> tuple[int, int]:
    """engines.hpp partition(), exactly."""
    return rows * t // T, rows * (t + 1) // T


def neighborhoods(n: int) -> list[tuple[int, ...]]:
    """Eight neighbor indices per cell, by golden_rule.neighbor_count's modulo."""
    out = []
    for r in range(n):
        for c in range(n):
            out.append(tuple(((r + dy) % n) * n + (c + dx) % n
                             for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                             if not (dx == 0 and dy == 0)))
    return out


def to_bits(grid, n: int) -> int:
    return sum(grid[r][c] << (r * n + c) for r in range(n) for c in range(n))


def from_bits(v: int, n: int):
    return [[(v >> (r * n + c)) & 1 for c in range(n)] for r in range(n)]


def golden_after(v: int, n: int, b: int, s: int, gens: int) -> int:
    grid = from_bits(v, n)
    for _ in range(gens):
        grid = step_golden_masked(grid, n, b, s)
    return to_bits(grid, n)


def self_check(n: int) -> None:
    """The explorer's one-cell update must equal golden_rule's step, on every
    grid of this size and every rule, before any of its verdicts count."""
    nb = neighborhoods(n)
    for name in RULES:
        b, s = rule_masks(name)
        for v in range(1 << (n * n)):
            mine = 0
            for cell in range(n * n):
                cnt = sum((v >> q) & 1 for q in nb[cell])
                mine |= update_masked((v >> cell) & 1, cnt, b, s) << cell
            if mine != golden_after(v, n, b, s, 1):
                raise SystemExit(f"explorer disagrees with golden_rule.py: n={n} {name} grid {v:#x}")


class Instance:
    def __init__(self, n: int, T: int, gens: int, protocol: str):
        self.n, self.T, self.G, self.protocol = n, T, gens, protocol
        self.nb = neighborhoods(n)
        self.owned = []
        for t in range(T):
            r0, r1 = partition(n, T, t)
            self.owned.append(tuple(r * n + c for r in range(r0, r1) for c in range(n)))
        # On n >= 3 the eight neighbors are eight distinct cells, so a mask
        # and a popcount count them exactly (checked, not assumed).
        assert all(len(set(nbh)) == 8 for nbh in self.nb), "explorer needs side >= 3"
        self.nbmask = tuple(sum(1 << q for q in nbh) for nbh in self.nb)
        self.has_barrier = protocol != "no_barrier"
        self.per_gen = tuple(len(o) + (1 if self.has_barrier else 0) for o in self.owned)
        self.end = tuple(gens * pg for pg in self.per_gen)
        # position of BARRIER(k) in thread u's program
        self.bar_pos = tuple(tuple(k * self.per_gen[u] + len(self.owned[u]) for k in range(gens))
                             for u in range(T))

    def _moves(self, pcs, m0, m1, b, s):
        """Every enabled step from this state: (label, next pcs, next m0, next m1)."""
        T, n = self.T, self.n
        in_place = self.protocol == "in_place"
        for t in range(T):
            pc = pcs[t]
            if pc == self.end[t]:
                continue
            k, j = divmod(pc, self.per_gen[t])
            if j < len(self.owned[t]):
                cell = self.owned[t][j]
                src = m0 if (in_place or k % 2 == 0) else m1
                cnt = (src & self.nbmask[cell]).bit_count()
                bit = update_masked((src >> cell) & 1, cnt, b, s)
                clear = ~(1 << cell)
                if in_place or k % 2 == 1:
                    n0, n1 = (m0 & clear) | (bit << cell), m1
                else:
                    n0, n1 = m0, (m1 & clear) | (bit << cell)
                label = f"t{t} gen {k + 1} cell ({cell // n},{cell % n})"
            else:
                if any(pcs[u] < self.bar_pos[u][k] for u in range(T)):
                    continue  # blocked: somebody has not reached barrier k
                n0, n1 = m0, m1
                label = f"t{t} passes barrier {k + 1}"
            yield label, pcs[:t] + (pc + 1,) + pcs[t + 1:], n0, n1

    def _final(self, m0, m1):
        if self.protocol == "in_place" or self.G % 2 == 0:
            return m0
        return m1

    def explore(self, init: int, b: int, s: int, want: int):
        """(schedules, wrong schedules) over every interleaving from `init`,
        plus the memo so a caller can extract a counterexample."""
        end = self.end

        @lru_cache(maxsize=None)
        def go(pcs, m0, m1):
            if pcs == end:
                return (1, 0 if self._final(m0, m1) == want else 1)
            total = wrong = 0
            for _, npcs, n0, n1 in self._moves(pcs, m0, m1, b, s):
                a, w = go(npcs, n0, n1)
                total += a
                wrong += w
            if total == 0:
                raise SystemExit(f"deadlock in the model at {pcs}: the model is wrong")
            return (total, wrong)

        return go((0,) * self.T, init, 0), go

    def counterexample(self, init: int, b: int, s: int, want: int, go):
        """Walk one wrong schedule, pruning with the memo's wrong-counts."""
        pcs, m0, m1, steps = (0,) * self.T, init, 0, []
        while pcs != self.end:
            for label, npcs, n0, n1 in self._moves(pcs, m0, m1, b, s):
                if go(npcs, n0, n1)[1] > 0:
                    steps.append(label)
                    pcs, m0, m1 = npcs, n0, n1
                    break
        return steps, self._final(m0, m1)


def count_str(x: int) -> str:
    """Exact with separators up to 15 digits, then scientific: past that the
    exact digits carry no information and overflow the table."""
    return f"{x:,}" if x < 10**15 else f"{x:.3e}".replace("e+", "e")


def grid_str(v: int, n: int) -> str:
    return " / ".join("".join("#" if (v >> (r * n + c)) & 1 else "." for c in range(n)) for r in range(n))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="larger samples and a third generation")
    args = ap.parse_args()

    # (side, threads, generations, initial grids, protocols). The largest
    # instance runs only the barrier protocol by default: its state space
    # stays small because its phases commute, while the broken protocols'
    # state spaces explode there (no_barrier took 87 s; in_place ran over
    # nine minutes without finishing). The broken protocols run on every
    # other instance, which is what shows the explorer can see bugs.
    everything = PROTOCOLS
    plan = [
        (3, 1, 2, "all", everything),
        (3, 2, 2, "all", everything),
        (3, 3, 2, "all", everything),
        (4, 2, 2, 16, everything),
        (4, 4, 2, 2, ("barrier",)),
    ]
    if args.full:
        plan = [(3, 1, 3, "all", everything), (3, 2, 3, "all", everything),
                (3, 3, 3, "all", everything), (4, 2, 2, 128, everything),
                (4, 4, 2, 2, ("barrier", "no_barrier"))]

    for n in sorted({p[0] for p in plan}):
        self_check(n)
    print("Explorer self-check: one-cell update equals golden_rule.py on every grid "
          f"of side {', '.join(str(n) for n in sorted({p[0] for p in plan}))}, all {len(RULES)} rules.\n",
          flush=True)

    rng = random.Random(20260910)
    header = (f"{'torus':<6}{'T':>3}{'gens':>6}  {'protocol':<11}{'grids':>13}{'rules':>7}"
              f"{'schedules explored':>22}{'wrong':>20}{'':>9}   {'time':>6}   verdict")
    print(header)
    print("-" * len(header))

    status = 0
    witness = None
    t_start = time.time()
    for n, T, G, grids, protocols in plan:
        space = 1 << (n * n)
        inits = list(range(space)) if grids == "all" else rng.sample(range(space), grids)
        grid_label = f"{len(inits)} of {space}"
        for protocol in protocols:
            if protocol == "no_barrier" and T == 1:
                continue  # one thread cannot race; the row would say nothing
            inst = Instance(n, T, G, protocol)
            total = wrong = 0
            t_row = time.time()
            for name in RULES:
                b, s = rule_masks(name)
                for init in inits:
                    want = golden_after(init, n, b, s, G)
                    (tot, bad), go = inst.explore(init, b, s, want)
                    total += tot
                    wrong += bad
                    if bad and witness is None and protocol == "no_barrier":
                        steps, got = inst.counterexample(init, b, s, want, go)
                        witness = (n, T, G, name, init, want, got, steps)
                    go.cache_clear()

            if protocol == "barrier":
                verdict = "every schedule matches golden" if wrong == 0 else "FAILED"
                if wrong:
                    status = 1
            else:
                verdict = "counterexamples found" if wrong else "none found"
            pct = f"({100.0 * wrong / total:.1f}%)" if total else ""
            print(f"{n}x{n:<4}{T:>3}{G:>6}  {protocol:<11}{grid_label:>13}{len(RULES):>7}"
                  f"{count_str(total):>22}{count_str(wrong):>20} {pct:>8}   {time.time() - t_row:>5.1f}s"
                  f"   {verdict}", flush=True)

    print(f"\n{time.time() - t_start:.1f} s total")

    if witness is None:
        print("\nno counterexample for no_barrier: the explorer is not seeing races")
        status = 1
    else:
        n, T, G, name, init, want, got, steps = witness
        print(f"\nA concrete wrong schedule (no_barrier, {n}x{n}, T={T}, {name}, {G} generations):")
        print(f"  start   {grid_str(init, n)}")
        for i, step in enumerate(steps, 1):
            print(f"  {i:>3}.  {step}")
        print(f"  golden  {grid_str(want, n)}")
        print(f"  got     {grid_str(got, n)}")

    print("\nRESULT:", "barrier protocol correct on every explored schedule; both broken "
          "protocols produce counterexamples" if status == 0 else "FAILED")
    return status


if __name__ == "__main__":
    sys.exit(main())
