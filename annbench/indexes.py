"""Build / search wrappers for exact, HNSW, IVF-Flat, IVF-PQ and IVF-PQ + exact re-rank (FAISS only).

Families and their search parameter (set it only through ``set_search_param``):

    exact         IndexFlatL2                                  -
    hnsw          IndexHNSWFlat(d, M), efConstruction           efSearch
    ivfflat       IndexIVFFlat(IndexFlatL2, d, nlist)           nprobe
    ivfpq         IndexIVFPQ(IndexFlatL2, d, nlist, m, nbits)   nprobe
    ivfpq_refine  IndexRefineFlat(ivfpq), k_factor = 10         nprobe (of the inner IVF-PQ)

Every builder returns ``(index, build_time_s, build_threads, train_time_s)``. ``build_time_s``
is the whole build (training + adding); ``train_time_s`` is the training part.

Training (seeded sample of the base vectors, ``config.SEED``):
  * IVF-Flat: ``min(n, 64 * nlist)`` vectors (about 64 per inverted list).
  * IVF-PQ:   ``min(n, max(64 * nlist, 10_000))`` vectors. Each PQ sub-quantizer learns
    2^nbits = 256 centroids, and FAISS asks for at least 39 * 256 ~= 10,000 training points.
The FAISS k-means seeds (coarse quantizer and PQ) are also set from ``config.SEED``. HNSW has
no training; its graph depends on the insertion order, which is not fully deterministic when
building with several threads.

Builds use all logical CPUs (``config.BUILD_THREADS``), FAISS OpenMP and BLAS threads alike;
the previous thread settings are restored afterwards. Searches are timed separately, single
threaded (``annbench.timing``).

``get_index`` caches built indexes in ``cache/`` keyed by (dataset, n_base, family, params),
with a sidecar JSON holding the measured build time, train time, build threads and training
size from when the index was built. ``rebuild=True`` forces a rebuild.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

import config
from annbench import sizes

FAMILIES = ("exact", "hnsw", "ivfflat", "ivfpq", "ivfpq_refine")
SEARCH_PARAM = {"exact": None, "hnsw": "efSearch", "ivfflat": "nprobe", "ivfpq": "nprobe",
                "ivfpq_refine": "nprobe"}


# ---------------------------------------------------------------- helpers
def n_build_threads() -> int:
    return config.BUILD_THREADS or os.cpu_count() or 1


@contextmanager
def _build_threads(n: int):
    """All FAISS OpenMP + BLAS threads for building; restored on exit."""
    import faiss
    prev = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(n)
    try:
        with threadpool_limits(limits=n):
            yield n
    finally:
        faiss.omp_set_num_threads(prev)


def ivf_train_size(n: int, nlist: int) -> int:
    return min(n, config.IVF_TRAIN_PER_LIST * nlist)


def ivfpq_train_size(n: int, nlist: int) -> int:
    return min(n, max(config.IVF_TRAIN_PER_LIST * nlist, config.PQ_MIN_TRAIN))


def train_size(family: str, n: int, params: dict) -> int:
    if family == "ivfflat":
        return ivf_train_size(n, params["nlist"])
    if family in ("ivfpq", "ivfpq_refine"):
        return ivfpq_train_size(n, params["nlist"])
    return 0


def train_sample(xb: np.ndarray, size: int, seed: int = config.SEED) -> np.ndarray:
    """Seeded random sample of ``size`` base vectors (sorted ids, no replacement)."""
    n = xb.shape[0]
    if size >= n:
        return xb
    ids = np.sort(np.random.default_rng(seed).choice(n, size=size, replace=False))
    return np.ascontiguousarray(xb[ids])


def _check(xb: np.ndarray) -> np.ndarray:
    if xb.dtype != np.float32 or not xb.flags["C_CONTIGUOUS"]:
        xb = np.ascontiguousarray(xb, dtype=np.float32)
    return xb


# ---------------------------------------------------------------- builders
def build_exact(xb: np.ndarray):
    import faiss
    xb = _check(xb)
    with _build_threads(n_build_threads()) as nt:
        t0 = time.perf_counter()
        index = faiss.IndexFlatL2(xb.shape[1])
        index.add(xb)
        build = time.perf_counter() - t0
    return index, build, nt, 0.0


def build_hnsw(xb: np.ndarray, M: int, efConstruction: int = config.HNSW_EF_CONSTRUCTION):
    import faiss
    xb = _check(xb)
    with _build_threads(n_build_threads()) as nt:
        t0 = time.perf_counter()
        index = faiss.IndexHNSWFlat(xb.shape[1], M)
        index.hnsw.efConstruction = efConstruction
        index.add(xb)
        build = time.perf_counter() - t0
    return index, build, nt, 0.0


def _train_and_add(index, xb: np.ndarray, n_train: int):
    """Train on a seeded sample, then add all vectors. Returns (build_s, train_s, threads)."""
    sample = train_sample(xb, n_train)
    with _build_threads(n_build_threads()) as nt:
        t0 = time.perf_counter()
        index.train(sample)
        train = time.perf_counter() - t0
        index.add(xb)
        build = time.perf_counter() - t0
    return build, train, nt


def build_ivfflat(xb: np.ndarray, nlist: int):
    import faiss
    xb = _check(xb)
    d = xb.shape[1]
    quantizer = faiss.IndexFlatL2(d)
    index = faiss.IndexIVFFlat(quantizer, d, nlist)
    index.cp.seed = config.SEED
    build, train, nt = _train_and_add(index, xb, ivf_train_size(xb.shape[0], nlist))
    return index, build, nt, train


def _new_ivfpq(d: int, nlist: int, m: int, nbits: int):
    import faiss
    if d % m != 0:
        raise ValueError(f"PQ m={m} must divide d={d}")
    quantizer = faiss.IndexFlatL2(d)
    index = faiss.IndexIVFPQ(quantizer, d, nlist, m, nbits)
    index.cp.seed = config.SEED          # coarse k-means
    index.pq.cp.seed = config.SEED       # PQ codebooks
    return index


def build_ivfpq(xb: np.ndarray, nlist: int, m: int, nbits: int = config.PQ_NBITS):
    xb = _check(xb)
    index = _new_ivfpq(xb.shape[1], nlist, m, nbits)
    build, train, nt = _train_and_add(index, xb, ivfpq_train_size(xb.shape[0], nlist))
    return index, build, nt, train


def build_ivfpq_refine(xb: np.ndarray, nlist: int, m: int, nbits: int = config.PQ_NBITS,
                       k_factor: int = config.REFINE_K_FACTOR):
    """IVF-PQ wrapped in ``IndexRefineFlat``: the top k * k_factor PQ candidates (100 for k=10)
    are re-ranked with exact distances, so the raw float32 vectors are stored as well."""
    import faiss
    xb = _check(xb)
    ivfpq = _new_ivfpq(xb.shape[1], nlist, m, nbits)
    index = faiss.IndexRefineFlat(ivfpq)
    index.k_factor = k_factor
    build, train, nt = _train_and_add(index, xb, ivfpq_train_size(xb.shape[0], nlist))
    return index, build, nt, train


def build(family: str, xb: np.ndarray, params: dict):
    """Dispatch to the builder for ``family``."""
    p = dict(params)
    if family == "exact":
        return build_exact(xb)
    if family == "hnsw":
        return build_hnsw(xb, p["M"], p.get("efConstruction", config.HNSW_EF_CONSTRUCTION))
    if family == "ivfflat":
        return build_ivfflat(xb, p["nlist"])
    if family == "ivfpq":
        return build_ivfpq(xb, p["nlist"], p["m"], p.get("nbits", config.PQ_NBITS))
    if family == "ivfpq_refine":
        return build_ivfpq_refine(xb, p["nlist"], p["m"], p.get("nbits", config.PQ_NBITS),
                                  p.get("k_factor", config.REFINE_K_FACTOR))
    raise ValueError(f"unknown family {family!r}; expected one of {FAMILIES}")


# ---------------------------------------------------------------- search parameter
def set_search_param(index, family: str, value) -> int | None:
    """Set the search-time parameter of ``index`` and return the value actually in effect.

    hnsw: efSearch (must be >= config.K). ivfflat / ivfpq / ivfpq_refine: nprobe, capped at
    nlist (FAISS never probes more lists than exist). exact: no parameter (value must be None).
    """
    import faiss
    if family == "exact":
        if value is not None:
            raise ValueError("exact search has no search parameter")
        return None
    if family == "hnsw":
        value = int(value)
        if value < config.K:
            raise ValueError(f"efSearch={value} must be >= k={config.K}")
        faiss.downcast_index(index).hnsw.efSearch = value
        return value
    if family in ("ivfflat", "ivfpq", "ivfpq_refine"):
        ivf = faiss.extract_index_ivf(index)       # works through IndexRefineFlat too
        eff = min(int(value), ivf.nlist)
        ivf.nprobe = eff
        if family == "ivfpq_refine":
            faiss.downcast_index(index).k_factor = config.REFINE_K_FACTOR
        return eff
    raise ValueError(f"unknown family {family!r}")


# ---------------------------------------------------------------- cache
def _param_tag(params: dict) -> str:
    return "_".join(f"{k}{params[k]}" for k in sorted(params)) or "default"


def cache_paths(dataset: str, n_base: int, family: str, params: dict,
                cache_dir: Path = config.CACHE_DIR) -> tuple[Path, Path]:
    stem = f"{dataset}_{n_base}_{family}_{_param_tag(params)}"
    return Path(cache_dir) / f"{stem}.index", Path(cache_dir) / f"{stem}.json"


def get_index(dataset: str, family: str, params: dict, xb: np.ndarray, *,
              rebuild: bool = False, cache_dir: Path = config.CACHE_DIR,
              verbose: bool = True):
    """Load the index from ``cache_dir`` or build (and cache) it.

    Returns ``(index, meta)``. ``meta`` is the sidecar dict: dataset, n_base, d, family,
    params, build_time_s, train_time_s, build_threads, train_size, seed, index_bytes,
    bytes_per_vector (+ PQ code size), faiss version, created, loaded_from_cache.
    """
    import faiss
    n, d = xb.shape
    params = dict(params)
    idx_path, meta_path = cache_paths(dataset, n, family, params, cache_dir)
    expected = {"dataset": dataset, "n_base": n, "d": d, "family": family, "params": params,
                "seed": config.SEED, "train_size": train_size(family, n, params)}

    if not rebuild and idx_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if all(meta.get(k) == v for k, v in expected.items()):
            index = faiss.read_index(str(idx_path))
            if family == "ivfpq_refine":
                faiss.downcast_index(index).k_factor = params.get("k_factor",
                                                                  config.REFINE_K_FACTOR)
            meta["loaded_from_cache"] = True
            if verbose:
                print(f"[index] loaded {idx_path.name} (built in {meta['build_time_s']:.1f}s)")
            return index, meta
        if verbose:
            print(f"[index] cache {idx_path.name} does not match the request; rebuilding")

    if verbose:
        print(f"[index] building {family} {params} on {dataset} n={n} "
              f"({n_build_threads()} threads)...", flush=True)
    index, build_s, threads, train_s = build(family, xb, params)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    tmp = idx_path.with_name(idx_path.name + ".tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, idx_path)
    n_bytes = sizes.file_bytes(idx_path)          # == len(faiss.serialize_index(index))
    meta = {**expected, "build_time_s": build_s, "train_time_s": train_s,
            "build_threads": threads, **sizes.size_info(n_bytes, n, d, family, params),
            "faiss_version": faiss.__version__,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    meta_path.write_text(json.dumps(meta, indent=2))
    meta["loaded_from_cache"] = False
    if verbose:
        print(f"[index] built in {build_s:.1f}s (train {train_s:.1f}s), "
              f"{n_bytes / 2**20:.1f} MB, {meta['bytes_per_vector']:.1f} B/vector")
    return index, meta
