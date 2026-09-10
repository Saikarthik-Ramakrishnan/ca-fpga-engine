#!/usr/bin/env bash
# tsan_matrix.sh
#
# Runs every negative control in src/races.cpp under ThreadSanitizer, one
# process each, and puts two independent verdicts side by side:
#
#   TSan     did ThreadSanitizer report a data race?
#   answer   was the computed result right? (the program's own check)
#
# The rows where the two disagree are the point, and they go both ways:
#   split_atomic  TSan clean, answer WRONG: no data race, still loses updates
#   in_place_1    TSan clean, answer WRONG: one thread, no concurrency at all
#   barrier_std   TSan RACE, answer correct on macOS: libc++ runs
#                 std::barrier's arrival tree in an uninstrumented dylib, so
#                 TSan cannot see the ordering it provides
# A TSan verdict is evidence about the schedules and the code it could
# see. It is not a proof in either direction; docs/CONCURRENCY.md has one.
#
# Exits non-zero if any TSan verdict differs from the expected one, so CI
# notices if the tool stops catching a race or a correct variant starts
# racing. Answers for racy variants depend on the schedule and are shown,
# not gated; answers for the correct variants and in_place_1 are gated.
#
#   tools/tsan_matrix.sh build/races_tsan

set -uo pipefail
BIN="${1:-build/races_tsan}"

# variant : expected TSan verdict : expected answer ("any" = schedule-dependent)
MATRIX=(
    "plain:RACE:any"
    "split_atomic:clean:any"
    "mutex:clean:correct"
    "fetch_add:clean:correct"
    "reduction:clean:correct"
    "no_barrier:RACE:any"
    "in_place_1:clean:WRONG"
    "in_place:RACE:any"
    "barrier:clean:correct"
    "barrier_std:any:correct"
)

printf '%-13s %-6s %-8s  %s\n' variant TSan answer detail
status=0
for row in "${MATRIX[@]}"; do
    IFS=':' read -r v want_tsan want_answer <<< "$row"
    # abort_on_error=0: macOS sanitizers otherwise abort() after reporting
    out=$(TSAN_OPTIONS="halt_on_error=0 abort_on_error=0 exitcode=66" "$BIN" --variant "$v" 2>&1)
    if grep -q "WARNING: ThreadSanitizer: data race" <<< "$out"; then tsan="RACE"; else tsan="clean"; fi
    answer=$(grep -oE 'ANSWER=(correct|WRONG)' <<< "$out" | tail -1 | cut -d= -f2)
    detail=$(grep -E "^$v: " <<< "$out" | head -1 | sed "s/^$v: //")
    flag=""
    if [ "$want_tsan" != "any" ] && [ "$tsan" != "$want_tsan" ]; then flag=" <- expected TSan $want_tsan"; status=1; fi
    if [ "$v" = "barrier_std" ] && [ "$tsan" = "RACE" ]; then std_fp=1; fi
    if [ "$want_answer" != "any" ] && [ "$answer" != "$want_answer" ]; then
        flag="$flag <- expected answer $want_answer"; status=1
    fi
    printf '%-13s %-6s %-8s  %s%s\n' "$v" "$tsan" "${answer:-?}" "$detail" "$flag"
done

echo
if [ "${std_fp:-0}" = "1" ]; then
    echo "barrier_std: TSan reported a race on a correct engine. The standard orders every"
    echo "arrive before the completion step, but this libc++ performs that ordering inside"
    echo "libc++.dylib, which TSan does not instrument. Minimal reproduction: make tsan-probe."
    echo
fi
if [ "$status" -ne 0 ]; then
    echo "RESULT: a verdict changed; see the flagged rows"
else
    echo "RESULT: every TSan verdict as expected"
fi
exit "$status"
