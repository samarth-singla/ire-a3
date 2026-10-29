# A3: Benchmarking ANN Search (CS4.406 IRE)

Author: Samarth (roll number 2024101020)

This repository benchmarks exact search and three approximate nearest neighbour (ANN) indexes from
FAISS: HNSW, IVF-Flat and IVF-PQ. It runs on SIFT-1M and GloVe-100, plus two experiments:
- **Part 3:** PQ compression, with and without exact re-ranking.
- **Part 4:** drifting data, on our own seeded data derived from SIFT.

All recall, timing, frontier, plot and table code is our own (`annbench/`). FAISS is used only for
the indexes, and the ann-benchmarks framework is not used.

## Machine and library versions

All reported numbers come from one machine (recorded in `results/env.json` by
`scripts/env_info.py`):

| | |
|---|---|
| CPU | 13th Gen Intel Core i7-13700H: 14 cores (6 performance + 8 efficiency), 20 logical CPUs |
| RAM | 15.75 GB |
| OS | Windows 11 (`Windows-10-10.0.26200`), native, with Git Bash |
| Python | 3.11.17 (conda-forge env `ire-a3`) |
| FAISS | 1.14.3 (faiss-cpu, conda-forge); hnswlib not used |
| numpy / h5py / pandas / matplotlib | 2.4.6 / 3.16.0 / 3.1.0 / 3.11.2 |
| BLAS | OpenBLAS 0.3.34 (pthreads), conda `libblas-3.11.0-*_openblas` |
| threadpoolctl / psutil / pytest | 3.7.0 / 7.2.2 / 9.1.1 |

The laptop was plugged in during all runs. Results are single-thread timings on this machine and
will differ elsewhere.

## Setup

Python 3.11. Both options install the same pinned versions.

**Option A: conda (recommended, especially on Windows)**

```bash
conda env create -f environment.yml
conda activate ire-a3
```

`environment.yml` also pins OpenBLAS (`libblas=*=*openblas`). With conda-forge's default MKL
(2026.2) plus `llvm-openmp` 23.1.4, every large matrix product (numpy or FAISS) crashed the
process with exit code 127.

**Option B: pip (Linux / macOS / Windows)**

```bash
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
```

**Data:** SIFT-1M and GloVe-100 from ann-benchmarks.com, about 1 GB, saved in `data/`. Files that
already exist are skipped. `run_all.sh` runs this step too.

```bash
bash scripts/download_data.sh
```

`run_all.sh` prints which `python` it uses, and stops with a message if `import faiss` fails. On
Windows, check that `which python` points into the `ire-a3` env and not the base Miniforge install.

## How to run

```bash
bash run_all.sh            # full mode  -> results/        about 3.5 h on this laptop
bash run_all.sh --quick    # quick mode -> results_quick/  4 min 13 s measured (cold cache)
bash run_all.sh --resume   # continue an interrupted full run (add --quick for quick mode)
```

`run_all.sh` runs these steps in order. It times each one and writes the times to
`<results dir>/run_times.txt`:

| Step | Script | Full mode (measured) | Quick mode |
|---|---|---|---|
| download | `scripts/download_data.sh` | skipped if present | skipped if present |
| env | `scripts/env_info.py` | seconds | seconds |
| tests | `pytest -q` (15 tests) | seconds | seconds |
| Part 1 | `experiments/part1_exact.py` | ~8 min | 1 min 02 s |
| Part 2 | `experiments/part2_benchmark.py` | ~2.5 h (151.6 min + 5 min GloVe extension) | 1 min 18 s |
| Part 3 | `experiments/part3_experiment.py` | ~27 min (27.3 min) | 20 s |
| Part 4 | `experiments/part4_experiment.py` | ~15 min (14.8 min) | 1 min 10 s |
| Q4 | `experiments/q4_projection.py` | < 1 min | 10 s |
| tables | `experiments/make_tables.py` | seconds | 3 s |

The quick times were measured with `time bash run_all.sh --quick` on 29 Oct 2026, plugged in, with an
empty cache (`ANNBENCH_CACHE_DIR` pointed at a new folder, so every index and ground truth was
rebuilt) and the data already downloaded. Total: **4 min 13 s** (env, tests and download add 10 s),
leaving headroom under the 15-minute limit on slower machines.

Earlier, larger quick grids took 9 min 02 s plugged in and 16 min 52 s on battery on the same laptop.
On a laptop, plug in before timing anything.

The first full run also builds and caches every index in `cache/`, which adds a few minutes per
index (HNSW on 1M vectors takes 1–2.5 min with 20 threads).

### Full and quick mode

- **Full mode** uses all base vectors: SIFT 1,000,000 and GloVe 1,183,514.
  - Tuning uses the first 2,000 of the first 5,000 queries (`TUNE_N`), and every reported number
    uses the last 5,000 queries.
  - Part 3 uses SIFT 1M. Part 4 uses 200K base + 200K added vectors.
- **Quick mode** (`--quick`) uses the first 100,000 base vectors, with ground truth recomputed for
  that subset.
  - It uses smaller grids (`QUICK` in `config.py`), cut for runtime only; the method is the same:
    - Parts 2 and 3 time 500 tune and 500 test queries per point (`TUNE_N`, `TEST_N`).
    - Part 1 times 300 queries one at a time (`EXACT_SINGLE_N`), and its batch uses the
      1,000-query test split.
    - HNSW: M ∈ {16, 32}, efSearch ∈ {16, 32, 64, 128, 256}.
    - IVF-Flat: nlist 1024, nprobe ∈ {1, 4, 16, 64, 256}.
    - IVF-PQ: nlist 256 (16,384 training vectors), m ∈ {16, 32} on SIFT and {20, 50} on GloVe,
      nprobe ∈ {1, 4, 16, 64}.
  - It still runs every part:
    - Part 1, including the agreement check on full-size data for the first 1,000 queries;
    - Part 2;
    - Part 3, with m ∈ {8, 16, 32} at nlist 256, sharing Part 2's quick IVF-PQ indexes;
    - Part 4, with all four shifts on 40K base + 40K added vectors and 1,000 queries (500 tune /
      500 test), nprobe ∈ {1, 4, 16, 64}, efSearch ∈ {16, 32, 64, 128};
    - the Q4 table, with exact search at 150K timed on 300 queries.
  - Quick mode writes only to `results_quick/` and never touches `results/`.
- **Re-timing:** by default Parts 2–4 re-time every point (`--fresh`) and replace only their own
  rows in `results.csv`; the file is never deleted. Parts 1 and Q4 always replace their own rows.
- **Resuming:** with `--resume`, points already in `results.csv` are skipped. Each row is written
  and flushed as soon as it is measured, so an interrupted run loses at most one point.
- **Individual parts** can be run directly. Each script has `--help`, `--quick`, `--report-only`
  (redraw outputs from `results.csv` without timing), and `--rebuild` (rebuild cached indexes).
  Part 2 also has `--only <dataset>[,<family>]` and `--estimate` (runtime estimate).
- **Cache location:** `ANNBENCH_CACHE_DIR=<dir>` moves the index and ground-truth cache. This is
  useful for timing a cold run.

## Repository layout

```
run_all.sh                 one-command reproduction (full / --quick / --resume)
config.py                  paths, seed, query splits, timing settings, all grids, QUICK overrides
annbench/
  data.py                  load hdf5, normalise GloVe, query splits, exact ground truth (cached)
  metrics.py               tie-aware recall@10
  timing.py                single-thread + CPU-pinning context, single-query and batch timing
  indexes.py               FAISS builders (exact, HNSW, IVF-Flat, IVF-PQ, refine), index cache,
                           set_search_param
  sizes.py                 index bytes, bytes per vector
  results_io.py            results.csv schema, append/resume, per-part row replacement
  frontier.py              Pareto frontier, operating-point selection (tune -> test)
  plots.py / tables.py     figures (png + pdf) and tables (md + tex)
  synth.py                 Part 4 seeded drift generator
experiments/
  part1_exact.py           Part 1: agreement check, single vs batch exact search
  part2_benchmark.py       Part 2: HNSW / IVF-Flat / IVF-PQ sweeps on SIFT and GloVe
  part3_experiment.py      Part 3: PQ compression (plain vs exact re-rank)
  part4_experiment.py      Part 4: drift (stale vs rebuilt IVF-Flat and HNSW)
  q4_projection.py         report question 4 (150K measured, 10M projected)
  make_tables.py           regenerate all tables/figures/notes from results.csv
scripts/                   download_data.sh, env_info.py, make_submission.sh
tests/                     test_recall.py (recall@10), test_synth.py (generator determinism)
hypothesis.md              Part 3 and Part 4 hypotheses (committed before the experiments)
results/                   tracked: results.csv, figures/, tables/, notes, env.json
data/, cache/, results_quick/, logs/   not tracked (gitignored)
```

## Recall definition

Tie-aware recall@10 (`annbench/metrics.py`, tests in `tests/test_recall.py`):

> For query q, let d₁₀ be the true squared-L2 distance of the 10th exact neighbour. A returned id
> counts as correct if its true distance to q is ≤ d₁₀·(1+ε) + ε_abs, with ε = 1e-5 and
> ε_abs = 1e-6. Duplicate ids and `-1` padding are ignored. recall@10(q) = min(#correct, 10) / 10,
> and we report the mean over queries.

- **Ties:** a returned point at the same distance as the 10th neighbour counts as correct, even if
  the ground truth lists a different point at that distance.
- **True distances:** each returned id's distance is recomputed from the vectors in float64. The
  distances the index returns are never used, because PQ distances are approximate.
- **Ground truth:** d₁₀ comes from our own exact top-100 (FAISS `IndexFlatL2`, distances recomputed
  in float64), not from the data file. The file's neighbours are used only for the Part 1
  agreement check.
- **GloVe** vectors (base and queries) are L2-normalised. For unit vectors, Euclidean order equals
  angular order, so squared L2 is used everywhere.
- Only the first 10 returned ids count. Returning fewer (e.g. IVF with a tiny `nprobe`) is allowed.

## Timing protocol

All timing code is in `annbench/timing.py`.

- **Single thread.** Every timed search runs inside `timing.set_single_thread()`, which sets 1 FAISS
  OpenMP thread, 1 BLAS thread and `OMP_NUM_THREADS=1`. BLAS threads are limited with
  `threadpoolctl`, because OpenBLAS ignores FAISS's thread setting. The timing functions raise an
  error if called outside this context. The only multi-threaded timing is the Part 1 batch
  reference, which is labelled by `search_threads` in `results.csv`.
- **CPU pinning.** The report machine (i7-13700H) mixes performance and efficiency cores. During
  timed searches the process is pinned to one performance-core logical CPU (`PIN_CPU = 2` in
  `config.py`) via `psutil` CPU affinity, and the previous affinity is restored afterwards, so
  index building still uses all cores. Pinning is skipped on macOS (unsupported) or when
  `PIN_CPU = None`. The pinned CPU is recorded as `pinned_cpu` in the `extra` column of
  `results.csv`.
- **Repeats.** One untimed warm-up pass, then 3 timed passes; we report the median QPS. Each pass
  is timed as a whole with `time.perf_counter()`, with Python's garbage collector paused.
- **One query at a time.** Single-query timing calls `index.search(xq[i:i+1], k)` in a Python loop.
  The loop overhead (a few µs per call) is included and is the same for every index.
- **Query subsets.**
  - Part 1 times exact one-at-a-time search on the first 1,000 test queries (`EXACT_SINGLE_N`),
    because it is slow over 1M vectors. Batch timing uses all 5,000 test queries.
  - Part 2 and Part 3 tune on the first 2,000 tune queries (`TUNE_N`).
  - Part 4 uses its own 2,000 shifted queries: 1,000 tune and 1,000 test.
  - `n_queries` is recorded for every row.
- **Operating points.** For each index and target recall (0.90 / 0.95), the config with the highest
  QPS among those reaching the target on the **tune** split is chosen. That same config's **test**
  recall and QPS are reported as measured, so test recall can fall slightly below the target. If
  no config reaches the target, the tables say "not reached", with the highest recall and its
  config.
- **Early stopping.** A sweep stops once test recall is ≥ 0.999 for two consecutive points.
  `nprobe` values larger than `nlist` are skipped.
- **Noise canary.** Before each build config's sweep, a fixed exact search (200 queries on 20K
  vectors, single thread, pinned) is timed and stored as `canary_qps` in `extra`. This tracks
  drift in machine state during long runs.
- **Building** uses all 20 logical CPUs. The thread count is recorded in `build_threads`.
- **FAISS batch threshold.** FAISS 1.14.3 computes a batch of exact distances with BLAS (a matrix
  product) only when number of queries × dimension ≥ 128,000 (`faiss.cvar.distance_compute_blas_threshold`).
  Below that it uses a per-query SIMD loop, which is about as fast as one-at-a-time search.
  - Full mode: the Part 1 batch has 5,000 queries, so both datasets use BLAS.
  - Quick mode: 1,000 GloVe queries × 100 dims = 100,000 is below the threshold, so the quick
    GloVe batch is no faster than single-query search. SIFT, at 1,000 × 128 = 128,000, just
    reaches it.
  - This also slows the GloVe ground-truth computation, which uses batches of 1,000 queries; the
    results are unaffected.

## Where each figure and table comes from

All are written by the experiment scripts (and again by `experiments/make_tables.py`) from
`results/results.csv`:

| Output | Script | What it shows |
|---|---|---|
| `tables/part1.{md,tex}`, `part1_agreement.json`, `part1_notes.md` | `part1_exact.py` / `make_tables.py` | agreement with the file's neighbours; single vs batch exact QPS |
| `figures/part2_sift`, `figures/part2_glove` (`.png`, `.pdf`) | `part2_benchmark.py` | recall@10 vs QPS, Pareto curve per index, exact baseline |
| `tables/part2_qps.{md,tex}` | `part2_benchmark.py` | QPS at recall 0.90 / 0.95, config, speed-up vs exact |
| `tables/part2_cost.{md,tex}` | `part2_benchmark.py` | build time, size, bytes/vector at the 0.95 config |
| `part2_notes.md` | `part2_benchmark.py` | why IVF-PQ misses 0.95; canary spread |
| `figures/part3`, `tables/part3`, `part3_notes.md` | `part3_experiment.py` | PQ m vs recall/QPS/memory, plain vs re-rank |
| `figures/part4`, `tables/part4`, `part4_notes.md` | `part4_experiment.py` | QPS at 0.95 vs shift, stale vs rebuilt; IVF list diagnostics |
| `tables/q4.{md,tex}`, `q4_notes.md` | `q4_projection.py` | 150K (measured) / 10M (projected) latency, memory, recommendations |
| `env.json`, `run_times.txt` | `env_info.py`, `run_all.sh` | machine, library versions, BLAS; per-step runtimes |

Files named `*_notes.md` are drafts that Samarth rewrites for the report.

## results.csv schema

One row per timed run. `results.csv` is never deleted; each script owns the rows with its `part`
value.

| Column | Meaning |
|---|---|
| `run_id` | random 12-hex id of the row |
| `part` | `1`, `2`, `3`, `4` (report parts) or `10` (Step 10: question 4, exact search at 150K) |
| `dataset` | `sift`, `glove` or `sift_drift` (Part 4) |
| `n_base` | number of vectors in the index |
| `index` | `exact`, `hnsw`, `ivfflat`, `ivfpq`, `ivfpq_refine` |
| `build_params` | JSON, e.g. `{"M": 16, "efConstruction": 200}`, `{"nlist": 4096, "m": 32, "nbits": 8}`; Part 4 adds `variant` (stale/rebuilt), `shift`, `seed` |
| `search_param_name`, `search_param` | `efSearch` or `nprobe` and its value (empty for exact) |
| `split` | `tune` or `test` |
| `n_queries` | number of queries timed |
| `k` | 10 |
| `recall_at_10` | tie-aware recall@10 (mean over the queries) |
| `qps_median`, `qps_runs` | median QPS of the timed runs; JSON list of each run's QPS |
| `latency_ms_median` | mean per-query latency of the median run (= 1000 / `qps_median`) |
| `build_time_s`, `train_time_s`, `build_threads` | measured when the index was built (cached builds keep their original time) |
| `search_threads` | 1 for all single-query timing; 20 for the Part 1 all-threads batch |
| `index_bytes`, `bytes_per_vector` | serialised index size (Part 3 re-rank: including the raw vectors) |
| `mode` | `single` (one query per call) or `batch` |
| `experiment_tag` | `part1_exact`, `part2`, `part3_compression`, `part4_drift`, `q4_exact_150k` |
| `extra` | JSON: always `pinned_cpu`; also e.g. `canary_qps`, `blas`, `power_plugged`, `train_size`, `pq_part_bytes_per_vector`, `ndis_per_query`, IVF list diagnostics, `insert_time_s` |
| `timestamp` | UTC time the row was measured |
| `git_commit` | `git rev-parse --short HEAD`, plus `-dirty` if tracked code (outside `results/`) had uncommitted changes |
