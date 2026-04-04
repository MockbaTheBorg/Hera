# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hercules REST API client for SDL Hyperion.
Base URL: http://<host>:<port>/cgi-bin/api/v1

All methods return parsed JSON dicts/lists or None on error.
"""

import json
import requests
from typing import Optional

from .syslog_feed import SyslogFeed


class HerculesAPI:
    def __init__(self, base_url: str = "http://127.0.0.1:8081/cgi-bin/api/v1", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.syslog_feed = SyslogFeed(self)

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    @staticmethod
    def _syslog_payload(payload) -> dict:
        if isinstance(payload, dict):
            if "syslog" in payload and isinstance(payload["syslog"], list):
                payload.setdefault("index", -1)
                return payload
            for key in ("output", "lines", "messages"):
                value = payload.get(key)
                if isinstance(value, list):
                    return {"syslog": value, "index": payload.get("index", -1)}
                if isinstance(value, str):
                    return {"syslog": value.splitlines(), "index": payload.get("index", -1)}
            payload.setdefault("index", -1)
            return payload
        if isinstance(payload, list):
            return {"syslog": payload, "index": -1}
        return {"syslog": [], "index": -1}

    def test_connection(self) -> bool:
        """Return True if the Hercules API is reachable."""
        result = self._get("version")
        return result is not None

    def get_version(self) -> Optional[dict]:
        """Return Hercules version and build information."""
        return self._get("version")

    def get_cpus(self) -> Optional[dict]:
        """Return all CPU info including registers, PSW, mode, online status."""
        return self._get("cpus")

    def get_rates(self) -> Optional[dict]:
        """Return current MIPS and IO rates."""
        return self._get("rates")

    def get_devices(self) -> Optional[dict]:
        """Return list of configured devices with status."""
        return self._get("devices")

    def get_syslog(self, command: str = None, msgcount: int = 100, index: int = None) -> Optional[dict]:
        """
        Return syslog lines, optionally executing a command first.
        msgcount controls how many lines are returned.
        When msgcount==0 and index is a non-negative int, include index for incremental reads.
        """
        params = {"msgcount": msgcount}
        if command:
            params["command"] = command
        if index is not None and index >= 0 and msgcount == 0:
            params["index"] = index
        try:
            url = f"{self.base_url}/syslog"
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
        except Exception:
            return None

        try:
            payload = resp.json()
        except ValueError:
            text = resp.text.strip()
            if text:
                try:
                    payload = json.loads(text, strict=False)
                except ValueError:
                    return {"syslog": text.splitlines(), "index": -1}
            else:
                return {"syslog": [], "index": -1}
        return self._syslog_payload(payload)

    def send_command(self, command: str, msgcount: int = 100) -> Optional[list]:
        """Send a command to Hercules and return the resulting syslog lines."""
        result = self.get_syslog(command=command, msgcount=msgcount)
        if result is None:
            return None
        return result.get("syslog", [])

    def get_console_port(self, default: int = 3270) -> int:
        """Return the Hercules console socket port (CNSLPORT setting).

        Queries GET /v1/config and reads the 'cnslport' field.
        Returns ``default`` if the endpoint is unavailable or the field is absent.
        """
        result = self._get("config")
        if result:
            raw = result.get("cnslport") or result.get("CNSLPORT")
            try:
                port = int(raw)
                if 1 <= port <= 65535:
                    return port
            except (TypeError, ValueError):
                pass
        return default
