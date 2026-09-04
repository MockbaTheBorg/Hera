#!/usr/bin/env bash
# Change the room's background color via /preferences — the Preferences
# dialog's OK-handler logic, run with the dialog never shown — then
# restore the original. Watch Hera's room strip recolor live.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

orig_bg=$(api_get /preferences | jq -r .room_background)
echo "Current room background: $orig_bg"

echo "Switching to a scratch color..."
api_post /preferences '{"room_background": "#3355aa"}' > /dev/null
sleep 3

echo "Restoring $orig_bg..."
api_post /preferences "$(jq -n --arg bg "$orig_bg" '{room_background: $bg}')" > /dev/null
