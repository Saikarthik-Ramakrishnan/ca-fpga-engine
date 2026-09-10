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
#   ./synth/build_bitstream.sh                 # default 16x16, selectable rule
#   ./synth/build_bitstream.sh 24 24           # any ROWSxCOLS
#   RULE_CFG=0 ./synth/build_bitstream.sh 32 32   # fixed-Conway fabric
#
# RULE_CFG picks which fabric gets built:
#   1 (default)  ca_grid_rule + rule_loader. The rule is 18 bits in a
#                register, settable over UART with the 0x33 command, Conway
#                out of reset. All five console rulesets on one bitstream.
#   0            ca_grid, Conway welded into the gates. Smaller. Reach for
#                this if a large grid stops fitting.
# Both are covered by the same loopback testbench (Makefile.loopback and
# Makefile.loopback_fixed).
#
# Output: synth/build/cellnet_<R>x<C>[_fixed].fs plus the nextpnr timing
# report on stdout. The build fails loudly if 27 MHz timing is not met.
#
# Two flags that are not optional:
#   -nowidelut   the Phase 4 lesson; without it per-cell cost is ~5x
#   --freq 27    the dock oscillator; nextpnr verifies timing against it

set -euo pipefail
cd "$(dirname "$0")/.."   # hardware/

ROWS="${1:-16}"
COLS="${2:-16}"
RULE_CFG="${RULE_CFG:-1}"
DEVICE="GW2A-LV18PG256C8/I7"
FAMILY="GW2A-18"
CST="synth/cellnet_primer20k.cst"

if [ "${RULE_CFG}" = "1" ]; then
    SUFFIX=""
    RULE_LABEL="selectable rule (0x33 command, Conway on reset)"
else
    SUFFIX="_fixed"
    RULE_LABEL="fixed Conway B3/S23"
fi
OUT="synth/build/cellnet_${ROWS}x${COLS}${SUFFIX}"

mkdir -p synth/build

echo "== synthesis (${ROWS}x${COLS}, ${RULE_LABEL}) =="
# Every RTL file is read regardless of RULE_CFG. The generate-if inside
# cellnet_top elaborates away the branch that is not selected, so the
# unused fabric costs nothing in the bitstream; reading both keeps this
# script from having to know which modules belong to which build.
yosys -q -p "
read_verilog rtl/ca_cell.v rtl/ca_grid.v \
             rtl/ca_cell_rule.v rtl/ca_grid_rule.v \
             rtl/uart_tx.v rtl/uart_rx.v \
             rtl/seed_loader.v rtl/rule_loader.v \
             rtl/grid_streamer.v rtl/cellnet_top.v
chparam -set ROWS ${ROWS} -set COLS ${COLS} -set RULE_CFG ${RULE_CFG} cellnet_top
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
echo "done: ${OUT}.fs   (${ROWS}x${COLS}, ${RULE_LABEL})"
echo "flash it (SRAM, volatile, instant):"
echo "  openFPGALoader -b tangprimer20k ${OUT}.fs"
echo "or write it to flash (persistent):"
echo "  openFPGALoader -b tangprimer20k -f ${OUT}.fs"
if [ "${RULE_CFG}" = "1" ]; then
    echo
    echo "then set a rule over the wire, no rebuild:"
    echo "  python3 host/send_seed.py --port /dev/ttyUSB1 --rule highlife --pattern glider --rows ${ROWS} --cols ${COLS}"
fi
