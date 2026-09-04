"""Tiny shared client for the Hera scripting API Python examples.

Configure via environment variables:
    HERA_API_URL   base URL of Hera's scripting API (default http://127.0.0.1:8765)
    HERA_API_TOKEN bearer token, if one is set in Preferences > API (default: none)
"""
import os

import requests

BASE_URL = os.environ.get("HERA_API_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("HERA_API_TOKEN", "")


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def get(path: str, **params):
    r = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def post(path: str, body: dict | None = None):
    r = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=body or {}, timeout=10)
    r.raise_for_status()
    return r.json()


def find_device(devclass: str, occurrence: int = 0) -> dict:
    """Return the Nth device of the given devclass (CPU, CONSOLE, DSP, PRT,
    RDR, PCH, TAPE) from GET /devices, or raise if none is found."""
    matches = [d for d in get("/devices") if d["devclass"] == devclass]
    if occurrence >= len(matches):
        raise SystemExit(f"No {devclass} device at occurrence {occurrence} (found {len(matches)})")
    return matches[occurrence]
