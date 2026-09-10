// kernels.hpp
//
// Two ways to compute rows [r0, r1) of the next generation from the
// current one. Both honor one contract, and the concurrency argument in
// docs/CONCURRENCY.md rests on it:
//
//   reads    any cell of `in`, the current generation. Nobody writes `in`
//            while a generation is being computed.
//   writes   rows [r0, r1) of `out`, and nothing else.
//   returns  how many live cells it wrote, this call's share of the
//            population.
//
// So a thread handed rows [r0, r1) writes memory no other thread writes,
// and reads memory no thread writes. Inside a generation there is nothing
// for a lock to protect. The only synchronization left is the boundary
// between generations, which engines.hpp handles.
//
// ScalarKernel is the rule as golden_rule.py writes it, one byte per cell.
// BitsliceKernel is the same rule on 64 cells per machine word: eight
// neighbor planes go through a bitwise adder tree to a 4-bit count, then
// the count indexes the rule masks. That is ca_cell.v's structure
// (popcount, then lookup) with every wire widened from 1 bit to 64.

#pragma once

#include <algorithm>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "cellnet/grid.hpp"

namespace cellnet {

// ------------------------------------------------------------------ scalar

struct ScalarKernel {
    using Buffer = Grid;
    static constexpr const char* kName = "scalar";

    static Buffer load(const Grid& g) { return g; }
    static Buffer blank_like(const Buffer& b) { return Grid(b.rows, b.cols); }
    static int rows(const Buffer& b) { return b.rows; }
    static void store(const Buffer& b, Grid& g) { g = b; }

    // Copies into a grid of the same shape that already exists. No
    // allocation, so it is safe inside a barrier's noexcept completion step.
    static void snapshot(const Buffer& b, Grid& dst) noexcept {
        std::copy(b.cells.begin(), b.cells.end(), dst.cells.begin());
    }

    static uint64_t step(const Buffer& in, Buffer& out, int r0, int r1, Rule rule) {
        const int R = in.rows;
        const int C = in.cols;
        const uint8_t* src = in.cells.data();
        uint8_t* dst = out.cells.data();
        uint64_t pop = 0;
        for (int r = r0; r < r1; ++r) {
            // toroidal wrap, the same modulo golden_rule.neighbor_count uses
            const uint8_t* up = src + static_cast<std::size_t>(r == 0 ? R - 1 : r - 1) * C;
            const uint8_t* here = src + static_cast<std::size_t>(r) * C;
            const uint8_t* down = src + static_cast<std::size_t>(r == R - 1 ? 0 : r + 1) * C;
            uint8_t* o = dst + static_cast<std::size_t>(r) * C;
            for (int c = 0; c < C; ++c) {
                const int w = (c == 0) ? C - 1 : c - 1;
                const int e = (c == C - 1) ? 0 : c + 1;
                const int count = up[w] + up[c] + up[e] + here[w] + here[e] +
                                  down[w] + down[c] + down[e];
                const uint8_t v = cell_next(here[c], count, rule);
                o[c] = v;
                pop += v;
            }
        }
        return pop;
    }
};

// ---------------------------------------------------------------- bitslice

// Bit j of word w of row r is cell (r, 64*w + j). Rows are whole words, and
// that matters for concurrency: the C++ memory model's unit of conflict is
// the memory location, here one uint64_t. Two threads writing different
// bits of the same word would be a data race (the std::vector<bool> trap).
// Threads own whole rows, so no word is ever written by two threads.
struct BitGrid {
    int rows = 0;
    int cols = 0;
    int wpr = 0;  // words per row
    std::vector<uint64_t> w;
};

// Widths up to 64 use one word per row and wrap with a masked rotate;
// multiples of 64 carry the wrap across words. Every FPGA build size
// (8, 16, 24, 32) and every benchmark size is one or the other.
inline bool bitslice_supports(int cols) {
    return cols >= 1 && (cols <= 64 || cols % 64 == 0);
}

// A 4-bit count, bit-sliced: bit j of b0..b3 is lane j's count.
struct CountPlanes {
    uint64_t b0, b1, b2, b3;
};

// Eight neighbor planes in, one bit-sliced count out, for 64 cells at once.
// A carry-save tree of full and half adders: the popcount ca_cell.v
// synthesizes, with each wire a machine word.
inline constexpr CountPlanes count8(uint64_t n0, uint64_t n1, uint64_t n2, uint64_t n3,
                                    uint64_t n4, uint64_t n5, uint64_t n6, uint64_t n7) {
    // full adder: sum = a ^ b ^ c, carry = majority(a, b, c)
    // weight-1 column, first rank: 3 + 3 + 2 inputs
    const uint64_t ta = n0 ^ n1, sa = ta ^ n2, ca = (n0 & n1) | (ta & n2);
    const uint64_t tb = n3 ^ n4, sb = tb ^ n5, cb = (n3 & n4) | (tb & n5);
    const uint64_t sc = n6 ^ n7, cc = n6 & n7;
    // weight-1 column, second rank: the final low bit
    const uint64_t td = sa ^ sb, b0 = td ^ sc, cd = (sa & sb) | (td & sc);
    // weight-2 column: ca, cb, cc from rank one, cd from rank two
    const uint64_t te = ca ^ cb, se = te ^ cc, ce = (ca & cb) | (te & cc);
    const uint64_t b1 = se ^ cd, cf = se & cd;
    // weight-4 column: ce and cf. Their carry is the weight-8 bit, which is
    // set only when all eight neighbors are alive.
    const uint64_t b2 = ce ^ cf, b3 = ce & cf;
    return {b0, b1, b2, b3};
}

// The rule on bit-sliced counts, the 64-lane twin of cell_next. For each
// count k the rule mentions, select the lanes whose count equals k and
// route them to `born` or `kept` by the mask bits.
inline constexpr uint64_t apply_rule(uint64_t alive, CountPlanes p, Rule rule) {
    uint64_t born = 0, kept = 0;
    for (int k = 0; k <= 8; ++k) {
        const bool b = (rule.birth >> k) & 1u;
        const bool s = (rule.survive >> k) & 1u;
        if (!b && !s) continue;
        const uint64_t eq = ((k & 1) ? p.b0 : ~p.b0) & ((k & 2) ? p.b1 : ~p.b1) &
                            ((k & 4) ? p.b2 : ~p.b2) & ((k & 8) ? p.b3 : ~p.b3);
        if (b) born |= eq;
        if (s) kept |= eq;
    }
    return (alive & kept) | (~alive & born);
}

struct BitsliceKernel {
    using Buffer = BitGrid;
    static constexpr const char* kName = "bitslice";

    static Buffer load(const Grid& g) {
        if (!bitslice_supports(g.cols))
            throw std::invalid_argument("bitslice kernel needs cols <= 64 or a multiple of 64, got " +
                                        std::to_string(g.cols));
        BitGrid b;
        b.rows = g.rows;
        b.cols = g.cols;
        b.wpr = (g.cols + 63) / 64;
        b.w.assign(static_cast<std::size_t>(b.rows) * b.wpr, 0);
        for (int r = 0; r < g.rows; ++r)
            for (int c = 0; c < g.cols; ++c)
                if (g.at(r, c)) b.w[static_cast<std::size_t>(r) * b.wpr + c / 64] |= 1ull << (c % 64);
        return b;
    }

    static Buffer blank_like(const Buffer& b) {
        BitGrid o;
        o.rows = b.rows;
        o.cols = b.cols;
        o.wpr = b.wpr;
        o.w.assign(b.w.size(), 0);
        return o;
    }

    static int rows(const Buffer& b) { return b.rows; }

    static void snapshot(const Buffer& b, Grid& dst) noexcept {
        for (int r = 0; r < b.rows; ++r)
            for (int c = 0; c < b.cols; ++c)
                dst.at(r, c) = static_cast<uint8_t>(
                    (b.w[static_cast<std::size_t>(r) * b.wpr + c / 64] >> (c % 64)) & 1u);
    }

    static void store(const Buffer& b, Grid& g) {
        g = Grid(b.rows, b.cols);
        snapshot(b, g);
    }

    static uint64_t step(const Buffer& in, Buffer& out, int r0, int r1, Rule rule) {
        const int R = in.rows;
        const uint64_t* src = in.w.data();
        uint64_t* dst = out.w.data();
        uint64_t pop = 0;

        if (in.cols < 64) {
            // one word per row: rotate within `cols` bits for the wrap
            const int C = in.cols;
            const uint64_t mask = (1ull << C) - 1;
            const auto west = [C, mask](uint64_t x) { return ((x << 1) | (x >> (C - 1))) & mask; };
            const auto east = [C, mask](uint64_t x) { return ((x >> 1) | (x << (C - 1))) & mask; };
            for (int r = r0; r < r1; ++r) {
                const uint64_t u = src[r == 0 ? R - 1 : r - 1];
                const uint64_t x = src[r];
                const uint64_t d = src[r == R - 1 ? 0 : r + 1];
                const CountPlanes p =
                    count8(west(u), u, east(u), west(x), east(x), west(d), d, east(d));
                const uint64_t nx = apply_rule(x, p, rule) & mask;
                dst[r] = nx;
                pop += static_cast<uint64_t>(std::popcount(nx));
            }
            return pop;
        }

        // several words per row: the wrap carries a bit across word edges
        const int W = in.wpr;
        for (int r = r0; r < r1; ++r) {
            const uint64_t* u = src + static_cast<std::size_t>(r == 0 ? R - 1 : r - 1) * W;
            const uint64_t* x = src + static_cast<std::size_t>(r) * W;
            const uint64_t* d = src + static_cast<std::size_t>(r == R - 1 ? 0 : r + 1) * W;
            uint64_t* o = dst + static_cast<std::size_t>(r) * W;
            for (int j = 0; j < W; ++j) {
                const int jw = (j == 0) ? W - 1 : j - 1;
                const int je = (j == W - 1) ? 0 : j + 1;
                // the west neighbor of column 64j is bit 63 of the previous word
                const auto west = [j, jw](const uint64_t* row) { return (row[j] << 1) | (row[jw] >> 63); };
                const auto east = [j, je](const uint64_t* row) { return (row[j] >> 1) | (row[je] << 63); };
                const CountPlanes p =
                    count8(west(u), u[j], east(u), west(x), east(x), west(d), d[j], east(d));
                const uint64_t nx = apply_rule(x[j], p, rule);
                o[j] = nx;
                pop += static_cast<uint64_t>(std::popcount(nx));
            }
        }
        return pop;
    }
};

}  // namespace cellnet
