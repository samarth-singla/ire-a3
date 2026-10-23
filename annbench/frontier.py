"""Pareto frontier (recall vs QPS) and operating-point selection.

Operating point (implementation.md, Step 7): on the **tune** split, among all configs of an
index family with recall >= target, pick the one with the highest QPS; then report that same
config's **test** recall and test QPS. Test recall is reported as measured, even if it lands
slightly below the target. If no config reaches the target on the tune split, the result is
"not reached", with the config that has the highest tune recall (and its test numbers).

A config is (build_params, search_param); rows come from results.csv (``pandas.read_csv``).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

FAMILY_LABEL = {"exact": "Exact", "hnsw": "HNSW", "ivfflat": "IVF-Flat", "ivfpq": "IVF-PQ",
                "ivfpq_refine": "IVF-PQ + re-rank"}


def pareto(points) -> np.ndarray:
    """Indices of the points not dominated in (recall up, qps up), sorted by recall.

    ``points`` is a sequence of (recall, qps). A point is dominated if another point has
    recall >= and qps >= with at least one strictly greater.
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) == 0:
        return np.array([], dtype=int)
    # sort by recall descending, then qps descending; keep points that beat the best qps so far
    order = np.lexsort((-pts[:, 1], -pts[:, 0]))
    keep, best_qps = [], -np.inf
    for i in order:
        if pts[i, 1] > best_qps:
            keep.append(i)
            best_qps = pts[i, 1]
    keep = np.array(keep, dtype=int)
    return keep[np.argsort(pts[keep, 0], kind="stable")]


def pareto_df(df: pd.DataFrame, x: str = "recall_at_10", y: str = "qps_median") -> pd.DataFrame:
    """Frontier rows of ``df`` (sorted by recall)."""
    if df.empty:
        return df
    idx = pareto(df[[x, y]].to_numpy())
    return df.iloc[idx]


def describe_config(family: str, build_params, search_param) -> str:
    """Short text like 'M=32, efSearch=128' or 'nlist=4096, m=32, nprobe=64'."""
    bp = json.loads(build_params) if isinstance(build_params, str) else dict(build_params or {})
    parts = []
    if family == "hnsw":
        parts.append(f"M={bp.get('M')}")
        name = "efSearch"
    elif family in ("ivfflat", "ivfpq", "ivfpq_refine"):
        parts.append(f"nlist={bp.get('nlist')}")
        if "m" in bp:
            parts.append(f"m={bp['m']}")
        name = "nprobe"
    else:
        name = None
    if name is not None and search_param is not None and not pd.isna(search_param):
        parts.append(f"{name}={int(search_param)}")
    return ", ".join(parts) if parts else "-"


def _latest(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (build_params, search_param, split): the latest measurement."""
    return df.sort_values("timestamp").drop_duplicates(
        ["build_params", "search_param", "split"], keep="last")


def operating_point(df: pd.DataFrame, family: str, target: float) -> dict:
    """Pick the operating point of ``family`` at ``target`` recall. See module docstring.

    ``df`` holds the rows of one dataset (and one n_base). Returns a dict with keys:
    family, target, reached, config, build_params, search_param, tune_recall, tune_qps,
    test_recall, test_qps, test_row (the test row as a dict, or None), max_tune_recall.
    """
    d = _latest(df[df["index"] == family])
    tune, test = d[d["split"] == "tune"], d[d["split"] == "test"]
    out = {"family": family, "target": target, "reached": False, "config": None,
           "build_params": None, "search_param": None, "tune_recall": np.nan,
           "tune_qps": np.nan, "test_recall": np.nan, "test_qps": np.nan, "test_row": None,
           "max_tune_recall": float(tune["recall_at_10"].max()) if len(tune) else np.nan}
    if tune.empty:
        return out
    ok = tune[tune["recall_at_10"] >= target]
    if len(ok):
        chosen = ok.loc[ok["qps_median"].idxmax()]
        out["reached"] = True
    else:
        best = tune["recall_at_10"].max()
        top = tune[tune["recall_at_10"] == best]
        chosen = top.loc[top["qps_median"].idxmax()]
    out.update(build_params=chosen["build_params"], search_param=chosen["search_param"],
               tune_recall=float(chosen["recall_at_10"]), tune_qps=float(chosen["qps_median"]),
               config=describe_config(family, chosen["build_params"], chosen["search_param"]))
    match = test[(test["build_params"] == chosen["build_params"])
                 & (test["search_param"] == chosen["search_param"])]
    if len(match):
        row = match.iloc[-1]
        out.update(test_recall=float(row["recall_at_10"]), test_qps=float(row["qps_median"]),
                   test_row=row.to_dict())
    return out


def format_op(op: dict) -> str:
    """One line for logs, e.g. 'HNSW @0.95: M=16, efSearch=64 -> test recall 0.953, 4,120 QPS'."""
    head = f"{FAMILY_LABEL.get(op['family'], op['family'])} @{op['target']:.2f}: "
    if op["config"] is None:
        return head + "no tune rows"
    if not op["reached"]:
        return (head + f"not reached (max tune recall {op['max_tune_recall']:.4f} at "
                f"{op['config']}; test recall {op['test_recall']:.4f})")
    return (head + f"{op['config']} -> test recall {op['test_recall']:.4f}, "
            f"{op['test_qps']:,.0f} QPS (tune recall {op['tune_recall']:.4f})")
