#!/usr/bin/env bash
# Orderly z/OS shutdown, scripted: send S SHUTSA to the 3270 operator
# console, wait for it to drain, then terminate the emulator.
#
# WARNING: this actually shuts down the guest OS and quits Hercules. Only
# run it when you mean it.
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

dsp_index=$(find_device_index DSP)
echo "Sending S SHUTSA to device index $dsp_index..."
api_post "/devices/$dsp_index/dsp3270/type_text" '{"text": "S SHUTSA\n"}'

echo "Waiting for shutdown to complete (60s)..."
sleep 60

cpu_index=$(find_device_index CPU)
echo "Sending 'quit' to CPU (device index $cpu_index)..."
api_post "/devices/$cpu_index/cpu/command" '{"command": "quit"}'
