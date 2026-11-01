"""Today's page (static/) asks /api/<name> with the names of 85b365c. These aliases answer it
from the same queries as /api/v1/, in the shapes it knows, until the TypeScript app replaces
it (docs/WEB-DASHBOARD.md §11.2). Deleted with static/ in phase 3."""

from __future__ import annotations

import typing
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from wgra.web.queries import (
    Db,
    ScopeQuery,
    WindowQuery,
    explore,
    ingestion,
    intents,
    long_term,
    meta,
    spread,
    trends,
)
from wgra.web.routes import database


def _query[Q: BaseModel](model: type[Q], request: Request) -> Q:
    """The query string as `model`, lists from repeated or comma separated parameters."""
    params = request.query_params
    data: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        key = field.alias or name
        if key not in params:
            continue
        is_list = typing.get_origin(field.annotation) is list
        data[key] = params.getlist(key) if is_list else params[key]
    return model.model_validate(data)


def _early_warning_forecasts(db: Db, _: Request) -> dict[str, Any]:
    return {
        "pending": spread.forecasts(db),
        "cascades": [
            {**cascade.model_dump(), "cascade": [(o.scope, o.at) for o in cascade.cascade]}
            for cascade in spread.events(db)
        ],
    }


def _meta(db: Db, request: Request) -> Any:
    return meta.meta(db, request.app.state.settings.grafana_url)


Handler = Callable[[Db, Request], Any]
ALIASES: dict[str, Handler] = {
    "meta": _meta,
    "trending": lambda db, r: trends.trends(db, _query(trends.TrendQuery, r)),
    "trending-chart": lambda db, r: trends.series(db, _query(trends.TrendSeriesQuery, r)),
    "trending-digest": lambda db, r: trends.digest(db, _query(trends.TrendQuery, r)),
    "trending-alerts": lambda db, r: trends.alerts(db, _query(ScopeQuery, r)),
    "rising": lambda db, r: trends.rising(db, _query(trends.RisingQuery, r)),
    "long-term": lambda db, r: long_term.long_term(db, _query(long_term.LongTermQuery, r)),
    "early-warning": lambda db, r: spread.edges(db, _query(spread.EdgeQuery, r)),
    "early-warning-forecasts": _early_warning_forecasts,
    "early-warning-record": lambda db, r: spread.record(db, _query(WindowQuery, r)),
    "intents": lambda db, r: intents.intents(db, _query(intents.IntentQuery, r)),
    "intents-switches": lambda db, r: intents.flows(db, _query(intents.IntentQuery, r)),
    "intents-rising": lambda db, r: intents.rising(db, _query(intents.RisingIntentQuery, r)),
    "intents-needs": lambda db, r: intents.needs(db, _query(intents.IntentQuery, r)),
    "intents-examples": lambda db, r: intents.examples(db, _query(intents.ExampleQuery, r)),
    "explore": lambda db, r: explore.explore(db, _query(explore.ExploreQuery, r)),
    "explore-mentions": lambda db, r: explore.mentions(db, _query(explore.ExploreQuery, r)),
    "ingestion": lambda db, r: ingestion.ingestion(db, _query(ingestion.IngestionQuery, r)),
    "ingestion-charts": lambda db, r: ingestion.series(db, _query(ingestion.IngestionQuery, r)),
}


def router() -> APIRouter:
    legacy = APIRouter(prefix="/api", include_in_schema=False)

    @legacy.get("/config")
    def config(request: Request) -> dict[str, str]:
        return {"grafana_url": request.app.state.settings.grafana_url}

    for name, handler in ALIASES.items():
        legacy.add_api_route(f"/{name}", _answer(handler), methods=["GET"], name=f"legacy {name}")
    return legacy


def _answer(handler: Handler) -> Callable[[Request], Any]:
    def answer(request: Request) -> Any:
        return jsonable_encoder(handler(database(request), request), by_alias=True)

    return answer
