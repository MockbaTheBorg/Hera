#!/usr/bin/env python3
"""Turn the CPU's IPL address dials to a scratch value and back, without
ever pressing IPL and without selecting the CPU device first. If Hera is
visible, watch the dial change — this calls exactly what a manual drag
would call internally (set_ipl_address()), just with no drag animation."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

cpu = find_device("CPU")
index = cpu["index"]

original = get(f"/devices/{index}/cpu/state")["ipl_address"]
print(f"CPU is device index {index}, current IPL address {original}")

print("Setting to scratch value 0123...")
post(f"/devices/{index}/cpu/ipl_address", {"address": "0123"})
time.sleep(2)

print(f"Restoring {original}...")
post(f"/devices/{index}/cpu/ipl_address", {"address": original})
