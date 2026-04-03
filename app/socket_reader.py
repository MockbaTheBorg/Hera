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
        self._state_lock = threading.Lock()
        self._disconnect_generation = 0
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._is_connected = False

    def start(self) -> None:
        thread: Optional[threading.Thread] = None
        with self._state_lock:
            self._running = True
            self._connect_enabled = True
            if self._thread is not None and self._thread.is_alive():
                return
            thread = threading.Thread(
                target=self._run,
                daemon=True,
                name=self._thread_name,
            )
            self._thread = thread
        thread.start()

    def connect_socket(self) -> None:
        with self._state_lock:
            self._running = True
            self._connect_enabled = True
            should_start = self._thread is None or not self._thread.is_alive()
        if should_start:
            self.start()

    def disconnect_socket(self) -> None:
        sock = self._detach_socket(disable_connect=True, stop_running=False)
        self._set_connected(False)
        self._close_socket(sock)

    def stop(self) -> None:
        thread = self._thread
        sock = self._detach_socket(disable_connect=True, stop_running=True)
        self._set_connected(False)
        self._close_socket(sock)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._join_timeout())
            if thread.is_alive():
                self._logger.warning("%s did not stop cleanly", self._thread_name)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _set_connected(self, connected: bool) -> None:
        if connected == self._is_connected:
            return
        self._is_connected = connected
        self.connected_changed.emit(connected)

    def _join_timeout(self) -> float:
        return max(
            1.0,
            self._connect_timeout + self._recv_timeout + self._reconnect_delay + 0.5,
        )

    def _detach_socket(self, *, disable_connect: bool, stop_running: bool) -> Optional[socket.socket]:
        with self._state_lock:
            if stop_running:
                self._running = False
            if disable_connect:
                self._connect_enabled = False
                self._disconnect_generation += 1
            sock = self._sock
            self._sock = None
            return sock

    def _close_socket(self, sock: Optional[socket.socket]) -> None:
        if sock is None:
            return
        try:
            sock.close()
        except Exception:
            pass

    def _register_socket(self, sock: socket.socket, generation: int) -> bool:
        with self._state_lock:
            if (
                not self._running
                or not self._connect_enabled
                or self._disconnect_generation != generation
            ):
                return False
            self._sock = sock
            return True

    def _release_socket(self, sock: socket.socket) -> None:
        with self._state_lock:
            if self._sock is sock:
                self._sock = None

    def _thread_should_run(self) -> tuple[bool, bool, int]:
        with self._state_lock:
            return self._running, self._connect_enabled, self._disconnect_generation

    def _run(self) -> None:
        try:
            while True:
                running, connect_enabled, generation = self._thread_should_run()
                if not running:
                    break
                if not connect_enabled:
                    self._set_connected(False)
                    time.sleep(0.1)
                    continue
                sock: Optional[socket.socket] = None
                try:
                    with socket.create_connection(
                        (self._host, self._port),
                        timeout=self._connect_timeout,
                    ) as sock:
                        sock.settimeout(self._recv_timeout)
                        if not self._register_socket(sock, generation):
                            continue
                        self._set_connected(True)
                        buf = b""
                        while True:
                            running, connect_enabled, _ = self._thread_should_run()
                            if not running or not connect_enabled:
                                break
                            with self._state_lock:
                                owns_socket = self._sock is sock
                            if not owns_socket:
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
                    if sock is not None:
                        self._release_socket(sock)
                    self._set_connected(False)
                running, connect_enabled, _ = self._thread_should_run()
                if running and connect_enabled:
                    time.sleep(self._reconnect_delay)
        finally:
            with self._state_lock:
                if self._thread is threading.current_thread():
                    self._thread = None
