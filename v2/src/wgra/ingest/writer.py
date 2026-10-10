"""Buffers rows in memory and inserts them into ClickHouse in batches."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from clickhouse_connect.driver.client import Client

from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, ProcessedItem

log = logging.getLogger(__name__)

POLL_COLUMNS = (
    "ts",
    "feed",
    "kind",
    "background",
    "status",
    "items",
    "new_items",
    "gap",
    "id_span",
    "latency_ms",
    "interval_s",
    "rate",
    "ratelimit_remaining",
)

# if ClickHouse is down for long, drop the oldest rows instead of running out of memory
MAX_BUFFERED_ROWS = 2_000_000


@dataclass
class Buffer:
    table: str
    columns: Sequence[str]
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    dropped: int = 0

    def extend(self, rows: Sequence[tuple[Any, ...]]) -> None:
        self.rows.extend(rows)
        if (overflow := len(self.rows) - MAX_BUFFERED_ROWS) > 0:
            del self.rows[:overflow]
            self.dropped += overflow


class Writer:
    def __init__(self, client: Client, flush_interval: float = 5.0):
        self._client = client
        self._flush_interval = flush_interval
        self._lock = asyncio.Lock()
        # flushed in this order: an item before its terms, so a crash in between loses
        # terms (an undercount) instead of re-ingesting the item later (an overcount)
        self.items = Buffer("items", ITEM_COLUMNS)
        self.terms = Buffer("term_events", TERM_COLUMNS)
        self.polls = Buffer("polls", POLL_COLUMNS)
        self.inserted = {"items": 0, "term_events": 0, "polls": 0}

    def add(self, processed: ProcessedItem) -> None:
        self.items.extend([processed.item_row])
        self.terms.extend(processed.term_rows)

    def add_poll(self, row: tuple[Any, ...]) -> None:
        self.polls.extend([row])

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            await self.flush()

    async def flush(self) -> bool:
        """Inserts everything buffered, returns False if an insert failed (it's retried)."""
        async with self._lock:
            for buffer in (self.items, self.terms, self.polls):
                if not buffer.rows:
                    continue
                rows = buffer.rows
                buffer.rows = []
                try:
                    await asyncio.to_thread(
                        self._client.insert, buffer.table, rows, column_names=list(buffer.columns)
                    )
                except Exception:
                    log.exception(
                        "insert into %s failed, retrying with the next flush", buffer.table
                    )
                    buffer.rows = rows + buffer.rows
                    return False
                self.inserted[buffer.table] += len(rows)
            return True
