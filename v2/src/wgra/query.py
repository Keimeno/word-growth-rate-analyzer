"""Read-only queries for the command line."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from clickhouse_connect.driver.client import Client

Bucket = Literal["hour", "day"]

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
    """How many comments and posts in the scope mentioned the term, per hour or day."""
    if bucket == "day":
        term_table, term_bucket, scope_bucket = "term_daily", "day", "toDate(hour)"
        term_filter = "day >= today() - {days:UInt32}"
        scope_filter = "hour >= toDateTime(today() - {days:UInt32}, 'UTC')"
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
