"""What every source hands the shared pipeline, and the interface between them.

A source owns its schedule, its request budget and its restart state, and runs forever.
It turns what its platform returns into `Item`s and hands them to the `Sink` with the
rows of its polls. The sink is the shared part: the copypasta filter, terms, intents,
the author hash and buffered writes (ingest/pipeline.py and ingest/writer.py).
"""

from __future__ import annotations

import asyncio
from dataclasses import astuple, dataclass, fields
from datetime import datetime
from typing import Any, Protocol

from clickhouse_connect.driver.client import Client


@dataclass(frozen=True, slots=True)
class Item:
    """A document: a comment or a post."""

    # unique within its platform: reddit's fullname, "t1_abc"
    id: str
    platform: str
    # where its counts go: "r/technology", "r/all", "r/_search"
    channel: str
    # comment | post
    doc_type: str
    # as the platform writes it, "" when unknown or deleted
    author: str
    created_at: datetime
    text: str
    url: str
    # the channel's language, unless the item says otherwise
    lang: str
    # why the source drops it: bot, moderation, deleted
    skip: str | None = None


@dataclass(frozen=True, slots=True)
class Poll:
    """One request to a platform, for the ingestion health dashboard (the polls table)."""

    ts: datetime
    platform: str
    feed: str
    # comments | posts
    kind: str
    # a sample that is never complete, like r/all
    sample: bool
    # http status, 0 for network errors
    status: int
    items: int
    new_items: int
    gap: bool
    # how far the platform's id sequence advanced since the last poll
    id_span: int
    latency_ms: int
    interval_s: float
    # estimated items per second
    rate: float
    ratelimit_remaining: float

    def row(self) -> tuple[Any, ...]:
        return astuple(self)


POLL_COLUMNS = tuple(f.name for f in fields(Poll))


class Sink(Protocol):
    """The shared part: dedup, terms, intents, buffered writes."""

    # for restart state and lookups
    client: Client

    def add(self, item: Item) -> bool:
        """Stores the item's rows, False when it's skipped."""
        ...

    def add_poll(self, poll: Poll) -> None: ...


class Source(Protocol):
    platform: str

    async def run(self, sink: Sink, stop: asyncio.Event) -> None:
        """Collects until `stop` is set."""
        ...
