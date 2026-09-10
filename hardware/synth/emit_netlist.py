#!/usr/bin/env python3
"""
emit_netlist.py

Writes the gate-level netlist that synth_gowin actually produces, so it can
be simulated directly (see hardware/tests/Makefile.postsynth).

Simulating the RTL proves the design is right. Simulating THIS proves the
synthesized gates are right, which is a different and stronger claim: it
catches anything the synthesis tool itself got wrong, and it's how the
-nowidelut optimization was verified to be behavior-preserving rather than
just smaller.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.join(HERE, "..", "rtl")
BUILD = os.path.join(HERE, "build")

ROWS = int(os.environ.get("ROWS", "8"))
COLS = int(os.environ.get("COLS", "8"))
# RULE=1 emits the configurable fabric (ca_grid_rule) instead of the fixed
# one, for tests/Makefile.postsynth_rule.
RULE = os.environ.get("RULE", "0") == "1"


def main():
    os.makedirs(BUILD, exist_ok=True)

    if RULE:
        top = "ca_grid_rule"
        sources = ["ca_cell_rule.v", "ca_grid_rule.v"]
        out = os.path.join(BUILD, "ca_grid_rule_netlist.v")
    else:
        top = "ca_grid"
        sources = ["ca_cell.v", "ca_grid.v"]
        out = os.path.join(BUILD, "ca_grid_netlist.v")

    src_paths = " ".join(os.path.join(RTL, f) for f in sources)
    script = (
        f"read_verilog {src_paths}; "
        f"chparam -set ROWS {ROWS} -set COLS {COLS} {top}; "
        f"synth_gowin -top {top} -nowidelut; "
        f"write_verilog -noattr {out}"
    )
    r = subprocess.run(["yosys", "-p", script], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-1000:], file=sys.stderr)
        raise SystemExit("yosys failed")

    print(f"Wrote {out}  ({top}, {ROWS}x{COLS}, -nowidelut mapping)")
    if RULE:
        print("Now run:  cd ../tests && make -f Makefile.postsynth_rule")
    else:
        print("Now run:  cd ../tests && make -f Makefile.postsynth")


if __name__ == "__main__":
    main()
