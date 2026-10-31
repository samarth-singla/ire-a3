| Shift | Index | Variant | QPS @0.95 | Recall | Dist./q | List CV |
|---|---|---|---|---|---|---|
| 0 | IVF-Flat | stale | 2,357 | 0.966 | 14,087 | 0.44 |
| 0 | IVF-Flat | rebuilt | 2,393 | 0.968 | 14,013 | 0.43 |
| 0 | HNSW | stale | 9,272 | 0.952 | 985 | - |
| 0 | HNSW | rebuilt | 9,176 | 0.951 | 986 | - |
| 1 | IVF-Flat | stale | 1,800 | 0.965 | 18,842 | 0.76 |
| 1 | IVF-Flat | rebuilt | 2,734 | 0.979 | 12,693 | 0.41 |
| 1 | HNSW | stale | 10,085 | 0.956 | 914 | - |
| 1 | HNSW | rebuilt | 10,187 | 0.954 | 914 | - |

Drift, shift 0 (control) and 1: test QPS and recall at the 0.95 config, distance computations per query, IVF list-size CV.
