"""The entities' pages. A term is the rest of the path (`/terms/repo/ollama/ollama`), so
terms with slashes need no escaping; the routes with a suffix come first, since the term
takes everything up to it."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from undercurrent.web.models import (
    Annotations,
    EdgeDetail,
    EventDetail,
    Explanation,
    MapNode,
    ProductDetail,
    RankPoint,
    Related,
    Rhythm,
    ScopeDetail,
    SearchHit,
    SentAlert,
    SmallMultiples,
    TermEvent,
    TermSummary,
)
from undercurrent.web.queries import Db, WindowQuery, beyond
from undercurrent.web.queries import entities as queries
from undercurrent.web.queries.beyond import RankQuery, SeriesQuery
from undercurrent.web.queries.entities import (
    EdgeQuery,
    ExplainQuery,
    ProductQuery,
    TermQuery,
    TermWindowQuery,
)
from undercurrent.web.routes import database

router = APIRouter(tags=["entities"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/terms/{kind}/{term:path}/annotations")
def term_annotations(
    kind: str, term: str, query: Annotated[TermWindowQuery, Query()], db: DbDep
) -> Annotations:
    """What to mark on the term's series: runs where it trended, onsets, forecasts."""
    return queries.term_annotations(db, kind, term, query)


@router.get("/terms/{kind}/{term:path}/explain")
def term_explain(
    kind: str, term: str, query: Annotated[ExplainQuery, Query()], db: DbDep, request: Request
) -> Explanation:
    """Why it's trending: the parts of its score, the gates, the alert's outcome."""
    return queries.explain(db, request.app.state.settings.config, kind, term, query)


@router.get("/terms/{kind}/{term:path}/related")
def term_related(
    kind: str, term: str, query: Annotated[TermQuery, Query()], db: DbDep, request: Request
) -> Related:
    """Terms mentioned with it in the last 48 hours, far more than without it."""
    return beyond.related(db, request.app.state.settings.config, kind, term, query.scope)


@router.get("/terms/{kind}/{term:path}/channels")
def term_channels(
    kind: str, term: str, query: Annotated[SeriesQuery, Query()], db: DbDep
) -> SmallMultiples:
    """The term in every channel of the scope, in the order they took it up."""
    return beyond.small_multiples(db, kind, term, query)


@router.get("/terms/{kind}/{term:path}/rhythm")
def term_rhythm(kind: str, term: str, query: Annotated[TermQuery, Query()], db: DbDep) -> Rhythm:
    """When it's talked about: hour of week, and a year of days."""
    return beyond.rhythm(db, kind, term, query.scope)


@router.get("/terms/{kind}/{term:path}/events")
def term_events(kind: str, term: str, db: DbDep) -> list[TermEvent]:
    """The stories it was part of, as cascades."""
    return queries.term_events(db, kind, term)


@router.get("/terms/{kind}/{term:path}")
def term_summary(
    kind: str, term: str, query: Annotated[TermQuery, Query()], db: DbDep
) -> TermSummary:
    """Everything known about a term in a scope, summarized."""
    return queries.term_summary(db, kind, term, query.scope)


@router.get("/scopes/{scope:path}")
def scope_detail(scope: str, db: DbDep) -> ScopeDetail:
    """A scope's members, volume, and the edges where it leads or follows."""
    return queries.scope_detail(db, scope)


@router.get("/events/{kind}/{start}/{term:path}")
def event_detail(kind: str, start: datetime, term: str, db: DbDep) -> EventDetail:
    """One story: its onsets, forecasts, and every scope's share over its span."""
    return queries.event_detail(db, kind, term, start)


@router.get("/edge")
def edge_detail(query: Annotated[EdgeQuery, Query()], db: DbDep) -> EdgeDetail:
    """One leader → follower pair, its training events and its forecasts."""
    return queries.edge_detail(db, query)


@router.get("/products/{name:path}")
def product_detail(name: str, query: Annotated[ProductQuery, Query()], db: DbDep) -> ProductDetail:
    """A product as the intents mention it: switches in and out, complaints, alternatives."""
    return queries.product_detail(db, name, query)


@router.get("/alerts")
def alerts(query: Annotated[WindowQuery, Query()], db: DbDep) -> list[SentAlert]:
    """Every alert and forecast alert sent, newest first."""
    return queries.sent_alerts(db, query)


@router.get("/search")
def search(q: Annotated[str, Query(max_length=200)], db: DbDep) -> list[SearchHit]:
    """Terms starting with what was typed, for the command palette."""
    return queries.search(db, q)


@router.get("/trends/ranks")
def trend_ranks(query: Annotated[RankQuery, Query()], db: DbDep) -> list[RankPoint]:
    """A scope's top terms over the last 7 days, an hour at a time: a bump chart."""
    return beyond.ranks(db, query)


@router.get("/spread/map")
def spread_map(db: DbDep) -> list[MapNode]:
    """Where each scope usually is in a story: its median lag behind the first mover."""
    return beyond.spread_map(db)
