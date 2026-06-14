"""Forecasts: a term bursting in a leader whose followers haven't picked it up yet.

When a term trends in a subreddit that leads others (an edge), and the subreddit's onset
for the term's event is known while a follower hasn't crossed yet, a forecast says: the
follower will cross within `max_lag_days` of the leader's onset, with this probability
(the edge's, for the event's topic if there's an edge for it, else over all events),
expected after the edge's median lag. A forecast made a while after the leader's onset
accounts for the time that passed without the follower following (stats.py).

The same `decide` makes the forecasts of the live loop and of replays, `resolve` scores
them: a hit when the follower crosses after the leader's onset and by the due time, a miss
once the due time passed without.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass, fields
from datetime import datetime, timedelta
from typing import Any

from clickhouse_connect.driver.client import Client

from wgra.config import ForecastConfig, LeadLagConfig, NotifyConfig
from wgra.detect.alerts import CAPPED
from wgra.detect.short_term import as_utc
from wgra.leadlag.edges import ALL, Edge
from wgra.leadlag.events import HOUR, Event, event_span, topic_of
from wgra.leadlag.stats import given_nothing_yet, remaining_lag, still_to_come

PENDING = "pending"
HIT = "hit"
MISS = "miss"

# the alert status of forecasts while their alerts are off (forecast.alert: false), the
# others are those of trend alerts
OFF = "off"


@dataclass
class Forecast:
    """One row of the forecasts table."""

    kind: str
    term: str
    event_start: datetime
    follower: str
    leader: str
    follower_type: str
    without_leader: bool
    topic: str
    created_at: datetime
    leader_onset: datetime
    expected_at: datetime
    due_by: datetime
    probability: float
    probability_low: float
    probability_high: float
    base_rate: float
    lift: float
    edge_events: int
    edge_hits: int
    lag_q25: float
    lag_median: float
    lag_q75: float
    outcome: str = PENDING
    follower_onset: datetime | None = None
    resolved_at: datetime | None = None
    alert: str = ""

    @property
    def key(self) -> tuple[str, str, datetime, str, str]:
        return self.kind, self.term, self.event_start, self.follower, self.leader

    @property
    def event_key(self) -> tuple[str, str, datetime]:
        return self.kind, self.term, self.event_start

    @property
    def follower_key(self) -> tuple[str, str]:
        return self.follower, self.leader if self.without_leader else ""

    def row(self) -> tuple[Any, ...]:
        return astuple(self)


FORECAST_COLUMNS = tuple(f.name for f in fields(Forecast))


class EdgeIndex:
    """The edges by leader and follower, for each topic."""

    def __init__(self, edges: Iterable[Edge]):
        self._edges: dict[str, dict[tuple[str, str], dict[str, Edge]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for edge in edges:
            self._edges[edge.leader][edge.follower_key][edge.topic] = edge

    @property
    def leaders(self) -> set[str]:
        return set(self._edges)

    def __len__(self) -> int:
        return sum(len(by_follower) for by_follower in self._edges.values())

    def of(self, leader: str, topic: str) -> list[Edge]:
        """The leader's edges, the topic's where there is one, else the one over all events."""
        chosen = []
        for by_topic in self._edges.get(leader, {}).values():
            edge = by_topic.get(topic) if topic else None
            edge = edge or by_topic.get(ALL)
            if edge is not None:
                chosen.append(edge)
        return chosen


def decide(
    event: Event,
    leaders: Iterable[str],
    edges: EdgeIndex,
    now: datetime,
    groups: Mapping[str, Sequence[str]],
    settings: LeadLagConfig,
    forecast: ForecastConfig,
) -> list[Forecast]:
    """Forecasts for an event whose term trends in `leaders` now."""
    span = event_span(event.start, settings)
    max_lag = timedelta(days=settings.max_lag_days)
    known = event.onsets_known(now)
    # a follower crossing in the current hour has started too
    started = {onset.key for onset in event.onsets if onset.at <= now}
    topic = topic_of(event.scopes_at(now), groups)
    forecasts = []
    for leader in sorted(set(leaders)):
        onset = known.get((leader, ""))
        if onset is None or onset.at > span.leaders_until or now >= onset.at + max_lag:
            continue
        elapsed = (now - onset.at) / HOUR
        for edge in edges.of(leader, topic):
            if edge.lift < forecast.min_lift or edge.follower_key in started:
                continue
            still = still_to_come(edge.lags, elapsed, max_lag / HOUR)
            probability = given_nothing_yet(edge.probability, still)
            if probability < forecast.min_probability:
                continue
            forecasts.append(
                Forecast(
                    kind=event.kind,
                    term=event.term,
                    event_start=event.start,
                    follower=edge.follower,
                    leader=leader,
                    follower_type=edge.follower_type,
                    without_leader=edge.without_leader,
                    topic=edge.topic,
                    created_at=now,
                    leader_onset=onset.at,
                    expected_at=onset.at + remaining_lag(edge.lags, elapsed) * HOUR,
                    due_by=onset.at + max_lag,
                    probability=probability,
                    probability_low=given_nothing_yet(edge.probability_low, still),
                    probability_high=given_nothing_yet(edge.probability_high, still),
                    base_rate=edge.base_rate,
                    lift=edge.lift,
                    edge_events=edge.events,
                    edge_hits=edge.hits,
                    lag_q25=edge.lag_q25,
                    lag_median=edge.lag_median,
                    lag_q75=edge.lag_q75,
                )
            )
    return forecasts


def resolve(forecast: Forecast, event: Event, now: datetime) -> bool:
    """Sets the outcome once it's known as of `now`, returns whether it changed.

    A hit: the follower crossed by the due time. A crossing at or before the leader's
    onset can only show up after the forecast when the onsets were recomputed with the
    rest of a partial hour; the follower did pick the term up then, it counts as a hit."""
    if forecast.outcome != PENDING:
        return False
    follows = event.onsets_known(now).get(forecast.follower_key)
    if follows is not None and follows.at <= forecast.due_by:
        forecast.outcome = HIT
        forecast.follower_onset = follows.at
    elif forecast.due_by + HOUR <= now:
        forecast.outcome = MISS
    else:
        return False
    forecast.resolved_at = now
    return True


def best_per_follower(forecasts: Iterable[Forecast]) -> list[Forecast]:
    """One forecast per term and follower: the most likely leader's."""
    best: dict[tuple[str, str, datetime, str], Forecast] = {}
    for forecast in forecasts:
        key = (forecast.kind, forecast.term, forecast.event_start, forecast.follower)
        if key not in best or forecast.probability > best[key].probability:
            best[key] = forecast
    return list(best.values())


def decide_forecast_alerts(
    new: Sequence[Forecast],
    alerts_today: int,
    forecast_alerts_today: int,
    notify: NotifyConfig,
    forecast: ForecastConfig,
) -> list[Forecast]:
    """Sets `alert` on the new forecasts, returns those to send now.

    Forecast alerts count against the daily cap of all alerts (`alerts_today` includes
    trend and forecast alerts of the last 24 hours) and get at most `alert_max_per_day`
    of it. One alert per term: the follower and leader it's most likely for."""
    if not forecast.alert:
        for item in new:
            item.alert = OFF
        return []
    worthy = [
        item
        for item in best_per_follower(new)
        if item.probability >= forecast.alert_min_probability
        and item.edge_events >= forecast.alert_min_events
    ]
    to_send: list[Forecast] = []
    seen: set[tuple[str, str]] = set()
    for item in sorted(worthy, key=lambda item: item.probability, reverse=True):
        if (item.kind, item.term) in seen:
            continue
        seen.add((item.kind, item.term))
        if (
            alerts_today + len(to_send) >= notify.max_alerts_per_day
            or forecast_alerts_today + len(to_send) >= forecast.alert_max_per_day
        ):
            item.alert = CAPPED
        else:
            to_send.append(item)
    return to_send


def write_forecasts(client: Client, forecasts: Sequence[Forecast]) -> None:
    if forecasts:
        client.insert(
            "forecasts",
            [forecast.row() for forecast in forecasts],
            column_names=list(FORECAST_COLUMNS),
        )


def _forecast(row: Sequence[Any]) -> Forecast:
    values = dict(zip(FORECAST_COLUMNS, row, strict=True))
    for name in ("event_start", "created_at", "leader_onset", "expected_at", "due_by"):
        values[name] = as_utc(values[name])
    for name in ("follower_onset", "resolved_at"):
        if values[name] is not None:
            values[name] = as_utc(values[name])
    return Forecast(**values)


def load_forecasts(
    client: Client,
    pending_only: bool = False,
    since: datetime | None = None,
    event_keys: Iterable[tuple[str, str, datetime]] | None = None,
) -> list[Forecast]:
    conditions = ["1"]
    parameters: dict[str, Any] = {}
    if pending_only:
        conditions.append("outcome = 'pending'")
    if since is not None:
        conditions.append("created_at >= toDateTime({since:UInt32}, 'UTC')")
        parameters["since"] = int(since.timestamp())
    if event_keys is not None:
        keys = sorted({(kind, term, int(start.timestamp())) for kind, term, start in event_keys})
        if not keys:
            return []
        conditions.append(
            "(kind, term, toUInt32(event_start)) IN {keys:Array(Tuple(String, String, UInt32))}"
        )
        parameters["keys"] = keys
    rows = client.query(
        f"SELECT {', '.join(FORECAST_COLUMNS)} FROM forecasts FINAL "
        f"WHERE {' AND '.join(conditions)} ORDER BY created_at",
        parameters=parameters,
    ).result_rows
    return [_forecast(row) for row in rows]
