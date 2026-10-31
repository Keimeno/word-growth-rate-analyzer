"""Edges: leader channel -> follower scope, learned from the onsets of past events.

For each ordered pair, over the events of the training period:

* the leader's onsets: events where the leader crossed, up to `max_lag_days` after the
  event's first trend
* events (n): those of them the follower hadn't crossed at or before the leader, and whose
  outcome is known as of the run: the follower crossed since, or `max_lag_days` passed
* hits: the follower crossed within `max_lag_days` after the leader, and the lags
* the base rate: the share of all (closed) events in which the follower crossed at all,
  "how often does it pick up a term that trends somewhere"
* the probability to follow: hits and misses with a prior of `prior_events` events at the
  base rate (stats.posterior), its interval, and lift = probability / base rate
* association: a p-value (could the hits come from the base rate?) and a q-value
  (Benjamini–Hochberg over every pair with at least `min_events`)
* direction: reverse, the events where the follower crossed first, at most `max_lag_days`
  before the leader. Two scopes that pick up the same terms in either order are
  associated, but neither leads. The leader must come first significantly more often
  than not: a binomial test of hits against reverse at 1/2, Benjamini–Hochberg over the
  associated pairs.

An edge is stored when it has `min_events` and `min_hits`, the leader was first in at
least `min_lead_share` of the events where both crossed, and both q-values are at most
`max_q`, for a topic's edge `max_q` divided by the number of topics: each topic is another
look at the same data. Leaders: the analyzed channels that aren't a platform's background
(the tracked subreddits). Followers: the other analyzed channels, the background among
them (r/all, reddit-wide), and the configured groups (without the leader's own counts when
it's one of their channels). Edges are learned over all events (topic "all") and per
topic, the group an event trended in most.

Nothing an edge is learned from is after `as_of`: onsets count once their hour is over,
misses once the follow window is, base rates from events whose span is over. Replays learn
them as of each day and get the same edges a live run would have had.
"""

from __future__ import annotations

import bisect
import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass, field, fields
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from clickhouse_connect.driver.client import Client

from wgra.config import LeadLagConfig
from wgra.detect.short_term import CHANNEL, Scope, as_utc, load_scopes
from wgra.detect.trend_stats import benjamini_hochberg
from wgra.leadlag.events import HOUR, Event, event_span
from wgra.leadlag.onsets import split_scopes
from wgra.leadlag.stats import binomial_tail, posterior

log = logging.getLogger(__name__)

ALL = "all"
CHANNEL_FOLLOWER = CHANNEL
GROUP_FOLLOWER = "group"
# a platform's background channel: the whole platform (r/all, reddit-wide)
PLATFORM_FOLLOWER = "platform"


@dataclass(frozen=True)
class Follower:
    scope: str
    type: str
    # the leader's scope, when the follower is a group measured without it
    without: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.scope, self.without


class Network:
    """Who can lead whom: channels lead, channels, groups and the platforms follow."""

    def __init__(
        self,
        channels: Sequence[str],
        groups: Mapping[str, Sequence[str]],
        first_data: Mapping[str, datetime],
        backgrounds: Iterable[str] = (),
    ):
        """`first_data`: each channel's first hour with documents. `backgrounds`: the
        channels that are a platform's background (r/all), they follow but don't lead."""
        self.channels = list(channels)
        self.groups = {group: tuple(members) for group, members in groups.items()}
        self._first_data = dict(first_data)
        self.backgrounds = frozenset(backgrounds)
        self.leaders = [channel for channel in self.channels if channel not in self.backgrounds]
        self._followers = {leader: self._followers_of(leader) for leader in self.leaders}

    @classmethod
    def load(cls, client: Client, scopes: Sequence[Scope] | None = None) -> Network:
        scopes = load_scopes(client) if scopes is None else scopes
        channels, groups = split_scopes(scopes)
        rows = client.query("SELECT channel, min(hour) FROM scope_hourly GROUP BY channel")
        return cls(
            channels,
            groups,
            {channel: as_utc(hour) for channel, hour in rows.result_rows},
            [scope.name for scope in scopes if scope.background],
        )

    def _followers_of(self, leader: str) -> list[Follower]:
        followers = [
            Follower(
                channel, PLATFORM_FOLLOWER if channel in self.backgrounds else CHANNEL_FOLLOWER
            )
            for channel in self.channels
            if channel != leader
        ]
        for group, members in self.groups.items():
            if leader in members:
                if len(set(members)) > 1:
                    followers.append(Follower(group, GROUP_FOLLOWER, without=leader))
            else:
                followers.append(Follower(group, GROUP_FOLLOWER))
        return followers

    def followers(self, leader: str) -> list[Follower]:
        return self._followers.get(leader, [])

    def follower_keys(self) -> set[tuple[str, str]]:
        return {f.key for followers in self._followers.values() for f in followers}

    def data_from(self, key: tuple[str, str]) -> datetime | None:
        """The first hour with data of a follower (a group's: of any of its channels)."""
        scope, without = key
        members: Iterable[str] = (
            (member for member in self.groups[scope] if member != without)
            if scope in self.groups
            else (scope,)
        )
        starts = [self._first_data[m] for m in members if m in self._first_data]
        return min(starts) if starts else None


@dataclass
class Edge:
    """One row of the propagation_edges table (without the run's columns)."""

    topic: str
    leader: str
    follower: str
    follower_type: str
    without_leader: bool
    leader_onsets: int
    events: int
    hits: int
    hit_rate: float
    base_rate: float
    probability: float
    probability_low: float
    probability_high: float
    lift: float
    p_value: float
    q_value: float
    # the follower crossed first (within max_lag_days), and hits / (hits + reverse)
    reverse: int
    lead_share: float
    direction_q: float
    lag_median: float
    lag_q25: float
    lag_q75: float
    lags: list[float]

    @property
    def follower_key(self) -> tuple[str, str]:
        return self.follower, self.leader if self.without_leader else ""


EDGE_FIELDS = tuple(f.name for f in fields(Edge))


@dataclass
class EdgeResult:
    as_of: datetime
    training_start: datetime
    # events in the training period, and of them those whose span is over
    training_events: int
    closed_events: int
    # pairs with at least min_events: the Benjamini–Hochberg family of association, and
    # those associated: the family of direction
    tested: int
    associated: int = 0
    edges: list[Edge] = field(default_factory=list)


@dataclass
class _Pair:
    hits: int = 0
    misses: int = 0
    # the follower crossed at most max_lag before the leader
    reverse: int = 0
    lags: list[float] = field(default_factory=list)


def learn_edges(
    events: Iterable[Event], network: Network, as_of: datetime, settings: LeadLagConfig
) -> EdgeResult:
    """The edges as of `as_of`, from the events (with their onsets) of the training period."""
    max_lag = timedelta(days=settings.max_lag_days)
    history = timedelta(days=settings.min_reference_days)
    training_start = as_of - timedelta(days=settings.training_days)
    data_from = {key: network.data_from(key) for key in network.follower_keys()}

    def has_history(key: tuple[str, str], moment: datetime) -> bool:
        first = data_from.get(key)
        return first is not None and first + history <= moment

    # base rates: per topic, the span starts of the closed events, and per follower the
    # closed events it crossed in (when it had data then)
    closed_starts: dict[str, list[datetime]] = defaultdict(list)
    crossed: dict[tuple[str, tuple[str, str]], int] = defaultdict(int)
    leader_onsets: dict[tuple[str, str], int] = defaultdict(int)
    pairs: dict[tuple[str, str, Follower], _Pair] = defaultdict(_Pair)
    training_events = 0

    for event in events:
        if not training_start <= event.start <= as_of:
            continue
        training_events += 1
        span = event_span(event.start, settings)
        # an event whose onsets were computed before as_of only knows that much
        known_until = min(as_of, event.onsets_until or as_of)
        known = event.onsets_known(known_until)
        topic = event.topic(network.groups, as_of) if settings.topics else ""
        topics = (ALL, topic) if topic else (ALL,)

        if span.end <= known_until:
            for name in topics:
                closed_starts[name].append(span.start)
                for key in known:
                    if key in data_from and has_history(key, span.start):
                        crossed[name, key] += 1

        for (scope, without), onset in known.items():
            if without or onset.at > span.leaders_until or scope not in network.leaders:
                continue
            for name in topics:
                leader_onsets[name, scope] += 1
            window_over = onset.at + max_lag + HOUR <= known_until
            for follower in network.followers(scope):
                if not has_history(follower.key, onset.at):
                    continue
                follows = known.get(follower.key)
                if follows is not None and follows.at <= onset.at:
                    # it was there first: not a chance to follow, but against the direction
                    if follows.at < onset.at and onset.at - follows.at <= max_lag:
                        for name in topics:
                            pairs[name, scope, follower].reverse += 1
                    continue
                hit = follows is not None and follows.at <= onset.at + max_lag
                if not hit and not window_over:
                    continue  # not known yet
                for name in topics:
                    pair = pairs[name, scope, follower]
                    if hit:
                        assert follows is not None
                        pair.hits += 1
                        pair.lags.append((follows.at - onset.at) / HOUR)
                    else:
                        pair.misses += 1

    for starts in closed_starts.values():
        starts.sort()
    tested: list[tuple[tuple[str, str, Follower], _Pair, float, float]] = []
    for (topic, leader, follower), pair in pairs.items():
        if pair.hits + pair.misses < settings.min_events:
            continue
        first = data_from.get(follower.key)
        starts = closed_starts.get(topic, [])
        closed = len(starts) - bisect.bisect_left(starts, first + history) if first else 0
        if closed == 0:
            continue
        base_rate = (crossed[topic, follower.key] + 0.5) / (closed + 1)
        p_value = binomial_tail(pair.hits, pair.hits + pair.misses, base_rate)
        tested.append(((topic, leader, follower), pair, base_rate, p_value))

    # association over every pair tested, then direction over the associated ones
    q_values = benjamini_hochberg([p for *_, p in tested])
    associated = [
        (item, float(q_value))
        for item, q_value in zip(tested, q_values, strict=True)
        if q_value <= settings.max_q and item[1].hits >= settings.min_hits
    ]
    direction_q = benjamini_hochberg(
        [binomial_tail(pair.hits, pair.hits + pair.reverse, 0.5) for (_, pair, *_), _ in associated]
    )
    tested_topics = {topic for (topic, _, _), *_ in tested} - {ALL}
    edges = []
    for (((topic, leader, follower), pair, base_rate, p_value), q_value), direction in zip(
        associated, direction_q, strict=True
    ):
        max_q = settings.max_q if topic == ALL else settings.max_q / len(tested_topics)
        lead_share = pair.hits / (pair.hits + pair.reverse)
        if max(q_value, direction) > max_q or lead_share < settings.min_lead_share:
            continue
        mean, low, high = posterior(
            pair.hits, pair.misses, base_rate, settings.prior_events, settings.interval
        )
        lags = sorted(pair.lags)
        q25, median, q75 = (
            (float(v) for v in np.percentile(lags, [25, 50, 75])) if lags else (math.nan,) * 3
        )
        events_count = pair.hits + pair.misses
        edges.append(
            Edge(
                topic=topic,
                leader=leader,
                follower=follower.scope,
                follower_type=follower.type,
                without_leader=bool(follower.without),
                leader_onsets=leader_onsets[topic, leader],
                events=events_count,
                hits=pair.hits,
                hit_rate=pair.hits / events_count,
                base_rate=base_rate,
                probability=mean,
                probability_low=low,
                probability_high=high,
                lift=mean / base_rate,
                p_value=p_value,
                q_value=q_value,
                reverse=pair.reverse,
                lead_share=lead_share,
                direction_q=float(direction),
                lag_median=median,
                lag_q25=q25,
                lag_q75=q75,
                lags=lags,
            )
        )
    edges.sort(key=lambda edge: (edge.topic != ALL, edge.topic, -edge.lift))
    return EdgeResult(
        as_of=as_of,
        training_start=training_start,
        training_events=training_events,
        closed_events=len(closed_starts.get(ALL, [])),
        tested=len(tested),
        associated=len(associated),
        edges=edges,
    )


EDGE_COLUMNS = ("day", "computed_at", *EDGE_FIELDS, "training_start", "training_events")


def write_edges(client: Client, result: EdgeResult) -> None:
    """Replaces the edges of the run's day: the day's earlier runs found the same, unless
    the settings changed."""
    day = result.as_of.date()
    client.command("DELETE FROM propagation_edges WHERE day = {day:Date}", parameters={"day": day})
    if result.edges:
        client.insert(
            "propagation_edges",
            [
                (
                    day,
                    result.as_of,
                    *astuple(edge),
                    result.training_start,
                    result.training_events,
                )
                for edge in result.edges
            ],
            column_names=list(EDGE_COLUMNS),
        )


def load_edges(client: Client, day: date | None = None) -> tuple[date | None, list[Edge]]:
    """The edges of the latest day (or of `day`)."""
    columns = ", ".join(EDGE_FIELDS)
    rows = client.query(
        f"""
        WITH {{day:Nullable(Date)}} AS wanted,
             (SELECT max(day) FROM propagation_edges) AS latest
        SELECT day, {columns}
        FROM propagation_edges FINAL
        WHERE day = ifNull(wanted, latest)
        ORDER BY topic, leader, follower
        """,
        parameters={"day": day},
    ).result_rows
    if not rows:
        return None, []
    edges = []
    for row in rows:
        values: dict[str, Any] = dict(zip(EDGE_FIELDS, row[1:], strict=True))
        values["lags"] = [float(lag) for lag in values["lags"]]
        edges.append(Edge(**values))
    return rows[0][0], edges
