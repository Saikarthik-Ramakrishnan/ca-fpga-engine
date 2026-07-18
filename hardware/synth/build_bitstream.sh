#!/usr/bin/env bash
# build_bitstream.sh
#
# RTL to flashable bitstream for the Tang Primer 20K, entirely with the
# open toolchain (Yosys + nextpnr-himbaechel + Apicula's gowin_pack).
# No Gowin EDA needed. All three tools ship in one bundle:
#   https://github.com/YosysHQ/oss-cad-suite-build/releases
# Extract it and put its bin/ on PATH before running this.
#
# Usage, from hardware/:
#   ./synth/build_bitstream.sh            # default 16x16
#   ./synth/build_bitstream.sh 24 24      # any ROWSxCOLS
#
# Output: synth/build/cellnet_<R>x<C>.fs plus the nextpnr timing report
# on stdout. The build fails loudly if 27 MHz timing is not met.
#
# Two flags that are not optional:
#   -nowidelut   the Phase 4 lesson; without it per-cell cost is ~5x
#   --freq 27    the dock oscillator; nextpnr verifies timing against it

set -euo pipefail
cd "$(dirname "$0")/.."   # hardware/

ROWS="${1:-16}"
COLS="${2:-16}"
DEVICE="GW2A-LV18PG256C8/I7"
FAMILY="GW2A-18"
CST="synth/cellnet_primer20k.cst"
OUT="synth/build/cellnet_${ROWS}x${COLS}"

mkdir -p synth/build

echo "== synthesis (${ROWS}x${COLS}) =="
yosys -q -p "
read_verilog rtl/ca_cell.v rtl/ca_grid.v rtl/uart_tx.v rtl/uart_rx.v \
             rtl/seed_loader.v rtl/grid_streamer.v rtl/cellnet_top.v
chparam -set ROWS ${ROWS} -set COLS ${COLS} cellnet_top
hierarchy -top cellnet_top
synth_gowin -nowidelut -json ${OUT}.json
"

echo "== place and route =="
nextpnr-himbaechel \
    --device "${DEVICE}" \
    --vopt family="${FAMILY}" \
    --vopt cst="${CST}" \
    --json "${OUT}.json" \
    --write "${OUT}_pnr.json" \
    --freq 27

echo "== bitstream =="
gowin_pack -d "${FAMILY}" -o "${OUT}.fs" "${OUT}_pnr.json"

echo
echo "done: ${OUT}.fs"
echo "flash it (SRAM, volatile, instant):"
echo "  openFPGALoader -b tangprimer20k ${OUT}.fs"
echo "or write it to flash (persistent):"
echo "  openFPGALoader -b tangprimer20k -f ${OUT}.fs"
