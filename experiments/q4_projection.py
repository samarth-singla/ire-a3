"""Report question 4: 150K or 10M vectors, a 100 ms budget per query and 16 GB of RAM.

Measured here (rows part=10 in results.csv):
  * exact single-query search on the first 150,000 base vectors of each dataset, with the
    Part 1/2 protocol (IndexFlatL2, single thread, pinned CPU, 1 warm-up + 3 runs, median),
    on the first EXACT_SINGLE_N test queries, with a noise canary.
Taken from earlier measured results (results.csv):
  * exact single-query latency at full size (Part 1);
  * HNSW / IVF-Flat / IVF-PQ operating points at recall 0.95 (Part 2): latency, bytes/vector,
    build time;
  * IVF-PQ + exact re-rank (Part 3, SIFT only).
Projected / extrapolated here (always labelled):
  * exact latency at 10M: linear in n from the measured full-size latency;
  * memory at 150K and 10M: measured bytes/vector x n;
  * ANN latency at 10M: HNSW x log(10M)/log(n), IVF x 10M/n at fixed nlist (upper bound);
  * HNSW build time at 10M: measured build x (10M/n) x log(10M)/log(n) (optimistic).

Outputs: results/tables/q4.{md,tex}, results/q4_notes.md (draft for Samarth).
Usage: python experiments/q4_projection.py [--quick] [--report-only]
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
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from annbench import data, frontier, metrics, results_io, tables, timing  # noqa: E402

PART = "10"
DATASETS = ["sift", "glove"]
N_SMALL, N_LARGE = 150_000, 10_000_000
BUDGET_MS, RAM_GIB, FIT_GIB = 100.0, 16.0, 12.0     # "fits" = <= 12 GiB (leaves 4 GiB for OS)
GIB = 2 ** 30
REC_LABEL = {"hnsw": "HNSW", "ivfflat": "IVF-Flat", "refine": "IVF-PQ + re-rank"}


# ---------------------------------------------------------------- measurement
def measure(cfg: dict) -> None:
    K, R, W = cfg["K"], cfg["REPEATS"], cfg["WARMUP"]
    rows, blas = [], timing.blas_name()
    for name in DATASETS:
        xb, xq, *_ = data.load_dataset(name, N_SMALL)
        _, gt = data.get_ground_truth(name, N_SMALL, xb=xb, xq=xq)
        nq = cfg["EXACT_SINGLE_N"]
        q, g = data.test_queries(xq, cfg)[:nq], gt[cfg["TEST"]][:nq]
        index = faiss.IndexFlatL2(xb.shape[1])
        index.add(xb)
        canary_index = faiss.IndexFlatL2(xb.shape[1])
        canary_index.add(np.ascontiguousarray(xb[:config.CANARY_N_BASE]))
        cq = np.ascontiguousarray(data.tune_queries(xq, cfg)[:config.CANARY_NQ])
        with timing.set_single_thread() as st:
            canary = timing.time_single_query(canary_index.search, cq, K, repeats=R, warmup=W)
            r = timing.time_single_query(index.search, q, K, repeats=R, warmup=W,
                                         label=f"{name} exact 150K", verbose=True)
        rec = metrics.recall_at_k(q, xb, r["ids"], g, K)
        print(f"[q4] {name}: exact @150K {r['latency_ms_median']:.2f} ms/query "
              f"({r['qps_median']:,.0f} QPS), recall {rec:.4f}, canary "
              f"{canary['qps_median']:,.0f} QPS, pinned cpu {st['pinned_cpu']}")
        rows.append(results_io.make_row(
            part=PART, dataset=name, n_base=N_SMALL, index="exact", mode="single", split="test",
            k=K, timing=r, recall_at_10=rec, build_params={"type": "IndexFlatL2"},
            build_time_s=0.0, train_time_s=0.0, build_threads=1, index_bytes=int(xb.nbytes),
            bytes_per_vector=4 * xb.shape[1], experiment_tag="q4_exact_150k",
            extra={"canary_qps": canary["qps_median"], "blas": blas,
                   "power_plugged": timing.power_plugged(),
                   "query_subset": f"first {nq} test queries"}))
    path = results_io.replace_part_rows(cfg["RESULTS_DIR"], PART, rows)
    print(f"[q4] wrote {len(rows)} rows (part={PART}) -> {path}")


# ---------------------------------------------------------------- inputs from results.csv
def gib(b: float) -> float:
    return b / GIB


def fit_word(b: float) -> str:
    g = gib(b)
    return "fits" if g <= FIT_GIB else ("tight" if g <= RAM_GIB else "no")


def gather(cfg: dict) -> dict:
    df = pd.read_csv(cfg["RESULTS_DIR"] / "results.csv")
    df["part"] = df["part"].astype(str)
    out = {}
    for name in DATASETS:
        d = {"name": name}
        p1 = df[(df["part"] == "1") & (df["dataset"] == name) & (df["mode"] == "single")
                & (df["search_threads"] == 1)]
        if p1.empty:
            raise SystemExit(f"no Part 1 single-query rows for {name}; run part1_exact.py first")
        r1 = p1.sort_values("timestamp").iloc[-1]
        d.update(n_full=int(r1["n_base"]), exact_full_ms=float(r1["latency_ms_median"]))
        p10 = df[(df["part"] == PART) & (df["dataset"] == name)]
        d["exact_150k_ms"] = float(p10.sort_values("timestamp")["latency_ms_median"].iloc[-1]) \
            if len(p10) else None
        dim = config.DATASETS[name]["dim"]
        d["raw_bpv"] = 4 * dim
        p2 = df[(df["part"] == "2") & (df["dataset"] == name) & (df["n_base"] == d["n_full"])]
        for fam in ("hnsw", "ivfflat", "ivfpq"):
            op = frontier.operating_point(p2, fam, 0.95)
            best = op if op["reached"] else frontier.operating_point(p2, fam, 1.01)
            row = best["test_row"] or {}
            d[fam] = {"reached": op["reached"], "config": best["config"],
                      "recall": best["test_recall"], "qps": best["test_qps"],
                      "lat_ms": 1000.0 / best["test_qps"] if best["test_qps"] else None,
                      "bpv": float(row.get("bytes_per_vector", np.nan)),
                      "build_s": float(row.get("build_time_s", np.nan)),
                      "build_threads": row.get("build_threads"), "measured": True}
        # IVF-PQ + exact re-rank: Part 3 (SIFT) -> fastest m that reaches 0.95 on tune
        p3 = df[(df["part"] == "3") & (df["dataset"] == name) & (df["index"] == "ivfpq_refine")]
        best3 = None
        if len(p3):
            p3 = p3.assign(m=p3["extra"].map(lambda e: json.loads(e)["m"]))
            for m, g in p3.groupby("m"):
                op = frontier.operating_point(g, "ivfpq_refine", 0.95)
                if op["reached"] and (best3 is None or op["test_qps"] > best3[0]["test_qps"]):
                    best3 = (op, m)
        if best3:
            op, m = best3
            row = op["test_row"]
            d["refine"] = {"reached": True, "config": op["config"], "recall": op["test_recall"],
                           "qps": op["test_qps"], "lat_ms": 1000.0 / op["test_qps"],
                           "bpv": float(row["bytes_per_vector"]),
                           "build_s": float(row["build_time_s"]), "measured": True}
        else:   # not measured (GloVe): plain IVF-PQ bytes + raw vectors, recall/speed unknown
            d["refine"] = {"reached": None, "config": f"{d['ivfpq']['config']} + re-rank (not measured)",
                           "recall": None, "qps": None, "lat_ms": None,
                           "bpv": d["ivfpq"]["bpv"] + d["raw_bpv"], "build_s": None,
                           "measured": False}
        out[name] = d
    return out


# ---------------------------------------------------------------- scenarios
def scenarios(info: dict) -> list[dict]:
    res = []
    for name, d in info.items():
        n_full, scale_log = d["n_full"], math.log(N_LARGE) / math.log(d["n_full"])
        for n in (N_SMALL, N_LARGE):
            s = {"dataset": name, "n": n}
            if n == N_SMALL and d["exact_150k_ms"] is not None:
                s["exact_ms"], s["exact_src"] = d["exact_150k_ms"], "measured"
            else:
                s["exact_ms"] = d["exact_full_ms"] * n / n_full
                s["exact_src"] = "projected (linear in n)"
            s["mem"] = {"raw": d["raw_bpv"] * n, "hnsw": d["hnsw"]["bpv"] * n,
                        "ivfflat": d["ivfflat"]["bpv"] * n, "ivfpq": d["ivfpq"]["bpv"] * n,
                        "refine": d["refine"]["bpv"] * n}
            # ANN latency at n: measured at full size; 10M extrapolated
            ann = {}
            for fam in ("hnsw", "ivfflat", "refine"):
                e = d[fam]
                if not e.get("reached") or e["lat_ms"] is None:
                    continue
                if n <= n_full:
                    lat, src = e["lat_ms"], f"measured at {n_full:,} (upper bound for {n:,})"
                elif fam == "hnsw":
                    lat, src = e["lat_ms"] * scale_log, "extrapolated (x log n ratio; optimistic)"
                else:
                    lat, src = e["lat_ms"] * n / n_full, "extrapolated (x n ratio, fixed nlist)"
                ann[fam] = {"lat_ms": lat, "src": src, "config": e["config"], "recall": e["recall"],
                            "mem": s["mem"][fam]}
            s["ann"] = ann
            # rule: exact if it meets the budget and fits; otherwise the fastest ANN operating
            # point (recall >= 0.95 on tune) whose latency <= budget and memory "fits"
            exact_ok = s["exact_ms"] <= BUDGET_MS and fit_word(s["mem"]["raw"]) == "fits"
            cands = [(v["lat_ms"], k) for k, v in ann.items()
                     if v["lat_ms"] <= BUDGET_MS and fit_word(v["mem"]) == "fits"]
            s["exact_ok"] = exact_ok
            if exact_ok:
                s["rec"] = ("Exact (IndexFlatL2)", f"{s['exact_ms']:.1f} ms/query, recall 1.0, "
                            f"{gib(s['mem']['raw']):.2f} GiB; ANN not needed for the budget")
            elif cands:
                lat, fam = min(cands)
                v = ann[fam]
                s["rec"] = (REC_LABEL[fam],
                            f"{v['config']}; {v['lat_ms']:.2f} ms/query ({v['src']}); "
                            f"{gib(v['mem']):.1f} GiB")
                s["rec_fam"] = fam
            else:
                s["rec"] = ("none fits", "no measured config meets both limits")
            res.append(s)
    return res


# ---------------------------------------------------------------- outputs
def write_outputs(cfg: dict, info: dict, scen: list[dict]) -> None:
    out = cfg["RESULTS_DIR"]
    rows = []
    for s in scen:
        m = s["mem"]

        def cell(k):
            return f"{gib(m[k]):.2f} ({fit_word(m[k])})"
        tag = "M" if s["exact_src"] == "measured" else "P"
        rows.append([s["dataset"], f"{s['n']:,}", f"{s['exact_ms']:.1f} [{tag}]",
                     "yes" if s["exact_ms"] <= BUDGET_MS else "no",
                     cell("raw"), cell("hnsw"), cell("ivfflat"), cell("ivfpq"), cell("refine"),
                     f"{s['rec'][0]}: {s['rec'][1]}"])
    paths = tables.write_table(
        ["Dataset", "n", "Exact ms/query", "Exact ≤ 100 ms", "Raw GiB", "HNSW GiB",
         "IVF-Flat GiB", "IVF-PQ GiB", "IVF-PQ + re-rank GiB", "Recommendation"],
        rows, out / "tables" / "q4",
        "Question 4: exact single-thread latency ([M] measured, [P] projected linearly in n from "
        "the measured full-size latency) and index memory (measured bytes/vector at the recall-0.95 "
        "config x n; IVF-PQ: highest-recall config, which does not reach 0.95; GloVe re-rank: plain "
        f"IVF-PQ + raw vectors, not measured). 'fits' = at most {FIT_GIB:.0f} GiB, 'tight' = up to "
        f"{RAM_GIB:.0f} GiB, 'no' = more. Recommendation rule: exact if it meets 100 ms and fits; "
        "otherwise the fastest recall-0.95 operating point that meets both (10M latencies are "
        "extrapolated). Single-thread, one query at a time.",
        "tab:q4", align="lrrlllllll")

    L = ["# Question 4 notes (DRAFT - Samarth to rewrite)", "",
         f"Scenarios: 150,000 or 10,000,000 vectors, {BUDGET_MS:.0f} ms per query, {RAM_GIB:.0f} GB "
         f"RAM ('fits' = at most {FIT_GIB:.0f} GiB so the OS and the query process have room).", "",
         "## Measured vs extrapolated", ""]
    for name, d in info.items():
        r150 = d["exact_150k_ms"]
        lin150 = d["exact_full_ms"] * N_SMALL / d["n_full"]
        L += [f"**{name}** (full size n = {d['n_full']:,}, d = {d['raw_bpv'] // 4}):",
              f"- Exact, 1 thread: {d['exact_full_ms']:.1f} ms at {d['n_full']:,} (measured, Part 1); "
              + (f"{r150:.2f} ms at 150K (measured here); the linear model from the full-size number "
                 f"predicts {lin150:.2f} ms at 150K (measured/predicted = {r150 / lin150:.2f})."
                 if r150 else "150K not measured."),
              f"- Exact at 10M: {d['exact_full_ms'] * N_LARGE / d['n_full']:.0f} ms (PROJECTION, "
              "linear in n; a full scan streams all vectors once per query).",
              f"- HNSW @0.95: {d['hnsw']['config']}, {d['hnsw']['lat_ms']:.2f} ms/query, "
              f"{d['hnsw']['bpv']:.0f} B/vector, build {d['hnsw']['build_s']:.0f} s at full size (all measured).",
              f"- IVF-Flat @0.95: {d['ivfflat']['config']}, {d['ivfflat']['lat_ms']:.2f} ms/query, "
              f"{d['ivfflat']['bpv']:.0f} B/vector (measured).",
              f"- IVF-PQ: does not reach 0.95 (max recall {d['ivfpq']['recall']:.3f} at "
              f"{d['ivfpq']['config']}, {d['ivfpq']['bpv']:.0f} B/vector, measured).",
              ("- IVF-PQ + re-rank @0.95: " + (f"{d['refine']['config']}, {d['refine']['lat_ms']:.2f} "
               f"ms/query, {d['refine']['bpv']:.0f} B/vector (measured, Part 3)." if d["refine"]["measured"]
               else f"not measured for {name}; memory estimated as plain IVF-PQ + raw vectors = "
                    f"{d['refine']['bpv']:.0f} B/vector.")), ""]
    L += ["## Scenarios (draft recommendations)", ""]
    for s in scen:
        L.append(f"- **{s['dataset']}, n = {s['n']:,}**: exact {s['exact_ms']:.1f} ms ({s['exact_src']}), "
                 f"raw vectors {gib(s['mem']['raw']):.2f} GiB. -> **{s['rec'][0]}**: {s['rec'][1]}.")
        if s["n"] == N_LARGE and "hnsw" in s["ann"]:
            d = info[s["dataset"]]
            f = (N_LARGE / d["n_full"]) * math.log(N_LARGE) / math.log(d["n_full"])
            peak = gib(s["mem"]["hnsw"] + s["mem"]["raw"])
            L.append(f"  - HNSW build at 10M: ~{d['hnsw']['build_s'] * f / 60:.0f} min with "
                     f"{d['hnsw']['build_threads']:.0f} threads (EXTRAPOLATION: measured "
                     f"{d['hnsw']['build_s']:.0f} s x {f:.1f}). Caveat: real HNSW builds grow faster "
                     "than n log n once the graph no longer fits in cache, and building needs the raw "
                     f"vectors and the index in RAM at the same time (~{peak:.1f} GiB peak), close "
                     "to the 16 GB limit.")
    L += ["", "## Caveats (draft)", "",
          "- All latencies are single-thread, one query at a time. A multi-threaded or batched "
          "exact search could bring 10M exact search under 100 ms on this CPU (Part 1: batching "
          "gave ~10x), which this table does not credit.",
          "- 10M ANN latencies are extrapolated from 1M operating points. Keeping recall 0.95 at "
          "10M needs a larger efSearch / nprobe (recall at a fixed setting drops as n grows), and "
          "IVF should use a larger nlist (about sqrt(n)); both are untested.",
          "- Memory uses bytes/vector measured at full size; fixed costs (centroids, codebooks) are "
          "a slightly larger share at 150K and a smaller one at 10M.",
          "- 10M vectors of this kind are not available here; nothing at 10M was measured.", ""]
    notes = out / "q4_notes.md"
    notes.write_text("\n".join(L), encoding="utf-8")
    print("[q4] wrote:")
    for p in paths + [notes]:
        print(f"   {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="skip the 150K measurement")
    args = ap.parse_args()
    cfg = config.get_config(args.quick)
    print(f"[q4] mode={'quick' if cfg['QUICK'] else 'full'} -> {cfg['RESULTS_DIR']}; "
          f"git {results_io.git_commit()}; BLAS {timing.blas_name()}; "
          f"power plugged in: {timing.power_plugged()}")
    if not args.report_only:
        measure(cfg)
    info = gather(cfg)
    scen = scenarios(info)
    for s in scen:
        print(f"[q4] {s['dataset']:5s} n={s['n']:>10,}: exact {s['exact_ms']:7.1f} ms "
              f"({s['exact_src']}) -> {s['rec'][0]}: {s['rec'][1]}")
    write_outputs(cfg, info, scen)


if __name__ == "__main__":
    t0 = time.perf_counter()
    main()
    print(f"[q4] total wall time {(time.perf_counter() - t0) / 60:.1f} min")
