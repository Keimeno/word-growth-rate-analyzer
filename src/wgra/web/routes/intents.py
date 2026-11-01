from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from wgra.web.models import Flows, IntentExample, Intents, Need, RisingIntents
from wgra.web.queries import Db
from wgra.web.queries import intents as queries
from wgra.web.queries.intents import ExampleQuery, IntentQuery, RisingIntentQuery
from wgra.web.routes import database

router = APIRouter(tags=["intents"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/intents")
def intents(query: Annotated[IntentQuery, Query()], db: DbDep) -> Intents:
    """Intent mentions per kind, in all and per day."""
    return queries.intents(db, query)


@router.get("/intents/flows")
def intent_flows(query: Annotated[IntentQuery, Query()], db: DbDep) -> Flows:
    """The top switching flows, with the flow the other way."""
    return queries.flows(db, query)


@router.get("/intents/rising")
def intent_rising(query: Annotated[RisingIntentQuery, Query()], db: DbDep) -> RisingIntents:
    """An intent kind's last 7 days against the 28 before."""
    return queries.rising(db, query)


@router.get("/intents/needs")
def intent_needs(query: Annotated[IntentQuery, Query()], db: DbDep) -> list[Need]:
    """The needs mentioned most in each group and the background."""
    return queries.needs(db, query)


@router.get("/intents/examples")
def intent_examples(query: Annotated[ExampleQuery, Query()], db: DbDep) -> list[IntentExample]:
    """Comments and posts of the last 48 hours an intent was found in."""
    return queries.examples(db, query)
