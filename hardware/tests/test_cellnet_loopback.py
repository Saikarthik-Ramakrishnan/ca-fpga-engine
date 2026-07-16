# test_cellnet_loopback.py
#
# The Phase 4.5 end-to-end check, and the first test where the chip is
# exercised ONLY through its real pins: clk, rst_n, rx_serial, tx_serial.
# No test-only ports, no reaching inside. Exactly what a PC plugged into
# the Tang Primer's USB-serial bridge could do, which is the point.
#
# The loop under test:
#
#   this test --(rx_serial bits)--> uart_rx -> seed_loader -> ca_grid
#   this test <--(tx_serial bits)-- uart_tx <- grid_streamer <- ca_grid
#
# Sequence:
#   1. After reset, before any seed: every frame off the wire must be
#      all-zero. The pacer holds the (empty) grid; nothing invents cells.
#   2. Bit-bang a SEED command + glider payload into rx_serial at real
#      UART timing. From then on, every frame must match SOME generation
#      of the golden model seeded with that glider, in non-decreasing
#      order, and multiple distinct generations must show up (proving
#      the pacer actually steps the grid rather than freezing it).
#   3. Mid-run, send a SECOND seed (a blinker). Frames must switch to
#      the blinker's trajectory. One straddle frame latched pre-reseed
#      is legitimate hardware behavior and is allowed for.
#
# Generation pacing note: unlike the retired Phase 4 test where the grid
# stepped every clock, the golden model here advances once per GEN_DIV
# clocks, mirroring the pacer. The same "some consistent non-decreasing
# assignment must exist" matching logic carries over.

import sys
import os
import bisect
from collections import defaultdict

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.dirname(__file__))
from test_uart_tx import receive_uart_byte   # noqa: E402  proven decoder
from test_uart_rx import send_uart_byte      # noqa: E402  proven encoder

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                 "software_prototype", "parallelism_ladder"),
)
from golden_rule import step_golden  # noqa: E402

ROWS = 8
COLS = 8
NUM_BYTES = (ROWS * COLS) // 8
CLKS_PER_BIT = 4
GEN_DIV = 170          # clocks per generation in this sim. Deliberately NOT a
                       # divisor of the ~400-clock frame time: at 200 the
                       # streamer latched every 2nd generation exactly, so a
                       # period-2 blinker looked frozen (a real sampling alias,
                       # caught by this very test)
SYNC_BYTE = 0xAA
CMD_SEED = 0x55


def grid_to_bits(grid, rows, cols) -> int:
    bits = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                bits |= (1 << (r * cols + c))
    return bits


def bits_to_payload(bits: int) -> list:
    """Slice a grid value into the wire's byte order: byte 0 = bits
    [7:0], matching both seed_loader (in) and grid_streamer (out)."""
    return [(bits >> (8 * i)) & 0xFF for i in range(NUM_BYTES)]


def glider_grid(rows, cols, cx=2, cy=2):
    grid = [[0] * cols for _ in range(rows)]
    for dx, dy in [(0, 0), (1, 0), (2, 0), (2, 1), (1, 2)]:
        grid[(cy + dy) % rows][(cx + dx) % cols] = 1
    return grid


def blinker_grid(rows, cols, cx=3, cy=4):
    grid = [[0] * cols for _ in range(rows)]
    for dx in range(3):
        grid[cy][(cx + dx) % cols] = 1
    return grid


def golden_trajectory(seed_grid, generations: int) -> list:
    """Every grid value the golden model produces from seed_grid,
    inclusive of generation 0."""
    log = [grid_to_bits(seed_grid, ROWS, COLS)]
    g = seed_grid
    for _ in range(generations):
        g = step_golden(g, ROWS)
        log.append(grid_to_bits(g, ROWS, COLS))
    return log


def assert_frames_follow(frames, golden_log, label: str) -> list:
    """Assert some consistent non-decreasing assignment of golden
    generations to `frames` exists. Returns the chosen indices."""
    occurrences = defaultdict(list)
    for gen_index, value in enumerate(golden_log):
        occurrences[value].append(gen_index)

    chosen = []
    last = -1
    for i, frame_value in enumerate(frames):
        assert frame_value in occurrences, (
            f"[{label}] frame {i} (0x{frame_value:016x}) matches no "
            f"generation the golden model produced"
        )
        candidates = occurrences[frame_value]
        pos = bisect.bisect_left(candidates, last)
        assert pos < len(candidates), (
            f"[{label}] frame {i} (0x{frame_value:016x}) only occurs at "
            f"generations {candidates}, all before generation {last}: "
            f"streaming went backward"
        )
        last = candidates[pos]
        chosen.append(last)
    return chosen


async def frame_collector(dut, frames: list):
    while True:
        sync = await receive_uart_byte(dut, CLKS_PER_BIT)
        if sync != SYNC_BYTE:
            continue
        value = 0
        for byte_i in range(NUM_BYTES):
            b = await receive_uart_byte(dut, CLKS_PER_BIT)
            value |= (b << (byte_i * 8))
        frames.append(value)


async def send_seed(dut, grid):
    """Push a full SEED transfer into rx_serial, bit by bit, at real
    UART timing, with a small inter-byte idle like a real PC produces."""
    await send_uart_byte(dut, CMD_SEED, CLKS_PER_BIT)
    for b in bits_to_payload(grid_to_bits(grid, ROWS, COLS)):
        for _ in range(CLKS_PER_BIT * 2):   # inter-byte gap
            await RisingEdge(dut.clk)
        await send_uart_byte(dut, b, CLKS_PER_BIT)


@cocotb.test()
async def seed_in_frames_out_full_loop(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())

    dut.rx_serial.value = 1   # UART line idles high
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)

    frames = []
    cocotb.start_soon(frame_collector(dut, frames))

    # ---- 1: pre-seed, the wire must report an empty grid ----
    frame_clks = (NUM_BYTES + 1) * 10 * CLKS_PER_BIT
    for _ in range(frame_clks * 3):
        await RisingEdge(dut.clk)
    assert len(frames) >= 2, "streamer produced no frames after reset"
    assert all(f == 0 for f in frames), (
        f"pre-seed frames must be all-zero, got {[hex(f) for f in frames]}"
    )

    # ---- 2: seed a glider over the wire, watch it live ----
    glider = glider_grid(ROWS, COLS)
    await send_seed(dut, glider)

    run_clks = GEN_DIV * 40
    for _ in range(run_clks):
        await RisingEdge(dut.clk)

    golden = golden_trajectory(glider, run_clks // GEN_DIV + 4)

    # frames still zero at this point are the pre-seed transient
    # (including at most one frame latched mid-seed); everything after
    # the first nonzero frame belongs to the glider's trajectory.
    first_live = next((i for i, f in enumerate(frames) if f != 0), None)
    assert first_live is not None, "no live frames after seeding"
    glider_frames = frames[first_live:]
    chosen = assert_frames_follow(glider_frames, golden, "glider")
    assert len(set(chosen)) >= 3, (
        f"pacer appears stuck: only generations {sorted(set(chosen))} "
        f"observed across {len(glider_frames)} frames"
    )
    dut._log.info(
        f"glider phase: {len(glider_frames)} frames, "
        f"generations {chosen}"
    )

    # ---- 3: reseed mid-run with a blinker ----

    frames_at_reseed = len(frames)
    blinker = blinker_grid(ROWS, COLS)
    await send_seed(dut, blinker)

    for _ in range(GEN_DIV * 20):
        await RisingEdge(dut.clk)

    blinker_golden = golden_trajectory(blinker, 25)
    post = frames[frames_at_reseed:]
    assert len(post) >= 4, f"too few frames after reseed: {len(post)}"

    # up to 2 frames may straddle the reseed (latched before it, or the
    # transfer itself spans a frame): skip past any that still belong to
    # the glider's world, then everything must be blinker.
    start = 0
    blinker_values = set(blinker_golden)
    while start < min(3, len(post)) and post[start] not in blinker_values:
        start += 1
    assert start < 3, (
        "no frame within 3 of the reseed matches the blinker trajectory: "
        f"got {[hex(f) for f in post[:3]]}"
    )
    chosen2 = assert_frames_follow(post[start:], blinker_golden, "blinker")
    assert len(set(chosen2)) >= 2, "blinker never oscillated on the wire"
    dut._log.info(
        f"blinker phase: {len(post) - start} frames, generations {chosen2}"
    )
