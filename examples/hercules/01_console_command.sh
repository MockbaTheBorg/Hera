#!/usr/bin/env bash
# Type a Hercules operator command into the CONSOLE device, exactly as if
# entered by hand, then read back the console log to see the response.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

index=$(find_device_index CONSOLE)
echo "Console is device index $index"

api_post "/devices/$index/console/type" '{"command": "qcpuid"}' > /dev/null

sleep 1
echo "Console log:"
api_get "/devices/$index/console/log" | jq -r .text
