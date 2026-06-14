"""Events: a term trending somewhere, the unit lead–lag edges are learned from.

A term's trends (rows of `trends`, not subsumed, with z of at least `event_min_z`) form
episodes. The first trend starts an event, every later one within the event's span belongs
to it, the first one after starts the next event. "iphone" every September is one event a
year, not one.

The span runs from `lookback_hours` before the first trend (a scope can cross the onset
gates, which are lower than the detector's, before anything trends) to 2 × `max_lag_days`
after it: leaders' onsets count up to `max_lag_days` after the first trend, and each gets
`max_lag_days` for its followers.

Each event gets a topic, the configured group it trended in most: the group itself or one
of its subreddits with the highest score. Edges are learned per topic too, since a
subreddit can lead reddit on tech terms and follow on everything else.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from clickhouse_connect.driver.client import Client

from wgra.config import LeadLagConfig
from wgra.detect.short_term import as_utc

log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Sighting:
    """A term trending in a scope, as of a detector run."""

    kind: str
    term: str
    scope: str
    at: datetime
    z: float


@dataclass(frozen=True, slots=True)
class Onset:
    """The first hour a scope's window crossed the onset gates for an event's term.

    `without`: a group measured without one of its subreddits ("r/name"), to see whether
    the rest of the group follows that subreddit, '' otherwise."""

    scope: str
    without: str
    at: datetime
    mentions: int
    ratio: float
    z: float

    @property
    def key(self) -> tuple[str, str]:
        return self.scope, self.without


def hour_floor(moment: datetime) -> datetime:
    return as_utc(moment).replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class Span:
    """The hours of an event onsets are looked for in, [start, end)."""

    start: datetime
    end: datetime
    # leaders' onsets count up to here, so each one gets max_lag_days for its followers
    leaders_until: datetime


def event_span(start: datetime, settings: LeadLagConfig) -> Span:
    first = hour_floor(start)
    max_lag = timedelta(days=settings.max_lag_days)
    return Span(
        start=first - timedelta(hours=settings.lookback_hours),
        end=first + 2 * max_lag,
        leaders_until=first + max_lag,
    )


@dataclass
class Event:
    kind: str
    term: str
    start: datetime
    last_seen: datetime
    # scope -> its highest score in the event
    scopes: dict[str, float] = field(default_factory=dict)
    onsets: list[Onset] = field(default_factory=list)
    # the data the onsets were computed from ends here (exclusive), None: not yet
    onsets_until: datetime | None = None
    closed: bool = False
    # in replays: every sighting, so the topic can be known as of a time
    sightings: list[Sighting] = field(default_factory=list, repr=False)

    @property
    def key(self) -> tuple[str, str, datetime]:
        return self.kind, self.term, self.start

    def add(self, sighting: Sighting, keep: bool = False) -> None:
        self.last_seen = max(self.last_seen, sighting.at)
        self.scopes[sighting.scope] = max(self.scopes.get(sighting.scope, sighting.z), sighting.z)
        if keep:
            self.sightings.append(sighting)

    def scopes_at(self, moment: datetime) -> dict[str, float]:
        """The scopes it trended in up to `moment`, from the sightings when there are."""
        if not self.sightings:
            return self.scopes
        scopes: dict[str, float] = {}
        for sighting in self.sightings:
            if sighting.at <= moment:
                scopes[sighting.scope] = max(scopes.get(sighting.scope, sighting.z), sighting.z)
        return scopes

    def onsets_known(self, moment: datetime) -> dict[tuple[str, str], Onset]:
        """The onsets that are known at `moment`: their hour is over."""
        return {onset.key: onset for onset in self.onsets if onset.at + HOUR <= moment}


def topic_of(scopes: Mapping[str, float], groups: Mapping[str, Sequence[str]]) -> str:
    """The configured group the event trended in most: the group itself or one of its
    subreddits with the highest score. Ties go to the smaller group, then by name."""
    best: tuple[float, int, str] | None = None
    for group, members in groups.items():
        names = {group, *(f"r/{member}" for member in members)}
        score = max((z for scope, z in scopes.items() if scope in names), default=None)
        if score is None:
            continue
        candidate = (score, -len(members), group)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else ""


def assign_events(
    sightings: Iterable[Sighting],
    existing: Iterable[Event],
    settings: LeadLagConfig,
    keep_sightings: bool = False,
) -> list[Event]:
    """Adds sightings to the events they belong to, or starts new events.

    Returns the events that got sightings, new or existing. A sighting before the latest
    event of its term that no event covers is dropped: the events were assigned from an
    earlier start, and adding it would make events overlap."""
    by_term: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for event in existing:
        by_term[event.kind, event.term].append(event)
    for events in by_term.values():
        events.sort(key=lambda event: event.start)

    touched: dict[tuple[str, str, datetime], Event] = {}
    for sighting in sorted(sightings, key=lambda sighting: sighting.at):
        events = by_term[sighting.kind, sighting.term]
        covering = next(
            (
                event
                for event in reversed(events)
                if event.start <= sighting.at < event_span(event.start, settings).end
            ),
            None,
        )
        if covering is None:
            if events and sighting.at < events[-1].start:
                log.debug("dropping a sighting before its term's events: %s", sighting)
                continue
            covering = Event(sighting.kind, sighting.term, sighting.at, sighting.at)
            events.append(covering)
        covering.add(sighting, keep=keep_sightings)
        touched[covering.key] = covering
    return list(touched.values())


SIGHTINGS_SQL = """
SELECT kind, term, scope, min(detected_at) AS at, max(z)
FROM trends
WHERE detected_at > toDateTime({since:UInt32}, 'UTC')
  AND detected_at <= toDateTime({until:UInt32}, 'UTC')
  AND subsumed_by = '' AND z >= {min_z:Float64}
GROUP BY kind, term, scope, toStartOfHour(detected_at)
ORDER BY at
"""


def load_sightings(
    client: Client, since: datetime, until: datetime, min_z: float
) -> list[Sighting]:
    """Trends from `trends`, one per term, scope and hour (the runs of an hour are one
    sighting at the first of them, with the highest score)."""
    rows = client.query(
        SIGHTINGS_SQL,
        parameters={
            "since": int(since.timestamp()),
            "until": int(until.timestamp()),
            "min_z": min_z,
        },
    ).result_rows
    return [Sighting(kind, term, scope, as_utc(at), z) for kind, term, scope, at, z in rows]


EVENT_COLUMNS = (
    "kind",
    "term",
    "start",
    "last_seen",
    "topic",
    "scopes",
    "onsets",
    "onsets_until",
    "closed",
)


def write_events(
    client: Client, events: Sequence[Event], groups: Mapping[str, Sequence[str]]
) -> None:
    if not events:
        return
    client.insert(
        "lead_lag_events",
        [
            (
                event.kind,
                event.term,
                event.start,
                event.last_seen,
                topic_of(event.scopes, groups),
                event.scopes,
                [
                    (onset.scope, onset.without, onset.at, onset.mentions, onset.ratio, onset.z)
                    for onset in event.onsets
                ],
                event.onsets_until or datetime.fromtimestamp(0, UTC),
                event.closed,
            )
            for event in events
        ],
        column_names=list(EVENT_COLUMNS),
    )


def _onset(value: Any) -> Onset:
    """A tuple of the onsets column, as a tuple or a dict depending on the driver."""
    if isinstance(value, dict):
        value = tuple(value[name] for name in ("scope", "without", "at", "mentions", "ratio", "z"))
    scope, without, at, mentions, ratio, z = value
    return Onset(scope, without, as_utc(at), int(mentions), float(ratio), float(z))


EVENTS_SQL = """
SELECT kind, term, start, last_seen, scopes, onsets, onsets_until, closed
FROM lead_lag_events FINAL
WHERE start >= toDateTime({since:UInt32}, 'UTC') AND start <= toDateTime({until:UInt32}, 'UTC')
  {condition}
ORDER BY start
"""


def load_events(
    client: Client,
    since: datetime,
    until: datetime,
    terms: Iterable[tuple[str, str]] | None = None,
    open_only: bool = False,
) -> list[Event]:
    """Stored events starting in [since, until], only of `terms` when given."""
    conditions = []
    parameters: dict[str, Any] = {
        "since": int(since.timestamp()),
        "until": int(until.timestamp()),
    }
    if terms is not None:
        keys = sorted(set(terms))
        if not keys:
            return []
        conditions.append("AND (kind, term) IN {terms:Array(Tuple(String, String))}")
        parameters["terms"] = keys
    if open_only:
        conditions.append("AND NOT closed")
    rows = client.query(
        EVENTS_SQL.replace("{condition}", " ".join(conditions)), parameters=parameters
    ).result_rows
    events = []
    for kind, term, start, last_seen, scopes, onsets, onsets_until, closed in rows:
        until_at = as_utc(onsets_until)
        events.append(
            Event(
                kind=kind,
                term=term,
                start=as_utc(start),
                last_seen=as_utc(last_seen),
                scopes={scope: float(z) for scope, z in scopes.items()},
                onsets=[_onset(onset) for onset in onsets],
                onsets_until=until_at if until_at.timestamp() > 0 else None,
                closed=bool(closed),
            )
        )
    return events
