"""Central configuration: paths, seeds, query splits, timing settings and all parameter grids.

Every experiment script imports from here. Use ``get_config(quick)`` to get the settings for
full mode or quick mode (``--quick``); quick mode overrides the values listed in ``QUICK``.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
# indexes + ground truth (gitignored); ANNBENCH_CACHE_DIR overrides it, e.g. to time a cold run
CACHE_DIR = Path(os.environ.get("ANNBENCH_CACHE_DIR", ROOT / "cache"))
RESULTS_DIR = ROOT / "results"            # full mode
RESULTS_QUICK_DIR = ROOT / "results_quick"  # quick mode never overwrites full results

DATASETS = {
    "sift": {"file": "sift-128-euclidean.hdf5", "dim": 128,
             "url": "http://ann-benchmarks.com/sift-128-euclidean.hdf5"},
    "glove": {"file": "glove-100-angular.hdf5", "dim": 100,
              "url": "http://ann-benchmarks.com/glove-100-angular.hdf5"},
}

# ---------------------------------------------------------------- general
SEED = 42
K = 10                       # recall@10
GT_K = 100                   # depth of our own exact ground truth
RECALL_REL_EPS = 1e-5        # tie tolerance on squared L2 (relative)
RECALL_ABS_EPS = 1e-6        # tie tolerance on squared L2 (absolute)

# Query splits (the files have 10,000 queries). Tuning/selection uses TUNE, reports use TEST.
TUNE = slice(0, 5000)
TEST = slice(5000, 10000)
TUNE_N = 2000                # Part 2 full mode: only the first TUNE_N tune queries are timed
TEST_N: int | None = None    # Parts 2-3: cap on timed test queries (None = whole test split)
EXACT_SINGLE_N = 1000        # Part 1: exact one-at-a-time timing uses the first N test queries
AGREE_N: int | None = None   # Part 1 agreement check: None = all 10,000 queries (always full-size data)

# ---------------------------------------------------------------- timing
REPEATS = 3                  # median of REPEATS timed runs
WARMUP = 1                   # untimed warm-up passes
SEARCH_THREADS = 1           # all timed searches are single-threaded
BUILD_THREADS: int | None = None  # index building: None = all logical CPUs (recorded per index)
# Logical CPU the process is pinned to (psutil cpu_affinity) during timed searches only, so the
# single search thread is not moved between performance and efficiency cores. On the report
# machine (i7-13700H) logical CPUs 0-11 are P-core threads and 12-19 are E-cores; 2 = P-core.
# None disables pinning. Pinning is a no-op where psutil has no cpu_affinity (macOS).
PIN_CPU: int | None = 2

# Part 2: stop a sweep early once test recall >= EARLY_STOP_RECALL for EARLY_STOP_CONSECUTIVE
# consecutive sweep points
EARLY_STOP_RECALL = 0.999
EARLY_STOP_CONSECUTIVE = 2
PART2_FAMILIES = ("hnsw", "ivfflat", "ivfpq")
# Noise canary: before each build config's sweep, time a fixed exact search (single thread,
# pinned) so drift in machine state across a long run shows up in results.csv (extra.canary_qps)
CANARY_N_BASE = 20_000
CANARY_NQ = 200
TIME_BUDGET_HOURS = 8        # --estimate warns above this
TARGET_RECALLS = (0.90, 0.95)

# ---------------------------------------------------------------- index grids (Section 3)
HNSW_EF_CONSTRUCTION = 200
IVF_TRAIN_PER_LIST = 64      # train on min(n, 64 * nlist) seeded random vectors
PQ_MIN_TRAIN = 10_000        # PQ always gets at least this many training vectors
PQ_NBITS = 8
REFINE_K_FACTOR = 10         # IndexRefineFlat re-ranks top k * 10 = 100 candidates

NPROBE_SWEEP = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]

GRIDS = {
    "hnsw": {
        "build": {"M": [16, 32, 48], "efConstruction": [HNSW_EF_CONSTRUCTION]},
        "search_param": "efSearch",
        "sweep": [10, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512],
    },
    "ivfflat": {
        "build": {"nlist": [1024, 4096, 8192]},
        "search_param": "nprobe",
        "sweep": NPROBE_SWEEP,
    },
    "ivfpq": {
        # m must divide d: SIFT d=128, GloVe d=100
        "build": {
            "sift": {"nlist": [1024, 4096], "m": [16, 32, 64], "nbits": [PQ_NBITS]},
            "glove": {"nlist": [1024, 4096], "m": [20, 25, 50], "nbits": [PQ_NBITS]},
        },
        "search_param": "nprobe",
        "sweep": NPROBE_SWEEP,
    },
}

# Extra sweep values for single build configs whose sweep never reached recall 0.95 in the full
# run (implementation.md Section 3: extend the sweep rather than accept it). Full mode only.
SWEEP_EXTEND = [
    {"dataset": "glove", "family": "hnsw", "params": {"M": 16}, "values": [768, 1024]},
    {"dataset": "glove", "family": "ivfflat", "params": {"nlist": 8192}, "values": [1024]},
]

# ---------------------------------------------------------------- Part 3 (compression)
PART3 = {
    "dataset": "sift",
    "n_base": None,          # None = full 1M
    "nlist": 4096,
    "m": [8, 16, 32, 64],
    "nbits": PQ_NBITS,
    "refine_k_factor": REFINE_K_FACTOR,
    "sweep": NPROBE_SWEEP,
}

# ---------------------------------------------------------------- Part 4 (drift)
PART4 = {
    "n_base": 200_000,       # SIFT vectors [0, 200K) -> index is built on these
    "n_added": 200_000,      # SIFT vectors [200K, 400K) -> shifted, added after build
    "n_queries": 2000,       # 1,000 tune / 1,000 test
    "shifts": [0.0, 0.25, 0.5, 1.0],
    "ivf_nlist": 1024,
    "hnsw_M": 32,
    "nprobe_sweep": NPROBE_SWEEP,
    "ef_sweep": GRIDS["hnsw"]["sweep"],
}

# ---------------------------------------------------------------- quick mode overrides
# Quick mode: first 100K base vectors (ground truth recomputed), 1,000 tune / 1,000 test.
QUICK = {
    "N_BASE": 100_000,
    "TUNE": slice(0, 1000),
    "TEST": slice(5000, 6000),
    # Quick grids are cut for runtime (cold cache, plugged in: target < 8 min); the method is the
    # same as full mode. Parts 2-3 time 500 tune + 500 test queries; Part 1's batch and agreement
    # check keep the 1,000-query test split.
    "TUNE_N": 500,
    "TEST_N": 500,
    "EXACT_SINGLE_N": 300,
    "AGREE_N": 1000,           # 500 if quick mode would exceed 15 min
    "REPEATS": 3,
    "RESULTS_DIR": RESULTS_QUICK_DIR,
    "GRIDS": {
        "hnsw": {"build": {"M": [16, 32], "efConstruction": [HNSW_EF_CONSTRUCTION]},
                 "sweep": [16, 32, 64, 128, 256]},
        "ivfflat": {"build": {"nlist": [1024]},
                    "sweep": [1, 4, 16, 64, 256]},
        # nlist 256: PQ trains on 16,384 vectors instead of 65,536 (the slowest quick step)
        "ivfpq": {"build": {"sift": {"nlist": [256], "m": [16, 32], "nbits": [PQ_NBITS]},
                            "glove": {"nlist": [256], "m": [20, 50], "nbits": [PQ_NBITS]}},
                  "sweep": [1, 4, 16, 64]},
    },
    "PART3": {"n_base": 100_000, "nlist": 256, "m": [8, 16, 32],   # shares Part 2's IVF-PQ cache
              "sweep": [1, 4, 16, 64]},
    "SWEEP_EXTEND": [],
    "PART4": {"n_base": 40_000, "n_added": 40_000, "n_queries": 1000,
              "shifts": [0.0, 0.25, 0.5, 1.0],
              "nprobe_sweep": [1, 4, 16, 64], "ef_sweep": [16, 32, 64, 128]},
}


def _merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    out = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def get_config(quick: bool = False) -> dict:
    """Return the settings for full mode, or full mode with ``QUICK`` applied."""
    cfg = {
        "QUICK": False,
        "N_BASE": None,      # None = all base vectors in the file
        "SEED": SEED, "K": K, "GT_K": GT_K,
        "TUNE": TUNE, "TEST": TEST, "TUNE_N": TUNE_N, "TEST_N": TEST_N, "EXACT_SINGLE_N": EXACT_SINGLE_N,
        "AGREE_N": AGREE_N,
        "REPEATS": REPEATS, "WARMUP": WARMUP, "PIN_CPU": PIN_CPU,
        "RESULTS_DIR": RESULTS_DIR,
        "GRIDS": GRIDS, "SWEEP_EXTEND": SWEEP_EXTEND, "PART3": PART3, "PART4": PART4,
    }
    if quick:
        cfg = _merge(cfg, QUICK)
        cfg["QUICK"] = True
    return cfg
