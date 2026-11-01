from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from undercurrent.web.models import Ingestion, IngestionSeries
from undercurrent.web.queries import Db
from undercurrent.web.queries import ingestion as queries
from undercurrent.web.queries.ingestion import IngestionQuery
from undercurrent.web.routes import database

router = APIRouter(tags=["ingestion"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/ingestion")
def ingestion(query: Annotated[IngestionQuery, Query()], db: DbDep) -> Ingestion:
    """Collection health: polls, gaps, volume per channel, storage."""
    return queries.ingestion(db, query)


@router.get("/ingestion/series")
def ingestion_series(query: Annotated[IngestionQuery, Query()], db: DbDep) -> IngestionSeries:
    """New items per minute per feed, and requests, errors and gaps per minute."""
    return queries.series(db, query)
