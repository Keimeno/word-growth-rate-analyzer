"""Trending now: what the analyzer found every 15 minutes, its alerts and digest, and the
quick look (rising), which compares without the detector's scoring."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from wgra.web.models import Alert, DigestEntry, Rising, SharePoint, Trend, Trends
from wgra.web.queries import (
    BACKGROUND,
    GROUP_CHANNELS,
    NOW,
    SCOPE,
    TIME_FILTER,
    TREND_SCOPES,
    WORD_KINDS,
    Db,
    Items,
    ScopeQuery,
    WindowQuery,
    hourly_series,
    step,
)


class TrendQuery(ScopeQuery):
    horizon: Literal["24h", "6h"] = "24h"
    kinds: Items = Field(WORD_KINDS, description="term kinds, or intent kinds")
    subsumed: bool = Field(False, description="also terms a phrase explains")

    def parameters(self) -> dict[str, Any]:
        return {
            **super().parameters(),
            "horizon": self.horizon,
            "kinds": self.kinds,
            "subsumed": int(self.subsumed),
        }


class TrendSeriesQuery(TrendQuery, WindowQuery):
    pass


# the latest run of a horizon, as of now
LATEST_RUN = (
    "(SELECT maxOrNull(detected_at) FROM trends "
    f"WHERE horizon = {{horizon:String}} AND detected_at <= {NOW}) AS latest_run"
)
LATEST_TRENDS = (
    "horizon = {horizon:String} AND detected_at = latest_run AND "
    f"{TREND_SCOPES} AND has({{kinds:Array(String)}}, kind) "
    "AND (subsumed_by = '' OR {subsumed:UInt8} = 1)"
)
LAST_DAY = f"detected_at > {NOW} - INTERVAL 24 HOUR AND detected_at <= {NOW}"


def trends(db: Db, query: TrendQuery) -> Trends:
    parameters = query.parameters()
    status = db.one(
        f"""
        WITH {LATEST_RUN}
        SELECT
            latest_run AS last_run,
            (SELECT maxOrNull(reference_days) FROM trends
             WHERE horizon = {{horizon:String}} AND detected_at = latest_run
               AND {TREND_SCOPES}) AS reference_days,
            (SELECT uniqExact(term) FROM trends WHERE {LATEST_TRENDS}) AS trending,
            (SELECT count() FROM trends WHERE alert = 'sent' AND {LAST_DAY}) AS alerts_sent
        """,
        parameters,
    )
    found = db.rows(
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
    if found and status["last_run"]:
        # each trend's hourly mentions in the scope in the week before the run
        points = db.rows(
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
        sparklines = hourly_series(points, status["last_run"], 7 * 24)
    return Trends(
        **status,
        trends=[Trend.model_validate(row) for row in found],
        sparklines=sparklines,
    )


def series(db: Db, query: TrendSeriesQuery) -> list[SharePoint]:
    """The 8 strongest trends of the latest run, per 1,000 documents in the scope."""
    parameters = {**query.parameters(), **query.window(db.now, "7d")}
    parameters["step"] = step(parameters["to"] - parameters["from"], 3600)
    bucket = "toStartOfInterval(hour, toIntervalSecond({step:UInt32}))"
    rows = db.rows(
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
    return [SharePoint.model_validate(row) for row in rows]


def digest(db: Db, query: TrendQuery) -> list[DigestEntry]:
    """Each term at its strongest in the last 24 hours, the daily digest's material."""
    rows = db.rows(
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
        WHERE {LAST_DAY} AND {TREND_SCOPES}
          AND has({{kinds:Array(String)}}, kind) AND subsumed_by = ''
        GROUP BY term
        ORDER BY max(z) DESC
        LIMIT 100
        """,
        query.parameters(),
    )
    return [DigestEntry.model_validate(row) for row in rows]


def alerts(db: Db, query: ScopeQuery) -> list[Alert]:
    """Alerts of the last 14 days, sent or held back (cooldown, daily cap, warm-up)."""
    rows = db.rows(
        f"""
        SELECT detected_at AS time, horizon, scope, term, kind, alert, z AS score,
               is_new, ratio, mentions, authors
        FROM trends FINAL
        WHERE alert != '' AND detected_at > {NOW} - INTERVAL 14 DAY AND detected_at <= {NOW}
          AND {TREND_SCOPES}
        ORDER BY detected_at DESC
        LIMIT 200
        """,
        query.parameters(),
    )
    return [Alert.model_validate(row) for row in rows]


class RisingQuery(ScopeQuery):
    kinds: Items = Field(["word", "phrase"])
    min_mentions: int = Field(10, ge=1)
    min_authors: int = Field(5, ge=1)


def rising(db: Db, query: RisingQuery) -> list[Rising]:
    """The last 24 hours against the 7 days before, blended with the background's share,
    without the detector's scoring."""
    parameters = {
        **query.parameters(),
        "kinds": query.kinds,
        "min_mentions": query.min_mentions,
        "min_authors": query.min_authors,
    }
    day = f"{NOW} - INTERVAL 24 HOUR"
    week = f"{NOW} - INTERVAL 8 DAY"
    rows = db.rows(
        f"""
        WITH
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= {day} AND hour <= {NOW}) AS n_now,
            (SELECT sum(docs) FROM scope_hourly
             WHERE {SCOPE} AND hour >= {week} AND hour < {day}) AS n_before,
            (SELECT sum(docs) FROM scope_hourly
             WHERE channel IN ({BACKGROUND}) AND hour >= {week} AND hour <= {NOW})
                AS n_background,
            -- how many comments' worth of weight the platform-wide share gets in "usual"
            500 AS prior_weight,
            candidates AS (
                SELECT
                    term,
                    kind,
                    sumIf(docs, hour >= {day}) AS mentions_24h,
                    uniqCombinedMergeIf(12)(authors, hour >= {day}) AS authors_24h,
                    sumIf(docs, hour < {day}) AS mentions_before
                FROM term_hourly
                WHERE {SCOPE} AND has({{kinds:Array(String)}}, kind)
                  AND hour >= {week} AND hour <= {NOW}
                GROUP BY term, kind
                HAVING mentions_24h >= {{min_mentions:UInt32}}
                   AND authors_24h >= {{min_authors:UInt32}}
            ),
            background AS (
                SELECT term, kind, sum(docs) AS mentions
                FROM term_hourly
                WHERE channel IN ({BACKGROUND})
                  AND hour >= {week} AND hour <= {NOW}
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
    return [Rising.model_validate(row) for row in rows]
