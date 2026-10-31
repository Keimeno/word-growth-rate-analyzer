"""Long-term detection end to end against a real ClickHouse, on a year of synthetic history.

Uses a throwaway database (conftest.py), skipped when ClickHouse isn't reachable locally.
The history is written straight into term_daily and scope_hourly, one row per day, with
Poisson noise from a fixed seed.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import numpy as np
import pytest
from helpers import make_config

from wgra.config import SAMPLE_SCOPE, Config, Env, LongTermConfig
from wgra.detect.long_term import (
    LongTermDetector,
    LongTermTrend,
    first_full_week,
    history_weeks,
    report_trends,
    week_start,
    write_long_term,
)
from wgra.detect.run import Analyzer
from wgra.detect.short_term import load_scopes
from wgra.notify.ntfy import Ntfy
from wgra.store import migrate

# the run is as of Monday 2026-06-22 00:30 UTC: the weeks before Monday Jun 22 count.
# In the past, notifications are logged with the time they're really sent.
END = date(2026, 6, 22)
AS_OF = datetime(2026, 6, 22, 0, 30, tzinfo=UTC)
START = END - timedelta(weeks=53)
# r/late started on a Wednesday 20 weeks ago: 19 complete weeks
LATE_START = END - timedelta(weeks=20) + timedelta(days=2)
SPIKE_WEEK = END - timedelta(weeks=3)

Share = Callable[[date], float]


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days)]


def exponential(first: float, last: float) -> Share:
    """Per 1,000 comments, from `first` at the start of the history to `last` at its end."""
    span = (END - START).days

    def share(day: date) -> float:
        return first * (last / first) ** ((day - START).days / span)

    return share


def constant(value: float) -> Share:
    return lambda day: value


def spike(base: float, peak: float) -> Share:
    return lambda day: peak if week_start(day) == SPIKE_WEEK else base


def weekend(value: float) -> Share:
    return lambda day: value if day.weekday() >= 5 else 0.0


def payday(high: float, low: float) -> Share:
    return lambda day: high if day.day <= 3 else low


class History:
    def __init__(self) -> None:
        self.rng = np.random.default_rng(42)
        self.terms: list[tuple[object, ...]] = []
        self.totals: list[tuple[object, ...]] = []
        # (subreddit, term, day) -> mentions, for checking the weekly shares
        self.mentions: dict[tuple[str, str, date], int] = {}
        self.comments: dict[tuple[str, date], int] = {}

    def subreddit(
        self,
        name: str,
        per_day: Callable[[date], int],
        terms: dict[str, Share],
        start: date = START,
        end: date = END + timedelta(days=7),
    ) -> None:
        for day in days(start, end):
            total = per_day(day)
            self.comments[name, day] = total
            self.totals.append((datetime(day.year, day.month, day.day), name, "comment", total, 0))
            for term, share in terms.items():
                mentions = int(self.rng.poisson(total * share(day) / 1000))
                self.mentions[name, term, day] = mentions
                if mentions:
                    kind = "phrase" if " " in term else "word"
                    self.terms.append((day, name, "comment", kind, term, mentions, mentions))

    def insert(self, client) -> None:
        client.insert(
            "scope_hourly",
            self.totals,
            column_names=["hour", "subreddit", "source", "docs", "tokens"],
        )
        client.insert(
            "term_daily",
            self.terms,
            column_names=["day", "subreddit", "source", "kind", "term", "occurrences", "docs"],
        )

    def weekly_share(self, subreddit: str, term: str, monday: date) -> float:
        week = days(monday, monday + timedelta(weeks=1))
        mentions = sum(self.mentions.get((subreddit, term, day), 0) for day in week)
        return 1000 * mentions / sum(self.comments[subreddit, day] for day in week)


def build_history() -> History:
    history = History()
    history.subreddit(
        "big",
        # busier on weekends
        lambda day: 70_000 if day.weekday() >= 5 else 50_000,
        {
            # steady growth from rare: about +38% a month
            "emerging thing": exponential(0.03, 1.5),
            # steady growth of a common topic: about +11% a month
            "mainstream": exponential(2.0, 8.0),
            # about −10% a month
            "fading": exponential(8.0, 2.0),
            "flat": constant(3.0),
            # one week at 20 times its usual share
            "spike": spike(0.5, 10.0),
            # seasonal: only mentioned on weekends, or around the first of the month
            "weekend": weekend(6.0),
            "payday": payday(4.0, 1.0),
            # growing as fast as "emerging thing", but far too rare: a few a week
            "rare": exponential(0.0005, 0.02),
            # the same everywhere in big, growing in small: see the group test
            "macro": constant(5.0),
        },
    )
    history.subreddit("small", lambda day: 2_000, {"macro": exponential(5.0, 20.0)})
    history.subreddit(
        "late", lambda day: 3_000, {"late riser": exponential(0.5, 8.0)}, start=LATE_START
    )
    # the current week: a burst that a run as of Monday morning must not see yet
    for day in days(END, END + timedelta(days=7)):
        history.terms.append((day, "big", "comment", "word", "flat", 50_000, 50_000))
    return history


@pytest.fixture(scope="module")
def history() -> History:
    return build_history()


def config_for_tests(**long_term: Any) -> Config:
    config = make_config(
        groups={"tech": ["big", "small"], "other": ["late"]},
        notify={"report_day": "monday", "report_time": "08:00", "timezone": "UTC"},
    )
    return replace(config, long_term=replace(LongTermConfig(), **long_term))


@pytest.fixture
def history_client(client, history):
    migrate(client)
    client.insert(
        "subreddit_groups",
        config_for_tests().group_memberships(),
        column_names=["group_name", "subreddit"],
    )
    history.insert(client)
    return client


def categories(trends: list[LongTermTrend]) -> dict[tuple[str, str, str], str]:
    return {(trend.horizon, trend.scope, trend.term): trend.category for trend in trends}


def test_history_counts_complete_weeks():
    monday = date(2026, 10, 12)
    assert first_full_week(datetime(2026, 10, 12, 15, tzinfo=UTC)) == monday
    assert first_full_week(datetime(2026, 10, 10, 20, tzinfo=UTC)) == monday
    assert history_weeks(datetime(2026, 10, 10, 20, tzinfo=UTC), monday) == 0
    assert history_weeks(datetime(2026, 10, 10, 20, tzinfo=UTC), date(2027, 1, 11)) == 13
    assert history_weeks(None, monday) == 0
    assert week_start(datetime(2026, 10, 18, 23, 59, tzinfo=UTC)) == monday


def test_classifies_trends_in_every_window(history_client):
    result = LongTermDetector(history_client, config_for_tests()).run(AS_OF)
    assert result.week == END
    found = categories(result.trends)

    for horizon in ("13w", "26w", "52w"):
        assert found[horizon, "r/big", "emerging thing"] == "emerging"
        assert found[horizon, "r/big", "mainstream"] == "mainstreaming"
        assert found[horizon, "r/big", "fading"] == "fading"
        # flat, seasonal, too rare, or only in the current week: never stored
        for term in ("flat", "weekend", "payday", "rare"):
            assert (horizon, "r/big", term) not in found, (horizon, term)
        # nothing in r/big changes for "macro"
        assert (horizon, "r/big", "macro") not in found
        assert found[horizon, "r/small", "macro"] == "mainstreaming"
    # the one week burst explains the change of the last 13 and 26 weeks; in 52 weeks it
    # isn't even a candidate
    assert found["13w", "r/big", "spike"] == "one-off"
    assert found["26w", "r/big", "spike"] == "one-off"
    assert ("52w", "r/big", "spike") not in found

    emerging = next(
        t
        for t in result.trends
        if (t.horizon, t.scope, t.term) == ("52w", "r/big", "emerging thing")
    )
    # 50 times in 53 weeks
    assert emerging.growth == pytest.approx(50 ** (4.35 / 53), rel=0.05)
    assert emerging.q_value < 0.05
    assert emerging.spike_share < 0.2
    assert emerging.weeks == 52
    assert len(emerging.weekly) == 52
    assert emerging.window_start == END - timedelta(weeks=52)
    assert emerging.start_share < 0.1 < 1.0 < emerging.end_share


def test_group_share_is_the_average_of_its_subreddits(history_client, history):
    result = LongTermDetector(history_client, config_for_tests()).run(AS_OF)
    found = categories(result.trends)
    # growing in small, flat in the 25 times bigger big: the average of the two grows
    assert found["52w", "tech", "macro"] == "mainstreaming"
    tech = next(
        t for t in result.trends if (t.horizon, t.scope, t.term) == ("52w", "tech", "macro")
    )
    assert tech.members == 2
    first_monday = END - timedelta(weeks=52)
    expected = [
        (
            history.weekly_share("big", "macro", monday)
            + history.weekly_share("small", "macro", monday)
        )
        / 2
        for monday in (first_monday + timedelta(weeks=week) for week in range(52))
    ]
    assert tech.weekly == pytest.approx(expected)

    # pooled, small's growth disappears in big's mentions
    pooled = LongTermDetector(history_client, config_for_tests(group_rate="pooled")).run(AS_OF)
    assert ("52w", "tech", "macro") not in categories(pooled.trends)
    # a subreddit is a subreddit either way
    assert categories(pooled.trends)["52w", "r/small", "macro"] == "mainstreaming"


def test_windows_need_enough_history(history_client):
    result = LongTermDetector(history_client, config_for_tests()).run(AS_OF)
    insufficient = {(gap.scope, gap.weeks): gap.available for gap in result.insufficient}
    # r/late has 19 complete weeks
    assert insufficient["r/late", 26] == 19
    assert insufficient["r/late", 52] == 19
    assert insufficient["other", 52] == 19
    assert ("r/late", 13) not in insufficient
    # nothing at all in the sample
    assert insufficient["sample", 13] == 0
    found = categories(result.trends)
    assert found["13w", "r/late", "late riser"] in ("emerging", "mainstreaming")
    # tracked is big, small and late: for 52 weeks without late (2 of 3 have the history)
    tracked = [t for t in result.trends if t.scope == "tracked"]
    assert {t.members for t in tracked if t.horizon == "52w"} == {2}
    assert {t.members for t in tracked if t.horizon == "13w"} == {3}

    # a year earlier there is no history at all
    early = LongTermDetector(history_client, config_for_tests()).run(AS_OF - timedelta(weeks=60))
    assert not early.trends
    assert not early.windows
    assert {gap.available for gap in early.insufficient} == {0}


def test_as_of_a_past_date_only_uses_the_weeks_before_it(history_client):
    # as of the spike's week, the spike hasn't happened yet
    as_of = datetime.combine(SPIKE_WEEK, datetime.min.time(), UTC) + timedelta(days=3)
    result = LongTermDetector(history_client, config_for_tests()).run(as_of)
    assert result.week == SPIKE_WEEK
    found = categories(result.trends)
    assert not [key for key in found if key[2] == "spike"]
    assert found["26w", "r/big", "emerging thing"] == "emerging"
    # 50 weeks of history then
    assert {gap.available for gap in result.insufficient if gap.scope == "r/big"} == {50}


def stored(client) -> set[tuple[str, str, str]]:
    rows = client.query("SELECT horizon, scope, term FROM long_term_trends FINAL").result_rows
    return set(rows)


def test_rerunning_the_same_week_replaces_rows(history_client):
    detector = LongTermDetector(history_client, config_for_tests())
    first = detector.run(AS_OF)
    write_long_term(history_client, first)
    # a day later: the same weeks
    second = detector.run(AS_OF + timedelta(days=1))
    assert second.week == first.week
    write_long_term(history_client, second)
    (count,) = history_client.query("SELECT count() FROM long_term_trends").result_rows[0]
    assert count == len(first.trends) == len(second.trends)

    # with other settings, what the earlier runs found and this one doesn't is gone
    stricter = LongTermDetector(history_client, config_for_tests(min_growth=1.2))
    third = stricter.run(AS_OF + timedelta(days=2))
    write_long_term(history_client, third)
    assert stored(history_client) == set(categories(third.trends))
    assert ("52w", "r/big", "mainstream") not in stored(history_client)
    assert ("52w", "r/big", "emerging thing") in stored(history_client)

    # a run of only some scopes leaves the others alone
    only_big = [scope for scope in load_scopes(history_client) if scope.name == "r/big"]
    write_long_term(history_client, stricter.run(AS_OF, scopes=only_big, horizons=[13]))
    assert stored(history_client) == set(categories(third.trends))
    # an earlier week is kept next to the latest
    write_long_term(history_client, detector.run(AS_OF - timedelta(weeks=1)))
    weeks = history_client.query("SELECT DISTINCT week FROM long_term_trends ORDER BY week")
    assert [week for (week,) in weeks.result_rows] == [END - timedelta(weeks=1), END]


def recording_ntfy() -> tuple[Ntfy, list[dict]]:
    sent: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    return Ntfy("http://ntfy", "wgra", transport=httpx.MockTransport(handle)), sent


def test_analyzer_runs_daily_and_reports_on_mondays(history_client):
    ntfy, sent = recording_ntfy()
    env = Env("", "", "", b"", "", 0, "", "", "", grafana_url="https://grafana.test")
    analyzer = Analyzer(config_for_tests(), env, history_client, ntfy)
    scopes = load_scopes(history_client)
    monday_night = datetime(2026, 6, 22, 0, 15, tzinfo=UTC)

    # before 00:30 UTC, and no report without a long-term run of this process
    assert not analyzer.long_term_due(monday_night)
    assert analyzer.send_weekly_reports(monday_night + timedelta(hours=9), scopes) == []
    assert analyzer.long_term_due(AS_OF)
    analyzer.run_long_term(AS_OF)
    assert not analyzer.long_term_due(AS_OF + timedelta(hours=12))
    assert analyzer.long_term_due(AS_OF + timedelta(days=1))

    # before 08:00 nothing, then one report per configured group, once
    assert analyzer.send_weekly_reports(datetime(2026, 6, 22, 7, 59, tzinfo=UTC), scopes) == []
    morning = datetime(2026, 6, 22, 8, 15, tzinfo=UTC)
    assert analyzer.send_weekly_reports(morning, scopes) == ["other", "tech"]
    assert analyzer.send_weekly_reports(morning + timedelta(hours=2), scopes) == []
    # not on tuesday
    assert analyzer.report_day(morning + timedelta(days=1)) is None

    tech = next(
        message for message in sent if message["title"].startswith("Long-term trends in tech")
    )
    assert tech["title"] == "Long-term trends in tech, weeks to Sun 21 Jun"
    body = tech["message"]
    assert "**Emerging**\n1. [emerging thing](https://grafana.test/d/wgra-terms?" in body
    assert "**Mainstreaming**" in body
    assert "**Fading**\n1. [fading]" in body
    assert "spike" not in body  # one-offs aren't reported
    assert "var-bucket=week" in body
    assert tech["click"] == "https://grafana.test/d/wgra-long-term?var-group=tech"
    kinds = history_client.query("SELECT kind, scope, ok FROM notifications ORDER BY scope")
    assert kinds.result_rows == [("weekly", "other", True), ("weekly", "tech", True)]


def test_report_lists_each_term_once_at_its_strongest(history_client):
    write_long_term(history_client, LongTermDetector(history_client, config_for_tests()).run(AS_OF))
    week, trends = report_trends(history_client, ["tech", "r/big", "r/small"], 5)
    assert week == END
    terms = [(trend.category, trend.term) for trend in trends]
    assert len(terms) == len(set(terms))
    assert {trend.category for trend in trends} == {"emerging", "mainstreaming", "fading"}
    emerging = next(trend for trend in trends if trend.term == "emerging thing")
    # strongest in a 13-week window of r/big (+36% a month), not tech's average
    assert emerging.scope == "r/big"
    assert emerging.growth == pytest.approx(1.35, abs=0.02)
    assert report_trends(history_client, ["nowhere"], 5) == (None, [])


def test_no_data_at_all(client):
    migrate(client)
    config = config_for_tests()
    client.insert(
        "subreddit_groups", config.group_memberships(), column_names=["group_name", "subreddit"]
    )
    result = LongTermDetector(client, config).run(AS_OF)
    assert not result.trends
    assert {gap.scope for gap in result.insufficient} >= {"r/big", "tech", "sample"}
    assert SAMPLE_SCOPE not in {gap.scope for gap in result.insufficient}
