# Verification Strategy

This document describes how the hardware and software are tested and what each test suite establishes.

## Principles

- Every test compares against `golden_rule.py`, the project's single reference model for the automaton.
- Tests are exhaustive wherever the input space allows, and they are designed to fail when a protection is removed, which confirms that they can detect the faults they are meant to catch.
- Everything described here runs in simulation and requires no FPGA.

## Hardware: 32 Tests Across 14 Suites

```bash
cd hardware/tests && ./run_all.sh
```

| Suite | What it establishes |
|---|---|
| `ca_cell` | The cell is correct for all 512 possible inputs. |
| `ca_cell_rule` | The configurable cell is correct for 15,360 cases across five rulesets and 24 random rules. |
| `ca_grid` | The grid matches the reference model for four seeds over 15 generations. |
| `ca_grid_rule` | The configurable grid matches the reference model across five rulesets, including a rule change during a run. |
| `uart_tx`, `uart_rx` | Bytes are transmitted and received correctly, and glitches and framing errors are rejected. |
| `seed_loader` | Seeds load in the correct byte order and survive noise, timeouts and back-to-back transfers. |
| `rule_loader` | Rule and seed commands cannot corrupt each other on the shared serial stream. |
| `loopback_cfg`, `loopback_fixed` | The complete chip works through its real pins in both builds. |
| `cellnet_rules` | Rules sent over the wire take effect, change during a run and survive a reseed. |
| `fabric_latency_16`, `fabric_latency_32` | The fabric completes exactly one generation per clock cycle. |
| `link_latency` | Seed and frame timing is correct at the real 115200 baud rate. |
| `postsynth`, `postsynth_rule` | The synthesized gate-level netlist behaves like the RTL, when Yosys is installed. |

## Software: The C++ Engine

```bash
cd software_prototype/cpp && make check
```

- More than 15.2 million checks compare the engine with the reference model, including every 4x4 grid under every way of dividing its rows between threads.
- The same suite runs under ThreadSanitizer with 4.7 million checks and no reported data races.
- A model checker explores every thread interleaving of small instances. The synchronized engine produces the correct result on more than 10^20 schedules, while removing either the barrier or the second buffer makes 12% to 76% of schedules incorrect.
- Deliberately broken variants remove one protection at a time and record both the ThreadSanitizer verdict and the actual result.

The proof and the full evidence are in [Concurrency and correctness](CONCURRENCY.md).

## Continuous Integration

Every push runs the hardware suites, the C++ engine with and without ThreadSanitizer, the schedule exploration, the Python correctness checks, the protocol encoders and a headless check of the console. The serial encoding is verified by three independent implementations: the Verilog testbenches, `hardware/host/protocol.py` and `software_prototype/check_console.js`.
