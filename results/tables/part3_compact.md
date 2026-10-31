| m | Plain max R | Re-rank max R | Re-rank QPS @0.95 | B/vec RAM | B/vec PQ |
|---|---|---|---|---|---|
| 8 | 0.412 | 0.885 | not reached | 530.3 | 18.3 |
| 16 | 0.590 | 0.985 | 2,917 (np64) | 538.3 | 26.3 |
| 32 | 0.745 | 1.000 | 1,841 (np64) | 554.3 | 42.3 |
| 64 | 0.885 | 1.000 | 1,067 (np64) | 586.3 | 74.3 |

SIFT, nlist 4096: best recall of plain IVF-PQ vs re-ranking the top 100; re-rank memory with raw vectors in RAM, and the PQ part alone.
