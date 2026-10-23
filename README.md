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

_Single thread, warm-up, median of 3 runs, query subsets (Step 4)._
Timed searches are pinned to one performance-core logical CPU (`PIN_CPU` in `config.py`).

## Where each figure and table comes from

_To fill._

## results.csv schema

_To fill._
