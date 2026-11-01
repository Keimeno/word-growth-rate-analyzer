"""Intents (docs/ARCHITECTURE.md §4.7): why people mention things. Switches are stored as
"x → y", the other kinds as "alternative: x", "complaint: x", "need: x" and
"considering: x → y" or "considering: x"."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import Field

from wgra.text.intents import INTENT_KINDS
from wgra.web.models import (
    Flow,
    Flows,
    IntentDay,
    IntentExample,
    Intents,
    Need,
    RisingIntent,
    RisingIntents,
)
from wgra.web.queries import (
    DAYS,
    GROUP_CHANNELS,
    NOW,
    SCOPE,
    TODAY,
    WHOLE_DAYS,
    Db,
    Items,
    ScopeQuery,
    WindowQuery,
    daily_series,
)

ENTITY = "if(position(term, ': ') > 0, substring(term, position(term, ': ') + 2), term)"
# the kind of an intent's term: a switch has no kind in front, the others do, and no
# entity has a colon
TERM_KIND = "if(position(t, ': ') > 0, splitByString(': ', t)[1], 'switch')"


class IntentQuery(ScopeQuery, WindowQuery):
    min_authors: int = Field(1, ge=1)
    min_mentions: int = Field(2, ge=1)

    def intent_parameters(self, now: datetime) -> dict[str, Any]:
        return {
            **self.parameters(),
            **self.window(now, "30d"),
            "min_authors": self.min_authors,
            "min_mentions": self.min_mentions,
        }


class RisingIntentQuery(IntentQuery):
    kind: Literal["alternative", "complaint", "considering", "need"] = "alternative"


class ExampleQuery(ScopeQuery):
    intent_kinds: Items = Field(list(INTENT_KINDS))
    term: str = Field("", description="only this intent")


def intents(db: Db, query: IntentQuery) -> Intents:
    parameters = {**query.intent_parameters(db.now), "intent_kinds": list(INTENT_KINDS)}
    counts = db.rows(
        f"""
        SELECT kind, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND has({{intent_kinds:Array(String)}}, kind) AND {DAYS}
        GROUP BY kind
        """,
        parameters,
    )
    daily = db.rows(
        f"""
        SELECT toDateTime(day, 'UTC') AS time, kind, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND has({{intent_kinds:Array(String)}}, kind) AND {DAYS}
        GROUP BY time, kind
        ORDER BY time
        """,
        parameters,
    )
    since = db.value(
        f"SELECT minOrNull(day) FROM term_daily "
        f"WHERE has({{intent_kinds:Array(String)}}, kind) AND day <= {TODAY}",
        parameters,
    )
    return Intents(
        counts={row["kind"]: row["mentions"] for row in counts},
        daily=[IntentDay.model_validate(row) for row in daily],
        since=since,
    )


def flows(db: Db, query: IntentQuery) -> Flows:
    """The top switching flows (x → y), with the flow the other way and a daily sparkline."""
    parameters = query.intent_parameters(db.now)
    rows = db.rows(
        f"""
        WITH
            (SELECT sum(docs) FROM scope_hourly WHERE {SCOPE} AND {WHOLE_DAYS}) AS total,
            flows AS (
                SELECT term, sum(docs) AS mentions, uniqCombinedMerge(12)(authors) AS authors
                FROM term_daily
                WHERE {SCOPE} AND kind = 'switch' AND {DAYS}
                GROUP BY term
            )
        SELECT
            splitByString(' → ', f.term)[1] AS from,
            splitByString(' → ', f.term)[2] AS to,
            f.mentions AS mentions,
            f.authors AS authors,
            r.mentions AS other_way,
            10000 * f.mentions / total AS per_10k,
            f.term AS term
        FROM flows AS f
        LEFT JOIN flows AS r
            ON r.term = concat(splitByString(' → ', f.term)[2], ' → ',
                               splitByString(' → ', f.term)[1])
        WHERE f.authors >= {{min_authors:UInt32}}
        ORDER BY mentions DESC, authors DESC, from
        LIMIT 50
        """,
        parameters,
    )
    first, days = _days(parameters)
    return Flows(
        flows=[Flow.model_validate(row) for row in rows],
        first_day=first,
        sparklines=_daily_sparklines(db, parameters, "switch", rows, first, days),
    )


def rising(db: Db, query: RisingIntentQuery) -> RisingIntents:
    """An intent kind's last 7 days (today included) against the 28 days before, the most
    extra mentions first."""
    parameters = {**query.intent_parameters(db.now), "kind": query.kind}
    week = f"{TODAY} - 6"
    rows = db.rows(
        f"""
        WITH
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= toDateTime({week}, 'UTC') AND hour <= {NOW}) AS n_now,
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= toDateTime({TODAY} - 34, 'UTC')
               AND hour < toDateTime({week}, 'UTC')) AS n_before,
            trending AS (
                SELECT term, max(z) AS z FROM trends
                WHERE detected_at > {NOW} - INTERVAL 24 HOUR AND detected_at <= {NOW}
                  AND kind = {{kind:String}} AND subsumed_by = ''
                  AND scope IN (SELECT {{scope:String}} UNION ALL {GROUP_CHANNELS})
                GROUP BY term
            )
        SELECT
            {ENTITY} AS entity,
            sumIf(docs, day >= {week}) AS mentions,
            uniqCombinedMergeIf(12)(authors, day >= {week}) AS authors,
            sumIf(docs, day < {week}) / 4 AS per_week_before,
            -- the share now against the share before, with half a mention added to both
            (mentions + 0.5) / n_now / ((sumIf(docs, day < {week}) + 0.5)
                / greatest(n_before, 1)) AS times_usual,
            mentions - sumIf(docs, day < {week}) * n_now / greatest(n_before, 1) AS excess,
            any(t.z) AS trend_z,
            term
        FROM term_daily
        LEFT JOIN trending AS t USING term
        WHERE {SCOPE} AND kind = {{kind:String}} AND day >= {TODAY} - 34 AND day <= {TODAY}
        GROUP BY term
        HAVING mentions >= {{min_mentions:UInt32}} AND authors >= {{min_authors:UInt32}}
        ORDER BY excess DESC, mentions DESC
        LIMIT 30
        """,
        parameters,
    )
    first = db.now.astimezone(UTC).date() - timedelta(days=34)
    window = {
        **parameters,
        "from": int(datetime.combine(first, datetime.min.time(), UTC).timestamp()),
        "to": db.timestamp,
    }
    return RisingIntents(
        entries=[RisingIntent.model_validate(row) for row in rows],
        first_day=first,
        sparklines=_daily_sparklines(db, window, query.kind, rows, first, 35),
    )


def needs(db: Db, query: IntentQuery) -> list[Need]:
    """The 10 needs mentioned most in each configured group and the background, whatever
    scope is picked."""
    rows = db.rows(
        f"""
        SELECT
            g.group_name AS group_name,
            substring(t.term, 7) AS need,
            sum(t.docs) AS mentions,
            uniqCombinedMerge(12)(t.authors) AS authors,
            t.term AS term
        FROM term_daily AS t
        INNER JOIN (
            SELECT group_name, channel FROM channel_groups
            WHERE group_name NOT IN (SELECT platform FROM channels)
            UNION ALL SELECT channel, channel FROM channels WHERE background
        ) AS g ON g.channel = t.channel
        WHERE t.kind = 'need' AND {DAYS.replace("day", "t.day")}
          AND (empty({{doc_types:Array(String)}}) OR has({{doc_types:Array(String)}}, t.doc_type))
        GROUP BY group_name, term
        HAVING authors >= {{min_authors:UInt32}}
        ORDER BY group_name, mentions DESC, authors DESC, need
        LIMIT 10 BY group_name
        """,
        query.intent_parameters(db.now),
    )
    return [Need.model_validate(row) for row in rows]


def examples(db: Db, query: ExampleQuery) -> list[IntentExample]:
    """The comments and posts of the last 48 hours an intent was found in."""
    parameters = {
        **query.parameters(),
        "intent_kinds": query.intent_kinds or list(INTENT_KINDS),
        "term": query.term,
    }
    found = (
        f"has({{intent_kinds:Array(String)}}, {TERM_KIND}) "
        "AND ({term:String} = '' OR t = {term:String})"
    )
    rows = db.rows(
        f"""
        SELECT created_at AS time, channel, doc_type, arrayFilter(t -> {found}, intents) AS found,
               substring(text, 1, 600) AS text, url
        FROM items
        WHERE {SCOPE} AND created_at > {NOW} - INTERVAL 48 HOUR AND created_at <= {NOW}
          AND arrayExists(t -> {found}, intents)
        ORDER BY created_at DESC
        LIMIT 200
        """,
        parameters,
    )
    return [IntentExample.model_validate(row) for row in rows]


def _days(parameters: dict[str, Any]) -> tuple[date, int]:
    first = datetime.fromtimestamp(parameters["from"], UTC).date()
    last = datetime.fromtimestamp(parameters["to"], UTC).date()
    return first, (last - first).days + 1


def _daily_sparklines(
    db: Db,
    parameters: dict[str, Any],
    kind: str,
    entries: list[dict[str, Any]],
    first: date,
    days: int,
) -> dict[str, list]:
    if not entries:
        return {}
    points = db.rows(
        f"""
        SELECT day, term, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND kind = {{kind:String}} AND {DAYS} AND has({{terms:Array(String)}}, term)
        GROUP BY day, term
        """,
        {**parameters, "kind": kind, "terms": [entry["term"] for entry in entries]},
    )
    return daily_series(points, first, days)
