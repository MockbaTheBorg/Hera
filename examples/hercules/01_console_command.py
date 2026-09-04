#!/usr/bin/env python3
"""Python version of 01_console_command.sh — same pattern, a different
command, to compare the curl idiom against requests."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

console = find_device("CONSOLE")
index = console["index"]
print(f"Console is device index {index}")

post(f"/devices/{index}/console/type", {"command": "devlist"})
time.sleep(1)

print(get(f"/devices/{index}/console/log")["text"])
