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
- The bare grid can reach 38x38. The complete chip, including the serial interface and seed storage, reaches 32x32. The default build is 16x16.

## Timing After Place and Route

Figures are from nextpnr post-route static timing analysis against the 27 MHz requirement.

| Build | Fmax | LUT4 | ALU | Flip-flops |
|---|---|---|---|---|
| 16x16 | 240.38 MHz | 19% | 7% | 5% |
| 32x32 | 176.46 MHz | 72% | 27% | 20% |

- Both builds meet the 27 MHz requirement with a wide margin.
- The routed utilization is lower than the estimate above because nextpnr maps the adder trees onto dedicated ALU carry cells. Both accountings are reported, and the routed figure is the one that applies to the device.
- The critical path inside a cell is 11 logic levels regardless of grid size, so a larger grid costs area and leaves the clock rate largely unchanged.

## Pending Measurement

The configurable-rule build described in [Runtime rule configuration](RULE_CONFIGURATION.md) has not yet been synthesized. Its area will be measured with `python3 hardware/synth/measure_rule_cost.py` on a machine with the Yosys toolchain.

The full methodology is in [`hardware/synth/README.md`](../hardware/synth/README.md).
