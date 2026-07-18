# Synthesis and resource analysis

Question answered here: maximum grid size on the target, and the clock it
runs at.

```bash
python3 measure_resources.py   # sweeps grid sizes, compares mappings
python3 measure_top.py         # full flashable chip vs bare grid
python3 emit_netlist.py        # gate-level netlist for post-synth sim
./build_bitstream.sh           # RTL to .fs, timing-checked (run from hardware/)
```

Target: Gowin GW2A-18, Tang Primer 20K. 20,736 LUT4, 15,552 registers.

## 4.9x saving from one synthesis flag

- Initial estimate: ~66 LUT4-equivalents per cell, ceiling near 22x22.
- One cell is 9 inputs, 1 output; generic synthesis produces 33 gates.
  Expected LUT4 count: under 20.
- `synth_gowin` default maps the count comparison to wide muxes
  (MUX2_LUT5/6/7 at 2, 4, and 8 LUT4 each), dominating the design.
- `-nowidelut` forces plain LUT decomposition.

| grid | cells | default LUT4 | /cell | nowidelut LUT4 | /cell | saving |
|---|---|---|---|---|---|---|
| 8x8 | 64 | 4,200 | 65.6 | 874 | 13.7 | 4.8x |
| 16x16 | 256 | 16,974 | 66.3 | 3,476 | 13.6 | 4.9x |
| 20x20 | 400 | 26,490 (128%, no fit) | 66.2 | 5,436 (26%) | 13.6 | 4.9x |
| 24x24 | 576 | 38,214 (184%, no fit) | 66.3 | 7,830 (38%) | 13.6 | 4.9x |
| 32x32 | 1,024 | 67,974 (328%, no fit) | 66.4 | 13,924 (67%) | 13.6 | 4.9x |

- 13.6 LUT4 per cell at every size.
- Bare-grid ceiling: 38x38 (19,629 LUT4, 95% of budget), 1,444 cells.
- These are pre-route LUT4-equivalent estimates. Routed results for the full
  chip are in Phase 5a of `hardware/README.md`: the 32x32 full chip placed,
  routed, and closed timing on the real device model.

## Gate-level verification

- `emit_netlist.py` writes the netlist `synth_gowin -nowidelut` produces.
- `tests/Makefile.postsynth` runs the grid testbench against that netlist
  with Gowin primitive models (`cells_sim.v`).
- Four random-seed trials, 15 generations each, matched `golden_rule.py` bit
  for bit.

```bash
cd hardware/synth && python3 emit_netlist.py
cd ../tests && make -f Makefile.postsynth
```

## Clock speed vs grid size

- Register-to-register critical path inside one cell: logic depth 11,
  independent of grid size.
- Each cell reads neighbor registers and writes its own register. No signal
  crosses more than one cell per clock.
- Grid growth costs area; Fmax is unchanged. Confirmed by routed results:
  240 MHz at 16x16, 176 MHz at 32x32, both far above the 27 MHz requirement
  (the 32x32 drop comes from routing congestion at 72% utilization).
- `yosys ltp` reports a longer path on the full grid because the torus wraps
  topologically through every cell. That trace crosses registers and is
  therefore excluded from timing.

## Files

- `cellnet_primer20k.cst`: dock pin constraints, sourced from Sipeed example
  projects. clk H11, rst_n T5, tx M11, rx T13, leds L16/L14.
- `cellnet_primer20k.sdc`: 27 MHz clock constraint for the Gowin EDA flow.
- `build_bitstream.sh`: yosys, nextpnr-himbaechel, gowin_pack. Any grid size.
