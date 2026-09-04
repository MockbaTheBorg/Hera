# Hera - Hercules Hyperion GUI - by Mockba the Borg
#
"""Embedded HTTP server for the Hera scripting API.

Disabled by default; enabled via the [scripting_api] config section
(enabled/host/port/token), settable through the existing Config
get_setting/set_setting mechanism. Binds to 127.0.0.1 by default.
"""

import hmac
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import routes
from .errors import ApiError

logger = logging.getLogger(__name__)

_PARAM_RE = re.compile(r"\{(\w+)\}")


def _compile_path(path: str) -> re.Pattern:
    pattern = _PARAM_RE.sub(lambda m: f"(?P<{m.group(1)}>[^/]+)", path)
    return re.compile(f"^{pattern}$")


class _CompiledRoute:
    def __init__(self, spec: "routes.RouteSpec"):
        self.spec = spec
        self.compiled = _compile_path(spec.path)


class RouteContext:
    """Everything a route handler needs, bundled once at server start."""

    def __init__(self, main_window, api, bridge, config):
        self.main_window = main_window
        self.api = api
        self.bridge = bridge
        self.config = config


class ScriptingRequestHandler(BaseHTTPRequestHandler):
    server_version = "HeraScriptingAPI/1.0"

    def log_message(self, fmt, *args):
        logger.info("scripting-api %s - %s", self.address_string(), fmt % args)

    def _write_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        token = self.server.ctx.config.get_setting("scripting_api", "token", "")
        if not token:
            return True
        expected = f"Bearer {token}"
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _handle(self, method: str) -> None:
        if not self._check_auth():
            self._write_json(401, {"error": "Unauthorized"})
            return

        try:
            body = self._read_body()
        except json.JSONDecodeError:
            self._write_json(400, {"error": "Invalid JSON body"})
            return

        path = urlsplit(self.path).path
        for route in self.server.route_table:
            if route.spec.method != method:
                continue
            match = route.compiled.match(path)
            if not match:
                continue
            try:
                result = route.spec.handler(self.server.ctx, match.groupdict(), body)
                self._write_json(200, result)
            except ApiError as exc:
                self._write_json(exc.status_code, {"error": exc.message})
            except TimeoutError as exc:
                self._write_json(504, {"error": str(exc)})
            except Exception as exc:
                logger.exception("Scripting API handler error for %s %s", method, path)
                self._write_json(500, {"error": str(exc)})
            return

        self._write_json(404, {"error": f"No route for {method} {path}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class ScriptingServer:
    def __init__(self, bridge, config, api, main_window):
        self._config = config
        self._ctx = RouteContext(main_window, api, bridge, config)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._config.get_setting("scripting_api", "enabled", "0") != "1":
            return
        host = self._config.get_setting("scripting_api", "host", "127.0.0.1")
        port = int(self._config.get_setting("scripting_api", "port", "8765"))
        route_table = [_CompiledRoute(spec) for spec in routes.ROUTES]

        self._httpd = ThreadingHTTPServer((host, port), ScriptingRequestHandler)
        self._httpd.ctx = self._ctx
        self._httpd.route_table = route_table
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="HeraScriptingAPI", daemon=True
        )
        self._thread.start()
        logger.info("Scripting API listening on %s:%s", host, port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
