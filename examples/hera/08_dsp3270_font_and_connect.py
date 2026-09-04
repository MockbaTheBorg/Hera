#!/usr/bin/env python3
"""Resize a 3270 terminal's font, then bounce its socket connection —
both without bringing the terminal to the front."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

dsp = find_device("DSP")
index = dsp["index"]
print(f"3270 terminal is device index {index} ({dsp['label']})")

print("Setting font size to 18px...")
post(f"/devices/{index}/dsp3270/setup", {"font_size": 18})

print("Disconnecting...")
post(f"/devices/{index}/dsp3270/disconnect")
time.sleep(1)

print("Reconnecting...")
post(f"/devices/{index}/dsp3270/connect")
# The socket connects on a background thread, same as a real Connect click —
# an immediate connected:false here would just mean the handshake isn't
# done yet, not a failure. Give it a moment, then re-check (idempotent).
time.sleep(1)
result = post(f"/devices/{index}/dsp3270/connect")
print("Connected:", result["connected"])

screen = get(f"/devices/{index}/dsp3270/screen")
print("Current screen:")
for line in screen["lines"]:
    print(line)
