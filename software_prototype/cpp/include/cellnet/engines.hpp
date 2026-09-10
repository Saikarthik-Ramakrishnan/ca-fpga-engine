// engines.hpp
//
// Where the concurrency lives. Every engine evolves a grid through `gens`
// synchronous generations; they differ only in how threads are kept from
// corrupting each other. docs/CONCURRENCY.md proves the barrier engine
// correct, and this header is the code that proof is about.
//
// SHARED STATE, AND WHAT PROTECTS EACH PIECE (barrier engines)
//
//   state              who touches it                 protection
//   -----------------  -----------------------------  ------------------------------
//   buf[cur]           every thread reads, no writes  read-only for the whole phase
//   buf[cur ^ 1]       thread t writes its own rows   disjoint ownership (partition)
//   cur, gen, trace    changed between generations    barrier completion step only
//   population         one partial per thread         own padded slot per thread,
//                                                     summed once in completion
//
// The generation boundary comes in two builds of one engine: `barrier`
// uses C++20 std::barrier, `atomic` uses AtomicBarrier below, two atomics
// written out in this header. MutexEngine protects the same state with a
// mutex and a condition variable, for comparison. src/races.cpp takes each
// protection away in turn to show what it was preventing.
//
// Hardware twin: in ca_grid.v each cell's flip-flop is its own buf[cur]
// (the Q output its neighbors read) and buf[cur ^ 1] (the D input only
// that cell drives), and the clock edge is the barrier. The FPGA is
// race-free for the same reason the barrier engine is; the difference is
// that its synchronization is silicon instead of a library call.

#pragma once

#include <atomic>
#include <barrier>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#if defined(__APPLE__)
#include <pthread.h>
#include <sys/qos.h>
#endif

#include "cellnet/grid.hpp"
#include "cellnet/kernels.hpp"

// True when built with -fsanitize=thread (clang or gcc).
#if defined(__SANITIZE_THREAD__)
#define CELLNET_TSAN 1
#elif defined(__has_feature)
#if __has_feature(thread_sanitizer)
#define CELLNET_TSAN 1
#endif
#endif
#ifndef CELLNET_TSAN
#define CELLNET_TSAN 0
#endif

namespace cellnet {

inline int64_t now_ns() noexcept {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

// macOS places threads by quality-of-service class and has no hard
// affinity. Asking for the interactive class keeps workers on performance
// cores where the scheduler can; it is a request, not a pin.
inline void prefer_performance_cores() noexcept {
#if defined(__APPLE__)
    pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
#endif
}

// Each thread's partial population on its own cache line. M-series lines
// are 128 bytes (sysctl hw.cachelinesize). The result is correct without
// the padding, since each thread writes only its own slot; the padding
// stops neighbors' writes invalidating each other's lines (false
// sharing), which costs time and never correctness.
struct alignas(128) PaddedCount {
    uint64_t v = 0;
};

// Rows [r0, r1) for thread t of T: contiguous, as even as possible. With
// more threads than rows some threads own no rows and only take part in
// the barrier. The tests run that case on purpose.
inline std::pair<int, int> partition(int rows, int T, int t) {
    return {static_cast<int>(static_cast<int64_t>(rows) * t / T),
            static_cast<int>(static_cast<int64_t>(rows) * (t + 1) / T)};
}

// Optional record of a run. Everything is sized before the run starts, so
// filling it in (inside the barrier's noexcept completion step) never
// allocates.
struct Trace {
    bool keep_grids = false;
    bool timestamps = false;
    std::vector<Grid> grids;           // grids[k]: state after generation k+1
    std::vector<uint64_t> population;  // population[k]: live cells in grids[k]
    std::vector<int64_t> t_ns;         // t_ns[0]: start line; t_ns[k+1]: end of generation k+1

    void prepare(const Grid& g, int gens) {
        population.assign(static_cast<std::size_t>(gens), 0);
        grids.assign(keep_grids ? static_cast<std::size_t>(gens) : 0, Grid(g.rows, g.cols));
        t_ns.assign(timestamps ? static_cast<std::size_t>(gens) + 1 : 0, 0);
    }
};

template <class K>
inline void record(Trace* tr, int k, uint64_t pop, const typename K::Buffer& cur) noexcept {
    if (!tr) return;
    tr->population[static_cast<std::size_t>(k)] = pop;
    if (tr->keep_grids) K::snapshot(cur, tr->grids[static_cast<std::size_t>(k)]);
    if (tr->timestamps) tr->t_ns[static_cast<std::size_t>(k) + 1] = now_ns();
}

class Engine {
public:
    virtual ~Engine() = default;
    virtual std::string name() const = 0;
    virtual int threads() const = 0;
    // Evolve g through `gens` generations under `rule`. On return g holds
    // the final generation.
    virtual void run(Grid& g, Rule rule, int gens, Trace* trace = nullptr) = 0;
};

// ------------------------------------------------------------------ serial
// One thread, two buffers, a swap. The baseline the threaded engines are
// timed against, and itself checked against golden_rule.py.
template <class K>
class SerialEngine final : public Engine {
public:
    std::string name() const override { return std::string("serial/") + K::kName; }
    int threads() const override { return 1; }

    void run(Grid& g, Rule rule, int gens, Trace* tr) override {
        if (tr) tr->prepare(g, gens);
        typename K::Buffer a = K::load(g);
        typename K::Buffer b = K::blank_like(a);
        if (tr && tr->timestamps) tr->t_ns[0] = now_ns();
        for (int k = 0; k < gens; ++k) {
            const uint64_t pop = K::step(a, b, 0, K::rows(a), rule);
            std::swap(a, b);
            record<K>(tr, k, pop, a);
        }
        K::store(a, g);
    }
};

// ----------------------------------------------------------- AtomicBarrier
// A generation barrier built from two atomics. It exists for two reasons.
//
// 1. It is the synchronization written out instead of hidden in a library:
//    one counter every thread decrements, one phase number the last thread
//    advances. docs/CONCURRENCY.md proves it; the argument is short.
// 2. ThreadSanitizer can see all of it. libc++ runs std::barrier's arrival
//    tree inside libc++.dylib (the header declares
//    __arrive_barrier_algorithm_base _LIBCPP_EXPORTED_FROM_ABI), and that
//    library is not instrumented. TSan therefore cannot see the
//    acquire/release that orders each thread's arrival before the
//    completion step, and reports a race that is not there.
//    src/tsan_barrier_probe.cpp reproduces it in a few dozen lines. This
//    barrier lives entirely in this header, so TSan checks every operation.
//
// Why it is correct:
//   - Each arriving thread does fetch_sub(acq_rel) on left_. Those
//     read-modify-writes form one release sequence, so every earlier
//     arrival's release synchronizes-with the last arrival's acquire:
//     everything any thread wrote before arriving happens-before the
//     completion step.
//   - The last arriver runs the completion step, resets left_, then stores
//     the next phase with release. A waiter leaves only after an acquire
//     load sees that phase, so the completion step and the reset
//     happen-before everything the waiter does next.
//   - No thread can arrive twice in one phase: after arriving it waits for
//     the phase to change, and the phase changes only after the reset.
template <class Completion>
class AtomicBarrier {
public:
    AtomicBarrier(int count, Completion completion)
        : count_(count), left_(count), completion_(std::move(completion)) {}

    void arrive_and_wait() noexcept {
        // Relaxed is enough: this thread last saw (or wrote) this phase, and
        // the phase cannot move again until this thread arrives.
        const uint32_t my_phase = phase_.load(std::memory_order_relaxed);
        if (left_.fetch_sub(1, std::memory_order_acq_rel) == 1) {
            completion_();
            left_.store(count_, std::memory_order_relaxed);
            phase_.store(my_phase + 1, std::memory_order_release);
            phase_.notify_all();
            return;
        }
        // Spin briefly first: at small grids a whole generation is shorter
        // than putting a thread to sleep and waking it.
        for (int i = 0; i < 4096; ++i)
            if (phase_.load(std::memory_order_acquire) != my_phase) return;
        while (phase_.load(std::memory_order_acquire) == my_phase)
            phase_.wait(my_phase, std::memory_order_acquire);
    }

private:
    const int count_;
    alignas(128) std::atomic<int> left_;
    alignas(128) std::atomic<uint32_t> phase_{0};
    Completion completion_;
};

template <class F>
using StdBarrier = std::barrier<F>;

// ----------------------------------------------------------------- barrier
// T threads, a static row partition, a barrier between generations. No
// mutex anywhere, and no shared variable is written during a generation.
// B is std::barrier (engine name "barrier") or AtomicBarrier ("atomic");
// the engine is otherwise identical, so the two isolate the primitive.
template <class K, template <class> class B>
class BarrierEngine final : public Engine {
public:
    BarrierEngine(int threads, const char* sync_name)
        : T_(threads < 1 ? 1 : threads), sync_name_(sync_name) {}
    std::string name() const override { return std::string(sync_name_) + "/" + K::kName; }
    int threads() const override { return T_; }

    void run(Grid& g, Rule rule, int gens, Trace* tr) override {
        if (tr) tr->prepare(g, gens);
        typename K::Buffer buf[2] = {K::load(g), {}};
        buf[1] = K::blank_like(buf[0]);
        const int R = K::rows(buf[0]);
        std::vector<PaddedCount> partial(static_cast<std::size_t>(T_));

        // Written only inside the completion step. Workers read `cur` only
        // after returning from arrive_and_wait, and the standard orders the
        // completion step before those returns ([thread.barrier.class]: the
        // completion step happens-before the return from every call that
        // was blocked on that phase). That ordering is the whole protection.
        int cur = 0;
        int gen = 0;
        bool started = false;

        auto on_phase_complete = [&]() noexcept {
            if (!started) {  // the start line: every worker is up and waiting
                started = true;
                if (tr && tr->timestamps) tr->t_ns[0] = now_ns();
                return;
            }
            uint64_t pop = 0;
            for (const PaddedCount& p : partial) pop += p.v;
            cur ^= 1;  // the swap: next becomes current
            record<K>(tr, gen, pop, buf[cur]);
            ++gen;
        };
        B<decltype(on_phase_complete)> sync(T_, on_phase_complete);

        auto work = [&](int t) {
            prefer_performance_cores();
            const auto [r0, r1] = partition(R, T_, t);
            sync.arrive_and_wait();  // start line
            for (int k = 0; k < gens; ++k) {
                const int c = cur;  // cannot change until every thread arrives
                partial[static_cast<std::size_t>(t)].v = K::step(buf[c], buf[c ^ 1], r0, r1, rule);
                sync.arrive_and_wait();  // every write to buf[c ^ 1] is done
            }
        };

        {
            std::vector<std::jthread> pool;
            pool.reserve(static_cast<std::size_t>(T_ - 1));
            for (int t = 1; t < T_; ++t) pool.emplace_back(work, t);
            work(0);  // the calling thread is worker 0
        }             // jthreads join here
        K::store(buf[cur], g);
    }

private:
    int T_;
    const char* sync_name_;
};

// ------------------------------------------------------------------- mutex
// The same algorithm with every shared variable behind one mutex, and the
// generation boundary built from that mutex and a condition variable. It
// keeps the static partition and makes one population update per thread
// per generation: this is what a careful mutex-first design looks like,
// so the comparison with BarrierEngine measures the primitive, not a
// strawman.
template <class K>
class MutexEngine final : public Engine {
public:
    explicit MutexEngine(int threads) : T_(threads < 1 ? 1 : threads) {}
    std::string name() const override { return std::string("mutex/") + K::kName; }
    int threads() const override { return T_; }

    void run(Grid& g, Rule rule, int gens, Trace* tr) override {
        if (tr) tr->prepare(g, gens);
        typename K::Buffer buf[2] = {K::load(g), {}};
        buf[1] = K::blank_like(buf[0]);
        const int R = K::rows(buf[0]);

        std::mutex m;
        std::condition_variable cv;
        // everything below is guarded by m
        int arrived = 0;
        uint64_t phase = 0;
        int cur = 0;
        int gen = 0;
        uint64_t pop_acc = 0;
        bool started = false;

        // Counting barrier: the last thread in does the between-generation
        // work, advances `phase`, and wakes everyone. Waiters re-check the
        // predicate, so spurious wakeups are harmless.
        auto barrier_locked = [&](std::unique_lock<std::mutex>& lk) {
            const uint64_t my_phase = phase;
            if (++arrived == T_) {
                arrived = 0;
                if (!started) {
                    started = true;
                    if (tr && tr->timestamps) tr->t_ns[0] = now_ns();
                } else {
                    cur ^= 1;
                    record<K>(tr, gen, pop_acc, buf[cur]);
                    pop_acc = 0;
                    ++gen;
                }
                ++phase;
                cv.notify_all();
            } else {
                cv.wait(lk, [&] { return phase != my_phase; });
            }
        };

        auto work = [&](int t) {
            prefer_performance_cores();
            const auto [r0, r1] = partition(R, T_, t);
            {
                std::unique_lock lk(m);
                barrier_locked(lk);  // start line
            }
            for (int k = 0; k < gens; ++k) {
                int c;
                {
                    std::lock_guard lk(m);
                    c = cur;
                }
                const uint64_t p = K::step(buf[c], buf[c ^ 1], r0, r1, rule);
                std::unique_lock lk(m);
                pop_acc += p;
                barrier_locked(lk);
            }
        };

        {
            std::vector<std::jthread> pool;
            pool.reserve(static_cast<std::size_t>(T_ - 1));
            for (int t = 1; t < T_; ++t) pool.emplace_back(work, t);
            work(0);
        }
        K::store(buf[cur], g);
    }

private:
    int T_;
};

// ----------------------------------------------------------------- factory

inline std::unique_ptr<Engine> make_engine(const std::string& sync, const std::string& kernel,
                                           int threads) {
    const bool bits = (kernel == "bitslice");
    if (!bits && kernel != "scalar") throw std::invalid_argument("kernel must be scalar or bitslice");
    if (sync == "serial") {
        if (bits) return std::make_unique<SerialEngine<BitsliceKernel>>();
        return std::make_unique<SerialEngine<ScalarKernel>>();
    }
    if (sync == "barrier") {
        if (bits) return std::make_unique<BarrierEngine<BitsliceKernel, StdBarrier>>(threads, "barrier");
        return std::make_unique<BarrierEngine<ScalarKernel, StdBarrier>>(threads, "barrier");
    }
    if (sync == "atomic") {
        if (bits) return std::make_unique<BarrierEngine<BitsliceKernel, AtomicBarrier>>(threads, "atomic");
        return std::make_unique<BarrierEngine<ScalarKernel, AtomicBarrier>>(threads, "atomic");
    }
    if (sync == "mutex") {
        if (bits) return std::make_unique<MutexEngine<BitsliceKernel>>(threads);
        return std::make_unique<MutexEngine<ScalarKernel>>(threads);
    }
    throw std::invalid_argument("sync must be serial, mutex, barrier or atomic");
}

}  // namespace cellnet
