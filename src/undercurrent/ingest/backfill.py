"""Counts the intents of the raw items still stored (48 hours), once, after an upgrade.

Intents can only be extracted from raw text, which is deleted after 48 hours. When the
ingester starts extracting them, the items it stored before still have their text for up
to two days: `undercurrent backfill-intents --before <when the new ingester started>` counts their
intents into term_events (and so term_hourly and term_daily). Only intent rows are
inserted, the words of those items were counted when they were ingested. Their `intents`
column stays empty (rewriting items would count them again in scope_hourly), so the
dashboards' examples start with the new ingester.

Run it once: running it twice counts the intents twice.

`--copy-items` also copies the items themselves, for building a separate database to try
things on (the default target is the configured database, CLICKHOUSE_DB).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from clickhouse_connect.driver.client import Client

from undercurrent.config import Config
from undercurrent.detect.short_term import as_utc
from undercurrent.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS
from undercurrent.text.intents import INTENT_KINDS, configure_names, extract_intents
from undercurrent.text.terms import clean

log = logging.getLogger(__name__)

BATCH_ROWS = 50_000

SOURCE_SQL = """
SELECT id, platform, channel, doc_type, created_at, author_hash, text, url, lang, token_count
FROM {database:Identifier}.items FINAL
WHERE ingested_at < toDateTime({before:UInt32}, 'UTC')
ORDER BY created_at
"""


@dataclass
class BackfillResult:
    items: int = 0
    with_intents: int = 0
    term_rows: int = 0
    kinds: Counter[str] = field(default_factory=Counter)


def item_intents(config: Config, channel: str, lang: str, text: str) -> Counter[tuple[str, str]]:
    """What the ingester would count for the item now (pipeline.Processor)."""
    if not config.counts_intents(channel):
        return Counter()
    return extract_intents(clean(text), lang)


def backfill_intents(
    source: Client,
    target: Client,
    config: Config,
    before: datetime,
    source_database: str,
    copy_items: bool = False,
    dry_run: bool = False,
) -> BackfillResult:
    result = BackfillResult()
    term_rows: list[tuple] = []
    items: list[tuple] = []
    configure_names(config.radar.names)

    def flush() -> None:
        if dry_run:
            term_rows.clear()
            items.clear()
            return
        if items:
            target.insert("items", items, column_names=list(ITEM_COLUMNS))
            items.clear()
        if term_rows:
            target.insert("term_events", term_rows, column_names=list(TERM_COLUMNS))
            term_rows.clear()

    with source.query_rows_stream(
        SOURCE_SQL,
        parameters={"database": source_database, "before": int(before.timestamp())},
    ) as stream:
        for row in stream:
            # naive datetimes from ClickHouse are UTC; inserted naive, they'd be read as local
            row = (*row[:4], as_utc(row[4]), *row[5:])
            _, _, channel, doc_type, created_at, author_hash, text, _, lang, _ = row
            result.items += 1
            counts = item_intents(config, channel, lang, text)
            hour = created_at.replace(minute=0, second=0, microsecond=0)
            for (kind, term), occurrences in counts.items():
                term_rows.append((hour, channel, doc_type, kind, term, author_hash, occurrences))
                result.kinds[kind] += 1
            if counts:
                result.with_intents += 1
            result.term_rows += len(counts)
            if copy_items:
                found = sorted(term for kind, term in counts if kind in INTENT_KINDS)
                items.append((*row, found))
            if len(term_rows) + len(items) >= BATCH_ROWS:
                flush()
                log.info("%d items read, %d intents", result.items, result.term_rows)
    flush()
    return result
