#!/usr/bin/env bash
# Send PF3 (Exit) to back out of whatever ISPF panel is currently showing
# on a 3270 terminal — useful for scripted recovery from a stuck screen.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

# Occurrence 1: 0700 is the operator/VTAM console, 0701 runs ISPF.
index=$(find_device_index DSP 1)
echo "Sending PF3 to device index $index (0701)..."
api_post "/devices/$index/dsp3270/aid" '{"key": "pf3"}'
sleep 1
api_get "/devices/$index/dsp3270/screen" | jq -r '.lines[]'
