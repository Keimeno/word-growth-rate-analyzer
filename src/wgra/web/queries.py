"""The web dashboard's data: what the Grafana dashboards show (grafana/build_dashboards.py),
as JSON endpoints with bound parameters instead of Grafana's variables.

Every endpoint takes the request's query string (`Params`) and returns plain data. A scope is
a group or a channel, as everywhere: `scope` picks it, `channels` and `doc_types` narrow it
down (empty means all of them), `scopes` picks among the group and its channels for the
tables of trends.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from clickhouse_connect.driver.client import Client

from wgra.text.intents import INTENT_KINDS

Endpoint = Callable[[Client, "Params"], Any]
ENDPOINTS: dict[str, Endpoint] = {}

WORD_KINDS = ["word", "phrase", "domain", "subreddit"]


def endpoint(name: str) -> Callable[[Endpoint], Endpoint]:
    def register(function: Endpoint) -> Endpoint:
        ENDPOINTS[name] = function
        return function

    return register


class Params:
    """A request's query string, read with defaults and limits, so bad input is a
    ValueError (a 400) and never reaches the SQL other than as a bound parameter."""

    _RANGE = re.compile(r"^(\d+)([hdw])$")

    def __init__(self, query: dict[str, list[str]]):
        self._query = query

    def text(self, name: str, default: str = "") -> str:
        values = self._query.get(name)
        return values[-1].strip() if values else default

    def choice(self, name: str, options: Iterable[str], default: str) -> str:
        value = self.text(name, default)
        if value not in options:
            raise ValueError(f"{name} must be one of {', '.join(options)}")
        return value

    def items(self, name: str, default: Iterable[str] = ()) -> list[str]:
        """A comma separated list, empty when not given."""
        if name not in self._query:
            return list(default)
        return [item.strip() for item in self.text(name).split(",") if item.strip()]

    def number(self, name: str, default: int, low: int = 0, high: int = 1_000_000) -> int:
        try:
            value = int(self.text(name, str(default)))
        except ValueError:
            raise ValueError(f"{name} must be a whole number") from None
        return min(max(value, low), high)

    def flag(self, name: str) -> bool:
        return self.text(name) in ("1", "true", "yes")

    def window(self, default: str) -> tuple[int, int]:
        """The time range as unix seconds: `range` back from now (6h, 7d, 26w), or `from`
        and `to`."""
        now = int(time.time())
        if "from" in self._query:
            start = self.number("from", now - 86400, 0, now)
            end = self.number("to", now, start + 1, now + 86400)
            return start, end
        match = self._RANGE.match(self.text("range", default))
        if not match:
            raise ValueError("range must look like 6h, 7d or 26w")
        amount, unit = int(match[1]), match[2]
        seconds = amount * {"h": 3600, "d": 86400, "w": 7 * 86400}[unit]
        return now - min(seconds, 5 * 365 * 86400), now


def _json(value: Any) -> Any:
    """ClickHouse values as JSON: times in UTC with a Z, nan and inf as null."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
        return moment.isoformat(timespec="seconds") + "Z"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    return value


def rows(client: Client, sql: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    result = client.query(sql, parameters=parameters)
    return [
        dict(zip(result.column_names, (_json(value) for value in row), strict=True))
        for row in result.result_rows
    ]


def value(client: Client, sql: str, parameters: dict[str, Any]) -> Any:
    result = client.query(sql, parameters=parameters).result_rows
    return _json(result[0][0]) if result else None


# A scope's channels: a group's, or the channel itself. Groups and channels are looked up,
# never told apart by their names.
GROUP_CHANNELS = (
    "SELECT channel FROM channel_groups WHERE group_name = {scope:String} "
    "UNION ALL SELECT channel FROM channels WHERE channel = {scope:String}"
)
SCOPE = (
    f"channel IN ({GROUP_CHANNELS}) "
    "AND (empty({channels:Array(String)}) OR has({channels:Array(String)}, channel)) "
    "AND (empty({doc_types:Array(String)}) OR has({doc_types:Array(String)}, doc_type))"
)
# the scopes of a table of trends: the group and its channels, or some of them
TREND_SCOPES = (
    "(scope IN (SELECT {scope:String} UNION ALL "
    "SELECT channel FROM channel_groups WHERE group_name = {scope:String}) "
    "AND (empty({scopes:Array(String)}) OR has({scopes:Array(String)}, scope)))"
)
# the platform's background channel, the prior of its scores (r/all)
BACKGROUND = "SELECT channel FROM channels WHERE background"
FROM = "toDateTime({from:UInt32}, 'UTC')"
TO = "toDateTime({to:UInt32}, 'UTC')"
TIME_FILTER = f"hour >= {FROM} AND hour <= {TO}"
# whole days, for term_daily and the hours of the same days
DAYS = f"day >= toDate({FROM}) AND day <= toDate({TO})"
WHOLE_DAYS = (
    f"hour >= toDateTime(toDate({FROM}), 'UTC') AND hour < toDateTime(toDate({TO}) + 1, 'UTC')"
)


def scope_parameters(params: Params) -> dict[str, Any]:
    return {
        "scope": params.text("scope", "reddit"),
        "channels": params.items("channels"),
        "doc_types": params.items("doc_types"),
        "scopes": params.items("scopes"),
    }


def window_parameters(params: Params, default: str) -> dict[str, Any]:
    start, end = params.window(default)
    return {"from": start, "to": end}


def hourly_series(points: Iterable[dict[str, Any]], end: datetime, hours: int) -> dict[str, list]:
    """Each term's counts per hour in the `hours` up to `end`, zeros where it had none."""
    first = end.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    series: dict[str, list] = {}
    for point in points:
        index = int((_parse_time(point["time"]) - first).total_seconds() // 3600)
        if 0 <= index < hours:
            series.setdefault(point["term"], [0] * hours)[index] += point["mentions"]
    return series


def daily_series(points: Iterable[dict[str, Any]], first: date, days: int) -> dict[str, list]:
    series: dict[str, list] = {}
    for point in points:
        index = (date.fromisoformat(point["day"]) - first).days
        if 0 <= index < days:
            series.setdefault(point["term"], [0] * days)[index] += point["mentions"]
    return series


def _parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.removesuffix("Z"))


@endpoint("meta")
def meta(client: Client, _: Params) -> dict[str, Any]:
    """What the pickers offer: groups (platforms first) and channels, the groups' channels,
    document types, platforms."""
    scopes = rows(
        client,
        "SELECT name, position, platform FROM ("
        "SELECT DISTINCT group_name AS name, 0 AS position, "
        "group_name IN (SELECT platform FROM channels) AS platform FROM channel_groups "
        "UNION ALL SELECT channel, 1, false FROM channels WHERE analyzed) "
        "ORDER BY position, platform DESC, name",
        {},
    )
    groups = rows(
        client,
        "SELECT group_name, arraySort(groupArray(channel)) AS channels FROM channel_groups "
        "GROUP BY group_name",
        {},
    )
    return {
        "scopes": [
            {
                "name": scope["name"],
                "type": "platform"
                if scope["platform"]
                else ("group" if scope["position"] == 0 else "channel"),
            }
            for scope in scopes
        ],
        "groups": {group["group_name"]: group["channels"] for group in groups},
        "doc_types": [
            row["doc_type"]
            for row in rows(client, "SELECT DISTINCT doc_type FROM scope_hourly ORDER BY 1", {})
        ],
        "platforms": [
            row["platform"]
            for row in rows(client, "SELECT DISTINCT platform FROM channels ORDER BY 1", {})
        ],
        "word_kinds": WORD_KINDS,
        "intent_kinds": list(INTENT_KINDS),
    }


# Trending now: what the analyzer found every 15 minutes.
LATEST_RUN = "(SELECT max(detected_at) FROM trends WHERE horizon = {horizon:String}) AS latest_run"
LATEST_TRENDS = (
    "horizon = {horizon:String} AND detected_at = latest_run AND "
    f"{TREND_SCOPES} AND has({{kinds:Array(String)}}, kind) "
    "AND (subsumed_by = '' OR {subsumed:UInt8} = 1)"
)


def trend_parameters(params: Params) -> dict[str, Any]:
    return {
        **scope_parameters(params),
        "horizon": params.choice("horizon", ["24h", "6h"], "24h"),
        "kinds": params.items("kinds", WORD_KINDS),
        "subsumed": int(params.flag("subsumed")),
    }


@endpoint("trending")
def trending(client: Client, params: Params) -> dict[str, Any]:
    parameters = trend_parameters(params)
    status = rows(
        client,
        f"""
        WITH {LATEST_RUN}
        SELECT
            latest_run AS last_run,
            (SELECT max(reference_days) FROM trends
             WHERE horizon = {{horizon:String}} AND detected_at = latest_run
               AND {TREND_SCOPES}) AS reference_days,
            (SELECT uniqExact(term) FROM trends WHERE {LATEST_TRENDS}) AS trending,
            (SELECT count() FROM trends
             WHERE alert = 'sent' AND detected_at > now() - INTERVAL 24 HOUR) AS alerts_sent
        """,
        parameters,
    )[0]
    trends = rows(
        client,
        f"""
        WITH {LATEST_RUN}
        SELECT scope, scope_type, term, kind, z AS score, ratio, is_new, mentions, authors,
               breadth, members, reference_mentions AS mentions_before, alert, subsumed_by
        FROM trends FINAL
        WHERE {LATEST_TRENDS}
        ORDER BY z DESC
        LIMIT 200
        """,
        parameters,
    )
    sparklines: dict[str, list] = {}
    if trends and status["last_run"]:
        # each trend's hourly mentions in the scope in the week before the run
        points = rows(
            client,
            f"""
            WITH {LATEST_RUN}
            SELECT hour AS time, term, sum(docs) AS mentions
            FROM term_hourly
            WHERE hour > latest_run - INTERVAL 7 DAY AND hour <= latest_run
              AND channel IN ({GROUP_CHANNELS})
              AND (kind, term) IN (SELECT kind, term FROM trends WHERE {LATEST_TRENDS})
            GROUP BY time, term
            """,
            parameters,
        )
        sparklines = hourly_series(points, _parse_time(status["last_run"]), 7 * 24)
    return {**status, "trends": trends, "sparklines": sparklines}


@endpoint("trending-chart")
def trending_chart(client: Client, params: Params) -> list[dict[str, Any]]:
    """The 8 strongest trends of the latest run, per 1,000 documents in the scope."""
    parameters = {**trend_parameters(params), **window_parameters(params, "7d")}
    parameters["step"] = _step(parameters["to"] - parameters["from"], 3600)
    bucket = "toStartOfInterval(hour, toIntervalSecond({step:UInt32}))"
    return rows(
        client,
        f"""
        WITH {LATEST_RUN}
        SELECT t.time AS time, t.term AS term, 1000 * t.docs / s.docs AS per_1000
        FROM (
            SELECT {bucket} AS time, term, sum(docs) AS docs
            FROM term_hourly
            WHERE {TIME_FILTER} AND channel IN ({GROUP_CHANNELS})
              AND (kind, term) IN (
                  SELECT kind, term FROM trends
                  WHERE {LATEST_TRENDS} AND subsumed_by = ''
                  GROUP BY kind, term ORDER BY max(z) DESC LIMIT 8
              )
            GROUP BY time, term
        ) AS t
        INNER JOIN (
            SELECT {bucket} AS time, sum(docs) AS docs
            FROM scope_hourly
            WHERE {TIME_FILTER} AND channel IN ({GROUP_CHANNELS})
            GROUP BY time
        ) AS s USING time
        ORDER BY time
        """,
        parameters,
    )


@endpoint("trending-digest")
def trending_digest(client: Client, params: Params) -> list[dict[str, Any]]:
    """Each term at its strongest in the last 24 hours, the daily digest's material."""
    return rows(
        client,
        f"""
        SELECT
            term,
            any(kind) AS term_kind,
            argMax(scope, z) AS strongest_in,
            max(z) AS score,
            argMax(is_new, z) AS is_new,
            argMax(ratio, z) AS ratio,
            argMax(mentions, z) AS mentions,
            min(detected_at) AS first_seen,
            max(detected_at) AS last_seen,
            arraySort(groupUniqArray(horizon)) AS horizons
        FROM trends
        WHERE detected_at > now() - INTERVAL 24 HOUR AND {TREND_SCOPES}
          AND has({{kinds:Array(String)}}, kind) AND subsumed_by = ''
        GROUP BY term
        ORDER BY max(z) DESC
        LIMIT 100
        """,
        trend_parameters(params),
    )


@endpoint("trending-alerts")
def trending_alerts(client: Client, params: Params) -> list[dict[str, Any]]:
    return rows(
        client,
        f"""
        SELECT detected_at AS time, horizon, scope, term, kind, alert, z AS score,
               is_new, ratio, mentions, authors
        FROM trends FINAL
        WHERE alert != '' AND detected_at > now() - INTERVAL 14 DAY AND {TREND_SCOPES}
        ORDER BY detected_at DESC
        LIMIT 200
        """,
        trend_parameters(params),
    )


@endpoint("rising")
def rising(client: Client, params: Params) -> list[dict[str, Any]]:
    """Rising (preview): the last 24 hours against the 7 days before, blended with the
    background's share, without the detector's scoring."""
    parameters = {
        **scope_parameters(params),
        "kinds": params.items("kinds", ["word", "phrase"]),
        "min_mentions": params.number("min_mentions", 10, 1),
        "min_authors": params.number("min_authors", 5, 1),
    }
    return rows(
        client,
        f"""
        WITH
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= now() - INTERVAL 24 HOUR) AS n_now,
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE}
               AND hour >= now() - INTERVAL 8 DAY AND hour < now() - INTERVAL 24 HOUR) AS n_before,
            (SELECT sum(docs) FROM scope_hourly
             WHERE channel IN ({BACKGROUND})
               AND hour >= now() - INTERVAL 8 DAY) AS n_background,
            -- how many comments' worth of weight the platform-wide share gets in "usual"
            500 AS prior_weight,
            candidates AS (
                SELECT
                    term,
                    kind,
                    sumIf(docs, hour >= now() - INTERVAL 24 HOUR) AS mentions_24h,
                    uniqCombinedMergeIf(12)(authors, hour >= now() - INTERVAL 24 HOUR)
                        AS authors_24h,
                    sumIf(docs, hour < now() - INTERVAL 24 HOUR) AS mentions_before
                FROM term_hourly
                WHERE {SCOPE} AND has({{kinds:Array(String)}}, kind)
                  AND hour >= now() - INTERVAL 8 DAY
                GROUP BY term, kind
                HAVING mentions_24h >= {{min_mentions:UInt32}}
                   AND authors_24h >= {{min_authors:UInt32}}
            ),
            background AS (
                SELECT term, kind, sum(docs) AS mentions
                FROM term_hourly
                WHERE channel IN ({BACKGROUND})
                  AND hour >= now() - INTERVAL 8 DAY
                  AND (term, kind) IN (SELECT term, kind FROM candidates)
                GROUP BY term, kind
            )
        SELECT
            c.term AS term,
            c.kind AS kind,
            c.mentions_24h AS mentions,
            c.authors_24h AS authors,
            c.mentions_before AS mentions_before,
            b.mentions AS mentions_background,
            (c.mentions_before + prior_weight * (b.mentions + 1) / (n_background + 1))
                / (n_before + prior_weight) AS usual_share,
            1000 * c.mentions_24h / n_now AS per_1000_now,
            1000 * usual_share AS per_1000_usual,
            c.mentions_24h / n_now / usual_share AS times_usual
        FROM candidates AS c
        LEFT JOIN background AS b USING (term, kind)
        ORDER BY times_usual DESC, mentions DESC
        LIMIT 200
        """,
        parameters,
    )


# Long-term trends: once a day, per scope and window (13, 26, 52 weeks), the terms growing
# or fading steadily, of the latest analyzed week.
LATEST_WEEK = "(SELECT max(week) FROM long_term_trends WHERE horizon = {horizon:String}) AS latest"
LONG_TERM_ROWS = (
    f"week = latest AND horizon = {{horizon:String}} AND {TREND_SCOPES} "
    "AND has({kinds:Array(String)}, kind)"
)


@endpoint("long-term")
def long_term(client: Client, params: Params) -> dict[str, Any]:
    parameters = {
        **scope_parameters(params),
        "horizon": params.choice("horizon", ["13w", "26w", "52w"], "13w"),
        "kinds": params.items("kinds", WORD_KINDS),
    }
    status = rows(
        client,
        f"""
        WITH {LATEST_WEEK}
        SELECT
            (SELECT max(detected_at) FROM long_term_trends
             WHERE horizon = {{horizon:String}}) AS last_run,
            if(latest = toDate(0), NULL, latest - 1) AS analyzed_until,
            (SELECT greatest(max(intDiv(toMonday(today()) - first_week, 7)), 0)
             FROM (
                 SELECT if(toDayOfWeek(min(hour)) = 1, toMonday(min(hour)),
                           toMonday(min(hour)) + 7) AS first_week
                 FROM scope_hourly
                 WHERE channel IN ({GROUP_CHANNELS})
                 GROUP BY channel
             )) AS weeks_of_history
        """,
        parameters,
    )[0]
    trends = rows(
        client,
        f"""
        WITH {LATEST_WEEK}
        SELECT scope, term, kind, category, growth, q_value AS q, start_share, end_share,
               mentions, spike_share, peak, change, window_start, weekly
        FROM long_term_trends FINAL
        WHERE {LONG_TERM_ROWS}
        ORDER BY category, abs(log(if(category = 'one-off', change, growth))) DESC
        LIMIT 100 BY category
        """,
        parameters,
    )
    return {**status, "trends": trends}


# Early warning: which channels lead which (edges, learned daily), and forecasts of which
# current bursts will reach which scopes, with how they turned out.
LATEST_EDGES = "day = (SELECT max(day) FROM propagation_edges)"
EDGE_ROWS = (
    f"{LATEST_EDGES} AND topic = {{topic:String}} "
    "AND (empty({leaders:Array(String)}) OR has({leaders:Array(String)}, leader))"
)
RESOLVED = "outcome IN ('hit', 'miss')"


def edge_parameters(params: Params) -> dict[str, Any]:
    return {"topic": params.text("topic", "all"), "leaders": params.items("leaders")}


@endpoint("early-warning")
def early_warning(client: Client, params: Params) -> dict[str, Any]:
    parameters = edge_parameters(params)
    status = rows(
        client,
        f"""
        SELECT
            (SELECT max(computed_at) FROM propagation_edges) AS edges_learned,
            (SELECT count() FROM propagation_edges FINAL
             WHERE {LATEST_EDGES} AND topic = {{topic:String}}) AS edge_count,
            (SELECT count() FROM lead_lag_events FINAL) AS events,
            (SELECT countIf(closed) FROM lead_lag_events FINAL) AS closed_events,
            (SELECT count() FROM forecasts FINAL WHERE outcome = 'pending') AS pending,
            (SELECT if(count() = 0, NULL, countIf(outcome = 'hit') / count()) FROM forecasts FINAL
             WHERE {RESOLVED} AND created_at > now() - INTERVAL 30 DAY) AS precision_30d,
            (SELECT count() FROM forecasts FINAL
             WHERE {RESOLVED} AND created_at > now() - INTERVAL 30 DAY) AS resolved_30d,
            (SELECT count() FROM notifications
             WHERE kind = 'forecast' AND ok AND sent_at > now() - INTERVAL 24 HOUR)
                AS forecast_alerts
        """,
        parameters,
    )[0]
    topics = rows(
        client,
        f"SELECT DISTINCT topic FROM propagation_edges WHERE {LATEST_EDGES} "
        "ORDER BY topic = 'all' DESC, topic",
        {},
    )
    leaders = rows(
        client,
        f"SELECT DISTINCT leader FROM propagation_edges WHERE {LATEST_EDGES} ORDER BY leader",
        {},
    )
    edges = rows(
        client,
        f"""
        SELECT leader, follower, without_leader, follower_type, lag_median, lag_q25, lag_q75,
               events, hits, hit_rate, base_rate, probability, probability_low,
               probability_high, lift, lead_share, greatest(q_value, direction_q) AS q,
               leader_onsets
        FROM propagation_edges FINAL
        WHERE {EDGE_ROWS}
        ORDER BY lift DESC
        LIMIT 500
        """,
        parameters,
    )
    return {
        **status,
        "topics": [row["topic"] for row in topics] or ["all"],
        "leaders": [row["leader"] for row in leaders],
        "edges": edges,
    }


@endpoint("early-warning-forecasts")
def early_warning_forecasts(client: Client, _: Params) -> dict[str, Any]:
    pending = rows(
        client,
        """
        SELECT term, kind, leader, follower, without_leader, follower_type, probability,
               probability_low, probability_high, base_rate, expected_at, due_by,
               leader_onset, created_at, edge_events, lift, alert
        FROM forecasts FINAL
        WHERE outcome = 'pending'
        ORDER BY probability DESC
        LIMIT 200
        """,
        {},
    )
    cascades = rows(
        client,
        """
        SELECT
            term,
            kind,
            start,
            topic,
            arrayMap(o -> (o.1, o.3),
                     arraySort(o -> o.3, arrayFilter(o -> o.2 = '', onsets))) AS cascade,
            closed
        FROM lead_lag_events FINAL
        WHERE start > now() - INTERVAL 14 DAY AND length(cascade) > 1
        ORDER BY start DESC
        LIMIT 200
        """,
        {},
    )
    return {"pending": pending, "cascades": cascades}


@endpoint("early-warning-record")
def early_warning_record(client: Client, params: Params) -> dict[str, Any]:
    """How forecasts turned out: the last 30 days, calibration, per day, Wikipedia."""
    resolved = rows(
        client,
        f"""
        SELECT created_at, term, kind, leader, follower, without_leader, probability, outcome,
               dateDiff('hour', created_at, follower_onset) AS warning_hours,
               dateDiff('hour', leader_onset, follower_onset) AS lag_hours,
               lag_median AS expected_lag_hours
        FROM forecasts FINAL
        WHERE {RESOLVED} AND created_at > now() - INTERVAL 30 DAY
        ORDER BY created_at DESC
        LIMIT 500
        """,
        {},
    )
    calibration = rows(
        client,
        f"""
        SELECT
            toUInt8(floor(least(probability, 0.999) * 5)) AS bin,
            count() AS forecasts,
            avg(probability) AS predicted,
            countIf(outcome = 'hit') / count() AS came_true,
            avg(base_rate) AS base_rate
        FROM forecasts FINAL
        WHERE {RESOLVED} AND created_at > now() - INTERVAL 90 DAY
        GROUP BY bin
        ORDER BY bin
        """,
        {},
    )
    daily = rows(
        client,
        f"""
        SELECT toStartOfDay(created_at) AS time,
               countIf(outcome = 'hit') AS came_true,
               countIf(outcome = 'miss') AS missed,
               countIf(outcome = 'pending') AS pending
        FROM forecasts FINAL
        WHERE created_at >= {FROM} AND created_at <= {TO}
        GROUP BY time
        ORDER BY time
        """,
        window_parameters(params, "30d"),
    )
    wikipedia = rows(
        client,
        """
        SELECT
            count() AS events,
            countIf(wiki_onset IS NOT NULL) AS with_interest,
            countIf(lead_days > 0) AS onset_first,
            countIf(lead_days = 0) AS same_day,
            countIf(lead_days < 0) AS wikipedia_first,
            quantileExactIf(0.5)(lead_days, lead_days IS NOT NULL) AS median_lead_days
        FROM wiki_leads FINAL
        WHERE start > now() - INTERVAL 90 DAY
        """,
        {},
    )[0]
    return {
        "resolved": resolved,
        "calibration": calibration,
        "daily": daily,
        "wikipedia": wikipedia,
    }


# Intents (docs/ARCHITECTURE.md §4.7): why people mention things. Switches are stored as
# "x → y", the other kinds as "alternative: x", "complaint: x", "need: x" and
# "considering: x → y" or "considering: x".
ENTITY = "if(position(term, ': ') > 0, substring(term, position(term, ': ') + 2), term)"
# the kind of an intent's term: a switch has no kind in front, the others do, and no
# entity has a colon
TERM_KIND = "if(position(t, ': ') > 0, splitByString(': ', t)[1], 'switch')"


def intent_parameters(params: Params) -> dict[str, Any]:
    return {
        **scope_parameters(params),
        **window_parameters(params, "30d"),
        "min_authors": params.number("min_authors", 1, 1),
        "min_mentions": params.number("min_mentions", 2, 1),
    }


@endpoint("intents")
def intents(client: Client, params: Params) -> dict[str, Any]:
    parameters = {**intent_parameters(params), "intent_kinds": list(INTENT_KINDS)}
    counts = rows(
        client,
        f"""
        SELECT kind, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND has({{intent_kinds:Array(String)}}, kind) AND {DAYS}
        GROUP BY kind
        """,
        parameters,
    )
    daily = rows(
        client,
        f"""
        SELECT toDateTime(day, 'UTC') AS time, kind, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND has({{intent_kinds:Array(String)}}, kind) AND {DAYS}
        GROUP BY time, kind
        ORDER BY time
        """,
        parameters,
    )
    since = value(
        client,
        "SELECT min(day) FROM term_daily WHERE has({intent_kinds:Array(String)}, kind)",
        parameters,
    )
    return {
        "counts": {row["kind"]: row["mentions"] for row in counts},
        "daily": daily,
        # min() of nothing is 1970-01-01
        "since": since if since and since > "1970-01-01" else None,
    }


@endpoint("intents-switches")
def intents_switches(client: Client, params: Params) -> dict[str, Any]:
    """The top switching flows (x → y), with the flow the other way and a daily sparkline."""
    parameters = intent_parameters(params)
    flows = rows(
        client,
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
    return {
        "flows": flows,
        "first_day": first.isoformat(),
        "sparklines": _daily_sparklines(client, parameters, "switch", flows, first, days),
    }


@endpoint("intents-rising")
def intents_rising(client: Client, params: Params) -> dict[str, Any]:
    """An intent kind's last 7 days (today included) against the 28 days before, the most
    extra mentions first."""
    kind = params.choice("kind", ["alternative", "complaint", "considering", "need"], "alternative")
    parameters = {**intent_parameters(params), "kind": kind}
    entries = rows(
        client,
        f"""
        WITH
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= toDateTime(today() - 6, 'UTC')) AS n_now,
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= toDateTime(today() - 34, 'UTC')
               AND hour < toDateTime(today() - 6, 'UTC')) AS n_before,
            trending AS (
                SELECT term, max(z) AS z FROM trends
                WHERE detected_at > now() - INTERVAL 24 HOUR AND kind = {{kind:String}}
                  AND subsumed_by = ''
                  AND scope IN (SELECT {{scope:String}} UNION ALL {GROUP_CHANNELS})
                GROUP BY term
            )
        SELECT
            {ENTITY} AS entity,
            sumIf(docs, day >= today() - 6) AS mentions,
            uniqCombinedMergeIf(12)(authors, day >= today() - 6) AS authors,
            sumIf(docs, day < today() - 6) / 4 AS per_week_before,
            -- the share now against the share before, with half a mention added to both
            (mentions + 0.5) / n_now / ((sumIf(docs, day < today() - 6) + 0.5)
                / greatest(n_before, 1)) AS times_usual,
            mentions - sumIf(docs, day < today() - 6) * n_now / greatest(n_before, 1) AS excess,
            any(t.z) AS trend_z,
            term
        FROM term_daily
        LEFT JOIN trending AS t USING term
        WHERE {SCOPE} AND kind = {{kind:String}} AND day >= today() - 34
        GROUP BY term
        HAVING mentions >= {{min_mentions:UInt32}} AND authors >= {{min_authors:UInt32}}
        ORDER BY excess DESC, mentions DESC
        LIMIT 30
        """,
        parameters,
    )
    first = date.today() - timedelta(days=34)
    sparkline_parameters = {
        **parameters,
        "from": int(datetime.combine(first, datetime.min.time(), UTC).timestamp()),
        "to": int(time.time()),
    }
    return {
        "entries": entries,
        "first_day": first.isoformat(),
        "sparklines": _daily_sparklines(client, sparkline_parameters, kind, entries, first, 35),
    }


@endpoint("intents-needs")
def intents_needs(client: Client, params: Params) -> list[dict[str, Any]]:
    """The 10 needs mentioned most in each configured group and the background, whatever
    scope is picked."""
    return rows(
        client,
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
        intent_parameters(params),
    )


@endpoint("intents-examples")
def intents_examples(client: Client, params: Params) -> list[dict[str, Any]]:
    """The comments and posts of the last 48 hours an intent was found in."""
    parameters = {
        **scope_parameters(params),
        "intent_kinds": params.items("intent_kinds", INTENT_KINDS) or list(INTENT_KINDS),
        "term": params.text("term"),
    }
    found = (
        f"has({{intent_kinds:Array(String)}}, {TERM_KIND}) "
        "AND ({term:String} = '' OR t = {term:String})"
    )
    return rows(
        client,
        f"""
        SELECT created_at AS time, channel, doc_type, arrayFilter(t -> {found}, intents) AS found,
               substring(text, 1, 600) AS text, url
        FROM items
        WHERE {SCOPE} AND created_at > now() - INTERVAL 48 HOUR
          AND arrayExists(t -> {found}, intents)
        ORDER BY created_at DESC
        LIMIT 200
        """,
        parameters,
    )


def _days(parameters: dict[str, Any]) -> tuple[date, int]:
    first = datetime.fromtimestamp(parameters["from"], UTC).date()
    last = datetime.fromtimestamp(parameters["to"], UTC).date()
    return first, (last - first).days + 1


def _daily_sparklines(
    client: Client,
    parameters: dict[str, Any],
    kind: str,
    entries: list[dict[str, Any]],
    first: date,
    days: int,
) -> dict[str, list]:
    if not entries:
        return {}
    points = rows(
        client,
        f"""
        SELECT day, term, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND kind = {{kind:String}} AND {DAYS} AND has({{terms:Array(String)}}, term)
        GROUP BY day, term
        """,
        {**parameters, "kind": kind, "terms": [entry["term"] for entry in entries]},
    )
    return daily_series(points, first, days)


# Term explorer: how often terms are mentioned over time, where, and recent examples.
# Hours come from term_hourly (180 days), days and weeks from term_daily (forever); weeks are
# ISO weeks, Monday to Sunday UTC.
def _step(seconds: int, minimum: int, points: int = 300) -> int:
    """A bucket of whole multiples of `minimum` that keeps a series near `points` long."""
    return max(minimum, math.ceil(seconds / points / minimum) * minimum)


def explore_bucket(params: Params, start: int, end: int) -> tuple[str, int]:
    bucket = params.choice("bucket", ["auto", "hour", "day", "week"], "auto")
    if bucket == "auto":
        days = (end - start) / 86400
        bucket = "hour" if days <= 14 else "day" if days <= 366 else "week"
    step = _step(end - start, 3600) if params.text("bucket", "auto") == "auto" else 3600
    return bucket, step


def explore_parameters(params: Params) -> dict[str, Any]:
    terms = list(dict.fromkeys(" ".join(term.lower().split()) for term in params.items("terms")))
    if not terms:
        raise ValueError("name at least one term")
    return {**scope_parameters(params), **window_parameters(params, "2d"), "terms": terms[:12]}


def _explore_sql(bucket: str) -> dict[str, str]:
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


@endpoint("explore")
def explore(client: Client, params: Params) -> dict[str, Any]:
    """Per bucket and term: mentions, distinct authors and the share per 1,000 documents,
    pooled (all mentions over all documents) and macro (the average of the channels'
    shares)."""
    parameters = explore_parameters(params)
    bucket, step = explore_bucket(params, parameters["from"], parameters["to"])
    parameters["step"] = step
    sql = _explore_sql(bucket)
    points = rows(
        client,
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
    totals = rows(
        client,
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
    return {
        "terms": parameters["terms"],
        "bucket": bucket,
        "step": step if bucket == "hour" else None,
        "from": parameters["from"],
        "to": parameters["to"],
        "points": points,
        "where": totals,
    }


# words of the text and of each term, joined by single spaces, so "GPT-5" matches "gpt 5"
TEXT_MATCHES_TERMS = (
    "arrayExists(t -> position("
    "concat(' ', arrayStringConcat(splitByNonAlpha(lower(text)), ' '), ' '), "
    "concat(' ', arrayStringConcat(splitByNonAlpha(lower(t)), ' '), ' ')) > 0, "
    "{terms:Array(String)})"
)


@endpoint("explore-mentions")
def explore_mentions(client: Client, params: Params) -> list[dict[str, Any]]:
    """Recent comments and posts with the terms. Raw text is only kept for 48 hours."""
    return rows(
        client,
        f"""
        SELECT created_at AS time, channel, doc_type, substring(text, 1, 600) AS text, url,
               intents
        FROM items
        WHERE created_at >= {FROM} AND created_at <= {TO} AND {SCOPE}
          AND ({TEXT_MATCHES_TERMS} OR hasAny(intents, {{terms:Array(String)}}))
        ORDER BY created_at DESC
        LIMIT 100
        """,
        explore_parameters(params),
    )


# Ingestion: is the ingester healthy and complete, per platform.
PLATFORMS = "(empty({platforms:Array(String)}) OR has({platforms:Array(String)}, platform))"
# the picked platforms' tracked channels: the group named like the platform, not r/all
TRACKED = (
    "channel IN (SELECT channel FROM channel_groups WHERE group_name IN "
    f"(SELECT platform FROM channels WHERE {PLATFORMS}))"
)


@endpoint("ingestion")
def ingestion(client: Client, params: Params) -> dict[str, Any]:
    parameters = {**window_parameters(params, "6h"), "platforms": params.items("platforms")}
    status = rows(
        client,
        f"""
        SELECT
            (SELECT sum(docs) FROM scope_hourly
             WHERE {TRACKED} AND hour >= now() - INTERVAL 24 HOUR) AS documents_24h,
            (SELECT count() FROM polls
             WHERE {PLATFORMS} AND ts > now() - INTERVAL 10 MINUTE) AS requests_10m,
            (SELECT sum(gap) FROM polls
             WHERE {PLATFORMS} AND ts > now() - INTERVAL 24 HOUR) AS gaps_24h,
            (SELECT sum(new_items) / sum(id_span) FROM polls
             WHERE platform = 'reddit' AND sample AND id_span > 0
               AND ts >= {FROM} AND ts <= {TO}) AS sampled_share,
            (SELECT max(ts) FROM polls WHERE {PLATFORMS}) AS last_poll
        """,
        parameters,
    )[0]
    feeds = rows(
        client,
        f"""
        SELECT platform, feed, count() AS polls, countIf(status != 200) AS errors,
               sum(new_items) AS new_items, sum(gap) AS gaps, avg(interval_s) AS poll_every_s,
               argMax(rate, ts) * 60 AS items_per_minute, max(ts) AS last_poll
        FROM polls
        WHERE {PLATFORMS} AND ts > now() - INTERVAL 1 HOUR
        GROUP BY platform, feed
        ORDER BY platform, feed
        """,
        parameters,
    )
    channels = rows(
        client,
        """
        SELECT c.channel AS channel, c.platform AS platform, c.background AS background,
               c.analyzed AS analyzed, sum(s.docs) AS documents,
               arraySort(groupArrayIf((s.doc_type, s.docs), s.docs > 0)) AS by_type,
               sum(s.authors) AS authors
        FROM channels AS c
        LEFT JOIN (
            SELECT channel, doc_type, sum(docs) AS docs, uniqCombinedMerge(12)(authors) AS authors
            FROM scope_hourly
            WHERE hour >= now() - INTERVAL 24 HOUR
            GROUP BY channel, doc_type
        ) AS s ON s.channel = c.channel
        WHERE (empty({platforms:Array(String)}) OR has({platforms:Array(String)}, c.platform))
        GROUP BY c.channel, c.platform, c.background, c.analyzed
        ORDER BY c.platform, documents DESC, c.channel
        """,
        parameters,
    )
    storage = rows(
        client,
        """
        SELECT table, sum(rows) AS rows, sum(bytes_on_disk) AS bytes
        FROM system.parts
        WHERE active AND database = currentDatabase()
        GROUP BY table
        ORDER BY bytes DESC
        """,
        {},
    )
    return {**status, "feeds": feeds, "channels": channels, "storage": storage}


@endpoint("ingestion-charts")
def ingestion_charts(client: Client, params: Params) -> dict[str, Any]:
    """New items per minute per feed, and requests, errors and gaps per minute."""
    parameters = {**window_parameters(params, "6h"), "platforms": params.items("platforms")}
    parameters["step"] = _step(parameters["to"] - parameters["from"], 60, 240)
    bucket = "toStartOfInterval(ts, toIntervalSecond({step:UInt32}))"
    items = rows(
        client,
        f"""
        SELECT {bucket} AS time, feed, sum(new_items) / ({{step:UInt32}} / 60) AS per_minute
        FROM polls
        WHERE {PLATFORMS} AND ts >= {FROM} AND ts <= {TO}
        GROUP BY time, feed
        ORDER BY time
        """,
        parameters,
    )
    requests = rows(
        client,
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
    return {"step": parameters["step"], "items": items, "requests": requests}
