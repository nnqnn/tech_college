#!/usr/bin/env bash
set -euo pipefail

mkdir -p results
CSV=${CSV:-results/results.csv}
DURATION=${DURATION:-20}
PRODUCERS=${PRODUCERS:-1}
CONSUMERS=${CONSUMERS:-1}
BROKERS=${BROKERS:-"rabbit redis"}
SIZES=${SIZES:-"128 1024 10240 102400"}
RATES=${RATES:-"1000 5000 10000"}

rm -f "$CSV"

for broker in $BROKERS; do
  for size in $SIZES; do
    for rate in $RATES; do
      python bench.py \
        --broker "$broker" \
        --payload-size "$size" \
        --rate "$rate" \
        --duration "$DURATION" \
        --producers "$PRODUCERS" \
        --consumers "$CONSUMERS" \
        --csv "$CSV"
    done
  done
done

echo "saved to $CSV"
