// bench.cpp
//
// Laptop throughput and latency for every engine: the laptop half of the
// laptop-vs-FPGA comparison (tools/compare_fpga.py builds the other half
// from cycle-accurate RTL simulation).
//
// Throughput  generations per second, the median of --reps timed runs,
//             each at least --min-ms long. Cell updates per second is that
//             times the cell count.
// Latency     the time to produce one generation. Every generation
//             boundary is timestamped (inside the barrier completion step
//             for threaded engines) and the gaps form a distribution:
//             p50, p99, p99.9 and max. The steady_clock tick here is
//             measured at startup and written to the CSV; rows whose p50
//             is under ten ticks are marked resolution_limited, and for
//             those the mean from throughput is the number to trust.
// Gate        before timing anything, each engine's output is compared
//             with serial/scalar, which the test suite pins to
//             golden_rule.py. A mismatch aborts the run. A fast wrong
//             answer is worse than no answer.
//
//   build/bench --out results/laptop_bench.csv --machine results/machine.json
//               [--sizes 8,16,...] [--threads 1,2,...] [--reps 5]
//               [--min-ms 100] [--lat-samples 4000] [--lat-max-ms 800]

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#if defined(__APPLE__)
#include <sys/sysctl.h>
#endif

#include "cellnet/engines.hpp"

using namespace cellnet;

namespace {

std::vector<int> parse_ints(const std::string& s) {
    std::vector<int> v;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, ',')) v.push_back(std::atoi(item.c_str()));
    return v;
}

// smallest nonzero step of the clock, and the cost of reading it
struct ClockInfo {
    double tick_ns;
    double read_ns;
};

ClockInfo measure_clock() {
    double best = 1e18;
    for (int i = 0; i < 2000; ++i) {
        const int64_t a = now_ns();
        int64_t b = now_ns();
        while (b == a) b = now_ns();
        best = std::min(best, static_cast<double>(b - a));
    }
    const int N = 2'000'000;
    volatile int64_t sink = 0;
    const int64_t t0 = now_ns();
    for (int i = 0; i < N; ++i) sink = now_ns();
    (void)sink;
    return {best, static_cast<double>(now_ns() - t0) / N};
}

std::string sysctl_string(const char* name) {
#if defined(__APPLE__)
    char buf[256];
    size_t len = sizeof buf;
    if (sysctlbyname(name, buf, &len, nullptr, 0) == 0) return std::string(buf, strnlen(buf, len));
#else
    (void)name;
#endif
    return "";
}

int sysctl_int(const char* name) {
#if defined(__APPLE__)
    int v = 0;
    size_t len = sizeof v;
    if (sysctlbyname(name, &v, &len, nullptr, 0) == 0) return v;
#else
    (void)name;
#endif
    return 0;
}

std::string cpu_name() {
    std::string s = sysctl_string("machdep.cpu.brand_string");
    if (!s.empty()) return s;
    std::ifstream f("/proc/cpuinfo");
    std::string line;
    while (std::getline(f, line))
        if (line.rfind("model name", 0) == 0) return line.substr(line.find(':') + 2);
    return "unknown";
}

struct Result {
    std::string sync, kernel;
    int threads, rows, cols, gens_per_run, reps;
    double gps_median, gps_min, gps_max;
    std::size_t lat_n;
    double lat_mean, p50, p90, p99, p999, pmax;
    bool resolution_limited;
};

double run_gps(Engine& e, const Grid& start, Rule rule, int gens) {
    Grid g = start;
    const int64_t t0 = now_ns();
    e.run(g, rule, gens);
    const int64_t dt = now_ns() - t0;
    return dt > 0 ? gens * 1e9 / static_cast<double>(dt) : 0.0;
}

}  // namespace

int main(int argc, char** argv) {
    std::vector<int> sizes = {8, 16, 24, 32, 64, 128, 256, 512, 1024, 2048};
    std::vector<int> thread_counts = {1, 2, 4, 6, 8, 10};
    int reps = 5;
    double min_ms = 100;
    int lat_samples = 4000;
    double lat_max_ms = 800;
    std::string out_path = "results/laptop_bench.csv";
    std::string machine_path = "results/machine.json";

    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                std::fprintf(stderr, "%s needs a value\n", a.c_str());
                std::exit(2);
            }
            return argv[++i];
        };
        if (a == "--sizes") sizes = parse_ints(next());
        else if (a == "--threads") thread_counts = parse_ints(next());
        else if (a == "--reps") reps = std::atoi(next().c_str());
        else if (a == "--min-ms") min_ms = std::atof(next().c_str());
        else if (a == "--lat-samples") lat_samples = std::atoi(next().c_str());
        else if (a == "--lat-max-ms") lat_max_ms = std::atof(next().c_str());
        else if (a == "--out") out_path = next();
        else if (a == "--machine") machine_path = next();
        else {
            std::fprintf(stderr, "unknown option %s\n", a.c_str());
            return 2;
        }
    }

    prefer_performance_cores();
    const ClockInfo clk = measure_clock();
    const Rule rule = kRules[0].rule;  // Conway, the rule the fixed-rule FPGA build runs

    std::printf("steady_clock tick %.2f ns, read cost %.1f ns\n", clk.tick_ns, clk.read_ns);
    std::printf("%-17s %3s %6s %14s %14s %11s %11s %11s  %s\n", "engine", "T", "grid", "gen/s", "cell upd/s",
                "lat p50", "lat p99", "lat p99.9", "note");

    std::vector<Result> results;
    auto reference = make_engine("serial", "scalar", 1);

    for (int side : sizes) {
        const Grid start = random_grid(side, side, 0.35, 0xB0A7 + static_cast<uint64_t>(side));
        Grid want = start;
        reference->run(want, rule, 8);

        struct Family {
            const char* sync;
            const char* kernel;
        };
        const Family families[] = {{"serial", "scalar"},  {"serial", "bitslice"}, {"mutex", "scalar"},
                                   {"mutex", "bitslice"},  {"barrier", "scalar"}, {"barrier", "bitslice"},
                                   {"atomic", "scalar"},   {"atomic", "bitslice"}};

        for (const Family& f : families) {
            const bool serial = std::string(f.sync) == "serial";
            for (int T : thread_counts) {
                if (serial && T != 1) continue;
                if (T > side) continue;  // more threads than rows only adds idle barrier members
                auto engine = make_engine(f.sync, f.kernel, T);

                // gate: no timing for an engine that gets the wrong answer
                Grid check = start;
                engine->run(check, rule, 8);
                if (!(check == want)) {
                    std::fprintf(stderr, "GATE FAILED: %s T=%d %dx%d disagrees with serial/scalar\n",
                                 engine->name().c_str(), T, side, side);
                    return 3;
                }

                // calibrate generations per run to reach min_ms
                int gens = 64;
                for (;;) {
                    const double gps = run_gps(*engine, start, rule, gens);
                    const double ms = gens / gps * 1e3;
                    if (ms >= min_ms * 0.5 || gens >= 50'000'000) {
                        gens = static_cast<int>(std::clamp(gens * (min_ms / std::max(ms, 1e-3)), 16.0, 5e7));
                        break;
                    }
                    gens *= 8;
                }

                std::vector<double> gps;
                for (int r = 0; r < reps; ++r) gps.push_back(run_gps(*engine, start, rule, gens));
                std::sort(gps.begin(), gps.end());

                // latency: one timestamped run, capped by samples and wall time
                const double per_gen_ms = 1e3 / gps[gps.size() / 2];
                const int lat_gens =
                    std::max(20, std::min(lat_samples, static_cast<int>(lat_max_ms / std::max(per_gen_ms, 1e-6))));
                Trace tr;
                tr.timestamps = true;
                Grid lg = start;
                engine->run(lg, rule, lat_gens, &tr);
                std::vector<double> gaps;
                const int warm = lat_gens / 20;  // first 5% absorbs thread start-up
                for (int k = warm; k < lat_gens; ++k)
                    gaps.push_back(static_cast<double>(tr.t_ns[static_cast<std::size_t>(k) + 1] -
                                                       tr.t_ns[static_cast<std::size_t>(k)]));
                std::sort(gaps.begin(), gaps.end());
                auto pct = [&](double p) {
                    return gaps[static_cast<std::size_t>(p / 100.0 * static_cast<double>(gaps.size() - 1) + 0.5)];
                };
                double mean = 0;
                for (double gv : gaps) mean += gv;
                mean /= static_cast<double>(gaps.size());

                Result res{f.sync, f.kernel, T, side, side, gens, reps,
                           gps[gps.size() / 2], gps.front(), gps.back(),
                           gaps.size(), mean, pct(50), pct(90), pct(99), pct(99.9), gaps.back(),
                           pct(50) < 10 * clk.tick_ns};
                results.push_back(res);

                char note[64] = "";
                if (res.resolution_limited) std::snprintf(note, sizeof note, "timer-limited");
                std::printf("%-17s %3d %4dx%-4d %11.4g %14.4g %9.0fns %9.0fns %9.0fns  %s\n",
                            engine->name().c_str(), T, side, side, res.gps_median,
                            res.gps_median * side * side, res.p50, res.p99, res.p999, note);
                std::fflush(stdout);
            }
        }
    }

    std::ofstream csv(out_path);
    csv << "engine,sync,kernel,threads,rows,cols,cells,gens_per_run,reps,gens_per_s_median,gens_per_s_min,"
           "gens_per_s_max,cell_updates_per_s,lat_samples,lat_mean_ns,lat_p50_ns,lat_p90_ns,lat_p99_ns,"
           "lat_p999_ns,lat_max_ns,timer_tick_ns,resolution_limited\n";
    for (const Result& r : results) {
        csv << r.sync << '/' << r.kernel << ',' << r.sync << ',' << r.kernel << ',' << r.threads << ',' << r.rows
            << ',' << r.cols << ',' << r.rows * r.cols << ',' << r.gens_per_run << ',' << r.reps << ','
            << r.gps_median << ',' << r.gps_min << ',' << r.gps_max << ',' << r.gps_median * r.rows * r.cols << ','
            << r.lat_n << ',' << r.lat_mean << ',' << r.p50 << ',' << r.p90 << ',' << r.p99 << ',' << r.p999 << ','
            << r.pmax << ',' << clk.tick_ns << ',' << (r.resolution_limited ? 1 : 0) << '\n';
    }

    char date[32];
    const std::time_t now = std::time(nullptr);
    std::strftime(date, sizeof date, "%Y-%m-%d", std::localtime(&now));
    std::ofstream mj(machine_path);
    mj << "{\n"
       << "  \"cpu\": \"" << cpu_name() << "\",\n"
       << "  \"logical_cores\": " << std::thread::hardware_concurrency() << ",\n"
       << "  \"performance_cores\": " << sysctl_int("hw.perflevel0.physicalcpu") << ",\n"
       << "  \"efficiency_cores\": " << sysctl_int("hw.perflevel1.physicalcpu") << ",\n"
       << "  \"cache_line_bytes\": " << sysctl_int("hw.cachelinesize") << ",\n"
       << "  \"compiler\": \"" << __VERSION__ << "\",\n"
       << "  \"flags\": \"-std=c++20 -O3 -mcpu=native\",\n"
       << "  \"rule\": \"conway B3/S23\",\n"
       << "  \"timer_tick_ns\": " << clk.tick_ns << ",\n"
       << "  \"timer_read_ns\": " << clk.read_ns << ",\n"
       << "  \"date\": \"" << date << "\"\n"
       << "}\n";

    std::printf("\nwrote %s (%zu rows) and %s\n", out_path.c_str(), results.size(), machine_path.c_str());
    return 0;
}
