// tsan_barrier_probe.cpp
//
// The smallest program that shows why the ThreadSanitizer run excludes the
// std::barrier engine family on macOS.
//
// Four threads each write their own slot, then arrive at a barrier. The
// barrier's completion step, run once by whichever thread arrives last,
// reads every slot. C++20 [thread.barrier.class] says each arrival
// strongly happens-before the completion step, so this program has no data
// race, and it always prints the right sum.
//
// Built with -fsanitize=thread against Apple's libc++, TSan reports a race
// for std::barrier anyway. libc++ declares __arrive_barrier_algorithm_base
// _LIBCPP_EXPORTED_FROM_ABI and implements it in libc++.dylib; the
// acquire/release that orders the arrivals lives there, in code TSan never
// instrumented, so it sees a write and a read with nothing between them.
// Swap in AtomicBarrier from engines.hpp (every operation in a header TSan
// does instrument) and the report goes away. Same program, same answer,
// opposite verdicts: the verdict depends on what the tool could see.
//
//   make tsan-probe

#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

#include "cellnet/engines.hpp"

using namespace cellnet;

namespace {

template <template <class> class B>
uint64_t run() {
    constexpr int kThreads = 4;
    constexpr int kPhases = 200;
    std::vector<PaddedCount> slot(kThreads);
    uint64_t sum = 0;  // touched only by the completion step
    auto completion = [&]() noexcept {
        for (const PaddedCount& s : slot) sum += s.v;
    };
    B<decltype(completion)> barrier(kThreads, completion);
    {
        std::vector<std::jthread> pool;
        for (int t = 0; t < kThreads; ++t)
            pool.emplace_back([&, t] {
                for (int k = 1; k <= kPhases; ++k) {
                    slot[static_cast<std::size_t>(t)].v = static_cast<uint64_t>(k);  // own slot, before arriving
                    barrier.arrive_and_wait();
                }
            });
    }
    return sum;
}

}  // namespace

int main(int argc, char** argv) {
    const bool use_std = argc > 1 && std::strcmp(argv[1], "std") == 0;
    const uint64_t got = use_std ? run<StdBarrier>() : run<AtomicBarrier>();
    const uint64_t want = 4ull * 200 * 201 / 2;
    std::printf("%-14s sum %llu, expected %llu: %s\n", use_std ? "std::barrier" : "AtomicBarrier",
                static_cast<unsigned long long>(got), static_cast<unsigned long long>(want),
                got == want ? "correct" : "WRONG");
    return got == want ? 0 : 1;
}
