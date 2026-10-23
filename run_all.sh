#!/usr/bin/env bash
# One-command reproduction: bash run_all.sh [--quick]
set -euo pipefail

# --- check the Python environment before doing anything else
if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: 'python' not found on PATH. Activate the env first: conda activate ire-a3" >&2
  exit 1
fi
echo "Using python: $(command -v python)"
python -c "import sys; print('  ', sys.executable, sys.version.split()[0])"
if ! python -c "import faiss" >/dev/null 2>&1; then
  echo "ERROR: 'import faiss' failed with this python." >&2
  echo "  Activate the project env (conda activate ire-a3) or install it:" >&2
  echo "    conda env create -f environment.yml    # or: pip install -r requirements.txt" >&2
  exit 1
fi

# --- pipeline: not implemented yet (implementation.md, Step 11)
echo "run_all.sh: pipeline not implemented yet (Step 11)." >&2
exit 1
