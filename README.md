# A3: Benchmarking ANN Search (CS4.406 IRE)

Author: Samarth

> Work in progress. Sections below are filled in as the steps in `implementation.md` are done.

## Machine and library versions

_To fill from `results/env.json` (`python scripts/env_info.py`)._

## Setup

Python 3.11. Both options install the same pinned versions.

**Option A: conda (recommended, especially on Windows)**

```bash
conda env create -f environment.yml
conda activate ire-a3
```

**Option B: pip (Linux / macOS / Windows)**

```bash
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
```

Then download the data (SIFT-1M and GloVe-100 into `data/`; existing files are skipped):

```bash
bash scripts/download_data.sh
```

`run_all.sh` prints which `python` it uses and stops with a message if `import faiss` fails.
On Windows, check that `which python` points into the `ire-a3` env, not the base install.

## How to run

_Full and quick mode (`bash run_all.sh [--quick]`), expected runtimes._

## Repository layout

_To fill._

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
  in float64), not from the data file.
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
- **Query subsets.** Exact one-at-a-time search over 1M vectors is slow, so Part 1 times it on the
  first 1,000 test queries (`EXACT_SINGLE_N`). Batch timing uses all 5,000 test queries.
  `n_queries` is recorded for every row.

## Where each figure and table comes from

_To fill._

## results.csv schema

_To fill._
