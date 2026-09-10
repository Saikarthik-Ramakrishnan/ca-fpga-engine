// races.cpp
//
// Negative controls. Each variant takes one protection out of the design
// and shows what it was preventing. A check that cannot fail proves
// nothing; these are the evidence that test_correctness.cpp and
// ThreadSanitizer can see the bugs they are claimed to rule out.
//
// Everything in this file is broken on purpose except the variants marked
// correct. The racy ones contain data races, which are undefined behavior
// in C++; they exist only as demonstrations and are linked into nothing.
//
// Shared counter. T threads count the live cells of a soup into one shared
// total: the textbook exposed shared variable.
//   plain          unprotected read-modify-write            data race
//   split_atomic   atomic load, then a separate atomic      no data race, yet
//                  store                                    it loses updates
//   mutex          std::mutex around every increment        correct
//   fetch_add      one atomic read-modify-write             correct
//   reduction      each thread sums privately, combines     correct
//                  once at the end
//
// Grid. The CA step itself with one protection removed.
//   no_barrier     double buffer, nothing between generations
//   in_place_1     barrier but one buffer, a single thread (no concurrency)
//   in_place       barrier but one buffer, T threads
//   barrier        the real engine with AtomicBarrier, as the control
//   barrier_std    the same engine with std::barrier. Correct, and under
//                  TSan on macOS a false positive: see engines.hpp
//
// The grid oracle is serial/scalar, which test_correctness.cpp layer 3
// pins to golden_rule.py. The counter oracle is the population itself.
//
//   build/races                    every variant, summary table
//   build/races --variant NAME     one variant; tools/tsan_matrix.sh uses this

#include <atomic>
#include <barrier>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "cellnet/engines.hpp"

using namespace cellnet;

namespace {

// TSan slows code 5-15x, so its workloads are smaller. The races still
// happen; they only need to happen once for the tool to report them.
constexpr int kThreads = 8;
constexpr int kCounterSide = CELLNET_TSAN ? 96 : 512;
constexpr int kCounterPasses = CELLNET_TSAN ? 4 : 20;
constexpr int kGridSide = CELLNET_TSAN ? 32 : 64;
constexpr int kGridGens = CELLNET_TSAN ? 60 : 400;
constexpr int kGridTrials = CELLNET_TSAN ? 3 : 20;

template <class F>
void run_threads(int T, F&& f) {
    std::vector<std::jthread> pool;
    pool.reserve(static_cast<std::size_t>(T - 1));
    for (int t = 1; t < T; ++t) pool.emplace_back([&f, t] { f(t); });
    f(0);
}

// ------------------------------------------------------------ counter

struct CounterRun {
    uint64_t got;
    double ns_per_increment;
};

template <class Body>
CounterRun time_counter(const Grid& g, uint64_t increments, Body&& body) {
    const int64_t t0 = now_ns();
    const uint64_t got = body();
    const double ns = static_cast<double>(now_ns() - t0);
    return {got, increments ? ns / static_cast<double>(increments) : 0.0};
    (void)g;
}

// Calls inc(t) once per live cell in thread t's rows, `passes` times over.
template <class Inc>
void for_each_live(const Grid& g, int T, int passes, Inc&& inc) {
    run_threads(T, [&](int t) {
        const auto [r0, r1] = partition(g.rows, T, t);
        for (int p = 0; p < passes; ++p)
            for (int r = r0; r < r1; ++r)
                for (int c = 0; c < g.cols; ++c)
                    if (g.at(r, c)) inc(t);
    });
}

CounterRun counter_plain(const Grid& g, uint64_t n) {
    return time_counter(g, n, [&] {
        uint64_t total = 0;
        volatile uint64_t* shared = &total;  // forces a real load and store each time
        for_each_live(g, kThreads, kCounterPasses, [&](int) {
            *shared = *shared + 1;  // load, add, store: another thread can land between any two
        });
        return total;
    });
}

CounterRun counter_split_atomic(const Grid& g, uint64_t n) {
    return time_counter(g, n, [&] {
        std::atomic<uint64_t> total{0};
        for_each_live(g, kThreads, kCounterPasses, [&](int) {
            // Each access is atomic, so there is no data race and TSan stays
            // quiet. The increment as a whole is not atomic: two threads can
            // load the same value and both store value + 1.
            total.store(total.load(std::memory_order_relaxed) + 1, std::memory_order_relaxed);
        });
        return total.load();
    });
}

CounterRun counter_mutex(const Grid& g, uint64_t n) {
    return time_counter(g, n, [&] {
        std::mutex m;
        uint64_t total = 0;
        for_each_live(g, kThreads, kCounterPasses, [&](int) {
            std::lock_guard lk(m);
            ++total;
        });
        return total;
    });
}

CounterRun counter_fetch_add(const Grid& g, uint64_t n) {
    return time_counter(g, n, [&] {
        std::atomic<uint64_t> total{0};
        for_each_live(g, kThreads, kCounterPasses, [&](int) { total.fetch_add(1, std::memory_order_relaxed); });
        return total.load();
    });
}

CounterRun counter_reduction(const Grid& g, uint64_t n) {
    return time_counter(g, n, [&] {
        std::vector<PaddedCount> partial(kThreads);
        run_threads(kThreads, [&](int t) {
            const auto [r0, r1] = partition(g.rows, kThreads, t);
            uint64_t local = 0;  // private: nobody else can see it
            for (int p = 0; p < kCounterPasses; ++p)
                for (int r = r0; r < r1; ++r)
                    for (int c = 0; c < g.cols; ++c) local += g.at(r, c);
            partial[static_cast<std::size_t>(t)].v = local;  // own slot, written once
        });  // join orders every slot write before the sum below
        uint64_t total = 0;
        for (const auto& p : partial) total += p.v;
        return total;
    });
}

// --------------------------------------------------------------- grid

Grid grid_no_barrier(const Grid& start, Rule rule, int T, int gens) {
    Grid buf[2] = {start, Grid(start.rows, start.cols)};
    std::barrier start_line(T);
    run_threads(T, [&](int t) {
        const auto [r0, r1] = partition(start.rows, T, t);
        start_line.arrive_and_wait();  // everyone starts together...
        for (int k = 0; k < gens; ++k) ScalarKernel::step(buf[k & 1], buf[(k + 1) & 1], r0, r1, rule);
        // ...and after that nothing stops generation k+1 reading rows a
        // neighbor is still writing for generation k.
    });
    return buf[gens & 1];
}

Grid grid_in_place(const Grid& start, Rule rule, int T, int gens) {
    Grid buf = start;
    std::barrier sync(T);
    run_threads(T, [&](int t) {
        const auto [r0, r1] = partition(start.rows, T, t);
        for (int k = 0; k < gens; ++k) {
            // in and out are the same buffer: cells read here may already
            // hold this generation's value instead of the previous one's
            ScalarKernel::step(buf, buf, r0, r1, rule);
            sync.arrive_and_wait();
        }
    });
    return buf;
}

Grid grid_barrier(const Grid& start, Rule rule, int T, int gens) {
    Grid g = start;
    make_engine("atomic", "scalar", T)->run(g, rule, gens);
    return g;
}

Grid grid_barrier_std(const Grid& start, Rule rule, int T, int gens) {
    Grid g = start;
    make_engine("barrier", "scalar", T)->run(g, rule, gens);
    return g;
}

Grid oracle(const Grid& start, Rule rule, int gens) {
    Grid g = start;
    make_engine("serial", "scalar", 1)->run(g, rule, gens);
    return g;
}

struct GridVerdict {
    int diverged;
    int trials;
};

template <class Variant>
GridVerdict grid_trials(Variant&& variant, int T) {
    const Rule conway = kRules[0].rule;
    int diverged = 0;
    for (int i = 0; i < kGridTrials; ++i) {
        const Grid start = random_grid(kGridSide, kGridSide, 0.35, 1000 + static_cast<uint64_t>(i));
        if (!(variant(start, conway, T, kGridGens) == oracle(start, conway, kGridGens))) ++diverged;
    }
    return {diverged, kGridTrials};
}

// -------------------------------------------------------------- driver

struct Row {
    std::string name, protection, answer, detail;
};

Row run_variant(const std::string& v) {
    const Grid soup = random_grid(kCounterSide, kCounterSide, 0.35, 42);
    const uint64_t expect = soup.population() * kCounterPasses;
    char buf[160];

    auto counter_row = [&](const char* name, const char* prot, CounterRun r) {
        const uint64_t lost = expect > r.got ? expect - r.got : 0;
        std::snprintf(buf, sizeof buf, "%llu of %llu increments lost, %.1f ns per increment",
                      static_cast<unsigned long long>(lost), static_cast<unsigned long long>(expect),
                      r.ns_per_increment);
        return Row{name, prot, r.got == expect ? "correct" : "WRONG", buf};
    };
    auto grid_row = [&](const char* name, const char* prot, GridVerdict gv, int T) {
        std::snprintf(buf, sizeof buf, "T=%d, %d of %d trials diverged from the oracle (%dx%d, %d generations)", T,
                      gv.diverged, gv.trials, kGridSide, kGridSide, kGridGens);
        return Row{name, prot, gv.diverged ? "WRONG" : "correct", buf};
    };

    if (v == "plain") return counter_row("plain", "none", counter_plain(soup, expect));
    if (v == "split_atomic")
        return counter_row("split_atomic", "atomic load, then atomic store", counter_split_atomic(soup, expect));
    if (v == "mutex") return counter_row("mutex", "std::mutex per increment", counter_mutex(soup, expect));
    if (v == "fetch_add") return counter_row("fetch_add", "atomic read-modify-write", counter_fetch_add(soup, expect));
    if (v == "reduction")
        return counter_row("reduction", "private sums, one combine", counter_reduction(soup, expect));
    if (v == "no_barrier")
        return grid_row("no_barrier", "double buffer, no barrier", grid_trials(grid_no_barrier, kThreads), kThreads);
    if (v == "in_place_1")
        return grid_row("in_place_1", "barrier, one buffer, one thread", grid_trials(grid_in_place, 1), 1);
    if (v == "in_place")
        return grid_row("in_place", "barrier, one buffer", grid_trials(grid_in_place, kThreads), kThreads);
    if (v == "barrier")
        return grid_row("barrier", "double buffer + AtomicBarrier", grid_trials(grid_barrier, kThreads), kThreads);
    if (v == "barrier_std")
        return grid_row("barrier_std", "double buffer + std::barrier", grid_trials(grid_barrier_std, kThreads),
                        kThreads);
    std::fprintf(stderr, "unknown variant %s\n", v.c_str());
    std::exit(2);
}

const char* const kVariants[] = {"plain",      "split_atomic", "mutex",    "fetch_add", "reduction",
                                 "no_barrier", "in_place_1",   "in_place", "barrier",   "barrier_std"};

}  // namespace

int main(int argc, char** argv) {
    if (argc == 3 && std::strcmp(argv[1], "--variant") == 0) {
        const Row r = run_variant(argv[2]);
        std::printf("%s: %s\nANSWER=%s\n", r.name.c_str(), r.detail.c_str(), r.answer.c_str());
        return 0;  // under TSan, the tool sets the exit code when it reports
    }
    if (argc != 1) {
        std::fprintf(stderr, "usage: %s [--variant NAME]\n", argv[0]);
        return 2;
    }

    std::printf("Negative controls: one protection removed per variant.%s\n",
                CELLNET_TSAN ? " (ThreadSanitizer build: workloads scaled down)" : "");
    std::printf("Grid oracle: serial/scalar, pinned to golden_rule.py by test_correctness layer 3.\n\n");
    std::printf("%-13s %-33s %-8s %s\n", "variant", "protection", "answer", "detail");
    for (const char* v : kVariants) {
        const Row r = run_variant(v);
        std::printf("%-13s %-33s %-8s %s\n", r.name.c_str(), r.protection.c_str(), r.answer.c_str(),
                    r.detail.c_str());
        std::fflush(stdout);
    }
    return 0;
}
