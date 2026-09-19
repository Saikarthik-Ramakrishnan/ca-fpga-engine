#!/usr/bin/env bash
# run_link_speed.sh
#
# Answers one question: how fast can the serial link run, and which rate
# should be deployed?
#
# The latency measurement found that the fabric computes a generation in
# 37 ns while the UART needs 2.86 ms to report one, so the link sets the
# end-to-end timing and the divider is the only lever. Two sweeps are
# needed, because either one alone gives the wrong answer:
#
#   test_link_speed.py      seeds the whole chip at a divider and checks
#                           the pattern comes back bit for bit. Every
#                           rate passes, because the testbench generates
#                           bits at exactly the rate the receiver wants.
#   test_baud_tolerance.py  drives the receiver at a rate it was not
#                           built for, and finds how far off the sender
#                           can be. This is what the first sweep cannot
#                           see, and it is what rules the fast rates out.
#
# A rate is deployable when its frames decode and it still has margin
# against the error a real USB-serial bridge brings.
#
#   ./run_link_speed.sh                 # the default candidate set
#   ./run_link_speed.sh 234 27 18       # specific dividers

set -uo pipefail
cd "$(dirname "$0")"

F_CLK=27000000
DEPLOYED=234

DIVIDERS=("$@")
if [ ${#DIVIDERS[@]} -eq 0 ]; then
    DIVIDERS=(234 117 59 29 27 18 12 10 9 6 4 3)
fi

mkdir -p results
rm -f results/link_speed_sweep.json

echo "16x16 chip, 27 MHz clock. Round trip through the real pins, then"
echo "the receiver's tolerance to a sender that is off rate."
echo

failed=()
for cpb in "${DIVIDERS[@]}"; do
    printf 'CLKS_PER_BIT %-4s ' "$cpb"

    if make -f Makefile.link_speed CPB="$cpb" > "results/link_speed_cpb${cpb}.log" 2>&1 \
       && grep -q 'TESTS=1 PASS=1 FAIL=0' "results/link_speed_cpb${cpb}.log"; then
        printf 'round trip ok, '
    else
        echo "ROUND TRIP FAILED (results/link_speed_cpb${cpb}.log)"
        failed+=("$cpb")
        rm -f "results/link_speed_cpb${cpb}.json"
        continue
    fi

    # sweep the sender 30% either side, which is wide enough to close
    # the window at every divider that has one
    span=$(python3 -c "print(max(3, int($cpb * 0.30) + 1))")
    if make -f Makefile.baud_tolerance DUT_CPB="$cpb" SPAN="$span" \
            > "results/baud_tolerance_cpb${cpb}.log" 2>&1 \
       && grep -q 'TESTS=1 PASS=1 FAIL=0' "results/baud_tolerance_cpb${cpb}.log"; then
        echo "tolerance measured"
    else
        echo "TOLERANCE FAILED (results/baud_tolerance_cpb${cpb}.log)"
        failed+=("$cpb")
        rm -f "results/baud_tolerance_cpb${cpb}.json"
    fi
done

echo
python3 - "$F_CLK" "${DIVIDERS[@]}" <<'PY'
import json, os, sys

f_clk = int(sys.argv[1])
dividers = [int(x) for x in sys.argv[2:]]


def load(path):
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return None


rows = []
for cpb in dividers:
    speed = load(f"results/link_speed_cpb{cpb}.json")
    tol = load(f"results/baud_tolerance_cpb{cpb}.json")
    rows.append({"clks_per_bit": cpb, "baud": f_clk / cpb,
                 "speed": speed, "tolerance": tol})

hdr = (f"{'clks/bit':>9} {'baud':>11} {'frame period':>13} {'frames/s':>9} "
       f"{'vs 115200':>10} {'sender margin':>16}")
print(hdr)
print("-" * len(hdr))

base = next((r["speed"]["frame_period_clocks"] for r in rows
             if r["clks_per_bit"] == 234 and r["speed"]), None)

for r in rows:
    s, t = r["speed"], r["tolerance"]
    if not s:
        print(f"{r['clks_per_bit']:>9} {r['baud']:>11,.0f} "
              f"{'frames did not decode':>50}")
        continue
    p = s["frame_period_clocks"]
    speedup = f"{base / p:.2f}x" if base else "-"
    if not t:
        margin = "not measured"
    else:
        res = t["resolution_pct"]
        fast = (f"<{res:.1f}" if t["fast_bounded_only"]
                else f"{t['tolerance_pct_sender_fast']:.1f}")
        slow = (f"<{res:.1f}" if t["slow_bounded_only"]
                else f"{abs(t['tolerance_pct_sender_slow']):.1f}")
        margin = f"{fast}% / {slow}%"
    print(f"{r['clks_per_bit']:>9} {r['baud']:>11,.0f} "
          f"{1e3 * p / f_clk:>10.3f} ms {s['frames_per_second']:>9.1f} "
          f"{speedup:>10} {margin:>16}")

print()
print("sender margin is how far off rate the other end of the wire may be")
print("and still decode, fast / slow. A value written with < is an upper")
print("bound: the sweep steps by whole clocks per bit, and at that divider")
print("one clock is already too big a step to measure inside. A real")
print("USB-serial bridge is inside half a percent, so a few percent is")
print("comfortable and an unmeasurably small window is not.")

with open("results/link_speed_sweep.json", "w") as fh:
    json.dump({"f_clk_hz": f_clk, "rows": rows}, fh, indent=2)
print("\nwrote results/link_speed_sweep.json")
PY

if printf '%s\n' ${failed[@]+"${failed[@]}"} | grep -qx "$DEPLOYED"; then
    echo "the deployed divider ($DEPLOYED) failed, which is a regression" >&2
    exit 1
fi
exit 0
