# Serial Protocol Specification

Everything the PC and the chip say to each other, over one 115200 8N1
serial link on the Tang Primer 20K dock's BL616 bridge.

Three magic bytes. None is a rotation of another, and the two commands are
bit-inverses of the sync byte's neighbourhood, so a receiver that starts
listening mid-stream cannot mistake one for another.

| byte | name | direction | meaning |
|---|---|---|---|
| `0x55` | SEED | PC to chip | command, followed by one full grid snapshot |
| `0x33` | RULE | PC to chip | command, followed by 3 rule bytes |
| `0xAA` | SYNC | chip to PC | frame header, followed by one full grid snapshot |

## Byte order, one convention both directions

- Cell `(r, c)` is bit `r*COLS + c` of the grid value.
- Payload byte 0 carries grid bits `[7:0]`, byte 1 carries `[15:8]`, and so on.
- A grid of `ROWS*COLS` cells is `ROWS*COLS/8` payload bytes. `ROWS*COLS`
  must be a multiple of 8.
- `seed_loader.v`, `grid_streamer.v`, `hardware/host/protocol.py` and the
  console's Live tab all use this ordering. Changing it means changing all
  four.

## SEED, PC to chip

```
0x55  P0  P1  ...  P(N-1)          N = ROWS*COLS/8
```

- `seed_loader.v` ignores every byte until `0x55` arrives, so line noise
  and a port opened mid-thought cannot start a bogus transfer.
- When byte `P(N-1)` lands, `load` pulses for one clock and the whole grid
  takes the snapshot on that edge.
- A transfer that stalls mid-payload for longer than `TIMEOUT_CLKS`
  (~100 ms at 27 MHz) is abandoned. Nothing is loaded, and the next `0x55`
  is treated as a fresh command and is never swallowed as payload.
- A payload byte equal to `0x33` or `0xAA` is data. Only the loader's state
  decides what a byte means, never the byte's value alone.

## RULE, PC to chip

```
0x33  B  S  X
```

| byte | contents |
|---|---|
| `B` | `birth[7:0]` |
| `S` | `survive[7:0]` |
| `X` | `{6'b0, survive[8], birth[8]}`, so bit 0 is `birth[8]` and bit 1 is `survive[8]` |

- `birth` and `survive` are 9-bit masks over the live-neighbor count. Bit
  `k` set means "k live neighbors fires this transition".
- Conway B3/S23 is `birth = 0b000001000`, `survive = 0b000001100`, which on
  the wire is `33 08 0C 00`.
- Day & Night B3678/S34678 exercises both of byte `X`'s flags: `33 C8 D8 03`.

Rulesets shipped in the console, `golden_rule.py` and the testbenches:

| rule | notation | birth mask | survive mask | packet |
|---|---|---|---|---|
| Conway | B3/S23 | `0b000001000` | `0b000001100` | `33 08 0C 00` |
| HighLife | B36/S23 | `0b001001000` | `0b000001100` | `33 48 0C 00` |
| Day & Night | B3678/S34678 | `0b111001000` | `0b111011000` | `33 C8 D8 03` |
| Seeds | B2/S | `0b000000100` | `0b000000000` | `33 04 00 00` |
| Maze | B3/S12345 | `0b000001000` | `0b000111110` | `33 08 3E 00` |

Behaviour:

- The rule register resets to Conway, so a board nobody sends a rule to
  behaves exactly like a `RULE_CFG=0` build.
- `birth` and `survive` only move on the clock the third payload byte
  lands. The fabric is never driven by a half-received mask.
- A rule change does not touch the grid. The next generation continues from
  the live state under the new rule.
- A rule survives a reseed, and a seed survives a rule change. The two are
  independent registers.
- A stalled transfer times out exactly like SEED, and leaves the previous
  rule in force.
- A bitstream built with `RULE_CFG=0` has Conway welded into the gates and
  ignores `0x33` silently. There is no error byte; the rule simply does not
  change.

## Sharing one byte stream between two loaders

`seed_loader.v` and `rule_loader.v` both watch the same `rx_dv`/`rx_byte`
pair. Two symmetric guards keep each out of the other's payload:

1. `rule_loader` recognises `0x33` as a command only while `seed_loader`
   reports it is not mid-transfer. A `0x33` inside a grid seed is data.
2. While `rule_loader` is consuming its three payload bytes it raises
   `consuming`, and `cellnet_top` gates `rx_dv` away from `seed_loader`.
   A `0x55` inside a rule payload never reaches the seed loader.

Both guards are checked directly by
`hardware/tests/test_rule_loader.py`, against the real `seed_loader`
instance itself, and end to end through the chip's real
pins by `hardware/tests/test_cellnet_rules.py`.

## Frames, chip to PC

```
0xAA  P0  P1  ...  P(N-1)          repeating, forever
```

- `grid_streamer.v` latches a grid snapshot, sends the sync byte and the
  payload, then latches again immediately. The link is never idle.
- Frames report the current state. Generations that pass while a frame is
  being sent are skipped, the way a camera does not capture every instant
  of real motion. This behavior is intentional.
- Frames are therefore **not** consecutive generations. Any test that
  asserts frame N equals generation N is wrong. The correct assertion, and
  the one the testbenches make, is that some consistent non-decreasing
  assignment of generations to frames exists.
- Choosing the generation period as an exact divisor of the frame period
  makes every frame latch the same phase, and a period-2 blinker then looks
  frozen. That alias is real and was caught by the loopback testbench.
  Keep `GEN_DIV` and the frame time non-commensurate.

## Timing

- 115200 baud, 8N1: 10 bit times per byte.
- `CLKS_PER_BIT` = 27 MHz / 115200 = 234. Both ends must agree; a mismatch
  produces garbage with no sync, and is the first thing to check when
  frames look wrong.
- A 16x16 frame is 33 bytes, about 2.9 ms on the wire, so roughly 350
  frames per second is the link ceiling at this baud.
- Default `GEN_DIV` is 2,700,000, i.e. 10 generations per second at 27 MHz.
  The fabric itself can do one generation per clock; the pacer exists only
  so a human and a UART can follow along.

## Implementations of this document

| where | file |
|---|---|
| chip, receive | `hardware/rtl/seed_loader.v`, `hardware/rtl/rule_loader.v` |
| chip, transmit | `hardware/rtl/grid_streamer.v` |
| host | `hardware/host/protocol.py` (`python3 protocol.py` self-tests it) |
| browser | `software_prototype/cellnet_console.html`, Live tab |
| tests | `hardware/tests/test_seed_loader.py`, `test_rule_loader.py`, `test_cellnet_loopback.py`, `test_cellnet_rules.py` |

The same packet vectors are asserted in the cocotb tests, in
`protocol.py`'s self-test and in `software_prototype/check_console.js`, so
the Verilog, the host tools and the browser are pinned to one encoding by
three independent checks.
