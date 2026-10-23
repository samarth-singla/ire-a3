#!/usr/bin/env bash
# Download the two ann-benchmarks datasets into data/ (skips files that already exist).
# Uses wget -c if available, otherwise curl -L -C - (Git Bash on Windows has no wget).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
mkdir -p "$DATA"

URLS=(
  "http://ann-benchmarks.com/sift-128-euclidean.hdf5"
  "http://ann-benchmarks.com/glove-100-angular.hdf5"
)

for url in "${URLS[@]}"; do
  out="$DATA/$(basename "$url")"
  if [[ -s "$out" ]]; then
    echo "[skip] $(basename "$out") already present"
    continue
  fi
  echo "[get ] $url"
  if command -v wget >/dev/null 2>&1; then
    wget -c -O "$out.part" "$url"
  else
    curl -L -C - -o "$out.part" "$url"
  fi
  mv "$out.part" "$out"
done

echo "Files in data/:"
ls -lh "$DATA"/*.hdf5
