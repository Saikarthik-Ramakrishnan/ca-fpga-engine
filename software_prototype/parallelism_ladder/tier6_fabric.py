#!/usr/bin/env python3
"""
tier6_fabric.py

Tiers 1 to 5 are five ways of running the rule on a CPU, and every one of
them gets slower as the grid grows. This adds the tier the project exists
to argue for, and puts a number on the difference.

WHAT THIS IS, EXACTLY
---------------------
This is a throughput model, not a measurement of a running board. It has
no board to measure. Every input is a number already measured and recorded
in this repo:

  - software generations per second: results.csv, produced by benchmark.py
    on this machine and verified against golden_rule.py first.
  - fabric clock: 27 MHz, the Tang Primer 20K dock oscillator.
  - routed Fmax: nextpnr post-route static timing analysis, Phase 5a,
    240.38 MHz at 16x16 and 176.46 MHz at 32x32.
  - per-cell area: 13.6 LUT4-equivalents, measured by measure_resources.py
    with -nowidelut, consistent at every grid size.

The one modelling step is the line that matters most, and it is a
structural fact rather than an estimate: the fabric computes one whole
generation per clock edge, so its generations per second equals its clock
frequency and does not depend on the grid size. Every cell has its own
copy of the rule; adding cells adds area, not time. That is the entire
thesis, and it is what the flat row in the table below shows.

WHAT THIS IS NOT
----------------
Not a head-to-head benchmark. The software numbers come from a running
CPU; the fabric numbers come from timing analysis of a placed and routed
design that has not yet been flashed. Comparing them is fair for
throughput and unfair to nobody, but it is a comparison of a measurement
against a model, and it is labelled that way everywhere it appears.

Nor is it what you can watch. The UART reports roughly 350 frames per
second at 16x16 and 115200 baud, and the generation pacer deliberately
runs the fabric at 10 generations per second so a human can follow it.
The rate below is what the silicon computes, not what leaves the chip.

  python3 tier6_fabric.py            # table to stdout
  python3 tier6_fabric.py --csv      # also write fabric_comparison.csv
  python3 tier6_fabric.py --plot     # also write ladder_with_fabric.png
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.csv")

# ---- measured constants, all sourced from this repo ----
DOCK_CLOCK_HZ = 27_000_000          # Tang Primer 20K oscillator, pin H11
LUT4_PER_CELL = 13.6                # measure_resources.py, -nowidelut
BUDGET_LUT4 = 20_736                # Gowin GW2A-18
ROUTED_FMAX_HZ = {                  # nextpnr post-route STA, Phase 5a
    16: 240_380_000,
    32: 176_460_000,
}
FULL_CHIP_CEILING = 32              # largest square full chip that fits


def load_software_results(path: str):
    """results.csv -> {grid_n: [(tier, gen_per_sec), ...]}"""
    if not os.path.exists(path):
        sys.exit(f"missing {path}. Run: python3 benchmark.py")
    by_grid = defaultdict(list)
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            by_grid[int(row["grid_n"])].append(
                (row["tier"], float(row["gen_per_sec"]))
            )
    return dict(by_grid)


def fabric_fits(n: int) -> bool:
    return n <= FULL_CHIP_CEILING


def fabric_lut4(n: int) -> float:
    return n * n * LUT4_PER_CELL


def human(x: float) -> str:
    for unit, div in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if x >= div:
            return f"{x / div:,.1f}{unit}"
    return f"{x:,.0f}"


def build_rows(by_grid):
    rows = []
    for n in sorted(by_grid):
        tiers = by_grid[n]
        best_tier, best_rate = max(tiers, key=lambda t: t[1])
        cells = n * n
        fits = fabric_fits(n)
        # one generation per clock edge, independent of grid size
        fabric_rate = DOCK_CLOCK_HZ if fits else None
        rows.append({
            "grid_n": n,
            "cells": cells,
            "best_tier": best_tier,
            "best_gen_per_sec": best_rate,
            "best_cell_updates_per_sec": best_rate * cells,
            "fits_on_gw2a18": fits,
            "lut4_required": fabric_lut4(n),
            "fabric_gen_per_sec": fabric_rate,
            "fabric_cell_updates_per_sec": (
                fabric_rate * cells if fabric_rate else None),
            "speedup_vs_best_software": (
                fabric_rate / best_rate if fabric_rate else None),
        })
    return rows


def print_table(rows):
    print("Tier 6: the FPGA fabric, against the fastest software tier at each size")
    print("Fabric clocked at the 27 MHz dock oscillator, one generation per clock.\n")

    header = (f"{'grid':>7} {'cells':>7} | {'best software':>15} {'gen/s':>10} "
              f"{'cell upd/s':>11} | {'fabric gen/s':>12} {'cell upd/s':>11} "
              f"{'speedup':>9} | {'fits':>5}")
    print(header)
    print("-" * len(header))

    for r in rows:
        if r["fits_on_gw2a18"]:
            fab_gen = human(r["fabric_gen_per_sec"])
            fab_cell = human(r["fabric_cell_updates_per_sec"])
            speed = f"{r['speedup_vs_best_software']:,.0f}x"
            fits = "yes"
        else:
            fab_gen = fab_cell = speed = "-"
            fits = "NO"
        print(f"{r['grid_n']:>4}x{r['grid_n']:<2} {r['cells']:>7} | "
              f"{r['best_tier']:>15} {r['best_gen_per_sec']:>10,.0f} "
              f"{human(r['best_cell_updates_per_sec']):>11} | "
              f"{fab_gen:>12} {fab_cell:>11} {speed:>9} | {fits:>5}")

    print()
    print("Reading the table:")
    print("  - Every software tier slows down as the grid grows. The fabric column")
    print("    does not move: more cells is more area, not more time.")
    print("  - So the gap is not one number. It widens with grid size, which is the")
    print("    claim the project is actually making.")

    over = [r for r in rows if not r["fits_on_gw2a18"]]
    if over:
        print()
        print("  - Where the fabric loses: capacity. These do not fit on the GW2A-18")
        print(f"    ({BUDGET_LUT4:,} LUT4 at {LUT4_PER_CELL} per cell):")
        for r in over:
            need = r["lut4_required"]
            print(f"      {r['grid_n']}x{r['grid_n']} needs {need:>10,.0f} LUT4, "
                  f"{need / BUDGET_LUT4:.1f}x the budget")
        print("    Software has no such wall. It just gets slower.")

    print()
    print("Headroom, from routed timing rather than the dock clock:")
    for n, fmax in sorted(ROUTED_FMAX_HZ.items()):
        cells = n * n
        print(f"  {n}x{n} closed at {fmax / 1e6:,.2f} MHz post-route, "
              f"{fmax / DOCK_CLOCK_HZ:.1f}x the 27 MHz requirement "
              f"({human(fmax * cells)} cell updates/s if clocked there)")
    print("  The dock oscillator is what binds on this board, not the fabric.")

    print()
    print("What you can actually watch is far slower, on purpose:")
    print("  - UART at 115200 8N1 carries about 350 frames/s at 16x16.")
    print("  - GEN_DIV holds the fabric to 10 generations/s by default.")
    print("  - The rate above is what the silicon computes, not what leaves the chip.")

    print()
    print("Modelled, not measured on hardware: the software numbers are timings from")
    print("a running CPU, the fabric numbers come from post-route timing analysis of")
    print("a design that has not been flashed yet. Phase 5b closes that gap.")

    print()
    print("Baseline caveat: the software rows are the Python tiers. The bit-sliced C++")
    print("engine (software_prototype/cpp) is about 75x faster per core than Numba here,")
    print("and against it the dock-clock factor is 2.6x at 16x16 and 5.3x at 32x32.")
    print("The speedups printed above overstate the gap; see")
    print("software_prototype/cpp/results/laptop_vs_fpga.md.")


def write_csv(rows, path):
    fields = list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote {path}")


def write_plot(by_grid, rows, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not installed, skipping the plot")
        return

    series = defaultdict(list)
    for n in sorted(by_grid):
        for tier, rate in by_grid[n]:
            series[tier].append((n, rate))

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for tier, points in series.items():
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, marker="o", linewidth=1.4, label=tier)

    fab = [r for r in rows if r["fits_on_gw2a18"]]
    ax.plot([r["grid_n"] for r in fab],
            [r["fabric_gen_per_sec"] for r in fab],
            marker="s", linewidth=2.4, color="#F2C14E",
            label="fpga fabric (27 MHz, modelled)")

    ax.axvline(FULL_CHIP_CEILING, color="#B33A0F", linestyle="--", linewidth=1.2)
    ax.annotate(f"GW2A-18 full-chip ceiling\n{FULL_CHIP_CEILING}x{FULL_CHIP_CEILING}",
                xy=(FULL_CHIP_CEILING, ax.get_ylim()[1]),
                xytext=(-6, -46), textcoords="offset points",
                ha="right", fontsize=8, color="#B33A0F")

    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("grid size N (NxN)")
    ax.set_ylabel("generations per second")
    ax.set_title("Parallelism ladder: five software tiers and the fabric")
    ax.grid(True, which="both", alpha=0.25, linewidth=0.6)
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true",
                    help="write fabric_comparison.csv")
    ap.add_argument("--plot", action="store_true",
                    help="write ladder_with_fabric.png")
    args = ap.parse_args()

    by_grid = load_software_results(RESULTS)
    rows = build_rows(by_grid)
    print_table(rows)

    if args.csv:
        write_csv(rows, os.path.join(HERE, "fabric_comparison.csv"))
    if args.plot:
        write_plot(by_grid, rows, os.path.join(HERE, "ladder_with_fabric.png"))


if __name__ == "__main__":
    main()
