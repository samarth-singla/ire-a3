# Hypotheses

Author: Samarth. Both hypotheses were written before running the experiment on real or generated data. The only evidence I had was the 20K-vector SIFT sanity check from the index tests, where plain IVF-PQ (m=16) stopped at recall about 0.68 and IVF-PQ with exact re-ranking reached about 0.998.

## Part 3 hypothesis: Compression (SIFT, 1M vectors, nlist=4096, 8-bit PQ codes)

**Setup.** I vary the number of PQ sub-vectors m in {8, 16, 32, 64} and compare plain IVF-PQ with IVF-PQ followed by exact re-ranking of the top 100 candidates, sweeping nprobe for each.

**Prediction 1 (recall of plain IVF-PQ).** The best recall plain IVF-PQ can reach rises with m, and for small m it never reaches 0.90 however large nprobe is.
- m=8 will stay below 0.60.
- m=16 will stay below 0.90.
- Only m=64 may come close to 0.95.

**Mechanism.** PQ replaces each vector by a short code, so distances are computed on quantised vectors. The quantisation error is a fixed property of the code and does not depend on nprobe. When the true 10th and 11th neighbours differ in distance by less than that error, they get mis-ordered, so searching more lists cannot fix it. More sub-vectors mean finer quantisation, hence a smaller error.

**Prediction 2 (re-ranking).** Re-ranking the top 100 candidates with exact distances removes most of this ceiling.
- For m >= 16, recall of at least 0.95 becomes reachable at large enough nprobe.
- For m=8, recall may still fall short, because a true neighbour that PQ ranks below 100 can never be recovered.

**Prediction 3 (speed).** At a fixed nprobe, re-ranking lowers QPS, because it adds 100 exact distance computations with random memory access per query. I expect a drop of less than 2x. Larger m also lowers QPS slightly, since each vector needs more table lookups.

**Prediction 4 (memory).** Plain IVF-PQ costs roughly m plus about 8 bytes per vector (code plus id). Re-ranking needs the original float32 vectors, which adds 512 bytes per vector for SIFT. So at m=16, memory goes from about 34 to about 546 bytes per vector, and most of the saving from PQ is lost unless the raw vectors live on disk.

**What would prove me wrong.**
- Plain IVF-PQ at m=16 reaches 0.95 recall.
- Re-ranking changes recall by less than 0.02 at every m.
- Re-ranking more than halves QPS at a fixed nprobe, which would mean the exact step, not the list scan, dominates the cost.

## Part 4 hypothesis: Drifting data (IVF-Flat vs HNSW)

**Setup.** I build indexes on SIFT vectors 0 to 200K. I then add vectors 200K to 400K, translated by shift x R x u. Here u is a fixed seeded random unit direction and R is the mean distance of base vectors from the base centroid. The queries get the same translation. The shift takes values in {0.25, 0.5, 1.0}, plus a control with shift = 0. I compare a stale index (trained on the base only, then extended) with a rebuilt index (trained on all 400K), using IVF-Flat (nlist=1024) and HNSW (M=32).

**Prediction 1 (control).** At shift 0, stale and rebuilt behave the same for both indexes, within normal timing noise of about 10 to 15%.

**Prediction 2 (IVF-Flat degrades).** For stale IVF-Flat, the damage grows with the shift and shows up mostly as lost speed, not lost recall.
- The k-means centroids are frozen at training time, so the shifted vectors are all assigned to the few cells nearest to the new region.
- Those lists become very long. I expect the coefficient of variation of list sizes to grow with the shift.
- Because the queries are shifted too, they probe exactly those long lists. The distance computations per query rise, and QPS at recall 0.95 falls. At shift 1.0 I expect a drop of at least 2x compared with the rebuilt index.
- Recall at a fixed nprobe may change less, since the shifted queries and their true neighbours land in the same crowded cells.

**Prediction 3 (rebuild helps IVF).** Retraining IVF on all 400K vectors restores speed to within about 20% of the control, because the centroids then follow the new distribution and the lists are balanced again.

**Prediction 4 (HNSW is robust).** Stale HNSW stays within about 20% of rebuilt HNSW in both QPS and recall at every shift. HNSW has no trained component. Each inserted vector connects itself to its nearest neighbours at insertion time, so the graph adapts to the new region as the vectors arrive. I expect only insertion time and graph quality to differ slightly.

**What would prove me wrong.**
- Stale IVF-Flat at shift 1.0 stays within 20% of rebuilt IVF-Flat in QPS at recall 0.95, with no growth in list imbalance.
- Stale HNSW degrades as much as IVF-Flat. This could happen if the shifted cluster connects to the old graph only through a few poor long-range links.
- Rebuilding does not restore IVF speed.

**What I do not test.** Rotations, deletions, new clusters, IVF-PQ, shifts larger than 1.0 R, and drift in real deployments. I also do not test whether the effect is the same at other nlist values.