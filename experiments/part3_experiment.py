"""Part 3: compression experiment on SIFT (IVF-PQ, varying the number of PQ sub-vectors m).

For each m in config.PART3["m"] (nlist fixed, 8-bit codes) two variants are swept over nprobe:
  * ivfpq         plain IVF-PQ (PQ distances only);
  * ivfpq_refine  the SAME trained IVF-PQ wrapped in ``faiss.IndexRefineFlat`` with
                  k_factor = 10: the top 100 PQ candidates are re-ranked with exact distances.
                  The wrapper stores a copy of the raw float32 vectors, so the only difference
                  between the variants is the re-ranking step.
Plain IVF-PQ indexes come from the shared index cache (Part 2 already built m = 16/32/64 at
nlist 4096); the re-rank wrapper is rebuilt each run (a copy of the raw vectors).

Protocol as Part 2: single thread, pinned CPU, 1 warm-up + 3 runs (median), tune split (first
TUNE_N tune queries) and test split, noise canary per (m, variant), every row appended to
results.csv (part=3) as soon as it is measured, restart skips measured points, a sweep stops
early once test recall >= 0.999 for 2 consecutive points.

Memory is recorded both ways for the re-rank variant: ``bytes_per_vector`` is the whole index
with the raw vectors in RAM; ``extra.pq_part_bytes_per_vector`` is the IVF-PQ part alone (what
it would cost if the raw vectors were read from disk; that case is not tested).

Outputs: results/figures/part3.{png,pdf}, results/tables/part3.{md,tex},
results/part3_notes.md (draft verdict on the hypothesis, for Samarth to rewrite).

Usage:
  python experiments/part3_experiment.py [--quick] [--rebuild] [--fresh]
  python experiments/part3_experiment.py --estimate       # full-run runtime estimate
  python experiments/part3_experiment.py [--quick] --report-only
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
from annbench import data, frontier, indexes, metrics, plots, results_io, sizes, tables, timing  # noqa: E402

PART = "3"
VARIANTS = ("ivfpq", "ivfpq_refine")
VARIANT_LABEL = {"ivfpq": "plain IVF-PQ", "ivfpq_refine": "IVF-PQ + re-rank top 100"}
# categorical slots 1-4 (adjacent-pair validated); one colour per m, in order
M_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]


def p3(cfg: dict) -> dict:
    return cfg["PART3"]


def build_params(cfg: dict, m: int, variant: str) -> dict:
    p = {"nlist": p3(cfg)["nlist"], "m": m, "nbits": p3(cfg)["nbits"]}
    if variant == "ivfpq_refine":
        p["k_factor"] = p3(cfg)["refine_k_factor"]
    return p


def sweep(cfg: dict) -> list[int]:
    return [v for v in p3(cfg)["sweep"] if v <= p3(cfg)["nlist"]]


def key_for(dataset, n, variant, params, value, split, nq) -> tuple:
    return results_io.row_key({"part": PART, "dataset": dataset, "n_base": n, "index": variant,
                               "build_params": params, "search_param": value, "split": split,
                               "n_queries": nq})


# ---------------------------------------------------------------- experiment
def run(cfg: dict, rebuild: bool, fresh: bool) -> None:
    P = p3(cfg)
    name, out_dir = P["dataset"], cfg["RESULTS_DIR"]
    csv_path = out_dir / "results.csv"
    K, R, W = cfg["K"], cfg["REPEATS"], cfg["WARMUP"]
    if fresh and csv_path.exists():
        results_io.prune_part_rows(out_dir, PART, lambda r: False)
        print("[part3] --fresh: removed all Part 3 rows")
    existing = {results_io.row_key(r): r for r in results_io.read_rows(csv_path)
                if r["part"] == PART}
    print(f"[part3] {len(existing)} Part 3 rows already in {csv_path}")

    xb, xq, *_ = data.load_dataset(name, P["n_base"])
    n, d = xb.shape
    _, gt = data.get_ground_truth(name, P["n_base"], xb=xb, xq=xq)
    tune_q = data.tune_queries(xq, cfg)[:cfg["TUNE_N"]]
    tune_gt = gt[cfg["TUNE"]][:cfg["TUNE_N"]]
    test_q = data.test_queries(xq, cfg)[:cfg.get("TEST_N")]
    test_gt = gt[cfg["TEST"]][:cfg.get("TEST_N")]
    splits = [("tune", tune_q, tune_gt), ("test", test_q, test_gt)]
    canary_index = faiss.IndexFlatL2(d)
    canary_index.add(np.ascontiguousarray(xb[:config.CANARY_N_BASE]))
    canary_q = np.ascontiguousarray(tune_q[:config.CANARY_NQ])
    blas, values = timing.blas_name(), sweep(cfg)
    planned, t_start = set(), time.perf_counter()
    print(f"[part3] {name} n={n}, nlist={P['nlist']}, m={P['m']}, nprobe sweep {values}; "
          f"tune {len(tune_q)} / test {len(test_q)} queries; BLAS {blas}; "
          f"power plugged in: {timing.power_plugged()}")

    for m in P["m"]:
        todo = {}
        for variant in VARIANTS:
            params = build_params(cfg, m, variant)
            streak, todo[variant] = 0, False
            for v in values:
                for s, q, _ in splits:
                    planned.add(key_for(name, n, variant, params, v, s, len(q)))
            for v in values:                       # replay early stopping from existing rows
                if streak >= config.EARLY_STOP_CONSECUTIVE:
                    break
                keys = {s: key_for(name, n, variant, params, v, s, len(q)) for s, q, _ in splits}
                if not all(k in existing for k in keys.values()):
                    todo[variant] = True
                    break
                rec = float(existing[keys["test"]]["recall_at_10"])
                streak = streak + 1 if rec >= config.EARLY_STOP_RECALL else 0
        if not any(todo.values()):
            print(f"[skip] m={m}: all points already measured")
            continue

        pq_params = {"nlist": P["nlist"], "m": m, "nbits": P["nbits"]}
        plain, meta = indexes.get_index(name, "ivfpq", pq_params, xb, rebuild=rebuild)
        pq_bpv = meta["bytes_per_vector"]
        built = {"ivfpq": (plain, {
            "build_time_s": meta["build_time_s"], "index_bytes": meta["index_bytes"],
            "bytes_per_vector": pq_bpv, "wrap_s": 0.0})}
        if todo["ivfpq_refine"]:
            t0 = time.perf_counter()
            refine = faiss.IndexRefineFlat(plain, faiss.swig_ptr(xb))   # copies the raw vectors
            refine.k_factor = P["refine_k_factor"]
            wrap_s = time.perf_counter() - t0
            ref_bytes = sizes.index_bytes(refine)
            built["ivfpq_refine"] = (refine, {
                "build_time_s": meta["build_time_s"] + wrap_s, "index_bytes": ref_bytes,
                "bytes_per_vector": ref_bytes / n, "wrap_s": wrap_s})
            print(f"[index] re-rank wrapper: {wrap_s:.1f}s, {ref_bytes / 2**20:.1f} MB "
                  f"({ref_bytes / n:.1f} B/vector; PQ part {pq_bpv:.1f} B/vector)")

        for variant in VARIANTS:
            if not todo[variant]:
                print(f"[skip] m={m} {VARIANT_LABEL[variant]}: all points already measured")
                continue
            index, vmeta = built[variant]
            params = build_params(cfg, m, variant)
            with timing.set_single_thread() as st:
                canary = timing.time_single_query(canary_index.search, canary_q, K,
                                                  repeats=R, warmup=W)
                print(f"[canary] {canary['qps_median']:,.0f} QPS (pinned cpu {st['pinned_cpu']})")
                streak = 0
                for v in values:
                    if streak >= config.EARLY_STOP_CONSECUTIVE:
                        print(f"[stop] m={m} {VARIANT_LABEL[variant]}: test recall >= "
                              f"{config.EARLY_STOP_RECALL} for {streak} points; skipping "
                              f"{values[values.index(v):]}")
                        break
                    eff = indexes.set_search_param(index, variant, v)
                    line = []
                    for split, q, g in splits:
                        key = key_for(name, n, variant, params, eff, split, len(q))
                        if key in existing:
                            rec = float(existing[key]["recall_at_10"])
                            line.append(f"{split} {rec:.4f} (done)")
                        else:
                            r = timing.time_single_query(index.search, q, K, repeats=R, warmup=W)
                            rec = metrics.recall_at_k(q, xb, r["ids"], g, K)
                            row = results_io.make_row(
                                part=PART, dataset=name, n_base=n, index=variant, mode="single",
                                split=split, k=K, timing=r, recall_at_10=rec,
                                build_params=params, search_param_name="nprobe",
                                search_param=eff, build_time_s=vmeta["build_time_s"],
                                train_time_s=meta["train_time_s"],
                                build_threads=meta["build_threads"],
                                index_bytes=vmeta["index_bytes"],
                                bytes_per_vector=vmeta["bytes_per_vector"],
                                experiment_tag="part3_compression",
                                extra={"canary_qps": canary["qps_median"], "m": m,
                                       "train_size": meta["train_size"], "blas": blas,
                                       "power_plugged": timing.power_plugged(),
                                       "pq_part_bytes_per_vector": pq_bpv,
                                       "raw_bytes_per_vector": 4 * d,
                                       "pq_code_bytes_per_vector": sizes.pq_code_bytes(m, P["nbits"]),
                                       "refine_wrap_time_s": vmeta["wrap_s"],
                                       "pq_index_loaded_from_cache": meta["loaded_from_cache"]})
                            results_io.append_row(out_dir, row)
                            existing[key] = {"recall_at_10": str(rec)}
                            line.append(f"{split} {rec:.4f} {r['qps_median']:,.0f} QPS")
                        if split == "test":
                            streak = streak + 1 if rec >= config.EARLY_STOP_RECALL else 0
                    el = (time.perf_counter() - t_start) / 60
                    print(f"  m={m:<3d} {VARIANT_LABEL[variant]:25s} nprobe={eff:<4d} | "
                          f"{' | '.join(line)}   [{el:.1f} min]", flush=True)
        del built, plain
        if todo["ivfpq_refine"]:
            del refine

    kept = results_io.prune_part_rows(out_dir, PART, lambda r: results_io.row_key(r) in planned)
    print(f"\n[part3] done in {(time.perf_counter() - t_start) / 60:.1f} min; "
          f"{kept} Part 3 rows in {csv_path}")


# ---------------------------------------------------------------- analysis
def load_rows(cfg: dict) -> pd.DataFrame:
    path = cfg["RESULTS_DIR"] / "results.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    P = p3(cfg)
    n = P["n_base"] or 1_000_000
    df = df[(df["part"].astype(str) == PART) & (df["dataset"] == P["dataset"]) & (df["n_base"] == n)]
    if df.empty:
        return df
    df = df.copy()
    df["ex"] = df["extra"].map(json.loads)
    df["m"] = df["ex"].map(lambda e: e["m"])
    return df


def summarise(df: pd.DataFrame, cfg: dict) -> list[dict]:
    """One dict per (m, variant): max recall, operating points, memory, QPS ratios."""
    out = []
    for m in p3(cfg)["m"]:
        dm = df[df["m"] == m]
        for variant in VARIANTS:
            dv = dm[dm["index"] == variant]
            if dv.empty:
                continue
            ops = {t: frontier.operating_point(dv, variant, t) for t in config.TARGET_RECALLS}
            best = frontier.operating_point(dv, variant, 1.01)    # never reached -> max recall
            ex = dv["ex"].iloc[-1]
            out.append({"m": m, "variant": variant, "ops": ops, "max_test_recall": best["test_recall"],
                        "max_tune_recall": best["max_tune_recall"], "max_config": best["config"],
                        "max_test_recall_any": float(dv[dv["split"] == "test"]["recall_at_10"].max()),
                        "bytes_per_vector": float(dv["bytes_per_vector"].iloc[-1]),
                        "pq_part_bytes_per_vector": ex["pq_part_bytes_per_vector"],
                        "code_bytes": ex["pq_code_bytes_per_vector"],
                        "raw_bytes": ex["raw_bytes_per_vector"]})
    # QPS ratio plain / re-rank at the same nprobe (test split)
    for m in p3(cfg)["m"]:
        t = df[(df["m"] == m) & (df["split"] == "test")]
        a = t[t["index"] == "ivfpq"].set_index("search_param")["qps_median"]
        b = t[t["index"] == "ivfpq_refine"].set_index("search_param")["qps_median"]
        common = a.index.intersection(b.index)
        ratio = (a[common] / b[common]) if len(common) else pd.Series(dtype=float)
        for s in out:
            if s["m"] == m:
                s["qps_ratio_plain_over_refine"] = ratio
    return out


def make_figure(df: pd.DataFrame, summ: list[dict], cfg: dict) -> list[Path]:
    P = p3(cfg)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3), gridspec_kw={"width_ratios": [1.5, 1]})
    for ax in (ax1, ax2):
        plots._style(ax)
    col = {m: M_COLORS[i % len(M_COLORS)] for i, m in enumerate(P["m"])}
    xmin = 1.0
    for m in P["m"]:
        for variant in VARIANTS:
            t = df[(df["m"] == m) & (df["index"] == variant) & (df["split"] == "test")]
            if t.empty:
                continue
            t = t.sort_values("search_param")
            xmin = min(xmin, t["recall_at_10"].min())
            refine = variant == "ivfpq_refine"
            ax1.plot(t["recall_at_10"], t["qps_median"], color=col[m], linewidth=2,
                     linestyle=(0, (4, 2)) if refine else "-", marker="o", markersize=4.5,
                     markerfacecolor="white" if refine else col[m], markeredgecolor=col[m],
                     zorder=3)
            if not refine:
                end = t.iloc[-1]
                ax1.annotate(f"m={m}", (end["recall_at_10"], end["qps_median"]), xytext=(3, -10),
                             textcoords="offset points", fontsize=8, color=plots.INK)
    for tr in config.TARGET_RECALLS:
        ax1.axvline(tr, color=plots.MUTED, linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
        ax1.annotate(f"{tr:.2f}", (tr, 1.0), xycoords=("data", "axes fraction"), xytext=(2, -10),
                     textcoords="offset points", fontsize=7, color=plots.MUTED)
    ax1.set_yscale("log")
    ax1.set_xlim(max(0.0, xmin - 0.02), 1.005)
    ax1.set_xlabel("Recall@10 (test queries)", fontsize=9, color=plots.INK)
    ax1.set_ylabel("Queries per second (1 thread, log scale)", fontsize=9, color=plots.INK)
    ax1.set_title("Recall vs speed, sweeping nprobe", fontsize=10, color=plots.INK, loc="left")
    handles = [Line2D([], [], color=col[m], linewidth=2, label=f"m = {m}") for m in P["m"]]
    handles += [Line2D([], [], color=plots.INK2, linewidth=1.5, marker="o", markersize=4.5,
                       label="plain IVF-PQ"),
                Line2D([], [], color=plots.INK2, linewidth=1.5, linestyle=(0, (4, 2)), marker="o",
                       markersize=4.5, markerfacecolor="white", label="+ exact re-rank of top 100")]
    leg = ax1.legend(handles=handles, fontsize=8, frameon=False, loc="lower left")
    for text in leg.get_texts():
        text.set_color(plots.INK)

    # re-rank points sit close together (all ~raw size, recall near 1): label them to the left,
    # staggered vertically from the highest recall down so labels never overlap
    ref_rank = {id(s): i for i, s in enumerate(sorted(
        [s for s in summ if s["variant"] == "ivfpq_refine"], key=lambda s: -s["max_test_recall_any"]))}
    for s in summ:
        refine = s["variant"] == "ivfpq_refine"
        ax2.scatter([s["bytes_per_vector"]], [s["max_test_recall_any"]], s=40,
                    marker="o", facecolors="white" if refine else col[s["m"]],
                    edgecolors=col[s["m"]], linewidths=1.6, zorder=3)
        if refine:
            off, ha = (-8, 2 - 11 * ref_rank[id(s)]), "right"
        else:
            off, ha = (6, -3), "left"
        ax2.annotate(f"m={s['m']}", (s["bytes_per_vector"], s["max_test_recall_any"]),
                     xytext=off, textcoords="offset points", fontsize=8, color=plots.INK, ha=ha,
                     arrowprops=dict(arrowstyle="-", color=plots.AXIS, lw=0.6) if refine else None)
    raw = summ[0]["raw_bytes"] if summ else 512
    ax2.axvline(raw, color=plots.INK2, linewidth=1.0, linestyle=(0, (4, 2)), zorder=1)
    ax2.annotate(f"raw float32: {raw:.0f} B", (raw, 0.02), xycoords=("data", "axes fraction"),
                 xytext=(-4, 0), textcoords="offset points", fontsize=7, color=plots.INK2,
                 ha="right")
    ax2.axhline(0.95, color=plots.MUTED, linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
    ax2.set_xscale("log", base=2)
    ticks = [8, 16, 32, 64, 128, 256, 512, 1024]
    lo = min(s["bytes_per_vector"] for s in summ) if summ else 16
    hi = max(s["bytes_per_vector"] for s in summ) if summ else 600
    ax2.set_xlim(lo / 1.5, hi * 1.4)
    ax2.set_xticks([t for t in ticks if lo / 1.5 <= t <= hi * 1.4])
    ax2.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax2.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax2.set_xlabel("Index bytes per vector (log scale; re-rank includes raw vectors)", fontsize=9,
                   color=plots.INK)
    ax2.set_ylabel("Max recall@10 reached (test)", fontsize=9, color=plots.INK)
    ax2.set_title("Memory vs best recall (filled: plain, hollow: re-rank)", fontsize=10,
                  color=plots.INK, loc="left")
    n = P["n_base"] or 1_000_000
    fig.suptitle(f"Part 3: PQ compression on SIFT (n = {n:,}, nlist = {P['nlist']}, 8-bit codes)",
                 fontsize=11, color=plots.INK, x=0.01, ha="left", y=0.99)
    fig.tight_layout()
    return plots.save(fig, cfg["RESULTS_DIR"] / "figures" / "part3")


def _op_cell(op: dict) -> str:
    if not op["reached"]:
        return "not reached"
    return f"{op['test_qps']:,.0f} ({op['test_recall']:.3f}, nprobe={int(op['search_param'])})"


def make_table(summ: list[dict], cfg: dict) -> list[Path]:
    rows = []
    for s in summ:
        rows.append([s["m"], VARIANT_LABEL[s["variant"]], f"{s['max_test_recall']:.3f}",
                     _op_cell(s["ops"][0.90]), _op_cell(s["ops"][0.95]),
                     f"{s['bytes_per_vector']:,.1f}", f"{s['pq_part_bytes_per_vector']:,.1f}",
                     f"{s['code_bytes']:.0f}"])
    quick = (f" Quick mode: first {p3(cfg)['n_base']:,} base vectors." if cfg["QUICK"] else "")
    return tables.write_table(
        ["m", "Variant", "Max recall@10", "QPS @0.90 (recall, nprobe)",
         "QPS @0.95 (recall, nprobe)", "Bytes/vector in RAM", "PQ part bytes/vector",
         "PQ code bytes"],
        rows, cfg["RESULTS_DIR"] / "tables" / "part3",
        f"PQ compression on SIFT (nlist {p3(cfg)['nlist']}, 8-bit codes): plain IVF-PQ vs the same "
        "index with exact re-ranking of the top 100 candidates. Single-thread QPS on the test "
        "queries (median of 3 runs). Max recall: test recall of the config with the highest "
        "tune recall. Configs are chosen on the tune queries (recall ≥ target); test recall is "
        "reported as measured and may fall slightly below the target. 'Bytes/vector in RAM' for "
        "re-rank includes the raw float32 vectors; 'PQ part' is the IVF-PQ index alone." + quick,
        "tab:part3", align="rlrrrrrr")


def write_notes(summ: list[dict], cfg: dict) -> Path:
    S = {(s["m"], s["variant"]): s for s in summ}
    ms = [m for m in p3(cfg)["m"] if (m, "ivfpq") in S]

    def mx(m, v="ivfpq"):
        return S[(m, v)]["max_test_recall"] if (m, v) in S else float("nan")

    def yes(cond):
        return "**supported**" if cond else "**not supported**"

    L = ["# Part 3 notes (DRAFT - Samarth to check and rewrite)", "",
         f"Data: `results.csv` part=3 ({'QUICK MODE, ' + format(p3(cfg)['n_base'], ',') + ' vectors' if cfg['QUICK'] else 'full SIFT 1M'}), "
         f"nlist={p3(cfg)['nlist']}. Max recall = test recall of the config with the highest tune "
         "recall. These are automatic checks against the committed hypothesis; the reasoning "
         "is Samarth's.", "",
         "| m | plain max recall | re-rank max recall | plain B/vector | re-rank B/vector (RAM) | "
         "plain/re-rank QPS at same nprobe (median, range) |", "|---|---|---|---|---|---|"]
    for m in ms:
        r = S[(m, "ivfpq")].get("qps_ratio_plain_over_refine", pd.Series(dtype=float))
        rr = (f"{r.median():.2f}x ({r.min():.2f}-{r.max():.2f})" if len(r) else "-")
        L.append(f"| {m} | {mx(m):.3f} | {mx(m, 'ivfpq_refine'):.3f} | "
                 f"{S[(m, 'ivfpq')]['bytes_per_vector']:.1f} | "
                 f"{S[(m, 'ivfpq_refine')]['bytes_per_vector'] if (m, 'ivfpq_refine') in S else float('nan'):.1f} | {rr} |")
    L += ["", "## Prediction by prediction (draft)", ""]
    # P1
    p1 = []
    if 8 in ms:
        p1.append(f"m=8 below 0.60: {mx(8):.3f} -> {yes(mx(8) < 0.60)}")
    if 16 in ms:
        p1.append(f"m=16 below 0.90: {mx(16):.3f} -> {yes(mx(16) < 0.90)}")
    if 64 in ms:
        p1.append(f"only m=64 may come close to 0.95: m=64 reaches {mx(64):.3f}"
                  + (f", m=32 {mx(32):.3f}" if 32 in ms else ""))
    mono = all(mx(a) < mx(b) for a, b in zip(ms, ms[1:]))
    p1.append(f"max recall rises with m: {[round(mx(m), 3) for m in ms]} -> {yes(mono)}")
    L += ["**P1 (plain IVF-PQ recall ceiling)**", ""] + [f"- {x}" for x in p1] + [""]
    # P2
    p2 = []
    for m in ms:
        if (m, "ivfpq_refine") in S:
            reach = S[(m, "ivfpq_refine")]["ops"][0.95]["reached"]
            want = m >= 16
            p2.append(f"m={m}: re-rank max recall {mx(m, 'ivfpq_refine'):.3f}, reaches 0.95 on tune: "
                      f"{'yes' if reach else 'no'} (predicted {'yes' if want else 'maybe not'})"
                      + ("" if m < 16 else f" -> {yes(reach)}"))
    gain = [mx(m, "ivfpq_refine") - mx(m) for m in ms if (m, "ivfpq_refine") in S]
    p2.append(f"recall gain from re-ranking per m: {[round(g, 3) for g in gain]}; refuted if < 0.02 "
              f"everywhere -> {yes(any(g >= 0.02 for g in gain))}")
    L += ["**P2 (re-ranking removes the ceiling)**", ""] + [f"- {x}" for x in p2] + [""]
    # P3
    p3l = []
    worst = 0.0
    for m in ms:
        r = S[(m, "ivfpq")].get("qps_ratio_plain_over_refine", pd.Series(dtype=float))
        if len(r):
            worst = max(worst, r.max())
            p3l.append(f"m={m}: plain/re-rank QPS at same nprobe median {r.median():.2f}x, max {r.max():.2f}x")
    p3l.append(f"drop below 2x at every nprobe (refuted if re-ranking more than halves QPS): "
               f"worst {worst:.2f}x -> {yes(worst < 2.0)}")
    L += ["**P3 (speed)**", ""] + [f"- {x}" for x in p3l] + [""]
    # P4
    p4 = [f"m={m}: plain {S[(m, 'ivfpq')]['bytes_per_vector']:.1f} B/vector (predicted ~{m + 8}); "
          f"re-rank {S[(m, 'ivfpq_refine')]['bytes_per_vector']:.1f} B/vector in RAM "
          f"(predicted ~{m + 8 + S[(m, 'ivfpq')]['raw_bytes']:.0f}), PQ part alone "
          f"{S[(m, 'ivfpq_refine')]['pq_part_bytes_per_vector']:.1f}"
          for m in ms if (m, "ivfpq_refine") in S]
    L += ["**P4 (memory)**", ""] + [f"- {x}" for x in p4] + [
        "- The measured plain size is above m + 8 because of the coarse centroids and PQ codebooks "
        "(and inverted-list overhead); check the gap shrinks relative to n at full size.", "",
        "**Not tested:** re-ranking from raw vectors on disk (memory would stay near the PQ part, "
        "at an I/O cost per query), k_factor other than 10, nbits other than 8, other nlist "
        "values, OPQ / rotations, multi-threaded or batched search.", ""]
    path = cfg["RESULTS_DIR"] / "part3_notes.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def make_outputs(cfg: dict) -> None:
    df = load_rows(cfg)
    if df.empty:
        print("[part3] no Part 3 rows to report")
        return
    summ = summarise(df, cfg)
    for s in summ:
        print(f"   m={s['m']:<3d} {VARIANT_LABEL[s['variant']]:25s} max test recall "
              f"{s['max_test_recall']:.4f} | " + " | ".join(
                  frontier.format_op(op).split(": ", 1)[1] if op["reached"] else f"@{t}: not reached"
                  for t, op in s["ops"].items())
              + f" | {s['bytes_per_vector']:.1f} B/vector")
    written = make_figure(df, summ, cfg) + make_table(summ, cfg) + [write_notes(summ, cfg)]
    print("[part3] wrote:")
    for p in written:
        print(f"   {p}")


# ---------------------------------------------------------------- runtime estimate
def estimate(cfg: dict) -> None:
    """Full-run estimate from measured latencies: Part 2 full rows (plain IVF-PQ at the same
    nlist, m = 16/32/64) and the quick Part 3 run (re-rank overhead, m = 8 vs m = 16)."""
    P, qcfg = p3(cfg), config.get_config(True)
    full = pd.read_csv(cfg["RESULTS_DIR"] / "results.csv")
    p2 = full[(full["part"].astype(str) == "2") & (full["dataset"] == P["dataset"])
              & (full["index"] == "ivfpq")].copy()
    p2["bp"] = p2["build_params"].map(json.loads)
    p2 = p2[p2["bp"].map(lambda b: b["nlist"]) == P["nlist"]]
    p2["m"] = p2["bp"].map(lambda b: b["m"])
    q = load_rows(qcfg)
    if q.empty:
        raise SystemExit("--estimate needs the quick Part 3 results: run with --quick first")
    passes = cfg["WARMUP"] + cfg["REPEATS"]
    nq = {"tune": cfg["TUNE_N"], "test": len(range(10000)[cfg["TEST"]])}
    values = sweep(cfg)

    def quick_lat(m, variant):
        t = q[(q["m"] == m) & (q["index"] == variant) & (q["split"] == "test")]
        return t.set_index("search_param")["latency_ms_median"] / 1000

    total = 0.0
    print(f"[estimate] Part 3 full: {P['dataset']} nlist={P['nlist']}, m={P['m']}, nprobe {values}; "
          f"{nq['tune']}+{nq['test']} queries x {passes} passes per point")
    for m in P["m"]:
        # plain latency per nprobe at full size: Part 2 rows, or m=16 scaled by the quick m ratio
        src = m if m in set(p2["m"]) else 16
        lat = p2[(p2["m"] == src) & (p2["split"] == "test")].set_index("search_param")["latency_ms_median"] / 1000
        if src != m:
            qa, qb = quick_lat(m, "ivfpq"), quick_lat(16, "ivfpq")
            lat = lat * float((qa / qb).median())
        qm = m if m in set(q["m"]) else max(set(q["m"]))
        delta = float((quick_lat(qm, "ivfpq_refine") - quick_lat(qm, "ivfpq")).median())
        plain_s = sum(lat.get(v, lat.iloc[-1]) * (nq["tune"] + nq["test"]) * passes for v in values)
        ref_s = sum((lat.get(v, lat.iloc[-1]) + delta) * (nq["tune"] + nq["test"]) * passes
                    for v in values)
        cached = (config.CACHE_DIR / f"{P['dataset']}_1000000_ivfpq_m{m}_nbits8_nlist{P['nlist']}.index").exists()
        build = 0.0 if cached else float(p2.drop_duplicates("build_params")["build_time_s"].median())
        total += plain_s + ref_s + build
        print(f"  m={m:<3d} plain ~{plain_s / 60:5.1f} min | re-rank ~{ref_s / 60:5.1f} min "
              f"(+{delta * 1e6:.0f} us/query) | build {'cached' if cached else f'~{build / 60:.1f} min'}")
    print(f"[estimate] TOTAL ~{total / 60:.0f} min (upper bound: early stopping not assumed)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="first 100K vectors, nlist 1024, m 8/16/32")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the IVF-PQ indexes")
    ap.add_argument("--fresh", action="store_true", help="delete existing Part 3 rows first")
    ap.add_argument("--estimate", action="store_true", help="print a full-run estimate and exit")
    ap.add_argument("--report-only", action="store_true", help="only regenerate figure/table/notes")
    args = ap.parse_args()
    cfg = config.get_config(args.quick)
    print(f"[part3] mode={'quick' if cfg['QUICK'] else 'full'} -> {cfg['RESULTS_DIR']}; "
          f"git {results_io.git_commit()}")
    if args.estimate:
        estimate(config.get_config(False))
        return
    if not args.report_only:
        run(cfg, args.rebuild, args.fresh)
    make_outputs(cfg)


if __name__ == "__main__":
    t0 = time.perf_counter()
    main()
    print(f"[part3] total wall time {(time.perf_counter() - t0) / 60:.1f} min")
