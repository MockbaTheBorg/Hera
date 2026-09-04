#!/usr/bin/env python3
"""Run a 1403/3211 printer entirely through the API: connect, change paper
color, trigger the built-in test printout, save it as a PDF, then discard
the buffer — none of it requires selecting the printer in the room first."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

prt = find_device("PRT")
index = prt["index"]
print(f"Printer is device index {index} ({prt['label']})")

print("Connecting...")
post(f"/devices/{index}/printer/connect")

print("Setting paper color to BLUE...")
post(f"/devices/{index}/printer/paper_color", {"color": "BLUE"})

print("Triggering test printout...")
post(f"/devices/{index}/printer/test")

print("Waiting for it to finish...")
time.sleep(5)

output = get(f"/devices/{index}/printer/output")
print(f"{len(output['lines'])} line(s) buffered")

saved = post(f"/devices/{index}/printer/save", {"path": "/tmp/hera_test_print.pdf"})
print("Saved:", saved["path"])

post(f"/devices/{index}/printer/discard")
print("Buffer discarded.")
