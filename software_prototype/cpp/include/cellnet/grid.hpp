// grid.hpp
//
// The two things every part of the C++ port agrees on: a rule and a grid.
//
// Rule. Two 9-bit masks over the live-neighbor count. Bit k of `birth` set
// means a dead cell with k live neighbors becomes alive; bit k of `survive`
// set means a live cell with k live neighbors stays alive. These are the
// 18 bits golden_rule.py calls birth_mask and survive_mask, the 18 bits
// ca_cell_rule.v indexes, and the 18 bits the 0x33 packet carries.
//
// Grid. One byte per cell, cell (r, c) at index r*cols + c. That is the
// flattening ca_grid.v uses for its bit vector, so a grid here, a frame
// off the UART and a seed going in all name cells the same way.
//
// Nothing in this file is shared between threads. Concurrency lives in
// engines.hpp, and the rules it follows are written down there.

#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace cellnet {

struct Rule {
    uint16_t birth = 0;
    uint16_t survive = 0;
    friend bool operator==(Rule, Rule) = default;
};

struct NamedRule {
    const char* name;
    const char* notation;
    Rule rule;
};

// Same order and same masks as golden_rule.RULES and the console.
inline constexpr NamedRule kRules[] = {
    {"conway",   "B3/S23",       {0b000001000, 0b000001100}},
    {"highlife", "B36/S23",      {0b001001000, 0b000001100}},
    {"daynight", "B3678/S34678", {0b111001000, 0b111011000}},
    {"seeds",    "B2/S",         {0b000000100, 0b000000000}},
    {"maze",     "B3/S12345",    {0b000001000, 0b000111110}},
};
inline constexpr int kNumRules = sizeof(kRules) / sizeof(kRules[0]);

// One cell's next state, written the way golden_rule.update_masked writes
// it: pick the mask with the cell's own state, index it with the count.
// `count` is 0..8 because a cell has eight neighbors, so the shift never
// leaves the 9-bit mask.
inline constexpr uint8_t cell_next(uint8_t alive, int count, Rule rule) {
    const uint16_t mask = alive ? rule.survive : rule.birth;
    return static_cast<uint8_t>((mask >> count) & 1u);
}

struct Grid {
    int rows = 0;
    int cols = 0;
    std::vector<uint8_t> cells;

    Grid() = default;
    Grid(int r, int c) : rows(r), cols(c), cells(static_cast<std::size_t>(r) * c, 0) {}

    uint8_t& at(int r, int c) { return cells[static_cast<std::size_t>(r) * cols + c]; }
    uint8_t at(int r, int c) const { return cells[static_cast<std::size_t>(r) * cols + c]; }

    uint64_t population() const {
        uint64_t n = 0;
        for (uint8_t v : cells) n += v;
        return n;
    }

    friend bool operator==(const Grid&, const Grid&) = default;
};

// Deterministic soup for benchmarks and stress runs. splitmix64, so one
// seed gives one grid on every compiler and platform. The test vectors do
// not use this: their initial grids come from golden_rule.seed_grid.
inline uint64_t splitmix64(uint64_t& s) {
    uint64_t z = (s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

inline Grid random_grid(int rows, int cols, double density, uint64_t seed) {
    Grid g(rows, cols);
    uint64_t s = seed;
    for (auto& v : g.cells) {
        const double u = static_cast<double>(splitmix64(s) >> 11) * 0x1.0p-53;  // [0, 1)
        v = u < density ? 1 : 0;
    }
    return g;
}

}  // namespace cellnet
