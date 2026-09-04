#!/usr/bin/env python3
"""Submit a small, harmless JCL job through the card reader and watch the
printer output fill in as the job runs."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hera_client import find_device, get, post

JCL = [
    "//SCRATCH  JOB (ACCT),'HERA API',CLASS=A,MSGCLASS=A",
    "//STEP1    EXEC PGM=IEFBR14",
    "/*",
]

rdr = find_device("RDR")
rdr_index = rdr["index"]
print(f"Card reader is device index {rdr_index}")

post(f"/devices/{rdr_index}/reader/load", {"lines": JCL})
post(f"/devices/{rdr_index}/reader/submit")
print("Job submitted.")

prt = find_device("PRT")
prt_index = prt["index"]
print(f"Watching printer at device index {prt_index} for output...")

seen = 0
for _ in range(15):
    time.sleep(2)
    lines = get(f"/devices/{prt_index}/printer/output")["lines"]
    if len(lines) > seen:
        for line in lines[seen:]:
            print(line)
        seen = len(lines)
