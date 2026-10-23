"""Single-thread setup, single-query and batch timing (median of repeats).

Timed searches run single-threaded and pinned to one logical CPU (``config.PIN_CPU``, a P-core on
the report machine) via psutil cpu_affinity; the previous affinity is restored afterwards. Pinning
is a no-op where unsupported (macOS). The pinned CPU is recorded in results.csv ``extra``.

Not implemented yet (implementation.md, Step 4).
"""
