"""Record machine specs and library versions to results/env.json (and print them).

The report must state the CPU, cores, RAM, OS, Python version and numpy/faiss/hnswlib versions.
Usage: python scripts/env_info.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil  # noqa: E402

import config  # noqa: E402


def cpu_model() -> str:
    """Best-effort CPU model name on Windows, Linux and macOS."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        if system == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        if system == "Darwin":
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def lib_version(name: str) -> str | None:
    try:
        mod = __import__(name)
    except Exception:
        return None
    return getattr(mod, "__version__", "unknown")


def collect() -> dict:
    freq = psutil.cpu_freq()
    info = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cpu_model": cpu_model(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "cpu_max_mhz": round(freq.max, 1) if freq else None,
        "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 2),
        "os": platform.platform(),
        "python": platform.python_version(),
        "numpy": lib_version("numpy"),
        "faiss": lib_version("faiss"),
        "hnswlib": lib_version("hnswlib"),
        "h5py": lib_version("h5py"),
        "pandas": lib_version("pandas"),
        "matplotlib": lib_version("matplotlib"),
    }
    try:
        import faiss
        info["faiss_max_threads"] = faiss.omp_get_max_threads()
    except Exception:
        info["faiss_max_threads"] = None
    info.update(blas_info())
    return info


def blas_info() -> dict:
    """BLAS / OpenMP libraries actually loaded by numpy + FAISS (threadpoolctl), plus the conda
    libblas build string when running under conda."""
    out = {"blas": None, "blas_libraries": [], "conda_libblas": None}
    try:
        import faiss  # noqa: F401  (load FAISS's libraries too)
        from threadpoolctl import threadpool_info
        libs = [{k: lib.get(k) for k in ("user_api", "internal_api", "version",
                                          "threading_layer", "num_threads", "filepath")}
                for lib in threadpool_info()]
        out["blas_libraries"] = libs
        blas = [lib for lib in libs if lib["user_api"] == "blas"]
        out["blas"] = ", ".join(f"{b['internal_api']} {b['version']}"
                                + (f" ({b['threading_layer']})" if b["threading_layer"] else "")
                                for b in blas) or None
    except Exception as e:                       # threadpoolctl missing or failed
        out["blas"] = f"unknown ({e.__class__.__name__})"
    meta = Path(sys.prefix) / "conda-meta"
    if meta.is_dir():
        hits = sorted(p.stem for p in meta.glob("libblas-*.json"))
        out["conda_libblas"] = hits[0] if hits else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="write to the quick-mode results dir")
    args = ap.parse_args()

    out_dir = config.get_config(args.quick)["RESULTS_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)
    info = collect()
    (out_dir / "env.json").write_text(json.dumps(info, indent=2))

    width = max(len(k) for k in info)
    for key, val in info.items():
        print(f"{key:<{width}}  {val}")
    print(f"-> wrote {out_dir / 'env.json'}")


if __name__ == "__main__":
    main()
