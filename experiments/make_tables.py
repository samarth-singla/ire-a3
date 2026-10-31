"""Regenerate every table (and the Part 2-4 figures and notes) from results.csv, without timing
anything.

  results/tables/part1.{md,tex}        Part 1: agreement check + single vs batch exact search
  results/tables/part2_qps / part2_cost, results/figures/part2_*.{png,pdf}, part2_notes.md
  results/tables/part3, results/figures/part3, part3_notes.md
  results/tables/part4, results/figures/part4, part4_notes.md
  results/tables/q4, q4_notes.md
  results/tables/*_compact.{md,tex}    short versions for the 5-page two-column report

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
from annbench import frontier, tables  # noqa: E402


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


# ---------------------------------------------------------------- compact tables (report)
COMPACT = dict(size=r"\footnotesize", placement="!t")
FAM = {"hnsw": "HNSW", "ivfflat": "IVF-Flat", "ivfpq": "IVF-PQ"}
DS = {"sift": "SIFT", "glove": "GloVe"}


def short_config(family: str, build_params, search_param) -> str:
    """Compact config text, e.g. M16/ef64, nl4096/np64, nl4096/m64/np512."""
    bp = json.loads(build_params) if isinstance(build_params, str) else dict(build_params)
    sp = "" if search_param is None or pd.isna(search_param) else int(search_param)
    if family == "hnsw":
        return f"M{bp['M']}/ef{sp}"
    if family == "ivfflat":
        return f"nl{bp['nlist']}/np{sp}"
    return f"nl{bp['nlist']}/m{bp['m']}/np{sp}"


def compact_tables(cfg: dict) -> list[Path]:
    """Short tables for the two-column report, built from the same rows as the full tables."""
    out, written = cfg["RESULTS_DIR"], []
    df = pd.read_csv(out / "results.csv")
    df["part"] = df["part"].astype(str)
    quick = " Quick mode." if cfg["QUICK"] else ""

    # Part 1: exact search, single vs batch (1 thread), agreement
    agr_path = out / "part1_agreement.json"
    agr = json.loads(agr_path.read_text()) if agr_path.exists() else {}
    p1 = df[df["part"] == "1"].sort_values("timestamp")
    rows = []
    for name in ("sift", "glove"):
        d = p1[p1["dataset"] == name]
        if d.empty:
            continue
        single = d[d["mode"] == "single"].iloc[-1]
        b1 = d[(d["mode"] == "batch") & (d["search_threads"] == 1)].iloc[-1]
        a = agr.get(name, {})
        rows.append([DS[name], f"{int(single['n_base']):,}", f"{single['qps_median']:,.1f}",
                     f"{b1['qps_median']:,.0f}", f"{b1['qps_median'] / single['qps_median']:.1f}×",
                     f"{a['set_match_fraction']:.4f}" if a else "-"])
    if rows:
        written += tables.write_table(
            ["Data", "n", "Single QPS", "Batch QPS", "Ratio", "Set match"], rows,
            out / "tables" / "part1_compact",
            "Exact search, 1 thread: one query per call vs one batch call; agreement with the "
            "file's top-10 sets." + quick, "tab:part1c", align="lrrrrr", **COMPACT)

    # Part 2: merged operating points at recall 0.95
    rows = []
    for name in ("sift", "glove"):
        n = part2_benchmark.n_base_of(name, cfg)
        d = df[(df["part"] == "2") & (df["dataset"] == name) & (df["n_base"] == n)]
        for fam in ("hnsw", "ivfflat", "ivfpq"):
            if d[d["index"] == fam].empty:
                continue
            op = frontier.operating_point(d, fam, 0.95)
            if op["reached"]:
                qps, rec = f"{op['test_qps']:,.0f}", f"{op['test_recall']:.3f}"
            else:
                qps, rec = f"not reached (max recall {op['test_recall']:.3f})", "-"
            r = op["test_row"]
            rows.append([DS[name], FAM[fam],
                         short_config(fam, op["build_params"], op["search_param"]), qps, rec,
                         f"{r['build_time_s']:,.1f}", f"{r['index_bytes'] / 2**20:,.1f}",
                         f"{r['bytes_per_vector']:,.1f}"])
    if rows:
        written += tables.write_table(
            ["Data", "Index", "Config", "QPS", "Recall", "Build s", "Size MB", "B/vector"], rows,
            out / "tables" / "part2_compact",
            "Operating points at recall@10 0.95: single-thread test QPS (median of 3), test "
            "recall, build time (20 threads), index size. Config chosen on tune queries; IVF-PQ "
            "shows its highest-recall config." + quick, "tab:part2c", align="lllrrrrr",
            env="table*", **COMPACT)

    # Part 3: re-rank rows + plain max recall
    p3 = part3_experiment.load_rows(cfg)
    if not p3.empty:
        summ = {(s["m"], s["variant"]): s for s in part3_experiment.summarise(p3, cfg)}
        rows = []
        for m in part3_experiment.p3(cfg)["m"]:
            if (m, "ivfpq_refine") not in summ:
                continue
            plain, ref = summ.get((m, "ivfpq")), summ[(m, "ivfpq_refine")]
            op = ref["ops"][0.95]
            qps = (f"{op['test_qps']:,.0f} (np{int(op['search_param'])})" if op["reached"]
                   else "not reached")
            rows.append([m, f"{plain['max_test_recall']:.3f}" if plain else "-",
                         f"{ref['max_test_recall']:.3f}", qps, f"{ref['bytes_per_vector']:,.1f}",
                         f"{ref['pq_part_bytes_per_vector']:,.1f}"])
        written += tables.write_table(
            ["m", "Plain max R", "Re-rank max R", "Re-rank QPS @0.95", "B/vec RAM", "B/vec PQ"],
            rows, out / "tables" / "part3_compact",
            f"SIFT, nlist {part3_experiment.p3(cfg)['nlist']}: best recall of plain IVF-PQ vs "
            "re-ranking the top 100; re-rank memory with raw vectors in RAM, and the PQ part "
            "alone." + quick, "tab:part3c", align="rrrrrr", **COMPACT)

    # Part 4: shifts 0 and 1, stale vs rebuilt
    p4 = part4_experiment.load_rows(cfg["RESULTS_DIR"])
    if not p4.empty:
        rows = []
        for s in part4_experiment.summarise(p4):
            if s["shift"] not in (0.0, 1.0):
                continue
            rows.append([f"{s['shift']:g}", FAM[s["fam"]], s["variant"],
                         f"{s['qps']:,.0f}" if s["reached"] else f"n.r. (max {s['recall']:.3f})",
                         f"{s['recall']:.3f}",
                         f"{s['ndis']:,.0f}" if s["ndis"] is not None else "-",
                         f"{s['diag']['list_cv']:.2f}" if s["fam"] == "ivfflat" else "-"])
        written += tables.write_table(
            ["Shift", "Index", "Variant", "QPS @0.95", "Recall", "Dist./q", "List CV"], rows,
            out / "tables" / "part4_compact",
            "Drift, shift 0 (control) and 1: test QPS and recall at the 0.95 config, distance "
            "computations per query, IVF list-size CV." + quick, "tab:part4c",
            align="rllrrrr", **COMPACT)

    # Q4: four scenarios
    info = q4_projection.gather(cfg)
    rows = []
    for s in q4_projection.scenarios(info):
        tag = "M" if s["exact_src"] == "measured" else "P"
        if s.get("rec_fam"):
            e = info[s["dataset"]][s["rec_fam"]]
            rec = q4_projection.REC_LABEL[s["rec_fam"]] + " " + \
                e["config"].replace("M=", "M").replace(", efSearch=", "/ef")
        else:
            rec = s["rec"][0].split(" (")[0]
        rows.append([DS[s["dataset"]], f"{s['n']:,}", f"{s['exact_ms']:.1f} [{tag}]",
                     f"{q4_projection.gib(s['mem']['hnsw']):.2f}", rec])
    written += tables.write_table(
        ["Data", "n", "Exact ms [M/P]", "HNSW GiB", "Recommendation"], rows,
        out / "tables" / "q4_compact",
        "Q4: exact single-thread latency (M measured, P projected linearly in n), HNSW memory "
        "at the 0.95 config, recommended index (100 ms, 16 GB)." + quick, "tab:q4c",
        align="lrrrl", **COMPACT)
    return written


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
    print("[tables] compact tables (report)")
    for p in compact_tables(cfg):
        print(f"   {p}")


if __name__ == "__main__":
    main()
