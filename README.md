# A3: Benchmarking ANN Search (CS4.406 IRE)

Author: Samarth

> Work in progress. Sections below are filled in as the steps in `implementation.md` are done.

## Machine and library versions

_To fill from `results/env.json` (`python scripts/env_info.py`)._

## Setup

```bash
conda create -n ire-a3 -c conda-forge python=3.11 faiss-cpu numpy h5py pandas matplotlib pytest psutil pypdf
conda activate ire-a3
bash scripts/download_data.sh   # downloads SIFT-1M and GloVe-100 into data/ (skips existing files)
```

## How to run

_Full and quick mode (`bash run_all.sh [--quick]`), expected runtimes._

## Repository layout

_To fill._

## Recall definition

_Tie-aware recall@10 (Step 3)._

## Timing protocol

_Single thread, warm-up, median of 3 runs, query subsets (Step 4)._

## Where each figure and table comes from

_To fill._

## results.csv schema

_To fill._
