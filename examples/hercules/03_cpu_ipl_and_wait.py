#!/usr/bin/env python3
"""IPL the CPU at a given address and poll its status until it settles.

WARNING: this actually IPLs the guest OS — only run it against a machine
you intend to (re)boot. Address defaults to 0A80; override with argv[1].
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

address = sys.argv[1] if len(sys.argv) > 1 else "0A80"

cpu = find_device("CPU")
index = cpu["index"]
print(f"CPU is device index {index}; IPLing at {address}")

post(f"/devices/{index}/cpu/ipl", {"address": address})

for _ in range(30):
    time.sleep(2)
    state = get(f"/devices/{index}/cpu/state")
    print("status:", state["status_text"])
    if any(word in state["status_text"].lower() for word in ("wait", "running")):
        break
