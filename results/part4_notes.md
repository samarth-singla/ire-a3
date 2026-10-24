# Part 4 notes (DRAFT - Samarth to check and rewrite)

Data: results.csv part=4 (full): 200,000 SIFT base + 200,000 added vectors, 2,000 queries (half tune, half test), shifts [0.0, 0.25, 0.5, 1.0]. Numbers are test QPS at the config chosen on tune for recall 0.95 ('nr' = not reached; the highest-recall config is used).

## What changed

Only the shift: added vectors and queries are moved by shift x R along one fixed seeded direction u (R = mean distance of base vectors to their centroid). Shift 0 is the control. Stale indexes are trained/built on the base and then extended; rebuilt indexes are built on base + added.

## What happened

| shift | IVF stale | IVF rebuilt | IVF stale/rebuilt | HNSW stale | HNSW rebuilt | HNSW stale/rebuilt | IVF stale list CV | added in top 1% lists | IVF dist/query stale vs rebuilt |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 2,357 | 2,393 | 0.98 | 9,272 | 9,176 | 1.01 | 0.44 | 3% | 14,087 vs 14,013 |
| 0.25 | 2,315 | 2,394 | 0.97 | 6,907 | 6,657 | 1.04 | 0.47 | 3% | 14,542 vs 13,947 |
| 0.5 | 2,173 | 2,642 | 0.82 | 9,935 | 9,808 | 1.01 | 0.54 | 4% | 15,467 vs 12,997 |
| 1 | 1,800 | 2,734 | 0.66 | 10,085 | 10,187 | 0.99 | 0.76 | 9% | 18,842 vs 12,693 |

## Prediction by prediction (draft)

- **P1 control** (stale = rebuilt within 10-15% at shift 0): IVF stale/rebuilt 0.98, HNSW 1.01 -> **supported**
- **P2 IVF stale degrades with shift**: list CV [0.44, 0.47, 0.54, 0.76] (grows: **supported**); stale/rebuilt QPS at shift 1 = 0.66, i.e. a 1.5x drop (predicted >= 2x) -> **not supported**
- **P3 rebuild restores IVF speed** (within 20% of control): rebuilt QPS / control [1.0, 1.0, 1.1, 1.14] -> **supported**
- **P4 HNSW robust** (stale within 20% of rebuilt in QPS and recall): QPS ratios [1.01, 1.04, 1.01, 0.99], recall (stale, rebuilt) [(0.952, 0.951), (0.971, 0.975), (0.953, 0.954), (0.956, 0.954)] -> **supported**

## Mechanism to check (draft)

- IVF: centroids are fixed at training time, so shifted vectors pile into the few cells nearest the new region (see list CV, max/mean and the share of added vectors in the top 1% of lists). Shifted queries probe exactly those long lists, so distance computations per query rise (column 'dist/query') and QPS at a given recall falls.
- HNSW: no trained component; inserted vectors link to their nearest neighbours at insertion time, so the graph covers the new region. Compare insertion time of the added vectors with the rebuild time in the table.

## Not tested

Rotations, deletions, new clusters appearing, IVF-PQ, shifts larger than 1.0 R, drift in real deployments, other nlist / M values, queries from the old distribution after drift, multi-threaded or batched search.
