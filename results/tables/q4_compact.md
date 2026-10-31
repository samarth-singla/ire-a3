| Data | n | Exact ms [M/P] | HNSW GiB | Recommendation |
|---|---|---|---|---|
| SIFT | 150,000 | 4.5 [M] | 0.09 | Exact |
| SIFT | 10,000,000 | 324.9 [P] | 6.11 | HNSW M16/ef64 |
| GloVe | 150,000 | 3.3 [M] | 0.09 | Exact |
| GloVe | 10,000,000 | 245.8 [P] | 6.26 | HNSW M32/ef384 |

Q4: exact single-thread latency (M measured, P projected linearly in n), HNSW memory at the 0.95 config, recommended index (100 ms, 16 GB).
