#!/usr/bin/env python3
"""Navigate a 3270 panel by checking the cursor position and the
protected/unprotected field map before typing into it, instead of guessing.

GET /devices/{index}/dsp3270/screen returns both the cursor position and a
per-cell protected grid — exactly what was missing when Hera's Erase Input
bug (see bugs.md) was root-caused: without it, a script can only guess
where a field starts and ends."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

# Occurrence 1: 0700 is the operator/VTAM console, 0701 is the terminal a
# real user would already be logged into TSO on (see 04_tso_login_and_time.sh).
dsp = find_device("DSP", occurrence=1)
index = dsp["index"]


def screen():
    return get(f"/devices/{index}/dsp3270/screen")


def cursor_in_unprotected_field(s):
    row, col = s["cursor"]["row"], s["cursor"]["col"]
    return not s["protected"][row][col]


print("Starting ISPF...")
post(f"/devices/{index}/dsp3270/type_text", {"text": "ISPF\n"})
time.sleep(2)

print("Tabbing until the cursor lands in an unprotected (input) field...")
for _ in range(10):
    s = screen()
    if cursor_in_unprotected_field(s):
        print(f"Landed in an input field at row={s['cursor']['row']} col={s['cursor']['col']}")
        break
    post(f"/devices/{index}/dsp3270/aid", {"key": "tab"})
    time.sleep(0.3)
else:
    raise SystemExit("Never found an unprotected field")

post(f"/devices/{index}/dsp3270/type_text", {"text": "3\n"})
time.sleep(2)
print("\n".join(screen()["lines"]))
