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
import mimetypes
import os
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

ROOT = Path(__file__).resolve().parents[3]

# today's page, at /classic/ until phase 3 deletes it
STATIC = (Path(__file__).parent / "static").resolve()
# the built TypeScript app: web/dist when run from the repository, /app/web-dist in the image
DIST = next(
    (
        path.resolve()
        for path in (Path(os.environ.get("WEB_DIST", "/app/web-dist")), ROOT / "web" / "dist")
        if (path / "index.html").is_file()
    ),
    None,
)
# everything is served from here; styles may be inline (charts and popovers set them)
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)
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
    # the built app (web/dist); None serves only today's page
    dist: Path | None = DIST


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
    _errors_as_400(app)

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

        @app.get("/classic/", include_in_schema=False)
        def classic() -> Response:
            return _file(STATIC, "index.html")

        dist = settings.dist

        @app.get("/{path:path}", include_in_schema=False)
        def page(path: str, request: Request) -> Response:
            """The app's files, and its index.html for every other path, so the router
            handles deep links (/t/word/claude after a reload)."""
            if dist is None:
                return _file(STATIC, "index.html") if path == "" else _not_found()
            if path.startswith("assets/"):
                # named by their content: cached for a year
                return _built(dist, path, request, "public, max-age=31536000, immutable")
            found = _built(dist, path, request, "no-cache") if path else None
            if found is not None and found.status_code == 200:
                return found
            response = _built(dist, "index.html", request, "no-cache")
            response.headers["Content-Security-Policy"] = CSP
            return response

    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    app.add_middleware(Headers)
    app.add_middleware(BasicAuth, password=settings.password)
    return app


def _errors_as_400(app: FastAPI) -> None:
    """Bad parameters are a 400 with {"error": "…"} (`invalid` below), not FastAPI's 422,
    and the schema says so, so the page's generated types do too."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = generate()
            for operations in schema["paths"].values():
                for operation in operations.values():
                    operation["responses"].pop("422", None)
            for name in ("HTTPValidationError", "ValidationError"):
                schema["components"]["schemas"].pop(name, None)
        return app.openapi_schema or {}

    app.openapi = openapi  # type: ignore[method-assign]


def _not_found() -> Response:
    return Response("not found", status_code=404, media_type="text/plain")


def _file(root: Path, relative: str) -> Response:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return _not_found()
    # the page is small and changes with the code
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def _built(root: Path, relative: str, request: Request, cache: str) -> Response:
    """A file of the build, as its .br or .gz twin when the browser takes it (the build
    writes them, web/vite.config.ts)."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return _not_found()
    headers = {"Cache-Control": cache, "Vary": "Accept-Encoding"}
    accepted = request.headers.get("accept-encoding", "")
    for encoding, suffix in (("br", ".br"), ("gzip", ".gz")):
        twin = path.with_name(path.name + suffix)
        if encoding in accepted and twin.is_file():
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            headers["Content-Encoding"] = encoding
            return FileResponse(twin, media_type=media_type, headers=headers)
    return FileResponse(path, headers=headers)


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
