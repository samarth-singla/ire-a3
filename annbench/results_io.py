"""results.csv with a fixed schema (implementation.md, Section 4).

One row per timed run. ``results.csv`` is never deleted: each experiment script owns the rows
with its ``part`` value ("1", "2", "3", "4", "q4"), collects its rows in memory, and at the end
calls ``replace_part_rows``, which rewrites the file with every other part's rows unchanged and
its own old rows replaced (temp file + rename, so a crashed run leaves the old rows in place).

Every row's ``extra`` JSON must contain ``pinned_cpu`` (the logical CPU the search was pinned
to, or null).
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

SCHEMA = [
    "run_id", "part", "dataset", "n_base", "index", "build_params", "search_param_name",
    "search_param", "split", "n_queries", "k", "recall_at_10", "qps_median", "qps_runs",
    "latency_ms_median", "build_time_s", "train_time_s", "build_threads", "search_threads",
    "index_bytes", "bytes_per_vector", "mode", "experiment_tag", "extra", "timestamp",
    "git_commit",
]
JSON_COLUMNS = {"build_params", "qps_runs", "extra"}
PARTS = {"1", "2", "3", "4", "q4"}

_GIT_COMMIT: str | None = None


def git_commit() -> str:
    """``git rev-parse --short HEAD`` plus ``-dirty`` if tracked code has uncommitted changes.

    Read-only git only. Changes under results/ and results_quick/ are ignored for the dirty
    flag (results are written by the runs themselves). Cached for the whole process, so all
    rows of one run share it. Returns "unknown" outside a git checkout.
    """
    global _GIT_COMMIT
    if _GIT_COMMIT is None:
        try:
            head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                           cwd=config.ROOT, text=True,
                                           stderr=subprocess.DEVNULL).strip()
            status = subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no", "--", ".",
                 ":(exclude)results", ":(exclude)results_quick"],
                cwd=config.ROOT, text=True, stderr=subprocess.DEVNULL).strip()
            _GIT_COMMIT = head + ("-dirty" if status else "")
        except (OSError, subprocess.CalledProcessError):
            _GIT_COMMIT = "unknown"
    return _GIT_COMMIT


def make_row(*, part, dataset, n_base, index, mode, split, k, timing: dict | None = None,
             extra: dict | None = None, **fields) -> dict:
    """Build one schema row.

    ``timing`` is the dict from ``timing.time_single_query`` / ``time_batch``; it supplies
    n_queries, qps_median, qps_runs, latency_ms_median, search_threads and ``pinned_cpu``
    (stored in ``extra``). Other columns are passed as keyword arguments; unknown names raise.
    """
    part = str(part)
    if part not in PARTS:
        raise ValueError(f"part must be one of {sorted(PARTS)}, got {part!r}")
    row = {c: None for c in SCHEMA}
    row.update(part=part, dataset=dataset, n_base=n_base, index=index, mode=mode,
               split=split, k=k)
    extra = dict(extra or {})
    if timing is not None:
        for key in ("n_queries", "qps_median", "qps_runs", "latency_ms_median",
                    "search_threads"):
            row[key] = timing[key]
        extra.setdefault("pinned_cpu", timing["pinned_cpu"])
    unknown = set(fields) - set(SCHEMA)
    if unknown:
        raise ValueError(f"unknown result columns: {sorted(unknown)}")
    row.update(fields)
    if "pinned_cpu" not in extra:
        raise ValueError("extra must record 'pinned_cpu' (the CPU id, or None if unpinned)")
    row["extra"] = extra
    row["run_id"] = row["run_id"] or uuid.uuid4().hex[:12]
    row["timestamp"] = row["timestamp"] or datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["git_commit"] = row["git_commit"] or git_commit()
    return row


def _encode(row: dict) -> dict:
    out = {}
    for col in SCHEMA:
        val = row.get(col)
        if col in JSON_COLUMNS:
            out[col] = "" if val is None else json.dumps(val, sort_keys=True)
        elif val is None:
            out[col] = ""
        else:
            out[col] = val
    return out


def read_rows(path: Path) -> list[dict]:
    """Raw rows (strings) of an existing results.csv; [] if it does not exist."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SCHEMA:
            raise ValueError(f"{path} has columns {reader.fieldnames}, expected the fixed schema")
        return list(reader)


def replace_part_rows(results_dir: Path, part, rows: list[dict]) -> Path:
    """Replace all rows of ``part`` in ``results_dir/results.csv`` with ``rows``."""
    part = str(part)
    for r in rows:
        if str(r["part"]) != part:
            raise ValueError(f"row has part {r['part']!r}, expected {part!r}")
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "results.csv"
    kept = [r for r in read_rows(path) if r["part"] != part]
    tmp = path.with_name("results.csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(kept)
        writer.writerows(_encode(r) for r in rows)
    os.replace(tmp, path)
    return path
