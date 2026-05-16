#!/usr/bin/env bash
set -euo pipefail

mkdir -p results
rm -f results/results.csv results/run.log

python bench.py \
  --requests "${REQUESTS:-12000}" \
  --duration "${DURATION:-15}" \
  --csv results/results.csv

echo "saved to results/results.csv"
