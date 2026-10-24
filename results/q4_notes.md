# Question 4 notes (DRAFT - Samarth to rewrite)

Scenarios: 150,000 or 10,000,000 vectors, 100 ms per query, 16 GB RAM ('fits' = at most 12 GiB so the OS and the query process have room).

## Measured vs extrapolated

**sift** (full size n = 1,000,000, d = 128):
- Exact, 1 thread: 32.5 ms at 1,000,000 (measured, Part 1); 4.54 ms at 150K (measured here); the linear model from the full-size number predicts 4.87 ms at 150K (measured/predicted = 0.93).
- Exact at 10M: 325 ms (PROJECTION, linear in n; a full scan streams all vectors once per query).
- HNSW @0.95: M=16, efSearch=64, 0.21 ms/query, 656 B/vector, build 61 s at full size (all measured).
- IVF-Flat @0.95: nlist=4096, nprobe=64, 0.59 ms/query, 522 B/vector (measured).
- IVF-PQ: does not reach 0.95 (max recall 0.885 at nlist=4096, m=64, nprobe=512, 74 B/vector, measured).
- IVF-PQ + re-rank @0.95: nlist=4096, m=16, nprobe=64, 0.34 ms/query, 538 B/vector (measured, Part 3).

**glove** (full size n = 1,183,514, d = 100):
- Exact, 1 thread: 29.1 ms at 1,183,514 (measured, Part 1); 3.29 ms at 150K (measured here); the linear model from the full-size number predicts 3.69 ms at 150K (measured/predicted = 0.89).
- Exact at 10M: 246 ms (PROJECTION, linear in n; a full scan streams all vectors once per query).
- HNSW @0.95: M=32, efSearch=384, 1.93 ms/query, 672 B/vector, build 149 s at full size (all measured).
- IVF-Flat @0.95: nlist=4096, nprobe=512, 3.30 ms/query, 409 B/vector (measured).
- IVF-PQ: does not reach 0.95 (max recall 0.863 at nlist=1024, m=50, nprobe=512, 58 B/vector, measured).
- IVF-PQ + re-rank @0.95: not measured for glove; memory estimated as plain IVF-PQ + raw vectors = 458 B/vector.

## Scenarios (draft recommendations)

- **sift, n = 150,000**: exact 4.5 ms (measured), raw vectors 0.07 GiB. -> **Exact (IndexFlatL2)**: 4.5 ms/query, recall 1.0, 0.07 GiB; ANN not needed for the budget.
- **sift, n = 10,000,000**: exact 324.9 ms (projected (linear in n)), raw vectors 4.77 GiB. -> **HNSW**: M=16, efSearch=64; 0.24 ms/query (extrapolated (x log n ratio; optimistic)); 6.1 GiB.
  - HNSW build at 10M: ~12 min with 20 threads (EXTRAPOLATION: measured 61 s x 11.7). Caveat: real HNSW builds grow faster than n log n once the graph no longer fits in cache, and building needs the raw vectors and the index in RAM at the same time (~10.9 GiB peak), close to the 16 GB limit.
- **glove, n = 150,000**: exact 3.3 ms (measured), raw vectors 0.06 GiB. -> **Exact (IndexFlatL2)**: 3.3 ms/query, recall 1.0, 0.06 GiB; ANN not needed for the budget.
- **glove, n = 10,000,000**: exact 245.8 ms (projected (linear in n)), raw vectors 3.73 GiB. -> **HNSW**: M=32, efSearch=384; 2.22 ms/query (extrapolated (x log n ratio; optimistic)); 6.3 GiB.
  - HNSW build at 10M: ~24 min with 20 threads (EXTRAPOLATION: measured 149 s x 9.7). Caveat: real HNSW builds grow faster than n log n once the graph no longer fits in cache, and building needs the raw vectors and the index in RAM at the same time (~10.0 GiB peak), close to the 16 GB limit.

## Caveats (draft)

- All latencies are single-thread, one query at a time. A multi-threaded or batched exact search could bring 10M exact search under 100 ms on this CPU (Part 1: batching gave ~10x), which this table does not credit.
- 10M ANN latencies are extrapolated from 1M operating points. Keeping recall 0.95 at 10M needs a larger efSearch / nprobe (recall at a fixed setting drops as n grows), and IVF should use a larger nlist (about sqrt(n)); both are untested.
- Memory uses bytes/vector measured at full size; fixed costs (centroids, codebooks) are a slightly larger share at 150K and a smaller one at 10M.
- 10M vectors of this kind are not available here; nothing at 10M was measured.
