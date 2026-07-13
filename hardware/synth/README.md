# Synthesis and resource analysis

Tools for answering the question the whole project hinges on: how big a grid
actually fits on the target FPGA, and how fast can it run?

```bash
python3 measure_resources.py   # sweeps grid sizes, compares mappings
python3 emit_netlist.py        # writes the gate-level netlist for post-synth sim
```

Target is the Gowin GW2A-18 on the Tang Primer 20K: 20,736 LUT4, 15,552
registers.

## The finding: a 4.9x resource saving from one synthesis flag

The first resource estimate for this project put the maximum grid at roughly
17x17 to 22x22, based on a per-cell cost of about 66 LUT4-equivalents. That
number was real, but it was measuring a badly mapped circuit.

A single cell's logic is tiny. Generic synthesis (no vendor mapping) turns
`ca_cell` into 33 gates. There are 9 inputs (own state, 8 neighbors) and 1
output. That should map to well under 20 LUT4s.

Instead, `synth_gowin`'s default mapping was producing a tree of wide muxes
(MUX2_LUT5, MUX2_LUT6, MUX2_LUT7) to implement the count comparison. On
Gowin parts those cost 2, 4, and 8 LUT4s respectively, and they dominated
everything: 66 LUT4-equivalents to compute "count 8 bits, is it 2 or 3".

Passing `-nowidelut` forbids that mux mapping and forces plain LUT decomposition:

| grid | cells | default LUT4 | /cell | nowidelut LUT4 | /cell | saving |
|---|---|---|---|---|---|---|
| 8x8 | 64 | 4,200 | 65.6 | 874 | 13.7 | 4.8x |
| 16x16 | 256 | 16,974 | 66.3 | 3,476 | 13.6 | 4.9x |
| 20x20 | 400 | 26,490 (128%, does not fit) | 66.2 | 5,436 (26%) | 13.6 | 4.9x |
| 24x24 | 576 | 38,214 (184%, does not fit) | 66.3 | 7,830 (38%) | 13.6 | 4.9x |
| 32x32 | 1,024 | 67,974 (328%, does not fit) | 66.4 | 13,924 (67%) | 13.6 | 4.9x |

Cost per cell drops from ~66 to ~13.6 LUT4-equivalents, consistently, at
every size.

**The real ceiling is 38x38** (19,629 LUT4, 95% of budget), not 22x22. That
is 1,444 cells instead of about 484: roughly 3x the grid, and enough to run
the 40x40-class grid the software console was originally built around.

An honest caveat: these are synthesis estimates. Real place-and-route on the
actual device (via Gowin's own toolchain, once the board is in hand) is the
number that finally settles it. Routing congestion at 95% utilization is a
real risk, so 32x32 (67% of budget) is the safer target to flash first.

## Verifying the optimization did not break anything

A smaller design that computes the wrong thing is worthless, so the
optimization was checked against behavior, not just size.

`emit_netlist.py` writes the actual gate-level netlist that
`synth_gowin -nowidelut` produces. `hardware/tests/Makefile.postsynth` then
runs the existing grid testbench against **that netlist**, wired up with
Gowin's own primitive simulation models (`cells_sim.v`), instead of against
the RTL.

```bash
cd hardware/synth && python3 emit_netlist.py
cd ../tests && make -f Makefile.postsynth
```

All four random-seed trials, 15 generations each, matched `golden_rule.py`
bit for bit at the gate level. This is a stronger claim than the RTL tests
alone: it verifies what synthesis actually produced, not just what the
source code says.

## Why maximum clock speed does not drop as the grid grows

The critical path (register to register, through logic) inside one cell has
a logic depth of 11. That number is **independent of grid size**.

Each cell reads its eight neighbors' *registers* and writes its own
*register*. No signal ever propagates through more than one cell in a single
clock cycle. A 38x38 grid has exactly the same critical path as an 8x8 one,
so it runs at the same clock speed.

This is the architectural payoff of the whole project thesis, stated in a
number: growing the grid costs area, not time. Software doing the same work
gets linearly slower as the grid grows. This does not.

(Note: `yosys`'s `ltp` command reports a much larger path for the full grid,
because the grid is a torus and every cell feeds its neighbors, so tracing
topologically finds a path that wraps the entire fabric. That path is not a
real timing path, since it crosses registers. The per-cell number above is
the one that matters.)
