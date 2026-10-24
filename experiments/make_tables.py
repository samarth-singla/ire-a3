"""Regenerate every table (and the Part 2-4 figures and notes) from results.csv, without timing
anything.

  results/tables/part1.{md,tex}        Part 1: agreement check + single vs batch exact search
  results/tables/part2_qps / part2_cost, results/figures/part2_*.{png,pdf}, part2_notes.md
  results/tables/part3, results/figures/part3, part3_notes.md
  results/tables/part4, results/figures/part4, part4_notes.md
  results/tables/q4, q4_notes.md

Usage: python experiments/make_tables.py [--quick]   (quick: results_quick/)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

import pandas as pd  # noqa: E402

import config  # noqa: E402
import part2_benchmark  # noqa: E402
import part3_experiment  # noqa: E402
import part4_experiment  # noqa: E402
import q4_projection  # noqa: E402
from annbench import tables  # noqa: E402


def part1_table(cfg: dict) -> list[Path]:
    out = cfg["RESULTS_DIR"]
    csv_path, agr_path = out / "results.csv", out / "part1_agreement.json"
    if not csv_path.exists():
        return []
    df = pd.read_csv(csv_path)
    df = df[df["part"].astype(str) == "1"]
    if df.empty:
        print("[tables] no Part 1 rows")
        return []
    agr = json.loads(agr_path.read_text()) if agr_path.exists() else {}
    rows = []
    for name in ["sift", "glove"]:
        d = df[df["dataset"] == name].sort_values("timestamp")
        if d.empty:
            continue
        single = d[d["mode"] == "single"].iloc[-1]
        b1 = d[(d["mode"] == "batch") & (d["search_threads"] == 1)].iloc[-1]
        bn = d[(d["mode"] == "batch") & (d["search_threads"] > 1)].iloc[-1]
        a = agr.get(name, {})
        rows.append([name, f"{int(single['n_base']):,}",
                     f"{a['set_match_fraction']:.4f} ({a['n_queries_checked']:,} q)" if a else "-",
                     f"{a['recall_ours_vs_file']:.4f}" if a else "-",
                     f"{single['qps_median']:,.1f} ({single['latency_ms_median']:.1f} ms)",
                     f"{b1['qps_median']:,.0f}", f"{bn['qps_median']:,.0f} ({int(bn['search_threads'])} thr)",
                     f"{b1['qps_median'] / single['qps_median']:.1f}×"])
    n_single = int(df[df["mode"] == "single"]["n_queries"].iloc[-1])
    n_batch = int(df[df["mode"] == "batch"]["n_queries"].iloc[-1])
    return tables.write_table(
        ["Dataset", "n", "Exact top-10 set match", "Tie-aware recall vs file", "Single-query QPS",
         "Batch QPS (1 thread)", "Batch QPS (all threads)", "Batch / single (1 thread)"],
        rows, out / "tables" / "part1",
        f"Exact search (IndexFlatL2). Agreement with the neighbours stored in the data file "
        f"(full-size data). Single-query timing: first {n_single:,} test queries, 1 thread, "
        f"pinned; batch: {n_batch:,} test queries in one call. Median of 3 runs."
        + (f" Quick mode: timing on the first {cfg['N_BASE']:,} base vectors." if cfg["QUICK"] else ""),
        "tab:part1", align="lrrrrrrr")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    cfg = config.get_config(args.quick)
    print(f"[tables] {cfg['RESULTS_DIR']}")
    for p in part1_table(cfg):
        print(f"   {p}")
    print("[tables] Part 2")
    part2_benchmark.make_outputs(cfg)
    print("[tables] Part 3")
    part3_experiment.make_outputs(cfg)
    print("[tables] Part 4")
    part4_experiment.make_outputs(cfg, part4_experiment.settings(cfg, False), cfg["RESULTS_DIR"])
    print("[tables] Q4")
    info = q4_projection.gather(cfg)
    q4_projection.write_outputs(cfg, info, q4_projection.scenarios(info))


if __name__ == "__main__":
    main()
