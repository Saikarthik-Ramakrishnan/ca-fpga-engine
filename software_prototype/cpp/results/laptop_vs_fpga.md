# Laptop vs FPGA: throughput and latency

- Laptop: Apple M2 Pro, 6 performance + 4 efficiency cores, Apple LLVM 21.0.0, `-std=c++20 -O3 -mcpu=native`, measured 2026-09-10.
- FPGA: clocks per generation and link timing measured in cycle-accurate RTL simulation of `cellnet_top`, converted at the 27 MHz dock clock. Not yet measured on the board.
- Routed Fmax is the post-route timing ceiling of the Phase 5a fixed-rule build. The dock oscillator is 27 MHz; running at Fmax would need a PLL that is not in the design.
- Rule: Conway B3/S23. Laptop engines also count the population every generation; the fabric does not, so the laptop does slightly more work per generation.

## Throughput

Generations per second. One generation of the fabric is one clock edge, measured.

| grid | laptop, 1 core | laptop, best configuration | FPGA at 27 MHz | FPGA at routed Fmax | FPGA 27 MHz vs best laptop |
|---|---|---|---|---|---|
| 8x8 | 19.3 M (serial/bitslice) | 19.3 M (serial/bitslice, 1 thread) | 27 M | not routed | 1.4x |
| 16x16 | 10.4 M (serial/bitslice) | 10.4 M (serial/bitslice, 1 thread) | 27 M | 240 M | 2.6x |
| 24x24 | 6.72 M (serial/bitslice) | 6.72 M (serial/bitslice, 1 thread) | 27 M | not routed | 4.0x |
| 32x32 | 5.1 M (serial/bitslice) | 5.1 M (serial/bitslice, 1 thread) | 27 M | 176 M | 5.3x |
| 64x64 | 2.47 M (serial/bitslice) | 2.47 M (serial/bitslice, 1 thread) | does not fit | does not fit | n/a |
| 128x128 | 687 k (serial/bitslice) | 1.22 M (atomic/bitslice, 6 threads) | does not fit | does not fit | n/a |
| 256x256 | 185 k (serial/bitslice) | 509 k (barrier/bitslice, 6 threads) | does not fit | does not fit | n/a |
| 512x512 | 47.5 k (serial/bitslice) | 167 k (barrier/bitslice, 6 threads) | does not fit | does not fit | n/a |
| 1024x1024 | 11.5 k (serial/bitslice) | 43.5 k (barrier/bitslice, 6 threads) | does not fit | does not fit | n/a |
| 2048x2048 | 2.43 k (serial/bitslice) | 9.46 k (barrier/bitslice, 6 threads) | does not fit | does not fit | n/a |

## Latency per generation

Time from one generation being complete to the next being complete. Laptop: every generation boundary timestamped, distribution over the run. FPGA: clocks per generation counted every clock for 64 generations; the count was 1 every time, so the distribution is a single value.

### 16x16

| implementation | mean from throughput | p50 | p99 | p99.9 | max | p99 / p50 |
|---|---|---|---|---|---|---|
| FPGA fabric, routed Fmax (ceiling) | 4.16 ns | 4.16 ns | 4.16 ns | 4.16 ns | 4.16 ns | 1.00 |
| FPGA fabric, 27 MHz | 37 ns | 37 ns | 37 ns | 37 ns | 37 ns | 1.00 |
| laptop, 1 core (serial/bitslice) (timer-limited) | 96.2 ns | 125 ns | 125 ns | 208 ns | 209 ns | 1.00 |
| laptop, AtomicBarrier, 4 threads | 600 ns | 625 ns | 667 ns | 10.4 µs | 12.5 µs | 1.07 |
| laptop, std::barrier, 4 threads | 789 ns | 833 ns | 1 µs | 4.54 µs | 18.6 µs | 1.20 |
| laptop, mutex + condvar, 4 threads | 8.43 µs | 8.29 µs | 24.6 µs | 30.5 µs | 39.1 µs | 2.97 |

### 32x32

| implementation | mean from throughput | p50 | p99 | p99.9 | max | p99 / p50 |
|---|---|---|---|---|---|---|
| FPGA fabric, routed Fmax (ceiling) | 5.67 ns | 5.67 ns | 5.67 ns | 5.67 ns | 5.67 ns | 1.00 |
| FPGA fabric, 27 MHz | 37 ns | 37 ns | 37 ns | 37 ns | 37 ns | 1.00 |
| laptop, 1 core (serial/bitslice) (latency run 2.6x slower than the throughput runs) | 196 ns | 500 ns | 625 ns | 12.2 µs | 100 µs | 1.25 |
| laptop, AtomicBarrier, 4 threads | 592 ns | 542 ns | 625 ns | 709 ns | 4.96 µs | 1.15 |
| laptop, std::barrier, 4 threads | 701 ns | 708 ns | 834 ns | 917 ns | 7.54 µs | 1.18 |
| laptop, mutex + condvar, 4 threads | 8.48 µs | 8.25 µs | 17.9 µs | 22.4 µs | 32.6 µs | 2.17 |

Laptop clock tick is 41.0 ns (Apple silicon's 24 MHz system counter). Rows whose p50 is under ten ticks are marked timer-limited: their percentiles are quantized, and the mean from throughput (five timed runs, no timestamps) is the number to use.

- 32x32, laptop, 1 core (serial/bitslice): its single timestamped latency run was 2.6x slower than the median of its five throughput runs, while every other row at that size agrees within 10%. macOS places threads by quality of service with no hard affinity, and can keep one run on an efficiency core. The row is shown as measured; its throughput mean is the better estimate.

## Getting bits on and off the FPGA (16x16, 115200 baud)

Measured cycle-accurately through the real pins with the deployed parameters.

| quantity | clocks | time at 27 MHz |
|---|---|---|
| one generation of the fabric | 1 | 37 ns |
| seed transfer in (33 bytes) | 77,220 | 2.860 ms |
| frame period out | 77,320 | 2.864 ms (349 frames/s) |
| seed to first frame carrying it (measured) | 77,299 | 2.863 ms |
| seed to frame, possible range | 77,086 to 154,640 | 2.855 to 5.727 ms |

The fabric computes a generation in 37 ns; the UART needs 2.86 ms to report one. End-to-end latency is set by the link, by a factor of about 77,320.

