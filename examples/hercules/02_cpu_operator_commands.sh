#!/usr/bin/env bash
# Press the CPU panel's operator buttons (store/restart/startall/stopall/
# quit/ext) via the API instead of clicking them.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

index=$(find_device_index CPU)
echo "CPU is device index $index"

echo "Sending 'stopall'..."
api_post "/devices/$index/cpu/command" '{"command": "stopall"}'
sleep 1

echo "Sending 'startall'..."
api_post "/devices/$index/cpu/command" '{"command": "startall"}'
sleep 1

api_get "/devices/$index/cpu/state" | jq .
