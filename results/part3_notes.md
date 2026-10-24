# Part 3 notes (DRAFT - Samarth to check and rewrite)

Data: `results.csv` part=3 (full SIFT 1M), nlist=4096. Max recall = test recall of the config with the highest tune recall. These are automatic checks against the committed hypothesis; the reasoning is Samarth's.

| m | plain max recall | re-rank max recall | plain B/vector | re-rank B/vector (RAM) | plain/re-rank QPS at same nprobe (median, range) |
|---|---|---|---|---|---|
| 8 | 0.412 | 0.885 | 18.3 | 530.3 | 1.29x (1.04-1.42) |
| 16 | 0.590 | 0.985 | 26.3 | 538.3 | 1.21x (1.02-1.35) |
| 32 | 0.745 | 1.000 | 42.3 | 554.3 | 1.16x (1.01-1.30) |
| 64 | 0.885 | 1.000 | 74.3 | 586.3 | 1.09x (1.01-1.26) |

## Prediction by prediction (draft)

**P1 (plain IVF-PQ recall ceiling)**

- m=8 below 0.60: 0.412 -> **supported**
- m=16 below 0.90: 0.590 -> **supported**
- only m=64 may come close to 0.95: m=64 reaches 0.885, m=32 0.745
- max recall rises with m: [0.412, 0.59, 0.745, 0.885] -> **supported**

**P2 (re-ranking removes the ceiling)**

- m=8: re-rank max recall 0.885, reaches 0.95 on tune: no (predicted maybe not)
- m=16: re-rank max recall 0.985, reaches 0.95 on tune: yes (predicted yes) -> **supported**
- m=32: re-rank max recall 1.000, reaches 0.95 on tune: yes (predicted yes) -> **supported**
- m=64: re-rank max recall 1.000, reaches 0.95 on tune: yes (predicted yes) -> **supported**
- recall gain from re-ranking per m: [0.474, 0.395, 0.255, 0.115]; refuted if < 0.02 everywhere -> **supported**

**P3 (speed)**

- m=8: plain/re-rank QPS at same nprobe median 1.29x, max 1.42x
- m=16: plain/re-rank QPS at same nprobe median 1.21x, max 1.35x
- m=32: plain/re-rank QPS at same nprobe median 1.16x, max 1.30x
- m=64: plain/re-rank QPS at same nprobe median 1.09x, max 1.26x
- drop below 2x at every nprobe (refuted if re-ranking more than halves QPS): worst 1.42x -> **supported**

**P4 (memory)**

- m=8: plain 18.3 B/vector (predicted ~16); re-rank 530.3 B/vector in RAM (predicted ~528), PQ part alone 18.3
- m=16: plain 26.3 B/vector (predicted ~24); re-rank 538.3 B/vector in RAM (predicted ~536), PQ part alone 26.3
- m=32: plain 42.3 B/vector (predicted ~40); re-rank 554.3 B/vector in RAM (predicted ~552), PQ part alone 42.3
- m=64: plain 74.3 B/vector (predicted ~72); re-rank 586.3 B/vector in RAM (predicted ~584), PQ part alone 74.3
- The measured plain size is above m + 8 because of the coarse centroids and PQ codebooks (and inverted-list overhead); check the gap shrinks relative to n at full size.

**Not tested:** re-ranking from raw vectors on disk (memory would stay near the PQ part, at an I/O cost per query), k_factor other than 10, nbits other than 8, other nlist values, OPQ / rotations, multi-threaded or batched search.
