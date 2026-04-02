"""Read-only queries for the command line."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from clickhouse_connect.driver.client import Client

if TYPE_CHECKING:
    from wgra.detect.long_term import LongTermTrend
    from wgra.detect.short_term import Trend

Bucket = Literal["hour", "day", "week"]

# a scope is a group from config.yaml or a single subreddit
_SCOPE = (
    "subreddit IN (SELECT subreddit FROM subreddit_groups WHERE group_name = {scope:String} "
    "UNION ALL SELECT {scope:String})"
)


@dataclass(frozen=True)
class TermPoint:
    bucket: date | datetime
    docs: int
    authors: int
    total_docs: int

    @property
    def per_thousand(self) -> float:
        return 1000 * self.docs / self.total_docs if self.total_docs else 0.0


def normalize_term(term: str) -> str:
    return " ".join(term.lower().split())


def normalize_scope(scope: str) -> str:
    return scope.strip().removeprefix("/").removeprefix("r/").lower()


def term_series(
    client: Client, term: str, scope: str, days: int, bucket: Bucket = "day"
) -> list[TermPoint]:
    """How many comments and posts in the scope mentioned the term, per hour, day or week
    (ISO weeks, Monday to Sunday UTC, the current one so far)."""
    if bucket in ("day", "week"):
        term_table = "term_daily"
        term_bucket = "day" if bucket == "day" else "toMonday(day)"
        scope_bucket = "toDate(hour)" if bucket == "day" else "toMonday(hour)"
        term_filter = "day >= today() - {days:UInt32}"
        scope_filter = "hour >= toDateTime(today() - {days:UInt32}, 'UTC')"
        if bucket == "week":
            # whole weeks only
            term_filter = "day >= toMonday(today() - {days:UInt32})"
            scope_filter = "hour >= toDateTime(toMonday(today() - {days:UInt32}), 'UTC')"
    else:
        term_table, term_bucket, scope_bucket = "term_hourly", "hour", "hour"
        term_filter = scope_filter = "hour >= toStartOfHour(now()) - INTERVAL {days:UInt32} DAY"

    sql = f"""
        SELECT s.bucket, t.docs, t.authors, s.docs
        FROM (
            SELECT {scope_bucket} AS bucket, sum(docs) AS docs
            FROM scope_hourly
            WHERE {_SCOPE} AND {scope_filter}
            GROUP BY bucket
        ) AS s
        LEFT JOIN (
            SELECT {term_bucket} AS bucket, sum(docs) AS docs,
                   uniqCombinedMerge(12)(authors) AS authors
            FROM {term_table}
            WHERE {_SCOPE} AND term = {{term:String}} AND {term_filter}
            GROUP BY bucket
        ) AS t USING bucket
        ORDER BY s.bucket
    """
    rows = client.query(
        sql,
        parameters={"term": normalize_term(term), "scope": normalize_scope(scope), "days": days},
    ).result_rows
    return [TermPoint(bucket, docs, authors, total) for bucket, docs, authors, total in rows]


def ingestion_status(client: Client) -> dict[str, Sequence[Sequence[Any]]]:
    feeds = client.query(
        """
        SELECT feed, count() AS polls, countIf(status != 200) AS errors, sum(new_items) AS new,
               sum(gap) AS gaps, round(avg(interval_s), 1) AS interval_s,
               round(argMax(rate, ts) * 60) AS per_minute, max(ts) AS last_poll
        FROM polls WHERE ts > now() - INTERVAL 1 HOUR
        GROUP BY feed ORDER BY feed
        """
    ).result_rows
    subreddits = client.query(
        """
        SELECT subreddit, sumIf(docs, source = 'comment') AS comments,
               sumIf(docs, source = 'post') AS posts
        FROM scope_hourly
        WHERE hour >= now() - INTERVAL 24 HOUR
          AND subreddit IN (SELECT subreddit FROM subreddit_groups WHERE group_name = 'tracked')
        GROUP BY subreddit ORDER BY comments DESC
        """
    ).result_rows
    tables = client.query(
        """
        SELECT table, sum(rows) AS rows, formatReadableSize(sum(bytes_on_disk)) AS size
        FROM system.parts WHERE active AND database = currentDatabase()
        GROUP BY table ORDER BY sum(bytes_on_disk) DESC
        """
    ).result_rows
    return {"feeds": feeds, "subreddits": subreddits, "tables": tables}


def latest_trends(
    client: Client, horizon: str, scope: str | None = None, limit: int = 30
) -> tuple[datetime | None, list[Trend]]:
    """The trends of the analyzer's most recent run, strongest first."""
    from wgra.detect.short_term import TREND_COLUMNS, Trend

    latest = client.query(
        "SELECT max(detected_at), count() FROM trends WHERE horizon = {horizon:String}",
        parameters={"horizon": horizon},
    ).result_rows[0]
    if not latest[1]:
        return None, []
    rows = client.query(
        f"""
        SELECT {", ".join(TREND_COLUMNS)}
        FROM trends FINAL
        WHERE horizon = {{horizon:String}} AND detected_at = {{detected_at:DateTime('UTC')}}
          AND subsumed_by = '' AND ({{scope:String}} = '' OR scope = {{scope:String}})
        ORDER BY z DESC
        LIMIT {{limit:UInt32}}
        """,
        parameters={
            "horizon": horizon,
            "detected_at": latest[0],
            "scope": normalize_trend_scope(scope) if scope else "",
            "limit": limit,
        },
    ).result_rows
    return latest[0], [Trend(*row) for row in rows]


def normalize_trend_scope(scope: str) -> str:
    """Groups are plain names, subreddits "r/name" (as stored in the trends table)."""
    scope = scope.strip().removeprefix("/")
    return f"r/{scope[2:].lower()}" if scope.lower().startswith("r/") else scope


def latest_long_term(
    client: Client, horizon: str, scope: str | None = None, limit: int = 30
) -> tuple[date | None, list[LongTermTrend]]:
    """The long-term trends of the latest analyzed week, by category and strength."""
    from wgra.detect.long_term import LONG_TERM_COLUMNS, LongTermTrend

    (week,) = client.query(
        "SELECT max(week) FROM long_term_trends WHERE horizon = {horizon:String}",
        parameters={"horizon": horizon},
    ).result_rows[0]
    rows = client.query(
        f"""
        SELECT {", ".join(LONG_TERM_COLUMNS)}
        FROM long_term_trends FINAL
        WHERE horizon = {{horizon:String}} AND week = {{week:Date}}
          AND ({{scope:String}} = '' OR scope = {{scope:String}})
        ORDER BY category, rank, scope
        LIMIT {{limit:UInt32}}
        """,
        parameters={
            "horizon": horizon,
            "week": week,
            "scope": normalize_trend_scope(scope) if scope else "",
            "limit": limit,
        },
    ).result_rows
    if not rows:
        return None, []
    return week, [LongTermTrend(*row) for row in rows]
