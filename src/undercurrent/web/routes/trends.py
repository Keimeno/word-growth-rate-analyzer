from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from undercurrent.web.models import Alert, DigestEntry, Rising, SharePoint, Trends
from undercurrent.web.queries import Db, ScopeQuery
from undercurrent.web.queries import trends as queries
from undercurrent.web.queries.trends import RisingQuery, TrendQuery, TrendSeriesQuery
from undercurrent.web.routes import database

router = APIRouter(tags=["trends"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/trends")
def trends(query: Annotated[TrendQuery, Query()], db: DbDep) -> Trends:
    """The latest run of a scope and horizon, with each term's 7-day sparkline."""
    return queries.trends(db, query)


@router.get("/trends/series")
def trend_series(query: Annotated[TrendSeriesQuery, Query()], db: DbDep) -> list[SharePoint]:
    """The 8 strongest trends of the latest run over time, per 1,000 documents."""
    return queries.series(db, query)


@router.get("/trends/digest")
def trend_digest(query: Annotated[TrendQuery, Query()], db: DbDep) -> list[DigestEntry]:
    """Each term at its strongest in the last 24 hours."""
    return queries.digest(db, query)


@router.get("/trends/alerts")
def trend_alerts(query: Annotated[ScopeQuery, Query()], db: DbDep) -> list[Alert]:
    """Alerts of the last 14 days, sent or held back."""
    return queries.alerts(db, query)


@router.get("/rising")
def rising(query: Annotated[RisingQuery, Query()], db: DbDep) -> list[Rising]:
    """The quick look: the last 24 hours against the 7 days before, without scoring."""
    return queries.rising(db, query)
