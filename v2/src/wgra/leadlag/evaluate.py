"""How good the forecasts would have been: replays them over stored history, no lookahead.

The input is what a replay's detector found at every step (or the trends the live
analyzer stored). At each step only what was known then is used:

* the events of the trends seen so far
* edges learned once a day, after `lead_lag.run_at`, as of that time (edges.learn_edges
  only counts onsets whose hour was over, misses whose window was)
* forecasts for the step's trends in leader subreddits, by the same `decide` as the live
  loop

Onsets are computed once with all the data: nothing after an hour goes into its onset, so
those of the hours before a step are what a run at the step would have computed. Outcomes
are scored with all the data, they're what happened.

Scored per event and follower, the first forecast (of several leaders the most likely):

* precision: the share that came true
* recall: of the followers that did follow a subreddit's onset within `max_lag_days`, the
  share forecast before they crossed
* lead time: from the forecast to the follower's onset, for the hits
* calibration: per probability bin, the forecasts and the share that came true; the Brier
  score against that of always forecasting the follower's base rate
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as clock_time
from itertools import pairwise

import numpy as np
from clickhouse_connect.driver.client import Client

from wgra.config import Config
from wgra.leadlag.edges import Network, learn_edges
from wgra.leadlag.events import HOUR, Event, Sighting, assign_events, event_span
from wgra.leadlag.forecasts import HIT, MISS, EdgeIndex, Forecast, decide, resolve
from wgra.leadlag.onsets import OnsetFinder


@dataclass
class Step:
    at: datetime
    sightings: list[Sighting]


@dataclass(frozen=True)
class Bin:
    low: float
    high: float
    forecasts: int
    predicted: float
    observed: float


@dataclass
class Evaluation:
    start: datetime
    end: datetime
    steps: int
    events: int
    # edges at the last step, and steps that had any
    edges: int
    steps_with_edges: int
    # every forecast made, the first of each event, follower and leader
    forecasts: list[Forecast] = field(default_factory=list)
    # the first per event and follower, with a known outcome, and those still pending
    scored: list[Forecast] = field(default_factory=list)
    pending: int = 0
    # (event, follower) pairs that followed a subreddit, and those forecast before
    followed: int = 0
    forecast_in_time: int = 0

    @property
    def hits(self) -> list[Forecast]:
        return [forecast for forecast in self.scored if forecast.outcome == HIT]

    @property
    def precision(self) -> float | None:
        return len(self.hits) / len(self.scored) if self.scored else None

    @property
    def recall(self) -> float | None:
        return self.forecast_in_time / self.followed if self.followed else None

    def lead_hours(self) -> list[float]:
        """From each hit's forecast to the follower's onset."""
        return sorted(
            (forecast.follower_onset - forecast.created_at) / HOUR
            for forecast in self.hits
            if forecast.follower_onset is not None
        )

    def brier(self) -> tuple[float, float] | None:
        """(Brier score of the forecasts, of forecasting the base rate instead)."""
        if not self.scored:
            return None
        outcomes = np.array([forecast.outcome == HIT for forecast in self.scored], dtype=float)
        forecast_p = np.array([forecast.probability for forecast in self.scored])
        base_p = np.array([forecast.base_rate for forecast in self.scored])
        return (
            float(np.mean((forecast_p - outcomes) ** 2)),
            float(np.mean((base_p - outcomes) ** 2)),
        )

    def calibration(self, bins: int = 5) -> list[Bin]:
        result = []
        for low, high in pairwise(np.linspace(0, 1, bins + 1)):
            inside = [
                forecast
                for forecast in self.scored
                if low <= forecast.probability < high or (high == 1 and forecast.probability == 1)
            ]
            if not inside:
                continue
            result.append(
                Bin(
                    low=float(low),
                    high=float(high),
                    forecasts=len(inside),
                    predicted=float(np.mean([forecast.probability for forecast in inside])),
                    observed=sum(forecast.outcome == HIT for forecast in inside) / len(inside),
                )
            )
        return result


def scheduled_run(moment: datetime, run_at: str) -> datetime:
    """The latest daily run time (`run_at`, UTC) at or before `moment`."""
    hours, minutes = map(int, run_at.split(":"))
    today = datetime.combine(moment.date(), clock_time(hours, minutes), moment.tzinfo)
    return today if today <= moment else today - timedelta(days=1)


def first_per_follower(forecasts: Sequence[Forecast]) -> list[Forecast]:
    """Per event and follower: the earliest forecast, the most likely leader's of those."""
    best: dict[tuple[str, str, datetime, str], Forecast] = {}
    for forecast in forecasts:
        key = (forecast.kind, forecast.term, forecast.event_start, forecast.follower)
        current = best.get(key)
        if current is None or (forecast.created_at, -forecast.probability) < (
            current.created_at,
            -current.probability,
        ):
            best[key] = forecast
    return list(best.values())


def evaluate(
    client: Client,
    config: Config,
    steps: Sequence[Step],
    data_until: datetime,
    network: Network | None = None,
) -> Evaluation:
    settings = config.lead_lag
    steps = sorted(steps, key=lambda step: step.at)
    if not steps:
        raise ValueError("nothing to evaluate, no steps")
    sightings = [sighting for step in steps for sighting in step.sightings]
    events = assign_events(sightings, [], settings, keep_sightings=True)
    OnsetFinder(client, config).find(events, data_until)
    network = network or Network.load(client)
    by_term: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for event in events:
        by_term[event.kind, event.term].append(event)
    by_key = {event.key: event for event in events}

    edges = EdgeIndex([])
    learned_at: datetime | None = None
    steps_with_edges = 0
    made: dict[tuple[str, str, datetime, str, str], Forecast] = {}
    for step in steps:
        at = step.at
        # like the live loop: once a day, at the first step after run_at
        if learned_at is None or learned_at < scheduled_run(at, settings.run_at):
            known = [event for event in events if event.start <= at]
            edges = EdgeIndex(learn_edges(known, network, at, settings).edges)
            learned_at = at
        if len(edges):
            steps_with_edges += 1
        leading: dict[tuple[str, str], set[str]] = defaultdict(set)
        for sighting in step.sightings:
            if sighting.scope in edges.leaders:
                leading[sighting.kind, sighting.term].add(sighting.scope)
        for term, leaders in leading.items():
            current = next(
                (
                    candidate
                    for candidate in by_term[term]
                    if candidate.start <= at < event_span(candidate.start, settings).end
                ),
                None,
            )
            if current is None:
                continue
            for forecast in decide(
                current, leaders, edges, at, config.groups, settings, config.forecast
            ):
                made.setdefault(forecast.key, forecast)

    for forecast in made.values():
        resolve(forecast, by_key[forecast.event_key], data_until)
    firsts = first_per_follower(list(made.values()))
    scored = [forecast for forecast in firsts if forecast.outcome in (HIT, MISS)]

    # recall: the followers that did follow, in the events the replay saw start
    start, end = steps[0].at, steps[-1].at
    max_lag = timedelta(days=settings.max_lag_days)
    followed: dict[tuple[tuple[str, str, datetime], str], datetime] = {}
    for event in events:
        if not start <= event.start <= end:
            continue
        span = event_span(event.start, settings)
        onsets = event.onsets_known(data_until)
        for (scope, without), onset in onsets.items():
            if without or scope not in network.leaders or onset.at > span.leaders_until:
                continue
            for follower in network.followers(scope):
                follows = onsets.get(follower.key)
                if follows is not None and onset.at < follows.at <= onset.at + max_lag:
                    key = (event.key, follower.scope)
                    followed[key] = min(followed.get(key, follows.at), follows.at)
    in_time = sum(
        1
        for forecast in firsts
        if forecast.outcome == HIT
        and (forecast.event_key, forecast.follower) in followed
        and forecast.follower_onset is not None
        and forecast.created_at <= forecast.follower_onset
    )
    return Evaluation(
        start=start,
        end=end,
        steps=len(steps),
        events=sum(1 for event in events if start <= event.start <= end),
        edges=len(edges),
        steps_with_edges=steps_with_edges,
        forecasts=list(made.values()),
        scored=scored,
        pending=len(firsts) - len(scored),
        followed=len(followed),
        forecast_in_time=in_time,
    )


def _hours(value: float) -> str:
    return f"{value / 24:.1f}d" if value >= 48 else f"{value:.0f}h"


def report(evaluation: Evaluation) -> str:
    lines = [
        f"forecasts: {evaluation.events} events in {evaluation.steps} steps, "
        f"edges at {evaluation.steps_with_edges} of them ({evaluation.edges} at the end)"
    ]
    if not evaluation.forecasts:
        lines.append("  no forecasts: no edges yet, or no leader's burst passed the gates")
        return "\n".join(lines)
    precision, recall = evaluation.precision, evaluation.recall
    lines.append(
        f"  {len(evaluation.scored)} scored (per event and follower), "
        f"{evaluation.pending} still pending, {len(evaluation.forecasts)} forecasts in all"
    )
    scored = (
        f"{precision:.0%} ({len(evaluation.hits)} of {len(evaluation.scored)})"
        if precision is not None
        else "-"
    )
    found = (
        f"{recall:.0%} ({evaluation.forecast_in_time} of {evaluation.followed} followers that "
        "followed a subreddit were forecast before they did)"
        if recall is not None
        else "- (no follower followed)"
    )
    lines.append(f"  precision {scored} | recall {found}")
    leads = evaluation.lead_hours()
    if leads:
        q25, median, q75 = np.percentile(leads, [25, 50, 75])
        lines.append(
            f"  warning before the follower's onset: median {_hours(median)} "
            f"(IQR {_hours(q25)} to {_hours(q75)})"
        )
    if brier := evaluation.brier():
        score, base = brier
        skill = 1 - score / base if base else float("nan")
        lines.append(f"  Brier score {score:.3f}, base rate alone {base:.3f}: skill {skill:+.2f}")
    bins = evaluation.calibration()
    if bins:
        lines.append("  calibration: probability → came true")
        for item in bins:
            lines.append(
                f"    {item.low:.1f}–{item.high:.1f}: {item.forecasts:>4} forecasts, "
                f"predicted {item.predicted:.0%}, came true {item.observed:.0%}"
            )
    return "\n".join(lines)
