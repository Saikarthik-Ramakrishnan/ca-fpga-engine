#!/usr/bin/env python3
"""
measure_top.py

Synthesizes the complete flashable chip (cellnet_top with UART in and
out, seed loader, pacer) with -nowidelut, and reports what Phase 4.5
adds on top of the bare grid that measure_resources.py already measured.

Why this needed its own measurement instead of assuming "UART is tiny":
two of the new costs scale WITH the grid, not with the UART.

  1. seed_loader holds a full grid snapshot: one extra register per cell.
  2. The generation pacer feeds grid state back through the seed input
     (the hold trick), so the per-cell load mux now has a real 2:1 mux
     behind it selecting loader-seed vs own-state: extra LUTs per cell.

So the honest per-cell figure for the flashable chip is higher than the
13.6 LUT4-equivalents measured for the bare fabric, and the real grid
ceiling moves. This script reports by how much, from actual synthesis,
not estimates. Run from hardware/synth/:  python3 measure_top.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure_resources import synth, analyze, BUDGET_LUT4, BUDGET_FF

SOURCES = [
    "ca_cell.v", "ca_grid.v",
    "uart_tx.v", "uart_rx.v",
    "seed_loader.v", "grid_streamer.v",
    "cellnet_top.v",
]

GRID_SOURCES = ["ca_cell.v", "ca_grid.v"]


def main():
    sizes = [(8, 8), (16, 16), (24, 24), (32, 32)]

    print(f"Target: Gowin GW2A-18, {BUDGET_LUT4} LUT4, {BUDGET_FF} FF")
    print("Full flashable cellnet_top vs bare ca_grid, both -nowidelut.\n")

    header = (f"{'grid':>9} {'cells':>6} | {'grid LUT4':>9} {'top LUT4':>9} "
              f"{'delta':>7} {'d/cell':>7} | {'top FF':>7} {'FF/cell':>8} "
              f"| {'LUT %':>6} {'fit':>4}")
    print(header)
    print("-" * len(header))

    for rows, cols in sizes:
        n = rows * cols
        grid = analyze(synth("ca_grid", rows, cols, GRID_SOURCES,
                             nowidelut=True))
        top = analyze(synth("cellnet_top", rows, cols, SOURCES,
                            nowidelut=True))
        delta = top["lut4_equiv"] - grid["lut4_equiv"]
        pct = 100.0 * top["lut4_equiv"] / BUDGET_LUT4
        fit = "yes" if (top["lut4_equiv"] <= BUDGET_LUT4
                        and top["ffs"] <= BUDGET_FF) else "NO"
        print(f"{rows:>4}x{cols:<4} {n:>6} | {grid['lut4_equiv']:>9} "
              f"{top['lut4_equiv']:>9} {delta:>7} {delta / n:>7.2f} | "
              f"{top['ffs']:>7} {top['ffs'] / n:>8.2f} | {pct:>5.1f}% "
              f"{fit:>4}")
        if top["unknown"]:
            print(f"          unmapped primitives (check LUT_COST table): "
                  f"{top['unknown']}")


if __name__ == "__main__":
    main()
