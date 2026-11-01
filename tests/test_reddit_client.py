import asyncio

import httpx
import pytest

from undercurrent.sources.reddit.client import RedditClient, RedditError
from undercurrent.sources.reddit.models import parse_listing


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def comment_listing(*names: str) -> dict:
    return {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "name": name,
                        "subreddit": "Technology",
                        "author": "someone",
                        "created_utc": 1_700_000_000.0,
                        "body": "hello",
                        "permalink": f"/r/technology/comments/x/{name}",
                    },
                }
                for name in names
            ]
        },
    }


class FakeReddit:
    """Answers token and api requests, records what it was asked."""

    def __init__(self, api_responses: list[httpx.Response]):
        self.api_responses = api_responses
        self.token_requests = 0
        self.api_requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/access_token":
            self.token_requests += 1
            return httpx.Response(
                200, json={"access_token": f"token-{self.token_requests}", "expires_in": 86400}
            )
        self.api_requests.append(request)
        return self.api_responses.pop(0)


def make_client(fake: FakeReddit, time: FakeTime, requests_per_minute: float = 60) -> RedditClient:
    return RedditClient(
        "id",
        "secret",
        "python:undercurrent-test:1.0 (by /u/test)",
        requests_per_minute,
        transport=httpx.MockTransport(fake.handler),
        clock=time.clock,
        sleep=time.sleep,
    )


def ok(payload: dict, remaining: float = 900, reset: float = 300) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        headers={
            "x-ratelimit-remaining": str(remaining),
            "x-ratelimit-used": "1",
            "x-ratelimit-reset": str(reset),
        },
    )


async def test_listing_authenticates_and_sends_user_agent():
    fake = FakeReddit([ok(comment_listing("t1_b", "t1_a"))])
    async with make_client(fake, FakeTime()) as client:
        items = await client.listing("/r/technology/comments")

    assert [item.fullname for item in items] == ["t1_b", "t1_a"]
    assert items[0].subreddit == "technology"
    request = fake.api_requests[0]
    assert request.headers["authorization"] == "bearer token-1"
    assert request.headers["user-agent"] == "python:undercurrent-test:1.0 (by /u/test)"
    assert request.url.params["limit"] == "100"
    assert request.url.params["raw_json"] == "1"


async def test_token_is_reused_and_refreshed_on_401():
    fake = FakeReddit(
        [
            ok(comment_listing("t1_a")),
            ok(comment_listing("t1_b")),
            httpx.Response(401, json={"message": "Unauthorized"}),
            ok(comment_listing("t1_c")),
        ]
    )
    async with make_client(fake, FakeTime()) as client:
        await client.listing("/r/x/comments")
        await client.listing("/r/x/comments")
        assert fake.token_requests == 1
        items = await client.listing("/r/x/comments")

    assert [item.fullname for item in items] == ["t1_c"]
    assert fake.token_requests == 2
    assert fake.api_requests[-1].headers["authorization"] == "bearer token-2"


async def test_requests_are_spaced_by_the_budget():
    fake = FakeReddit([ok(comment_listing("t1_a")) for _ in range(3)])
    time = FakeTime()
    async with make_client(fake, time, requests_per_minute=30) as client:
        for _ in range(3):
            await client.listing("/r/x/comments")

    assert time.slept == [pytest.approx(2.0), pytest.approx(2.0)]


class SlowReddit:
    """Answers api requests only once `count` of them have been sent, with `status`."""

    def __init__(self, time: FakeTime, count: int, status: int = 200):
        self.time = time
        self.count = count
        self.status = status
        self.sent: list[tuple[float, str]] = []
        self.token_requests = 0
        self._all_sent = asyncio.Event()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/access_token":
            self.token_requests += 1
            return httpx.Response(
                200, json={"access_token": f"token-{self.token_requests}", "expires_in": 86400}
            )
        self.sent.append((self.time.now, request.headers["authorization"]))
        if len(self.sent) <= self.count:
            if len(self.sent) == self.count:
                self._all_sent.set()
            await asyncio.wait_for(self._all_sent.wait(), 1)
            if self.status != 200:
                return httpx.Response(self.status, json={})
        return ok(comment_listing("t1_a"))

    def client(self, requests_per_minute: float) -> RedditClient:
        return RedditClient(
            "id",
            "secret",
            "ua",
            requests_per_minute,
            transport=httpx.MockTransport(self.handler),
            clock=self.time.clock,
            sleep=self.time.sleep,
        )


async def test_requests_overlap_one_spacing_apart():
    time = FakeTime()
    fake = SlowReddit(time, count=3)
    async with fake.client(requests_per_minute=30) as client:
        await asyncio.gather(*(client.listing("/r/all/comments") for _ in range(3)))

    # each sent while the ones before wait for their answer (r/all takes seconds)
    assert [at for at, _ in fake.sent] == [1000.0, 1002.0, 1004.0]


async def test_overlapping_requests_with_an_expired_token_get_a_new_one_once():
    time = FakeTime()
    fake = SlowReddit(time, count=2, status=401)
    async with fake.client(requests_per_minute=600) as client:
        await asyncio.gather(*(client.listing("/r/x/comments") for _ in range(2)))

    assert fake.token_requests == 2
    assert [token for _, token in fake.sent] == ["bearer token-1"] * 2 + ["bearer token-2"] * 2


async def test_requests_slow_down_when_reddit_reports_few_remaining():
    fake = FakeReddit([ok(comment_listing("t1_a"), remaining=10, reset=100) for _ in range(2)])
    time = FakeTime()
    async with make_client(fake, time, requests_per_minute=600) as client:
        await client.listing("/r/x/comments")
        await client.listing("/r/x/comments")

    # 10 requests left for 100 seconds: one every 10s instead of every 0.1s
    assert time.slept == [pytest.approx(10.0)]


async def test_rate_limited_responses_raise_with_retry_after():
    fake = FakeReddit([httpx.Response(429, headers={"x-ratelimit-reset": "42"})])
    async with make_client(fake, FakeTime()) as client:
        with pytest.raises(RedditError) as error:
            await client.listing("/r/x/comments")
    assert error.value.status == 429
    assert error.value.retry_after == pytest.approx(42)


async def test_failed_authentication_is_not_retried_immediately():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"message": "Unauthorized", "error": 401})

    time = FakeTime()
    client = RedditClient(
        "id",
        "wrong",
        "ua",
        60,
        transport=httpx.MockTransport(handler),
        clock=time.clock,
        sleep=time.sleep,
    )
    async with client:
        for _ in range(3):
            with pytest.raises(RedditError, match="authentication failed"):
                await client.listing("/r/x/comments")
    assert attempts == 1


@pytest.mark.parametrize(
    ("status", "problem"), [(403, "private"), (404, "banned or missing"), (302, "does not exist")]
)
async def test_subreddit_problems(status: int, problem: str):
    fake = FakeReddit([httpx.Response(status, json={})])
    async with make_client(fake, FakeTime()) as client:
        assert await client.subreddit_problem("whatever") == problem


async def test_public_subreddit_has_no_problem():
    fake = FakeReddit([ok({"kind": "t5", "data": {"subreddit_type": "public"}})])
    async with make_client(fake, FakeTime()) as client:
        assert await client.subreddit_problem("technology") is None


def test_posts_combine_title_and_selftext_and_drop_removed_selftext():
    payload = {
        "data": {
            "children": [
                {"kind": "t3", "data": {"name": "t3_a", "title": "Title", "selftext": "Body"}},
                {"kind": "t3", "data": {"name": "t3_b", "title": "Only", "selftext": "[removed]"}},
                {"kind": "more", "data": {}},
            ]
        }
    }
    items = parse_listing(payload)
    assert [(item.doc_type, item.text) for item in items] == [
        ("post", "Title\n\nBody"),
        ("post", "Only"),
    ]


async def test_search_listings_pass_their_parameters():
    fake = FakeReddit([ok({"kind": "Listing", "data": {"children": []}})])
    async with make_client(fake, FakeTime()) as client:
        await client.listing("/search", {"q": '"notion"', "sort": "new"})
    params = fake.api_requests[0].url.params
    assert fake.api_requests[0].url.path == "/search"
    assert (params["q"], params["sort"], params["limit"]) == ('"notion"', "new", "100")


def comment(name: str, *replies: dict) -> dict:
    return {
        "kind": "t1",
        "data": {
            "name": name,
            "subreddit": "productivity",
            "author": "someone",
            "created_utc": 1_700_000_000.0,
            "body": "hello",
            "permalink": f"/r/productivity/comments/x/{name}",
            "replies": {"kind": "Listing", "data": {"children": list(replies)}} if replies else "",
        },
    }


async def test_comment_trees_include_replies_but_not_load_more():
    post = {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {"name": "t3_p"}}]}}
    more = {"kind": "more", "data": {"children": ["t1_x", "t1_y"]}}
    tree = {
        "kind": "Listing",
        "data": {"children": [comment("t1_a", comment("t1_b", more)), comment("t1_c")]},
    }
    fake = FakeReddit([httpx.Response(200, json=[post, tree])])
    async with make_client(fake, FakeTime()) as client:
        comments = await client.comment_tree("p")
    assert sorted(item.fullname for item in comments) == ["t1_a", "t1_b", "t1_c"]
    assert fake.api_requests[0].url.path == "/comments/p"
    assert fake.api_requests[0].url.params["limit"] == "500"
