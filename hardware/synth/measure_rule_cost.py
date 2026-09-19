#!/usr/bin/env python3
"""
measure_rule_cost.py

What does making the rule runtime-selectable actually cost in silicon?

ca_cell.v welds Conway B3/S23 into two comparators. ca_cell_rule.v replaces
those with a 2-to-1 mux over 9 bits (pick the mask with `state`) feeding a
9-to-1 mux (index it with `count`). The popcount adder tree, which dominates
the cell, is identical in both. So the expectation is a small per-cell
delta, and this script measures it instead of asserting it.

Four builds, all with -nowidelut:

  ca_grid           the Phase 3 fabric, fixed Conway
  ca_grid_rule      the same fabric with two 9-bit masks broadcast in
  cellnet_top RULE_CFG=0    full flashable chip, fixed rule
  cellnet_top RULE_CFG=1    full flashable chip, rule_loader included

The comparison that decides which bitstream to build at a given grid size
is the last two rows: whether the configurable chip still fits.

Needs yosys on PATH (oss-cad-suite). Run from hardware/synth/:

    python3 measure_rule_cost.py
    python3 measure_rule_cost.py --sizes 8 16 32
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure_resources import synth, analyze, BUDGET_LUT4, BUDGET_FF

GRID_FIXED = ["ca_cell.v", "ca_grid.v"]
GRID_RULE = ["ca_cell_rule.v", "ca_grid_rule.v"]
TOP_SOURCES = [
    "ca_cell.v", "ca_grid.v",
    "ca_cell_rule.v", "ca_grid_rule.v",
    "uart_tx.v", "uart_rx.v",
    "seed_loader.v", "rule_loader.v",
    "grid_streamer.v", "cellnet_top.v",
]


def yosys_version() -> str:
    """The exact synthesiser these numbers came from. Cell counts move
    between yosys releases, so a figure without its version is not
    comparable to anything."""
    out = subprocess.run(["yosys", "-V"], capture_output=True, text=True)
    return out.stdout.strip().splitlines()[0] if out.returncode == 0 else "unknown"


def measure(top, rows, cols, sources, params=None):
    return analyze(synth(top, rows, cols, sources, nowidelut=True, params=params))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[8, 16, 24, 32],
                    help="square grid sizes to measure")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the raw measurements here, with the "
                         "yosys version that produced them")
    args = ap.parse_args()

    if not shutil.which("yosys"):
        sys.exit("yosys not on PATH. Install oss-cad-suite and put its bin/ "
                 "on PATH, then rerun. Nothing here can be estimated honestly "
                 "without it.")

    print(f"Target: Gowin GW2A-18, {BUDGET_LUT4:,} LUT4, {BUDGET_FF:,} FF")
    print("Cost of a runtime-selectable rule, all builds -nowidelut.\n")

    header = (f"{'grid':>9} {'cells':>6} | {'grid fixed':>10} {'grid rule':>10} "
              f"{'d/cell':>7} | {'top fixed':>10} {'top rule':>10} {'d/cell':>7} "
              f"| {'rule %':>7} {'fits':>5}")
    print(header)
    print("-" * len(header))

    record = {"yosys": yosys_version(), "budget_lut4": BUDGET_LUT4,
              "budget_ff": BUDGET_FF, "nowidelut": True, "sizes": {}}

    for n in args.sizes:
        cells = n * n
        gf = measure("ca_grid", n, n, GRID_FIXED)
        gr = measure("ca_grid_rule", n, n, GRID_RULE)
        tf = measure("cellnet_top", n, n, TOP_SOURCES, {"RULE_CFG": 0})
        tr = measure("cellnet_top", n, n, TOP_SOURCES, {"RULE_CFG": 1})

        d_grid = (gr["lut4_equiv"] - gf["lut4_equiv"]) / cells
        d_top = (tr["lut4_equiv"] - tf["lut4_equiv"]) / cells
        pct = 100.0 * tr["lut4_equiv"] / BUDGET_LUT4
        fits = "yes" if (tr["lut4_equiv"] <= BUDGET_LUT4
                         and tr["ffs"] <= BUDGET_FF) else "NO"

        print(f"{n:>4}x{n:<4} {cells:>6} | {gf['lut4_equiv']:>10,} "
              f"{gr['lut4_equiv']:>10,} {d_grid:>7.2f} | {tf['lut4_equiv']:>10,} "
              f"{tr['lut4_equiv']:>10,} {d_top:>7.2f} | {pct:>6.1f}% {fits:>5}")

        record["sizes"][f"{n}x{n}"] = {
            "cells": cells,
            "grid_fixed": gf, "grid_rule": gr,
            "top_fixed": tf, "top_rule": tr,
            "delta_lut4_per_cell_grid": d_grid,
            "delta_lut4_per_cell_top": d_top,
            "top_rule_budget_pct": pct,
            "top_rule_fits_pre_route": fits == "yes",
        }

        for label, a in (("grid rule", gr), ("top rule", tr)):
            if a["unknown"]:
                print(f"          {label}: unmapped primitives "
                      f"(check LUT_COST): {a['unknown']}")

    print()
    print("d/cell is the extra LUT4-equivalents per cell the configurable rule")
    print("costs. The popcount adder tree is identical in both fabrics; only the")
    print("rule lookup differs, so this is the price of the two muxes.")
    print()
    print("If the configurable chip stops fitting at the size you want, build the")
    print("fixed one:  RULE_CFG=0 ./synth/build_bitstream.sh <rows> <cols>")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w") as fh:
            json.dump(record, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
