# Concurrency and Correctness

This document lists the variables that the parallel C++ engine shares between threads, explains how each one is protected, proves that every schedule produces the reference result, and presents the evidence for each step of the proof.

## Background

- Two threads access the same variable, at least one of them writes, and nothing orders the two accesses: that is a data race. The result depends on the schedule, and C++ defines it as undefined behavior.
- Every shared variable therefore needs protection. A mutex is one kind. Atomics with acquire/release ordering, barriers, and data ownership are others, and they cost very different amounts.
- A synchronous cellular automaton admits the cheapest one: arrange the data so that, within a generation, nothing is both shared and written. The only point where threads must synchronize is the boundary between generations.
- Everything below is checked against `golden_rule.py`, the project's single reference.

## Algorithm

`BarrierEngine` in [`software_prototype/cpp/include/cellnet/engines.hpp`](../software_prototype/cpp/include/cellnet/engines.hpp):

```text
input    grid G0, rule (birth, survive), T threads, N generations
state    buf[0] = G0, buf[1] = zeros, cur = 0
         rows split into T contiguous blocks; thread t owns block P(t)

thread t:
    wait at barrier                                     start line
    repeat N times:
        c = cur                                         fixed for the whole phase
        partial[t] = step(buf[c] -> buf[c^1], rows P(t))
        wait at barrier                                 every row is written

completion step, run once per phase by one thread while every other waits:
    population = partial[0] + ... + partial[T-1]
    cur = cur ^ 1                                       next becomes current
```

- `step` reads any cell of its input and writes only rows `P(t)` of its output ([`kernels.hpp`](../software_prototype/cpp/include/cellnet/kernels.hpp)). The proof rests on that contract.
- The barrier comes in two builds of the same engine: C++20 `std::barrier` (engine `barrier`) and `AtomicBarrier` (engine `atomic`), two atomics written out in the header.
- `MutexEngine` implements the same algorithm with every shared variable behind one `std::mutex` and a condition-variable barrier, for comparison.

## Shared State Inventory

| variable | read by | written by | written when | protection |
|---|---|---|---|---|
| `buf[c]`, current generation | every thread | nobody | never during a phase | read-only for the whole phase |
| `buf[c^1]`, next generation | nobody during the phase | thread t, rows `P(t)` only | during the phase | disjoint ownership |
| `cur`, generation count, trace | every thread | the completion step | between phases | the barrier's ordering |
| `partial[t]`, population shares | the completion step | thread t only | during the phase | one padded slot per thread |
| the barrier's counter and phase | every thread | every thread | on arrival | acquire/release atomics |

- No row of the table needs a mutex, because no variable is both shared and written inside a phase.
- Ownership is by memory location, the C++ unit of conflict. In the bit-sliced kernel a row is whole 64-bit words; two threads writing different bits of one word would race (the `std::vector<bool>` trap). Owning whole rows rules that out.
- `partial[t]` slots are 128-byte aligned (the M2 cache line) so neighbors' writes do not invalidate each other's lines. That is a speed measure; correctness never depended on it.

## Case Study: A Shared Counter

[`src/races.cpp`](../software_prototype/cpp/src/races.cpp): 8 threads count the live cells of a 512x512 soup, 20 passes, into one total. The right answer is 1,837,520.

| protection | TSan | increments lost | ns per increment |
|---|---|---|---|
| none: `total = total + 1` | race | 1,253,159 | 3.7 |
| atomic load, then a separate atomic store | clean | 1,155,497 | 12.5 |
| `std::mutex` around each increment | clean | 0 | 41.7 |
| atomic `fetch_add` | clean | 0 | 36.3 |
| private sum per thread, combined once | clean | 0 | 0.1 |

- The unprotected counter loses 68% of its increments.
- The mutex fixes it at 417x the cost of the private sums.
- The second row passes ThreadSanitizer and is still wrong: each access is atomic, the read-modify-write as a whole is not. Two threads load the same value and both store value + 1.
- The engine uses the last row's pattern: `partial[t]`, summed once per generation in the completion step.

## Generation Barrier

`AtomicBarrier`, from `engines.hpp`:

```cpp
void arrive_and_wait() noexcept {
    const uint32_t my_phase = phase_.load(std::memory_order_relaxed);
    if (left_.fetch_sub(1, std::memory_order_acq_rel) == 1) {   // last to arrive
        completion_();
        left_.store(count_, std::memory_order_relaxed);
        phase_.store(my_phase + 1, std::memory_order_release);
        phase_.notify_all();
        return;
    }
    for (int i = 0; i < 4096; ++i)                                 // brief spin
        if (phase_.load(std::memory_order_acquire) != my_phase) return;
    while (phase_.load(std::memory_order_acquire) == my_phase)
        phase_.wait(my_phase, std::memory_order_acquire);
}
```

Why it provides the two orderings the proof needs:

- Arrivals before completion. Every arrival is a `fetch_sub` with `acq_rel` on `left_`. Those read-modify-writes form one release sequence, so each earlier arrival's release synchronizes-with the last arrival's acquire. Every write a thread made before arriving happens-before the completion step.
- Completion before release. The last arriver runs the completion step, resets `left_`, then stores the new phase with `release`. A waiter leaves only after an `acquire` load sees that phase.
- No double arrival. After arriving, a thread waits for the phase to change, and the phase changes only after the reset.
- The M2 Pro is ARMv8, a weakly ordered machine: acquire and release compile to ARM's load-acquire and store-release instructions, and the hardware relies on them. On this machine, relaxed ordering here would be a real bug.

`std::barrier` provides the same two orderings by specification: C++20 [thread.barrier.class] orders every arrival before the completion step, and the completion step before every return from that phase.

## Theorem

For every thread count T >= 1, every row partition, every grid size, every rule, and every schedule the operating system chooses, the barrier engine ends with the golden generation G(N), and the population it records after generation k is the live-cell count of G(k).

## Proof

Write G(k) for `golden_rule.py`'s generation k. Name the barrier completions C(0) (the start line), C(1), ..., C(N). Phase k is the interval between C(k) and C(k+1); in it the threads compute generation k+1.

Invariant I(k), at the end of C(k):

1. `buf[cur]` holds G(k).
2. C(k) happens-before everything any thread does after leaving barrier k.
3. For k >= 1, the recorded population for generation k is the live-cell count of G(k).

Base case, I(0). The calling thread writes `buf[0] = G(0)` and `cur = 0` before creating the workers. Thread creation and the start-line barrier order those writes before every worker's first read.

Inductive step, I(k) implies I(k+1).

1. Every thread reads `c = cur` after C(k). By I(k).2 each reads the value C(k) left, so all threads agree on `c`.
2. No two conflicting accesses are unordered, so the run has no data race.
   - Across phases: everything a thread did in phase k-1 is sequenced before its arrival, every arrival happens-before C(k), and by I(k).2 C(k) happens-before everything in phase k. A read of a buffer in phase k-1 and a write to it in phase k are therefore ordered.
   - Within phase k: `step` writes only rows `P(t)` of `buf[c^1]`, nothing writes `buf[c]`, no thread reads `buf[c^1]`, and C(k+1) has not begun, since it starts only after every thread arrives. No two accesses in the phase conflict.
   - Every read of `buf[c]` in phase k therefore returns G(k), by I(k).1.
3. By the kernel contract and its verification, thread t writes rows `P(t)` of G(k+1) into `buf[c^1]` and returns their live count in `partial[t]`. The blocks `P(t)` cover every row, so once every thread has arrived, `buf[c^1]` holds G(k+1) and the partials sum to its live count.
4. Each thread's writes are sequenced before its arrival, and every arrival happens-before C(k+1). C(k+1) therefore sees all of `buf[c^1]` and all partials. It sets `cur = c^1` and records the sum: I(k+1).1 and I(k+1).3 hold.
5. C(k+1) happens-before every thread's return from that barrier: I(k+1).2 holds.

After N phases `buf[cur]` holds G(N). The workers are joined, which synchronizes, before `store` copies `buf[cur]` out.

Nothing in the argument depends on T, the block sizes, the grid size, the rule, or the schedule.

## Assumptions and How They Are Checked

| step | assumption | how it is established |
|---|---|---|
| 2, 3 | `step(in, out, r0, r1)` reads only `in` and writes only rows r0 to r1 of `out` | the code, about 30 lines per kernel; ThreadSanitizer on the threaded test runs |
| 3 | `step` produces golden rows for any partition, in any order | layer 2 below: all 65,536 4x4 tori, 5 rules, 8 partitions, 2 orders, both kernels, exhaustive; layer 3: 3,520 golden generations up to 128x128 |
| 3 | the blocks are disjoint and cover every row | `partition()` arithmetic; runs with T from 1 to 24, including more threads than rows |
| 4, 5 | the two barrier orderings | `std::barrier`: the standard. `AtomicBarrier`: the argument above, with every operation visible to TSan |
| 2 | ownership is by whole memory locations | scalar: one byte per cell; bit-sliced: whole 64-bit words per row |

## Hardware Equivalent

| software | `ca_grid.v` |
|---|---|
| `buf[cur]` | each cell's flip-flop output Q, which its neighbors read |
| `buf[cur^1]` | the flip-flop's D input, driven only by that cell's logic |
| disjoint ownership | each cell drives exactly one D |
| the barrier | the clock edge: every flip-flop samples its D at once |
| every write lands before the swap | setup time: every D input has settled before the edge |
| no read sees the next generation early | hold time: every flip-flop captures its D before any neighbor's changing Q can reach it |
| checking both | static timing analysis: 176 to 240 MHz routed (fixed-rule build) against 27 MHz required |

- Synchronous logic is double buffering with a barrier, built into the flip-flop. That is why the RTL has no mutex and needs none, and why `test_fabric_latency.py` measures exactly one clock per generation.

## Evidence

### 1. Comparison With the Reference Model

[`src/test_correctness.cpp`](../software_prototype/cpp/src/test_correctness.cpp), reading vectors `tools/gen_vectors.py` computes with `golden_rule.py`:

| layer | check | passed | against |
|---|---|---|---|
| 1 | `cell_next`, 5 rules x 18 inputs | 90 | golden `update_masked` |
| 1 | bit-sliced adder tree, all 256 neighbor patterns | 256 | popcount, exhaustive |
| 1 | bit-sliced rule lookup, all 2^18 rules x 18 inputs | 4,718,592 | `cell_next`, exhaustive |
| 2 | scalar kernel: every 4x4 torus, 5 rules, 8 partitions, 2 orders | 5,242,880 | golden step, exhaustive |
| 2 | bit-sliced kernel, same space | 5,242,880 | golden step, exhaustive |
| 3 | serial + mutex, barrier, atomic x T in {1,2,3,4,7,8,16}, every trajectory | 5,720 runs | golden, 154,880 generations |
| 4 | randomized size, rule, T (1 to 24), generations | 300 runs | serial/scalar, pinned by layer 3 |
| 5 | rectangular grids, every engine | 1,760 runs | serial/scalar, differential |

- 15,212,478 checks, 0 failures, 6.3 s on the M2 Pro.
- Layer 3 compares the whole grid and the population after every generation, so a divergence is pinned to the generation where it first appears.

### 2. Exhaustive Schedule Exploration

[`tools/prove_schedules.py`](../software_prototype/cpp/tools/prove_schedules.py) enumerates every interleaving of the threads, for every initial grid (or a stated sample), and checks each outcome against `golden_rule.py`. It models the engine's partition, its double buffer and `std::barrier`'s semantics, and first checks its own one-cell update against `golden_rule.py` on every grid it uses.

| torus | T | generations | protocol | initial grids | schedules explored | wrong schedules |
|---|---|---|---|---|---|---|
| 3x3 | 1 | 2 | barrier | all 512 | 2,560 | 0 |
| 3x3 | 1 | 2 | in place | all 512 | 2,560 | 1,092 (42.7%) |
| 3x3 | 2 | 2 | barrier | all 512 | 141,926,400 | 0 |
| 3x3 | 2 | 2 | no barrier | all 512 | 47,523,840 | 5,712,065 (12.0%) |
| 3x3 | 2 | 2 | in place | all 512 | 141,926,400 | 59,714,988 (42.1%) |
| 3x3 | 3 | 2 | barrier | all 512 | 894,136,320,000 | 0 |
| 3x3 | 3 | 2 | no barrier | all 512 | 43,912,028,160 | 9,233,544,102 (21.0%) |
| 3x3 | 3 | 2 | in place | all 512 | 894,136,320,000 | 374,286,460,680 (41.9%) |
| 4x4 | 2 | 2 | barrier | 16 of 65,536 | 100,118,304,000 | 0 |
| 4x4 | 2 | 2 | no barrier | 16 of 65,536 | 48,086,431,200 | 12,555,216,993 (26.1%) |
| 4x4 | 2 | 2 | in place | 16 of 65,536 | 100,118,304,000 | 76,197,228,030 (76.1%) |
| 4x4 | 4 | 2 | barrier | 2 of 65,536 | 1.776 x 10^20 | 0 |

- All five rules on every row. The barrier protocol produced the golden grid on every one of more than 10^20 schedules. Removing the barrier, or the second buffer, makes 12% to 76% of schedules wrong.
- An in-place update is wrong with a single thread (42.7% of 3x3 grids), so the barrier alone does not save it: the algorithm needs both the second buffer and the barrier.
- An extended run adds 4x4 with 4 threads and no barrier: 4.765 x 10^20 of 9.956 x 10^20 schedules wrong (47.9%), 87 s. In-place at that size did not finish in nine minutes and is left out.

Why a model with one atomic step per cell update is enough:

- Barrier protocol: inside a phase no operation conflicts with another thread's (reads hit the read buffer nobody writes; writes hit disjoint cells). Operations that do not conflict commute, so every finer-grained interleaving, single loads and stores included, is equivalent to one enumerated here (Lipton's reduction). Zero wrong schedules here means zero at any granularity.
- The broken protocols: coarse interleavings are a subset of fine ones, so every wrong outcome found here can happen in the real code.
- The script exits non-zero if the barrier protocol has a single wrong schedule, or if the broken protocols produce no counterexample: an explorer that cannot see bugs would make its clean result worthless.

A concrete wrong schedule, the first the explorer found (no barrier, 3x3, T=2, Conway, 2 generations). Thread 0 owns row 0, thread 1 rows 1 and 2.

```text
start      ###        golden gen 1   ###        golden gen 2   ...
           ...                       ###                       ...
           ...                       ###                       ...

steps 1-3    t0 computes generation 1 of row 0, reading buf[0]: row 0 survives
steps 4-6    t0, with nothing to stop it, computes generation 2 of row 0 from
             buf[1], whose rows 1 and 2 thread 1 has not written yet: zeros,
             where golden generation 1 is all alive
steps 7-18   t1 computes both generations of rows 1 and 2, correctly

got        ###        wrong: golden generation 2 is all dead
           ...
           ...
```

- Each cell of row 0 sees two live neighbors instead of eight, so it survives instead of dying.
- With the barrier, step 4 cannot run before step 12: thread 0 waits until thread 1 has written its rows of generation 1.

### 3. ThreadSanitizer

- `make tsan`: the whole suite (layers 1, 3, 4, 5) under TSan, serial, mutex and atomic families, T in {1, 2, 3, 4, 7, 8, 16}, `halt_on_error=1`. 4,724,098 checks, 0 failures, 0 race reports.
- `make tsan-matrix`: every negative control, one process each, TSan's verdict next to the actual answer.

| variant | protection | TSan | answer |
|---|---|---|---|
| plain | none | race | wrong |
| split_atomic | atomic load, then atomic store | clean | wrong |
| mutex | `std::mutex` per increment | clean | correct |
| fetch_add | atomic read-modify-write | clean | correct |
| reduction | private sums, one combine | clean | correct |
| no_barrier | double buffer, no barrier | race | wrong |
| in_place_1 | barrier, one buffer, one thread | clean | wrong |
| in_place | barrier, one buffer | race | wrong |
| barrier | double buffer + `AtomicBarrier` | clean | correct |
| barrier_std | double buffer + `std::barrier` | race (macOS) | correct |

### 4. The std::barrier Report on macOS

On macOS TSan reports races in the `std::barrier` engine: 124 of them over a full run, whose answers were all correct (4,726,438 checks, 0 failures).

- Every reported pair crosses the barrier: the completion step reading `partial[]` and writing `cur` (`engines.hpp:255-257`), and kernels reading rows another thread wrote the previous generation (`kernels.hpp:200-206, 226-228`).
- Cause: libc++ declares `__arrive_barrier_algorithm_base` `_LIBCPP_EXPORTED_FROM_ABI` and implements the arrival tree in `libc++.dylib`, which is not instrumented. TSan cannot see the ordering from each arrival to the completion step.
- The other ordering is visible: the completion step's `release` store of the phase and the waiters' `acquire` polling load are in the header (`<barrier>` lines 139 and 145). One missing link is enough. Every reported pair crosses a phase boundary through arrival, completion and return; without the first link TSan sees the chain as broken.
- Upstream libc++ implements that tree with `acq_rel` compare-exchange (`libcxx/src/barrier.cpp`), which provides the ordering the standard requires. Apple's dylib source is not on this machine, so that detail comes from the upstream source. What was checked here: the header (above), the correct answers on every run, and the probe below.
- `make tsan-probe` isolates it: a program where threads write their own slot and the completion step sums the slots. `std::barrier`: correct sum, race reported. `AtomicBarrier`: correct sum, clean.
- The gated TSan run therefore uses the mutex and atomic families; `make tsan-stdbarrier` runs the `std::barrier` family and reports without gating. On Linux, libstdc++ implements `std::barrier` in headers TSan instruments; CI records the result there.

## Limits of Automated Tools

| case | TSan | answer | what it shows |
|---|---|---|---|
| split_atomic | clean | wrong | free of data races and still wrong: every access atomic, the increment not |
| in_place_1 | clean | wrong | one thread, no concurrency at all: a logic error the tool cannot see |
| barrier_std on macOS | race | correct | ordering inside an uninstrumented library is invisible to the tool |

- A TSan verdict is evidence about the schedules that ran and the code the tool could see. It fails in both directions above.
- The proof covers every schedule and every size by argument, and the exhaustive exploration checks the protocol against every schedule of small instances by enumeration. TSan, the stress runs and the golden vectors check that the compiled code matches the model.

## Cost of Each Protection

Per-generation time on the M2 Pro, bit-sliced kernel, from [`results/laptop_bench.csv`](../software_prototype/cpp/results/laptop_bench.csv). Throughput is the median of 5 timed runs; latency timestamps every generation boundary.

| 16x16, 4 threads | p50 | p99 | throughput |
|---|---|---|---|
| `AtomicBarrier` | 625 ns | 667 ns | 1.67 M gen/s |
| `std::barrier` | 833 ns | 1.00 µs | 1.27 M gen/s |
| mutex + condition variable | 8.29 µs | 24.6 µs | 119 k gen/s |
| one thread, no synchronization | 106 ns (mean) | timer-limited | 10.4 M gen/s |

- At small grids the generation boundary is nearly the whole cost. The mutex and condition variable make it 13x slower than `AtomicBarrier` at p50 and 37x at p99: every waiter sleeps and the kernel has to wake it.
- The gap closes as compute grows. Mutex against `AtomicBarrier` at p50, 4 threads: 13x at 16x16, 4.5x at 256x256, 1.1x at 2048x2048.
- Up to 64x64 one thread with no synchronization beats every threaded configuration. Threads pay off from 128x128 (1.8x one core) to 2048x2048 (3.9x).
- Spinning is a trade. `AtomicBarrier` spins briefly before sleeping. With a core per thread it beats `std::barrier`, 1.2x to 1.4x at 16x16 with 2 to 6 threads. With 10 threads on 10 cores the spinning threads take cycles from the threads they wait for, and it falls to 0.13x of `std::barrier`, whose back-off handles that case.
- Six threads is the best count at every size where threads help: the M2 Pro has six performance cores. Adding the four efficiency cores slows the run (for `AtomicBarrier`, 10 threads reach 8% to 86% of 6 threads' throughput from 256x256 to 2048x2048). A barrier waits for its slowest thread, and a static partition gives the slow cores as many rows as the fast ones.
- The shared counter shows the same ordering at the level of one variable: 41.7 ns per increment with a mutex, 0.1 ns with private sums.
- The FPGA pays none of this. Its generation boundary is the clock edge, measured at one clock per generation with no jitter.

## Limits

- The proof covers the protocol for every T, grid size and rule. The kernel's sequential correctness is exhaustive at 4x4 only, checked against golden trajectories from 1x1 to 128x128, and randomized up to 256x256. At other sizes it is tested without a proof.
- The model checker covers 3x3 and 4x4 tori over two generations; the reduction argument extends its result to finer interleavings; larger grids rely on the proof.
- TSan observes the schedules that ran.
- `std::barrier`'s correctness is taken from the standard and, for libc++, from its upstream source; on macOS TSan cannot confirm it. `AtomicBarrier` exists so a barrier checked end to end is available.
- All measurements are from one Apple M2 Pro. CI repeats the correctness checks with GCC on Linux once the branch is pushed.

## Reproduce

```bash
cd software_prototype/cpp
make test          # golden vectors, every layer
make tsan          # the suite under ThreadSanitizer
make tsan-matrix   # the verdict table above
make tsan-probe    # the std::barrier report, isolated
make prove         # every schedule of the small instances
make races         # the counter table above, with timings
```
