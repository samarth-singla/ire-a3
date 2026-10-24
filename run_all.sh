#!/usr/bin/env bash
# One-command reproduction of every number, figure and table in the report.
#
#   bash run_all.sh            full mode  -> results/        (about 3.5 h on the report laptop)
#   bash run_all.sh --quick    quick mode -> results_quick/  (first 100K vectors, < 15 min)
#   bash run_all.sh --resume   continue an interrupted run without re-timing finished points
#
# By default Parts 2-4 re-time everything (--fresh), replacing only their own rows in
# results.csv; results.csv itself is never deleted. Quick mode never writes to results/.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

QUICK=""; FRESH="--fresh"
for arg in "$@"; do
  case "$arg" in
    --quick)  QUICK="--quick" ;;
    --resume) FRESH="" ;;
    *) echo "usage: bash run_all.sh [--quick] [--resume]" >&2; exit 2 ;;
  esac
done

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

export OMP_NUM_THREADS=1        # search timing is single-threaded; builders raise it internally
export PYTHONUNBUFFERED=1
OUT="results"; [[ -n "$QUICK" ]] && OUT="results_quick"
mkdir -p "$OUT"
TIMES="$OUT/run_times.txt"
echo "# run_all.sh ${*:-} started $(date '+%Y-%m-%d %H:%M:%S')" > "$TIMES"
T_ALL=$(date +%s)

step() {   # step <name> <command...>: run, time, record
  local name="$1"; shift
  echo; echo "==================== $name: $*"
  local t0; t0=$(date +%s)
  "$@"
  local dt=$(( $(date +%s) - t0 ))
  printf '%-10s %6ds  (%dm%02ds)\n' "$name" "$dt" $((dt / 60)) $((dt % 60)) | tee -a "$TIMES"
}

step download bash scripts/download_data.sh
step env      python scripts/env_info.py $QUICK
step tests    python -m pytest -q
step part1    python experiments/part1_exact.py $QUICK
step part2    python experiments/part2_benchmark.py $QUICK $FRESH
step part3    python experiments/part3_experiment.py $QUICK $FRESH
step part4    python experiments/part4_experiment.py $QUICK $FRESH
step q4       python experiments/q4_projection.py $QUICK
step tables   python experiments/make_tables.py $QUICK

DT=$(( $(date +%s) - T_ALL ))
printf '%-10s %6ds  (%dm%02ds)\n' "TOTAL" "$DT" $((DT / 60)) $((DT % 60)) | tee -a "$TIMES"
echo; echo "Done. See $OUT/ (per-step times in $TIMES)"
