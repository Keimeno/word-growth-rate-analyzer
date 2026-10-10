"""Detection end to end against a real ClickHouse, on 29 days of synthetic history.

Uses a throwaway database (conftest.py), skipped when ClickHouse isn't reachable locally.
"""

import io
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from helpers import make_config

from wgra.config import SAMPLE_SCOPE, Config, Env, Horizon, NotifyConfig
from wgra.detect.alerts import SENT
from wgra.detect.replay import replay, report
from wgra.detect.run import Analyzer
from wgra.detect.short_term import Detector, Trend, write_trends
from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS
from wgra.notify.ntfy import Ntfy
from wgra.query import latest_trends
from wgra.store import migrate

# the window of the 24h horizon is Sep 29 12:00 to Sep 30 12:00
END = datetime(2026, 9, 30, 12, tzinfo=UTC)
WINDOW_START = END - timedelta(hours=24)
HISTORY_START = WINDOW_START - timedelta(days=28)

VISION_PRO = [("phrase", "vision pro"), ("word", "vision"), ("word", "pro")]


class History:
    """Comments of synthetic subreddits, as the ingester would write them."""

    def __init__(self) -> None:
        self.items: list[tuple[object, ...]] = []
        self.terms: list[tuple[object, ...]] = []
        self._next_id = 0

    def comments(
        self,
        subreddit: str,
        hour: datetime,
        count: int,
        terms: list[tuple[str, str]] | None = None,
        author: int | None = None,
    ) -> None:
        """`count` comments in the hour, each mentioning all `terms`, by different authors
        unless `author` is given."""
        for index in range(count):
            self._next_id += 1
            author_hash = author if author is not None else self._next_id
            self.items.append(
                (
                    f"t1_{self._next_id}",
                    "comment",
                    subreddit,
                    hour + timedelta(minutes=index % 60),
                    author_hash,
                    "text",
                    f"/r/{subreddit}/comments/x/{self._next_id}",
                    10,
                )
            )
            for kind, term in terms or []:
                self.terms.append((hour, subreddit, "comment", kind, term, author_hash, 1))

    def insert(self, client) -> None:
        client.insert("items", self.items, column_names=list(ITEM_COLUMNS))
        client.insert("term_events", self.terms, column_names=list(TERM_COLUMNS))


def hours(start: datetime, end: datetime) -> Iterator[datetime]:
    while start < end:
        yield start
        start += timedelta(hours=1)


def build_history() -> History:
    history = History()
    for hour in hours(HISTORY_START, END):
        # everyday chatter
        history.comments("technology", hour, 20)
        history.comments("programming", hour, 10)
        history.comments(SAMPLE_SCOPE, hour, 40)
        # mentioned as always: never a trend
        history.comments("technology", hour, 2, [("word", "rust")])
        history.comments(SAMPLE_SCOPE, hour, 1, [("word", "rust")])
        # every morning: a trend only if mornings are compared with whole days
        if 6 <= hour.hour < 12:
            history.comments("technology", hour, 3, [("word", "breakfast")])

    # once a day before the window
    for day in range(28):
        daily = HISTORY_START + timedelta(days=day)
        history.comments("technology", daily, 1, [("word", "pro")])
        if day % 2:
            history.comments("technology", daily, 1, [("word", "vision")])

    burst = END - timedelta(hours=3)
    # a new product: the phrase trends, "vision" and "pro" only because of it
    history.comments("technology", burst, 30, VISION_PRO)
    # a new name, in both subreddits of the group
    history.comments("technology", burst, 15, [("word", "newthing")])
    history.comments("programming", burst, 12, [("word", "newthing")])
    # one person repeating themselves
    history.comments("technology", burst, 40, [("word", "spammy")], author=7)
    return history


@pytest.fixture
def history_client(client):
    migrate(client)
    config = make_config(groups={"tech": ["technology", "programming"]})
    client.insert(
        "subreddit_groups", config.group_memberships(), column_names=["group_name", "subreddit"]
    )
    build_history().insert(client)
    return client


def config_for_tests() -> Config:
    config = make_config(groups={"tech": ["technology", "programming"]})
    # "vision pro" has 30 authors, "newthing" 27: only the first alerts
    notify = NotifyConfig(alert_min_z=5, alert_min_authors=28, digest_time="08:00")
    return replace(config, notify=notify)


def by_key(trends: list[Trend]) -> dict[tuple[str, str, str], Trend]:
    return {(trend.horizon, trend.scope, trend.term): trend for trend in trends}


def test_detects_bursts_new_terms_and_subsumption(history_client):
    trends = by_key(Detector(history_client, config_for_tests()).run(END))

    vision_pro = trends["24h", "r/technology", "vision pro"]
    assert (vision_pro.mentions, vision_pro.reference_mentions, vision_pro.authors) == (30, 0, 30)
    assert vision_pro.is_new
    assert vision_pro.z > 5
    assert vision_pro.subsumed_by == ""
    assert vision_pro.reference_days == 28
    # chatter and rust, the mornings in the window, the bursts
    assert vision_pro.total == 24 * 22 + 6 * 3 + 30 + 15 + 40
    # "pro" and "vision" trend too, but only because of "vision pro"
    assert trends["24h", "r/technology", "pro"].subsumed_by == "vision pro"
    assert trends["24h", "r/technology", "vision"].subsumed_by == "vision pro"

    # the group counts both subreddits, and the term trends in both of them
    newthing = trends["24h", "tech", "newthing"]
    assert newthing.mentions == 27
    assert (newthing.breadth, newthing.members) == (2, 2)
    assert newthing.scope_type == "group"
    assert ("24h", "r/programming", "newthing") in trends
    assert ("24h", "tracked", "newthing") in trends

    terms = {term for _, _, term in trends}
    assert "rust" not in terms  # stable
    assert "spammy" not in terms  # one author


def test_the_6h_window_compares_the_same_hours_of_the_day(history_client):
    detector = Detector(history_client, config_for_tests())
    same_hours = Horizon("6h", 6, same_hours=True)
    all_hours = Horizon("6h-all", 6, same_hours=False)
    trends = by_key(detector.run(END, horizons=[same_hours, all_hours]))
    # every morning has breakfast: only against whole days it looks like a trend
    assert ("6h", "r/technology", "breakfast") not in trends
    assert ("6h-all", "r/technology", "breakfast") in trends
    assert ("6h", "r/technology", "vision pro") in trends


def test_nothing_after_the_end_is_used(history_client):
    # as of before the burst, nothing trends yet
    trends = Detector(history_client, config_for_tests()).run(END - timedelta(hours=4))
    assert not [trend for trend in trends if trend.term in ("vision pro", "newthing")]


def test_rerunning_replaces_rows(history_client):
    trends = Detector(history_client, config_for_tests()).run(END)
    write_trends(history_client, trends)
    write_trends(history_client, trends)
    (count,) = history_client.query("SELECT count() FROM trends FINAL").result_rows[0]
    assert count == len(trends)


def recording_ntfy() -> tuple[Ntfy, list[dict]]:
    sent: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    return Ntfy("http://ntfy", "wgra", transport=httpx.MockTransport(handle)), sent


def test_analyzer_alerts_once_and_sends_one_digest_per_day(history_client):
    ntfy, sent = recording_ntfy()
    env = Env("", "", "", b"", "", 0, "", "", "", grafana_url="https://grafana.test")
    analyzer = Analyzer(config_for_tests(), env, history_client, ntfy)
    now = END - timedelta(minutes=1)

    first = analyzer.run_once(now)
    alerts = [trend for trend in first.trends if trend.alert == SENT]
    # the strongest story alerts once, though it trends in r/technology, tech and tracked
    assert [trend.term for trend in alerts] == ["vision pro"]
    assert sent[0]["title"].startswith("vision pro · ")
    assert sent[0]["click"].startswith("https://grafana.test/d/wgra-terms?var-terms=vision+pro")
    # 11:59 UTC is past the digest time: one digest for the only configured group
    assert first.digests == ["tech"]
    digest = sent[-1]
    assert digest["title"].startswith("Trending in tech")
    assert "[vision pro]" in digest["message"]
    assert "[pro]" not in digest["message"]  # subsumed

    second = analyzer.run_once(now + timedelta(minutes=15))
    assert not [trend for trend in second.trends if trend.alert == SENT]
    assert {trend.alert for trend in second.trends if trend.term == "vision pro"} >= {"cooldown"}
    assert second.digests == []
    assert len(sent) == 2

    stored = history_client.query(
        "SELECT kind, scope, term, ok FROM notifications ORDER BY sent_at"
    ).result_rows
    assert stored == [("alert", alerts[0].scope, "vision pro", True), ("digest", "tech", "", True)]

    detected_at, latest = latest_trends(history_client, "24h", "tech")
    assert detected_at == (now + timedelta(minutes=15)).replace(tzinfo=None)
    assert latest[0].scope == "tech"
    assert all(trend.subsumed_by == "" for trend in latest)


def test_without_notifications_alerts_are_muted(history_client):
    env = Env("", "", "", b"", "", 0, "", "", "")
    analyzer = Analyzer(config_for_tests(), env, history_client, None)
    result = analyzer.run_once(END - timedelta(minutes=1))
    assert result.alerts["muted"] == 1
    assert result.digests == []


def test_replay_simulates_the_alert_rules(history_client):
    out = io.StringIO()
    config = config_for_tests()
    result = replay(
        history_client,
        config,
        END - timedelta(hours=4),
        END,
        horizons=[config.detect.horizons[0]],
        out=out,
    )
    assert len(result.steps) == 5
    # the burst is 3 hours before the end: it alerts on the first step that sees it, and
    # the cooldown keeps it from alerting again
    assert [(trend.detected_at, trend.term) for trend in result.alerts] == [
        (END - timedelta(hours=2), "vision pro"),
    ]
    text = report(result, [])
    assert "5 steps" in text
    assert "vision pro" in text
    rows = out.getvalue().splitlines()
    assert rows[0].startswith("horizon,scope,term,detected_at")
    assert len(rows) > 1
    # replays never write
    (count,) = history_client.query("SELECT count() FROM trends").result_rows[0]
    assert count == 0
