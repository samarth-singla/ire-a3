# Part 1 notes (DRAFT - Samarth to check and rewrite)

Exact search (`IndexFlatL2`), measured by `experiments/part1_exact.py`; numbers from this run (also in `results.csv`, part=1).

| dataset | single-query QPS (1 thread) | batch QPS (1 thread) | batch QPS (all threads) | batch(1t) / single | batch(all) / single |
|---|---|---|---|---|---|
| sift | 28.4 | 250.8 | 640.2 (20 threads) | 8.8x | 22.5x |
| glove | 33.1 | 257.5 | 278.3 (20 threads) | 7.8x | 8.4x |

Single-query timing uses the first 1000 test queries; batch timing uses all 5000 test queries.

## Why batch is so much faster (draft, two sentences)

Batched search turns the distance computation into one matrix-matrix product (BLAS GEMM), which loads each base vector from memory once and reuses it for many queries while it is in cache, and makes full use of SIMD and cache blocking. One-at-a-time search is a matrix-vector product that is limited by memory bandwidth, because it streams all base vectors from RAM again for every query, and it also pays the Python and FAISS per-call overhead for each query.
