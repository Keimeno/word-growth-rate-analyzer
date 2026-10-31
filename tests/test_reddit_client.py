import httpx
import pytest

from wgra.reddit import RedditClient, RedditError, parse_listing


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
        "python:wgra-test:1.0 (by /u/test)",
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
    assert request.headers["user-agent"] == "python:wgra-test:1.0 (by /u/test)"
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
    assert [(item.source, item.text) for item in items] == [
        ("post", "Title\n\nBody"),
        ("post", "Only"),
    ]
