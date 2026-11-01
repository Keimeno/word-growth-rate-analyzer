"""Term explorer: how often terms are mentioned over time, where, and recent examples.
Hours come from term_hourly (180 days), days and weeks from term_daily (forever); weeks are
ISO weeks, Monday to Sunday UTC."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from wgra.web.models import Bucket, Explore, ExplorePoint, ExploreWhere, Mention
from wgra.web.queries import (
    DAYS,
    FROM,
    SCOPE,
    TIME_FILTER,
    TO,
    WHOLE_DAYS,
    Db,
    Items,
    ScopeQuery,
    WindowQuery,
    step,
)


class ExploreQuery(ScopeQuery, WindowQuery):
    terms: Items = Field(description="up to 12 terms, as the detector stores them")
    bucket: Literal["auto", "hour", "day", "week"] = "auto"

    @field_validator("terms")
    @classmethod
    def _normalized(cls, terms: list[str]) -> list[str]:
        unique = list(dict.fromkeys(" ".join(term.lower().split()) for term in terms))
        if not unique:
            raise ValueError("name at least one term")
        return unique[:12]

    def explore_parameters(self, db: Db) -> dict[str, Any]:
        return {**self.parameters(), **self.window(db.now, "2d"), "terms": self.terms}


def _bucket(query: ExploreQuery, start: int, end: int) -> tuple[str, int]:
    bucket = query.bucket
    if bucket == "auto":
        days = (end - start) / 86400
        bucket = "hour" if days <= 14 else "day" if days <= 366 else "week"
    return bucket, step(end - start, 3600) if query.bucket == "auto" else 3600


def _sql(bucket: str) -> dict[str, str]:
    if bucket == "hour":
        hourly = "toStartOfInterval(hour, toIntervalSecond({step:UInt32}))"
        return {
            "table": "term_hourly",
            "term_bucket": hourly,
            "term_filter": TIME_FILTER,
            "total_bucket": hourly,
            "total_filter": TIME_FILTER,
        }
    weekly = bucket == "week"
    return {
        "table": "term_daily",
        "term_bucket": "toDateTime(toMonday(day), 'UTC')" if weekly else "toDateTime(day, 'UTC')",
        "term_filter": DAYS,
        "total_bucket": "toDateTime(toMonday(hour), 'UTC')" if weekly else "toStartOfDay(hour)",
        "total_filter": WHOLE_DAYS,
    }


def explore(db: Db, query: ExploreQuery) -> Explore:
    """Per bucket and term: mentions, distinct authors and the share per 1,000 documents,
    pooled (all mentions over all documents) and macro (the average of the channels'
    shares)."""
    parameters = query.explore_parameters(db)
    bucket, seconds = _bucket(query, parameters["from"], parameters["to"])
    parameters["step"] = seconds
    sql = _sql(bucket)
    points = db.rows(
        f"""
        WITH totals AS (
            SELECT {sql["total_bucket"]} AS time, channel, sum(docs) AS n
            FROM scope_hourly
            WHERE {sql["total_filter"]} AND {SCOPE}
            GROUP BY time, channel
        )
        SELECT t.time AS time, t.term AS term, t.docs AS mentions, t.authors AS authors,
               1000 * t.docs / s.n AS pooled, 1000 * t.share_sum / s.members AS macro
        FROM (
            SELECT c.time AS time, c.term AS term, sum(c.docs) AS docs,
                   sum(c.docs / totals.n) AS share_sum,
                   uniqCombinedMerge(12)(c.authors) AS authors
            FROM (
                SELECT {sql["term_bucket"]} AS time, channel, term, sum(docs) AS docs,
                       uniqCombinedMergeState(12)(authors) AS authors
                FROM {sql["table"]}
                WHERE {sql["term_filter"]} AND has({{terms:Array(String)}}, term) AND {SCOPE}
                GROUP BY time, channel, term
            ) AS c
            INNER JOIN totals USING (time, channel)
            GROUP BY time, term
        ) AS t
        INNER JOIN (SELECT time, sum(n) AS n, count() AS members FROM totals GROUP BY time) AS s
            USING time
        ORDER BY time
        """,
        parameters,
    )
    where = db.rows(
        f"""
        SELECT t.term AS term, t.channel AS channel, t.docs AS mentions, t.authors AS authors,
               1000 * t.docs / s.docs AS per_1000
        FROM (
            SELECT term, channel, sum(docs) AS docs, uniqCombinedMerge(12)(authors) AS authors
            FROM {sql["table"]}
            WHERE {sql["term_filter"]} AND has({{terms:Array(String)}}, term) AND {SCOPE}
            GROUP BY term, channel
        ) AS t
        INNER JOIN (
            SELECT channel, sum(docs) AS docs
            FROM scope_hourly
            WHERE {sql["total_filter"]} AND {SCOPE}
            GROUP BY channel
        ) AS s USING channel
        ORDER BY mentions DESC
        LIMIT 100
        """,
        parameters,
    )
    return Explore(
        terms=parameters["terms"],
        bucket=Bucket(bucket),
        step=seconds if bucket == "hour" else None,
        from_=parameters["from"],
        to=parameters["to"],
        points=[ExplorePoint.model_validate(row) for row in points],
        where=[ExploreWhere.model_validate(row) for row in where],
    )


# words of the text and of each term, joined by single spaces, so "GPT-5" matches "gpt 5"
TEXT_MATCHES_TERMS = (
    "arrayExists(t -> position("
    "concat(' ', arrayStringConcat(splitByNonAlpha(lower(text)), ' '), ' '), "
    "concat(' ', arrayStringConcat(splitByNonAlpha(lower(t)), ' '), ' ')) > 0, "
    "{terms:Array(String)})"
)


def mentions(db: Db, query: ExploreQuery) -> list[Mention]:
    """Recent comments and posts with the terms. Raw text is only kept for 48 hours."""
    rows = db.rows(
        f"""
        SELECT created_at AS time, channel, doc_type, substring(text, 1, 600) AS text, url,
               intents
        FROM items
        WHERE created_at >= {FROM} AND created_at <= {TO} AND {SCOPE}
          AND ({TEXT_MATCHES_TERMS} OR hasAny(intents, {{terms:Array(String)}}))
        ORDER BY created_at DESC
        LIMIT 100
        """,
        query.explore_parameters(db),
    )
    return [Mention.model_validate(row) for row in rows]
