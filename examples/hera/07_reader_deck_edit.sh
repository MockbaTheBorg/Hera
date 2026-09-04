#!/usr/bin/env bash
# Load a small deck into the card reader, read it back, flip between the
# text/card views, then clear — without ever opening the reader dialog.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

index=$(find_device_index RDR)
echo "Card reader is device index $index"

api_post "/devices/$index/reader/load" '{"lines": ["//SCRATCH JOB", "//STEP1 EXEC PGM=IEFBR14", "/*"]}' > /dev/null

echo "Deck content:"
api_get "/devices/$index/reader/deck" | jq .

echo "Toggling view..."
api_post "/devices/$index/reader/toggle_view" | jq .

echo "Clearing deck..."
api_post "/devices/$index/reader/new" > /dev/null
