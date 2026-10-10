import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from wgra.notify.messages import (
    TrendSummary,
    alert_message,
    digest_message,
    explorer_url,
    trending_url,
)
from wgra.notify.ntfy import Message, Ntfy, NtfyError

GRAFANA = "https://grafana.example"


def summary(**overrides: object) -> TrendSummary:
    values: dict[str, object] = {
        "term": "vision pro",
        "scope": "r/technology",
        "horizon": "24h",
        "z": 23.14,
        "ratio": 14.2,
        "mentions": 312,
        "authors": 280,
        "is_new": False,
    }
    values.update(overrides)
    return TrendSummary(**values)  # type: ignore[arg-type]


def recording_ntfy(status: int = 200) -> tuple[Ntfy, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"id": "abc"} if status == 200 else {"error": "no"})

    return Ntfy("http://ntfy", "wgra", "secret", transport=httpx.MockTransport(handle)), requests


def test_publishes_json_with_unicode_title_and_actions():
    ntfy, requests = recording_ntfy()
    ntfy.send(
        Message(
            title="für · r/de",
            body="**bold**",
            click="http://click",
            tags=("sparkles",),
            priority=4,
            links=(("Explore", "http://a"), ("Trending now", "http://b")),
        )
    )
    (request,) = requests
    assert request.method == "POST"
    assert request.url == "http://ntfy/"
    assert request.headers["authorization"] == "Bearer secret"
    assert json.loads(request.content) == {
        "topic": "wgra",
        "title": "für · r/de",
        "message": "**bold**",
        "priority": 4,
        "markdown": True,
        "tags": ["sparkles"],
        "click": "http://click",
        "actions": [
            {"action": "view", "label": "Explore", "url": "http://a", "clear": False},
            {"action": "view", "label": "Trending now", "url": "http://b", "clear": False},
        ],
    }


def test_errors_are_raised():
    ntfy, _ = recording_ntfy(status=403)
    with pytest.raises(NtfyError, match="403"):
        ntfy.send(Message(title="t", body="b"))

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    unreachable = Ntfy("http://ntfy", "wgra", transport=httpx.MockTransport(refuse))
    with pytest.raises(NtfyError, match="unreachable"):
        unreachable.send(Message(title="t", body="b"))


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_explorer_links_open_the_term_in_its_scope():
    subreddit = explorer_url(GRAFANA, "vision pro", "r/technology")
    assert subreddit.startswith(f"{GRAFANA}/d/wgra-terms?")
    assert query(subreddit) == {
        "var-terms": ["vision pro"],
        "var-group": ["tracked"],
        "var-subreddit": ["technology"],
        "from": ["now-7d"],
        "to": ["now"],
    }
    group = query(explorer_url(GRAFANA, "für", "de"))
    assert group["var-group"] == ["de"]
    assert group["var-terms"] == ["für"]
    assert "var-subreddit" not in group
    assert query(trending_url(GRAFANA, "tech", "6h")) == {
        "var-group": ["tech"],
        "var-horizon": ["6h"],
    }


def test_alert_message():
    message = alert_message(summary(), GRAFANA)
    assert message.title == "vision pro · r/technology"
    assert "14× its usual share: 312 comments and posts by 280 people" in message.body
    assert "Score 23.1" in message.body
    assert message.click == explorer_url(GRAFANA, "vision pro", "r/technology")
    assert message.priority == 4

    new = alert_message(
        summary(is_new=True, scope="tech", breadth=6, members=9, reference_days=12), GRAFANA
    )
    assert "New: 312 comments and posts" in new.body
    assert "in the 12 days before" in new.body
    assert "Trending in 6 of the 9 subreddits" in new.body
    assert new.tags == ("sparkles",)


def test_digest_lists_terms_with_links():
    message = digest_message(
        "tech",
        date(2026, 10, 12),
        [summary(), summary(term="gpt-6", scope="tech", is_new=True, breadth=4, ratio=2.5)],
        GRAFANA,
    )
    assert message.title == "Trending in tech, Mon 12 Oct"
    first, second = message.body.splitlines()
    assert first.startswith("1. [vision pro](https://grafana.example/d/wgra-terms?")
    assert first.endswith(" · 14× · 312 mentions · r/technology")
    assert second.endswith(" · new · 312 mentions · in 4 subreddits")
    assert message.click == trending_url(GRAFANA, "tech")
