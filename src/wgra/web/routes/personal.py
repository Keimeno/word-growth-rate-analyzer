"""Pins and saved views. Writes only take JSON and check `Origin`, so a page on another site
can't make a logged-in browser change them: browsers send basic credentials on their own,
which is what makes cross-site requests a risk (docs/WEB-DASHBOARD.md §5.4)."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from wgra.web.models import Pin, PinIn, View, ViewIn
from wgra.web.queries import Db
from wgra.web.queries import personal as queries
from wgra.web.routes import database

router = APIRouter(tags=["personal"])
DbDep = Annotated[Db, Depends(database)]


def same_origin(request: Request) -> None:
    """A write from this dashboard's own pages: JSON, and an Origin of this host."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "writes only come from the dashboard's own pages")
    if request.method in ("PUT", "POST") and not request.headers.get("content-type", "").startswith(
        "application/json"
    ):
        raise HTTPException(415, "send JSON")


Write = Depends(same_origin)


@router.get("/pins")
def pins(db: DbDep) -> list[Pin]:
    """Pinned terms, the newest first."""
    return queries.pins(db)


@router.put("/pins", dependencies=[Write])
def pin(new: PinIn, db: DbDep, request: Request) -> Pin:
    """Pin a term."""
    return queries.pin(request.app.state.writer, db, new)


@router.delete("/pins", dependencies=[Write], status_code=204)
def unpin(
    kind: Annotated[str, Query()], term: Annotated[str, Query()], db: DbDep, request: Request
) -> Response:
    """Unpin a term."""
    queries.unpin(request.app.state.writer, db, kind, term)
    return Response(status_code=204)


@router.get("/views")
def views(db: DbDep) -> list[View]:
    """Saved views: named links to the dashboard."""
    return queries.views(db)


@router.put("/views", dependencies=[Write])
def save_view(new: ViewIn, db: DbDep, request: Request) -> View:
    """Save the url of a view under a name (an existing name is replaced)."""
    return queries.save_view(request.app.state.writer, db, new)


@router.delete("/views", dependencies=[Write], status_code=204)
def delete_view(name: Annotated[str, Query()], db: DbDep, request: Request) -> Response:
    """Delete a saved view."""
    queries.delete_view(request.app.state.writer, db, name)
    return Response(status_code=204)
