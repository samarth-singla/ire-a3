| Dataset | Index | QPS @0.90 | Recall | Config @0.90 | QPS @0.95 | Recall | Config @0.95 | Speed-up vs exact (0.90 / 0.95) |
|---|---|---|---|---|---|---|---|---|
| sift | HNSW | 8,581 | 0.916 | M=16, efSearch=32 | 4,775 | 0.970 | M=16, efSearch=64 | 279× / 155× |
| sift | IVF-Flat | 3,030 | 0.927 | nlist=4096, nprobe=32 | 1,697 | 0.973 | nlist=4096, nprobe=64 | 98× / 55× |
| sift | IVF-PQ | not reached | max 0.885 | nlist=4096, m=64, nprobe=512 | not reached | max 0.885 | nlist=4096, m=64, nprobe=512 | - / - |
| glove | HNSW | 1,241 | 0.910 | M=48, efSearch=128 | 518 | 0.954 | M=32, efSearch=384 | 36× / 15× |
| glove | IVF-Flat | 995 | 0.909 | nlist=8192, nprobe=256 | 303 | 0.967 | nlist=4096, nprobe=512 | 29× / 9× |
| glove | IVF-PQ | not reached | max 0.863 | nlist=1024, m=50, nprobe=512 | not reached | max 0.863 | nlist=1024, m=50, nprobe=512 | - / - |

Single-thread, one-query-at-a-time QPS on the test queries (median of 3 runs) at recall@10 0.90 and 0.95. Configs are chosen on the tune queries (recall ≥ target); test recall is reported as measured and may fall slightly below the target. 'not reached': no config reached the target on the tune queries; the highest-recall config is shown with its test recall.
