"""Early warning: which channels lead which (edges, learned daily), the stories that spread
(events and their cascades), and forecasts of which current bursts will reach which scopes,
with how they turned out."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from undercurrent.web.models import (
    CalibrationBin,
    Cascade,
    Edge,
    Edges,
    Forecast,
    ForecastDay,
    ForecastRecord,
    ResolvedForecast,
    WikipediaRecord,
)
from undercurrent.web.queries import FROM, NOW, TO, Db, Items, WindowQuery

# the edges of the latest day learned as of now
LATEST_EDGES = f"day = (SELECT max(day) FROM propagation_edges WHERE computed_at <= {NOW})"
EDGE_ROWS = (
    f"{LATEST_EDGES} AND topic = {{topic:String}} "
    "AND (empty({leaders:Array(String)}) OR has({leaders:Array(String)}, leader))"
)
RESOLVED = "outcome IN ('hit', 'miss')"
# forecasts made before now; their outcome is what's known today, not as of then
MADE = f"created_at <= {NOW}"
LAST_30_DAYS = f"created_at > {NOW} - INTERVAL 30 DAY AND {MADE}"


class EdgeQuery(BaseModel):
    topic: str = Field("all", description="'all', or the group the events trended in")
    leaders: Items = Field([], description="only edges from these channels")

    def parameters(self) -> dict[str, Any]:
        return {"topic": self.topic, "leaders": self.leaders}


def edges(db: Db, query: EdgeQuery) -> Edges:
    parameters = query.parameters()
    status = db.one(
        f"""
        SELECT
            (SELECT maxOrNull(computed_at) FROM propagation_edges
             WHERE computed_at <= {NOW}) AS edges_learned,
            (SELECT count() FROM propagation_edges FINAL
             WHERE {LATEST_EDGES} AND topic = {{topic:String}}) AS edge_count,
            (SELECT count() FROM lead_lag_events FINAL WHERE start <= {NOW}) AS events,
            (SELECT countIf(closed) FROM lead_lag_events FINAL WHERE start <= {NOW})
                AS closed_events,
            (SELECT count() FROM forecasts FINAL WHERE outcome = 'pending' AND {MADE})
                AS pending,
            (SELECT if(count() = 0, NULL, countIf(outcome = 'hit') / count())
             FROM forecasts FINAL WHERE {RESOLVED} AND {LAST_30_DAYS}) AS precision_30d,
            (SELECT count() FROM forecasts FINAL WHERE {RESOLVED} AND {LAST_30_DAYS})
                AS resolved_30d,
            (SELECT count() FROM notifications
             WHERE kind = 'forecast' AND ok
               AND sent_at > {NOW} - INTERVAL 24 HOUR AND sent_at <= {NOW}) AS forecast_alerts
        """,
        parameters,
    )
    topics = db.rows(
        f"SELECT DISTINCT topic FROM propagation_edges WHERE {LATEST_EDGES} "
        "ORDER BY topic = 'all' DESC, topic",
        {},
    )
    leaders = db.rows(
        f"SELECT DISTINCT leader FROM propagation_edges WHERE {LATEST_EDGES} ORDER BY leader",
        {},
    )
    rows = db.rows(
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
    return Edges(
        **status,
        topics=[row["topic"] for row in topics] or ["all"],
        leaders=[row["leader"] for row in leaders],
        edges=[Edge.model_validate(row) for row in rows],
    )


def forecasts(db: Db) -> list[Forecast]:
    """Forecasts still waiting for their follower, the likeliest first."""
    rows = db.rows(
        f"""
        SELECT term, kind, leader, follower, without_leader, follower_type, probability,
               probability_low, probability_high, base_rate, expected_at, due_by,
               leader_onset, created_at, edge_events, lift, alert
        FROM forecasts FINAL
        WHERE outcome = 'pending' AND {MADE}
        ORDER BY probability DESC
        LIMIT 200
        """,
        {},
    )
    return [Forecast.model_validate(row) for row in rows]


def events(db: Db) -> list[Cascade]:
    """Stories of the last 14 days that reached more than one scope, as cascades: the scopes
    in the order they crossed their onset."""
    rows = db.rows(
        f"""
        SELECT
            term,
            kind,
            start,
            topic,
            arrayMap(o -> (o.1, o.3),
                     arraySort(o -> o.3, arrayFilter(o -> o.2 = '', onsets))) AS cascade,
            closed
        FROM lead_lag_events FINAL
        WHERE start > {NOW} - INTERVAL 14 DAY AND start <= {NOW} AND length(cascade) > 1
        ORDER BY start DESC
        LIMIT 200
        """,
        {},
    )
    return [
        Cascade.model_validate(
            {**row, "cascade": [{"scope": scope, "at": at} for scope, at in row["cascade"]]}
        )
        for row in rows
    ]


def record(db: Db, query: WindowQuery) -> ForecastRecord:
    """How forecasts turned out: the last 30 days, calibration, per day, Wikipedia."""
    resolved = db.rows(
        f"""
        SELECT created_at, term, kind, leader, follower, without_leader, probability, outcome,
               dateDiff('hour', created_at, follower_onset) AS warning_hours,
               dateDiff('hour', leader_onset, follower_onset) AS lag_hours,
               lag_median AS expected_lag_hours
        FROM forecasts FINAL
        WHERE {RESOLVED} AND {LAST_30_DAYS}
        ORDER BY created_at DESC
        LIMIT 500
        """,
        {},
    )
    calibration = db.rows(
        f"""
        SELECT
            toUInt8(floor(least(probability, 0.999) * 5)) AS bin,
            count() AS forecasts,
            avg(probability) AS predicted,
            countIf(outcome = 'hit') / count() AS came_true,
            avg(base_rate) AS base_rate
        FROM forecasts FINAL
        WHERE {RESOLVED} AND created_at > {NOW} - INTERVAL 90 DAY AND {MADE}
        GROUP BY bin
        ORDER BY bin
        """,
        {},
    )
    daily = db.rows(
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
        query.window(db.now, "30d"),
    )
    wikipedia = db.one(
        f"""
        SELECT
            count() AS events,
            countIf(wiki_onset IS NOT NULL) AS with_interest,
            countIf(lead_days > 0) AS onset_first,
            countIf(lead_days = 0) AS same_day,
            countIf(lead_days < 0) AS wikipedia_first,
            quantileExactIf(0.5)(lead_days, lead_days IS NOT NULL) AS median_lead_days
        FROM wiki_leads FINAL
        WHERE start > {NOW} - INTERVAL 90 DAY AND start <= {NOW}
        """,
        {},
    )
    return ForecastRecord(
        resolved=[ResolvedForecast.model_validate(row) for row in resolved],
        calibration=[CalibrationBin.model_validate(row) for row in calibration],
        daily=[ForecastDay.model_validate(row) for row in daily],
        wikipedia=WikipediaRecord.model_validate(wikipedia),
    )
