"""`wgra suggest-subreddits` and the optional Wikipedia check.

The ClickHouse parts use a throwaway database (conftest.py). Wikimedia is never called:
its two APIs are answered by a mock transport.
"""

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from helpers import make_config

from wgra.config import SAMPLE_SCOPE, WikipediaConfig
from wgra.detect.short_term import TREND_COLUMNS
from wgra.ingest.pipeline import ITEM_COLUMNS
from wgra.leadlag.events import Event, Onset, write_events
from wgra.leadlag.suggest import suggest, yaml_snippet
from wgra.leadlag.wikipedia import (
    Lead,
    Wikimedia,
    WikipediaCheck,
    interest_onset,
    load_leads,
    summarize,
)
from wgra.store import migrate

NOW = datetime.now(UTC).replace(microsecond=0)


def trend_row(term: str, kind: str, detected_at: datetime, z: float, reference_days: int):
    values = {
        "horizon": "24h",
        "scope": "r/technology",
        "term": term,
        "detected_at": detected_at,
        "scope_type": "subreddit",
        "kind": kind,
        "window_start": detected_at - timedelta(hours=24),
        "window_end": detected_at,
        "mentions": 50,
        "total": 1000,
        "reference_mentions": 0,
        "reference_total": 10_000,
        "authors": 40,
        "prior": 1.0,
        "log_odds": 3.0,
        "ratio": 20.0,
        "z": z,
        "is_new": True,
        "breadth": 0,
        "members": 0,
        "subsumed_by": "",
        "rank": 1,
        "reference_days": reference_days,
        "alert": "",
    }
    return [values[column] for column in TREND_COLUMNS]


class Items:
    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []

    def add(self, subreddit: str, text: str, at: datetime, count: int = 1) -> None:
        for _ in range(count):
            number = len(self.rows)
            self.rows.append(
                (
                    f"t1_{number}",
                    "comment",
                    SAMPLE_SCOPE,
                    at,
                    number,
                    text,
                    f"/r/{subreddit}/comments/x{number}/title/c{number}/",
                    10,
                )
            )


def test_suggests_untracked_subreddits_that_are_early(client):
    migrate(client)
    client.insert(
        "trends",
        [
            trend_row("ollama", "word", NOW - timedelta(hours=6), 12, 10),
            trend_row("vision pro", "phrase", NOW - timedelta(hours=3), 9, 10),
            # a scope without history: what's distinctive, not what's rising
            trend_row("warmupword", "word", NOW - timedelta(hours=3), 15, 1),
        ],
        column_names=list(TREND_COLUMNS),
    )
    items = Items()
    # a small subreddit talking about both before they trended
    items.add("LocalLLaMA2", "Has anyone tried Ollama yet?", NOW - timedelta(hours=10), 5)
    items.add("LocalLLaMA2", "the Vision-Pro looks heavy", NOW - timedelta(hours=5), 3)
    items.add("LocalLLaMA2", "unrelated", NOW - timedelta(hours=5), 5)
    # a big one mentions everything a bit, later: no more than its size explains
    items.add("AskReddit", "what is ollama", NOW - timedelta(hours=2), 3)
    items.add("AskReddit", "something else", NOW - timedelta(hours=2), 100)
    # tracked subreddits are never suggested, warmup trends don't count
    items.add("technology", "ollama and vision pro", NOW - timedelta(hours=1), 5)
    items.add("Other", "warmupword warmupword", NOW - timedelta(hours=12), 5)
    # older than the 48 hours the items are kept
    items.add("Old", "ollama vision pro", NOW - timedelta(hours=60), 5)
    client.insert("items", items.rows, column_names=list(ITEM_COLUMNS))

    result = suggest(client, ["technology"], NOW)
    assert result.rising == 2
    assert result.sampled_items == len(items.rows) - 5
    [first] = result.candidates
    assert first.subreddit == "localllama2"
    assert (first.terms, first.first, first.early, first.mentions) == (2, 2, 2, 8)
    assert sorted(first.examples) == ["ollama", "vision pro"]
    assert first.items == 13
    assert "    - localllama2" in yaml_snippet(result.candidates)

    # with the warmup trends, the subreddit mentioning those shows up too
    loose = suggest(client, ["technology"], NOW, min_terms=1, min_reference_days=0)
    assert {c.subreddit for c in loose.candidates} == {"localllama2", "other"}


def test_suggests_nothing_without_rising_terms(client):
    migrate(client)
    result = suggest(client, [], NOW)
    assert (result.rising, result.candidates) == (0, [])


def views_for(days: dict[date, int]) -> dict:
    return {
        "items": [
            {"timestamp": f"{day:%Y%m%d}00", "views": views, "article": "Ollama"}
            for day, views in sorted(days.items())
        ]
    }


class FakeWikimedia:
    """Answers the action API and the pageviews API, records the requests."""

    def __init__(self, views: dict[date, int]):
        self.views = views
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = urlparse(str(request.url))
        if url.path == "/w/api.php":
            titles = parse_qs(url.query)["titles"][0].split("|")
            normalized = [{"from": t, "to": t[0].upper() + t[1:]} for t in titles if t != t.title()]
            pages = []
            for title in {t[0].upper() + t[1:] for t in titles}:
                if title.lower() == "ollama":
                    pages.append({"pageid": 1, "ns": 0, "title": title})
                elif title.lower() == "mercury":
                    pages.append(
                        {"pageid": 2, "ns": 0, "title": title, "pageprops": {"disambiguation": ""}}
                    )
                else:
                    pages.append({"ns": 0, "title": title, "missing": True})
            body = {"query": {"normalized": normalized, "pages": pages}}
            return httpx.Response(200, json=body)
        if "/pageviews/per-article/en.wikipedia/all-access/user/Ollama/daily/" in url.path:
            return httpx.Response(200, json=views_for(self.views))
        return httpx.Response(404, json={"detail": "not found"})


def wikimedia(fake: FakeWikimedia, settings: WikipediaConfig | None = None) -> Wikimedia:
    return Wikimedia(
        settings or WikipediaConfig(enabled=True),
        transport=httpx.MockTransport(fake.handle),
        clock=lambda: 0.0,
        sleep=lambda seconds: None,
    )


def test_articles_resolve_through_redirects_and_skip_disambiguation():
    fake = FakeWikimedia({})
    found = wikimedia(fake).articles(["ollama", "mercury", "nothinghere"])
    assert found == {"ollama": "Ollama", "mercury": "", "nothinghere": ""}
    [request] = fake.requests
    assert request.headers["user-agent"].startswith("wgra/2.0 (https://github.com/")
    assert "httpx/" in request.headers["user-agent"]


def test_requests_are_rate_limited():
    fake = FakeWikimedia({})
    clock = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    client = Wikimedia(
        WikipediaConfig(requests_per_second=2),
        transport=httpx.MockTransport(fake.handle),
        clock=lambda: clock[0],
        sleep=sleep,
    )
    for _ in range(3):
        client.pageviews("Missing", date(2026, 1, 1), date(2026, 1, 2))
    assert waits == [0.5, 0.5]


def test_interest_starts_well_above_the_median():
    settings = WikipediaConfig(min_views=100, min_ratio=3)
    first = date(2026, 9, 1)
    views = {first - timedelta(days=offset): 60 for offset in range(1, 40)}
    views |= {first + timedelta(days=2): 150, first + timedelta(days=3): 400}
    assert interest_onset(views, first, first + timedelta(days=10), settings) == first + timedelta(
        days=3
    )
    # far from enough views: no onset
    quiet = {day: 10 for day in views}
    quiet[first + timedelta(days=3)] = 90
    assert interest_onset(quiet, first, first + timedelta(days=10), settings) is None


def lead(days: int | None) -> Lead:
    onset = datetime(2026, 9, 1, 15, tzinfo=UTC)
    wiki = None if days is None else onset.date() + timedelta(days=days)
    return Lead("word", "x", onset, "X", onset, "r/x", wiki)


def test_summary_counts_who_was_first():
    summary = summarize([lead(2), lead(3), lead(0), lead(-1), lead(None), lead(1)])
    assert (summary.events, summary.with_onset) == (6, 5)
    assert (summary.reddit_first, summary.same_day, summary.wiki_first) == (3, 1, 1)
    assert summary.median_lead == 1
    # two-sided sign test, 3 of 4 decided ones: 2 · P(X ≥ 3 | 4, 0.5) = 0.625
    assert summary.p_value == pytest.approx(0.625)


def test_wikipedia_check_caches_and_compares(client):
    migrate(client)
    config = make_config(wikipedia={"enabled": True})
    start = (NOW - timedelta(days=30)).replace(minute=0, second=0)
    reddit_onset = start - timedelta(hours=2)
    events = [
        Event(
            "word",
            term,
            start,
            start,
            {"r/technology": 8.0},
            onsets=[Onset("r/technology", "", reddit_onset, 10, 4.0, 5.0)],
            onsets_until=NOW,
            closed=True,
        )
        for term in ("ollama", "nothinghere")
    ]
    write_events(client, events, config.groups)
    rising = reddit_onset.date() + timedelta(days=2)
    views = {reddit_onset.date() + timedelta(days=offset): 50 for offset in range(-40, 20)}
    views |= {rising + timedelta(days=offset): 600 for offset in range(4)}
    fake = FakeWikimedia(views)
    check = WikipediaCheck(client, config, wikimedia(fake))

    [found] = check.run(NOW, days=90, max_events=10)
    assert (found.term, found.article, found.wiki_onset) == ("ollama", "Ollama", rising)
    assert found.lead_days == 2
    assert found.reddit_scope == "r/technology"
    requests = len(fake.requests)
    assert requests == 2  # the titles, then one article's views

    # compared events aren't looked up again; articles and views are cached
    assert check.run(NOW, days=90, max_events=10) == []
    assert len(fake.requests) == requests
    # the span (3 days before to 14 after the first trend) and 28 days before for the median
    (cached,) = client.query("SELECT count() FROM wiki_pageviews").result_rows[0]
    assert 28 + 3 + 13 <= cached <= 28 + 3 + 14 + 1
    articles = dict(client.query("SELECT term, article FROM wiki_articles FINAL").result_rows)
    assert articles == {"ollama": "Ollama", "nothinghere": ""}

    [stored] = load_leads(client, "en.wikipedia", NOW - timedelta(days=90))
    assert stored.lead_days == 2
    assert summarize([stored]).reddit_first == 1
