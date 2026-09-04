#!/usr/bin/env bash
# List every device currently shown in Hera's room, plus the full route
# table each supports. This is the "what can I even talk to right now"
# entry point — the device set depends on whichever Hercules config is
# loaded, so nothing here is hardcoded.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

echo "== Devices =="
api_get /devices | jq .

echo
echo "== Capabilities (route table) =="
api_get /capabilities | jq .
