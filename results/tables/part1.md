| Dataset | n | Exact top-10 set match | Tie-aware recall vs file | Single-query QPS | Batch QPS (1 thread) | Batch QPS (all threads) | Batch / single (1 thread) |
|---|---|---|---|---|---|---|---|
| sift | 1,000,000 | 0.9935 (10,000 q) | 1.0000 | 30.8 (32.5 ms) | 342 | 761 (20 thr) | 11.1× |
| glove | 1,183,514 | 1.0000 (10,000 q) | 1.0000 | 34.4 (29.1 ms) | 348 | 383 (20 thr) | 10.1× |

Exact search (IndexFlatL2). Agreement with the neighbours stored in the data file (full-size data). Single-query timing: first 1,000 test queries, 1 thread, pinned; batch: 5,000 test queries in one call. Median of 3 runs.
