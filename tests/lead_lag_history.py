"""Synthetic history with a planted lead–lag structure, for the lead–lag tests.

Ten weeks of hourly counts in five tracked subreddits and the r/all sample:

* "lead" terms: r/a picks each up first, r/b 3 days later (± 4 hours), and two of every
  three reach the sample (reddit-wide) 5 days after r/a
* "random" terms: r/c picks each up at a random time; some also show up in r/b, at an
  independent random time up to 10 days before or after
* "background" terms: bursts in r/d or r/e only, unrelated to anything

The history ends two days ago: `trends` deletes rows older than 90 days. Every burst lasts
48 hours at a constant share of the subreddit's comments, brand-new terms with no mentions
before. Comments are written to term_events (each by a different author, so the detector's
author gate passes) and the hourly totals to scope_hourly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from wgra.config import SAMPLE_SCOPE, Config
from wgra.detect.short_term import Detector, write_trends
from wgra.ingest.pipeline import TERM_COLUMNS
from wgra.store import migrate

DAYS = 70
# recent: `trends` deletes rows older than 90 days
END = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
START = END - timedelta(days=DAYS)
GROUPS = {"first": ["a", "c"], "second": ["b", "d", "e"]}
# comments and posts per hour
PER_HOUR = {"a": 100, "b": 150, "c": 100, "d": 80, "e": 80, SAMPLE_SCOPE: 400}
# a burst's mentions per hour
BURST_RATE = {"a": 2.0, "b": 3.0, "c": 2.0, "d": 2.0, "e": 2.0, SAMPLE_SCOPE: 4.0}
BURST_HOURS = 48
LEAD = timedelta(days=3)
SAMPLE_LEAD = timedelta(days=5)

LEADING_TERMS = 18
RANDOM_TERMS = 14
RANDOM_IN_B = 5
BACKGROUND_TERMS = 20


@dataclass(frozen=True)
class Burst:
    subreddit: str
    term: str
    start: datetime


def _hour(day: float) -> datetime:
    return START + timedelta(hours=round(day * 24))


class LeadLagHistory:
    def __init__(self, seed: int = 7):
        rng = np.random.default_rng(seed)
        self.bursts: list[Burst] = []
        self.leading = [f"lead{index:02d}" for index in range(LEADING_TERMS)]
        self.random = [f"random{index:02d}" for index in range(RANDOM_TERMS)]
        self.background = [f"background{index:02d}" for index in range(BACKGROUND_TERMS)]

        for index, term in enumerate(self.leading):
            first = _hour(6 + index * 2.6 + rng.uniform(0, 1))
            self.bursts.append(Burst("a", term, first))
            jitter = timedelta(hours=int(rng.integers(-4, 5)))
            self.bursts.append(Burst("b", term, first + LEAD + jitter))
            if index % 3:
                self.bursts.append(Burst(SAMPLE_SCOPE, term, first + SAMPLE_LEAD))
        for index, term in enumerate(self.random):
            first = _hour(rng.uniform(6, 56))
            self.bursts.append(Burst("c", term, first))
            if index < RANDOM_IN_B:
                other = first + timedelta(days=float(rng.uniform(-10, 10)))
                other = min(max(other, _hour(6)), _hour(58))
                self.bursts.append(
                    Burst("b", term, other.replace(minute=0, second=0, microsecond=0))
                )
        for index, term in enumerate(self.background):
            subreddit = "d" if index % 2 else "e"
            self.bursts.append(Burst(subreddit, term, _hour(rng.uniform(6, 58))))

        self._rng = rng

    def term_rows(self) -> list[tuple[object, ...]]:
        rows: list[tuple[object, ...]] = []
        author = 0
        for burst in self.bursts:
            for offset in range(BURST_HOURS):
                hour = burst.start + timedelta(hours=offset)
                for _ in range(int(self._rng.poisson(BURST_RATE[burst.subreddit]))):
                    author += 1
                    rows.append((hour, burst.subreddit, "comment", "word", burst.term, author, 1))
        return rows

    def insert(self, client) -> None:
        hours = [START + timedelta(hours=offset) for offset in range(DAYS * 24)]
        client.insert(
            "scope_hourly",
            [
                (hour, sub, "comment", docs, docs * 20)
                for sub, docs in PER_HOUR.items()
                for hour in hours
            ],
            column_names=["hour", "subreddit", "source", "docs", "tokens"],
        )
        client.insert("term_events", self.term_rows(), column_names=list(TERM_COLUMNS))

    def first_burst(self, subreddit: str, term: str) -> datetime:
        return min(b.start for b in self.bursts if (b.subreddit, b.term) == (subreddit, term))


def detect_daily(client, config: Config, start: datetime, end: datetime) -> int:
    """Runs the 24h detector once a day and stores the trends, like the live loop would
    (only daily, to keep the tests fast: a burst lasts 48 hours, so each is seen)."""
    detector = Detector(client, config)
    horizon = [h for h in config.detect.horizons if h.name == "24h"]
    stored = 0
    at = start
    while at <= end:
        trends = detector.run(at, horizons=horizon)
        write_trends(client, trends)
        stored += len(trends)
        at += timedelta(days=1)
    return stored


def build(client, config: Config, history: LeadLagHistory | None = None) -> LeadLagHistory:
    migrate(client)
    client.insert(
        "subreddit_groups", config.group_memberships(), column_names=["group_name", "subreddit"]
    )
    history = history or LeadLagHistory()
    history.insert(client)
    return history
