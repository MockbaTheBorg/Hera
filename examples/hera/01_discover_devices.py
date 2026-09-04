#!/usr/bin/env python3
"""Python version of 01_discover_devices.sh — same two calls, kept
functionally identical, to compare the curl+jq idiom against requests+json."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import get

print("== Devices ==")
print(json.dumps(get("/devices"), indent=2))

print("\n== Capabilities (route table) ==")
print(json.dumps(get("/capabilities"), indent=2))
