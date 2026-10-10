"""Long-term trends: which terms grow or fade steadily over months, per scope.

Once a day (`wgra analyze`, after midnight UTC) or on demand (`wgra long-term --once`),
for every scope (each tracked subreddit, each group) and window (13, 26 and 52 weeks)
whose subreddits have enough history:

1. Weekly shares: comments and posts mentioning the term per week (ISO weeks, Monday to
   Sunday, UTC, the current partial week left out) divided by all comments and posts
   (scope_hourly). A group's share is the average of its subreddits' shares (macro), or
   all mentions divided by all comments (pooled), see `long_term.group_rate`.
2. ClickHouse, for every term above the volume floor: least squares of the log share over
   the week index (simpleLinearRegression). The terms growing or shrinking fastest, by the
   t of the fit, are the candidates.
3. Python, for the candidates: Theil–Sen growth, Mann–Kendall p-value, spike share and
   peak (see trend_stats.py). Benjamini–Hochberg over every term the run tested (all
   above the floor, in every scope and window; those that weren't candidates count as
   p = 1), then each candidate is classified as emerging, mainstreaming, fading, one-off
   or flat. All but flat are stored in long_term_trends.

Results only change when a week completes, every day after Monday's run repeats it.
Rows are keyed by the week the run was in, so repeating it replaces them.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import astuple, dataclass, field, fields
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from clickhouse_connect.driver.client import Client

from wgra.config import MACRO, Config, LongTermConfig
from wgra.detect.short_term import Scope, as_utc, load_scopes
from wgra.detect.trend_stats import (
    FLAT,
    ONE_OFF,
    WEEKS_PER_MONTH,
    MannKendall,
    benjamini_hochberg,
    classify,
    half_growth,
    mann_kendall,
    peak_ratio,
    per_month,
    spike_share,
    theil_sen,
)
from wgra.notify.messages import REPORTED, LongTermSummary

log = logging.getLogger(__name__)


def horizon_name(weeks: int) -> str:
    return f"{weeks}w"


def week_start(moment: date | datetime) -> date:
    """The Monday of the (ISO, UTC) week the moment is in."""
    day = as_utc(moment).date() if isinstance(moment, datetime) else moment
    return day - timedelta(days=day.weekday())


def first_full_week(first_comment: datetime) -> date:
    """The first week the collection covered from its Monday on.

    Measured on comments: their listings only reach back minutes, while the first listing
    of posts can reach back days and would make a week look covered that wasn't.
    """
    day = as_utc(first_comment).date()
    return day if day.weekday() == 0 else week_start(day) + timedelta(weeks=1)


def history_weeks(first_comment: datetime | None, end: date) -> int:
    """Complete weeks of history before `end` (a Monday)."""
    if first_comment is None:
        return 0
    return max((end - first_full_week(first_comment)).days // 7, 0)


@dataclass
class LongTermTrend:
    """One row of the long_term_trends table."""

    horizon: str
    scope: str
    term: str
    # the Monday the analyzed weeks end before: the week the run was in
    week: date
    detected_at: datetime
    scope_type: str
    kind: str
    category: str
    window_start: date
    weeks: int
    members: int
    mentions: int
    total: int
    growth: float
    slope: float
    ols_growth: float
    start_share: float
    end_share: float
    change: float
    peak: float
    mk_s: int
    mk_z: float
    p_value: float
    q_value: float
    spike_share: float
    weekly: list[float]
    rank: int = 0

    def row(self) -> tuple[Any, ...]:
        return astuple(self)


LONG_TERM_COLUMNS = tuple(f.name for f in fields(LongTermTrend))


@dataclass(frozen=True)
class Window:
    """A scope analyzed over the `weeks` weeks before `end` (a Monday)."""

    scope: Scope
    weeks: int
    end: date
    # the subreddits whose history covers the window, the others are left out
    members: tuple[str, ...]

    @property
    def start(self) -> date:
        return self.end - timedelta(weeks=self.weeks)

    @property
    def horizon(self) -> str:
        return horizon_name(self.weeks)


@dataclass(frozen=True)
class Insufficient:
    """A scope and window without enough history."""

    scope: str
    weeks: int
    # complete weeks of history the scope has
    available: int


@dataclass
class Candidate:
    window: Window
    kind: str
    term: str
    # comments and posts mentioning it in the window, in all members together
    mentions: int
    # its share per week (macro or pooled), NaN for weeks without data
    shares: list[float]
    # comments and posts per week in all members together
    totals: list[float]
    ols_slope: float


@dataclass
class WindowStats:
    """What the first pass found for one scope and window."""

    window: Window
    above_floor: int
    candidates: int
    seconds: float


@dataclass
class LongTermResult:
    week: date
    detected_at: datetime
    trends: list[LongTermTrend] = field(default_factory=list)
    windows: list[WindowStats] = field(default_factory=list)
    insufficient: list[Insufficient] = field(default_factory=list)
    # terms that got the robust statistics
    candidates: int = 0
    # the first complete week of data in any tracked subreddit, None without data
    first_week: date | None = None
    seconds: float = 0.0

    @property
    def tested(self) -> int:
        """Terms the first pass tested, all above the floor: the Benjamini–Hochberg family."""
        return sum(stats.above_floor for stats in self.windows)


# when each subreddit's collection started (a start after a replay's weeks is 0 weeks)
FIRST_COMMENTS_SQL = """
SELECT subreddit, min(hour) FROM scope_hourly WHERE source = 'comment' GROUP BY subreddit
"""

WEEKLY_TOTALS_SQL = """
SELECT subreddit, intDiv(toDate(hour) - {start:Date}, 7) AS week, sum(docs)
FROM scope_hourly
WHERE source IN {sources:Array(String)}
  AND hour >= toDateTime({start:Date}, 'UTC') AND hour < toDateTime({end:Date}, 'UTC')
GROUP BY subreddit, week
"""

TERMS = (
    "subreddit IN {members:Array(String)} AND source IN {sources:Array(String)} "
    "AND kind IN {kinds:Array(String)} AND day >= {start:Date} AND day < {end:Date}"
)
# a row's mentions as an array over the weeks of the window, at its week. Summed up per
# term, that is its mentions per week. (Built from sparse (week, mentions) pairs instead,
# the lambda would capture the pairs, which ClickHouse copies for every week.)
WEEKLY = (
    "arrayMap(w -> if(w = intDiv(day - {start:Date}, 7), toUInt32(docs), 0), range({weeks:UInt16}))"
)

# Per scope and window, in two passes over the term_daily rows of the scope's
# subreddits. Both group them by (subreddit, term, kind), the order of the table's key,
# so ClickHouse aggregates them as they stream by instead of holding the millions of
# terms of a year in memory (with small blocks: the parts are read side by side).
#
# 1. The terms above the volume floor. For a group of k subreddits, a term above it in
#    all of them together has at least 1/k of it in one of them: those are found per
#    subreddit, then counted exactly.
# 2. Their mentions per week and subreddit (the primary index skips most of the rest).
SUBREDDIT_FLOOR = f"""
    above_floor AS (
        SELECT kind, term FROM term_daily WHERE {TERMS}
        GROUP BY subreddit, term, kind HAVING sum(docs) >= {{min_total:UInt64}}
    ),"""
GROUP_FLOOR = f"""
    candidates AS (
        SELECT DISTINCT kind, term FROM (
            SELECT subreddit, term, kind FROM term_daily WHERE {TERMS}
            GROUP BY subreddit, term, kind HAVING sum(docs) >= {{member_min:UInt64}}
        )
    ),
    above_floor AS (
        SELECT kind, term FROM term_daily
        WHERE {TERMS} AND (kind, term) IN (SELECT kind, term FROM candidates)
        GROUP BY kind, term HAVING sum(docs) >= {{min_total:UInt64}}
    ),"""

FIRST_PASS = f"""
WITH{{floor}}
    per_member AS (
        SELECT subreddit, kind, term, sumForEach({WEEKLY}) AS by_week
        FROM term_daily
        WHERE {TERMS} AND (kind, term) IN (SELECT kind, term FROM above_floor)
        GROUP BY subreddit, term, kind
    ),
    -- comments and posts per week of each member, a table of k rows
    member_totals AS (
        SELECT pair.1 AS subreddit, pair.2 AS totals
        FROM (SELECT arrayJoin(arrayZip({{members:Array(String)}},
                                        {{totals:Array(Array(Float64))}})) AS pair)
    ),
    -- per term and week: the members' shares summed (the macro average divides them by
    -- the number of members), or their mentions (pooled). One Float32 per week keeps the
    -- state of the hundred thousand terms of a big group small.
    series AS (
        SELECT kind, term,
               sum(arraySum(by_week)) AS mentions,
               sumForEach(if({{macro:Bool}},
                             arrayMap((y, n) -> toFloat32(if(n > 0, y / n, 0)), by_week, totals),
                             arrayMap(y -> toFloat32(y), by_week))) AS weekly_sum
        FROM per_member INNER JOIN member_totals USING subreddit
        GROUP BY kind, term
    )
SELECT kind, term, mentions, shares, ols_slope, terms_above_floor
FROM (
    SELECT kind, term, mentions,
           -- pooled: comments and posts per week in all members, active: members with any
           arrayMap((s, n, k) -> if(n = 0, nan, if({{macro:Bool}}, s / k, s / n)),
                    weekly_sum, {{pooled:Array(Float64)}}, {{active:Array(UInt16)}}) AS shares,
           -- the weeks with data, and the log share in them (pseudo-mentions for zero weeks)
           arrayFilter((w, n) -> n > 0, range({{weeks:UInt16}}), {{pooled:Array(Float64)}}) AS xs,
           arrayFilter((v, n) -> n > 0,
                       arrayMap((s, n) -> log(s + {{pseudo:Float64}} / n),
                                shares, {{pooled:Array(Float64)}}),
                       {{pooled:Array(Float64)}}) AS ys,
           arrayReduce('simpleLinearRegression', arrayMap(x -> toFloat64(x), xs), ys).1
               AS ols_slope,
           arrayReduce('corr', arrayMap(x -> toFloat64(x), xs), ys) AS r,
           r * sqrt((length(xs) - 2) / greatest(1 - r * r, 1e-12)) AS t,
           count() OVER () AS terms_above_floor
    FROM series
)
-- the ones growing or shrinking at least min_growth first, the strongest fit first
ORDER BY abs(ols_slope) >= {{min_slope:Float64}} DESC, abs(t) DESC
LIMIT {{limit:UInt32}}
SETTINGS optimize_aggregation_in_order = 1, max_block_size = 8192
"""


def first_pass_sql(group: bool) -> str:
    return FIRST_PASS.replace("{floor}", GROUP_FLOOR if group else SUBREDDIT_FLOOR)


class LongTermDetector:
    def __init__(self, client: Client, config: Config):
        self._client = client
        self._config = config

    @property
    def settings(self) -> LongTermConfig:
        return self._config.long_term

    def run(
        self,
        as_of: datetime,
        scopes: Sequence[Scope] | None = None,
        horizons: Sequence[int] | None = None,
    ) -> LongTermResult:
        """Analyzes the complete weeks before `as_of`'s week, for every scope and window."""
        started = time.monotonic()
        detected_at = as_utc(as_of).replace(microsecond=0)
        end = week_start(detected_at)
        result = LongTermResult(week=end, detected_at=detected_at)
        if scopes is None:
            scopes = load_scopes(self._client, self.settings.exclude_scopes)
        horizons = sorted(horizons or self.settings.horizons)
        if not horizons:
            return result

        first_comments = {
            subreddit: as_utc(first)
            for subreddit, first in self._client.query(FIRST_COMMENTS_SQL).result_rows
        }
        result.first_week = min(map(first_full_week, first_comments.values()), default=None)
        longest_start = end - timedelta(weeks=horizons[-1])
        totals: dict[str, list[float]] = defaultdict(lambda: [0.0] * horizons[-1])
        for subreddit, week, docs in self._client.query(
            WEEKLY_TOTALS_SQL,
            parameters={
                "start": longest_start,
                "end": end,
                "sources": list(self._config.detect.sources),
            },
        ).result_rows:
            totals[subreddit][week] = float(docs)

        candidates: list[Candidate] = []
        for weeks in horizons:
            for scope in scopes:
                history = {
                    sub: history_weeks(first_comments.get(sub), end) for sub in scope.subreddits
                }
                members = tuple(sub for sub in scope.subreddits if history[sub] >= weeks)
                if not members or len(members) < self.settings.min_member_share * len(history):
                    result.insufficient.append(
                        Insufficient(scope.name, weeks, self.available(history))
                    )
                    continue
                window = Window(scope, weeks, end, members)
                # the window's weeks are the last ones of the longest window's
                offset = horizons[-1] - weeks
                found, stats = self.first_pass(window, [totals[sub][offset:] for sub in members])
                candidates += found
                result.windows.append(stats)
                log.debug(
                    "%s %s: %d above the floor, %d candidates, %.1fs",
                    window.horizon,
                    scope.name,
                    stats.above_floor,
                    stats.candidates,
                    stats.seconds,
                )

        result.candidates = len(candidates)
        result.trends = self.classify(candidates, result.tested, detected_at)
        result.seconds = time.monotonic() - started
        return result

    def available(self, history: dict[str, int]) -> int:
        """Weeks of history of a scope: the most that enough of its subreddits have."""
        weeks = sorted(history.values(), reverse=True)
        needed = max(math.ceil(self.settings.min_member_share * len(weeks)), 1)
        return weeks[needed - 1] if len(weeks) >= needed else 0

    def first_pass(
        self, window: Window, member_totals: list[list[float]]
    ) -> tuple[list[Candidate], WindowStats]:
        """The least squares pass in ClickHouse: the candidates of one scope and window."""
        started = time.monotonic()
        settings = self.settings
        min_total = math.ceil(settings.min_mentions_per_week * window.weeks)
        group = len(window.members) > 1
        pooled = [sum(week) for week in zip(*member_totals, strict=True)]
        min_slope = math.log(settings.min_growth) / WEEKS_PER_MONTH
        rows = self._client.query(
            first_pass_sql(group),
            parameters={
                "members": list(window.members),
                "totals": member_totals,
                "pooled": pooled,
                "active": [
                    sum(total > 0 for total in week) for week in zip(*member_totals, strict=True)
                ],
                "weeks": window.weeks,
                "start": window.start,
                "end": window.end,
                "sources": list(self._config.detect.sources),
                "kinds": list(self._config.detect.kinds),
                "min_total": min_total,
                "member_min": math.ceil(min_total / len(window.members)),
                "macro": settings.group_rate == MACRO,
                "pseudo": settings.pseudo_mentions,
                "min_slope": min_slope,
                "limit": settings.max_candidates,
            },
            # in system.query_log, to see which scope took how long
            settings={"log_comment": f"long-term {window.horizon} {window.scope.name}"},
        ).result_rows
        found = [
            Candidate(window, kind, term, int(mentions), list(shares), pooled, slope)
            for kind, term, mentions, shares, slope, _ in rows
            if abs(slope) >= min_slope
        ]
        stats = WindowStats(
            window,
            above_floor=rows[0][-1] if rows else 0,
            candidates=len(found),
            seconds=time.monotonic() - started,
        )
        return found, stats

    def classify(
        self, candidates: list[Candidate], tests: int, detected_at: datetime
    ) -> list[LongTermTrend]:
        """The robust statistics for every candidate, then the categories.

        `tests` is how many terms the first pass tested, all of them count for
        Benjamini–Hochberg (the ones that weren't candidates with p = 1).
        """
        settings = self.settings
        scored = [Scored.of(candidate, settings) for candidate in candidates]
        q_values = benjamini_hochberg([score.mann_kendall.p for score in scored], tests)

        trends: list[LongTermTrend] = []
        for score, q in zip(scored, q_values, strict=True):
            category = classify(
                score.growth,
                float(q),
                score.spike_share,
                score.change,
                score.peak,
                score.start_share,
                settings,
            )
            if category != FLAT:
                trends.append(score.trend(category, float(q), detected_at))
        return rank(trends, settings.max_per_category)


@dataclass(frozen=True)
class Scored:
    """A candidate with its robust statistics."""

    candidate: Candidate
    slope: float
    intercept: float
    mann_kendall: MannKendall
    spike_share: float
    change: float
    peak: float

    @classmethod
    def of(cls, candidate: Candidate, settings: LongTermConfig) -> Scored:
        shares = np.asarray(candidate.shares, dtype=np.float64)
        totals = np.asarray(candidate.totals, dtype=np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            log_shares = np.where(
                totals > 0, np.log(shares + settings.pseudo_mentions / totals), np.nan
            )
        slope, intercept = theil_sen(log_shares)
        return cls(
            candidate,
            slope,
            intercept,
            # rank based: the same on shares and log shares, but zero weeks stay ties
            mann_kendall(shares),
            spike_share(log_shares, settings.spike_weeks),
            half_growth(log_shares),
            peak_ratio(shares),
        )

    @property
    def growth(self) -> float:
        return per_month(self.slope)

    @property
    def start_share(self) -> float:
        """The Theil–Sen line at the first week, per 1,000."""
        return 1000 * math.exp(self.intercept)

    @property
    def end_share(self) -> float:
        return 1000 * math.exp(self.intercept + self.slope * (len(self.candidate.shares) - 1))

    def trend(self, category: str, q: float, detected_at: datetime) -> LongTermTrend:
        candidate = self.candidate
        window = candidate.window
        return LongTermTrend(
            horizon=window.horizon,
            scope=window.scope.name,
            term=candidate.term,
            week=window.end,
            detected_at=detected_at,
            scope_type=window.scope.type,
            kind=candidate.kind,
            category=category,
            window_start=window.start,
            weeks=sum(total > 0 for total in candidate.totals),
            members=len(window.members),
            mentions=candidate.mentions,
            total=int(sum(candidate.totals)),
            growth=self.growth,
            slope=self.slope,
            ols_growth=per_month(candidate.ols_slope),
            start_share=self.start_share,
            end_share=self.end_share,
            change=self.change,
            peak=self.peak,
            mk_s=self.mann_kendall.s,
            mk_z=self.mann_kendall.z,
            p_value=self.mann_kendall.p,
            q_value=q,
            spike_share=self.spike_share,
            weekly=[1000 * share for share in candidate.shares],
        )


def rank(trends: list[LongTermTrend], limit: int) -> list[LongTermTrend]:
    """The strongest `limit` per scope, window and category: by growth or decline, one-offs
    by the change between the halves of the window."""

    def strength(trend: LongTermTrend) -> float:
        return abs(math.log(trend.change if trend.category == ONE_OFF else trend.growth))

    groups: dict[tuple[str, str, str], list[LongTermTrend]] = defaultdict(list)
    for trend in trends:
        groups[trend.horizon, trend.scope, trend.category].append(trend)
    kept = []
    for members in groups.values():
        members.sort(key=strength, reverse=True)
        for position, trend in enumerate(members[:limit], start=1):
            trend.rank = position
            kept.append(trend)
    return kept


def write_long_term(client: Client, result: LongTermResult) -> None:
    """Replaces the results of the analyzed scopes and windows for the run's week.

    The runs of a week find the same, unless the settings changed: what an earlier run
    found and this one doesn't would otherwise stay.
    """
    analyzed = sorted({(stats.window.horizon, stats.window.scope.name) for stats in result.windows})
    if analyzed:
        client.command(
            "DELETE FROM long_term_trends WHERE week = {week:Date} "
            "AND (horizon, scope) IN {analyzed:Array(Tuple(String, String))}",
            parameters={"week": result.week, "analyzed": analyzed},
        )
    if result.trends:
        client.insert(
            "long_term_trends",
            [trend.row() for trend in result.trends],
            column_names=list(LONG_TERM_COLUMNS),
        )


def report_trends(
    client: Client, scopes: Sequence[str], size: int
) -> tuple[date | None, list[LongTermSummary]]:
    """The latest week's long-term trends in the scopes, for the weekly report: per
    category the `size` fastest growing or fading terms, each at its strongest."""
    rows = client.query(
        """
        WITH (SELECT max(week) FROM long_term_trends) AS latest
        SELECT latest, term, argMax(scope, strength), category,
               argMax(toUInt16(toUInt16OrZero(trimRight(horizon, 'w'))), strength),
               argMax(growth, strength), argMax(start_share, strength),
               argMax(end_share, strength)
        FROM (
            SELECT *, abs(log(growth)) AS strength FROM long_term_trends FINAL
            WHERE week = latest AND scope IN {scopes:Array(String)}
              AND category IN {categories:Array(String)}
        )
        GROUP BY term, category
        ORDER BY category, max(strength) DESC, term
        LIMIT {size:UInt32} BY category
        """,
        parameters={"scopes": list(scopes), "categories": list(REPORTED), "size": size},
    ).result_rows
    if not rows:
        return None, []
    return rows[0][0], [LongTermSummary(*row[1:]) for row in rows]
