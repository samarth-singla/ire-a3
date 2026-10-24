"""Part 1: exact baseline (agreement check, single-query vs batch timing).

For each dataset (SIFT, GloVe):
1. Agreement check against the file's ``neighbors``, always on the full-size data (the file's
   ground truth is for the full base set): fraction of queries whose top-10 id sets match
   exactly, tie-aware recall of our exact top-10 with the file as reference, and the reverse.
   Full mode: all 10,000 queries; quick mode: the first ``AGREE_N`` queries.
   -> results/part1_agreement.json
2. Exact search (``faiss.IndexFlatL2``) on the base set (quick mode: first 100K vectors):
   - one query at a time, single thread, pinned: first ``EXACT_SINGLE_N`` test queries;
   - batch: all test queries in one call, single thread (pinned) and all threads.
   Median of ``REPEATS`` runs after one warm-up. Rows replace the part=1 rows of results.csv.
3. Prints the speed-ups and writes a draft explanation to results/part1_notes.md.

Usage: python experiments/part1_exact.py [--quick] [--agree-n N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faiss  # noqa: E402
import numpy as np  # noqa: E402

import config  # noqa: E402
from annbench import data, metrics, results_io, timing  # noqa: E402

DATASETS = ["sift", "glove"]


def agreement_check(name: str, xb, xq, file_ids, file_dist, gt_ids, n_check: int, k: int) -> dict:
    """Compare our exact top-k (full size) with the file's neighbours on the first n_check queries."""
    q = slice(0, n_check)
    ours, theirs = gt_ids[q, :k], file_ids[q, :k]
    set_match = np.array([set(a) == set(b) for a, b in zip(ours.tolist(), theirs.tolist())])

    # true squared-L2 distances (float64, from the vectors) of the file's top-k ids
    file_true = metrics.true_sq_dist(xq[q], xb, theirs)
    file_ref = np.sort(file_true, axis=1)                  # file as the reference: its d10
    rec_ours_vs_file = metrics.recall_per_query(xq[q], xb, ours, file_ref, k)
    ours_true = metrics.true_sq_dist(xq[q], xb, ours)
    rec_file_vs_ours = metrics.recall_per_query(xq[q], xb, theirs, np.sort(ours_true, axis=1), k)

    mism = ~set_match
    tie_only = mism & (rec_ours_vs_file == 1.0) & (rec_file_vs_ours == 1.0)

    # are the file's stored distances consistent with ours? (file metric -> squared L2)
    if name == "sift":
        file_sq = file_dist[q, :k].astype(np.float64) ** 2         # file stores plain L2
        conv = "file L2 distance squared"
    else:
        file_sq = 2.0 * file_dist[q, :k].astype(np.float64)        # unit vectors: 2 (1 - cos)
        conv = "2 x file angular distance (= squared L2 for unit vectors)"
    abs_diff = np.abs(file_sq - file_true)
    rel_diff = abs_diff / np.maximum(file_true, 1e-12)

    examples = []
    for i in np.flatnonzero(mism)[:5]:
        only_ours = sorted(set(ours[i].tolist()) - set(theirs[i].tolist()))
        only_file = sorted(set(theirs[i].tolist()) - set(ours[i].tolist()))
        d_ours = metrics.true_sq_dist(xq[i:i + 1], xb, np.array([only_ours]))[0].tolist()
        d_file = metrics.true_sq_dist(xq[i:i + 1], xb, np.array([only_file]))[0].tolist()
        examples.append({"query": int(i), "only_ours": only_ours, "only_ours_sqdist": d_ours,
                         "only_file": only_file, "only_file_sqdist": d_file,
                         "our_d10": float(np.sort(ours_true[i])[k - 1])})

    return {
        "dataset": name,
        "n_base": int(xb.shape[0]),
        "n_queries_checked": int(n_check),
        "k": k,
        "set_match_fraction": float(set_match.mean()),
        "n_mismatched_queries": int(mism.sum()),
        "n_mismatches_explained_by_ties": int(tie_only.sum()),
        "recall_ours_vs_file": float(rec_ours_vs_file.mean()),
        "recall_file_vs_ours": float(rec_file_vs_ours.mean()),
        "file_distance_check": {"conversion": conv,
                                "max_abs_diff": float(abs_diff.max()),
                                "max_rel_diff": float(rel_diff.max())},
        "mismatch_examples": examples,
        "note": ("Recall is tie-aware (rel 1e-5, abs 1e-6 on squared L2), with true distances "
                 "recomputed from the vectors in float64. 'ours_vs_file' uses the file's 10th "
                 "neighbour distance as d10; 'file_vs_ours' uses ours."
                 + (" GloVe vectors are L2-normalised, so Euclidean order = angular order."
                    if name == "glove" else "")),
    }


def fmt_aff(aff):
    if aff is None:
        return "n/a (cpu_affinity unsupported)"
    return f"{len(aff)} CPUs {aff}" if len(aff) > 4 else str(aff)


def blas_threads() -> list[tuple]:
    return [(lib["internal_api"], lib["num_threads"]) for lib in timing.blas_info()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--agree-n", type=int, default=None,
                    help="queries for the agreement check (default: config AGREE_N)")
    args = ap.parse_args()

    cfg = config.get_config(args.quick)
    K, out_dir = cfg["K"], cfg["RESULTS_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)
    n_agree = args.agree_n or cfg["AGREE_N"]

    blas = timing.blas_name()
    print(f"[part1] mode={'quick' if cfg['QUICK'] else 'full'}  results -> {out_dir}")
    print(f"[part1] BLAS in use: {blas}")
    for lib in timing.blas_info():
        print(f"         {lib['user_api']:6s} {lib['internal_api']:8s} v{lib['version']} "
              f"threads={lib['num_threads']} layer={lib['threading_layer']} ({lib['filepath']})")
    print(f"[part1] PIN_CPU={config.PIN_CPU}  power plugged in: {timing.power_plugged()}  "
          f"git: {results_io.git_commit()}")

    rows, agreements, summary = [], {}, {}
    for name in DATASETS:
        print(f"\n================ {name}")
        # ---- 1. agreement check (always full-size data)
        xb_full, xq, file_ids, file_dist, note = data.load_dataset(name)
        n_check = min(n_agree or xq.shape[0], xq.shape[0])
        if n_check < xq.shape[0] and not data.gt_cache_path(name, xb_full.shape[0]).exists():
            # quick mode, cold cache: exact top-k for the checked queries only (same method)
            gt_full_ids, _, _ = data.compute_ground_truth(xb_full, xq[:n_check], K,
                                                          label=f"{name} (agreement subset)")
        else:
            gt_full_ids, _ = data.get_ground_truth(name, None, xb=xb_full, xq=xq)
        t0 = time.perf_counter()
        agr = agreement_check(name, xb_full, xq, file_ids, file_dist, gt_full_ids, n_check, K)
        agr["metric_note"] = note
        agreements[name] = agr
        print(f"[agree] {name}: {n_check} queries ({time.perf_counter() - t0:.1f}s)\n"
              f"        exact set match: {agr['set_match_fraction']:.4f} "
              f"({agr['n_mismatched_queries']} mismatched, "
              f"{agr['n_mismatches_explained_by_ties']} explained by ties)\n"
              f"        tie-aware recall@10, ours vs file: {agr['recall_ours_vs_file']:.6f}; "
              f"file vs ours: {agr['recall_file_vs_ours']:.6f}\n"
              f"        file distances vs ours ({agr['file_distance_check']['conversion']}): "
              f"max rel diff {agr['file_distance_check']['max_rel_diff']:.2e}")
        for ex in agr["mismatch_examples"]:
            print(f"        mismatch q{ex['query']}: only ours {ex['only_ours']} "
                  f"{np.round(ex['only_ours_sqdist'], 4).tolist()}, only file {ex['only_file']} "
                  f"{np.round(ex['only_file_sqdist'], 4).tolist()}, our d10 {ex['our_d10']:.4f}")

        # ---- 2. exact search timing
        if cfg["N_BASE"] is not None:
            xb = np.ascontiguousarray(xb_full[:cfg["N_BASE"]])
            _, gt_dist = data.get_ground_truth(name, cfg["N_BASE"], xb=xb, xq=xq)
        else:
            xb = xb_full
            _, gt_dist = data.get_ground_truth(name, None, xb=xb, xq=xq)
        n, d = xb.shape
        test_q = data.test_queries(xq, cfg)
        test_gt = gt_dist[cfg["TEST"]]
        n_single = min(cfg["EXACT_SINGLE_N"], test_q.shape[0])

        t0 = time.perf_counter()
        index = faiss.IndexFlatL2(d)
        index.add(xb)
        build_time, build_threads = time.perf_counter() - t0, faiss.omp_get_max_threads()

        common = dict(part=1, dataset=name, n_base=n, index="exact", split="test", k=K,
                      build_params={"type": "IndexFlatL2"}, build_time_s=build_time,
                      train_time_s=0.0, build_threads=build_threads,
                      index_bytes=int(xb.nbytes), bytes_per_vector=4 * d,
                      experiment_tag="part1_exact")
        base_extra = {"blas": blas, "power_plugged": timing.power_plugged(),
                      "warmup": cfg["WARMUP"], "repeats": cfg["REPEATS"],
                      "index_bytes_method": "raw float32 vectors (n*d*4)"}

        print(f"[time] {name}: n={n}, d={d}; single-query on first {n_single} test queries, "
              f"batch on {test_q.shape[0]} test queries; {cfg['WARMUP']} warm-up + "
              f"{cfg['REPEATS']} runs each")
        print(f"[pin ] affinity before: {fmt_aff(timing.current_affinity())}")
        with timing.set_single_thread() as st:
            print(f"[pin ] affinity during (pinned_cpu={st['pinned_cpu']}): "
                  f"{fmt_aff(timing.current_affinity())}; faiss threads "
                  f"{faiss.omp_get_max_threads()}; BLAS/OpenMP threads {blas_threads()}")
            single = timing.time_single_query(index.search, test_q[:n_single], K,
                                              repeats=cfg["REPEATS"], warmup=cfg["WARMUP"],
                                              label="single", verbose=True)
            print(f"[pin ] affinity read right after the timed loop (still in context): "
                  f"{fmt_aff(single['affinity_during'])}")
            batch1 = timing.time_batch(index.search, test_q, K, repeats=cfg["REPEATS"],
                                       warmup=cfg["WARMUP"], label="batch 1 thread",
                                       verbose=True)
        print(f"[pin ] affinity after: {fmt_aff(timing.current_affinity())}; "
              f"BLAS/OpenMP threads {blas_threads()}")
        with timing.all_threads() as at:
            print(f"[time] all-threads context: {at['search_threads']} threads, "
                  f"BLAS/OpenMP {blas_threads()}")
            batchN = timing.time_batch(index.search, test_q, K, repeats=cfg["REPEATS"],
                                       warmup=cfg["WARMUP"], label=f"batch {at['search_threads']} threads",
                                       verbose=True)

        res = {}
        for label, r, nq_sub, mode in [("single", single, n_single, "single"),
                                       ("batch_1t", batch1, test_q.shape[0], "batch"),
                                       ("batch_all", batchN, test_q.shape[0], "batch")]:
            rec = metrics.recall_at_k(test_q[:nq_sub], xb, r["ids"], test_gt[:nq_sub], K)
            res[label] = {"qps": r["qps_median"], "latency_ms": r["latency_ms_median"],
                          "recall": rec, "threads": r["search_threads"], "n_queries": nq_sub}
            subset = (f"first {nq_sub} test queries" if label == "single"
                      else f"all {nq_sub} test queries")
            rows.append(results_io.make_row(
                mode=mode, timing=r, recall_at_10=rec,
                extra={**base_extra, "query_subset": subset,
                       "blas_threads": r["search_threads"]},
                **common))
        summary[name] = res

        s, b1, bN = res["single"]["qps"], res["batch_1t"]["qps"], res["batch_all"]["qps"]
        print(f"[res ] {name}: single {s:,.1f} QPS ({res['single']['latency_ms']:.2f} ms/query), "
              f"batch 1 thread {b1:,.1f} QPS, batch {res['batch_all']['threads']} threads "
              f"{bN:,.1f} QPS")
        print(f"[res ] {name}: speed-up batch(1 thread)/single = {b1 / s:.1f}x, "
              f"batch(all threads)/single = {bN / s:.1f}x; recall@10 "
              f"{res['single']['recall']:.4f}/{res['batch_1t']['recall']:.4f}/"
              f"{res['batch_all']['recall']:.4f}")
        del index, xb, xb_full       # free ~0.5 GB before the next dataset

    # ---- outputs
    (out_dir / "part1_agreement.json").write_text(json.dumps(agreements, indent=2))
    path = results_io.replace_part_rows(out_dir, 1, rows)
    write_notes(out_dir / "part1_notes.md", summary, cfg)
    print(f"\n[part1] wrote {len(rows)} rows (part=1) -> {path}")
    print(f"[part1] wrote {out_dir / 'part1_agreement.json'} and {out_dir / 'part1_notes.md'}")


def write_notes(path: Path, summary: dict, cfg: dict) -> None:
    lines = ["# Part 1 notes (DRAFT - Samarth to check and rewrite)", "",
             "Exact search (`IndexFlatL2`), measured by `experiments/part1_exact.py`; numbers "
             "from this run (also in `results.csv`, part=1).", "",
             "| dataset | single-query QPS (1 thread) | batch QPS (1 thread) | batch QPS (all threads) "
             "| batch(1t) / single | batch(all) / single |",
             "|---|---|---|---|---|---|"]
    for name, r in summary.items():
        s, b1, bN = r["single"]["qps"], r["batch_1t"]["qps"], r["batch_all"]["qps"]
        lines.append(f"| {name} | {s:,.1f} | {b1:,.1f} | {bN:,.1f} ({r['batch_all']['threads']} "
                     f"threads) | {b1 / s:.1f}x | {bN / s:.1f}x |")
    n_single = next(iter(summary.values()))["single"]["n_queries"]
    n_batch = next(iter(summary.values()))["batch_1t"]["n_queries"]
    lines += ["",
              f"Single-query timing uses the first {n_single} test queries; batch timing uses "
              f"all {n_batch} test queries.", "",
              "## Why batch is so much faster (draft, two sentences)", "",
              "Batched search turns the distance computation into one matrix-matrix product "
              "(BLAS GEMM), which loads each base vector from memory once and reuses it for "
              "many queries while it is in cache, and makes full use of SIMD and cache "
              "blocking. One-at-a-time search is a matrix-vector product that is limited by "
              "memory bandwidth, because it streams all base vectors from RAM again for every "
              "query, and it also pays the Python and FAISS per-call overhead for each query.",
              ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
