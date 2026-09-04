#!/usr/bin/env bash
# Bring every device in the room to the front in turn, pausing briefly on
# each one, then return to whichever was selected first. Watch Hera's
# window while this runs — the highlighted room slot and workspace switch
# exactly as if you clicked through them by hand.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

devices=$(api_get /devices)
count=$(echo "$devices" | jq 'length')
echo "Found $count device(s)."

for ((i = 0; i < count; i++)); do
    label=$(echo "$devices" | jq -r ".[$i].label")
    echo "Selecting index $i ($label)..."
    api_post "/devices/$i/select" > /dev/null
    sleep 1
done

echo "Returning to index 0."
api_post "/devices/0/select" > /dev/null
