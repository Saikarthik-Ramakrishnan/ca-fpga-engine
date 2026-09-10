// test_correctness.cpp
//
// Every C++ engine, checked against vectors that golden_rule.py wrote
// (tools/gen_vectors.py). Five layers, in the order the RTL was verified:
//
//   1  cell     cell_next vs golden update_masked, 5 rules x 18 inputs.
//               count8 over all 256 neighbor patterns (vs popcount).
//               apply_rule over every one of the 2^18 rule masks x 18 inputs,
//               differential against cell_next, which the first check pinned.
//   2  step     both kernels on all 65,536 4x4 tori x 5 rules, with the rows
//               cut into every contiguous partition (8 of them) and the blocks
//               computed forward and in reverse. A thread in a real run is
//               exactly "compute my block"; this proves any partition, in
//               any order, gives the golden answer.
//   3  engines  every engine x thread counts {1,2,3,4,7,8,16} on every golden
//               trajectory. Every generation and every population compared,
//               so a divergence is pinned to the generation it appears in.
//   4  stress   threaded engines vs serial/scalar (pinned to golden by layer 3)
//               over randomized sizes, rules, thread counts and repetitions.
//   5  shapes   rectangular grids. Differential only, since golden_rule.py is
//               square-only, and labelled that way in the report.
//
// Under ThreadSanitizer the std::barrier family is left out of the gated
// run by default: libc++ keeps std::barrier's arrival logic in an
// uninstrumented dylib, so TSan reports a race it cannot rule out (see
// engines.hpp, AtomicBarrier). --include-stdbarrier puts it back to show
// that report. The atomic and mutex families are checked in full.
//
//   build/test_correctness --vectors build/vectors [--stress N]
//                          [--skip-exhaustive] [--include-stdbarrier]

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include "cellnet/engines.hpp"

using namespace cellnet;

namespace {

// ------------------------------------------------------------- reporting

struct Tally {
    std::string layer;
    std::string what;
    std::string against;
    uint64_t pass = 0;
    uint64_t fail = 0;
};

std::vector<Tally> g_tallies;
int g_printed_failures = 0;
bool g_skip_stdbarrier = false;  // set under TSan unless --include-stdbarrier

Tally& tally(const std::string& layer, const std::string& what, const std::string& against) {
    g_tallies.push_back({layer, what, against, 0, 0});
    return g_tallies.back();
}

void report_failure(Tally& t, const char* fmt, ...) {
    ++t.fail;
    if (g_printed_failures >= 25) return;
    ++g_printed_failures;
    std::fprintf(stderr, "  FAIL [layer %s] ", t.layer.c_str());
    va_list ap;
    va_start(ap, fmt);
    std::vfprintf(stderr, fmt, ap);
    va_end(ap);
    std::fputc('\n', stderr);
}

// ---------------------------------------------------------------- vectors

std::vector<uint8_t> read_all(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        std::fprintf(stderr, "cannot open %s. Run: make vectors\n", path.c_str());
        std::exit(2);
    }
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}

struct Reader {
    const std::vector<uint8_t>& d;
    std::size_t p = 0;
    uint16_t u16() {
        const uint16_t v = static_cast<uint16_t>(d.at(p) | (d.at(p + 1) << 8));
        p += 2;
        return v;
    }
    uint32_t u32() {
        const uint32_t v = static_cast<uint32_t>(u16());
        return v | (static_cast<uint32_t>(u16()) << 16);
    }
    const uint8_t* bytes(std::size_t n) {
        if (p + n > d.size()) {
            std::fprintf(stderr, "vector file truncated\n");
            std::exit(2);
        }
        const uint8_t* b = d.data() + p;
        p += n;
        return b;
    }
};

// UART packing: cell i = r*cols + c in bit i % 8 of byte i / 8.
Grid unpack(const uint8_t* bytes, int rows, int cols) {
    Grid g(rows, cols);
    for (int i = 0; i < rows * cols; ++i) g.cells[static_cast<std::size_t>(i)] = (bytes[i / 8] >> (i % 8)) & 1u;
    return g;
}

Grid grid4(uint32_t state) {
    Grid g(4, 4);
    for (int i = 0; i < 16; ++i) g.cells[static_cast<std::size_t>(i)] = (state >> i) & 1u;
    return g;
}

// ------------------------------------------------------- layer 1: cell

void layer_cell(const std::string& dir) {
    auto data = read_all(dir + "/cell.bin");
    Reader rd{data};

    Tally& t1 = tally("1", "cell_next, 5 rules x 18 inputs", "golden update_masked");
    for (int ri = 0; ri < kNumRules; ++ri) {
        const Rule rule{rd.u16(), rd.u16()};
        if (!(rule == kRules[ri].rule))
            report_failure(t1, "rule bank drift: C++ %s has masks %03x/%03x, golden_rule.py %03x/%03x",
                           kRules[ri].name, kRules[ri].rule.birth, kRules[ri].rule.survive,
                           rule.birth, rule.survive);
        const uint8_t* expect = rd.bytes(18);
        for (int alive = 0; alive < 2; ++alive)
            for (int count = 0; count <= 8; ++count) {
                const uint8_t got = cell_next(static_cast<uint8_t>(alive), count, rule);
                if (got == expect[alive * 9 + count]) ++t1.pass;
                else report_failure(t1, "%s alive=%d count=%d: got %d", kRules[ri].name, alive, count, got);
            }
    }

    // count8: 256 neighbor patterns on 256 lanes (4 words of 64). Lane L's
    // eight neighbor bits are the bits of L, so every pattern appears once.
    Tally& t2 = tally("1", "count8 adder tree, all 256 patterns", "popcount (exhaustive)");
    for (int w = 0; w < 4; ++w) {
        uint64_t n[8] = {};
        for (int j = 0; j < 64; ++j) {
            const int lane = 64 * w + j;
            for (int i = 0; i < 8; ++i)
                if ((lane >> i) & 1) n[i] |= 1ull << j;
        }
        const CountPlanes p = count8(n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7]);
        for (int j = 0; j < 64; ++j) {
            const int lane = 64 * w + j;
            const int got = static_cast<int>(((p.b0 >> j) & 1) | (((p.b1 >> j) & 1) << 1) |
                                             (((p.b2 >> j) & 1) << 2) | (((p.b3 >> j) & 1) << 3));
            if (got == std::popcount(static_cast<unsigned>(lane))) ++t2.pass;
            else report_failure(t2, "pattern %02x: count8 gave %d", lane, got);
        }
    }

    // apply_rule over the whole rule space. 18 lanes hold every (alive,
    // count) pair; every one of the 262,144 rule masks is applied to them.
    Tally& t3 = tally("1", "apply_rule, all 2^18 rules x 18 inputs", "cell_next (exhaustive)");
    uint64_t alive_plane = 0;
    CountPlanes cp{0, 0, 0, 0};
    for (int alive = 0; alive < 2; ++alive)
        for (int count = 0; count <= 8; ++count) {
            const int lane = alive * 9 + count;
            if (alive) alive_plane |= 1ull << lane;
            if (count & 1) cp.b0 |= 1ull << lane;
            if (count & 2) cp.b1 |= 1ull << lane;
            if (count & 4) cp.b2 |= 1ull << lane;
            if (count & 8) cp.b3 |= 1ull << lane;
        }
    for (uint32_t birth = 0; birth < 512; ++birth)
        for (uint32_t survive = 0; survive < 512; ++survive) {
            const Rule rule{static_cast<uint16_t>(birth), static_cast<uint16_t>(survive)};
            const uint64_t out = apply_rule(alive_plane, cp, rule);
            uint64_t expect = 0;
            for (int alive = 0; alive < 2; ++alive)
                for (int count = 0; count <= 8; ++count)
                    if (cell_next(static_cast<uint8_t>(alive), count, rule)) expect |= 1ull << (alive * 9 + count);
            if ((out & 0x3FFFFull) == expect) t3.pass += 18;
            else report_failure(t3, "rule B=%03x S=%03x: lanes %05llx, want %05llx", birth, survive,
                                static_cast<unsigned long long>(out & 0x3FFFFull),
                                static_cast<unsigned long long>(expect));
        }
}

// ------------------------------------------------------- layer 2: step

template <class K>
void exhaustive4_kernel(const std::vector<uint8_t>& data, Tally& t) {
    Reader rd{data};
    Grid snap(4, 4);
    for (int ri = 0; ri < kNumRules; ++ri) {
        const Rule rule{rd.u16(), rd.u16()};
        const uint8_t* expect = rd.bytes(2u * 65536u);
        for (uint32_t state = 0; state < 65536; ++state) {
            const uint32_t want = static_cast<uint32_t>(expect[2 * state] | (expect[2 * state + 1] << 8));
            const uint64_t want_pop = static_cast<uint64_t>(std::popcount(want));
            const typename K::Buffer in = K::load(grid4(state));
            typename K::Buffer out = K::blank_like(in);

            // cut bit i set: a block boundary after row i + 1. Eight cuts give
            // every contiguous partition of four rows, from one block of four
            // to four blocks of one.
            for (int cuts = 0; cuts < 8; ++cuts) {
                int bounds[5];
                int nb = 0;
                bounds[nb++] = 0;
                for (int i = 0; i < 3; ++i)
                    if ((cuts >> i) & 1) bounds[nb++] = i + 1;
                bounds[nb++] = 4;
                const int blocks = nb - 1;

                for (int order = 0; order < 2; ++order) {
                    uint64_t pop = 0;
                    for (int b = 0; b < blocks; ++b) {
                        const int blk = (order == 0) ? b : blocks - 1 - b;
                        pop += K::step(in, out, bounds[blk], bounds[blk + 1], rule);
                    }
                    K::snapshot(out, snap);
                    uint32_t got = 0;
                    for (int i = 0; i < 16; ++i) got |= static_cast<uint32_t>(snap.cells[static_cast<std::size_t>(i)]) << i;
                    if (got == want && pop == want_pop) ++t.pass;
                    else report_failure(t, "%s %s state %04x cuts %d %s: got %04x pop %llu, want %04x pop %llu",
                                        K::kName, kRules[ri].name, state, cuts, order ? "reverse" : "forward",
                                        got, static_cast<unsigned long long>(pop), want,
                                        static_cast<unsigned long long>(want_pop));
                }
            }
        }
    }
}

void layer_step(const std::string& dir) {
    auto data = read_all(dir + "/exhaustive4.bin");
    Tally& ts = tally("2", "scalar kernel, 4x4 x 65,536 x 5 rules x 8 partitions x 2 orders",
                      "golden step_golden_masked (exhaustive)");
    exhaustive4_kernel<ScalarKernel>(data, ts);
    Tally& tb = tally("2", "bitslice kernel, same space", "golden step_golden_masked (exhaustive)");
    exhaustive4_kernel<BitsliceKernel>(data, tb);
}

// ---------------------------------------------------- layer 3: engines

struct Config {
    std::string sync, kernel;
    int threads;
};

std::vector<Config> engine_configs() {
    std::vector<Config> v;
    for (const char* k : {"scalar", "bitslice"}) {
        v.push_back({"serial", k, 1});
        for (const char* s : {"mutex", "barrier", "atomic"}) {
            if (g_skip_stdbarrier && std::string(s) == "barrier") continue;
            for (int T : {1, 2, 3, 4, 7, 8, 16}) v.push_back({s, k, T});
        }
    }
    return v;
}

const char* threaded_families() {
    return g_skip_stdbarrier ? "mutex, atomic" : "mutex, barrier, atomic";
}

struct Case {
    int side, gens;
    Rule rule;
    uint32_t seed;
    int density_milli;
    Grid initial;
    std::vector<Grid> expect;
};

std::vector<Case> load_trajectories(const std::string& dir) {
    auto data = read_all(dir + "/trajectories.bin");
    Reader rd{data};
    const uint32_t n = rd.u32();
    std::vector<Case> cases;
    cases.reserve(n);
    for (uint32_t i = 0; i < n; ++i) {
        Case c;
        c.side = rd.u16();
        c.rule.birth = rd.u16();
        c.rule.survive = rd.u16();
        c.gens = rd.u16();
        c.seed = rd.u32();
        c.density_milli = rd.u16();
        const std::size_t nbytes = (static_cast<std::size_t>(c.side) * c.side + 7) / 8;
        c.initial = unpack(rd.bytes(nbytes), c.side, c.side);
        for (int k = 0; k < c.gens; ++k) c.expect.push_back(unpack(rd.bytes(nbytes), c.side, c.side));
        cases.push_back(std::move(c));
    }
    return cases;
}

const char* rule_name(Rule r) {
    for (const auto& nr : kRules)
        if (nr.rule == r) return nr.name;
    return "custom";
}

void layer_engines(const std::string& dir, uint64_t& gens_compared) {
    const auto cases = load_trajectories(dir);
    const auto configs = engine_configs();
    Tally& t = tally("3", std::string("serial + {") + threaded_families() +
                              "} x T in {1,2,3,4,7,8,16}, every trajectory, every generation",
                     "golden step_golden_masked");
    for (const Config& cfg : configs) {
        auto engine = make_engine(cfg.sync, cfg.kernel, cfg.threads);
        for (const Case& c : cases) {
            Grid g = c.initial;
            Trace tr;
            tr.keep_grids = true;
            engine->run(g, c.rule, c.gens, &tr);
            int first_bad = -1;
            for (int k = 0; k < c.gens; ++k) {
                ++gens_compared;
                const bool ok = tr.grids[static_cast<std::size_t>(k)] == c.expect[static_cast<std::size_t>(k)] &&
                                tr.population[static_cast<std::size_t>(k)] == c.expect[static_cast<std::size_t>(k)].population();
                if (!ok && first_bad < 0) first_bad = k + 1;
            }
            const bool final_ok = (g == c.expect.back());
            if (first_bad < 0 && final_ok) ++t.pass;
            else report_failure(t, "%s T=%d on %dx%d %s seed=%u d=0.%03d: first divergence at generation %d",
                                engine->name().c_str(), cfg.threads, c.side, c.side, rule_name(c.rule),
                                c.seed, c.density_milli, first_bad < 0 ? c.gens : first_bad);
        }
    }
}

// ----------------------------------------------------- layer 4: stress

void layer_stress(int reps, uint64_t seed) {
    Tally& t = tally("4", std::string("{") + threaded_families() + "}, randomized size/rule/T/gens, " +
                              std::to_string(reps) + " runs",
                     "serial/scalar (pinned to golden by layer 3)");
    const int sides[] = {17, 32, 48, 64, 128, 256};
    uint64_t s = seed;
    auto reference = make_engine("serial", "scalar", 1);
    for (int i = 0; i < reps; ++i) {
        const int side = sides[splitmix64(s) % 6];
        const Rule rule = kRules[splitmix64(s) % kNumRules].rule;
        const int T = 1 + static_cast<int>(splitmix64(s) % 24);
        const char* families[] = {"mutex", "barrier", "atomic"};
        const char* sync = families[splitmix64(s) % 3];
        if (g_skip_stdbarrier && std::string(sync) == "barrier") sync = "atomic";
        const char* kern = (splitmix64(s) & 1) ? "bitslice" : "scalar";
        const int gens = 50 + static_cast<int>(splitmix64(s) % 151);
        const double density = 0.1 + 0.6 * static_cast<double>(splitmix64(s) % 1000) / 1000.0;
        const Grid start = random_grid(side, side, density, splitmix64(s));

        Grid want = start;
        Trace want_tr;
        reference->run(want, rule, gens, &want_tr);

        Grid got = start;
        Trace got_tr;
        make_engine(sync, kern, T)->run(got, rule, gens, &got_tr);

        if (got == want && got_tr.population == want_tr.population) ++t.pass;
        else report_failure(t, "%s/%s T=%d %dx%d %s gens=%d: final state or population trajectory differs",
                            sync, kern, T, side, side, rule_name(rule), gens);
    }
}

// ----------------------------------------------------- layer 5: shapes

void layer_shapes() {
    Tally& t = tally("5", "rectangular grids, every engine config, 5 rules",
                     "serial/scalar (differential; golden is square-only)");
    const int shapes[][2] = {{5, 64}, {64, 5}, {3, 128}, {130, 64}, {17, 33}, {1, 40}, {40, 1}, {9, 192}};
    auto reference = make_engine("serial", "scalar", 1);
    uint64_t s = 0xC0FFEE;
    for (const auto& sh : shapes)
        for (int ri = 0; ri < kNumRules; ++ri) {
            const Grid start = random_grid(sh[0], sh[1], 0.35, splitmix64(s));
            Grid want = start;
            Trace want_tr;
            reference->run(want, kRules[ri].rule, 30, &want_tr);
            for (const Config& cfg : engine_configs()) {
                Grid got = start;
                Trace got_tr;
                make_engine(cfg.sync, cfg.kernel, cfg.threads)->run(got, kRules[ri].rule, 30, &got_tr);
                if (got == want && got_tr.population == want_tr.population) ++t.pass;
                else report_failure(t, "%s/%s T=%d on %dx%d %s", cfg.sync.c_str(), cfg.kernel.c_str(),
                                    cfg.threads, sh[0], sh[1], kRules[ri].name);
            }
        }
}

}  // namespace

int main(int argc, char** argv) {
    std::string dir = "build/vectors";
    int stress = 300;
    bool skip_exhaustive = false;
    bool include_std = false;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--vectors" && i + 1 < argc) dir = argv[++i];
        else if (a == "--stress" && i + 1 < argc) stress = std::atoi(argv[++i]);
        else if (a == "--skip-exhaustive") skip_exhaustive = true;
        else if (a == "--include-stdbarrier") include_std = true;
        else {
            std::fprintf(stderr, "usage: %s [--vectors DIR] [--stress N] [--skip-exhaustive] [--include-stdbarrier]\n",
                         argv[0]);
            return 2;
        }
    }
    g_skip_stdbarrier = CELLNET_TSAN && !include_std;
    if (g_skip_stdbarrier)
        std::printf("ThreadSanitizer build: std::barrier family excluded (uninstrumented libc++.dylib);\n"
                    "run with --include-stdbarrier to see the report it produces.\n");

    const int64_t t0 = now_ns();
    uint64_t gens_compared = 0;
    layer_cell(dir);
    if (!skip_exhaustive) layer_step(dir);
    layer_engines(dir, gens_compared);
    layer_stress(stress, 0x5EED5EEDull);
    layer_shapes();
    const double secs = static_cast<double>(now_ns() - t0) / 1e9;

    uint64_t pass = 0, fail = 0;
    std::printf("\n%-5s %-78s %12s %6s  %s\n", "layer", "check", "passed", "failed", "against");
    for (const Tally& t : g_tallies) {
        std::printf("%-5s %-78s %12llu %6llu  %s\n", t.layer.c_str(), t.what.c_str(),
                    static_cast<unsigned long long>(t.pass), static_cast<unsigned long long>(t.fail),
                    t.against.c_str());
        pass += t.pass;
        fail += t.fail;
    }
    std::printf("\nlayer 3 compared %llu generations, grid and population each.\n",
                static_cast<unsigned long long>(gens_compared));
    if (skip_exhaustive) std::printf("layer 2 skipped (--skip-exhaustive).\n");
    std::printf("%llu checks passed, %llu failed, %.1f s\n", static_cast<unsigned long long>(pass),
                static_cast<unsigned long long>(fail), secs);
    std::printf("RESULT: %s\n", fail ? "FAILED" : "all green");
    return fail ? 1 : 0;
}
