| Data | Index | Config | QPS | Recall | Build s | Size MB | B/vector |
|---|---|---|---|---|---|---|---|
| SIFT | HNSW | M16/ef64 | 4,775 | 0.970 | 60.8 | 625.9 | 656.3 |
| SIFT | IVF-Flat | nl4096/np64 | 1,697 | 0.973 | 18.9 | 497.9 | 522.1 |
| SIFT | IVF-PQ | nl4096/m64/np512 | not reached (max recall 0.885) | - | 62.3 | 70.8 | 74.3 |
| GloVe | HNSW | M32/ef384 | 518 | 0.954 | 149.2 | 758.6 | 672.2 |
| GloVe | IVF-Flat | nl4096/np512 | 303 | 0.967 | 18.1 | 462.1 | 409.4 |
| GloVe | IVF-PQ | nl1024/m50/np512 | not reached (max recall 0.863) | - | 35.4 | 66.0 | 58.4 |

Operating points at recall@10 0.95: single-thread test QPS (median of 3), test recall, build time (20 threads), index size. Config chosen on tune queries; IVF-PQ shows its highest-recall config.
