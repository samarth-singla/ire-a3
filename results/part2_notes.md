# Part 2 notes (DRAFT - Samarth to check and rewrite)

- **sift / IVF-PQ** does not reach 0.95 on the tune queries: max tune recall 0.8795 at nlist=4096, m=64, nprobe=512 (test recall 0.8848). PQ distances are approximate (quantisation error), so true neighbours at similar distances get mis-ordered, and no nprobe can fix that; only re-ranking with exact distances can.
- Noise canary (sift): exact 200-query search QPS min 3,331, median 3,871, max 4,155 (spread 21.3%) over 12 build configs.
- **glove / IVF-PQ** does not reach 0.95 on the tune queries: max tune recall 0.8566 at nlist=1024, m=50, nprobe=512 (test recall 0.8629). PQ distances are approximate (quantisation error), so true neighbours at similar distances get mis-ordered, and no nprobe can fix that; only re-ranking with exact distances can.
- Noise canary (glove): exact 200-query search QPS min 3,931, median 4,505, max 5,276 (spread 29.9%) over 12 build configs.
