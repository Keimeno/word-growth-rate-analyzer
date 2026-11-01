"""Collection: is the ingester healthy and complete, per platform."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from undercurrent.web.models import (
    ChannelVolume,
    Feed,
    FeedRate,
    Ingestion,
    IngestionSeries,
    RequestRate,
    TableSize,
)
from undercurrent.web.queries import FROM, NOW, TO, Db, Items, WindowQuery, step

PLATFORMS = "(empty({platforms:Array(String)}) OR has({platforms:Array(String)}, platform))"
# the picked platforms' tracked channels: the group named like the platform, not r/all
TRACKED = (
    "channel IN (SELECT channel FROM channel_groups WHERE group_name IN "
    f"(SELECT platform FROM channels WHERE {PLATFORMS}))"
)


class IngestionQuery(WindowQuery):
    platforms: Items = Field([], description="only these platforms")

    def ingestion_parameters(self, db: Db) -> dict[str, Any]:
        return {**self.window(db.now, "6h"), "platforms": self.platforms}


def ingestion(db: Db, query: IngestionQuery) -> Ingestion:
    parameters = query.ingestion_parameters(db)
    status = db.one(
        f"""
        SELECT
            (SELECT sum(docs) FROM scope_hourly
             WHERE {TRACKED} AND hour >= {NOW} - INTERVAL 24 HOUR AND hour <= {NOW})
                AS documents_24h,
            (SELECT count() FROM polls
             WHERE {PLATFORMS} AND ts > {NOW} - INTERVAL 10 MINUTE AND ts <= {NOW})
                AS requests_10m,
            (SELECT sum(gap) FROM polls
             WHERE {PLATFORMS} AND ts > {NOW} - INTERVAL 24 HOUR AND ts <= {NOW}) AS gaps_24h,
            (SELECT sum(new_items) / sum(id_span) FROM polls
             WHERE platform = 'reddit' AND sample AND id_span > 0
               AND ts >= {FROM} AND ts <= {TO}) AS sampled_share,
            (SELECT maxOrNull(ts) FROM polls WHERE {PLATFORMS} AND ts <= {NOW}) AS last_poll
        """,
        parameters,
    )
    feeds = db.rows(
        f"""
        SELECT platform, feed, count() AS polls, countIf(status != 200) AS errors,
               sum(new_items) AS new_items, sum(gap) AS gaps, avg(interval_s) AS poll_every_s,
               argMax(rate, ts) * 60 AS items_per_minute, max(ts) AS last_poll
        FROM polls
        WHERE {PLATFORMS} AND ts > {NOW} - INTERVAL 1 HOUR AND ts <= {NOW}
        GROUP BY platform, feed
        ORDER BY platform, feed
        """,
        parameters,
    )
    channels = db.rows(
        f"""
        SELECT c.channel AS channel, c.platform AS platform, c.background AS background,
               c.analyzed AS analyzed, sum(s.docs) AS documents,
               arraySort(groupArrayIf((s.doc_type, s.docs), s.docs > 0)) AS by_type,
               sum(s.authors) AS authors
        FROM channels AS c
        LEFT JOIN (
            SELECT channel, doc_type, sum(docs) AS docs, uniqCombinedMerge(12)(authors) AS authors
            FROM scope_hourly
            WHERE hour >= {NOW} - INTERVAL 24 HOUR AND hour <= {NOW}
            GROUP BY channel, doc_type
        ) AS s ON s.channel = c.channel
        WHERE (empty({{platforms:Array(String)}}) OR has({{platforms:Array(String)}}, c.platform))
        GROUP BY c.channel, c.platform, c.background, c.analyzed
        ORDER BY c.platform, documents DESC, c.channel
        """,
        parameters,
    )
    storage = db.rows(
        """
        SELECT table, sum(rows) AS rows, sum(bytes_on_disk) AS bytes
        FROM system.parts
        WHERE active AND database = currentDatabase()
        GROUP BY table
        ORDER BY bytes DESC
        """,
        {},
    )
    return Ingestion(
        **status,
        feeds=[Feed.model_validate(row) for row in feeds],
        channels=[ChannelVolume.model_validate(row) for row in channels],
        storage=[TableSize.model_validate(row) for row in storage],
    )


def series(db: Db, query: IngestionQuery) -> IngestionSeries:
    """New items per minute per feed, and requests, errors and gaps per minute."""
    parameters = query.ingestion_parameters(db)
    parameters["step"] = step(parameters["to"] - parameters["from"], 60, 240)
    bucket = "toStartOfInterval(ts, toIntervalSecond({step:UInt32}))"
    items = db.rows(
        f"""
        SELECT {bucket} AS time, feed, sum(new_items) / ({{step:UInt32}} / 60) AS per_minute
        FROM polls
        WHERE {PLATFORMS} AND ts >= {FROM} AND ts <= {TO}
        GROUP BY time, feed
        ORDER BY time
        """,
        parameters,
    )
    requests = db.rows(
        f"""
        SELECT {bucket} AS time,
               count() / ({{step:UInt32}} / 60) AS requests,
               countIf(status != 200) / ({{step:UInt32}} / 60) AS errors,
               sum(gap) / ({{step:UInt32}} / 60) AS gaps
        FROM polls
        WHERE {PLATFORMS} AND ts >= {FROM} AND ts <= {TO}
        GROUP BY time
        ORDER BY time
        """,
        parameters,
    )
    return IngestionSeries(
        step=parameters["step"],
        items=[FeedRate.model_validate(row) for row in items],
        requests=[RequestRate.model_validate(row) for row in requests],
    )
