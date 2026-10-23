"""Index size in bytes and bytes per vector.

``index_bytes`` is the length of the serialised index (``faiss.serialize_index``). This is the
same number of bytes ``faiss.write_index`` puts on disk, so for a cached index the file size
can be used instead of serialising a large index again.
"""
from __future__ import annotations

from pathlib import Path


def index_bytes(index) -> int:
    """Size of the serialised index in bytes."""
    import faiss
    return int(len(faiss.serialize_index(index)))


def file_bytes(path: Path) -> int:
    """Size of an index file written by ``faiss.write_index`` (equals ``index_bytes``)."""
    return int(Path(path).stat().st_size)


def bytes_per_vector(n_bytes: int, n_base: int) -> float:
    return n_bytes / n_base


def raw_bytes_per_vector(d: int) -> int:
    """Raw float32 storage for one d-dimensional vector (reference for the cost tables)."""
    return 4 * d


def pq_code_bytes(m: int, nbits: int = 8) -> float:
    """Theoretical PQ code size per vector: m sub-vectors x nbits bits."""
    return m * nbits / 8


def size_info(n_bytes: int, n_base: int, d: int, family: str, params: dict) -> dict:
    """Size fields for results / tables.

    For IVF-PQ the theoretical code size is m*nbits/8; the measured bytes/vector is larger
    because of the stored ids (8 bytes each), the coarse centroids and the PQ codebooks.
    ``ivfpq_refine`` additionally stores the raw float32 vectors for exact re-ranking.
    """
    info = {
        "index_bytes": int(n_bytes),
        "bytes_per_vector": bytes_per_vector(n_bytes, n_base),
        "raw_bytes_per_vector": raw_bytes_per_vector(d),
    }
    if family in ("ivfpq", "ivfpq_refine"):
        info["pq_code_bytes_per_vector"] = pq_code_bytes(params["m"], params.get("nbits", 8))
    if family == "ivfpq_refine":
        info["refine_raw_bytes_per_vector"] = raw_bytes_per_vector(d)
    return info
