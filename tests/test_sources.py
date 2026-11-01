"""Sources and the shared pipeline: a source's items and polls through the sink into
ClickHouse, and what the Reddit source decides (channels, skips, what's new).

The ClickHouse part uses a throwaway database (conftest.py). Reddit is never called: a mock
transport answers the token and listing requests.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from helpers import make_config, make_item

from undercurrent.ingest.run import Pipeline, run_sources, write_channels
from undercurrent.sources.base import Item, Poll, Sink
from undercurrent.sources.reddit.client import RedditClient
from undercurrent.sources.reddit.feeds import (
    MAX_SAMPLE_POLLS_IN_FLIGHT,
    FeedScheduler,
    build_feeds,
)
from undercurrent.sources.reddit.models import RedditItem
from undercurrent.sources.reddit.source import RedditSource, to_item
from undercurrent.store import migrate

# recent, since items keeps 48 hours: older rows are gone as soon as they're inserted
HOUR = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
MINUTES = timedelta(minutes=5)


class ListSource:
    """A source of a platform that doesn't exist: hands over what it was given, once."""

    platform = "fake"

    def __init__(self, items: list[Item], polls: list[Poll]):
        self.items = items
        self.polls = polls

    async def run(self, sink: Sink, stop: asyncio.Event) -> None:
        for item in self.items:
            sink.add(item)
        for poll in self.polls:
            sink.add_poll(poll)


def fake_item(id: str, channel: str, doc_type: str, author: str, text: str, **values: Any) -> Item:
    return Item(
        id=id,
        platform="fake",
        channel=channel,
        doc_type=doc_type,
        author=author,
        created_at=values.pop("created_at", HOUR),
        text=text,
        url=f"https://fake.example/{id}",
        lang="en",
        **values,
    )


async def test_any_source_goes_through_the_sink_into_clickhouse(client):
    migrate(client)
    config = make_config()
    write_channels(client, config)
    items = [
        fake_item("1", "r/technology", "comment", "alice", "rust is great"),
        fake_item("2", "r/technology", "post", "bob", "I like rust", created_at=HOUR + MINUTES),
        fake_item("3", "r/technology", "comment", "Alice", "rust again"),
        fake_item("4", "r/technology", "comment", "spammer", "rust rust rust", skip="bot"),
    ]
    poll = Poll(
        ts=HOUR,
        platform="fake",
        feed="everything",
        kind="comments",
        sample=False,
        status=200,
        items=4,
        new_items=4,
        gap=False,
        id_span=4,
        latency_ms=120,
        interval_s=30.0,
        rate=0.1,
        ratelimit_remaining=-1,
    )
    pipeline = Pipeline(config, b"key", client)
    await run_sources([ListSource(items, [poll])], pipeline, asyncio.Event())

    assert pipeline.skipped == {"bot": 1}
    assert client.query("SELECT id, platform, url FROM items ORDER BY id").result_rows == [
        ("1", "fake", "https://fake.example/1"),
        ("2", "fake", "https://fake.example/2"),
        ("3", "fake", "https://fake.example/3"),
    ]
    rows = client.query(
        "SELECT channel, doc_type, sum(docs), uniqCombinedMerge(12)(authors) FROM term_hourly "
        "WHERE term = 'rust' GROUP BY channel, doc_type ORDER BY doc_type"
    ).result_rows
    # alice and Alice are one person
    assert rows == [("r/technology", "comment", 2, 1), ("r/technology", "post", 1, 1)]
    assert client.query("SELECT platform, feed, new_items, sample FROM polls").result_rows == [
        ("fake", "everything", 4, False)
    ]


def test_reddit_items_go_to_their_subreddits_channel_r_all_or_the_search():
    config = make_config()
    tracked = to_item(make_item(1, subreddit="technology"), config)
    assert (tracked.platform, tracked.channel, tracked.doc_type) == (
        "reddit",
        "r/technology",
        "comment",
    )
    assert tracked.url == "https://www.reddit.com/r/technology/comments/x/1"
    assert tracked.created_at == datetime.fromtimestamp(1_700_000_000, UTC)
    # every subreddit we don't track is counted in r/all, the url still names it
    elsewhere = to_item(make_item(2, subreddit="askreddit"), config)
    assert elsewhere.channel == "r/all"
    assert elsewhere.url.startswith("https://www.reddit.com/r/askreddit/")
    assert to_item(make_item(3, subreddit="askreddit"), config, "r/_search").channel == "r/_search"
    # the language of the item's own subreddit, wherever it's counted
    assert to_item(make_item(4, subreddit="de"), config, "r/_search").lang == "de"
    assert to_item(make_item(5, author="[deleted]"), config).author == ""


@pytest.mark.parametrize(
    ("values", "skip"),
    [
        ({"text": "[removed]"}, "deleted"),
        ({"author": "AutoModerator"}, "bot"),
        ({"author": "RemindMeBot"}, "bot"),
        ({"distinguished": "moderator"}, "moderation"),
        ({"stickied": True}, "moderation"),
        ({"text": "an ordinary comment"}, None),
    ],
)
def test_the_reddit_source_says_what_to_skip(values, skip):
    assert to_item(make_item(1, **values), make_config()).skip == skip


class RecordingSink:
    client: Any = None

    def __init__(self) -> None:
        self.items: list[Item] = []
        self.polls: list[Poll] = []

    def add(self, item: Item) -> bool:
        self.items.append(item)
        return item.skip is None

    def add_poll(self, poll: Poll) -> None:
        self.polls.append(poll)


def listing(*items: tuple[str, str, int]) -> dict:
    return {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "name": name,
                        "subreddit": subreddit,
                        "author": "someone",
                        "created_utc": created,
                        "body": "hello",
                        "permalink": f"/r/{subreddit}/comments/x/{name}",
                    },
                }
                for name, subreddit, created in items
            ]
        },
    }


def reddit(*responses: httpx.Response) -> RedditClient:
    answers = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 86400})
        return answers.pop(0)

    return RedditClient("id", "secret", "test", 6000, transport=httpx.MockTransport(handle))


def test_the_reddit_source_hands_on_each_new_item_once():
    source = RedditSource(make_config(), reddit())
    sink = RecordingSink()
    now = int(time.time())
    assert source.ingest(make_item(1, now), sink)
    # seen before, or too old to tell (it may have been counted and deleted since)
    assert not source.ingest(make_item(1, now), sink)
    assert not source.ingest(make_item(2, now - 40 * 3600), sink)
    # new, but the pipeline skips it
    assert source.ingest(make_item(3, now, author="AutoModerator"), sink)
    assert source.ingest(make_item(4, now, subreddit="askreddit"), sink, "r/_search")
    assert [(item.id, item.channel, item.skip) for item in sink.items] == [
        ("t1_1", "r/technology", None),
        ("t1_3", "r/technology", "bot"),
        ("t1_4", "r/_search", None),
    ]


async def test_the_reddit_sample_counts_untracked_subreddits_in_r_all():
    config = make_config()
    now = int(time.time())
    page = listing(("t1_b", "AskReddit", now), ("t1_a", "technology", now - 1))
    source = RedditSource(config, reddit(httpx.Response(200, json=page)))
    feeds = build_feeds(config)
    source.scheduler = FeedScheduler(feeds, config)
    sink = RecordingSink()
    sample = next(feed for feed in feeds if feed.sample)
    await source.poll(sample, sink)
    # a tracked subreddit's comment found in r/all still counts in its own channel
    assert [(item.id, item.channel) for item in sink.items] == [
        ("t1_b", "r/all"),
        ("t1_a", "r/technology"),
    ]
    [poll] = sink.polls
    assert (poll.platform, poll.feed, poll.sample, poll.new_items) == (
        "reddit",
        "sample-all",
        True,
        2,
    )
    assert poll.ts > datetime.now(UTC) - timedelta(minutes=1)


async def test_the_samples_polls_answered_out_of_order_lose_nothing():
    config = make_config()
    now = int(time.time())
    newer = listing(("t1_d", "AskReddit", now), ("t1_c", "AskReddit", now))
    older = listing(("t1_c", "AskReddit", now), ("t1_b", "AskReddit", now - 1))
    source = RedditSource(
        config, reddit(httpx.Response(200, json=newer), httpx.Response(200, json=older))
    )
    feeds = build_feeds(config)
    source.scheduler = FeedScheduler(feeds, config)
    sink = RecordingSink()
    sample = next(feed for feed in feeds if feed.sample)
    # the later poll's answer came first, the earlier one still has t1_b
    await source.poll(sample, sink)
    await source.poll(sample, sink)
    assert [item.id for item in sink.items] == ["t1_d", "t1_c", "t1_b"]
    assert [poll.new_items for poll in sink.polls] == [2, 1]


async def test_the_reddit_source_overlaps_the_samples_polls():
    config = make_config(
        platforms={"reddit": {"requests_per_minute": 6000, "sample": {"requests_per_minute": 600}}}
    )
    paths: list[str] = []
    in_flight = most = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, most
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 86400})
        paths.append(request.url.path)
        in_flight += 1
        most = max(most, in_flight)
        # r/all takes seconds to answer, here a third of one
        await asyncio.sleep(0.3 if request.url.path == "/r/all/comments" else 0)
        in_flight -= 1
        return httpx.Response(200, json=listing())

    client = RedditClient("id", "secret", "test", 6000, transport=httpx.MockTransport(handle))
    source = RedditSource(config, client)
    source.scheduler = FeedScheduler(build_feeds(config), config)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.6, stop.set)
    async with client:
        await source._poll_forever(RecordingSink(), stop)

    # a poll of r/all every 0.1s, each answered after 0.3s
    assert 3 <= most <= MAX_SAMPLE_POLLS_IN_FLIGHT
    assert paths.count("/r/all/comments") >= 4
    # the tracked feeds and r/all's posts once, their next polls are minutes away
    tracked = [path for path in paths if path != "/r/all/comments"]
    assert sorted(tracked) == [
        "/r/all/new",
        "/r/de+programming+technology/comments",
        "/r/de+programming+technology/new",
    ]


async def test_a_complete_feeds_polls_answered_out_of_order_lose_nothing():
    config = make_config()
    now = int(time.time())
    pages = [
        listing(("t1_c", "technology", now - 1), ("t1_b", "technology", now - 2)),
        listing(("t1_d", "technology", now), ("t1_c", "technology", now - 1)),
    ]
    first_sent, first_answered = asyncio.Event(), asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 86400})
        page = pages.pop(0)
        if not first_sent.is_set():
            first_sent.set()
            await first_answered.wait()
        return httpx.Response(200, json=page)

    client = RedditClient("id", "secret", "test", 6000, transport=httpx.MockTransport(handle))
    source = RedditSource(config, client)
    feeds = build_feeds(config)
    source.scheduler = FeedScheduler(feeds, config)
    comments = feeds[0]
    comments.newest_id = int("a", 36)
    sink = RecordingSink()
    async with client:
        slow = asyncio.create_task(source.poll(comments, sink))
        await first_sent.wait()
        # the later poll is answered first, the earlier one still has t1_b
        await source.poll(comments, sink)
        first_answered.set()
        await slow
    assert [item.id for item in sink.items] == ["t1_d", "t1_c", "t1_b"]


def test_untracked_posts_naming_a_watched_product_count_in_the_search():
    config = make_config(
        radar={
            "enabled": True,
            "watchlists": {"pkm": {"group": "tech", "products": {"notion": ["Notion AI"]}}},
        }
    )
    source = RedditSource(config, reddit())
    all_posts = next(feed for feed in build_feeds(config) if feed.path == "/r/all/new")

    def post(subreddit: str, text: str) -> RedditItem:
        return make_item(1, doc_type="post", subreddit=subreddit, text=text)

    assert source.channel_of(post("productivity", "Leaving Notion AI for good"), all_posts) == (
        "r/_search"
    )
    # anything else from elsewhere counts in r/all, a tracked subreddit's in its own channel
    assert source.channel_of(post("productivity", "My notebook setup"), all_posts) is None
    assert source.channel_of(post("technology", "Notion raises prices"), all_posts) is None
    # the search is for posts, comments naming it stay in the sample
    comment = make_item(2, subreddit="askreddit", text="I use notion")
    assert source.channel_of(comment, all_posts) is None
