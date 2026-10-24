"""Part 4: drifting data (our own seeded data derived from SIFT), IVF-Flat vs HNSW.

Question: when vectors added after building come from a shifted distribution, which index
degrades, and does rebuilding fix it?

Data (annbench.synth.make_drift): base = SIFT [0, 200K), added = SIFT [200K, 400K) moved by
shift * R * u, 2,000 SIFT queries moved the same way (first 1,000 tune / last 1,000 test).
shift in {0.0 (control), 0.25, 0.5, 1.0}; only the shift changes between settings. Exact ground
truth (top 100) is recomputed on base + added for every shift.

For each shift, four indexes (built with all cores, cached in cache/):
  IVF-Flat (nlist 1024)  stale:   trained on base only, add(base), then add(added)
                         rebuilt: trained on base + added, add(all)
  HNSW (M 32, efC 200)   stale:   built on base, then add(added) (insertion time recorded)
                         rebuilt: built from scratch on base + added
Each is swept (nprobe / efSearch, as in Part 2) with the Part 2 protocol: single thread, pinned
CPU, 1 warm-up + 3 runs (median), tune and test splits, a noise canary per config (fixed exact
search on unshifted SIFT), rows appended to results.csv (part=4) as measured, resumable, early
stop after 2 consecutive points with test recall >= 0.999.

Diagnostics: IVF list sizes (CV, max/mean, empty lists) and the share of added vectors that
land in the largest 1% of lists; distance computations per query at every sweep point
(faiss indexIVF_stats / hnsw_stats, counted during the timed runs); HNSW insertion time.

Outputs: results/figures/part4.{png,pdf} (one single-panel figure: QPS at recall 0.95 vs
shift), results/tables/part4.{md,tex}, results/part4_notes.md (draft).

Usage:
  python experiments/part4_experiment.py --smoke --out <dir>   # tiny Gaussian fake data
  python experiments/part4_experiment.py [--quick] [--rebuild] [--fresh]
  python experiments/part4_experiment.py --estimate
  python experiments/part4_experiment.py [--quick] --report-only
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faiss  # noqa: E402
import matplotlib  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import config  # noqa: E402
from annbench import data, frontier, indexes, metrics, plots, results_io, synth, tables, timing  # noqa: E402

PART = "4"
DATASET = "sift_drift"
FAMILIES = ("ivfflat", "hnsw")
VARIANTS = ("stale", "rebuilt")
LABEL = {("ivfflat", "stale"): "IVF-Flat stale", ("ivfflat", "rebuilt"): "IVF-Flat rebuilt",
         ("hnsw", "stale"): "HNSW stale", ("hnsw", "rebuilt"): "HNSW rebuilt"}
TARGET = 0.95


# ---------------------------------------------------------------- settings
def settings(cfg: dict, smoke: bool) -> dict:
    P = dict(cfg["PART4"])
    P.setdefault("hnsw_efc", config.HNSW_EF_CONSTRUCTION)
    if smoke:
        P.update(n_base=2000, n_added=2000, n_queries=200, ivf_nlist=32, hnsw_M=16,
                 nprobe_sweep=[1, 4, 16, 32], ef_sweep=[16, 32, 64])
    return P


def build_params(P: dict, fam: str, variant: str, shift: float) -> dict:
    p = {"variant": variant, "shift": shift, "seed": config.SEED}
    if fam == "ivfflat":
        p["nlist"] = P["ivf_nlist"]
    else:
        p.update(M=P["hnsw_M"], efConstruction=P["hnsw_efc"])
    return p


def sweep(P: dict, fam: str) -> list[int]:
    if fam == "ivfflat":
        return [v for v in P["nprobe_sweep"] if v <= P["ivf_nlist"]]
    return list(P["ef_sweep"])


def get_data(P: dict, shift: float, smoke: bool) -> dict:
    if smoke:
        rng = np.random.default_rng(config.SEED)
        d = 16
        base = rng.normal(size=(P["n_base"], d)).astype(np.float32)
        added = rng.normal(size=(P["n_added"], d)).astype(np.float32)
        q = rng.normal(size=(P["n_queries"], d)).astype(np.float32)
        return synth.apply_drift(base, added, q, shift, config.SEED)
    return synth.make_drift(shift, config.SEED, P["n_base"], P["n_added"], P["n_queries"])


def ground_truth(all_vecs, queries, shift, cache_dir: Path):
    n = all_vecs.shape[0]
    path = Path(cache_dir) / f"gt_drift_{n}_s{shift}_seed{config.SEED}.npz"
    if path.exists():
        z = np.load(path)
        if z["ids"].shape[0] == queries.shape[0]:
            return z["ids"], z["dist"]
    ids, dist, _ = data.compute_ground_truth(all_vecs, queries, config.GT_K, verbose=False,
                                             label=f"drift shift={shift}")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, ids=ids, dist=dist)
    return ids, dist


# ---------------------------------------------------------------- builds + diagnostics
def build(fam: str, variant: str, P: dict, base, added):
    """Returns (index, info) with build_time_s (base or all), insert_time_s (stale: adding the
    shifted vectors), train_time_s, train_size, build_threads."""
    d = base.shape[1]
    allv = np.ascontiguousarray(np.vstack([base, added]))
    info = {"insert_time_s": None, "train_time_s": 0.0, "train_size": 0}
    with indexes._build_threads(indexes.n_build_threads()) as nt:
        if fam == "ivfflat":
            nl = P["ivf_nlist"]
            index = faiss.IndexIVFFlat(faiss.IndexFlatL2(d), d, nl)
            index.cp.seed = config.SEED
            src = base if variant == "stale" else allv
            sample = indexes.train_sample(src, indexes.ivf_train_size(src.shape[0], nl))
            t0 = time.perf_counter()
            index.train(sample)
            info["train_time_s"], info["train_size"] = time.perf_counter() - t0, int(sample.shape[0])
            index.add(base if variant == "stale" else allv)
            info["build_time_s"] = time.perf_counter() - t0
        else:
            index = faiss.IndexHNSWFlat(d, P["hnsw_M"])
            index.hnsw.efConstruction = P["hnsw_efc"]
            t0 = time.perf_counter()
            index.add(base if variant == "stale" else allv)
            info["build_time_s"] = time.perf_counter() - t0
        if variant == "stale":
            t0 = time.perf_counter()
            index.add(added)
            info["insert_time_s"] = time.perf_counter() - t0
    info["build_threads"] = nt
    return index, info


def ivf_diagnostics(index, added: np.ndarray) -> dict:
    ivf = faiss.extract_index_ivf(index)
    sizes = np.array([ivf.invlists.list_size(i) for i in range(ivf.nlist)], dtype=np.float64)
    top = np.argsort(-sizes, kind="stable")[: max(1, math.ceil(0.01 * ivf.nlist))]
    with indexes._build_threads(indexes.n_build_threads()):
        _, assign = ivf.quantizer.search(np.ascontiguousarray(added), 1)
    return {"list_cv": float(sizes.std() / sizes.mean()),
            "list_max_over_mean": float(sizes.max() / sizes.mean()),
            "empty_lists": int((sizes == 0).sum()),
            "added_in_top1pct_lists": float(np.isin(assign[:, 0], top).mean()),
            "all_in_top1pct_lists": float(sizes[top].sum() / sizes.sum())}


def get_index(fam, variant, P, shift, base, added, cache_dir: Path, rebuild: bool):
    n = base.shape[0] + added.shape[0]
    stem = f"part4_{n}_s{shift}_seed{config.SEED}_{fam}_{variant}_" + "_".join(
        f"{k}{v}" for k, v in sorted(build_params(P, fam, variant, shift).items())
        if k not in ("variant", "shift", "seed"))
    ipath, jpath = Path(cache_dir) / f"{stem}.index", Path(cache_dir) / f"{stem}.json"
    if not rebuild and ipath.exists() and jpath.exists():
        return faiss.read_index(str(ipath)), json.loads(jpath.read_text()), True
    index, info = build(fam, variant, P, base, added)
    if fam == "ivfflat":
        info.update(ivf_diagnostics(index, added))
    info["index_bytes"] = len(faiss.serialize_index(index))
    ipath.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(ipath))
    jpath.write_text(json.dumps(info, indent=2))
    return index, info, False


def _reset_stats(fam):
    (faiss.cvar.indexIVF_stats if fam == "ivfflat" else faiss.cvar.hnsw_stats).reset()


def _ndis(fam):
    return float((faiss.cvar.indexIVF_stats if fam == "ivfflat" else faiss.cvar.hnsw_stats).ndis)


# ---------------------------------------------------------------- experiment
def key_for(n, fam, params, value, split, nq):
    return results_io.row_key({"part": PART, "dataset": DATASET, "n_base": n, "index": fam,
                               "build_params": params, "search_param": value, "split": split,
                               "n_queries": nq})


def run(cfg: dict, P: dict, out_dir: Path, cache_dir: Path, smoke: bool, rebuild: bool,
        fresh: bool) -> None:
    csv_path = out_dir / "results.csv"
    K, R, W = cfg["K"], cfg["REPEATS"], cfg["WARMUP"]
    if fresh and csv_path.exists():
        results_io.prune_part_rows(out_dir, PART, lambda r: False)
    existing = {results_io.row_key(r): r for r in results_io.read_rows(csv_path)
                if r["part"] == PART}
    print(f"[part4] {len(existing)} Part 4 rows already in {csv_path}")
    # canary: fixed exact search on unshifted data, identical for every config
    if smoke:
        cb = np.random.default_rng(1).normal(size=(2000, 16)).astype(np.float32)
        cq = cb[:50].copy()
    else:
        cb, cxq, *_ = data.load_dataset("sift", config.CANARY_N_BASE, verbose=False)
        cq = np.ascontiguousarray(cxq[:config.CANARY_NQ])
    canary_index = faiss.IndexFlatL2(cb.shape[1])
    canary_index.add(cb)
    blas, planned, t_start = timing.blas_name(), set(), time.perf_counter()
    print(f"[part4] n_base={P['n_base']}, n_added={P['n_added']}, queries={P['n_queries']}, "
          f"shifts={P['shifts']}, IVF nlist={P['ivf_nlist']}, HNSW M={P['hnsw_M']}; BLAS {blas}; "
          f"power plugged in: {timing.power_plugged()}")

    for shift in P["shifts"]:
        D = get_data(P, shift, smoke)
        base, added, queries = D["base"], D["added"], D["queries"]
        allv = np.ascontiguousarray(np.vstack([base, added]))
        n = allv.shape[0]
        _, gt = ground_truth(allv, queries, shift, cache_dir)
        h = queries.shape[0] // 2
        splits = [("tune", queries[:h], gt[:h]), ("test", queries[h:], gt[h:])]
        print(f"\n================ shift={shift}: n={n} (base {base.shape[0]} + added "
              f"{added.shape[0]}), R={D['R']:.1f}, |offset|={np.linalg.norm(D['offset']):.1f}")

        for fam in FAMILIES:
            values = sweep(P, fam)
            pname = indexes.SEARCH_PARAM[fam]
            for variant in VARIANTS:
                params = build_params(P, fam, variant, shift)
                for v in values:
                    for s, q, _ in splits:
                        planned.add(key_for(n, fam, params, v, s, len(q)))
                todo, streak = False, 0
                for v in values:
                    if streak >= config.EARLY_STOP_CONSECUTIVE:
                        break
                    keys = {s: key_for(n, fam, params, v, s, len(q)) for s, q, _ in splits}
                    if not all(k in existing for k in keys.values()):
                        todo = True
                        break
                    rec = float(existing[keys["test"]]["recall_at_10"])
                    streak = streak + 1 if rec >= config.EARLY_STOP_RECALL else 0
                if not todo:
                    print(f"[skip] {LABEL[(fam, variant)]}: all points already measured")
                    continue
                index, info, cached = get_index(fam, variant, P, shift, base, added, cache_dir,
                                                rebuild)
                diag = {k: info.get(k) for k in ("list_cv", "list_max_over_mean", "empty_lists",
                                                 "added_in_top1pct_lists", "all_in_top1pct_lists")
                        if k in info}
                print(f"[index] {LABEL[(fam, variant)]}: {'cached' if cached else 'built'}; build "
                      f"{info['build_time_s']:.1f}s" + (f", insert added {info['insert_time_s']:.1f}s"
                                                         if info["insert_time_s"] is not None else "")
                      + (f"; lists CV {diag['list_cv']:.2f}, max/mean {diag['list_max_over_mean']:.1f}, "
                         f"added in top 1% lists {diag['added_in_top1pct_lists']:.1%}" if diag else ""))
                with timing.set_single_thread() as st:
                    canary = timing.time_single_query(canary_index.search, cq, K, repeats=R, warmup=W)
                    print(f"[canary] {canary['qps_median']:,.0f} QPS (pinned cpu {st['pinned_cpu']})")
                    streak = 0
                    for v in values:
                        if streak >= config.EARLY_STOP_CONSECUTIVE:
                            print(f"[stop] {LABEL[(fam, variant)]}: test recall >= "
                                  f"{config.EARLY_STOP_RECALL} for {streak} points")
                            break
                        eff = indexes.set_search_param(index, fam, v)
                        line = []
                        for split, q, g in splits:
                            key = key_for(n, fam, params, eff, split, len(q))
                            if key in existing:
                                rec = float(existing[key]["recall_at_10"])
                                line.append(f"{split} {rec:.4f} (done)")
                            else:
                                _reset_stats(fam)
                                r = timing.time_single_query(index.search, q, K, repeats=R, warmup=W)
                                ndis = _ndis(fam) / (len(q) * (R + W))
                                rec = metrics.recall_at_k(q, allv, r["ids"], g, K)
                                row = results_io.make_row(
                                    part=PART, dataset=DATASET, n_base=n, index=fam, mode="single",
                                    split=split, k=K, timing=r, recall_at_10=rec,
                                    build_params=params, search_param_name=pname, search_param=eff,
                                    build_time_s=info["build_time_s"],
                                    train_time_s=info["train_time_s"],
                                    build_threads=info["build_threads"],
                                    index_bytes=info["index_bytes"],
                                    bytes_per_vector=info["index_bytes"] / n,
                                    experiment_tag="part4_drift_smoke" if smoke else "part4_drift",
                                    extra={"canary_qps": canary["qps_median"], "shift": shift,
                                           "variant": variant, "ndis_per_query": ndis,
                                           "insert_time_s": info["insert_time_s"],
                                           "train_size": info["train_size"], "R": D["R"],
                                           "n_base_initial": int(base.shape[0]),
                                           "n_added": int(added.shape[0]), "blas": blas,
                                           "power_plugged": timing.power_plugged(),
                                           "index_loaded_from_cache": cached, **diag})
                                results_io.append_row(out_dir, row)
                                existing[key] = {"recall_at_10": str(rec)}
                                line.append(f"{split} {rec:.4f} {r['qps_median']:,.0f} QPS "
                                            f"{ndis:,.0f} dist/q")
                            if split == "test":
                                streak = streak + 1 if rec >= config.EARLY_STOP_RECALL else 0
                        el = (time.perf_counter() - t_start) / 60
                        print(f"  {LABEL[(fam, variant)]:16s} {pname}={eff:<4d} | "
                              f"{' | '.join(line)}   [{el:.1f} min]", flush=True)
                del index

    kept = results_io.prune_part_rows(out_dir, PART, lambda r: results_io.row_key(r) in planned)
    print(f"\n[part4] done in {(time.perf_counter() - t_start) / 60:.1f} min; {kept} Part 4 rows")


# ---------------------------------------------------------------- analysis
def load_rows(out_dir: Path) -> pd.DataFrame:
    path = out_dir / "results.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = df[(df["part"].astype(str) == PART) & (df["dataset"] == DATASET)].copy()
    if df.empty:
        return df
    df["ex"] = df["extra"].map(json.loads)
    df["shift"] = df["ex"].map(lambda e: e["shift"])
    df["variant"] = df["ex"].map(lambda e: e["variant"])
    return df


def summarise(df: pd.DataFrame) -> list[dict]:
    out = []
    for shift in sorted(df["shift"].unique()):
        for fam in FAMILIES:
            for variant in VARIANTS:
                d = df[(df["shift"] == shift) & (df["index"] == fam) & (df["variant"] == variant)]
                if d.empty:
                    continue
                op = frontier.operating_point(d, fam, TARGET)
                best = frontier.operating_point(d, fam, 1.01)
                row = op["test_row"] or best["test_row"] or {}
                ex = json.loads(row["extra"]) if row.get("extra") else {}
                out.append({"shift": shift, "fam": fam, "variant": variant, "op": op,
                            "max_test_recall": best["test_recall"],
                            "qps": op["test_qps"] if op["reached"] else best["test_qps"],
                            "recall": op["test_recall"] if op["reached"] else best["test_recall"],
                            "param": op["search_param"] if op["reached"] else best["search_param"],
                            "reached": op["reached"], "ndis": ex.get("ndis_per_query"),
                            "build_time_s": row.get("build_time_s"),
                            "insert_time_s": ex.get("insert_time_s"), "diag": ex,
                            "n": row.get("n_base")})
    return out


def make_figure(summ: list[dict], out_dir: Path, P: dict) -> list[Path]:
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    plots._style(ax)
    shifts = sorted({s["shift"] for s in summ})
    for fam in FAMILIES:
        for variant in VARIANTS:
            pts = [s for s in summ if s["fam"] == fam and s["variant"] == variant]
            if not pts:
                continue
            col, stale = plots.FAMILY_COLOR[fam], variant == "stale"
            xs, ys = [p["shift"] for p in pts], [p["qps"] for p in pts]
            ax.plot(xs, ys, color=col, linewidth=2, linestyle=(0, (4, 2)) if stale else "-",
                    marker=plots.FAMILY_MARKER[fam], markersize=6,
                    markerfacecolor="white" if stale else col, markeredgecolor=col, zorder=3)
            for p in pts:
                if not p["reached"]:
                    ax.annotate(f"max recall {p['recall']:.2f}", (p["shift"], p["qps"]),
                                xytext=(4, -11), textcoords="offset points", fontsize=7,
                                color=plots.INK2)
            ax.annotate(LABEL[(fam, variant)], (xs[-1], ys[-1]), xytext=(6, -3 if stale else 3),
                        textcoords="offset points", fontsize=8, color=plots.INK, va="center")
    ax.set_yscale("log")

    def _plain(v, _):          # 2,000 / 5,000 / 10,000 instead of 2x10^3 etc.
        lead = int(f"{v:e}"[0])
        return f"{v:,.0f}" if lead in (1, 2, 3, 4, 6, 8) else ""
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_plain))
    ax.yaxis.set_minor_formatter(matplotlib.ticker.FuncFormatter(_plain))
    ax.tick_params(axis="y", which="both", labelsize=8, colors=plots.INK2)
    ax.set_xticks(shifts)
    ax.set_xticklabels([f"{s:g}" + (" (control)" if s == 0 else "") for s in shifts])
    ax.set_xlim(min(shifts) - 0.05, max(shifts) + 0.32)
    ax.set_xlabel("Shift of added vectors and queries (multiples of R)", fontsize=9, color=plots.INK)
    ax.set_ylabel(f"QPS at recall@10 {TARGET:.2f} (test, 1 thread, log)", fontsize=9, color=plots.INK)
    n = P["n_base"] + P["n_added"]
    ax.set_title(f"Part 4: drift, stale vs rebuilt (n = {n:,}: {P['n_base']:,} base + "
                 f"{P['n_added']:,} added)", fontsize=10, color=plots.INK, loc="left")
    handles = [Line2D([], [], color=plots.FAMILY_COLOR[f], linewidth=2, marker=plots.FAMILY_MARKER[f],
                      label=frontier.FAMILY_LABEL[f]) for f in FAMILIES]
    handles += [Line2D([], [], color=plots.INK2, linewidth=1.5, label="rebuilt (solid)"),
                Line2D([], [], color=plots.INK2, linewidth=1.5, linestyle=(0, (4, 2)),
                       marker="o", markerfacecolor="white", label="stale (dashed, hollow)")]
    leg = ax.legend(handles=handles, fontsize=8, frameon=False, loc="best")
    for t in leg.get_texts():
        t.set_color(plots.INK)
    return plots.save(fig, out_dir / "figures" / "part4")


def make_table(summ: list[dict], out_dir: Path, cfg: dict, P: dict) -> list[Path]:
    rows = []
    for s in summ:
        dg = s["diag"]
        qps = (f"{s['qps']:,.0f}" if s["reached"] else f"not reached (max {s['max_test_recall']:.3f})")
        lists = (f"{dg['list_cv']:.2f} / {dg['list_max_over_mean']:.1f} / "
                 f"{dg['added_in_top1pct_lists']:.0%}" if s["fam"] == "ivfflat" else "-")
        t = (f"build {s['build_time_s']:.1f}" + (f", insert {s['insert_time_s']:.1f}"
                                                 if s["insert_time_s"] is not None else ""))
        rows.append([f"{s['shift']:g}", frontier.FAMILY_LABEL[s["fam"]], s["variant"], qps,
                     f"{s['recall']:.3f}", f"{indexes.SEARCH_PARAM[s['fam']]}={int(s['param'])}",
                     f"{s['ndis']:,.0f}" if s["ndis"] is not None else "-", lists, t])
    quick = " Quick mode." if cfg["QUICK"] else ""
    return tables.write_table(
        ["Shift", "Index", "Variant", "QPS @0.95", "Test recall", "Setting",
         "Dist. comps / query", "IVF lists: CV / max÷mean / added in top 1%", "Time s"],
        rows, out_dir / "tables" / "part4",
        f"Drift experiment: {P['n_base']:,} SIFT base vectors plus {P['n_added']:,} added vectors "
        "and the queries shifted by shift × R along a fixed random direction. Stale = trained/built "
        "on the base, then extended; rebuilt = built on base + added. Single-thread QPS on the test "
        "queries at the config chosen on the tune queries for recall ≥ 0.95 (test recall reported "
        "as measured; 'not reached': highest-recall config shown). Distance computations per query "
        "exclude the IVF coarse quantizer (nlist per query)." + quick,
        "tab:part4", align="rllrrlrp{2.8cm}p{2.4cm}")


def write_notes(summ: list[dict], out_dir: Path, cfg: dict, P: dict) -> Path:
    S = {(s["shift"], s["fam"], s["variant"]): s for s in summ}
    shifts = sorted({s["shift"] for s in summ})
    hi = max(shifts)

    def q(sh, f, v):
        return S[(sh, f, v)]["qps"] if (sh, f, v) in S else float("nan")

    def yes(c):
        return "**supported**" if c else "**not supported**"

    L = ["# Part 4 notes (DRAFT - Samarth to check and rewrite)", "",
         f"Data: results.csv part=4 ({'QUICK MODE' if cfg['QUICK'] else 'full'}): "
         f"{P['n_base']:,} SIFT base + {P['n_added']:,} added vectors, {P['n_queries']:,} queries "
         f"(half tune, half test), shifts {[float(x) for x in shifts]}. Numbers are test QPS at the config chosen on "
         "tune for recall 0.95 ('nr' = not reached; the highest-recall config is used).", "",
         "## What changed", "",
         "Only the shift: added vectors and queries are moved by shift x R along one fixed seeded "
         "direction u (R = mean distance of base vectors to their centroid). Shift 0 is the "
         "control. Stale indexes are trained/built on the base and then extended; rebuilt "
         "indexes are built on base + added.", "",
         "## What happened", "",
         "| shift | IVF stale | IVF rebuilt | IVF stale/rebuilt | HNSW stale | HNSW rebuilt | "
         "HNSW stale/rebuilt | IVF stale list CV | added in top 1% lists | IVF dist/query stale vs rebuilt |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for sh in shifts:
        a, b = S.get((sh, "ivfflat", "stale")), S.get((sh, "ivfflat", "rebuilt"))
        c, d = S.get((sh, "hnsw", "stale")), S.get((sh, "hnsw", "rebuilt"))

        def f(x):
            return "-" if x is None else f"{x['qps']:,.0f}{'' if x['reached'] else ' (nr)'}"
        L.append(f"| {sh:g} | {f(a)} | {f(b)} | {q(sh, 'ivfflat', 'stale') / q(sh, 'ivfflat', 'rebuilt'):.2f} | "
                 f"{f(c)} | {f(d)} | {q(sh, 'hnsw', 'stale') / q(sh, 'hnsw', 'rebuilt'):.2f} | "
                 f"{a['diag'].get('list_cv', float('nan')) if a else float('nan'):.2f} | "
                 f"{a['diag'].get('added_in_top1pct_lists', float('nan')) if a else float('nan'):.0%} | "
                 f"{a['ndis'] if a else float('nan'):,.0f} vs {b['ndis'] if b else float('nan'):,.0f} |")
    r0i = q(0.0, "ivfflat", "stale") / q(0.0, "ivfflat", "rebuilt")
    r0h = q(0.0, "hnsw", "stale") / q(0.0, "hnsw", "rebuilt")
    rhi = q(hi, "ivfflat", "stale") / q(hi, "ivfflat", "rebuilt")
    cvs = [S[(sh, "ivfflat", "stale")]["diag"].get("list_cv") for sh in shifts
           if (sh, "ivfflat", "stale") in S]
    reb = [q(sh, "ivfflat", "rebuilt") / q(0.0, "ivfflat", "rebuilt") for sh in shifts]
    hns = [q(sh, "hnsw", "stale") / q(sh, "hnsw", "rebuilt") for sh in shifts]
    hrec = [(S[(sh, "hnsw", "stale")]["recall"], S[(sh, "hnsw", "rebuilt")]["recall"]) for sh in shifts
            if (sh, "hnsw", "stale") in S and (sh, "hnsw", "rebuilt") in S]
    L += ["", "## Prediction by prediction (draft)", "",
          f"- **P1 control** (stale = rebuilt within 10-15% at shift 0): IVF stale/rebuilt "
          f"{r0i:.2f}, HNSW {r0h:.2f} -> {yes(abs(r0i - 1) <= 0.15 and abs(r0h - 1) <= 0.15)}",
          f"- **P2 IVF stale degrades with shift**: list CV {[round(c, 2) for c in cvs]} "
          f"(grows: {yes(all(a <= b for a, b in zip(cvs, cvs[1:])))}); stale/rebuilt QPS at "
          f"shift {hi:g} = {rhi:.2f}, i.e. a {1 / rhi:.1f}x drop (predicted >= 2x) -> {yes(1 / rhi >= 2)}",
          f"- **P3 rebuild restores IVF speed** (within 20% of control): rebuilt QPS / control "
          f"{[round(x, 2) for x in reb]} -> {yes(all(abs(x - 1) <= 0.2 for x in reb))}",
          f"- **P4 HNSW robust** (stale within 20% of rebuilt in QPS and recall): QPS ratios "
          f"{[round(x, 2) for x in hns]}, recall (stale, rebuilt) "
          f"{[(round(a, 3), round(b, 3)) for a, b in hrec]} -> "
          f"{yes(all(abs(x - 1) <= 0.2 for x in hns) and all(abs(a - b) <= 0.2 * b for a, b in hrec))}",
          "", "## Mechanism to check (draft)", "",
          "- IVF: centroids are fixed at training time, so shifted vectors pile into the few cells "
          "nearest the new region (see list CV, max/mean and the share of added vectors in the "
          "top 1% of lists). Shifted queries probe exactly those long lists, so distance "
          "computations per query rise (column 'dist/query') and QPS at a given recall falls.",
          "- HNSW: no trained component; inserted vectors link to their nearest neighbours at "
          "insertion time, so the graph covers the new region. Compare insertion time of the "
          "added vectors with the rebuild time in the table.", "",
          "## Not tested", "",
          "Rotations, deletions, new clusters appearing, IVF-PQ, shifts larger than 1.0 R, drift "
          "in real deployments, other nlist / M values, queries from the old distribution after "
          "drift, multi-threaded or batched search.", ""]
    path = out_dir / "part4_notes.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def make_outputs(cfg: dict, P: dict, out_dir: Path) -> None:
    df = load_rows(out_dir)
    if df.empty:
        print("[part4] no Part 4 rows to report")
        return
    summ = summarise(df)
    for s in summ:
        print(f"   shift={s['shift']:<5g} {LABEL[(s['fam'], s['variant'])]:16s} "
              + (f"QPS@0.95 {s['qps']:,.0f} (test recall {s['recall']:.3f}, "
                 f"{indexes.SEARCH_PARAM[s['fam']]}={int(s['param'])})" if s["reached"]
                 else f"0.95 not reached (max test recall {s['max_test_recall']:.3f})")
              + (f", {s['ndis']:,.0f} dist/q" if s["ndis"] is not None else ""))
    written = make_figure(summ, out_dir, P) + make_table(summ, out_dir, cfg, P) + \
        [write_notes(summ, out_dir, cfg, P)]
    print("[part4] wrote:")
    for p in written:
        print(f"   {p}")


# ---------------------------------------------------------------- runtime estimate
def estimate() -> None:
    """Full-run estimate from the quick run: IVF latency scaled by n (fixed nlist, so each list
    is ~5x longer at 400K than at 80K), HNSW latency by log(n); builds scaled by n (IVF) and
    n log n (HNSW); 2,000 queries x 4 passes per sweep point, early stop as measured in quick."""
    qcfg, fcfg = config.get_config(True), config.get_config(False)
    q = load_rows(qcfg["RESULTS_DIR"])
    if q.empty:
        raise SystemExit("--estimate needs the quick Part 4 results: run with --quick first")
    Pq, Pf = settings(qcfg, False), settings(fcfg, False)
    nq_, nf = Pq["n_base"] + Pq["n_added"], Pf["n_base"] + Pf["n_added"]
    passes = fcfg["WARMUP"] + fcfg["REPEATS"]
    total = 0.0
    print(f"[estimate] Part 4 full: n={nf:,} ({Pf['n_base']:,}+{Pf['n_added']:,}), "
          f"{len(Pf['shifts'])} shifts, {Pf['n_queries']} queries x {passes} passes per point")
    for fam in FAMILIES:
        scale = nf / nq_ if fam == "ivfflat" else math.log(nf) / math.log(nq_)
        bscale = nf / nq_ if fam == "ivfflat" else (nf / nq_) * math.log(nf) / math.log(nq_)
        d = q[q["index"] == fam]
        fam_t = 0.0
        for (shift, variant), g in d.groupby(["shift", "variant"]):
            lat = g.groupby("search_param")["latency_ms_median"].mean() / 1000 * scale
            # full sweeps have more points than quick: interpolate in log(param)
            fv = sweep(Pf, fam)
            lat_f = np.exp(np.interp(np.log(fv), np.log(lat.index.astype(float)), np.log(lat.values)))
            sweep_s = float(lat_f.sum()) * Pf["n_queries"] * passes
            b = g["build_time_s"].iloc[0] * bscale
            ins = (g["ex"].iloc[0].get("insert_time_s") or 0) * bscale
            fam_t += sweep_s + b + ins
        print(f"  {frontier.FAMILY_LABEL[fam]:8s} ~{fam_t / 60:5.1f} min "
              f"(all shifts, stale + rebuilt, no early stop)")
        total += fam_t
    print(f"[estimate] TOTAL ~{total / 60:.0f} min (+ data/ground truth, about 1 min per shift)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="40K base + 40K added")
    ap.add_argument("--smoke", action="store_true", help="tiny Gaussian fake data (needs --out)")
    ap.add_argument("--out", type=Path, help="results directory (default: config RESULTS_DIR)")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    if args.estimate:
        estimate()
        return
    cfg = config.get_config(args.quick)
    if args.smoke and not args.out:
        raise SystemExit("--smoke needs --out <dir> (never mixes fake rows into results/)")
    P = settings(cfg, args.smoke)
    out_dir = args.out or cfg["RESULTS_DIR"]
    cache_dir = (out_dir / "cache") if args.smoke else config.CACHE_DIR
    print(f"[part4] mode={'smoke' if args.smoke else 'quick' if cfg['QUICK'] else 'full'} -> "
          f"{out_dir}; git {results_io.git_commit()}")
    if not args.report_only:
        run(cfg, P, out_dir, cache_dir, args.smoke, args.rebuild, args.fresh)
    make_outputs(cfg, P, out_dir)


if __name__ == "__main__":
    t0 = time.perf_counter()
    main()
    print(f"[part4] total wall time {(time.perf_counter() - t0) / 60:.1f} min")
