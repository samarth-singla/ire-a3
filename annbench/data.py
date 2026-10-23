"""Load the ann-benchmarks hdf5 datasets, normalise GloVe, split queries, compute exact ground truth.

hdf5 keys: ``train`` (base vectors), ``test`` (10,000 queries), ``neighbors`` / ``distances``
(the file's top-100 ground truth). The file's distances are NOT squared L2: SIFT stores plain
Euclidean distance and GloVe stores angular distance (1 - cosine).

GloVe: base and queries are L2-normalised. For unit vectors ||a - b||^2 = 2 - 2 cos(a, b), so
Euclidean order equals angular order and we use Euclidean (squared L2, ``IndexFlatL2``) everywhere.

All recall in the project is measured against our own exact ground truth from
``get_ground_truth`` (squared L2). The file's ``neighbors`` are only used for the Part 1
agreement check, and only at full size (they are for the full base set).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import h5py
import numpy as np

import config
from annbench.metrics import true_sq_dist

_FILE_METRIC = {"sift": "euclidean (file distances = L2, not squared)",
                "glove": "angular (file distances = 1 - cosine)"}


def _as_f32(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float32)


def l2_normalise(x: np.ndarray) -> tuple[np.ndarray, int]:
    """Return (row-normalised copy of x, number of zero-norm rows). Zero rows stay zero."""
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x.astype(np.float64), axis=1, keepdims=True)
    zero = norms[:, 0] == 0
    norms[zero] = 1.0
    return _as_f32(x / norms), int(zero.sum())


def load_dataset(name: str, n_base: int | None = None, verbose: bool = True):
    """Load a dataset.

    Returns ``(xb, xq, gt_ids, gt_dist, metric_note)``:
      xb, xq      float32, C-contiguous (GloVe: L2-normalised).
      gt_ids      the file's ``neighbors`` (int64, top-100), or None if ``n_base`` is given,
      gt_dist     the file's ``distances`` (float32, in the file's own metric), or None if
                  ``n_base`` is given. With a subset the file's ground truth is invalid; use
                  ``get_ground_truth`` (which is what all recall uses anyway).
      metric_note short text describing the metric and preprocessing.

    ``n_base``: take the first ``n_base`` base vectors (quick mode / scaling).
    """
    if name not in config.DATASETS:
        raise ValueError(f"unknown dataset {name!r}; expected one of {list(config.DATASETS)}")
    path = config.DATA_DIR / config.DATASETS[name]["file"]
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run: bash scripts/download_data.sh")

    with h5py.File(path, "r") as f:
        n_total = f["train"].shape[0]
        if n_base is not None and not (0 < n_base <= n_total):
            raise ValueError(f"n_base={n_base} out of range (file has {n_total} base vectors)")
        xb = f["train"][:n_base] if n_base is not None else f["train"][:]
        xq = f["test"][:]
        if n_base is None:
            gt_ids = f["neighbors"][:].astype(np.int64)
            gt_dist = f["distances"][:].astype(np.float32)
        else:
            gt_ids = gt_dist = None

    xb, xq = _as_f32(xb), _as_f32(xq)
    note = f"{name}: file metric {_FILE_METRIC[name]}; we use squared L2"
    if name == "glove":
        xb, zb = l2_normalise(xb)
        xq, zq = l2_normalise(xq)
        note += f"; base+queries L2-normalised (zero-norm rows left as zeros: base {zb}, queries {zq})"
        if verbose:
            print(f"[data] glove: zero-norm vectors left as zeros: base={zb}, queries={zq}")
    if verbose:
        print(f"[data] loaded {name}: xb {xb.shape}, xq {xq.shape}"
              + (f" (first {n_base} base vectors)" if n_base is not None else ""))
    return xb, xq, gt_ids, gt_dist, note


def gt_cache_path(name: str, n_base: int) -> Path:
    return config.CACHE_DIR / f"gt_{name}_{n_base}.npz"


def get_ground_truth(name: str, n_base: int | None, k: int = config.GT_K, *,
                     xb: np.ndarray | None = None, xq: np.ndarray | None = None,
                     batch_size: int = 1000, verbose: bool = True):
    """Exact top-k ids and squared-L2 distances for all 10,000 queries.

    Computed with ``faiss.IndexFlatL2`` (batched, all threads; not timed), then the distances of
    the returned ids are recomputed in float64 from the vectors and each row is re-sorted by
    (distance, id). This puts ground-truth distances on the same float64 scale that recall@10
    uses for retrieved ids (Step 3); FAISS's float32 distances are kept as ``dist_faiss`` in the
    cache for reference.

    Cached to ``cache/gt_{name}_{n_base}.npz`` (``n_base`` = actual number of base vectors).
    Pass ``xb``/``xq`` from ``load_dataset`` to avoid reloading the file.
    Returns ``(ids int64 [nq, k], dist float64 [nq, k])``.
    """
    import faiss

    if xb is None or xq is None:
        xb, xq, *_ = load_dataset(name, n_base, verbose=verbose)
    n = xb.shape[0]
    if n_base is not None and n != n_base:
        raise ValueError(f"xb has {n} rows but n_base={n_base}")
    path = gt_cache_path(name, n)

    if path.exists():
        z = np.load(path)
        if int(z["k"]) >= k and int(z["n_base"]) == n and z["ids"].shape[0] == xq.shape[0]:
            if verbose:
                print(f"[gt] loaded cached ground truth {path.name}")
            return z["ids"][:, :k], z["dist"][:, :k]
        if verbose:
            print(f"[gt] cache {path.name} does not match (k/n_base/nq); recomputing")

    nq = xq.shape[0]
    prev_threads = faiss.omp_get_max_threads()
    threads = os.cpu_count() or 1
    faiss.omp_set_num_threads(threads)
    try:
        index = faiss.IndexFlatL2(xb.shape[1])
        index.add(xb)
        ids = np.empty((nq, k), dtype=np.int64)
        dist_faiss = np.empty((nq, k), dtype=np.float32)
        t0 = time.perf_counter()
        if verbose:
            print(f"[gt] {name}: exact top-{k} for {nq} queries over {n} vectors "
                  f"({threads} threads, batches of {batch_size})")
        for start in range(0, nq, batch_size):
            stop = min(start + batch_size, nq)
            dist_faiss[start:stop], ids[start:stop] = index.search(xq[start:stop], k)
            if verbose:
                el = time.perf_counter() - t0
                eta = el / stop * (nq - stop)
                print(f"[gt]   {stop:>6}/{nq} queries  {el:6.1f}s elapsed  ~{eta:5.1f}s left",
                      flush=True)
        del index
    finally:
        faiss.omp_set_num_threads(prev_threads)

    dist = exact_sq_dist(xq, xb, ids)
    order = np.lexsort((ids, dist), axis=1)          # by distance, ties by id
    ids = np.take_along_axis(ids, order, axis=1)
    dist = np.take_along_axis(dist, order, axis=1)
    dist_faiss = np.take_along_axis(dist_faiss, order, axis=1)

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez(tmp, ids=ids, dist=dist, dist_faiss=dist_faiss, k=k, n_base=n)
    os.replace(tmp, path)
    if verbose:
        print(f"[gt] done in {time.perf_counter() - t0:.1f}s -> {path}")
    return ids, dist


# Squared L2 in float64 from the vectors; same function recall@10 uses, so ground-truth and
# retrieved distances are on exactly the same scale.
exact_sq_dist = true_sq_dist


# ---------------------------------------------------------------- query splits
def tune_queries(xq: np.ndarray, cfg: dict | None = None) -> np.ndarray:
    """Tuning / selection queries: first half (``xq[0:5000]``; quick mode: ``xq[0:1000]``)."""
    return xq[(cfg or config.get_config())["TUNE"]]


def test_queries(xq: np.ndarray, cfg: dict | None = None) -> np.ndarray:
    """Reporting queries: second half (``xq[5000:10000]``; quick mode: ``xq[5000:6000]``)."""
    return xq[(cfg or config.get_config())["TEST"]]
