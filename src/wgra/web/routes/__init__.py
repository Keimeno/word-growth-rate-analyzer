"""The API under /api/v1/: one route per resource, each with its response model, so the
OpenAPI schema (`wgra web openapi`) describes everything the page receives. Routes are plain
`def`s: FastAPI runs them in its thread pool, on a ClickHouse client without a session, so
requests run in parallel."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from wgra.web.models import Error
from wgra.web.queries import Db, utc


def database(
    request: Request,
    as_of: Annotated[
        datetime | None,
        Query(description="show it as it was then, as far as the stored history goes"),
    ] = None,
) -> Db:
    """The request's database: as of `as_of`, the server's frozen time, or now."""
    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path).removeprefix("/api/v1")
    settings = request.app.state.settings
    now = as_of or settings.now or datetime.now(UTC)
    return Db(request.app.state.client, endpoint, utc(now).replace(microsecond=0))


# what every route can answer besides its data, all as {"error": "…"}
ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": Error, "description": "Parameters it can't read"},
    502: {"model": Error, "description": "ClickHouse failed"},
    504: {"model": Error, "description": "The query hit its time limit"},
}


def api() -> APIRouter:
    from wgra.web.routes import explore, ingestion, intents, meta, spread, trends

    router = APIRouter(prefix="/api/v1", responses=ERRORS)
    for module in (meta, trends, spread, intents, explore, ingestion):
        router.include_router(module.router)
    return router
