#!/usr/bin/env bash
# List mountable tape files, mount the first one read-only, check the
# drive status, then unmount — all through /devices/{index}/tape/*.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

index=$(find_device_index TAPE)
echo "Tape drive is device index $index"

files=$(api_get "/devices/$index/tape/files")
echo "Available files:"
echo "$files" | jq .

first=$(echo "$files" | jq -r '.files[0]')
if [ "$first" = "null" ] || [ -z "$first" ]; then
    echo "No tape files found in the configured tapes folder — nothing to mount."
    exit 0
fi

echo "Mounting $first read-only..."
api_post "/devices/$index/tape/mount" "$(jq -n --arg f "$first" '{filename: $f, readonly: true}')"

api_get "/devices/$index/tape/status" | jq .

echo "Unmounting..."
api_post "/devices/$index/tape/unmount"
