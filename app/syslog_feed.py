# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
SyslogFeed — single point of access for all Hercules syslog reads and command dispatches.

Maintains a byte-offset console index (_con_idx) and serialises all HTTP calls
through a single threading.Lock so that concurrent poll and command calls cannot
interleave.
"""

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import HerculesAPI


class SyslogFeed:
    def __init__(self, api: "HerculesAPI"):
        self._api = api
        self._lock = threading.Lock()
        self._con_idx: int = -1

    def _request(self, *, command: str | None = None):
        return self._api.get_syslog(command=command, msgcount=0, index=self._con_idx)

    def pull_new(self):
        """Return new syslog lines since the last call (or all lines on first call).

        Returns:
            list[str]  — new lines (may be empty if no new messages)
            None       — API failure; _con_idx reset so next call does a full read
        """
        with self._lock:
            result = self._request()
            if result is None:
                self._con_idx = -1
                return None
            self._con_idx = result.get("index", -1)
            return result.get("syslog", [])

    def get_all(self) -> list:
        """Fetch all syslog lines from the beginning without advancing _con_idx.

        Used for initial workspace population when the workspace is opened after
        polling has already started and _con_idx has moved past the early lines.
        """
        with self._lock:
            result = self._api.get_syslog(msgcount=0, index=-1)
            if result is None:
                return []
            return result.get("syslog", [])

    def send_command(self, cmd: str) -> list:
        """Send a command to Hercules and return the response lines.

        Does NOT advance _con_idx — pull_new() is the sole owner of the index.
        The console will naturally receive these lines on its next poll tick.
        """
        with self._lock:
            result = self._request(command=cmd)
            if result is None:
                return []
            return result.get("syslog", [])
