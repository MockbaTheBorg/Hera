# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared line-based socket reader for Hercules sockdev consumers.
"""

import logging
import socket
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal


class SocketLineReader(QObject):
    """Read newline-delimited records from a socket in a daemon thread."""

    line_received = Signal(str)
    connected_changed = Signal(bool)

    def __init__(
        self,
        host: str,
        port: int,
        parent=None,
        *,
        connect_timeout: float = 5.0,
        recv_timeout: float = 1.0,
        reconnect_delay: float = 2.0,
        encoding: str = "latin-1",
        thread_name: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._recv_timeout = recv_timeout
        self._reconnect_delay = reconnect_delay
        self._encoding = encoding
        self._thread_name = thread_name or f"SocketLineReader:{self._port}"
        self._logger = logger or logging.getLogger(__name__)
        self._running = False
        self._connect_enabled = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._is_connected = False

    def start(self) -> None:
        self._running = True
        self._connect_enabled = True
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=self._thread_name,
        )
        self._thread.start()

    def connect_socket(self) -> None:
        self._running = True
        self._connect_enabled = True
        if self._thread is None or not self._thread.is_alive():
            self.start()

    def disconnect_socket(self) -> None:
        self._connect_enabled = False
        self._set_connected(False)
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    def stop(self) -> None:
        self._running = False
        self._connect_enabled = False
        self._set_connected(False)
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _set_connected(self, connected: bool) -> None:
        if connected == self._is_connected:
            return
        self._is_connected = connected
        self.connected_changed.emit(connected)

    def _run(self) -> None:
        while self._running:
            if not self._connect_enabled:
                self._set_connected(False)
                time.sleep(0.1)
                continue
            try:
                with socket.create_connection(
                    (self._host, self._port),
                    timeout=self._connect_timeout,
                ) as sock:
                    self._sock = sock
                    self._set_connected(True)
                    sock.settimeout(self._recv_timeout)
                    buf = b""
                    while self._running:
                        if not self._connect_enabled:
                            break
                        try:
                            data = sock.recv(4096)
                        except socket.timeout:
                            continue
                        if not data:
                            break
                        buf += data
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            line = raw.decode(self._encoding).rstrip("\r")
                            self.line_received.emit(line)
            except Exception as exc:
                self._logger.debug("%s:%s - %s", self._host, self._port, exc)
            finally:
                self._sock = None
                self._set_connected(False)
            if self._running:
                time.sleep(self._reconnect_delay)
