"""Part 2: benchmark HNSW, IVF-Flat and IVF-PQ on SIFT and GloVe (single thread, one query at a time).

For each dataset x index family x build setting (config.py grids):
  1. build the index, or load it from cache/ (``--rebuild`` forces a rebuild);
  2. noise canary: time a fixed small exact search (CANARY_NQ tune queries on the first
     CANARY_N_BASE base vectors, single thread, pinned) and store it as extra.canary_qps;
  3. for each search parameter in the sweep (nprobe values larger than nlist are skipped):
     single-query timing (1 warm-up + 3 runs, median) on the tune split (first TUNE_N tune
     queries) and on the test split, recall@10 on each;
  4. every row is appended to results.csv as soon as it is measured (flushed), so a crash or
     sleep loses at most one point; a restart skips points already in the file (same dataset,
     n_base, index, build params, search param, split, n_queries);
  5. a sweep stops early once test recall >= 0.999 for 2 consecutive points.
Then (and with ``--report-only``) it writes, for every dataset with Part 2 rows:
  results/figures/part2_<dataset>.{png,pdf}, results/tables/part2_qps.{md,tex},
  results/tables/part2_cost.{md,tex}, results/part2_notes.md.

``--estimate`` prints an estimated runtime per dataset / family for this mode without running
the benchmark; it needs the quick-mode results (run ``--quick`` first) for calibration.

Usage:
  python experiments/part2_benchmark.py [--quick] [--only sift[,hnsw]] [--rebuild] [--fresh]
  python experiments/part2_benchmark.py --estimate          # before the full run
  python experiments/part2_benchmark.py [--quick] --report-only
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faiss  # noqa: E402
import h5py  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from annbench import data, frontier, indexes, metrics, plots, results_io, tables, timing  # noqa: E402
from annbench.frontier import FAMILY_LABEL  # noqa: E402

PART = "2"
DATASETS = ["sift", "glove"]


# ---------------------------------------------------------------- grid
def build_grid(cfg: dict, family: str, dataset: str) -> list[dict]:
    b = cfg["GRIDS"][family]["build"]
    if family == "ivfpq":
        b = b[dataset]
    keys = list(b)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(b[k] for k in keys))]


def sweep_values(cfg: dict, family: str, params: dict,
                 dataset: str | None = None) -> tuple[list[int], list[int]]:
    """(values to run, values skipped because nprobe > nlist).

    Includes ``cfg["SWEEP_EXTEND"]`` values for this (dataset, family, build params)."""
    vals = list(cfg["GRIDS"][family]["sweep"])
    for ext in cfg.get("SWEEP_EXTEND", []):
        if (ext["dataset"] == dataset and ext["family"] == family
                and all(params.get(k) == v for k, v in ext["params"].items())):
            vals = sorted(set(vals) | set(ext["values"]))
    if family in ("ivfflat", "ivfpq"):
        return [v for v in vals if v <= params["nlist"]], [v for v in vals if v > params["nlist"]]
    return vals, []


def n_base_of(dataset: str, cfg: dict) -> int:
    if cfg["N_BASE"] is not None:
        return cfg["N_BASE"]
    with h5py.File(config.DATA_DIR / config.DATASETS[dataset]["file"], "r") as f:
        return int(f["train"].shape[0])


def parse_only(only: str | None) -> tuple[list[str], list[str]]:
    datasets, families = list(DATASETS), list(config.PART2_FAMILIES)
    if only:
        parts = [p.strip() for p in only.split(",") if p.strip()]
        if parts[0] not in DATASETS:
            raise SystemExit(f"--only: unknown dataset {parts[0]!r} (expected {DATASETS})")
        datasets = [parts[0]]
        if len(parts) > 1:
            bad = [p for p in parts[1:] if p not in config.PART2_FAMILIES]
            if bad:
                raise SystemExit(f"--only: unknown family {bad} (expected {config.PART2_FAMILIES})")
            families = parts[1:]
    return datasets, families


# ---------------------------------------------------------------- benchmark
def key_for(dataset, n, family, params, value, split, nq) -> tuple:
    return results_io.row_key({"part": PART, "dataset": dataset, "n_base": n, "index": family,
                               "build_params": params, "search_param": value, "split": split,
                               "n_queries": nq})


def run_benchmark(cfg: dict, datasets, families, rebuild: bool, fresh: bool) -> None:
    out_dir = cfg["RESULTS_DIR"]
    csv_path = out_dir / "results.csv"
    K, R, W = cfg["K"], cfg["REPEATS"], cfg["WARMUP"]
    scope = {(d, f) for d in datasets for f in families}
    if fresh and csv_path.exists():
        kept = results_io.prune_part_rows(out_dir, PART,
                                          lambda r: (r["dataset"], r["index"]) not in scope)
        print(f"[part2] --fresh: removed Part 2 rows for {sorted(scope)}; {kept} other Part 2 rows kept")
    existing = {results_io.row_key(r): r for r in results_io.read_rows(csv_path)
                if r["part"] == PART}
    print(f"[part2] {len(existing)} Part 2 rows already in {csv_path}")
    blas = timing.blas_name()
    planned = set()
    t_start = time.perf_counter()

    for name in datasets:
        n = n_base_of(name, cfg)
        xb, xq, *_ = data.load_dataset(name, cfg["N_BASE"])
        _, gt = data.get_ground_truth(name, cfg["N_BASE"], xb=xb, xq=xq)
        tune_q = data.tune_queries(xq, cfg)[:cfg["TUNE_N"]]
        tune_gt = gt[cfg["TUNE"]][:cfg["TUNE_N"]]
        test_q, test_gt = data.test_queries(xq, cfg), gt[cfg["TEST"]]
        splits = [("tune", tune_q, tune_gt), ("test", test_q, test_gt)]
        canary_index = faiss.IndexFlatL2(xb.shape[1])
        canary_index.add(np.ascontiguousarray(xb[:config.CANARY_N_BASE]))
        canary_q = np.ascontiguousarray(tune_q[:config.CANARY_NQ])
        print(f"\n================ {name}: n={n}, tune {len(tune_q)} / test {len(test_q)} queries, "
              f"BLAS {blas}, power plugged in: {timing.power_plugged()}")

        for fam in families:
            for params in build_grid(cfg, fam, name):
                values, skipped = sweep_values(cfg, fam, params, name)
                tag = frontier.describe_config(fam, params, None)
                for v in values:
                    for split, q, _ in splits:
                        planned.add(key_for(name, n, fam, params, v, split, len(q)))
                # what is left to measure? (replay early stopping from rows already present)
                todo, streak = False, 0
                for v in values:
                    if streak >= config.EARLY_STOP_CONSECUTIVE:
                        break
                    keys = {s: key_for(name, n, fam, params, v, s, len(q)) for s, q, _ in splits}
                    if not all(k in existing for k in keys.values()):
                        todo = True
                        break
                    rec = float(existing[keys["test"]]["recall_at_10"])
                    streak = streak + 1 if rec >= config.EARLY_STOP_RECALL else 0
                if not todo:
                    print(f"[skip] {FAMILY_LABEL[fam]} {tag}: all points already measured")
                    continue

                index, meta = indexes.get_index(name, fam, params, xb, rebuild=rebuild)
                if skipped:
                    print(f"[note] {FAMILY_LABEL[fam]} {tag}: skipping nprobe {skipped} > nlist")
                with timing.set_single_thread() as st:
                    canary = timing.time_single_query(canary_index.search, canary_q, K,
                                                      repeats=R, warmup=W)
                    print(f"[canary] {canary['qps_median']:,.0f} QPS (exact, {config.CANARY_NQ} q x "
                          f"{config.CANARY_N_BASE} vectors, pinned cpu {st['pinned_cpu']})")
                    streak = 0
                    for v in values:
                        if streak >= config.EARLY_STOP_CONSECUTIVE:
                            print(f"[stop] {FAMILY_LABEL[fam]} {tag}: test recall >= "
                                  f"{config.EARLY_STOP_RECALL} for {streak} points; "
                                  f"skipping {values[values.index(v):]}")
                            break
                        eff = indexes.set_search_param(index, fam, v)
                        line = []
                        for split, q, g in splits:
                            key = key_for(name, n, fam, params, eff, split, len(q))
                            if key in existing:
                                rec = float(existing[key]["recall_at_10"])
                                line.append(f"{split} {rec:.4f} (done)")
                            else:
                                r = timing.time_single_query(index.search, q, K, repeats=R, warmup=W)
                                rec = metrics.recall_at_k(q, xb, r["ids"], g, K)
                                row = results_io.make_row(
                                    part=PART, dataset=name, n_base=n, index=fam, mode="single",
                                    split=split, k=K, timing=r, recall_at_10=rec,
                                    build_params=params,
                                    search_param_name=indexes.SEARCH_PARAM[fam], search_param=eff,
                                    build_time_s=meta["build_time_s"],
                                    train_time_s=meta["train_time_s"],
                                    build_threads=meta["build_threads"],
                                    index_bytes=meta["index_bytes"],
                                    bytes_per_vector=meta["bytes_per_vector"],
                                    experiment_tag="part2",
                                    extra={"canary_qps": canary["qps_median"],
                                           "train_size": meta["train_size"], "blas": blas,
                                           "power_plugged": timing.power_plugged(),
                                           "index_loaded_from_cache": meta["loaded_from_cache"],
                                           "raw_bytes_per_vector": meta["raw_bytes_per_vector"],
                                           "pq_code_bytes_per_vector":
                                               meta.get("pq_code_bytes_per_vector")})
                                results_io.append_row(out_dir, row)
                                existing[key] = {"recall_at_10": str(rec)}
                                line.append(f"{split} {rec:.4f} {r['qps_median']:,.0f} QPS")
                            if split == "test":
                                streak = streak + 1 if rec >= config.EARLY_STOP_RECALL else 0
                        el = (time.perf_counter() - t_start) / 60
                        print(f"  {FAMILY_LABEL[fam]:8s} {tag:22s} {indexes.SEARCH_PARAM[fam]}={eff:<4d} "
                              f"| {' | '.join(line)}   [{el:.1f} min]", flush=True)
                del index

    # drop Part 2 rows in scope that are not in the current grid; de-duplicate
    def keep(r):
        if (r["dataset"], r["index"]) not in scope:
            return True
        return results_io.row_key(r) in planned
    kept = results_io.prune_part_rows(out_dir, PART, keep)
    print(f"\n[part2] done in {(time.perf_counter() - t_start) / 60:.1f} min; "
          f"{kept} Part 2 rows in {csv_path}")


# ---------------------------------------------------------------- outputs
def _f(x, fmt="{:,.0f}"):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def make_outputs(cfg: dict) -> None:
    out_dir = cfg["RESULTS_DIR"]
    csv_path = out_dir / "results.csv"
    if not csv_path.exists():
        print(f"[part2] no {csv_path}; nothing to report")
        return
    df = pd.read_csv(csv_path)
    fams = list(config.PART2_FAMILIES)
    qps_rows, cost_rows, notes, written = [], [], [], []
    n_tune, n_test = min(cfg["TUNE_N"], len(range(10000)[cfg["TUNE"]])), len(range(10000)[cfg["TEST"]])
    quick_note = (f" Quick mode: first {cfg['N_BASE']:,} base vectors, {n_tune:,} tune / "
                  f"{n_test:,} test queries." if cfg["QUICK"] else "")
    for name in DATASETS:
        n = n_base_of(name, cfg)
        d = df[(df["part"].astype(str) == PART) & (df["dataset"] == name) & (df["n_base"] == n)]
        if d.empty:
            continue
        ex = df[(df["part"].astype(str) == "1") & (df["dataset"] == name) & (df["n_base"] == n)
                & (df["mode"] == "single") & (df["search_threads"] == 1)]
        exact_qps = float(ex.sort_values("timestamp")["qps_median"].iloc[-1]) if len(ex) else None
        test = d[d["split"] == "test"]
        title = f"{'SIFT' if name == 'sift' else 'GloVe-100'} (n = {n:,}): recall vs speed"
        written += plots.recall_qps_plot(test, fams, out_dir / "figures" / f"part2_{name}",
                                         title, exact_qps=exact_qps)
        print(f"\n[report] {name} (n={n}); exact single-query QPS: {_f(exact_qps)}")
        for fam in fams:
            if d[d["index"] == fam].empty:
                continue
            ops = {t: frontier.operating_point(d, fam, t) for t in config.TARGET_RECALLS}
            for op in ops.values():
                print("   " + frontier.format_op(op))
            cells = [name, FAMILY_LABEL[fam]]
            speed = []
            for t, op in ops.items():
                if op["reached"]:
                    cells += [_f(op["test_qps"]), _f(op["test_recall"], "{:.3f}"), op["config"]]
                    speed.append(_f(op["test_qps"] / exact_qps, "{:,.0f}×") if exact_qps else "-")
                else:
                    cells += ["not reached", f"max {op['test_recall']:.3f}", op["config"]]
                    speed.append("-")
            qps_rows.append(cells + [" / ".join(speed)])

            op = ops[0.95]
            row = op["test_row"] or {}
            extra = json.loads(row["extra"]) if row.get("extra") else {}
            cfg_cell = op["config"] if op["reached"] else \
                f"not reached (max recall {op['test_recall']:.3f}): {op['config']}"
            cost_rows.append([name, FAMILY_LABEL[fam], cfg_cell,
                              f"{_f(row.get('build_time_s'), '{:,.1f}')} ({_f(row.get('build_threads'), '{:.0f}')} thr)",
                              _f(row.get("train_time_s"), "{:,.1f}"),
                              _f(row.get("index_bytes", np.nan) / 2**20, "{:,.1f}"),
                              _f(row.get("bytes_per_vector"), "{:,.1f}"),
                              _f(extra.get("raw_bytes_per_vector"), "{:.0f}")])
            if not ops[0.95]["reached"]:
                if fam == "ivfpq":
                    why = ("PQ distances are approximate (quantisation error), so true neighbours "
                           "at similar distances get mis-ordered, and no nprobe can fix that; only "
                           "re-ranking with exact distances can.")
                else:
                    why = ("WARNING: per implementation.md Section 3, extend this sweep rather "
                           "than accept it, and tell Samarth.")
                notes.append(f"- **{name} / {FAMILY_LABEL[fam]}** does not reach 0.95 on the tune "
                             f"queries: max tune recall {op['max_tune_recall']:.4f} at "
                             f"{op['config']} (test recall {op['test_recall']:.4f}). {why}")
        # canary drift across the run
        can = [json.loads(e).get("canary_qps") for e in d["extra"]]
        can = np.array([c for c in can if c is not None], dtype=float)
        if len(can):
            notes.append(f"- Noise canary ({name}): exact {config.CANARY_NQ}-query search QPS "
                         f"min {can.min():,.0f}, median {np.median(can):,.0f}, max {can.max():,.0f} "
                         f"(spread {(can.max() - can.min()) / np.median(can):.1%}) over "
                         f"{d['build_params'].nunique()} build configs.")

    if not qps_rows:
        print("[part2] no Part 2 rows to report")
        return
    below = (" Configs are chosen on the tune queries (recall ≥ target); test recall is reported "
             "as measured and may fall slightly below the target.")
    written += tables.write_table(
        ["Dataset", "Index", "QPS @0.90", "Recall", "Config @0.90", "QPS @0.95", "Recall",
         "Config @0.95", "Speed-up vs exact (0.90 / 0.95)"],
        qps_rows, out_dir / "tables" / "part2_qps",
        "Single-thread, one-query-at-a-time QPS on the test queries (median of 3 runs) at "
        "recall@10 0.90 and 0.95." + below + " 'not reached': no config reached the target on the "
        "tune queries; the highest-recall config is shown with its test recall." + quick_note,
        "tab:part2_qps", align="llrrlrrlr")
    written += tables.write_table(
        ["Dataset", "Index", "Config @0.95", "Build time s (threads)", "Train s", "Size MB",
         "Bytes/vector", "Raw float32 bytes/vector"],
        cost_rows, out_dir / "tables" / "part2_cost",
        "Build cost and memory of the config chosen at recall 0.95 (or the highest-recall config "
        "if 0.95 is not reached). Size = serialised index." + below + quick_note,
        "tab:part2_cost", align="lllrrrrr")
    notes_path = out_dir / "part2_notes.md"
    notes_path.write_text("# Part 2 notes (DRAFT - Samarth to check and rewrite)\n\n"
                          + ("\n".join(notes) if notes else "All indexes reach 0.95.") + "\n",
                          encoding="utf-8")
    written.append(notes_path)
    print("\n[part2] wrote:")
    for p in written:
        print(f"   {p}")


# ---------------------------------------------------------------- runtime estimate
def _lin(x, xs, ys):
    """Linear interpolation, linear extrapolation from the end segments."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    o = np.argsort(xs)
    xs, ys = xs[o], ys[o]
    if len(xs) == 1:
        return float(ys[0])
    if x < xs[0]:
        y = ys[0] + (x - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0])
    elif x > xs[-1]:
        y = ys[-1] + (x - xs[-1]) * (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    else:
        y = float(np.interp(x, xs, ys))
    return max(y, 0.3 * ys.min())


def _first_pair(test_rows: pd.DataFrame) -> float | None:
    """Search param where test recall first reached the early-stop level (quick run)."""
    t = test_rows.sort_values("search_param")
    hit = t[t["recall_at_10"] >= config.EARLY_STOP_RECALL]
    return float(hit["search_param"].iloc[0]) if len(hit) else None


def _points_until_stop(values, first_needed) -> list:
    if first_needed is None:
        return list(values)
    for i, v in enumerate(values):
        if v >= first_needed:
            return list(values[: i + config.EARLY_STOP_CONSECUTIVE])
    return list(values)


def estimate(cfg: dict, datasets, families) -> None:
    qcfg = config.get_config(True)
    qpath = qcfg["RESULTS_DIR"] / "results.csv"
    if not qpath.exists():
        raise SystemExit("--estimate needs quick-mode results: run "
                         "`python experiments/part2_benchmark.py --quick` first")
    qdf = pd.read_csv(qpath)
    qdf = qdf[qdf["part"].astype(str) == PART]
    n_q = qcfg["N_BASE"]
    passes = cfg["WARMUP"] + cfg["REPEATS"]
    nq_point = cfg["TUNE_N"] + len(range(10000)[cfg["TEST"]])
    grand_exp = grand_up = 0.0
    all_points = []
    print(f"[estimate] {'quick' if cfg['QUICK'] else 'full'} mode; {nq_point} queries x "
          f"{passes} passes per sweep point; calibrated from {qpath}")
    print("[estimate] model: IVF latency = c * t_vec * (nlist + n * nprobe / nlist) (IVF-PQ: PQ "
          "scan cost per code fitted linear in m); HNSW latency = quick latency x log(n)/log(n_quick); "
          "build times scaled from quick builds. Early stop predicted from the quick run "
          "(HNSW: 2x the quick efSearch; IVF-Flat: quick nprobe x sqrt(nlist ratio)). Rough.")
    for name in datasets:
        n = n_base_of(name, cfg)
        q = qdf[(qdf["dataset"] == name) & (qdf["n_base"] == n_q) & (qdf["split"] == "test")]
        if q.empty:
            print(f"[estimate] no quick rows for {name}; skipped")
            continue
        # short measurement: exact single-query latency at full n and at quick n
        xb, xq, *_ = data.load_dataset(name, cfg["N_BASE"], verbose=False)
        qs = np.ascontiguousarray(data.tune_queries(xq, cfg)[:20])
        t_vec = {}
        for nn in (n, n_q):
            idx = faiss.IndexFlatL2(xb.shape[1])
            idx.add(np.ascontiguousarray(xb[:nn]))
            with timing.set_single_thread():
                r = timing.time_single_query(idx.search, qs, cfg["K"], repeats=3, warmup=1)
            t_vec[nn] = r["latency_ms_median"] / 1000 / nn
            del idx
        del xb
        print(f"\n================ {name}: n={n:,}; exact single-query {t_vec[n] * n * 1000:.1f} ms "
              f"(n={n:,}), {t_vec[n_q] * n_q * 1000:.2f} ms (n={n_q:,})")
        scale_log = math.log(n) / math.log(n_q)

        for fam in families:
            fq = q[q["index"] == fam].copy()
            if fq.empty:
                print(f"  {FAMILY_LABEL[fam]}: no quick rows; skipped")
                continue
            fq["bp"] = fq["build_params"].map(json.loads)
            fq["lat"] = fq["latency_ms_median"] / 1000
            builds = fq.drop_duplicates("build_params")
            fam_build = fam_exp = fam_up = 0.0
            if fam in ("ivfflat", "ivfpq"):
                fq["nlist"] = fq["bp"].map(lambda b: b["nlist"])
                builds = builds.assign(nlist=builds["bp"].map(lambda b: b["nlist"]),
                                       ts=builds["extra"].map(lambda e: json.loads(e)["train_size"]))
                rate_t = np.median(builds["train_time_s"] / (builds["ts"] * builds["nlist"]))
                rate_a = np.median((builds["build_time_s"] - builds["train_time_s"])
                                   / (n_q * builds["nlist"]))
            if fam == "ivfflat":
                c = np.median(fq["lat"] / (t_vec[n_q] * (fq["nlist"] + n_q * fq["search_param"]
                                                         / fq["nlist"])))
            if fam == "ivfpq":
                fq["m"] = fq["bp"].map(lambda b: b["m"])
                hi = fq[fq["search_param"] >= 16]
                tc = (hi["lat"] - t_vec[n_q] * hi["nlist"]) / (n_q * hi["search_param"] / hi["nlist"])
                per_m = tc.groupby(hi["m"]).median()
                coef = (np.polyfit(per_m.index, per_m.values, 1) if len(per_m) > 1
                        else [per_m.values[0] / per_m.index[0], 0.0])

            for params in build_grid(cfg, fam, name):
                values, _ = sweep_values(cfg, fam, params, name)
                if fam == "hnsw":
                    M = params["M"]
                    qM = sorted(builds["bp"].map(lambda b: b["M"]))
                    lat_at = {}
                    for mq in qM:
                        rows = fq[fq["bp"].map(lambda b: b["M"]) == mq]
                        lat_at[mq] = (rows["search_param"].to_numpy(), rows["lat"].to_numpy())
                    lat = {v: _lin(M, qM, [_lin(v, *lat_at[mq]) for mq in qM]) * scale_log
                           for v in values}
                    bq = builds.assign(M=builds["bp"].map(lambda b: b["M"]))
                    build_s = _lin(M, bq["M"], bq["build_time_s"]) * (n / n_q) * scale_log
                    near = min(qM, key=lambda mq: abs(mq - M))
                    first = _first_pair(fq[fq["bp"].map(lambda b: b["M"]) == near])
                    run_vals = _points_until_stop(values, None if first is None else 2 * first)
                else:
                    nl = params["nlist"]
                    ts = indexes.train_size(fam, n, params)
                    build_s = rate_t * ts * nl + rate_a * n * nl
                    if fam == "ivfflat":
                        lat = {v: c * t_vec[n] * (nl + n * v / nl) for v in values}
                        qnl = min(fq["nlist"].unique(), key=lambda x: abs(math.log(x / nl)))
                        first = _first_pair(fq[fq["nlist"] == qnl])
                        need = None if first is None else first * math.sqrt(nl / qnl)
                        run_vals = _points_until_stop(values, need)
                    else:
                        tcode = max(np.polyval(coef, params["m"]), 0.3 * per_m.min())
                        lat = {v: t_vec[n] * nl + n * v / nl * tcode for v in values}
                        run_vals = list(values)          # plain IVF-PQ rarely reaches 0.999
                pt = {v: nq_point * passes * lat[v] for v in values}
                exp_s = build_s + sum(pt[v] for v in run_vals)
                up_s = build_s + sum(pt.values())
                fam_build += build_s
                fam_exp += exp_s
                fam_up += up_s
                tag = frontier.describe_config(fam, params, None)
                for v in values:
                    all_points.append((pt[v], name, FAMILY_LABEL[fam], tag, v, v in run_vals))
                print(f"  {FAMILY_LABEL[fam]:8s} {tag:22s} build ~{build_s / 60:5.1f} min | sweep "
                      f"expected ~{(exp_s - build_s) / 3600:5.2f} h (stops after "
                      f"{indexes.SEARCH_PARAM[fam]}={run_vals[-1]}), all points "
                      f"~{(up_s - build_s) / 3600:5.2f} h")
            print(f"  -> {FAMILY_LABEL[fam]} total: expected ~{fam_exp / 3600:.2f} h "
                  f"(builds ~{fam_build / 60:.0f} min), upper bound ~{fam_up / 3600:.2f} h")
            grand_exp += fam_exp
            grand_up += fam_up

    print(f"\n[estimate] TOTAL expected ~{grand_exp / 3600:.1f} h, upper bound (no early stop) "
          f"~{grand_up / 3600:.1f} h")
    top = sorted(all_points, reverse=True)[:8]
    print("[estimate] most expensive sweep points (est. time, would run with early stop?):")
    for t, nm, fam, tag, v, run in top:
        print(f"   {t / 60:6.1f} min  {nm:5s} {fam:8s} {tag:22s} value={v:<4d} "
              f"{'runs' if run else 'skipped by early stop'}")
    if grand_exp > config.TIME_BUDGET_HOURS * 3600:
        print(f"[estimate] WARNING: expected total exceeds the {config.TIME_BUDGET_HOURS} h budget")


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="100K base vectors, small grids")
    ap.add_argument("--only", help="dataset[,family,...], e.g. sift or glove,hnsw")
    ap.add_argument("--rebuild", action="store_true", help="rebuild indexes even if cached")
    ap.add_argument("--fresh", action="store_true",
                    help="delete this run's Part 2 rows first (re-time everything in scope)")
    ap.add_argument("--estimate", action="store_true", help="print a runtime estimate and exit")
    ap.add_argument("--report-only", action="store_true",
                    help="only regenerate plots/tables/notes from results.csv")
    args = ap.parse_args()
    cfg = config.get_config(args.quick)
    datasets, families = parse_only(args.only)
    print(f"[part2] mode={'quick' if cfg['QUICK'] else 'full'} datasets={datasets} "
          f"families={families} -> {cfg['RESULTS_DIR']}; git {results_io.git_commit()}")
    if args.estimate:
        estimate(cfg, datasets, families)
        return
    if not args.report_only:
        run_benchmark(cfg, datasets, families, args.rebuild, args.fresh)
    make_outputs(cfg)


if __name__ == "__main__":
    t0 = time.perf_counter()
    main()
    print(f"[part2] total wall time {(time.perf_counter() - t0) / 60:.1f} min")
