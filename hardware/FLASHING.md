# Flashing CELL-NET onto the Tang Primer 20K

Everything below uses the open toolchain. Gowin EDA works too (load the
RTL, `synth/cellnet_primer20k.cst`, and `synth/cellnet_primer20k.sdc`,
top module `cellnet_top`), but nothing here requires it.

## 0. What you need

- Tang Primer 20K module seated on its dock, USB-C cable to the PC.
- `openFPGALoader` (ships in the oss-cad-suite bundle, or via most
  package managers).
- A bitstream. Either use the prebuilt one in this repo:

```bash
gunzip -k hardware/bitstreams/cellnet_16x16_tangprimer20k.fs.gz
```

  or rebuild it yourself from RTL (needs yosys + nextpnr-himbaechel +
  apicula, all in one oss-cad-suite download; the script checks timing
  against the 27 MHz dock clock and fails loudly if it is not met):

```bash
cd hardware
./synth/build_bitstream.sh          # 16x16, the default build
```

The prebuilt 16x16 was placed and routed at a reported Fmax of
240 MHz against the 27 MHz requirement, so timing is not a concern at
this size.

## 1. Load it

```bash
# into SRAM: instant, gone at power-off. Use this while iterating.
openFPGALoader -b tangprimer20k cellnet_16x16.fs

# into flash: persists across power cycles. Use this when happy.
openFPGALoader -b tangprimer20k -f cellnet_16x16.fs
```

If the board is not detected, it is almost always a cable or udev
permissions issue; `openFPGALoader --detect` and running once with sudo
narrows it down fast.

## 2. What you should see

Immediately after configuration:

- Both status LEDs off (they are wired assuming active-low, the usual
  Sipeed dock convention; if both are LIT instead, the polarity guess in
  `cellnet_top.v` is wrong for your dock revision, and the fix is
  flipping the two `assign led[...]` lines. Cosmetic only).
- The chip is already streaming: all-zero frames at 115200 baud on the
  USB-serial bridge, one `0xAA` sync byte then 32 payload bytes per
  frame, about 10 frames per second. The grid is empty and held; that is
  correct pre-seed behavior, proven by the loopback test.

The dock's BL616 exposes two serial ports over the one USB cable. If a
port shows nothing, try the other one.

## 3. Seed it

From the PC:

```bash
pip install pyserial
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --pattern glider --rows 16 --cols 16
```

- The first status LED latches on: the chip has accepted its first seed.
- The frame stream switches from zeros to a glider walking the torus at
  10 generations per second.

Or do the whole thing in the browser: open
`software_prototype/cellnet_console.html` in Chrome or Edge (served over
`http://localhost`, not `file://`), Live tab, Connect at 115200 with
rows/cols 16/16, then Send Seed. The board on screen from then on is the
FPGA's actual state, not a simulation.

## 4. If frames look wrong

- Garbage bytes, no 0xAA sync: baud mismatch, or the other serial port.
- Sync fine but the pattern never changes: the grid is held; a seed
  never arrived. Check you are writing to the same port you read from.
- Pattern changes but looks torn between frames: it is not torn; the
  streamer latches atomically (that race was found and fixed by the
  Phase 4 testbench). What tearing-like artifacts actually mean is the
  reader dropped bytes and lost frame alignment; resync on the next 0xAA.

## 5. Rebuilding at other sizes

```bash
./synth/build_bitstream.sh 24 24    # comfortable middle size
./synth/build_bitstream.sh 32 32    # the ceiling; routed at 72% LUT4, Fmax 176 MHz
```

A prebuilt 32x32 also ships in `bitstreams/`, same protocol, just pass
`--rows 32 --cols 32` everywhere.

Remember to pass matching `--rows/--cols` to `send_seed.py` and the
console; the seed payload length is baked into the bitstream.
