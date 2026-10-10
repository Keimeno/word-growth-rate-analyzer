"""Short-term burst detection: which terms are mentioned far more than usual right now.

For every scope (each tracked subreddit, each group) and horizon (24h, 6h), ClickHouse
finds the candidates, terms mentioned often enough and by enough people in the window,
and counts them in the window, the reference period and the r/all sample. Python scores
them (see scoring.py), applies the gates, suppresses words that a trending phrase
explains, and computes the breadth of group trends.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import astuple, dataclass, fields
from datetime import UTC, date, datetime, timedelta
from typing import Any

from clickhouse_connect.driver.client import Client

from wgra.config import SAMPLE_SCOPE, TRACKED_GROUP, Config, DetectConfig, Horizon
from wgra.detect.scoring import WORD, Candidate, Counts, Prior, breadth, passes, subsumed_by
from wgra.text.terms import stopwords

log = logging.getLogger(__name__)

SUBREDDIT = "subreddit"
GROUP = "group"


def subreddit_scope(subreddit: str) -> str:
    """Subreddit scopes are prefixed, the group "de" and r/de are different scopes."""
    return f"r/{subreddit}"


@dataclass(frozen=True)
class Scope:
    name: str
    type: str
    subreddits: tuple[str, ...]


def load_scopes(client: Client, exclude: Iterable[str] = ()) -> list[Scope]:
    """Every tracked subreddit and every group, from the subreddit_groups table."""
    rows = client.query(
        "SELECT group_name, groupArray(subreddit) FROM subreddit_groups "
        "GROUP BY group_name ORDER BY group_name"
    ).result_rows
    groups = {name: tuple(sorted(subs)) for name, subs in rows}
    scopes = [
        Scope(subreddit_scope(sub), SUBREDDIT, (sub,)) for sub in groups.get(TRACKED_GROUP, ())
    ]
    scopes += [Scope(name, GROUP, subs) for name, subs in groups.items()]
    excluded = set(exclude)
    return [scope for scope in scopes if scope.name not in excluded]


@dataclass
class Trend:
    """One row of the trends table."""

    horizon: str
    scope: str
    term: str
    detected_at: datetime
    scope_type: str
    kind: str
    window_start: datetime
    window_end: datetime
    mentions: int
    total: int
    reference_mentions: int
    reference_total: int
    authors: int
    prior: float
    log_odds: float
    ratio: float
    z: float
    is_new: bool
    breadth: int = 0
    members: int = 0
    subsumed_by: str = ""
    rank: int = 0
    # days with data in the reference period, alerts wait for enough history
    reference_days: int = 0
    alert: str = ""

    def row(self) -> tuple[Any, ...]:
        return astuple(self)


TREND_COLUMNS = tuple(f.name for f in fields(Trend))


@dataclass(frozen=True)
class Window:
    """The hours a horizon compares, as of `end` (exclusive, on a full hour)."""

    horizon: Horizon
    end: datetime

    def __post_init__(self) -> None:
        if self.end.minute or self.end.second or self.end.microsecond:
            raise ValueError(f"the window must end on a full hour, not {self.end}")

    @property
    def start(self) -> datetime:
        return self.end - timedelta(hours=self.horizon.window_hours)

    @property
    def reference_start(self) -> datetime:
        return self.start - timedelta(days=self.horizon.reference_days)

    def parameters(self) -> dict[str, Any]:
        return {
            "end": int(self.end.timestamp()),
            "window_start": int(self.start.timestamp()),
            "start": int(self.reference_start.timestamp()),
            "window_hours": self.horizon.window_hours,
            "same_hours": self.horizon.same_hours,
        }


# hours before the end of the window: 1 is the last hour of the window
_AGE = "intDiv({end:UInt32} - toUInt32(hour), 3600)"
IN_WINDOW = f"{_AGE} <= {{window_hours:UInt32}}"
# for the 6h horizon, the reference period only has the same hours of the day
IN_REFERENCE = (
    f"{_AGE} > {{window_hours:UInt32}} "
    f"AND (NOT {{same_hours:Bool}} OR ({_AGE} - 1) % 24 < {{window_hours:UInt32}})"
)
HOURS = "hour >= toDateTime({start:UInt32}, 'UTC') AND hour < toDateTime({end:UInt32}, 'UTC')"
WINDOW_HOURS = (
    "hour >= toDateTime({window_start:UInt32}, 'UTC') AND hour < toDateTime({end:UInt32}, 'UTC')"
)

TOTALS_SQL = f"""
SELECT subreddit,
       sumIf(docs, {IN_WINDOW}) AS total,
       sumIf(docs, {IN_REFERENCE}) AS reference_total,
       -- 24 hour periods before the window with data (not dates, the window can start
       -- at any hour)
       uniqExactIf(intDiv({_AGE} - 1, 24), {IN_REFERENCE}) AS reference_days
FROM scope_hourly
WHERE source IN {{sources:Array(String)}} AND {HOURS}
GROUP BY subreddit
"""

SAMPLE_TOTAL_SQL = """
SELECT sum(docs)
FROM scope_hourly
WHERE subreddit = {sample:String} AND source IN {sources:Array(String)}
  AND hour >= toDateTime({first_day:Date}, 'UTC')
  AND hour < toDateTime({last_day:Date} + 1, 'UTC')
"""

# The candidates are found in the window alone, and only for them the reference period
# (28 days) and the sample (90 days) are read. Mentions are counted first: a window has
# millions of distinct terms, merging the author sketches of all of them would take a lot
# of memory, and only the few thousand mentioned often enough need them.
WINDOW_TERMS = f"""
    subreddit IN {{subreddits:Array(String)}} AND source IN {{sources:Array(String)}}
    AND kind IN {{kinds:Array(String)}} AND {WINDOW_HOURS}
"""
CANDIDATES = f"""
SELECT kind, term
FROM term_hourly
WHERE {WINDOW_TERMS} AND (kind, term) IN (
    SELECT kind, term FROM term_hourly WHERE {WINDOW_TERMS}
    GROUP BY kind, term HAVING sum(docs) >= {{min_mentions:UInt64}}
)
GROUP BY kind, term
HAVING uniqCombinedMerge(12)(authors) >= {{min_authors:UInt64}}
"""


COUNTS_SQL = f"""
WITH candidates AS ({CANDIDATES})
SELECT c.kind, c.term, c.mentions, c.reference_mentions, c.authors, s.sample_mentions
FROM (
    SELECT kind, term,
           sumIf(docs, {IN_WINDOW}) AS mentions,
           sumIf(docs, {IN_REFERENCE}) AS reference_mentions,
           uniqCombinedMergeIf(12)(authors, {IN_WINDOW}) AS authors
    FROM term_hourly
    WHERE subreddit IN {{subreddits:Array(String)}} AND source IN {{sources:Array(String)}}
      AND {HOURS} AND (kind, term) IN (SELECT kind, term FROM candidates)
    GROUP BY kind, term
) AS c
LEFT JOIN (
    SELECT kind, term, sum(docs) AS sample_mentions
    FROM term_daily
    WHERE subreddit = {{sample:String}} AND source IN {{sources:Array(String)}}
      AND day BETWEEN {{first_day:Date}} AND {{last_day:Date}}
      AND (kind, term) IN (SELECT kind, term FROM candidates)
    GROUP BY kind, term
) AS s USING (kind, term)
"""

# For the breadth of a group's trends: their counts in each member subreddit. Only for
# the trends that are stored, a few dozen terms, so only a sliver of the table is read.
MEMBERS_SQL = f"""
SELECT subreddit, kind, term,
       sumIf(docs, {IN_WINDOW}) AS mentions,
       sumIf(docs, {IN_REFERENCE}) AS reference_mentions
FROM term_hourly
WHERE subreddit IN {{subreddits:Array(String)}} AND source IN {{sources:Array(String)}}
  AND {HOURS} AND term IN {{terms:Array(String)}}
GROUP BY subreddit, kind, term
"""


@dataclass(frozen=True)
class ScopeTotals:
    total: int
    reference_total: int
    reference_days: int


def prior_days(end: datetime, days: int) -> tuple[date, date]:
    """The days the prior is taken from, up to and including the window's last day."""
    last_day = (end - timedelta(seconds=1)).date()
    return last_day - timedelta(days=days - 1), last_day


class Detector:
    def __init__(self, client: Client, config: Config):
        self._client = client
        self._config = config

    @property
    def settings(self) -> DetectConfig:
        return self._config.detect

    def run(
        self,
        end: datetime,
        detected_at: datetime | None = None,
        scopes: Sequence[Scope] | None = None,
        horizons: Sequence[Horizon] | None = None,
    ) -> list[Trend]:
        """Scores every scope and horizon, as of `end` (a full hour, exclusive)."""
        detected_at = (detected_at or end).replace(microsecond=0)
        if scopes is None:
            scopes = load_scopes(self._client, self.settings.exclude_scopes)
        first_day, last_day = prior_days(end, self.settings.prior_days)
        common = {
            "sources": list(self.settings.sources),
            "kinds": list(self.settings.kinds),
            "sample": SAMPLE_SCOPE,
            "first_day": first_day,
            "last_day": last_day,
        }
        sample_total = self._client.query(SAMPLE_TOTAL_SQL, parameters=common).result_rows[0][0]
        prior = Prior(
            total=int(sample_total or 0),
            weight=self.settings.prior_weight,
            floor=self.settings.prior_floor,
        )

        trends: list[Trend] = []
        for horizon in horizons or self.settings.horizons:
            window = Window(horizon, end)
            parameters = common | window.parameters()
            totals = {
                sub: ScopeTotals(total, reference_total, reference_days)
                for sub, total, reference_total, reference_days in self._client.query(
                    TOTALS_SQL, parameters=parameters
                ).result_rows
            }
            for scope in scopes:
                started = time.monotonic()
                found = self.score_scope(scope, window, parameters, totals, prior, detected_at)
                log.debug(
                    "%s %s: %d trends in %.1fs",
                    horizon.name,
                    scope.name,
                    len(found),
                    time.monotonic() - started,
                )
                trends += found
        return trends

    def member_counts(
        self,
        group: Scope,
        trends: Sequence[Candidate],
        parameters: dict[str, Any],
        totals: dict[str, ScopeTotals],
    ) -> dict[tuple[str, str], list[Counts]]:
        """Each trend's counts in each member subreddit of the group."""
        if not trends:
            return {}
        sample = {(c.kind, c.term): c.counts.sample_mentions for c in trends}
        rows = self._client.query(
            MEMBERS_SQL,
            parameters=parameters
            | {"subreddits": list(group.subreddits), "terms": sorted({c.term for c in trends})},
        ).result_rows
        counts: dict[tuple[str, str], list[Counts]] = defaultdict(list)
        for subreddit, kind, term, mentions, reference_mentions in rows:
            member = totals.get(subreddit)
            if member and (kind, term) in sample:
                counts[kind, term].append(
                    Counts(
                        mentions,
                        member.total,
                        reference_mentions,
                        member.reference_total,
                        sample[kind, term],
                    )
                )
        return counts

    def stopwords(self, scope: Scope) -> frozenset[str]:
        """Single words that are never a trend: stopwords in every language of the scope.

        "war" is a stopword in German ("was"), but not in r/worldnews."""
        languages = {self._config.language(sub) for sub in scope.subreddits}
        return frozenset.intersection(*(stopwords(language) for language in languages))

    def score_scope(
        self,
        scope: Scope,
        window: Window,
        parameters: dict[str, Any],
        totals: dict[str, ScopeTotals],
        prior: Prior,
        detected_at: datetime,
    ) -> list[Trend]:
        members = [totals[sub] for sub in scope.subreddits if sub in totals]
        total = sum(member.total for member in members)
        reference_total = sum(member.reference_total for member in members)
        reference_days = max((member.reference_days for member in members), default=0)
        thresholds = self.settings.thresholds_for(scope.name)
        if total < thresholds.min_mentions:
            return []

        rows = self._client.query(
            COUNTS_SQL,
            parameters=parameters
            | {
                "subreddits": list(scope.subreddits),
                "min_mentions": thresholds.min_mentions,
                "min_authors": thresholds.min_authors,
            },
        ).result_rows

        stop = self.stopwords(scope)
        candidates = [
            Candidate(
                kind,
                term,
                Counts(mentions, total, reference_mentions, reference_total, sample),
                authors,
            )
            for kind, term, mentions, reference_mentions, authors, sample in rows
            if not (kind == WORD and term in stop)
        ]
        scores = {(c.kind, c.term): c.counts.score(prior) for c in candidates}
        trending = [
            c
            for c in candidates
            if passes(scores[c.kind, c.term], c.counts.mentions, c.authors, thresholds)
        ]
        trending.sort(key=lambda c: scores[c.kind, c.term].z, reverse=True)
        stored = trending[: self.settings.max_per_scope]
        member_counts = (
            self.member_counts(scope, stored, parameters, totals) if scope.type == GROUP else {}
        )

        trends = []
        for rank, candidate in enumerate(stored, start=1):
            score = scores[candidate.kind, candidate.term]
            counts = candidate.counts
            bursting, mentioning = (
                breadth(
                    member_counts.get((candidate.kind, candidate.term), []),
                    prior,
                    self.settings.breadth_min_z,
                    self.settings.breadth_min_mentions,
                )
                if scope.type == GROUP
                else (0, 0)
            )
            trends.append(
                Trend(
                    horizon=window.horizon.name,
                    scope=scope.name,
                    term=candidate.term,
                    detected_at=detected_at,
                    scope_type=scope.type,
                    kind=candidate.kind,
                    window_start=window.start,
                    window_end=window.end,
                    mentions=counts.mentions,
                    total=counts.total,
                    reference_mentions=counts.reference_mentions,
                    reference_total=counts.reference_total,
                    authors=candidate.authors,
                    prior=score.alpha,
                    log_odds=score.log_odds,
                    ratio=score.ratio,
                    z=score.z,
                    # only with enough history to tell
                    is_new=counts.reference_mentions <= self.settings.new_max_reference
                    and reference_days >= self.settings.min_reference_days,
                    breadth=bursting,
                    members=mentioning,
                    subsumed_by=subsumed_by(candidate, trending, prior, thresholds) or "",
                    rank=rank,
                    reference_days=reference_days,
                )
            )
        return trends


def write_trends(client: Client, trends: Sequence[Trend]) -> None:
    if trends:
        client.insert("trends", [trend.row() for trend in trends], column_names=list(TREND_COLUMNS))


def as_utc(moment: datetime) -> datetime:
    """ClickHouse returns naive datetimes, in UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def next_hour(moment: datetime) -> datetime:
    """The end of the hour `moment` is in: live runs include the current, partial hour."""
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
