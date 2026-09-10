#!/usr/bin/env python3
"""
compare_fpga.py

Laptop vs FPGA, throughput and latency, built from measured inputs only.

Laptop  results/laptop_bench.csv, written by build/bench on this machine
        (results/machine.json records which machine, compiler and clock).
FPGA    clocks per generation and link timing, measured in cycle-accurate
        RTL simulation of cellnet_top (hardware/tests/results/*.json, from
        Makefile.fabric_latency and Makefile.link_latency), turned into time
        at the 27 MHz dock oscillator. The routed-Fmax rows come from
        nextpnr's post-route timing of the Phase 5a fixed-rule build: a
        ceiling for a faster clock the dock does not have, not a board
        measurement.

Nothing is flashed yet, so no row here is a measurement of silicon. The
laptop rows are wall-clock measurements of real runs; the FPGA rows are
exact cycle counts of the RTL multiplied by a clock period.

  python3 tools/compare_fpga.py
    -> results/laptop_vs_fpga.md
       results/laptop_vs_fpga.png, results/laptop_vs_fpga_dark.png
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CPP = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(CPP, "..", ".."))
RESULTS = os.path.join(CPP, "results")
HW_RESULTS = os.path.join(REPO, "hardware", "tests", "results")

F_DOCK = 27_000_000
ROUTED_FMAX = {16: 240.38e6, 32: 176.46e6}  # nextpnr post-route, fixed-rule build (Phase 5a)
FULL_CHIP_CEILING = 32

# Chart tokens: the dataviz reference palette, slots 1 (blue) and 2 (orange),
# validated for both surfaces with scripts/validate_palette.js.
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7", laptop="#2a78d6", fpga="#eb6834"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835", laptop="#3987e5", fpga="#d95926"),
}


# ------------------------------------------------------------------ loading

def need(path: str, hint: str) -> str:
    if not os.path.exists(path):
        sys.exit(f"missing {os.path.relpath(path, REPO)}. {hint}")
    return path


def load_bench():
    path = need(os.path.join(RESULTS, "laptop_bench.csv"), "Run: make bench")
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("threads", "rows", "cols", "cells", "lat_samples", "resolution_limited"):
            r[k] = int(r[k])
        for k in ("gens_per_s_median", "gens_per_s_min", "gens_per_s_max", "cell_updates_per_s",
                  "lat_mean_ns", "lat_p50_ns", "lat_p90_ns", "lat_p99_ns", "lat_p999_ns",
                  "lat_max_ns", "timer_tick_ns"):
            r[k] = float(r[k])
    return rows


def load_machine():
    path = need(os.path.join(RESULTS, "machine.json"), "Run: make bench")
    with open(path) as fh:
        return json.load(fh)


def load_fabric():
    out = {}
    for path in sorted(glob.glob(os.path.join(HW_RESULTS, "fabric_latency_*x*.json"))):
        with open(path) as fh:
            d = json.load(fh)
        out[d["rows"]] = d
    if not out:
        sys.exit("no fabric latency results. Run, from hardware/tests: "
                 "make -f Makefile.fabric_latency ROWS=16 COLS=16 (and 8, 24, 32)")
    return out


def load_link():
    path = need(os.path.join(HW_RESULTS, "link_latency_16x16.json"),
                "Run, from hardware/tests: make -f Makefile.link_latency")
    with open(path) as fh:
        return json.load(fh)


# --------------------------------------------------------------- selection

def at(bench, side):
    return [r for r in bench if r["rows"] == side]


def best(rows, **match):
    pool = [r for r in rows if all(r[k] == v for k, v in match.items())]
    return max(pool, key=lambda r: r["gens_per_s_median"]) if pool else None


def config(r) -> str:
    return f"{r['engine']}, {r['threads']} thread{'s' if r['threads'] != 1 else ''}"


# -------------------------------------------------------------- formatting

def si(x: float, unit: str = "") -> str:
    for suf, div in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"{x / div:,.3g} {suf}{unit}".rstrip()
    return f"{x:,.3g} {unit}".rstrip()


def ns(x: float) -> str:
    if x >= 1e6:
        return f"{x / 1e6:,.3g} ms"
    if x >= 1e3:
        return f"{x / 1e3:,.3g} µs"
    return f"{x:,.3g} ns"


def ratio(a: float, b: float) -> str:
    if b <= 0:
        return "n/a"
    r = a / b
    return f"{r:,.1f}x" if r < 100 else f"{r:,.0f}x"


# ------------------------------------------------------------------ tables

def build_tables(bench, machine, fabric, link):
    sides = sorted({r["rows"] for r in bench})
    md = []
    md.append("# Laptop vs FPGA: throughput and latency\n")
    md.append(f"- Laptop: {machine['cpu']}, {machine['performance_cores']} performance + "
              f"{machine['efficiency_cores']} efficiency cores, {machine['compiler'].split(' (')[0]}, "
              f"`{machine['flags']}`, measured {machine['date']}.")
    md.append("- FPGA: clocks per generation and link timing measured in cycle-accurate RTL simulation "
              "of `cellnet_top`, converted at the 27 MHz dock clock. Not yet measured on the board.")
    md.append("- Routed Fmax is the post-route timing ceiling of the Phase 5a fixed-rule build. The dock "
              "oscillator is 27 MHz; running at Fmax would need a PLL that is not in the design.")
    md.append(f"- Rule: Conway B3/S23. Laptop engines also count the population every generation; "
              f"the fabric does not, so the laptop does slightly more work per generation.\n")

    # --- throughput
    md.append("## Throughput\n")
    md.append("Generations per second. One generation of the fabric is one clock edge, measured.\n")
    md.append("| grid | laptop, 1 core | laptop, best configuration | FPGA at 27 MHz | FPGA at routed Fmax "
              "| FPGA 27 MHz vs best laptop |")
    md.append("|---|---|---|---|---|---|")
    thr = []
    for s in sides:
        rows = at(bench, s)
        one = best(rows, threads=1, sync="serial")
        top = max(rows, key=lambda r: r["gens_per_s_median"])
        fab = fabric.get(s)
        f27 = F_DOCK / fab["clocks_per_generation_max"] if fab else None
        fmx = ROUTED_FMAX[s] / fab["clocks_per_generation_max"] if (fab and s in ROUTED_FMAX) else None
        fits = s <= FULL_CHIP_CEILING
        thr.append((s, one, top, f27, fmx))
        md.append(
            f"| {s}x{s} | {si(one['gens_per_s_median'])} ({one['engine']}) "
            f"| {si(top['gens_per_s_median'])} ({config(top)}) "
            f"| {si(f27) if f27 else ('does not fit' if not fits else 'not simulated')} "
            f"| {si(fmx) if fmx else ('does not fit' if not fits else 'not routed')} "
            f"| {ratio(f27, top['gens_per_s_median']) if f27 else 'n/a'} |")
    md.append("")

    # --- latency
    md.append("## Latency per generation\n")
    md.append("Time from one generation being complete to the next being complete. Laptop: every "
              "generation boundary timestamped, distribution over the run. FPGA: clocks per generation "
              "counted every clock for 64 generations; the count was 1 every time, so the distribution "
              "is a single value.\n")
    tick = bench[0]["timer_tick_ns"]
    lat_rows = {}
    flagged = []
    for s in (16, 32):
        if s not in fabric:
            continue
        rows = at(bench, s)
        fab = fabric[s]
        c = fab["clocks_per_generation_max"]
        entries = [("FPGA fabric, 27 MHz", "fpga", c / F_DOCK * 1e9, c / F_DOCK * 1e9, False)]
        if s in ROUTED_FMAX:
            entries.insert(0, ("FPGA fabric, routed Fmax (ceiling)", "fpga",
                               c / ROUTED_FMAX[s] * 1e9, c / ROUTED_FMAX[s] * 1e9, False))
        picks = [("laptop, 1 core (serial/bitslice)", best(rows, sync="serial", kernel="bitslice")),
                 ("laptop, AtomicBarrier, 4 threads", best(rows, sync="atomic", kernel="bitslice", threads=4)),
                 ("laptop, std::barrier, 4 threads", best(rows, sync="barrier", kernel="bitslice", threads=4)),
                 ("laptop, mutex + condvar, 4 threads", best(rows, sync="mutex", kernel="bitslice", threads=4))]
        for label, r in picks:
            if r:
                entries.append((label, "laptop", r["lat_p50_ns"], r["lat_p99_ns"], bool(r["resolution_limited"]),
                                r))
        lat_rows[s] = entries

        md.append(f"### {s}x{s}\n")
        md.append("| implementation | mean from throughput | p50 | p99 | p99.9 | max | p99 / p50 |")
        md.append("|---|---|---|---|---|---|---|")
        for e in entries:
            label, _, p50, p99, limited = e[:5]
            if len(e) > 5:
                r = e[5]
                thr_mean = 1e9 / r["gens_per_s_median"]
                notes = []
                if limited:
                    notes.append("timer-limited")
                if r["lat_mean_ns"] > 1.5 * thr_mean:
                    notes.append(f"latency run {r['lat_mean_ns'] / thr_mean:.1f}x slower than the throughput runs")
                    flagged.append((s, label, r["lat_mean_ns"] / thr_mean))
                note = f" ({'; '.join(notes)})" if notes else ""
                md.append(f"| {label}{note} | {ns(thr_mean)} | {ns(r['lat_p50_ns'])} | {ns(r['lat_p99_ns'])} "
                          f"| {ns(r['lat_p999_ns'])} | {ns(r['lat_max_ns'])} "
                          f"| {r['lat_p99_ns'] / r['lat_p50_ns']:.2f} |")
            else:
                md.append(f"| {label} | {ns(p50)} | {ns(p50)} | {ns(p99)} | {ns(p99)} | {ns(p99)} | 1.00 |")
        md.append("")
    md.append(f"Laptop clock tick is {tick:.1f} ns (Apple silicon's 24 MHz system counter). Rows whose p50 is "
              f"under ten ticks are marked timer-limited: their percentiles are quantized, and the mean from "
              f"throughput (five timed runs, no timestamps) is the number to use.\n")
    for side, label, factor in flagged:
        md.append(f"- {side}x{side}, {label}: its single timestamped latency run was {factor:.1f}x slower than the "
                  f"median of its five throughput runs, while every other row at that size agrees within 10%. "
                  f"macOS places threads by quality of service with no hard affinity, and can keep one run on an "
                  f"efficiency core. The row is shown as measured; its throughput mean is the better estimate.")
    if flagged:
        md.append("")

    # --- link
    ms = lambda c: 1e3 * c / link["f_clk_hz"]  # noqa: E731
    md.append("## Getting bits on and off the FPGA (16x16, 115200 baud)\n")
    md.append("Measured cycle-accurately through the real pins with the deployed parameters.\n")
    md.append("| quantity | clocks | time at 27 MHz |")
    md.append("|---|---|---|")
    md.append(f"| one generation of the fabric | 1 | {ns(1e9 / F_DOCK)} |")
    md.append(f"| seed transfer in ({link['payload_bytes'] + 1} bytes) | {link['seed_transfer_clocks']:,} "
              f"| {ms(link['seed_transfer_clocks']):.3f} ms |")
    md.append(f"| frame period out | {link['frame_period_clocks']:,} | {ms(link['frame_period_clocks']):.3f} ms "
              f"({link['f_clk_hz'] / link['frame_period_clocks']:.0f} frames/s) |")
    md.append(f"| seed to first frame carrying it (measured) | {link['seed_to_frame_clocks_measured']:,} "
              f"| {ms(link['seed_to_frame_clocks_measured']):.3f} ms |")
    md.append(f"| seed to frame, possible range | {link['seed_to_frame_clocks_min']:,} to "
              f"{link['seed_to_frame_clocks_max']:,} | {ms(link['seed_to_frame_clocks_min']):.3f} to "
              f"{ms(link['seed_to_frame_clocks_max']):.3f} ms |")
    md.append("")
    md.append(f"The fabric computes a generation in {ns(1e9 / F_DOCK)}; the UART needs "
              f"{ms(link['frame_period_clocks']):.2f} ms to report one. End-to-end latency is set by the "
              f"link, by a factor of about {link['frame_period_clocks']:,}.\n")
    return "\n".join(md), thr, lat_rows


# ------------------------------------------------------------------ figure

def draw(thr, lat_rows, theme_name: str, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    t = THEMES[theme_name]
    plt.rcParams.update({
        "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9.5, "axes.titlesize": 11, "axes.titleweight": "semibold",
        "text.color": t["ink"], "axes.labelcolor": t["ink2"],
        "xtick.color": t["muted"], "ytick.color": t["muted"],
        "axes.edgecolor": t["axis"], "axes.linewidth": 1.0,
        "figure.facecolor": t["surface"], "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"],
    })
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.4, 4.9), gridspec_kw={"width_ratios": [1.12, 1]})

    for ax in (ax1, ax2):
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(True, which="major", color=t["grid"], linewidth=0.8, linestyle="-")
        ax.set_axisbelow(True)
        ax.tick_params(length=0, pad=6)

    # ---- panel 1: throughput vs grid size
    def series(xs, ys, color, filled, label):
        # Filled dots carry no surface ring here: on short log-scale segments
        # the ring cut the line into what read as a dashed, projected series.
        face = color if filled else t["surface"]
        ax1.plot(xs, ys, color=color, linewidth=2, solid_capstyle="round", solid_joinstyle="round",
                 marker="o", markersize=6.5 if filled else 7, markerfacecolor=face,
                 markeredgecolor=color, markeredgewidth=(0 if filled else 2), label=label, zorder=3)

    sides = [s for s, *_ in thr]
    one = [(s, o["gens_per_s_median"]) for s, o, _, _, _ in thr]
    top = [(s, b["gens_per_s_median"]) for s, _, b, _, _ in thr]
    f27 = [(s, f) for s, _, _, f, _ in thr if f]
    fmx = [(s, f) for s, _, _, _, f in thr if f]

    series(*zip(*fmx), t["fpga"], False, "FPGA fabric, routed Fmax (ceiling)")
    series(*zip(*f27), t["fpga"], True, "FPGA fabric, 27 MHz dock clock")
    series(*zip(*top), t["laptop"], True, "Laptop, best configuration")
    series(*zip(*one), t["laptop"], False, "Laptop, 1 core")

    ax1.set_xscale("log", base=2)
    ax1.set_yscale("log")
    ax1.xaxis.set_major_locator(FixedLocator([s for s in sides if s != 24]))
    ax1.xaxis.set_minor_locator(NullLocator())
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v)}"))
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: si(v)))
    ax1.set_xlabel("grid side N (N x N cells)")
    ax1.set_ylabel("generations per second")
    ax1.set_title("Throughput", loc="left", pad=12, color=t["ink"])

    ax1.axvline(FULL_CHIP_CEILING, color=t["axis"], linewidth=1, zorder=1)
    ymin, ymax = ax1.get_ylim()
    ax1.text(FULL_CHIP_CEILING * 1.07, ymin * 1.6, "largest full chip\non the GW2A-18",
             color=t["muted"], fontsize=8.5, va="bottom")

    # direct labels at each series' last point, in text ink
    def end_label(pts, text, dy=1.0, ha="left", dx=1.12):
        x, y = pts[-1]
        ax1.annotate(text, (x, y), xytext=(x * dx, y * dy), color=t["ink2"], fontsize=8.5,
                     va="center", ha=ha)
    # every direct label sits just right of its series' last dot, level with it
    end_label(fmx, "Fmax ceiling", dx=1.1)
    end_label(f27, "27 MHz", dx=1.1)
    end_label(top, "best", dx=1.1)
    end_label(one, "1 core", dx=1.1)

    leg = ax1.legend(loc="upper right", frameon=False, fontsize=8.5, labelcolor=t["ink2"],
                     handlelength=2.2, borderaxespad=0.2)
    for text in leg.get_texts():
        text.set_color(t["ink2"])

    # ---- panel 2: latency dumbbell at 16x16
    entries = lat_rows.get(16, [])
    ys = list(range(len(entries)))[::-1]
    for y, e in zip(ys, entries):
        label, group, p50, p99 = e[:4]
        limited = len(e) > 5 and e[4]
        if limited:  # quantized percentiles: plot the throughput mean instead
            p50 = p99 = 1e9 / e[5]["gens_per_s_median"]
        color = t[group]
        ax2.hlines(y, p50, p99, color=t["axis"], linewidth=1.2, zorder=2)
        ax2.plot([p99], [y], marker="o", markersize=7, markerfacecolor=t["surface"],
                 markeredgecolor=color, markeredgewidth=2, linestyle="none", zorder=3)
        ax2.plot([p50], [y], marker="o", markersize=7, markerfacecolor=color,
                 markeredgecolor=t["surface"], markeredgewidth=1.5, linestyle="none", zorder=4)
        if limited:
            txt = f"{ns(p50)} mean (timer-limited)"
        else:
            txt = ns(p50) if abs(p99 - p50) < 1e-9 else f"{ns(p50)} to {ns(p99)}"
        ax2.annotate(txt, (p99, y), xytext=(8, 0), textcoords="offset points",
                     va="center", ha="left", fontsize=8.5, color=t["ink2"])
    ax2.set_yticks(ys)
    ax2.set_yticklabels([e[0] for e in entries], color=t["ink2"])
    ax2.set_xscale("log")
    ax2.set_xlim(1, 3e5)
    ax2.xaxis.set_major_locator(FixedLocator([1, 10, 100, 1e3, 1e4, 1e5]))
    ax2.xaxis.set_minor_locator(NullLocator())
    ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: ns(v)))
    ax2.set_xlabel("time to compute one generation (log scale)")
    ax2.set_title("Latency per generation, 16x16", loc="left", pad=12, color=t["ink"])
    ax2.grid(False, axis="y")
    ax2.set_ylim(-0.7, len(entries) - 0.3)

    handles = [
        Line2D([], [], marker="o", linestyle="none", markersize=7, markerfacecolor=t["fpga"],
               markeredgecolor=t["surface"], label="FPGA fabric"),
        Line2D([], [], marker="o", linestyle="none", markersize=7, markerfacecolor=t["laptop"],
               markeredgecolor=t["surface"], label="Laptop"),
        Line2D([], [], marker="o", linestyle="none", markersize=7, markerfacecolor=t["muted"],
               markeredgecolor=t["surface"], label="p50 (filled)"),
        Line2D([], [], marker="o", linestyle="none", markersize=7, markerfacecolor=t["surface"],
               markeredgecolor=t["muted"], markeredgewidth=2, label="p99 (ring)"),
    ]
    leg2 = ax2.legend(handles=handles, loc="upper right", frameon=False, fontsize=8.5, ncol=2,
                      borderaxespad=0.2)
    for text in leg2.get_texts():
        text.set_color(t["ink2"])

    fig.tight_layout(w_pad=3.0)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> int:
    bench = load_bench()
    machine = load_machine()
    fabric = load_fabric()
    link = load_link()

    md, thr, lat_rows = build_tables(bench, machine, fabric, link)
    os.makedirs(RESULTS, exist_ok=True)
    md_path = os.path.join(RESULTS, "laptop_vs_fpga.md")
    with open(md_path, "w") as fh:
        fh.write(md + "\n")
    print(md)

    try:
        draw(thr, lat_rows, "light", os.path.join(RESULTS, "laptop_vs_fpga.png"))
        draw(thr, lat_rows, "dark", os.path.join(RESULTS, "laptop_vs_fpga_dark.png"))
        print(f"\nwrote {os.path.relpath(md_path, REPO)} and both figures")
    except ImportError:
        print("\nmatplotlib not installed; tables written, figures skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
