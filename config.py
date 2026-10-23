"""Central configuration: paths, seeds, query splits, timing settings and all parameter grids.

Every experiment script imports from here. Use ``get_config(quick)`` to get the settings for
full mode or quick mode (``--quick``); quick mode overrides the values listed in ``QUICK``.
"""
from __future__ import annotations

import copy
from pathlib import Path

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
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
EXACT_SINGLE_N = 1000        # Part 1: exact one-at-a-time timing uses the first N test queries
AGREE_N: int | None = None   # Part 1 agreement check: None = all 10,000 queries (always full-size data)

# ---------------------------------------------------------------- timing
REPEATS = 3                  # median of REPEATS timed runs
WARMUP = 1                   # untimed warm-up passes
SEARCH_THREADS = 1           # all timed searches are single-threaded
# Logical CPU the process is pinned to (psutil cpu_affinity) during timed searches only, so the
# single search thread is not moved between performance and efficiency cores. On the report
# machine (i7-13700H) logical CPUs 0-11 are P-core threads and 12-19 are E-cores; 2 = P-core.
# None disables pinning. Pinning is a no-op where psutil has no cpu_affinity (macOS).
PIN_CPU: int | None = 2

# Part 2: stop a sweep early once test recall >= this for 3 consecutive points
EARLY_STOP_RECALL = 0.999
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
    "TUNE_N": 1000,
    "EXACT_SINGLE_N": 1000,
    "AGREE_N": 1000,           # 500 if quick mode would exceed 15 min
    "REPEATS": 3,
    "RESULTS_DIR": RESULTS_QUICK_DIR,
    "GRIDS": {
        "hnsw": {"build": {"M": [16, 32], "efConstruction": [HNSW_EF_CONSTRUCTION]},
                 "sweep": [16, 32, 64, 128, 256]},
        "ivfflat": {"build": {"nlist": [256, 1024]},
                    "sweep": [1, 4, 16, 64, 256]},
        "ivfpq": {"build": {"sift": {"nlist": [1024], "m": [16, 32], "nbits": [PQ_NBITS]},
                            "glove": {"nlist": [1024], "m": [20, 50], "nbits": [PQ_NBITS]}},
                  "sweep": [1, 4, 16, 64, 256]},
    },
    "PART3": {"n_base": 100_000, "nlist": 1024, "m": [8, 16, 32],
              "sweep": [1, 4, 16, 64, 256]},
    "PART4": {"n_base": 40_000, "n_added": 40_000, "shifts": [0.0, 0.25, 0.5, 1.0],
              "nprobe_sweep": [1, 4, 16, 64, 256], "ef_sweep": [16, 32, 64, 128, 256]},
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
        "TUNE": TUNE, "TEST": TEST, "TUNE_N": TUNE_N, "EXACT_SINGLE_N": EXACT_SINGLE_N,
        "AGREE_N": AGREE_N,
        "REPEATS": REPEATS, "WARMUP": WARMUP, "PIN_CPU": PIN_CPU,
        "RESULTS_DIR": RESULTS_DIR,
        "GRIDS": GRIDS, "PART3": PART3, "PART4": PART4,
    }
    if quick:
        cfg = _merge(cfg, QUICK)
        cfg["QUICK"] = True
    return cfg
