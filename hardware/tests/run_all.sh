#!/usr/bin/env bash
# run_all.sh
#
# Every cocotb suite in one command, with a pass/fail summary at the end
# and a non-zero exit if anything failed. This is what CI runs and what to
# run before pushing RTL.
#
#   ./run_all.sh          # all simulation suites
#   ./run_all.sh --clean  # wipe sim_build_* first (see the note below)
#
# The gate-level suite (Makefile.postsynth) needs yosys and a generated
# netlist. It is skipped, loudly, when either is missing, so the absence of
# a synthesis toolchain never looks like a pass.
#
# Note on build directories: every suite has its own SIM_BUILD. cocotb
# rebuilds when SOURCES change but not when Makefile parameters change, so
# two suites sharing a build directory silently run each other's stale
# binary. That cost two debugging cycles in Phase 4.5. --clean is the
# escape hatch when a suite's parameters change and results look wrong.

set -uo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--clean" ]; then
    echo "removing sim_build_* ..."
    rm -rf sim_build_*
fi

# suite name -> makefile
SUITES=(
    "ca_cell:Makefile"
    "ca_cell_rule:Makefile.cellrule"
    "ca_grid:Makefile.grid"
    "ca_grid_rule:Makefile.gridrule"
    "uart_tx:Makefile.uart"
    "uart_rx:Makefile.rx"
    "seed_loader:Makefile.loader"
    "rule_loader:Makefile.ruleloader"
    "loopback_cfg:Makefile.loopback"
    "loopback_fixed:Makefile.loopback_fixed"
    "cellnet_rules:Makefile.rules"
    "fabric_latency_16:Makefile.fabric_latency ROWS=16 COLS=16"
    "fabric_latency_32:Makefile.fabric_latency ROWS=32 COLS=32"
    "link_latency:Makefile.link_latency"
)

LOGDIR="$(mktemp -d)"
declare -a RESULTS=()
FAILED=0
TOTAL_TESTS=0
TOTAL_PASS=0

for entry in "${SUITES[@]}"; do
    name="${entry%%:*}"
    mk="${entry##*:}"
    printf '%-16s ' "$name"
    log="$LOGDIR/$name.log"

    # shellcheck disable=SC2086  # $mk may carry overrides like ROWS=32
    if make -f $mk > "$log" 2>&1; then
        line=$(grep -oE 'TESTS=[0-9]+ PASS=[0-9]+ FAIL=[0-9]+ SKIP=[0-9]+' "$log" | tail -1)
        if [ -z "$line" ]; then
            echo "NO RESULT LINE  (see $log)"
            RESULTS+=("$name: no result line")
            FAILED=1
            continue
        fi
        t=$(echo "$line" | sed -E 's/.*TESTS=([0-9]+).*/\1/')
        p=$(echo "$line" | sed -E 's/.*PASS=([0-9]+).*/\1/')
        f=$(echo "$line" | sed -E 's/.*FAIL=([0-9]+).*/\1/')
        TOTAL_TESTS=$((TOTAL_TESTS + t))
        TOTAL_PASS=$((TOTAL_PASS + p))
        if [ "$f" != "0" ]; then
            echo "FAIL   $line"
            RESULTS+=("$name: $line")
            FAILED=1
        else
            echo "ok     $line"
            RESULTS+=("$name: $line")
        fi
    else
        echo "ERROR  (build or run failed, see $log)"
        tail -20 "$log" | sed 's/^/    | /'
        RESULTS+=("$name: build/run error")
        FAILED=1
    fi
done

# ---- gate-level suites, only if the toolchain is actually present ----
# Skipped loudly rather than silently: a missing synthesis toolchain must
# never read as a pass.
for gate in "postsynth:Makefile.postsynth:../synth/build/ca_grid_netlist.v:python3 emit_netlist.py" \
            "postsynth_rule:Makefile.postsynth_rule:../synth/build/ca_grid_rule_netlist.v:RULE=1 python3 emit_netlist.py"; do
    IFS=':' read -r gname gmk gnetlist ghint <<< "$gate"
    printf '%-16s ' "$gname"
    if ! command -v yosys > /dev/null 2>&1; then
        echo "SKIPPED (yosys not on PATH)"
    elif [ ! -f "$gnetlist" ]; then
        echo "SKIPPED (run: cd ../synth && $ghint)"
    else
        log="$LOGDIR/$gname.log"
        if make -f "$gmk" > "$log" 2>&1; then
            line=$(grep -oE 'TESTS=[0-9]+ PASS=[0-9]+ FAIL=[0-9]+ SKIP=[0-9]+' "$log" | tail -1)
            echo "ok     $line"
        else
            echo "ERROR  (see $log)"
            FAILED=1
        fi
    fi
done

echo
echo "-------------------------------------------------------------"
printf 'simulation suites: %d\n' "${#SUITES[@]}"
printf 'cocotb tests:      %d passed / %d run\n' "$TOTAL_PASS" "$TOTAL_TESTS"
if [ "$FAILED" -ne 0 ]; then
    echo "RESULT: FAILED"
    echo "logs kept in $LOGDIR"
    exit 1
fi
echo "RESULT: all green"
rm -rf "$LOGDIR"
