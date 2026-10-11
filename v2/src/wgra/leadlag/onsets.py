"""Onsets: the first hour each scope picked up an event's term.

For every hour of an event's span, a scope's last `window_hours` (24) are scored against the
`reference_days` (28) before them with phase 2's weighted log odds (detect/scoring.py,
vectorized over the hours). The onset is the first hour the window passes the onset gates:
`onset_min_mentions`, `onset_min_ratio` times its usual share, and `onset_min_z`. It's the
hour a detector running then could have seen the term rise in the scope. The gates are
lower than the detector's (no author gate, the hourly author sketches can't be summed over
rolling windows cheaply), so an onset usually comes before the scope's first trend.

The scopes: every tracked subreddit, the r/all sample ("sample", reddit-wide), every
configured group, and every group without each of its subreddits. A subreddit can't lead
its own group, whose counts include its own; the rest of the group following is the
question that makes sense. Groups pool their subreddits' counts, like short-term detection.

Nothing after an hour is used for its onset, so onsets computed with data up to a later
time agree with those computed earlier: replays compute them once and only look at the
ones that were over at each step.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from clickhouse_connect.driver.client import Client
from numpy.typing import NDArray

from wgra.config import SAMPLE_GROUP, SAMPLE_SCOPE, TRACKED_GROUP, Config, LeadLagConfig
from wgra.detect.scoring import Prior, score_arrays
from wgra.detect.short_term import GROUP, SUBREDDIT, Scope, load_scopes, subreddit_scope
from wgra.leadlag.events import HOUR, Event, Onset, event_span

log = logging.getLogger(__name__)

# the scope name of the sample in trends, edges and forecasts: reddit-wide
SAMPLE = SAMPLE_GROUP


@dataclass(frozen=True, slots=True)
class Crossing:
    """Where a series first passed the onset gates."""

    index: int
    mentions: int
    ratio: float
    z: float


def first_crossings(
    mentions: NDArray[np.float64],
    totals: NDArray[np.float64],
    sample_mentions: float,
    prior: Prior,
    first: int,
    settings: LeadLagConfig,
) -> list[Crossing | None]:
    """The first hour index, from `first` on, at which each series' window passes the gates.

    `mentions` and `totals` are (series, hours): comments and posts mentioning the term,
    and all of them, per hour. The window ending at hour i covers hours i − window + 1 to i,
    the reference period the `reference_days` × 24 hours before. `first` must leave room for
    both. A series needs `min_reference_days` of data (hours since its first comment)
    before the window."""
    window = settings.window_hours
    reference = settings.reference_days * 24
    if first < window + reference - 1:
        raise ValueError("the series must start window + reference hours before `first`")
    count, hours = mentions.shape
    if first >= hours or count == 0:
        return [None] * count

    zeros = np.zeros((count, 1))
    cumulative_mentions = np.concatenate([zeros, np.cumsum(mentions, axis=1)], axis=1)
    cumulative_totals = np.concatenate([zeros, np.cumsum(totals, axis=1)], axis=1)
    # the column after hour i: sums over hours < end
    end = np.arange(first, hours) + 1
    window_start = end - window
    reference_start = window_start - reference

    def sums(cumulative: NDArray[np.float64]) -> tuple[NDArray[np.float64], ...]:
        return (
            cumulative[:, end] - cumulative[:, window_start],
            cumulative[:, window_start] - cumulative[:, reference_start],
        )

    y_window, y_reference = sums(cumulative_mentions)
    n_window, n_reference = sums(cumulative_totals)
    log_odds, z = score_arrays(y_window, n_window, y_reference, n_reference, sample_mentions, prior)

    has_data = totals > 0
    first_data = np.where(has_data.any(axis=1), has_data.argmax(axis=1), hours)
    enough_history = (window_start[None, :] - first_data[:, None]) >= (
        settings.min_reference_days * 24
    )
    passing = (
        (y_window >= settings.onset_min_mentions)
        & (n_window > 0)
        & enough_history
        & (log_odds >= math.log(settings.onset_min_ratio))
        & (z >= settings.onset_min_z)
    )
    crossings: list[Crossing | None] = []
    for row in range(count):
        if not passing[row].any():
            crossings.append(None)
            continue
        column = int(passing[row].argmax())
        crossings.append(
            Crossing(
                index=first + column,
                mentions=int(y_window[row, column]),
                ratio=float(math.exp(log_odds[row, column])),
                z=float(z[row, column]),
            )
        )
    return crossings


def _seconds(moment: datetime) -> int:
    return int(moment.timestamp())


# Term keys are "kind|term", mapped to their position in the chunk (from 1) by a hash
# table, so only integers come back
_KEY = "concat(kind, '|', term)"
_KEY_INDEX = f"transform({_KEY}, {{keys:Array(String)}}, {{indexes:Array(UInt32)}}, toUInt32(0))"
_COLUMN = "toUInt16(indexOf({columns:Array(String)}, subreddit) - 1)"
_HOUR_INDEX = "toUInt32(intDiv(toUInt32(hour) - {grid_start:UInt32}, 3600))"
_GRID = (
    "hour >= toDateTime({grid_start:UInt32}, 'UTC') AND hour < toDateTime({grid_end:UInt32}, 'UTC')"
)

MENTIONS_SQL = f"""
SELECT {_KEY_INDEX} AS key, {_COLUMN} AS column, {_HOUR_INDEX} AS hour_index,
       toFloat64(sum(docs)) AS docs
FROM term_hourly
WHERE subreddit IN {{columns:Array(String)}} AND source IN {{sources:Array(String)}}
  AND (kind, term) IN {{terms:Array(Tuple(String, String))}} AND {_GRID}
GROUP BY key, column, hour_index
"""

TOTALS_SQL = f"""
SELECT {_COLUMN} AS column, {_HOUR_INDEX} AS hour_index, toFloat64(sum(docs)) AS docs
FROM scope_hourly
WHERE subreddit IN {{columns:Array(String)}} AND source IN {{sources:Array(String)}} AND {_GRID}
GROUP BY column, hour_index
"""

# the prior: each term's mentions in the sample per day, and the sample's comments per day
SAMPLE_MENTIONS_SQL = f"""
SELECT {_KEY_INDEX} AS key, toUInt32(day - {{first_day:Date}}) AS day_index,
       toFloat64(sum(docs)) AS docs
FROM term_daily
WHERE subreddit = {{sample:String}} AND source IN {{sources:Array(String)}}
  AND (kind, term) IN {{terms:Array(Tuple(String, String))}}
  AND day >= {{first_day:Date}} AND day < {{last_day:Date}}
GROUP BY key, day_index
"""

SAMPLE_TOTALS_SQL = """
SELECT toUInt32(toDate(hour) - {first_day:Date}) AS day_index, toFloat64(sum(docs)) AS docs
FROM scope_hourly
WHERE subreddit = {sample:String} AND source IN {sources:Array(String)}
  AND hour >= toDateTime({first_day:Date}, 'UTC') AND hour < toDateTime({last_day:Date}, 'UTC')
GROUP BY day_index
"""

# events processed together: their grids are read in one query. A chunk of common words
# returns millions of rows; at 500 a query took up to 880 MiB on the production-scale
# benchmark (bench/lead_lag.py)
CHUNK_EVENTS = 250
CHUNK_DAYS = 7


@dataclass(frozen=True)
class Series:
    scope: str
    without: str
    mentions: NDArray[np.float64]
    totals: NDArray[np.float64]


def split_scopes(scopes: Sequence[Scope]) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    """The tracked subreddits, and the configured groups ("tracked" and "sample" aren't)."""
    subreddits = [scope.subreddits[0] for scope in scopes if scope.type == SUBREDDIT]
    groups = {
        scope.name: scope.subreddits
        for scope in scopes
        if scope.type == GROUP and scope.name not in (TRACKED_GROUP, SAMPLE_GROUP)
    }
    return subreddits, groups


class OnsetFinder:
    """Computes the onsets of events from term_hourly and scope_hourly."""

    def __init__(self, client: Client, config: Config, scopes: Sequence[Scope] | None = None):
        self._client = client
        self._config = config
        self.subreddits, self.groups = split_scopes(
            load_scopes(client) if scopes is None else scopes
        )
        # the columns of the hourly matrices: tracked subreddits, then the sample
        self.columns = [*self.subreddits, SAMPLE_SCOPE]
        self._column = {subreddit: index for index, subreddit in enumerate(self.columns)}

    @property
    def settings(self) -> LeadLagConfig:
        return self._config.lead_lag

    def find(self, events: Sequence[Event], until: datetime) -> None:
        """Sets the onsets of the events from the data before `until` (a full hour, or the
        end of the current hour in live runs), and whether their span is over."""
        started = time.monotonic()
        ordered = sorted(events, key=lambda event: event.start)
        chunk: list[Event] = []
        for event in ordered:
            if chunk and (
                len(chunk) >= CHUNK_EVENTS
                or event.start - chunk[0].start > timedelta(days=CHUNK_DAYS)
            ):
                self._find_chunk(chunk, until)
                chunk = []
            chunk.append(event)
        if chunk:
            self._find_chunk(chunk, until)
        log.debug("onsets of %d events in %.1fs", len(events), time.monotonic() - started)

    def _lead_in(self) -> timedelta:
        """Hours before a span's start its first window and reference period need."""
        return timedelta(hours=self.settings.window_hours + self.settings.reference_days * 24)

    def _find_chunk(self, events: list[Event], until: datetime) -> None:
        spans = {event.key: event_span(event.start, self.settings) for event in events}
        grid_start = min(span.start for span in spans.values()) - self._lead_in()
        grid_end = min(max(span.end for span in spans.values()), until)
        keys = sorted({(event.kind, event.term) for event in events})
        index = {key: number for number, key in enumerate(keys, start=1)}
        common = {
            "keys": [f"{kind}|{term}" for kind, term in keys],
            "indexes": list(range(1, len(keys) + 1)),
            "terms": keys,
            "columns": self.columns,
            "sources": list(self._config.detect.sources),
            "sample": SAMPLE_SCOPE,
        }

        totals = np.zeros((len(self.columns), 0))
        rows: NDArray | None = None
        if grid_end > grid_start:
            hours = int((grid_end - grid_start) / HOUR)
            grid = common | {"grid_start": _seconds(grid_start), "grid_end": _seconds(grid_end)}
            totals = np.zeros((len(self.columns), hours))
            for column, hour_index, docs in self._client.query(
                TOTALS_SQL, parameters=grid, settings={"log_comment": "lead-lag totals"}
            ).result_rows:
                totals[column, hour_index] = docs
            rows = self._client.query_np(
                MENTIONS_SQL, parameters=grid, settings={"log_comment": "lead-lag mentions"}
            )
            # by term, to slice each event's rows (sorting here costs ClickHouse no memory)
            rows = rows[np.argsort(rows["key"], kind="stable")] if len(rows) else rows
        priors = self._priors(events, index, common)

        key_column = rows["key"] if rows is not None and len(rows) else np.zeros(0, np.uint32)
        for event in events:
            span = spans[event.key]
            number = index[event.kind, event.term]
            start, stop = np.searchsorted(key_column, [number, number + 1])
            event_rows = rows[start:stop] if rows is not None else None
            prior, sample_mentions = priors[event.key]
            event.onsets = self._event_onsets(
                span.start,
                min(span.end, until),
                grid_start,
                totals,
                event_rows,
                prior,
                sample_mentions,
            )
            event.onsets_until = until
            event.closed = span.end <= until

    def _priors(
        self,
        events: list[Event],
        index: dict[tuple[str, str], int],
        common: dict[str, object],
    ) -> dict[tuple[str, str, datetime], tuple[Prior, float]]:
        """Each event's prior: the term's share of the sample in the `prior_days` before
        its span (phase 2 takes the days up to the window, here nothing after the span's
        start may count)."""
        detect = self._config.detect
        days = {event.key: event_span(event.start, self.settings).start.date() for event in events}
        first_day = min(days.values()) - timedelta(days=detect.prior_days)
        last_day = max(days.values())
        parameters = common | {"first_day": first_day, "last_day": last_day}
        length = (last_day - first_day).days + 1
        sample_totals = np.zeros(length)
        for day_index, docs in self._client.query(
            SAMPLE_TOTALS_SQL, parameters=parameters
        ).result_rows:
            sample_totals[day_index] = docs
        mentions = np.zeros((len(index) + 1, length))
        for key, day_index, docs in self._client.query(
            SAMPLE_MENTIONS_SQL, parameters=parameters
        ).result_rows:
            mentions[key, day_index] = docs
        cumulative_totals = np.concatenate([[0.0], np.cumsum(sample_totals)])
        cumulative_mentions = np.concatenate(
            [np.zeros((len(index) + 1, 1)), np.cumsum(mentions, axis=1)], axis=1
        )

        priors = {}
        for event in events:
            end = (days[event.key] - first_day).days
            begin = max(end - detect.prior_days, 0)
            number = index[event.kind, event.term]
            prior = Prior(
                total=int(cumulative_totals[end] - cumulative_totals[begin]),
                weight=detect.prior_weight,
                floor=detect.prior_floor,
            )
            sample = float(cumulative_mentions[number, end] - cumulative_mentions[number, begin])
            priors[event.key] = (prior, sample)
        return priors

    def _event_onsets(
        self,
        span_start: datetime,
        span_end: datetime,
        grid_start: datetime,
        totals: NDArray[np.float64],
        rows: NDArray | None,
        prior: Prior,
        sample_mentions: float,
    ) -> list[Onset]:
        event_start = span_start - self._lead_in()
        offset = int((event_start - grid_start) / HOUR)
        hours = int((span_end - event_start) / HOUR)
        first = int(self._lead_in() / HOUR)
        if hours <= first:
            return []
        mentions = np.zeros((len(self.columns), hours))
        if rows is not None and len(rows):
            positions = rows["hour_index"].astype(np.int64) - offset
            inside = (positions >= 0) & (positions < hours)
            np.add.at(
                mentions,
                (rows["column"][inside].astype(np.int64), positions[inside]),
                rows["docs"][inside],
            )
        event_totals = totals[:, offset : offset + hours]

        series = self._series(mentions, event_totals, first)
        if not series:
            return []
        crossings = first_crossings(
            np.stack([s.mentions for s in series]),
            np.stack([s.totals for s in series]),
            sample_mentions,
            prior,
            first,
            self.settings,
        )
        return [
            Onset(
                scope=s.scope,
                without=s.without,
                at=event_start + crossing.index * HOUR,
                mentions=crossing.mentions,
                ratio=crossing.ratio,
                z=crossing.z,
            )
            for s, crossing in zip(series, crossings, strict=True)
            if crossing is not None
        ]

    def _series(
        self, mentions: NDArray[np.float64], totals: NDArray[np.float64], first: int
    ) -> list[Series]:
        """Every scope that could cross: enough mentions in the hours the windows cover."""
        searched = slice(first - self.settings.window_hours + 1, None)
        minimum = self.settings.onset_min_mentions

        def mentioned(values: NDArray[np.float64]) -> bool:
            return bool(values[searched].sum() >= minimum)

        series = [
            Series(subreddit_scope(subreddit), "", mentions[column], totals[column])
            for column, subreddit in enumerate(self.subreddits)
            if mentioned(mentions[column])
        ]
        sample = self._column[SAMPLE_SCOPE]
        if mentioned(mentions[sample]):
            series.append(Series(SAMPLE, "", mentions[sample], totals[sample]))
        for group, members in self.groups.items():
            columns = [self._column[member] for member in members if member in self._column]
            group_mentions = mentions[columns].sum(axis=0)
            if not mentioned(group_mentions):
                continue
            group_totals = totals[columns].sum(axis=0)
            series.append(Series(group, "", group_mentions, group_totals))
            if len(columns) < 2:
                continue
            for column in columns:
                rest = group_mentions - mentions[column]
                if mentioned(rest):
                    series.append(
                        Series(
                            group,
                            subreddit_scope(self.columns[column]),
                            rest,
                            group_totals - totals[column],
                        )
                    )
        return series
