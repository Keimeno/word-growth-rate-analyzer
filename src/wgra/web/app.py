"""The web dashboard: the page and its data, read only, on port 3610. Grafana stays as the
pro mode.

    wgra web                      # http://localhost:3610
    wgra web --dev --reload       # only the API, for `pnpm dev` in web/
    wgra web openapi              # the API's schema, for web/src/api/openapi.json

One FastAPI process serves the API under /api/v1/ (routes/, queries/, models.py) and the
page. Basic auth through WEB_PASSWORD guards all of it; without it anyone who reaches the
port sees everything, so it listens on localhost unless told otherwise. ClickHouse enforces
read-only: in Compose the dashboard connects as its own user (clickhouse/users.d/web.xml),
and the client asks for readonly as well.
"""

from __future__ import annotations

import base64
import hmac
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import ClickHouseError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from wgra.web import legacy
from wgra.web.routes import api

log = logging.getLogger(__name__)

STATIC = (Path(__file__).parent / "static").resolve()
# ClickHouse's error code when a query hits max_execution_time
TIMEOUT = re.compile(r"\bCode: 159\b")
# how long a response may be reused, by what it reads: the analyzer runs every 15 minutes,
# collection every minute
CACHE = [
    ("/api/v1/ingestion", "no-cache"),
    ("/api/v1/meta", "max-age=60"),
    ("/api/v1/", "max-age=60"),
    ("/api/", "no-cache"),
]


@dataclass(frozen=True)
class Settings:
    grafana_url: str = "http://localhost:3608"
    password: str = ""
    # every query as of this time instead of now: tests and the demo database
    now: datetime | None = None
    # False serves only the API (`wgra web --dev`)
    page: bool = True


def create_app(client: Client, settings: Settings) -> FastAPI:
    app = FastAPI(
        title="Undercurrent",
        summary="Early signals in online conversation: the web dashboard's API.",
        version="1",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
        # operation ids are the route functions' names: useTrends, useTrendSeries…
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.client = client
    app.state.settings = settings

    app.include_router(api())
    app.include_router(legacy.router())

    @app.exception_handler(RequestValidationError)
    def invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = [
            f"{'.'.join(str(part) for part in problem['loc'][1:])}: {problem['msg']}"
            if len(problem["loc"]) > 1
            else problem["msg"]
            for problem in error.errors()
        ]
        return JSONResponse({"error": "; ".join(problems)}, status_code=400)

    @app.exception_handler(ValueError)
    def bad_value(_: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.exception_handler(ClickHouseError)
    def database_failed(request: Request, error: ClickHouseError) -> JSONResponse:
        message = str(error)
        if TIMEOUT.search(message):
            return JSONResponse({"error": "the query took too long"}, status_code=504)
        log.exception("%s failed", request.url.path)
        return JSONResponse({"error": message.splitlines()[0][:500]}, status_code=502)

    @app.get("/api/{path:path}", include_in_schema=False)
    def unknown(path: str) -> JSONResponse:
        return JSONResponse({"error": f"no endpoint {path}"}, status_code=404)

    if settings.page:

        @app.get("/static/{path:path}", include_in_schema=False)
        def static(path: str) -> Response:
            return _file(STATIC, path)

        @app.get("/", include_in_schema=False)
        def index() -> Response:
            return _file(STATIC, "index.html")

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(Headers)
    app.add_middleware(BasicAuth, password=settings.password)
    return app


def _file(root: Path, relative: str) -> Response:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return Response("not found", status_code=404, media_type="text/plain")
    # the page is small and changes with the code
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


class BasicAuth:
    """Every request needs the password (any user name) when WEB_PASSWORD is set."""

    def __init__(self, app: ASGIApp, password: str):
        self.app = app
        self.password = password.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.password or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        response = Response(
            status_code=401, headers={"WWW-Authenticate": 'Basic realm="Undercurrent"'}
        )
        await response(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        header = dict(scope["headers"]).get(b"authorization", b"")
        if not header.startswith(b"Basic "):
            return False
        try:
            credentials = base64.b64decode(header.removeprefix(b"Basic "), validate=True)
        except ValueError:
            return False
        _, _, password = credentials.partition(b":")
        return hmac.compare_digest(password, self.password)


class Headers:
    """Caching by what a response reads, and the security headers."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        cache = next((value for prefix, value in CACHE if path.startswith(prefix)), None)

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                names = {name.lower() for name, _ in headers}
                if cache and b"cache-control" not in names:
                    headers.append((b"cache-control", cache.encode()))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"referrer-policy", b"same-origin"))
                headers.append((b"x-frame-options", b"DENY"))
            await send(message)

        await self.app(scope, receive, send_with_headers)
