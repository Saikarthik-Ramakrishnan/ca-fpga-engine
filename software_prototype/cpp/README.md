# C++ engine: concurrency, correctness proof, laptop vs FPGA

The parallel CA engine in C++20, with every shared variable accounted for,
checked against `golden_rule.py`, and timed against the FPGA fabric.

- Correctness argument and evidence: [`docs/CONCURRENCY.md`](../../docs/CONCURRENCY.md)
- Laptop vs FPGA numbers: [`results/laptop_vs_fpga.md`](results/laptop_vs_fpga.md)

## The engines

Two kernels times four ways of synchronizing threads. Every combination is
tested and benchmarked.

| kernel | what it is |
|---|---|
| `scalar` | the rule as `golden_rule.py` writes it, one byte per cell |
| `bitslice` | 64 cells per machine word: a bitwise adder tree to a 4-bit count, then a mask lookup. `ca_cell.v`'s structure with each wire 64 bits wide |

| sync | how threads are kept apart |
|---|---|
| `serial` | one thread, two buffers, a swap |
| `mutex` | every shared variable behind one `std::mutex`; generation boundary from a mutex and a condition variable |
| `barrier` | C++20 `std::barrier`; per-thread population slots summed in the completion step |
| `atomic` | the same engine with `AtomicBarrier`, two atomics written out in `engines.hpp` |

## Files

```
software_prototype/cpp/
├── include/cellnet/
│   ├── grid.hpp              # Rule, Grid, the one-cell rule
│   ├── kernels.hpp           # scalar and bit-sliced step, and their contract
│   └── engines.hpp           # the engines, AtomicBarrier, the shared-state table
├── src/
│   ├── test_correctness.cpp  # five layers against golden_rule.py vectors
│   ├── races.cpp             # negative controls: each protection removed in turn
│   ├── tsan_barrier_probe.cpp# the std::barrier TSan false positive, isolated
│   └── bench.cpp             # throughput and latency, gated on correctness
├── tools/
│   ├── gen_vectors.py        # golden_rule.py -> test vectors
│   ├── prove_schedules.py    # exhaustive schedule exploration
│   ├── tsan_matrix.sh        # TSan verdict vs actual answer, per variant
│   └── compare_fpga.py       # laptop CSV + RTL cycle counts -> tables, figures
└── results/                  # benchmark CSV, machine info, comparison
```

## Running it

```bash
cd software_prototype/cpp
make test          # vectors from golden_rule.py, then every layer
make tsan          # the same suite under ThreadSanitizer
make tsan-matrix   # negative controls: what TSan catches, what it cannot
make prove         # every interleaving, every initial grid, small tori
make bench         # laptop numbers into results/
make check         # test + tsan + tsan-matrix + prove
```

The FPGA side of the comparison comes from cycle-accurate RTL simulation:

```bash
cd hardware/tests
make -f Makefile.fabric_latency ROWS=16 COLS=16   # also 8, 24, 32
make -f Makefile.link_latency                     # real 115200 baud
cd ../../software_prototype/cpp && python3 tools/compare_fpga.py
```

## Chain of trust

- `golden_rule.py` is the only reference. `gen_vectors.py` writes its
  answers to disk; the C++ never checks itself against itself.
- `serial/scalar` is pinned to those vectors (layer 3), and only then used as
  the oracle for randomized stress, rectangular grids and the race demos.
- The benchmark refuses to time an engine whose output differs from that
  oracle.
