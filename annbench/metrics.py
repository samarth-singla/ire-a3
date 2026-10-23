"""Tie-aware recall@k.

Definition (also in the README):

    For query q, let d10 be the true (squared L2) distance of the 10th exact neighbour.
    A returned id counts as correct if its true distance to q is <= d10 * (1 + eps) + eps_abs
    (default eps = 1e-5, eps_abs = 1e-6, on squared L2). Duplicates and -1 ids are ignored.
    recall@10(q) = min(#correct, 10) / 10. We report the mean over queries.

So a returned point tied with the 10th neighbour is never counted as a mistake, even if the
ground truth happened to list a different point at that distance.

The true distance of every returned id is recomputed from the vectors in float64. The distances
an index returns are never used: PQ distances are approximate and would give wrong answers.
Only the first k returned ids are considered; fewer than k (e.g. -1 padding from IVF with a
tiny nprobe) is fine.
"""
from __future__ import annotations

import numpy as np


def true_sq_dist(xq: np.ndarray, xb: np.ndarray, ids: np.ndarray, chunk: int = 500) -> np.ndarray:
    """Squared L2 distance in float64 between query i and each id in ``ids[i]``.

    ``ids`` is [nq, r]; ids < 0 give +inf. Returns float64 [nq, r]. Processed in chunks of
    queries to bound memory.
    """
    ids = np.asarray(ids)
    nq, r = ids.shape
    out = np.empty((nq, r), dtype=np.float64)
    for s in range(0, nq, chunk):
        e = min(s + chunk, nq)
        idc = ids[s:e]
        valid = idc >= 0
        vecs = xb[np.where(valid, idc, 0)].astype(np.float64)          # [c, r, d]
        diff = vecs - np.asarray(xq[s:e], dtype=np.float64)[:, None, :]
        d = np.einsum("ijk,ijk->ij", diff, diff)
        out[s:e] = np.where(valid, d, np.inf)
    return out


def recall_per_query(xq: np.ndarray, xb: np.ndarray, retrieved_ids: np.ndarray,
                     gt_dist: np.ndarray, k: int = 10,
                     rel_eps: float = 1e-5, abs_eps: float = 1e-6) -> np.ndarray:
    """Tie-aware recall@k for each query (float64 array of length nq). See module docstring.

    xq             [nq, d] queries.
    xb             [n, d] base vectors (the ones the index was built on).
    retrieved_ids  [nq, r] ids returned by the index; only the first k columns are used.
    gt_dist        [nq, >=k] exact squared-L2 distances, sorted ascending per row
                   (from ``data.get_ground_truth``); column k-1 is d10.
    """
    retrieved_ids = np.asarray(retrieved_ids)
    gt_dist = np.asarray(gt_dist, dtype=np.float64)
    if retrieved_ids.ndim != 2 or gt_dist.ndim != 2:
        raise ValueError("retrieved_ids and gt_dist must be 2-D [nq, *]")
    nq = xq.shape[0]
    if retrieved_ids.shape[0] != nq or gt_dist.shape[0] != nq:
        raise ValueError(f"row mismatch: xq {nq}, retrieved {retrieved_ids.shape[0]}, "
                         f"gt_dist {gt_dist.shape[0]}")
    if gt_dist.shape[1] < k:
        raise ValueError(f"gt_dist has {gt_dist.shape[1]} columns, need at least k={k}")

    ids = np.sort(retrieved_ids[:, :k].astype(np.int64), axis=1)
    # keep each valid id once: drop -1 and repeats (rows are sorted, so repeats are adjacent)
    first = np.ones_like(ids, dtype=bool)
    first[:, 1:] = ids[:, 1:] != ids[:, :-1]
    ids = np.where((ids >= 0) & first, ids, -1)

    dist = true_sq_dist(xq, xb, ids)                         # -1 -> +inf
    threshold = gt_dist[:, k - 1] * (1.0 + rel_eps) + abs_eps
    correct = (dist <= threshold[:, None]).sum(axis=1)
    return np.minimum(correct, k) / k


def recall_at_k(xq: np.ndarray, xb: np.ndarray, retrieved_ids: np.ndarray,
                gt_dist: np.ndarray, k: int = 10,
                rel_eps: float = 1e-5, abs_eps: float = 1e-6) -> float:
    """Mean tie-aware recall@k over queries. See ``recall_per_query``."""
    return float(recall_per_query(xq, xb, retrieved_ids, gt_dist, k, rel_eps, abs_eps).mean())
