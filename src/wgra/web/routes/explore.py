from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from wgra.web.models import Explore, Mention
from wgra.web.queries import Db
from wgra.web.queries import explore as queries
from wgra.web.queries.explore import ExploreQuery
from wgra.web.routes import database

router = APIRouter(tags=["explore"])
DbDep = Annotated[Db, Depends(database)]


@router.get("/explore")
def explore(query: Annotated[ExploreQuery, Query()], db: DbDep) -> Explore:
    """Terms over time: mentions, people and share, pooled and per channel."""
    return queries.explore(db, query)


@router.get("/explore/mentions")
def explore_mentions(query: Annotated[ExploreQuery, Query()], db: DbDep) -> list[Mention]:
    """Recent comments and posts with the terms (the last 48 hours)."""
    return queries.mentions(db, query)
