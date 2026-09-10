# Runtime Rule Configuration

This document describes how the default bitstream stores the automaton's rule in a register so that the rule can be changed over the serial link.

## Overview

In the default build (`RULE_CFG=1`), the rule is held as two 9-bit masks. Bit k of the birth mask decides whether a dead cell with k live neighbors comes alive, and bit k of the survival mask decides whether a live cell with k live neighbors stays alive. Every ruleset offered by the console therefore runs on a single bitstream, with no rebuild between them.

## Supported Rulesets

| Rule | Notation | Serial packet |
|---|---|---|
| Conway | B3/S23 | `33 08 0C 00` |
| HighLife | B36/S23 | `33 48 0C 00` |
| Day & Night | B3678/S34678 | `33 C8 D8 03` |
| Seeds | B2/S | `33 04 00 00` |
| Maze | B3/S12345 | `33 08 3E 00` |

A rule can be sent from the host with:

```bash
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --rule highlife --pattern glider
```

The console's Live tab sends the same packets and shows the exact bytes before they are transmitted.

## Design Properties

- The masks reach every cell as broadcast signals, in the same way as the clock and the load line. They carry no information between cells, so each cell still depends only on its own state and its eight neighbors.
- The chip starts with Conway's rule after reset, so a board that never receives a rule behaves exactly like the fixed-rule build.
- A new rule takes effect on the next generation and leaves the current grid in place. Seeds and rules are held independently, so each survives a change to the other.
- The fixed-rule build (`RULE_CFG=0`) remains available as the smaller option, and the same loopback testbench runs against both builds.

## Related Documents

- The byte format of the rule command: [Serial protocol](PROTOCOL.md)
- The implementation and its tests: [Hardware design](../hardware/README.md)
