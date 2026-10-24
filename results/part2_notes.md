# Part 2 notes (DRAFT - Samarth to check and rewrite)

- **sift / IVF-PQ** does not reach 0.95 on the tune queries: max tune recall 0.8795 at nlist=4096, m=64, nprobe=512 (test recall 0.8848). PQ distances are approximate (quantisation error), so true neighbours at similar distances get mis-ordered, and no nprobe can fix that; only re-ranking with exact distances can.
- Tune vs test recall (sift, 122 configs): |test - tune| median 0.0147, max 0.0500.
- Noise canary (sift, run at commit cddedc1, 12 sweeps, 2026-10-23T19:03 to 2026-10-23T20:07 UTC): exact 200-query search QPS min 3,331, median 3,877, max 4,155 (spread 21.3%).
- **glove / IVF-PQ** does not reach 0.95 on the tune queries: max tune recall 0.8566 at nlist=1024, m=50, nprobe=512 (test recall 0.8629). PQ distances are approximate (quantisation error), so true neighbours at similar distances get mis-ordered, and no nprobe can fix that; only re-ranking with exact distances can.
- Tune vs test recall (glove, 129 configs): |test - tune| median 0.0043, max 0.0129.
- Noise canary (glove, run at commit cddedc1, 12 sweeps, 2026-10-23T20:14 to 2026-10-23T21:28 UTC): exact 200-query search QPS min 3,931, median 4,584, max 4,998 (spread 23.3%).
- Noise canary (glove, run at commit cddedc1-dirty, 2 sweeps, 2026-10-24T04:54 to 2026-10-24T04:57 UTC): exact 200-query search QPS min 5,174, median 5,225, max 5,276 (spread 2.0%).
- Noise canary (glove, all runs, 14 sweeps, 2026-10-23T20:14 to 2026-10-24T04:57 UTC): exact 200-query search QPS min 3,931, median 4,701, max 5,276 (spread 28.6%).
