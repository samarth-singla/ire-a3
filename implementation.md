# implementation.md — A3: Benchmarking ANN Search (CS4.406 IRE)

Author of the assignment: **Samarth** (roll number: `2024101020`).
This file is the instruction set for Claude Code. Read the whole file before doing anything, then work **one step at a time**.

---

## 0. Ground rules for Claude (read first, obey always)

1. **Never change git state.** Do NOT run `git add`, `git commit`, `git push`, `git reset`, `git stash`, `git checkout`, `git rebase`, `git rm`, or anything that edits history or the index. Samarth makes every commit by hand.
   Read-only git is allowed: `git status`, `git log`, `git diff`, `git show`.
2. **Stop at every `⛔ STOP` marker.** Print a short summary of what you did, list the files changed, suggest a commit message, and wait. Do not start the next step until Samarth says so.
3. **Hypotheses before results (graded).** Never run any Part 3 or Part 4 experiment script — not even in `--quick` mode, not even "just to test" — until you have verified with `git log -p -- hypothesis.md` that the relevant hypothesis section is already committed. If it is not, stop and say so. You may write and unit-test the code on tiny fake data (e.g. 2,000 random vectors), but you must not produce any result on real or Part-4 data.
4. **Libraries:** FAISS (and optionally hnswlib) for the indexes only. Recall, timing, frontier, tables and plots are our own code. Never import or call the `ann-benchmarks` framework. Never hard-code numbers from papers.
5. **Name:** the author is Samarth. Use "Samarth" anywhere a name is needed (README, report, ai_statement). Do not use any other name. **Reminder:** `ai_log/` must also hold the TA's approval message for AI-written code (rule 11); Samarth adds it himself.
6. **Determinism:** every random thing takes a seed from `config.py` (default `SEED = 42`). Same command → same data.
7. **Single-thread search timing** always: set `OMP_NUM_THREADS=1`, `faiss.omp_set_num_threads(1)` and `hnswlib index.set_num_threads(1)` before any timed search. Building may use all cores; record the thread count used for building.
8. **Never put datasets or index files in git or in the submission.** `data/`, `cache/`, `results_quick/`, `*.hdf5`, `*.index`, `*.bin` are gitignored. `results/` **is tracked in git** (`results.csv`, `figures/`, `tables/`, notes, `env.json`), so it must never contain index or data files.
9. **`ai_files.txt` lists every source file in the repo** (one path per line) with exactly one label: `human-written`, `AI-assisted` or `AI-generated`. The default label for anything Claude writes is `AI-generated`. Samarth corrects the labels of files he edits himself; Claude must not change a label Samarth has set. Samarth uses this list for `ai_statement.md`.
10. If something in this file conflicts with the assignment PDF, the PDF wins — stop and point out the conflict.
11. **AI-written core modules (TA-approved).** The TA has approved Claude writing `annbench/metrics.py`, `annbench/timing.py` and `annbench/plots.py`, provided all AI use is logged in `ai_log/`. These three modules are AI-generated and must be labelled `AI-generated` in `ai_files.txt`. Samarth reviews each one line by line before committing it, because he must be able to explain it.

---

## 0.5 Platform: native Windows (no WSL)

Samarth works on **native Windows 10/11**, with Python from a Miniforge conda env and `bash` from **Git Bash**. The graders may run on Linux or macOS, so everything must work on all three.

- Use `pathlib.Path` for every path. Never hard-code `\` or drive letters.
- In shell scripts, call `python`, not `python3`. Conda on Windows has no `python3`.
- Git Bash has `curl` but not `wget`, so `download_data.sh` must use `curl -L -C - -o` when `wget` is missing.
- Git Bash has no `zip` or `pdfinfo`. `make_submission.sh` must build the zip with Python's `zipfile` (a small `scripts/make_zip.py`) and count PDF pages with `pypdf`. Add `pypdf` to `requirements.txt`.
- Add `.gitattributes` with `*.sh text eol=lf` and `*.py text eol=lf`, because CRLF line endings break `bash`.
- Never use `os.fork`, `signal.SIGALRM`, `resource`, or `multiprocessing` with the fork start method. Use `psutil` for RAM and CPU info.
- hnswlib is optional. If it fails to install on Windows, do HNSW with `faiss.IndexHNSWFlat` only. Do not fight the compiler.
- If FAISS crashes with an OpenMP or "libiomp5md.dll already initialized" error, the usual cause is another package bringing its own OpenMP. The fix is to install everything from conda-forge in a clean environment. Do not set `KMP_DUPLICATE_LIB_OK`, because it can corrupt timings.
- Before long runs, remind Samarth to plug in the laptop, set the Windows power mode to "Best performance", and close heavy apps. Timing noise on laptops is a threat to list in report Q5.

---

## 1. Target layout

The repo root **is** the `code/` folder of the submission.

```
code/                       # git repo root
├── README.md
├── requirements.txt
├── hypothesis.md
├── implementation.md       # this file (stays here; make_submission.sh copies it into ai_log/)
├── run_all.sh              # bash run_all.sh [--quick]
├── config.py               # all grids, paths, seeds, full vs quick settings
├── annbench/
│   ├── __init__.py
│   ├── data.py             # load hdf5, normalise GloVe, splits, subsets, ground truth
│   ├── metrics.py          # tie-aware recall@10
│   ├── timing.py           # single-query & batch timing, median of repeats
│   ├── indexes.py          # build/search wrappers: exact, HNSW, IVF-Flat, IVF-PQ (+refine)
│   ├── sizes.py            # index bytes, bytes/vector
│   ├── results_io.py       # replace one part's rows in results.csv (fixed schema)
│   ├── frontier.py         # Pareto frontier, operating-point selection
│   ├── plots.py
│   ├── tables.py           # markdown + LaTeX tables
│   └── synth.py            # Part 4 seeded data generator
├── experiments/
│   ├── part1_exact.py
│   ├── part2_benchmark.py
│   ├── part3_experiment.py
│   ├── part4_experiment.py
│   ├── q4_projection.py    # helper numbers for report question 4
│   └── make_tables.py      # regenerates all tables from results.csv
├── scripts/
│   ├── download_data.sh
│   ├── env_info.py         # CPU, RAM, OS, Python, faiss/hnswlib/numpy versions
│   └── make_submission.sh  # builds 2024101020_A3.zip
├── tests/
│   └── test_recall.py
├── report/                 # LaTeX source for report.pdf (Samarth writes prose)
├── data/          (gitignored)
├── cache/         (gitignored)
├── results_quick/ (gitignored; quick-mode output)
└── results/       (tracked in git; see below)
    ├── results.csv
    ├── env.json
    ├── part*_notes.md, part1_agreement.json
    ├── tables/
    └── figures/
```

**What goes in the zip from `results/`:** only `results/results.csv` and `results/figures/`, copied to the zip's top level by `make_submission.sh`. `results/` (and `results_quick/`) are excluded from the zipped `code/` working tree. `tables/`, notes and `env.json` reach the grader only through `report.pdf` and the git history.

---

## 2. Step-by-step plan

### Step 1 — Scaffold the repo

- Create the layout above (empty modules with docstrings are fine).
- `.gitignore`: `data/ cache/ results_quick/ *.hdf5 *.index *.bin __pycache__/ .venv/ *.zip report/*.aux report/*.log`. **`results/` is not ignored** (rule 8).
- `requirements.txt` (pin the versions actually installed — run `pip freeze` and copy the relevant lines): `numpy`, `h5py`, `faiss-cpu`, `hnswlib`, `pandas`, `matplotlib`, `pytest`, `psutil`.
- `scripts/download_data.sh`: downloads into `data/` only if the file is missing:
  - `http://ann-benchmarks.com/sift-128-euclidean.hdf5`
  - `http://ann-benchmarks.com/glove-100-angular.hdf5`
  Use `wget -c` (fall back to `curl -L -C -`). Print file sizes at the end.
- `scripts/env_info.py`: writes `results/env.json` and prints CPU model, cores, RAM, OS, Python version, and versions of numpy/faiss/hnswlib. (The report must state machine specs and library versions.)
- `config.py`: paths, `SEED`, `K = 10`, `TUNE = slice(0, 5000)`, `TEST = slice(5000, 10000)`, number of timing repeats (`REPEATS = 3`), all parameter grids (Section 3), and a `QUICK` dict that overrides them.
- `README.md` stub (title, author Samarth, sections to fill later).
- `hypothesis.md` with two empty headings: `## Part 3 hypothesis` and `## Part 4 hypothesis`.

⛔ **STOP** — suggest commit: `scaffold repo, config, download script`.

---

### Step 2 — Data loading (`annbench/data.py`)

- `load_dataset(name, n_base=None)` returns `xb (float32, C-contiguous), xq, gt_ids, gt_dist, metric_note`.
  - hdf5 keys: `train` (base), `test` (queries), `neighbors`, `distances`.
  - **GloVe:** L2-normalise both base and queries (guard zero-norm rows: leave them as zeros and count them; print the count). After normalising, Euclidean order = angular order, so we use Euclidean (`IndexFlatL2`) everywhere.
  - If `n_base` is given (quick mode / scaling), take the **first `n_base`** base vectors. The file's ground truth is then invalid, so ground truth must be recomputed (next point).
- `get_ground_truth(name, n_base, k=100)`: exact top-100 ids + squared-L2 distances computed with `faiss.IndexFlatL2` (batched, multi-threaded is fine here — this is not timed). Cache to `cache/gt_{name}_{n_base}.npz`.
  **All recall in the project is measured against this own exact ground truth.** The file's `neighbors` are used only for the agreement check in Part 1.
- Query split helpers: `tune_queries = xq[0:5000]`, `test_queries = xq[5000:10000]`. Tuning/selection uses tune; every reported number uses test.

---

### Step 3 — Tie-aware recall@10 + tests (`annbench/metrics.py`, `tests/test_recall.py`)

Definition (write it in the docstring and in the README):

> For query q, let d₁₀ be the true distance of the 10th exact neighbour. A returned id counts as correct if its true distance to q is ≤ d₁₀·(1+ε) + ε_abs (default ε = 1e-5, ε_abs = 1e-6, on squared L2). Duplicates and `-1` ids are ignored. recall@10(q) = min(#correct, 10) / 10. Report the mean over queries.

Implementation:
- `recall_at_k(xq, xb, retrieved_ids, gt_dist, k=10, rel_eps=1e-5, abs_eps=1e-6)`.
- Compute the true distance of each retrieved id **from the vectors** (`((xb[ids] - q)**2).sum(-1)` in float64), not from the index's returned distances (PQ distances are approximate and would be wrong).
- Vectorised over queries; must handle k returned < 10 (e.g. IVF with tiny nprobe returning -1).

Unit tests (pytest, tiny hand-made data, no dataset needed):
1. Perfect retrieval → 1.0.
2. Completely wrong retrieval → 0.0.
3. **Tie at the 10th neighbour:** two points at exactly the 10th distance; returning the "other" tied point still gives 1.0.
4. A point slightly farther than d₁₀ (beyond ε) is counted as wrong.
5. `-1` padding and duplicate ids are not counted.
6. Order of returned ids does not matter.
7. Returning fewer than 10 ids caps recall correctly (e.g. 7 correct → 0.7).
8. Mean over multiple queries is correct.

Run `pytest -q` and show the result.

⛔ **STOP** — suggest commit: `tie-aware recall@10 with unit tests`.

---

### Step 4 — Timing utilities (`annbench/timing.py`)

- `set_single_thread()` — sets env + faiss + returns a context so callers cannot forget.
- `time_single_query(search_fn, xq, k, repeats=REPEATS, warmup=1)`:
  loop `for i in range(nq): search_fn(xq[i:i+1], k)`, time the whole loop with `time.perf_counter()`, repeat, return `qps_median`, `qps_runs` (list), `latency_ms_median`, and the ids from the last run (for recall).
  One warm-up pass (not timed) first.
- `time_batch(search_fn, xq, k, repeats)` — one call with all queries.
- Note in the README: Python loop overhead (~a few µs per call) is included and is the same for all indexes.
- **CPU pinning (hybrid CPU).** The i7-13700H mixes performance and efficiency cores, and Windows may move the single search thread between them, which adds timing noise. During timed searches only, pin the process to one P-core logical CPU with `psutil.Process().cpu_affinity([config.PIN_CPU])` (default `PIN_CPU = 2`; on this machine logical CPUs 0–11 are P-core threads and 12–19 are E-cores). Restore the previous affinity afterwards, so index building still uses all cores. Make it a context manager (e.g. combined with `set_single_thread()`). It is a no-op when `PIN_CPU is None`, when `cpu_affinity` is unsupported (macOS), or when the CPU id does not exist on the machine (print a warning). Record the pinned CPU (or `null`) in the `extra` JSON of every `results.csv` row as `"pinned_cpu"`.

---

### Step 5 — Part 1: exact baseline (`experiments/part1_exact.py`)

For each dataset (SIFT, GloVe):
1. Build `faiss.IndexFlatL2`.
2. **Agreement check:** exact top-10 on all 10,000 queries vs the file's `neighbors[:, :10]`. Report: (a) fraction of queries whose id-sets match exactly, (b) tie-aware recall of our exact results against the file (should be ≈1.0), (c) a short note on any mismatches (ties / float precision / for GloVe, normalisation). Save to `results/part1_agreement.json`. The file's ground truth is for the full base set, so the check always uses the **full-size** data and our cached full-size ground truth (`cache/gt_{name}_{N}.npz`), even in quick mode. In quick mode it runs on the first 1,000 queries (500 if quick mode would otherwise exceed 15 min) and saves to `results_quick/part1_agreement.json`; record the number of queries checked in the JSON.
3. **Timing (single thread):**
   - one query at a time: on the test half. Full 1M exact single-query search is slow (~tens of ms each), so time the first `EXACT_SINGLE_N = 1000` test queries and state this in the report; record `n_queries` in the CSV.
   - batch: all 5,000 test queries in one `search` call, single-threaded, and also once with all threads (record both, label `threads`).
4. Replace the `part=1` rows in `results.csv` with this run's rows (`index=exact`, `mode=single|batch`); see Section 4 for the row-replacement rule.
5. Print the single vs batch speed-up. Write two sentences in `results/part1_notes.md` for Samarth to check: batched search becomes a matrix–matrix product (BLAS GEMM) that reuses each base vector loaded from memory across many queries and uses SIMD/cache blocking well; one-at-a-time search is matrix–vector, memory-bandwidth bound, re-streams all 1M vectors per query, and pays per-call overhead.

⛔ **STOP** — suggest commit: `part 1 exact baseline`.

---

### Step 6 — Index wrappers + sizes (`annbench/indexes.py`, `annbench/sizes.py`)

Use FAISS for all three (consistent implementation); hnswlib is optional as a cross-check only.

- `build_hnsw(xb, M, efConstruction=200)` → `faiss.IndexHNSWFlat(d, M)`, set `hnsw.efConstruction` before `add`. Search param: `index.hnsw.efSearch = ef` (must be ≥ k).
- `build_ivfflat(xb, nlist)` → `IndexIVFFlat(IndexFlatL2(d), d, nlist)`; train on a seeded random sample of `min(n, 64*nlist)` vectors (record the training size). Search param: `index.nprobe`.
- `build_ivfpq(xb, nlist, m, nbits=8)` → `IndexIVFPQ(quantizer, d, nlist, m, nbits)`; train on a seeded random sample of `min(n, max(64*nlist, 10,000))` vectors. The coarse quantizer wants ~64 vectors per list, and each PQ sub-quantizer learns 2^nbits = 256 centroids, for which FAISS asks for at least 39 × 256 ≈ 10,000 training points; record the training size. `m` must divide `d`.
- `build_ivfpq_refine(...)` (Part 3) → wrap with `faiss.IndexRefineFlat(ivfpq)`, `k_factor = 10` so the top 100 PQ candidates are re-ranked exactly.
- Every builder returns `(index, build_time_s, build_threads, train_time_s)`.
- **Cache** built indexes in `cache/` keyed by `(dataset, n_base, type, params)` with `faiss.write_index`; reload if present (`--rebuild` flag forces rebuild). Build time is always the measured value from when it was built (store it in a sidecar JSON next to the cached index).
- `index_bytes(index)` = `len(faiss.serialize_index(index))`. `bytes_per_vector = index_bytes / n_base`. Also record the theoretical code size for PQ (`m*nbits/8`) for the report.

---

### Step 7 — Part 2 benchmark (`experiments/part2_benchmark.py`)

For each dataset × index family × build setting:
1. Build (or load from cache).
2. For each search-param value in the sweep: run single-query timing on **both** halves (tune half for selecting operating points, test half for reporting). Compute recall@10 on each half. To save time in full mode, the tune half may use `TUNE_N = 2000` queries — state this in the README.
3. One CSV row per (build, search param, split); at the end, replace the `part=2` rows in `results.csv` with them.
4. Skip the rest of a sweep early once test recall ≥ 0.999 **and** the previous two points were also ≥ 0.999 (saves time; note it).

`annbench/frontier.py`:
- `pareto(points)` — keep points not dominated in (recall ↑, qps ↑).
- `operating_point(df, family, target)` — on the **tune** split, among all configs of that family with recall ≥ target, pick the one with the highest QPS; then report that same config's **test** recall and test QPS. If none reaches the target, return "not reached" + the max recall reached and its config.

Outputs:
- `results/figures/part2_{sift,glove}.png` (+ `.pdf`): x = recall@10 (test), y = QPS (log scale), one Pareto curve per index family, exact baseline as a horizontal line (or single marker at recall 1.0), dashed vertical lines at 0.90 and 0.95. Light grey faint markers for all non-frontier points are optional.
- `results/tables/part2_qps.{md,tex}`: rows = dataset × index; columns = QPS at 0.90, config used, QPS at 0.95, config used, speed-up over exact.
- `results/tables/part2_cost.{md,tex}`: at recall 0.95 config: build time (s, with threads), index size (MB), bytes/vector, (raw float32 = 4·d bytes for reference). For an index that never reaches 0.95, the row shows **"not reached"**, plus its max recall and the config that achieved it (with that config's build time, size and bytes/vector).
- **Below-target test recall (all tables in Parts 2–4):** configs are chosen on the tune split, so the test recall of a chosen config can land slightly below 0.90/0.95. Report test recall as measured (never round up or re-pick on test), and add a caption note to every such table: "Config chosen on tune queries (recall ≥ target); test recall reported as measured and may fall slightly below the target."
- `results/part2_notes.md`: if any index fails to reach 0.95 (likely IVF-PQ without re-ranking), list max recall reached and a draft explanation: PQ distances are approximate (quantisation error), so true neighbours at similar distance get mis-ordered and no nprobe can fix it — only re-ranking with exact distances can.

⛔ **STOP** — show the two plots and tables, suggest commit: `part 2 benchmark harness and results`. Samarth will look at the plots before moving on.

---

### Step 8 — Part 3 experiment (default choice: **Compression**)

Samarth may switch the choice; if so he will edit this section. Default spec:

- Dataset: SIFT 1M (quick: 100K). Fixed `nlist = 4096` (quick: 1024).
- Vary PQ sub-vectors `m ∈ {8, 16, 32, 64}`, `nbits = 8`.
- For each m: plain IVF-PQ vs IVF-PQ + exact re-rank of top 100 (`IndexRefineFlat`, k_factor 10). Sweep nprobe.
- Metrics per (m, variant): best QPS at recall 0.90 / 0.95 (or max recall reached), index bytes, bytes/vector, **including the raw vectors the re-ranker needs** (this is the catch: re-ranking needs the original float32 vectors, so memory jumps from m bytes to m + 512 bytes per vector, unless re-ranking reads them from disk — note this as untested).
- Figure: `results/figures/part3.png` — left: recall vs QPS for each m (solid = plain, dashed = re-rank); right: bytes/vector vs max recall.
- Table: `results/tables/part3.{md,tex}`.
- Rows: replace the `part=3` rows in `results.csv` (one row per (m, variant, nprobe, split)).

Procedure (strict order):
1. Write `experiments/part3_experiment.py` and test it **only** on 2,000 random synthetic vectors to confirm it runs. Do not touch SIFT with it.
2. Draft a hypothesis under `## Part 3 hypothesis` in `hypothesis.md` as a **suggestion** for Samarth (prediction + mechanism + what result would refute it), e.g.: "Recall of plain IVF-PQ is capped well below 0.95 for m ≤ 16 because quantisation error exceeds the gap between the 10th and 11th neighbour; re-ranking 100 candidates lifts recall above 0.95 for m ≥ 16 at a 2–3× QPS cost but needs the raw vectors in RAM, erasing most of the memory saving."

⛔ **STOP** — Samarth edits and commits `hypothesis.md` (Part 3 section) himself.
3. After Samarth says it is committed: run `git log -p -- hypothesis.md` and confirm the Part 3 section appears in a commit. Then run the experiment and generate the figure/table.
4. Write `results/part3_notes.md`: did the data support the hypothesis? (Draft; Samarth rewrites.)

⛔ **STOP** — suggest commit: `part 3 compression experiment results`.

---

### Step 9 — Part 4 experiment on our own data (default: **Drifting data**)

Must differ from Part 3 ✓ (Part 3 = compression). Indexes studied: **IVF-Flat and HNSW** (≥ 2 required). ≤ 500K synthetic vectors. Seeded.

Question: *When vectors added after building come from a shifted distribution, which index degrades, and does rebuilding fix it?*

Generator (`annbench/synth.py`, function `make_drift(shift, seed)`), derived by transforming real SIFT vectors:
- `base` = SIFT vectors 0–200K (quick: 0–40K). Index trained/built on this only.
- `added` = SIFT vectors 200K–400K (quick: 40K–80K), translated by `shift · R · u`, where `u` is a seeded random unit direction and `R` = mean distance of base vectors to the base centroid. **Only the shift changes between settings.**
- `queries` = 2,000 SIFT query vectors with the same translation (1,000 tune / 1,000 test). Ground truth recomputed exactly on `base ∪ added`.
- Settings: `shift ∈ {0.0 (control: same distribution), 0.25, 0.5, 1.0}`, in **both full and quick mode** (quick only shrinks the data to 40K + 40K). Total vectors = 400K ≤ 500K ✓.

For each shift:
1. **Stale:** IVF-Flat (nlist 1024) trained on `base` only, then `add(added)`; HNSW (M 32) built on `base`, then `add(added)`. Sweep nprobe / efSearch, measure test recall & single-thread QPS.
2. **Rebuilt:** IVF retrained on `base ∪ added`; HNSW built from scratch on `base ∪ added`. Same sweeps.
3. Diagnostics for IVF: inverted-list size imbalance (max/mean list size, coefficient of variation, fraction of added vectors falling in the top 1% largest lists); average number of distance computations per query at the chosen nprobe (use `faiss.cvar.indexIVF_stats` — reset before, read after).
4. Diagnostics for HNSW: insertion time for `added`; distance computations per query (`faiss.cvar.hnsw_stats`).

Outputs:
- **One main figure, single panel** `results/figures/part4.png`: QPS at recall 0.95 (or max recall) vs shift, lines for IVF-stale, IVF-rebuilt, HNSW-stale, HNSW-rebuilt. No inset, no second panel.
- `results/tables/part4.{md,tex}`: per shift and variant, QPS at 0.95 (or "not reached" + max recall), plus the diagnostics: IVF list-size max/mean, CV, fraction of added vectors in the top 1% largest lists, distance computations per query; HNSW insertion time and distance computations per query.
- Rows: replace the `part=4` rows in `results.csv`.
- Expected mechanism to check (do not state as fact before running): IVF centroids are frozen at training time, so shifted vectors pile into the few border cells nearest to them → very long lists → more distance computations per probe and poorer query-to-cell assignment; HNSW has no trained component, so incremental insertion adapts the graph.

Procedure is the same strict order as Part 3:
1. Write the generator + experiment script; test on tiny fake data only (e.g. 2,000 Gaussian vectors). Confirm determinism: generating twice with the same seed gives bit-identical arrays (add a unit test `tests/test_synth.py`).
2. Draft a `## Part 4 hypothesis` suggestion in `hypothesis.md`.

⛔ **STOP** — Samarth edits and commits the Part 4 hypothesis.
3. Verify with `git log -p -- hypothesis.md`, then run, plot, table.
4. Draft `results/part4_notes.md` with: what changed, what happened, mechanism, supported or not, what was **not** tested (e.g. rotations, deletions, new clusters, IVF-PQ, larger shifts, real-world drift).

⛔ **STOP** — suggest commit: `part 4 drift experiment results`.

*Alternative if Samarth prefers "hard geometry": seeded Gaussian-mixture data, n = 200K, vary dimension d ∈ {16, 64, 256} with control d = 32, or vary cluster spread σ with everything else fixed; same structure of hypothesis → STOP → run.*

---

### Step 10 — Question 4 helper (`experiments/q4_projection.py`)

Using measured numbers from `results.csv`:
- **Measure exact search at 150K** (do not project it): for each dataset, take the first 150,000 base vectors, build `IndexFlatL2`, and time single-thread one-query-at-a-time search on the test queries with the Step 4 protocol (same query count as Part 1's `EXACT_SINGLE_N`; quick mode uses the quick test-query count). Store these as `part=q4` rows in `results.csv` (`experiment_tag = "q4_exact_150k"`), replacing earlier `part=q4` rows.
- Exact single-query latency at **10M** is a projection: scale the measured 1M latency linearly in n (cross-check the linear model against the measured 150K and 1M points).
- Memory for 10M: raw float32 = 10M × 4d bytes (SIFT 5.12 GB, GloVe 4.0 GB); HNSW adds ≈ 2·M·4 bytes/vector of links plus overhead (use measured bytes/vector from Part 2); IVF-Flat ≈ raw + ids; IVF-PQ ≈ m + 8 bytes/vector.
- **Recommended index and settings per scenario** (150K and 10M, for each dataset; budget 100 ms/query, 16 GB RAM), chosen from the measured results by a fixed rule: among exact search and the Part 2 (and Part 3 re-rank) operating points at recall 0.95, keep those whose latency (measured at 150K / 1M, projected at 10M) fits in 100 ms and whose memory (measured or projected) fits in 16 GB with headroom for the OS; recommend the fastest of these, and say whether exact search alone already fits. Print the rule and the candidates considered. This is a draft for Samarth; the reasoning in the report is his.
- Output `results/tables/q4.{md,tex}`: dataset, n, exact latency (measured or projected), fits in 100 ms?, memory per index, fits in 16 GB?, recommended index + settings.
- Clearly label every value as **measured** or **projected**.

---

### Step 11 — `run_all.sh`, tables, README

`run_all.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
QUICK=""; [[ "${1:-}" == "--quick" ]] && QUICK="--quick"
export OMP_NUM_THREADS=1   # search timing; builders raise it internally where allowed
bash scripts/download_data.sh
python scripts/env_info.py
pytest -q
python experiments/part1_exact.py $QUICK
python experiments/part2_benchmark.py $QUICK
python experiments/part3_experiment.py $QUICK
python experiments/part4_experiment.py $QUICK
python experiments/q4_projection.py $QUICK
python experiments/make_tables.py $QUICK
echo "Done. See results/"
```
- `--quick` writes to `results_quick/` (so it never overwrites full results) — or a `--out` flag; pick one and document it.
- Quick mode: first 100,000 base vectors, ground truth recomputed, 1,000 tune / 1,000 test queries, smaller grids (Section 3), REPEATS = 3 still. The Part 1 agreement check still runs at full size on the first 1,000 queries (Step 5). **Must finish in < 15 min on a laptop including data loading** — measure it (`time bash run_all.sh --quick`) and record the time in the README. If it is over, first cut the agreement check to 500 queries, then shrink the quick grids, not the method.
- Full mode does **not** delete `results/results.csv`. Each experiment script replaces only its own part's rows (Section 4), so re-running one part never removes another part's rows. Cached indexes are kept, but everything is re-timed.
- Every number in the report must come from a file in `results/` — no manual numbers.
- **Task: record the BLAS library.** `scripts/env_info.py` must record which BLAS numpy/FAISS use (e.g. from `numpy.show_config(mode="dicts")` plus the conda `libblas` build string when running under conda), and the README and report must state it. Reason: the env's MKL 2026.2 + `llvm-openmp` 23.1.4 crashes on any large matrix multiply (exit 127), and the BLAS choice affects batch timings.
- **Task: pin OpenBLAS.** Once Samarth has switched the `ire-a3` env to OpenBLAS (`conda install -n ire-a3 -c conda-forge "libblas=*=*openblas"`), `environment.yml` must pin `libblas=*=*openblas`.

`README.md`: author Samarth; machine specs (from `env.json`); setup (venv, `pip install -r requirements.txt`); how to run full and quick, expected runtimes; layout; recall definition; timing protocol (single thread, warm-up, median of 3, query subsets used for exact single-query timing); where each figure/table comes from; results.csv schema.

⛔ **STOP** — Samarth runs `time bash run_all.sh --quick` himself in a fresh terminal. Suggest commit: `one-command reproduction`.

---

### Step 12 — Report scaffold (`report/`)

- `report/report.tex` (article class, 11pt, narrow margins, ≤ 5 pages) with sections: Setup (machine, versions, protocol), Part 1, Part 2, Part 3, Part 4 (≤ 1 page, one main figure), Answers to Q1–Q5.
- Collect all results first; compress the report to 5 pages at the end.
- `\input{}` the generated `.tex` tables and `\includegraphics` the figures from `../results/` so the report updates when results change.
- Under each question put **bullet-point notes with the relevant numbers** pulled from the tables and the draft mechanism, marked `% DRAFT – Samarth to rewrite`. Do not write final prose; the explanations ("why") are Samarth's.
- Q5 candidates to list: Python per-call overhead dominating at high QPS; single-thread/one-machine results not transferring to batched or multi-threaded serving; tuning-vs-test split and query subsets; cached build vs cold memory; tie tolerance ε; turbo boost/thermal noise; quick-subset ground truth. Mark which were tested.
- Compile with `latexmk -pdf` (or Samarth uses Overleaf) → `report.pdf`.

⛔ **STOP**.

---

### Step 13 — Submission packaging (`scripts/make_submission.sh`)

Builds `2024101020_A3.zip` (roll number 2024101020, fixed) containing **exactly**:
```
report.pdf
code/            # full repo incl. .git, minus data/, cache/, results/, results_quick/, *.zip, report build junk
results/results.csv    # copied from code/results/
results/figures/...    # copied from code/results/figures/
ai_log/          # Samarth fills: prompts+responses, ai_statement.md, the TA's approval message;
                 # make_submission.sh copies implementation.md here (it is not moved out of code/)
```
- Build the zip with Python's `zipfile` (Git Bash on Windows has no `zip`), and count pages with `pypdf`.
- Check and fail loudly if: any `.hdf5`, `.index`, `.bin`, or file > 20 MB is inside; `report.pdf` missing or > 5 pages (use `pdfinfo` if available); `ai_log/ai_statement.md` missing; `git status` in code/ is not clean (uncommitted changes).
- Print the zip's file tree and total size.

⛔ **STOP** — Samarth makes the final commit and builds the zip himself.

---

## 3. Parameter grids (put these in `config.py`)

| Family | Build params (full) | Search sweep |
|---|---|---|
| Exact | — | — |
| HNSW | M ∈ {16, 32, 48}, efConstruction = 200 | efSearch ∈ {10, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512} |
| IVF-Flat | nlist ∈ {1024, 4096, 8192} | nprobe ∈ {1, 2, 4, 8, 16, 32, 64, 128, 256, 512} |
| IVF-PQ (SIFT, d=128) | nlist ∈ {1024, 4096}, m ∈ {16, 32, 64}, nbits 8 | nprobe as IVF-Flat |
| IVF-PQ (GloVe, d=100) | nlist ∈ {1024, 4096}, m ∈ {20, 25, 50}, nbits 8 | nprobe as IVF-Flat |

Quick mode (100K vectors): HNSW M ∈ {16, 32}; IVF nlist ∈ {256, 1024}; IVF-PQ nlist 1024, m ∈ {16, 32} (SIFT) / {20, 50} (GloVe); trimmed sweeps (e.g. efSearch {16, 32, 64, 128, 256}, nprobe {1, 4, 16, 64, 256}). Part 3 quick: m ∈ {8, 16, 32}. Part 4 quick: 80K vectors, shifts {0, 0.25, 0.5, 1.0} (same as full: ≥ 3 settings + control).

If any index does not reach ≥ 0.95 recall with these grids (other than IVF-PQ), extend the sweep rather than accept it, and tell Samarth.

---

## 4. `results/results.csv` schema (one row per timed run)

`run_id, part, dataset, n_base, index, build_params(json), search_param_name, search_param, split(tune|test), n_queries, k, recall_at_10, qps_median, qps_runs(json), latency_ms_median, build_time_s, train_time_s, build_threads, search_threads, index_bytes, bytes_per_vector, mode(single|batch), experiment_tag, extra(json), timestamp, git_commit`

`git_commit` = output of `git rev-parse --short HEAD` (read-only) plus `-dirty` if the tree has uncommitted changes.

**Row replacement.** `results.csv` is never deleted. Each script owns the rows with its `part` value (`1`, `2`, `3`, `4`, `q4`). It collects its rows in memory and, at the end, rewrites the file with all other parts' rows unchanged and its own old rows replaced by the new ones (write to a temp file, then rename, so a crashed run leaves the old rows in place). Quick mode does the same in `results_quick/results.csv`.

---

## 5. Definition of done (checklist)

- [ ] `pytest -q` passes (recall tests + synth determinism test).
- [ ] Part 1: agreement check, single vs batch timings, explanation draft.
- [ ] Part 2: 2 plots, QPS@0.90/0.95 table, cost table at 0.95, failure note.
- [ ] Part 3: hypothesis committed **before** results (visible in `git log`), figure, table, verdict.
- [ ] Part 4: own seeded generator ≤ 500K, ≥ 3 settings + control (full and quick), ≥ 2 indexes, hypothesis committed first, one single-panel main figure, diagnostics in the table.
- [ ] Q4 table: exact search measured at 150K, 10M projected, recommended index + settings per scenario.
- [ ] `results/` tracked in git; each script replaces only its own rows in `results.csv`.
- [ ] `bash run_all.sh` and `bash run_all.sh --quick` (< 15 min, measured) both work; README explains both.
- [ ] `results/results.csv` has every run behind a reported number.
- [ ] Machine specs + library versions (including the BLAS library) in README and report; `environment.yml` pins OpenBLAS.
- [ ] No data/index files in git or zip; ann-benchmarks framework never used.
- [ ] `ai_files.txt` lists every source file with a label; `metrics.py`, `timing.py`, `plots.py` labelled AI-generated and reviewed line by line by Samarth.
- [ ] `ai_log/` has prompts + responses, `ai_statement.md`, the TA's approval message, and a copy of `implementation.md`.
