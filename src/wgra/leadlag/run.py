"""The lead–lag layer in `wgra analyze`: edges once a day, forecasts every run.

Daily (after `lead_lag.run_at`, UTC):
1. the trends since the last run become events (new ones, or added to theirs)
2. the onsets of every event whose span isn't over are recomputed with the new data
3. the edges are learned from the events of the training period and replace the day's

Every run (after short-term detection):
1. the terms trending in a leader subreddit now, and those with pending forecasts, get
   their events and onsets brought up to date (including the current hour)
2. forecasts for leaders' bursts that followers haven't picked up yet
3. pending forecasts are resolved
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time

from clickhouse_connect.driver.client import Client

from wgra.config import Config, LeadLagConfig
from wgra.detect.short_term import Trend, as_utc, next_hour
from wgra.leadlag.edges import Edge, EdgeResult, Network, learn_edges, load_edges, write_edges
from wgra.leadlag.events import (
    Event,
    Sighting,
    assign_events,
    event_span,
    hour_floor,
    load_events,
    load_sightings,
    write_events,
)
from wgra.leadlag.forecasts import (
    EdgeIndex,
    Forecast,
    decide,
    load_forecasts,
    resolve,
)
from wgra.leadlag.onsets import OnsetFinder

log = logging.getLogger(__name__)

# `trends` keeps rows for 90 days: the first run turns that much into events
TRENDS_DAYS = 90


@dataclass
class LearnResult:
    as_of: datetime
    # events that got new trends, and events whose onsets were computed
    new_sightings: int
    computed: int
    edges: EdgeResult
    seconds: float


@dataclass
class ForecastStep:
    new: list[Forecast] = field(default_factory=list)
    resolved: list[Forecast] = field(default_factory=list)
    # terms whose onsets were brought up to date
    terms: int = 0
    seconds: float = 0.0


def sightings_of(trends: Sequence[Trend], min_z: float) -> list[Sighting]:
    return [
        Sighting(trend.kind, trend.term, trend.scope, as_utc(trend.detected_at), trend.z)
        for trend in trends
        if not trend.subsumed_by and trend.z >= min_z
    ]


class LeadLag:
    def __init__(self, client: Client, config: Config):
        self._client = client
        self._config = config
        # the UTC day of this process's last daily run
        self.learned_day: date | None = None

    @property
    def settings(self) -> LeadLagConfig:
        return self._config.lead_lag

    def span(self) -> timedelta:
        return timedelta(hours=self.settings.lookback_hours, days=2 * self.settings.max_lag_days)

    def due(self, now: datetime) -> bool:
        """Once a day, after lead_lag.run_at (UTC)."""
        hours, minutes = map(int, self.settings.run_at.split(":"))
        now = as_utc(now)
        return self.learned_day != now.date() and now.time() >= clock_time(hours, minutes)

    def update_events(self, now: datetime) -> tuple[int, list[Event]]:
        """Turns the trends since the last run into events. Returns the number of sightings
        and every event whose span wasn't over, with the new ones."""
        (latest,) = self._client.query("SELECT max(last_seen) FROM lead_lag_events").result_rows[0]
        since = now - timedelta(days=min(TRENDS_DAYS, self.settings.training_days))
        if latest and as_utc(latest).timestamp() > 0:
            since = max(since, as_utc(latest) - self.span())
        sightings = load_sightings(self._client, since, now, self.settings.event_min_z)
        # every event a sighting since then can belong to
        existing = load_events(self._client, since - self.span(), now)
        touched = assign_events(sightings, existing, self.settings)
        events = {
            event.key: event
            for event in load_events(
                self._client,
                now - timedelta(days=self.settings.training_days),
                now,
                open_only=True,
            )
        }
        events.update({event.key: event for event in touched})
        return len(sightings), list(events.values())

    def learn(self, now: datetime | None = None, write: bool = True) -> LearnResult:
        started = time.monotonic()
        now = as_utc(now or datetime.now(UTC)).replace(microsecond=0)
        until = hour_floor(now)
        sightings, events = self.update_events(now)
        OnsetFinder(self._client, self._config).find(events, until)
        if write:
            write_events(self._client, events, self._config.groups)

        training = load_events(self._client, now - timedelta(days=self.settings.training_days), now)
        if not write:
            # what this run computed isn't stored, use it instead of the stored version
            computed = {event.key: event for event in events}
            stored = {event.key for event in training}
            training = [computed.get(event.key, event) for event in training]
            training += [event for key, event in computed.items() if key not in stored]
        result = learn_edges(training, Network.load(self._client), until, self.settings)
        if write:
            write_edges(self._client, result)
            if self._config.wikipedia.enabled:
                self.check_wikipedia(now)
        self.learned_day = now.date()
        learned = LearnResult(now, sightings, len(events), result, time.monotonic() - started)
        log.info(
            "lead-lag: %d trend sightings, onsets of %d events, %d training events "
            "(%d closed), %d pairs tested, %d edges, %.1fs",
            sightings,
            len(events),
            result.training_events,
            result.closed_events,
            result.tested,
            len(result.edges),
            learned.seconds,
        )
        return learned

    def check_wikipedia(self, now: datetime) -> None:
        """Compares the closed events of the last 90 days that aren't yet with Wikipedia
        (at most wikipedia.max_events_per_day). A failure doesn't stop the edges."""
        from wgra.leadlag.wikipedia import Wikimedia, WikipediaCheck

        wikimedia = Wikimedia(self._config.wikipedia)
        try:
            WikipediaCheck(self._client, self._config, wikimedia).run(
                now, TRENDS_DAYS, self._config.wikipedia.max_events_per_day
            )
        except Exception:
            log.exception("comparing with Wikipedia failed, trying again tomorrow")
        finally:
            wikimedia.close()

    def edges(self) -> tuple[date | None, list[Edge]]:
        return load_edges(self._client)

    def forecast(self, now: datetime, trends: Sequence[Trend]) -> ForecastStep:
        """New forecasts for this run's trends and the resolution of pending ones. Nothing
        is written, the caller decides the alerts first (write_forecasts)."""
        started = time.monotonic()
        now = as_utc(now).replace(microsecond=0)
        _, edges = self.edges()
        index = EdgeIndex(edges)
        sightings = sightings_of(trends, self.settings.event_min_z)
        leading = [s for s in sightings if s.scope in index.leaders]
        pending = load_forecasts(self._client, pending_only=True)
        if not leading and not pending:
            return ForecastStep(seconds=time.monotonic() - started)

        terms = {(s.kind, s.term) for s in leading} | {(f.kind, f.term) for f in pending}
        oldest = min([f.event_start for f in pending], default=now)
        existing = load_events(
            self._client, min(oldest, now - self.span()) - timedelta(hours=1), now, terms=terms
        )
        touched = assign_events(
            [s for s in sightings if (s.kind, s.term) in terms], existing, self.settings
        )
        events = {event.key: event for event in existing}
        events.update({event.key: event for event in touched})

        # the events of this run's leading terms (the one each sighting went to) and those
        # of the pending forecasts
        current = {
            key: event
            for key, event in events.items()
            if (event.kind, event.term) in {(s.kind, s.term) for s in leading}
            and event.start <= now < event_span(event.start, self.settings).end
        }
        needed = dict(current)
        for forecast in pending:
            if forecast.event_key in events:
                needed[forecast.event_key] = events[forecast.event_key]
        OnsetFinder(self._client, self._config).find(list(needed.values()), next_hour(now))
        write_events(self._client, list(needed.values()), self._config.groups)

        known = {f.key for f in load_forecasts(self._client, event_keys=current.keys())}
        step = ForecastStep(terms=len(needed))
        for event in current.values():
            leaders = {s.scope for s in leading if (s.kind, s.term) == (event.kind, event.term)}
            made = decide(
                event,
                leaders,
                index,
                now,
                self._config.groups,
                self.settings,
                self._config.forecast,
            )
            for forecast in made:
                if forecast.key not in known:
                    step.new.append(forecast)
        for forecast in pending:
            pending_event = needed.get(forecast.event_key)
            if pending_event is not None and resolve(forecast, pending_event, now):
                step.resolved.append(forecast)
        step.seconds = time.monotonic() - started
        return step
