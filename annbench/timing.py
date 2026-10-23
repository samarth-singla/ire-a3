"""Thread control, CPU pinning, and single-query / batch timing (median of repeats).

Timing protocol
---------------
* Every timed search runs inside a ``search_threads`` context. ``set_single_thread()`` is the
  normal one: 1 FAISS OpenMP thread, 1 BLAS thread (via threadpoolctl; OpenBLAS ignores FAISS's
  thread setting), ``OMP_NUM_THREADS=1``, and the process pinned to one logical CPU.
* CPU pinning: the report machine (i7-13700H) mixes performance and efficiency cores, and
  Windows may move the single search thread between them, which adds timing noise. Inside the
  context the process is pinned to ``config.PIN_CPU`` (a P-core thread) with
  ``psutil.Process().cpu_affinity``; the previous affinity is restored on exit, so index
  building still uses all cores. Pinning is a no-op when ``PIN_CPU`` is None, when
  ``cpu_affinity`` is unsupported (macOS), or when the CPU id does not exist (warning).
* The timing functions refuse to run outside a ``search_threads`` context, so callers cannot
  forget it.
* One untimed warm-up pass, then ``repeats`` timed passes; we report the median QPS.
  ``time.perf_counter`` times the whole pass; Python's garbage collector is off during it.
* Single-query timing calls ``search_fn(xq[i:i+1], k)`` in a Python loop. The loop overhead
  (a few microseconds per call) is included and is the same for every index.
"""
from __future__ import annotations

import gc
import os
import statistics
import time
import warnings
from contextlib import contextmanager

import numpy as np
import psutil
from threadpoolctl import threadpool_info, threadpool_limits

import config

_ACTIVE: list[dict] = []          # stack of active search_threads contexts


# ---------------------------------------------------------------- environment info
def blas_info() -> list[dict]:
    """BLAS / OpenMP libraries loaded in this process (threadpoolctl), short form."""
    import faiss  # noqa: F401  (make sure FAISS's libraries are loaded too)
    keys = ("user_api", "internal_api", "version", "num_threads", "threading_layer", "filepath")
    return [{k: lib.get(k) for k in keys} for lib in threadpool_info()]


def blas_name() -> str:
    """e.g. 'openblas 0.3.34 (pthreads)'."""
    libs = [lib for lib in blas_info() if lib["user_api"] == "blas"]
    if not libs:
        return "unknown"
    return ", ".join(f"{lib['internal_api']} {lib['version']}"
                     + (f" ({lib['threading_layer']})" if lib.get("threading_layer") else "")
                     for lib in libs)


def current_affinity() -> list[int] | None:
    """The process's CPU affinity, or None where unsupported (macOS)."""
    proc = psutil.Process()
    if not hasattr(proc, "cpu_affinity"):
        return None
    return proc.cpu_affinity()


def power_plugged() -> bool | None:
    batt = psutil.sensors_battery()
    return None if batt is None else bool(batt.power_plugged)


# ---------------------------------------------------------------- thread + pinning context
def _pin(cpu: int | None) -> tuple[int | None, list[int] | None]:
    """Pin the process to ``cpu``. Returns (pinned cpu or None, previous affinity or None)."""
    if cpu is None:
        return None, None
    proc = psutil.Process()
    if not hasattr(proc, "cpu_affinity"):
        warnings.warn("cpu_affinity not supported on this OS; timing without CPU pinning")
        return None, None
    before = proc.cpu_affinity()
    if cpu not in before:
        warnings.warn(f"PIN_CPU={cpu} is not an available CPU {before}; timing without pinning")
        return None, None
    proc.cpu_affinity([cpu])
    return cpu, before


@contextmanager
def search_threads(n: int, pin_cpu: int | None = None):
    """Run searches with ``n`` FAISS + BLAS threads, optionally pinned to one logical CPU.

    Yields a dict ``{"search_threads": n, "pinned_cpu": cpu or None}``. Everything is restored
    on exit (FAISS threads, BLAS/OpenMP limits, OMP_NUM_THREADS, CPU affinity).
    """
    import faiss

    if n < 1:
        raise ValueError("n must be >= 1")
    if pin_cpu is not None and n != 1:
        raise ValueError("pinning to one CPU only makes sense with 1 thread")
    prev_faiss = faiss.omp_get_max_threads()
    prev_env = os.environ.get("OMP_NUM_THREADS")
    os.environ["OMP_NUM_THREADS"] = str(n)
    faiss.omp_set_num_threads(n)
    pinned, prev_aff = None, None
    try:
        with threadpool_limits(limits=n):            # BLAS and OpenMP pools
            pinned, prev_aff = _pin(pin_cpu)
            state = {"search_threads": n, "pinned_cpu": pinned}
            _ACTIVE.append(state)
            try:
                yield state
            finally:
                _ACTIVE.pop()
                if prev_aff is not None:
                    psutil.Process().cpu_affinity(prev_aff)
    finally:
        faiss.omp_set_num_threads(prev_faiss)
        if prev_env is None:
            os.environ.pop("OMP_NUM_THREADS", None)
        else:
            os.environ["OMP_NUM_THREADS"] = prev_env


def set_single_thread(pin_cpu: int | None = config.PIN_CPU):
    """The standard timing context: 1 thread, pinned to ``config.PIN_CPU``."""
    return search_threads(1, pin_cpu=pin_cpu)


def all_threads():
    """All logical CPUs, no pinning (only for the Part 1 multi-threaded batch reference)."""
    return search_threads(os.cpu_count() or 1, pin_cpu=None)


def _require_context() -> dict:
    if not _ACTIVE:
        raise RuntimeError("timed search outside a search_threads() context; "
                           "wrap it in `with timing.set_single_thread():`")
    return _ACTIVE[-1]


# ---------------------------------------------------------------- timing
def _timed(fn) -> float:
    gc_was_on = gc.isenabled()
    gc.disable()
    try:
        t0 = time.perf_counter()
        fn()
        return time.perf_counter() - t0
    finally:
        if gc_was_on:
            gc.enable()


def _summary(times: list[float], nq: int, state: dict, ids: np.ndarray,
             affinity_during: list[int] | None) -> dict:
    qps_runs = [nq / t for t in times]
    qps_median = statistics.median(qps_runs)
    return {
        "qps_median": qps_median,
        "qps_runs": qps_runs,
        "latency_ms_median": 1000.0 / qps_median,    # mean per-query latency of the median run
        "n_queries": nq,
        "ids": ids,
        "search_threads": state["search_threads"],
        "pinned_cpu": state["pinned_cpu"],
        "affinity_during": affinity_during,
    }


def time_single_query(search_fn, xq: np.ndarray, k: int, repeats: int = config.REPEATS,
                      warmup: int = config.WARMUP, label: str = "",
                      verbose: bool = False) -> dict:
    """Time one-query-at-a-time search: ``search_fn(xq[i:i+1], k)`` for every query.

    ``search_fn`` returns ``(distances, ids)`` like ``faiss.Index.search``.
    Returns qps_median, qps_runs, latency_ms_median, n_queries, ids (from the last run),
    search_threads, pinned_cpu, affinity_during.
    """
    state = _require_context()
    xq = np.ascontiguousarray(xq, dtype=np.float32)
    nq = xq.shape[0]
    ids = np.full((nq, k), -1, dtype=np.int64)

    def one_pass():
        for i in range(nq):
            _, I = search_fn(xq[i:i + 1], k)
            ids[i] = I[0]

    for w in range(warmup):
        t = _timed(one_pass)
        if verbose:
            print(f"    {label} warm-up {w + 1}/{warmup}: {t:.2f}s ({nq / t:.1f} QPS)", flush=True)
    times = []
    for r in range(repeats):
        times.append(_timed(one_pass))
        if verbose:
            print(f"    {label} run {r + 1}/{repeats}: {times[-1]:.2f}s "
                  f"({nq / times[-1]:.1f} QPS)", flush=True)
    return _summary(times, nq, state, ids.copy(), current_affinity())


def time_batch(search_fn, xq: np.ndarray, k: int, repeats: int = config.REPEATS,
               warmup: int = config.WARMUP, label: str = "", verbose: bool = False) -> dict:
    """Time one ``search_fn(xq, k)`` call with all queries. Same return fields as
    ``time_single_query``."""
    state = _require_context()
    xq = np.ascontiguousarray(xq, dtype=np.float32)
    nq = xq.shape[0]
    out = {}

    def one_pass():
        out["ids"] = search_fn(xq, k)[1]

    for w in range(warmup):
        t = _timed(one_pass)
        if verbose:
            print(f"    {label} warm-up {w + 1}/{warmup}: {t:.2f}s ({nq / t:.1f} QPS)", flush=True)
    times = []
    for r in range(repeats):
        times.append(_timed(one_pass))
        if verbose:
            print(f"    {label} run {r + 1}/{repeats}: {times[-1]:.2f}s "
                  f"({nq / times[-1]:.1f} QPS)", flush=True)
    return _summary(times, nq, state, np.asarray(out["ids"], dtype=np.int64),
                    current_affinity())
