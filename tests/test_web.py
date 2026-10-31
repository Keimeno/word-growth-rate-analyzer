import base64
import json
import math
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta

import pytest
from helpers import make_config, make_doc, make_trend

from wgra.config import Env
from wgra.detect.short_term import write_trends
from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor
from wgra.ingest.run import write_channels
from wgra.store import connect, migrate
from wgra.web.queries import ENDPOINTS, Params, _json, daily_series, hourly_series
from wgra.web.server import Dashboard


def params(**values: str) -> Params:
    return Params({key: [value] for key, value in values.items()})


def test_params_read_lists_numbers_and_ranges():
    p = params(channels="r/a, r/b,,", min_authors="-3", horizon="6h", range="2d")
    assert p.items("channels") == ["r/a", "r/b"]
    assert p.items("kinds", ["word"]) == ["word"]
    assert params(kinds="").items("kinds", ["word"]) == []
    assert p.number("min_authors", 1, 1) == 1
    assert p.choice("horizon", ["24h", "6h"], "24h") == "6h"
    start, end = p.window("7d")
    assert end - start == 2 * 86400


@pytest.mark.parametrize(
    "bad",
    [
        lambda: params(horizon="1h").choice("horizon", ["24h", "6h"], "24h"),
        lambda: params(range="2 days").window("7d"),
        lambda: params(min_authors="many").number("min_authors", 1),
    ],
)
def test_params_reject_what_they_cant_read(bad):
    with pytest.raises(ValueError):
        bad()


def test_json_values():
    assert _json(datetime(2026, 10, 31, 12, 0, 5)) == "2026-10-31T12:00:05Z"
    assert _json(datetime(2026, 10, 31, 13, tzinfo=UTC)) == "2026-10-31T13:00:00Z"
    assert _json(date(2026, 10, 31)) == "2026-10-31"
    assert _json([math.nan, math.inf, 1.5, ("a", 2)]) == [None, None, 1.5, ["a", 2]]


def test_series_fill_the_hours_and_days_without_mentions():
    end = datetime(2026, 10, 31, 15, 45)
    points = [
        {"time": "2026-10-31T15:00:00Z", "term": "ai", "mentions": 3},
        {"time": "2026-10-31T13:00:00Z", "term": "ai", "mentions": 1},
        {"time": "2026-10-20T13:00:00Z", "term": "ai", "mentions": 9},
    ]
    assert hourly_series(points, end, 4) == {"ai": [0, 1, 0, 3]}
    days = [{"day": "2026-10-30", "term": "x", "mentions": 2}]
    assert daily_series(days, date(2026, 10, 29), 3) == {"x": [0, 2, 0]}


@pytest.fixture(scope="module")
def stored(module_client):
    """A database with an hour of comments in tech, a trend and a poll."""
    client = module_client
    migrate(client)
    config = make_config()
    write_channels(client, config)
    processor = Processor(config, b"key")
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    created = int(hour.timestamp()) + 60
    items = [
        make_doc(config, 1, created, author="alice", text="rust is great, rust rust"),
        make_doc(config, 2, created + 60, author="bob", text="I like rust"),
        make_doc(config, 3, created + 120, author="carol", text="python only"),
        make_doc(config, 4, created, subreddit="programming", author="dave", text="rust here"),
        make_doc(config, 5, created, author="erin", text="I switched from Notion to Obsidian"),
    ]
    processed = [processor.process(item) for item in items]
    client.insert("items", [p.item_row for p in processed], column_names=list(ITEM_COLUMNS))
    client.insert(
        "term_events",
        [row for p in processed for row in p.term_rows],
        column_names=list(TERM_COLUMNS),
    )
    write_trends(
        client,
        [make_trend("rust", kind="word", scope="tech", scope_type="group", detected_at=hour)],
    )
    client.insert(
        "polls",
        [[hour, "reddit", "comments-1", "comments", False, 200, 100, 40, False, 0, 80, 60, 1, 99]],
        column_names=[
            "ts", "platform", "feed", "kind", "sample", "status", "items", "new_items", "gap",
            "id_span", "latency_ms", "interval_s", "rate", "ratelimit_remaining",
        ],
    )  # fmt: skip
    return client


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_every_endpoint_runs_on_the_schema(stored, name):
    data = ENDPOINTS[name](stored, params(scope="tech", terms="rust", kind="complaint"))
    json.dumps(data)


def test_meta_lists_groups_then_channels(stored):
    meta = ENDPOINTS["meta"](stored, params())
    names = [scope["name"] for scope in meta["scopes"]]
    assert names[0] == "reddit"
    assert names.index("tech") < names.index("r/technology")
    assert meta["groups"]["tech"] == ["r/programming", "r/technology"]


def test_trending_shows_the_latest_run_with_sparklines(stored):
    data = ENDPOINTS["trending"](stored, params(scope="tech"))
    assert [trend["term"] for trend in data["trends"]] == ["rust"]
    assert data["trending"] == 1
    # the hour before the run: 3 comments mentioned rust in tech
    assert data["sparklines"]["rust"][-1] == 3
    assert ENDPOINTS["trending"](stored, params(scope="tech", kinds="phrase"))["trends"] == []


def test_explore_counts_mentions_and_shares(stored):
    data = ENDPOINTS["explore"](stored, params(scope="tech", terms="Rust", range="2d"))
    assert data["terms"] == ["rust"]
    assert data["bucket"] == "hour"
    [point] = data["points"]
    assert (point["mentions"], point["authors"]) == (3, 3)
    # 3 of 5 comments in tech, and the average of 2/4 and 1/1 over its channels
    assert point["pooled"] == pytest.approx(600)
    assert point["macro"] == pytest.approx(750)
    assert {row["channel"]: row["mentions"] for row in data["where"]} == {
        "r/technology": 2,
        "r/programming": 1,
    }
    channel = ENDPOINTS["explore"](
        stored, params(scope="tech", terms="rust", channels="r/programming")
    )
    assert channel["points"][0]["mentions"] == 1
    mentions = ENDPOINTS["explore-mentions"](stored, params(scope="tech", terms="rust"))
    assert len(mentions) == 3


def test_intents_show_the_switch_and_its_comment(stored):
    flows = ENDPOINTS["intents-switches"](stored, params(scope="tech"))["flows"]
    assert [(flow["from"], flow["to"], flow["mentions"]) for flow in flows] == [
        ("notion", "obsidian", 1)
    ]
    examples = ENDPOINTS["intents-examples"](stored, params(scope="tech", term="notion → obsidian"))
    assert [row["found"] for row in examples] == [["notion → obsidian"]]
    assert ENDPOINTS["intents-examples"](stored, params(scope="tech", intent_kinds="need")) == []


def test_explore_needs_a_term(stored):
    with pytest.raises(ValueError):
        ENDPOINTS["explore"](stored, params(scope="tech", terms=" , "))


@pytest.fixture
def server(stored):
    # as `wgra web` connects: without a session, which would take one query at a time
    client = connect(Env.from_environ(), stored.database, autogenerate_session_id=False)
    dashboard = Dashboard(("127.0.0.1", 0), client, "http://grafana", password="")
    thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
    thread.start()
    yield dashboard
    dashboard.shutdown()
    dashboard.server_close()


def get(dashboard: Dashboard, path: str, password: str | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(f"http://127.0.0.1:{dashboard.server_address[1]}{path}")
    if password is not None:
        token = base64.b64encode(f"me:{password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_server_serves_the_page_and_the_data(server):
    status, body = get(server, "/")
    assert status == 200 and b"<title>Undercurrent</title>" in body
    status, body = get(server, "/static/app.js")
    assert status == 200
    status, body = get(server, "/api/config")
    assert json.loads(body) == {"grafana_url": "http://grafana"}
    status, body = get(server, "/api/trending?scope=tech")
    assert status == 200 and json.loads(body)["trends"][0]["term"] == "rust"


def test_server_refuses_bad_requests(server):
    assert get(server, "/api/nothing")[0] == 404
    assert get(server, "/static/../server.py")[0] == 404
    assert get(server, "/static/%2e%2e/server.py")[0] == 404
    status, body = get(server, "/api/trending?horizon=1h")
    assert status == 400 and "horizon" in json.loads(body)["error"]


def test_server_asks_for_the_password(server):
    server.password = "secret"
    assert get(server, "/api/config")[0] == 401
    assert get(server, "/api/config", password="wrong")[0] == 401
    assert get(server, "/api/config", password="secret")[0] == 200


def test_server_answers_while_another_request_runs(server):
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(get(server, "/api/meta")[0]))
        for _ in range(4)
    ]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [200] * 4
    assert time.monotonic() - started < 10
