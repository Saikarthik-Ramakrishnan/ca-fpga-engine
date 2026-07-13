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


def main():
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "ca_grid_netlist.v")

    script = (
        f"read_verilog {os.path.join(RTL, 'ca_cell.v')} {os.path.join(RTL, 'ca_grid.v')}; "
        f"chparam -set ROWS {ROWS} -set COLS {COLS} ca_grid; "
        f"synth_gowin -top ca_grid -nowidelut; "
        f"write_verilog -noattr {out}"
    )
    r = subprocess.run(["yosys", "-p", script], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-1000:], file=sys.stderr)
        raise SystemExit("yosys failed")

    print(f"Wrote {out}  ({ROWS}x{COLS}, -nowidelut mapping)")
    print("Now run:  cd ../tests && make -f Makefile.postsynth")


if __name__ == "__main__":
    main()
