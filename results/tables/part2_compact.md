| Data | Index | QPS @0.90 (config) | Config @0.95 | QPS @0.95 | Recall @0.95 | Build s | Size MB | B/vector |
|---|---|---|---|---|---|---|---|---|
| SIFT | HNSW | 8,581 (M16/ef32) | M16/ef64 | 4,775 | 0.970 | 60.8 | 625.9 | 656.3 |
| SIFT | IVF-Flat | 3,030 (nl4096/np32) | nl4096/np64 | 1,697 | 0.973 | 18.9 | 497.9 | 522.1 |
| SIFT | IVF-PQ | not reached | nl4096/m64/np512 | not reached (max recall 0.885) | - | 62.3 | 70.8 | 74.3 |
| GloVe | HNSW | 1,241 (M48/ef128) | M32/ef384 | 518 | 0.954 | 149.2 | 758.6 | 672.2 |
| GloVe | IVF-Flat | 995 (nl8192/np256) | nl4096/np512 | 303 | 0.967 | 18.1 | 462.1 | 409.4 |
| GloVe | IVF-PQ | not reached | nl1024/m50/np512 | not reached (max recall 0.863) | - | 35.4 | 66.0 | 58.4 |

Single-thread test QPS (median of 3) at recall@10 0.90 and 0.95, and test recall, build time (20 threads) and index size at the 0.95 config. Configs chosen on tune queries; IVF-PQ shows its highest-recall config.
