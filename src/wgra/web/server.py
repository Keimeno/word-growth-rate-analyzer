"""The web dashboard: a plainer view of what the Grafana dashboards show, for every day.
Grafana stays as the pro mode.

    wgra web                      # http://localhost:3610

It serves the page in static/ and its data as JSON from /api/<endpoint> (queries.py). Read
only: every query runs with ClickHouse's readonly setting. Without WEB_PASSWORD anyone who
reaches the port sees everything, so it listens on localhost unless told otherwise.
"""

from __future__ import annotations

import base64
import gzip
import hmac
import json
import logging
import mimetypes
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import ClickHouseError

from wgra.config import Env
from wgra.store import connect
from wgra.web.queries import ENDPOINTS, Params

log = logging.getLogger(__name__)

STATIC = (Path(__file__).parent / "static").resolve()
TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".svg": "image/svg+xml",
}


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], client: Client, grafana_url: str, password: str):
        super().__init__(address, Handler)
        self.client = client
        self.grafana_url = grafana_url
        self.password = password


class Handler(BaseHTTPRequestHandler):
    server: Dashboard

    def do_GET(self) -> None:
        if not self._authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="wgra"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            self._api(path.removeprefix("/api/"))
        elif path in ("/", "/index.html"):
            self._file("index.html")
        elif path.startswith("/static/"):
            self._file(path.removeprefix("/static/"))
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def _authorized(self) -> bool:
        if not self.server.password:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            _, _, password = base64.b64decode(header.removeprefix("Basic ")).decode().partition(":")
        except ValueError:
            return False
        return hmac.compare_digest(password.encode(), self.server.password.encode())

    def _api(self, name: str) -> None:
        query = parse_qs(urlsplit(self.path).query)
        if name == "config":
            self._json({"grafana_url": self.server.grafana_url})
            return
        endpoint = ENDPOINTS.get(name)
        if endpoint is None:
            self._json({"error": f"no endpoint {name}"}, HTTPStatus.NOT_FOUND)
            return
        started = time.monotonic()
        try:
            data = endpoint(self.server.client, Params(query))
        except ValueError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except ClickHouseError as error:
            log.exception("%s failed", name)
            self._json({"error": str(error).splitlines()[0][:500]}, HTTPStatus.BAD_GATEWAY)
            return
        log.debug("%s in %.0f ms", self.path, 1000 * (time.monotonic() - started))
        self._json(data)

    def _file(self, relative: str) -> None:
        path = (STATIC / relative).resolve()
        if not path.is_relative_to(STATIC) or not path.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        kind = TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0]
        self._send(HTTPStatus.OK, path.read_bytes(), kind or "application/octet-stream")

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        self._send(status, body, "application/json")

    def _send(self, status: HTTPStatus, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header(
            "Content-Type",
            f"{kind}; charset=utf-8"
            if kind.startswith("text") or kind == "application/json"
            else kind,
        )
        # the page is small and changes with the code, the data with every run
        self.send_header("Cache-Control", "no-cache")
        if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("%s %s", self.address_string(), format % args)


def serve(env: Env, host: str, port: int, password: str = "") -> None:
    # no session: requests run in parallel, and a session takes one query at a time
    client = connect(
        env,
        autogenerate_session_id=False,
        settings={"readonly": 2, "max_execution_time": 60},
    )
    server = Dashboard((host, port), client, env.grafana_url, password)
    log.info(
        "web dashboard on http://%s:%d", "localhost" if host in ("", "0.0.0.0") else host, port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
