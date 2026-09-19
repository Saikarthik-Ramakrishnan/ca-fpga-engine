# FPGA Resource Utilization and Timing

This document reports how much of the Gowin GW2A-18 device each grid size uses and how fast the routed design can run.

## Device

The target is the Gowin GW2A-LV18PG256C8/I7 on the Sipeed Tang Primer 20K, which provides 20,736 LUT4 cells and 15,552 flip-flops. The board supplies a 27 MHz clock.

## Utilization Before Place and Route

Figures are LUT4 equivalents from `synth_gowin -nowidelut`.

| Grid | Cells | Grid only (LUT4) | Complete chip (LUT4) | Budget used | Fits |
|---|---|---|---|---|---|
| 8x8 | 64 | 874 | 1,951 | 9.4% | yes |
| 16x16 | 256 | 3,476 | 5,652 | 27.3% | yes |
| 24x24 | 576 | 7,830 | 11,675 | 56.3% | yes |
| 32x32 | 1,024 | 13,924 | 20,189 | 97.4% | yes |

- Each cell costs 13.6 LUT4 equivalents, and this figure holds at every grid size.
- The `-nowidelut` option is required. The default mapping uses wide multiplexers and costs 66 LUT4 per cell, which is 4.9 times more.
- The bare grid can reach 38x38. The complete chip with the rule welded into its gates, including the serial interface and seed storage, reaches 32x32. The default build is 16x16.
- Those ceilings are for the fixed-rule chip. The default bitstream is the configurable one, which is larger and reaches 25x25. The next section measures it.

## Timing After Place and Route

Figures are from nextpnr post-route static timing analysis against the 27 MHz requirement.

| Build | Fmax | LUT4 | ALU | Flip-flops |
|---|---|---|---|---|
| 16x16 | 240.38 MHz | 19% | 7% | 5% |
| 32x32 | 176.46 MHz | 72% | 27% | 20% |

- Both builds meet the 27 MHz requirement with a wide margin.
- The routed utilization is lower than the estimate above because nextpnr maps the adder trees onto dedicated ALU carry cells. Both accountings are reported, and the routed figure is the one that applies to the device.
- The critical path inside a cell is 11 logic levels regardless of grid size, so a larger grid costs area and leaves the clock rate largely unchanged.

## Cost of the Configurable Rule

The default bitstream builds `ca_grid_rule`, whose rule is 18 bits in a register rather than gates. Measuring what that costs was the last open question in this document, and the answer is larger than the design expected.

Figures are LUT4 equivalents from `synth_gowin -nowidelut`, Yosys 0.69.

| Grid | Fixed grid | Configurable grid | Extra per cell | Fixed chip | Configurable chip | Budget used | Fits |
|---|---|---|---|---|---|---|---|
| 8x8 | 705 | 1,665 | 15.0 | 1,138 | 2,274 | 11.0% | yes |
| 16x16 | 2,817 | 6,657 | 15.0 | 3,507 | 7,694 | 37.1% | yes |
| 24x24 | 6,337 | 14,977 | 15.0 | 7,983 | 17,892 | 86.3% | yes |
| 25x25 | 6,876 | 16,251 | 15.0 | 8,624 | 18,110 | 87.3% | yes |
| 26x26 | 7,437 | 17,577 | 15.0 | 9,319 | 20,891 | 100.7% | no |
| 32x32 | 11,265 | 26,625 | 15.0 | 13,914 | 28,551 | 137.7% | no |

- A fixed cell costs 11.0 LUT4 equivalents and a configurable one costs 26.0, so the runtime rule makes each cell 2.4 times larger.
- The extra 15.0 per cell is the price of a mux tree. Selecting one of nine neighbour counts from a register needs sixteen inputs reduced to one, and a tree of 2-to-1 muxes built from LUT4 cells costs fifteen of them. The popcount adder tree, which dominates the fixed cell, is identical in both fabrics.
- The configurable chip reaches 25x25 before it exceeds the device. The fixed chip is the one to build above that size, and `RULE_CFG=0` selects it.
- These are pre-route estimates. Place and route recovers a large margin on the fixed build by mapping adder trees onto dedicated ALU carry cells, so a configurable 26x26 may still route. Only a routed build settles it, and that needs nextpnr rather than Yosys alone.

Reproduce with:

```bash
python3 hardware/synth/measure_rule_cost.py --sizes 8 16 24 25 26 32 --json rule_cost.json
```

## A Note on Toolchain Versions

Cell counts move between Yosys releases, so a figure without its version is not comparable to anything.

- The utilization table above this section was produced by the Yosys inside oss-cad-suite, which mapped a fixed cell to 13.6 LUT4 equivalents.
- Yosys 0.69 maps the same cell to 11.0, which is 19% smaller, and narrows the `-nowidelut` saving from 4.9 times to 3.7 times. The option remains necessary: without it the same release spends 41.0 per fixed cell and 69.0 per configurable one.
- The routed figures are unaffected, because they come from nextpnr rather than from Yosys.
- Every number in this document is a pre-route estimate except the timing table, which is post-route and is the one that binds.

The full methodology is in [`hardware/synth/README.md`](../hardware/synth/README.md).
