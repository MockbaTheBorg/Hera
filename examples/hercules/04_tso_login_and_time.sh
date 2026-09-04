#!/usr/bin/env bash
# Log into TSO on the 0701 3270 terminal and run the TIME command, purely
# via the API — no device selection, no click, no keystroke animation.
#
# 0700 is the operator/VTAM console; 0701 is the terminal wired to a real
# TSO/E LOGON application, hence occurrence 1 of the DSP devclass.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

index=$(find_device_index DSP 1)
echo "3270 terminal is device index $index (0701)"

api_post "/devices/$index/dsp3270/type_text" '{"text": "LOGON IBMUSER\n"}' > /dev/null
sleep 2

# Cursor lands in the Password field automatically once Userid is filled.
api_post "/devices/$index/dsp3270/type_text" '{"text": "SYS1\n"}' > /dev/null
sleep 2

api_post "/devices/$index/dsp3270/type_text" '{"text": "TIME\n"}' > /dev/null
sleep 2

echo "Screen after TIME:"
api_get "/devices/$index/dsp3270/screen" | jq -r '.lines[]'
