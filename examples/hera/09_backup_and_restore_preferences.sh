#!/usr/bin/env bash
# Back up all of Hera's current preferences, change the poll interval,
# then restore the exact original document — a pattern useful before any
# scripted run that needs to temporarily change settings.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

backup=$(mktemp)
api_get /preferences > "$backup"
echo "Backed up preferences to $backup:"
cat "$backup"

echo
echo "Setting a fast poll interval for this session..."
api_post /preferences '{"poll_interval": 0.1}' > /dev/null

sleep 2

echo "Restoring original preferences..."
api_post /preferences "$(cat "$backup")" > /dev/null
rm -f "$backup"
echo "Restored."
