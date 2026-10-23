"""results.csv with a fixed schema (implementation.md, Section 4).

One row per timed run. ``results.csv`` is never deleted: each experiment script owns the rows
with its ``part`` value ("1", "2", "3", "4", "q4"), collects its rows in memory, and at the end
calls ``replace_part_rows``, which rewrites the file with every other part's rows unchanged and
its own old rows replaced (temp file + rename, so a crashed run leaves the old rows in place).

Long runs (Part 2) instead ``append_row`` each row as soon as it is measured (flushed to disk),
skip points whose ``row_key`` is already present when restarted, and finish with
``prune_part_rows`` (drop rows outside the current grid, de-duplicate).

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
    """Raw rows (strings) of an existing results.csv; [] if it does not exist.

    A row cut short by a crash during an append (missing or extra fields) is dropped with a
    warning; it is removed from the file by the next rewrite.
    """
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SCHEMA:
            raise ValueError(f"{path} has columns {reader.fieldnames}, expected the fixed schema")
        rows, bad = [], 0
        for r in reader:
            if None in r or any(v is None for v in r.values()):
                bad += 1
                continue
            rows.append(r)
    if bad:
        print(f"[results] WARNING: ignored {bad} incomplete row(s) in {path}")
    return rows


# columns that identify one measured point (resume / de-duplication key)
KEY_COLUMNS = ("part", "dataset", "n_base", "index", "build_params", "search_param", "split",
               "n_queries")


def row_key(row: dict) -> tuple:
    """Key of a row read from the CSV (strings) or built by ``make_row`` (Python values)."""
    enc = _encode(row) if not all(isinstance(row.get(c, ""), str) for c in KEY_COLUMNS) else row
    return tuple(str(enc.get(c, "")) for c in KEY_COLUMNS)


def append_row(results_dir: Path, row: dict) -> None:
    """Append one row to ``results_dir/results.csv`` and flush it to disk immediately.

    Used by long runs (Part 2) so a crash or sleep loses at most the point being measured.
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "results.csv"
    new = not path.exists() or path.stat().st_size == 0
    needs_newline = False
    if not new:
        with path.open("rb") as f:                         # check the header only
            header = f.readline().decode("utf-8").strip().split(",")
            f.seek(-1, os.SEEK_END)
            needs_newline = f.read(1) != b"\n"             # a crash left a half-written line
        if header != SCHEMA:
            raise ValueError(f"{path} has columns {header}, expected the fixed schema")
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA)
        if new:
            writer.writeheader()
        if needs_newline:
            f.write("\r\n")      # isolate the broken line; read_rows drops it as incomplete
        writer.writerow(_encode(row))
        f.flush()
        os.fsync(f.fileno())


def prune_part_rows(results_dir: Path, part, keep) -> int:
    """Rewrite results.csv keeping other parts' rows unchanged. Rows of ``part`` are kept only
    if ``keep(row)`` is true, and duplicates (same ``row_key``) keep the latest. Returns the
    number of ``part`` rows kept."""
    part = str(part)
    path = Path(results_dir) / "results.csv"
    rows = read_rows(path)
    others = [r for r in rows if r["part"] != part]
    latest: dict[tuple, dict] = {}
    for r in rows:
        if r["part"] == part and keep(r):
            latest[row_key(r)] = r                          # later rows win
    tmp = path.with_name("results.csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(others)
        writer.writerows(latest.values())
    os.replace(tmp, path)
    return len(latest)


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
