"""Read-only queries for the command line."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from clickhouse_connect.driver.client import Client

if TYPE_CHECKING:
    from wgra.detect.long_term import LongTermTrend
    from wgra.detect.short_term import Trend

Bucket = Literal["hour", "day", "week"]

# a scope is a group or a single channel
_SCOPE = (
    "channel IN (SELECT channel FROM channel_groups WHERE group_name = {scope:String} "
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


def resolve_scope(client: Client, scope: str) -> str:
    """A scope as stored: a group by its name, a channel by its id, which is lowercase
    (r/LocalLLaMA is r/localllama)."""
    scope = scope.strip().removeprefix("/")
    (is_channel,) = client.query(
        "SELECT count() > 0 FROM channels WHERE channel = lowerUTF8({scope:String})",
        parameters={"scope": scope},
    ).result_rows[0]
    return scope.lower() if is_channel else scope


def term_series(
    client: Client, term: str, scope: str, days: int, bucket: Bucket = "day"
) -> list[TermPoint]:
    """How many documents in the scope mentioned the term, per hour, day or week (ISO
    weeks, Monday to Sunday UTC, the current one so far)."""
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
        parameters={
            "term": normalize_term(term),
            "scope": resolve_scope(client, scope),
            "days": days,
        },
    ).result_rows
    return [TermPoint(bucket, docs, authors, total) for bucket, docs, authors, total in rows]


def ingestion_status(client: Client) -> dict[str, Sequence[Sequence[Any]]]:
    feeds = client.query(
        """
        SELECT platform, feed, count() AS polls, countIf(status != 200) AS errors,
               sum(new_items) AS new, sum(gap) AS gaps, round(avg(interval_s), 1) AS interval_s,
               round(argMax(rate, ts) * 60) AS per_minute, max(ts) AS last_poll
        FROM polls WHERE ts > now() - INTERVAL 1 HOUR
        GROUP BY platform, feed ORDER BY platform, feed
        """
    ).result_rows
    # every channel of config.yaml, the documents of each type it got
    channels = client.query(
        """
        SELECT c.channel, c.platform, sum(s.docs) AS docs,
               arrayStringConcat(
                   arraySort(groupArrayIf(concat(s.doc_type, ' ', toString(s.docs)), s.docs > 0)),
                   ', ') AS by_type
        FROM channels AS c
        LEFT JOIN (
            SELECT channel, doc_type, sum(docs) AS docs
            FROM scope_hourly
            WHERE hour >= now() - INTERVAL 24 HOUR
            GROUP BY channel, doc_type
        ) AS s ON s.channel = c.channel
        GROUP BY c.channel, c.platform
        ORDER BY c.platform, docs DESC, c.channel
        """
    ).result_rows
    tables = client.query(
        """
        SELECT table, sum(rows) AS rows, formatReadableSize(sum(bytes_on_disk)) AS size
        FROM system.parts WHERE active AND database = currentDatabase()
        GROUP BY table ORDER BY sum(bytes_on_disk) DESC
        """
    ).result_rows
    return {"feeds": feeds, "channels": channels, "tables": tables}


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
            "scope": resolve_scope(client, scope) if scope else "",
            "limit": limit,
        },
    ).result_rows
    return latest[0], [Trend(*row) for row in rows]


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
            "scope": resolve_scope(client, scope) if scope else "",
            "limit": limit,
        },
    ).result_rows
    if not rows:
        return None, []
    return week, [LongTermTrend(*row) for row in rows]


@dataclass(frozen=True)
class IntentRow:
    term: str
    mentions: int
    authors: int
    # mentions in the period before, as long as this one
    before: int
    # trending in the scope in the last 24 hours: the strongest score, 0 if not
    z: float = 0.0
    # comments and posts with it in the last 48 hours (raw text is kept that long)
    recent: int = 0


@dataclass(frozen=True)
class IntentReport:
    scope: str
    kind: str
    first_day: date
    last_day: date
    terms: int
    mentions: int
    total: int
    total_before: int
    rows: list[IntentRow]

    def per_10k(self, row: IntentRow) -> float:
        return 10_000 * row.mentions / self.total if self.total else 0.0

    def change(self, row: IntentRow) -> float | None:
        """Times the share of the period before, with half a mention added to both."""
        if not self.total or not self.total_before:
            return None
        return ((row.mentions + 0.5) / self.total) / ((row.before + 0.5) / self.total_before)


@dataclass(frozen=True)
class IntentExample:
    term: str
    created_at: datetime
    channel: str
    url: str
    lang: str
    text: str


def intent_report(
    client: Client, scope: str, kind: str, days: int, limit: int = 30, today: date | None = None
) -> IntentReport:
    """The intents of a kind in a scope over the last `days` days (today included), the
    most mentioned first, with the same number of days before them to compare."""
    today = today or datetime.now(UTC).date()
    scope = resolve_scope(client, scope)
    parameters = {
        "scope": scope,
        "kind": kind,
        "days": days,
        "limit": limit,
        "today": today,
    }
    (total, total_before), *_ = client.query(
        f"""
        SELECT sumIf(docs, toDate(hour) > {{today:Date}} - {{days:UInt32}}),
               sumIf(docs, toDate(hour) <= {{today:Date}} - {{days:UInt32}})
        FROM scope_hourly
        WHERE {_SCOPE}
          AND hour >= toDateTime({{today:Date}} - 2 * {{days:UInt32}} + 1, 'UTC')
          AND hour < toDateTime({{today:Date}} + 1, 'UTC')
        """,
        parameters=parameters,
    ).result_rows
    rows = client.query(
        f"""
        SELECT term, mentions, authors, before,
               count() OVER () AS terms, sum(mentions) OVER () AS all_mentions
        FROM (
            SELECT term,
                   sumIf(docs, day > {{today:Date}} - {{days:UInt32}}) AS mentions,
                   uniqCombinedMergeIf(12)(authors, day > {{today:Date}} - {{days:UInt32}})
                       AS authors,
                   sumIf(docs, day <= {{today:Date}} - {{days:UInt32}}) AS before
            FROM term_daily
            WHERE {_SCOPE} AND kind = {{kind:String}}
              AND day > {{today:Date}} - 2 * {{days:UInt32}} AND day <= {{today:Date}}
            GROUP BY term
            HAVING mentions > 0
        )
        ORDER BY mentions DESC, authors DESC, term
        LIMIT {{limit:UInt32}}
        """,
        parameters=parameters,
    ).result_rows
    terms = [row[0] for row in rows]
    trending = {
        term: float(z)
        for term, z in client.query(
            """
            SELECT term, max(z) FROM trends
            WHERE scope = {trend_scope:String} AND term IN {terms:Array(String)}
              AND detected_at > now() - INTERVAL 24 HOUR AND subsumed_by = ''
            GROUP BY term
            """,
            parameters={"trend_scope": scope, "terms": terms},
        ).result_rows
    }
    recent = {
        term: int(count)
        for term, count in client.query(
            f"""
            SELECT term, count() FROM items ARRAY JOIN intents AS term
            WHERE {_SCOPE} AND term IN {{terms:Array(String)}}
              AND created_at > now() - INTERVAL 48 HOUR
            GROUP BY term
            """,
            parameters=parameters | {"terms": terms},
        ).result_rows
    }
    return IntentReport(
        scope=scope,
        kind=kind,
        first_day=today - timedelta(days=days - 1),
        last_day=today,
        terms=rows[0][4] if rows else 0,
        mentions=int(rows[0][5]) if rows else 0,
        total=int(total or 0),
        total_before=int(total_before or 0),
        rows=[
            IntentRow(
                term,
                int(mentions),
                int(authors),
                int(before),
                trending.get(term, 0.0),
                recent.get(term, 0),
            )
            for term, mentions, authors, before, _, _ in rows
        ],
    )


def intent_examples(
    client: Client, scope: str, terms: Sequence[str], per_term: int
) -> list[IntentExample]:
    """The latest comments and posts of the last 48 hours behind each intent."""
    if not terms or per_term <= 0:
        return []
    rows = client.query(
        f"""
        SELECT term, created_at, channel, url, lang, text
        FROM items FINAL ARRAY JOIN intents AS term
        WHERE {_SCOPE} AND term IN {{terms:Array(String)}}
          AND created_at > now() - INTERVAL 48 HOUR
        ORDER BY created_at DESC
        LIMIT {{per_term:UInt32}} BY term
        """,
        parameters={
            "scope": resolve_scope(client, scope),
            "terms": list(terms),
            "per_term": per_term,
        },
    ).result_rows
    return [IntentExample(*row) for row in rows]
