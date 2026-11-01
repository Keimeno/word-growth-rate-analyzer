from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from undercurrent.web.models import Cascade, Edges, Forecast, ForecastRecord, LongTerm
from undercurrent.web.queries import Db, WindowQuery
from undercurrent.web.queries import long_term as long_term_queries
from undercurrent.web.queries import spread as queries
from undercurrent.web.queries.long_term import LongTermQuery
from undercurrent.web.queries.spread import EdgeQuery
from undercurrent.web.routes import database

router = APIRouter(tags=["spread"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/long-term")
def long_term(query: Annotated[LongTermQuery, Query()], db: DbDep) -> LongTerm:
    """A scope's emerging, mainstreaming, fading and one-off terms of the latest week."""
    return long_term_queries.long_term(db, query)


@router.get("/edges")
def edges(query: Annotated[EdgeQuery, Query()], db: DbDep) -> Edges:
    """Which channels lead which, learned daily, with the layer's status."""
    return queries.edges(db, query)


@router.get("/forecasts")
def forecasts(db: DbDep) -> list[Forecast]:
    """Forecasts waiting for their follower."""
    return queries.forecasts(db)


@router.get("/forecasts/record")
def forecast_record(query: Annotated[WindowQuery, Query()], db: DbDep) -> ForecastRecord:
    """How forecasts turned out: the last 30 days, calibration, per day, Wikipedia."""
    return queries.record(db, query)


@router.get("/events")
def events(db: DbDep) -> list[Cascade]:
    """Stories of the last 14 days that reached more than one scope."""
    return queries.events(db)
