from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from wgra.web.models import Meta
from wgra.web.queries import Db
from wgra.web.queries import meta as queries
from wgra.web.routes import database

router = APIRouter(tags=["meta"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/meta")
def meta(request: Request, db: DbDep) -> Meta:
    """Scopes, kinds and document types for the pickers, and the server's settings."""
    return queries.meta(db, request.app.state.settings.grafana_url)
