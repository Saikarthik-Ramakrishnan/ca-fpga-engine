# Synthesis and resource analysis

Answers the question the whole project hinges on: how big a grid actually fits
on the target FPGA, and how fast can it run?

```bash
python3 measure_resources.py   # sweeps grid sizes, compares mappings
python3 emit_netlist.py        # writes the gate-level netlist for post-synth sim
```

Target: Gowin GW2A-18 on the Tang Primer 20K. 20,736 LUT4, 15,552 registers.

## The finding: a 4.9x saving from one synthesis flag

- The first estimate capped the grid at ~17x17 to ~22x22, based on ~66
  LUT4-equivalents per cell. Real number, badly mapped circuit.
- One cell's logic is tiny: 9 inputs (own state + 8 neighbors), 1 output.
  Generic synthesis (no vendor mapping) turns `ca_cell` into 33 gates. That
  should map to well under 20 LUT4s.
- `synth_gowin`'s default mapping was instead building a tree of wide muxes
  (MUX2_LUT5/6/7) to implement the count comparison. On Gowin those cost 2, 4,
  and 8 LUT4s respectively, and they dominated everything.
- `-nowidelut` forbids that mapping and forces plain LUT decomposition.

| grid | cells | default LUT4 | /cell | nowidelut LUT4 | /cell | saving |
|---|---|---|---|---|---|---|
| 8x8 | 64 | 4,200 | 65.6 | 874 | 13.7 | 4.8x |
| 16x16 | 256 | 16,974 | 66.3 | 3,476 | 13.6 | 4.9x |
| 20x20 | 400 | 26,490 (128%, no fit) | 66.2 | 5,436 (26%) | 13.6 | 4.9x |
| 24x24 | 576 | 38,214 (184%, no fit) | 66.3 | 7,830 (38%) | 13.6 | 4.9x |
| 32x32 | 1,024 | 67,974 (328%, no fit) | 66.4 | 13,924 (67%) | 13.6 | 4.9x |

- Cost per cell drops from ~66 to ~13.6 LUT4-equivalents, consistently, at
  every size.
- **The real ceiling is 38x38** (19,629 LUT4, 95% of budget), not 22x22. That's
  1,444 cells instead of ~484: roughly 3x the grid, enough to run the
  40x40-class grid the console was originally built around.
- Caveat: these are synthesis estimates. Real place-and-route on the device
  (Gowin's own toolchain, once the board is in hand) is what finally settles
  it. Routing congestion at 95% utilization is a real risk, so **32x32 (67% of
  budget) is the safer target to flash first**.

## Verifying the optimization did not break anything

A smaller design that computes the wrong thing is worthless, so this was
checked against behavior, not just size.

- `emit_netlist.py` writes the actual gate-level netlist that
  `synth_gowin -nowidelut` produces.
- `hardware/tests/Makefile.postsynth` runs the existing grid testbench against
  **that netlist**, wired up with Gowin's own primitive simulation models
  (`cells_sim.v`), instead of against the RTL.
- All four random-seed trials, 15 generations each, matched `golden_rule.py`
  bit for bit at the gate level.
- Stronger claim than the RTL tests alone: it verifies what synthesis actually
  produced, not just what the source says.

```bash
cd hardware/synth && python3 emit_netlist.py
cd ../tests && make -f Makefile.postsynth
```

## Why max clock speed does not drop as the grid grows

- The critical path (register to register, through logic) inside one cell has a
  logic depth of **11**, and that number is **independent of grid size**.
- Each cell reads its eight neighbors' *registers* and writes its own
  *register*. No signal propagates through more than one cell in a single clock
  cycle.
- A 38x38 grid has the same critical path as an 8x8 one, so it runs at the same
  clock speed.
- This is the project thesis as a number: growing the grid costs area, not
  time. Software doing the same work gets linearly slower. This does not.
- Note: `yosys`'s `ltp` reports a much larger path for the full grid, because
  the grid is a torus and every cell feeds its neighbors, so tracing
  topologically finds a path wrapping the entire fabric. That path crosses
  registers, so it isn't a real timing path. The per-cell number is the one
  that matters.
