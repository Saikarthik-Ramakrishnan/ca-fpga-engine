#!/usr/bin/env python3
"""
measure_resources.py

Synthesizes ca_grid at several sizes and reports what each one actually
costs on the target FPGA, so grid-size decisions are made against real
numbers instead of guesses.

Why this exists: Yosys reports a "number of cells" total, but that mixes
things with very different real costs. A LUT4 is one lookup table. A
MUX2_LUT5 is built from LUT4s plus mux hardware. On Gowin parts, LUT5/6/7/8
muxes consume the LUT resources of the smaller LUTs they're composed from.
Counting raw Yosys cells therefore understates real usage. This script maps
each primitive to its LUT4-equivalent cost and totals honestly.

Target: Gowin GW2A-18 (Tang Primer 20K), ~20,736 LUT4 and ~15,552 registers.
"""

import re
import subprocess
import sys
import os
import tempfile

RTL_DIR = os.path.join(os.path.dirname(__file__), "..", "rtl")

# Gowin GW2A-18 (Tang Primer 20K)
BUDGET_LUT4 = 20736
BUDGET_FF = 15552

# LUT4-equivalent cost of each Yosys/Gowin primitive.
# LUT5 = 2x LUT4 + mux; LUT6 = 2x LUT5; LUT7 = 2x LUT6; LUT8 = 2x LUT7.
# ALU on Gowin occupies a LUT slot.
LUT_COST = {
    "LUT1": 1,
    "LUT2": 1,
    "LUT3": 1,
    "LUT4": 1,
    "ALU": 1,
    "MUX2_LUT5": 2,
    "MUX2_LUT6": 4,
    "MUX2_LUT7": 8,
    "MUX2_LUT8": 16,
}
FF_CELLS = {"DFF", "DFFC", "DFFE", "DFFCE", "DFFP", "DFFPE", "DFFR", "DFFRE",
            "DFFS", "DFFSE", "DFFN", "DFFNC"}
# not logic: IO buffers and constants
IGNORE = {"IBUF", "OBUF", "GND", "VCC", "TBUF", "IOBUF"}


def synth(top: str, rows: int, cols: int, sources: list, nowidelut: bool = False) -> dict:
    """Run yosys synth_gowin with the given grid parameters, return primitive counts."""
    src_paths = " ".join(os.path.join(RTL_DIR, s) for s in sources)
    flags = " -nowidelut" if nowidelut else ""
    script = (
        f"read_verilog {src_paths}; "
        f"chparam -set ROWS {rows} -set COLS {cols} {top}; "
        f"synth_gowin -top {top}{flags}"
    )
    result = subprocess.run(
        ["yosys", "-p", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"yosys failed for {rows}x{cols}")

    # parse the final "Number of cells" block
    counts = {}
    in_block = False
    for line in result.stdout.splitlines():
        if re.search(r"Number of cells:", line):
            in_block = True
            counts = {}  # keep only the last (top-level) block
            continue
        if in_block:
            m = re.match(r"\s+(\w+)\s+(\d+)\s*$", line)
            if m:
                counts[m.group(1)] = int(m.group(2))
            elif line.strip() == "":
                continue
            else:
                in_block = False
    return counts


def analyze(counts: dict) -> dict:
    luts = 0
    ffs = 0
    unknown = {}
    for cell, n in counts.items():
        if cell in LUT_COST:
            luts += LUT_COST[cell] * n
        elif cell in FF_CELLS:
            ffs += n
        elif cell in IGNORE:
            pass
        else:
            unknown[cell] = n
    return {"lut4_equiv": luts, "ffs": ffs, "unknown": unknown}


def main():
    sizes = [(8, 8), (16, 16), (20, 20), (24, 24), (28, 28), (32, 32)]
    sources = ["ca_cell.v", "ca_grid.v"]

    print(f"Target: Gowin GW2A-18, {BUDGET_LUT4} LUT4, {BUDGET_FF} FF")
    print("Comparing synth_gowin default mapping vs -nowidelut.\n")

    header = (f"{'grid':>9} {'cells':>6} | {'default LUT4':>12} {'/cell':>6} {'%':>6} {'fit':>4}"
              f" | {'nowidelut':>10} {'/cell':>6} {'%':>6} {'fit':>4} | {'saving':>7}")
    print(header)
    print("-" * len(header))

    for rows, cols in sizes:
        n_cells = rows * cols
        row = f"{rows:>4}x{cols:<4} {n_cells:>6} |"

        results = {}
        for label, nowide in (("default", False), ("nowidelut", True)):
            try:
                counts = synth("ca_grid", rows, cols, sources, nowidelut=nowide)
                a = analyze(counts)
                results[label] = a
            except RuntimeError:
                results[label] = None

        for label in ("default", "nowidelut"):
            a = results[label]
            if a is None:
                row += f" {'FAIL':>12} {'':>6} {'':>6} {'':>4} |"
                continue
            luts = a["lut4_equiv"]
            pct = 100.0 * luts / BUDGET_LUT4
            fits = "yes" if luts <= BUDGET_LUT4 and a["ffs"] <= BUDGET_FF else "NO"
            row += f" {luts:>12} {luts/n_cells:>6.1f} {pct:>5.0f}% {fits:>4} |"

        d, w = results["default"], results["nowidelut"]
        if d and w and w["lut4_equiv"]:
            row += f" {d['lut4_equiv']/w['lut4_equiv']:>6.1f}x"
        print(row)


if __name__ == "__main__":
    main()
