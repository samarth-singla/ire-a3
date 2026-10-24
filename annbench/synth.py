"""Part 4 data generator: drifting data derived from real SIFT vectors (seeded).

    base    = SIFT base vectors [0, n_base)                      (the index is built on these)
    added   = SIFT base vectors [n_base, n_base + n_added) + shift * R * u
    queries = SIFT query vectors [0, n_queries)                  + shift * R * u

``u`` is a unit direction drawn from a seeded standard normal; ``R`` is the mean Euclidean
distance of the base vectors to the base centroid. ``u`` depends only on the seed and the
dimension, and ``R`` only on the base vectors, so **only the shift changes between settings**;
shift = 0 is the control (added vectors and queries come from the same distribution as base).

The translation is computed in float64 and the result stored as C-contiguous float32, so the
same inputs and seed always give bit-identical arrays.
"""
from __future__ import annotations

import numpy as np

import config


def drift_direction(d: int, seed: int = config.SEED) -> np.ndarray:
    """Seeded random unit vector (float64) in d dimensions."""
    u = np.random.default_rng(seed).standard_normal(d)
    return u / np.linalg.norm(u)


def base_radius(base: np.ndarray) -> float:
    """R = mean distance of the base vectors to their centroid."""
    b = np.asarray(base, dtype=np.float64)
    return float(np.linalg.norm(b - b.mean(axis=0), axis=1).mean())


def apply_drift(base: np.ndarray, added_src: np.ndarray, queries_src: np.ndarray,
                shift: float, seed: int = config.SEED) -> dict:
    """Translate ``added_src`` and ``queries_src`` by ``shift * R * u``; ``base`` is unchanged.

    Returns a dict with float32 C-contiguous ``base``, ``added``, ``queries`` and the metadata
    ``shift``, ``seed``, ``R``, ``u`` (float64), ``offset`` (= shift * R * u).
    """
    base = np.ascontiguousarray(base, dtype=np.float32)
    d = base.shape[1]
    if added_src.shape[1] != d or queries_src.shape[1] != d:
        raise ValueError("base, added and queries must have the same dimension")
    u = drift_direction(d, seed)
    R = base_radius(base)
    offset = float(shift) * R * u
    added = np.ascontiguousarray(np.asarray(added_src, dtype=np.float64) + offset, dtype=np.float32)
    queries = np.ascontiguousarray(np.asarray(queries_src, dtype=np.float64) + offset,
                                   dtype=np.float32)
    return {"base": base, "added": added, "queries": queries, "shift": float(shift),
            "seed": int(seed), "R": R, "u": u, "offset": offset}


def make_drift(shift: float, seed: int = config.SEED, n_base: int = 200_000,
               n_added: int = 200_000, n_queries: int = 2000) -> dict:
    """Drift data from the SIFT file (see module docstring). At most n_base + n_added vectors
    (<= 500K required) plus n_queries queries."""
    from annbench import data

    if n_base + n_added > 500_000:
        raise ValueError("Part 4 must use at most 500K vectors")
    xb, xq, *_ = data.load_dataset("sift", n_base + n_added, verbose=False)
    out = apply_drift(xb[:n_base], xb[n_base:n_base + n_added], xq[:n_queries], shift, seed)
    out.update(n_base=n_base, n_added=n_added, n_queries=n_queries, source="sift")
    return out
