# Flashing CELL-NET onto the Tang Primer 20K

Open toolchain throughout. Gowin EDA also works: load `rtl/*.v`,
`synth/cellnet_primer20k.cst`, `synth/cellnet_primer20k.sdc`, top module
`cellnet_top`.

## 0. Requirements

- Tang Primer 20K on its dock, USB-C to the PC.
- `openFPGALoader` (in the oss-cad-suite bundle, or any package manager).
- A bitstream:

```bash
# prebuilt
gunzip -k hardware/bitstreams/cellnet_16x16_tangprimer20k.fs.gz

# or rebuild from RTL (yosys + nextpnr-himbaechel + apicula, one
# oss-cad-suite download; fails if 27 MHz timing is missed)
cd hardware
./synth/build_bitstream.sh
```

Prebuilt 16x16: routed Fmax 240 MHz against the 27 MHz requirement.

## 1. Load

```bash
# SRAM: instant, volatile. For iterating.
openFPGALoader -b tangprimer20k cellnet_16x16.fs

# flash: persists across power cycles.
openFPGALoader -b tangprimer20k -f cellnet_16x16.fs
```

Board undetected: check the cable, then `openFPGALoader --detect`, then udev
permissions (one run with sudo isolates it).

## 2. Expected state after configuration

- Both status LEDs off. Wiring assumes active-low, the usual Sipeed dock
  convention. Both LEDs lit means the polarity assumption in `cellnet_top.v`
  is wrong for your dock revision; flip the two `assign led[...]` lines.
- Serial stream already running at 115200: one `0xAA` sync byte plus 32
  payload bytes per frame, ~10 frames/s, all-zero payloads. Correct pre-seed
  behavior per the loopback test.
- The dock's BL616 exposes two serial ports over one cable. Empty port: try
  the other.

## 3. Seed

```bash
pip install pyserial
python3 hardware/host/send_seed.py --port /dev/ttyUSB1 --pattern glider --rows 16 --cols 16
```

- First status LED latches on after the first accepted seed.
- Frame stream switches to the glider at 10 gen/s.

Browser route: `software_prototype/cellnet_console.html` in Chrome or Edge,
served over `http://localhost`, Live tab, Connect at 115200 with rows/cols
16/16, Send Seed.

## 4. Triage

- Garbage bytes, no `0xAA`: baud mismatch or wrong serial port.
- Sync fine, pattern static: no seed arrived. Confirm the write port matches
  the read port.
- Torn-looking frames: dropped bytes on the reader side; resync on the next
  `0xAA`. The streamer latches snapshots atomically (race found and fixed by
  the Phase 4 testbench).

## 5. Other sizes

```bash
./synth/build_bitstream.sh 24 24
./synth/build_bitstream.sh 32 32    # routed at 72% LUT4, Fmax 176 MHz
```

A prebuilt 32x32 is in `bitstreams/`. Pass matching `--rows/--cols` to
`send_seed.py` and the console; payload length is fixed by the bitstream.
