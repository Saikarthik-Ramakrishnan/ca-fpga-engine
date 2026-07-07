"""
tier4_multiprocessing.py — genuine parallelism: separate OS processes.

Unlike threads, each process has its own Python interpreter and its own
GIL, so this is real concurrent execution across cores (as many as your
machine actually has). The grid is split into horizontal strips, one per
worker process. The catch — and the interesting problem — is that each
cell's rule needs its 8 neighbors, so a strip's top and bottom rows depend
on the *adjacent* strip's edge rows. Every generation, neighboring workers
must exchange one row each ("halo exchange") before they can compute their
own next state. This is a miniature version of the same problem real
distributed simulations (MPI, weather models, N-body codes) solve.

Workers are arranged in a ring (worker k-1 wraps around to worker 0,
matching the toroidal grid). Communication uses one Pipe per adjacent
pair, persistent for the whole run — workers are spawned once and loop
over all generations internally, not respawned per generation.
"""
from __future__ import annotations
import multiprocessing as mp
from golden_rule import update


def _local_step(strip: list[list[int]], halo_above: list[int],
                 halo_below: list[int], n: int) -> list[list[int]]:
    """Compute one generation for a strip given its two halo rows."""
    extended = [halo_above] + strip + [halo_below]
    h = len(strip)
    out = [[0] * n for _ in range(h)]
    for y in range(1, h + 1):  # index into `extended`
        row_above, row_here, row_below = extended[y - 1], extended[y], extended[y + 1]
        for x in range(n):
            xl, xr = (x - 1) % n, (x + 1) % n
            nb = (row_above[xl] + row_above[x] + row_above[xr] +
                  row_here[xl]  +                row_here[xr]  +
                  row_below[xl] + row_below[x] + row_below[xr])
            out[y - 1][x] = update(row_here[x], nb)
    return out


def _worker(strip, n, gens, link_to_prev, link_to_next, result_queue, worker_id):
    for _ in range(gens):
        top, bottom = strip[0], strip[-1]
        # send my edges to neighbors
        link_to_prev.send(top)      # goes to worker (i-1): becomes its "below" halo
        link_to_next.send(bottom)   # goes to worker (i+1): becomes its "above" halo
        # receive my halos
        halo_above = link_to_prev.recv()   # worker (i-1)'s bottom row
        halo_below = link_to_next.recv()   # worker (i+1)'s top row
        strip = _local_step(strip, halo_above, halo_below, n)
    result_queue.put((worker_id, strip))


def step_multiprocess(grid: list[list[int]], n: int, gens: int,
                       n_workers: int = 4) -> list[list[int]]:
    """Runs `gens` generations across `n_workers` processes and returns
    the final grid, fully re-assembled. Spawns workers once for the whole
    run (not per generation) so timing reflects compute + halo exchange,
    not process-startup overhead."""
    n_workers = max(1, min(n_workers, n))
    chunk = n // n_workers
    bounds = []
    y = 0
    for i in range(n_workers):
        h = chunk + (1 if i < n % n_workers else 0)
        bounds.append((y, y + h))
        y += h

    # ring of pipes: pipe[i] connects worker i (next-end) <-> worker i+1 (prev-end)
    pipes = [mp.Pipe() for _ in range(n_workers)]
    result_queue = mp.Queue()
    procs = []
    for i in range(n_workers):
        a, b = bounds[i]
        strip = grid[a:b]
        link_to_next = pipes[i][0]                    # my "down" link
        link_to_prev = pipes[(i - 1) % n_workers][1]   # my "up" link
        p = mp.Process(target=_worker, args=(
            strip, n, gens, link_to_prev, link_to_next, result_queue, i))
        procs.append(p)
        p.start()

    strips = [None] * n_workers
    for _ in range(n_workers):
        wid, strip = result_queue.get()
        strips[wid] = strip
    for p in procs:
        p.join()

    out = []
    for strip in strips:
        out.extend(strip)
    return out
