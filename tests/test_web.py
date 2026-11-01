import base64
import json
import os
import re
import secrets
import threading
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError
from fastapi.testclient import TestClient
from helpers import make_config, make_doc, make_trend
from pydantic import BaseModel

from wgra.config import Env
from wgra.detect.scoring import Counts, Prior
from wgra.detect.short_term import write_trends
from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor
from wgra.ingest.run import write_channels
from wgra.store import connect, migrate
from wgra.web.app import Settings, create_app
from wgra.web.models import Time
from wgra.web.queries import WindowQuery, daily_series, hourly_series
from wgra.web.queries.explore import ExploreQuery
from wgra.web.queries.trends import TrendQuery
from wgra.web.server import openapi, web_client
from wgra.web.stream import State, changes, read_alerts, read_state

HOUR = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


def test_queries_read_lists_and_ranges():
    query = TrendQuery.model_validate({"scopes": ["r/a, r/b,,"], "horizon": "6h"})
    assert query.scopes == ["r/a", "r/b"]
    assert query.kinds == ["word", "phrase", "domain", "subreddit"]
    assert TrendQuery.model_validate({"kinds": [""]}).kinds == []
    assert TrendQuery.model_validate({"kinds": ["word", "phrase,domain"]}).kinds == [
        "word",
        "phrase",
        "domain",
    ]
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    window = WindowQuery.model_validate({"range": "2d"}).window(now, "7d")
    assert window["to"] - window["from"] == 2 * 86400
    assert window["to"] == int(now.timestamp())
    assert WindowQuery().window(now, "6h")["from"] == int(now.timestamp()) - 6 * 3600


@pytest.mark.parametrize(
    "bad",
    [
        lambda: TrendQuery.model_validate({"horizon": "1h"}),
        lambda: WindowQuery.model_validate({"range": "2 days"}),
        lambda: ExploreQuery.model_validate({"terms": [" , "]}),
    ],
)
def test_queries_reject_what_they_cant_read(bad):
    with pytest.raises(ValueError):
        bad()


def test_times_are_utc_with_a_z_and_nan_is_null():
    class Row(BaseModel):
        time: Time
        value: float | None

    row = Row(time=datetime(2026, 10, 31, 12, 0, 5), value=float("nan"))
    assert row.model_dump_json() == '{"time":"2026-10-31T12:00:05Z","value":null}'


def test_series_fill_the_hours_and_days_without_mentions():
    end = datetime(2026, 10, 31, 15, 45)
    points = [
        {"time": datetime(2026, 10, 31, 15), "term": "ai", "mentions": 3},
        {"time": datetime(2026, 10, 31, 13), "term": "ai", "mentions": 1},
        {"time": datetime(2026, 10, 20, 13), "term": "ai", "mentions": 9},
    ]
    assert hourly_series(points, end, 4) == {"ai": [0, 1, 0, 3]}
    days = [{"day": date(2026, 10, 30), "term": "x", "mentions": 2}]
    assert daily_series(days, date(2026, 10, 29), 3) == {"x": [0, 2, 0]}


@pytest.fixture(scope="module")
def stored(module_client):
    """A database with an hour of comments in tech, a trend and a poll."""
    client = module_client
    migrate(client)
    config = make_config()
    write_channels(client, config)
    processor = Processor(config, b"key")
    created = int(HOUR.timestamp()) + 60
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
        [make_trend("rust", kind="word", scope="tech", scope_type="group", detected_at=HOUR)],
    )
    client.insert(
        "polls",
        [[HOUR, "reddit", "comments-1", "comments", False, 200, 100, 40, False, 0, 80, 60, 1, 99]],
        column_names=[
            "ts", "platform", "feed", "kind", "sample", "status", "items", "new_items", "gap",
            "id_span", "latency_ms", "interval_s", "rate", "ratelimit_remaining",
        ],
    )  # fmt: skip
    return client


@pytest.fixture(scope="module")
def web(stored):
    env = Env.from_environ()
    app = create_app(
        web_client(env, stored.database),
        Settings("http://grafana"),
        writer=connect(env, stored.database, autogenerate_session_id=False),
    )
    with TestClient(app) as test_client:
        yield test_client


def get(web: TestClient, path: str) -> Any:
    response = web.get(path)
    assert response.status_code == 200, response.text
    return response.json()


# the JSON endpoints; the stream has a test of its own
V1 = sorted(
    path for path in openapi()["paths"] if path.startswith("/api/v1/") and path != "/api/v1/stream"
)


# what the paths' parameters are filled with; an event that doesn't exist is a 404
PATH_PARAMETERS = {
    "{kind}": "word",
    "{term}": "rust",
    "{scope}": "tech",
    "{name}": "notion",
    "{start}": "2026-10-31T12:00:00Z",
}


@pytest.mark.parametrize("path", V1)
def test_every_endpoint_runs_on_the_schema(web, path):
    for placeholder, value in PATH_PARAMETERS.items():
        path = path.replace(placeholder, value)
    response = web.get(f"{path}?scope=tech&terms=rust&kind=complaint&q=ru&leader=r/a&follower=tech")
    assert response.status_code == (404 if path.startswith("/api/v1/events/") else 200), (
        response.text
    )


def test_every_endpoint_has_a_model_in_the_schema():
    schema = openapi()
    for path in V1:
        response = schema["paths"][path]["get"]["responses"]["200"]
        assert response["content"]["application/json"]["schema"], path
    assert schema["paths"]["/api/v1/trends"]["get"]["operationId"] == "trends"


def test_meta_lists_groups_then_channels(web):
    meta = get(web, "/api/v1/meta")
    names = [scope["name"] for scope in meta["scopes"]]
    assert names[0] == "reddit"
    assert names.index("tech") < names.index("r/technology")
    assert meta["groups"]["tech"] == ["r/programming", "r/technology"]
    assert meta["grafana_url"] == "http://grafana"


def test_trends_show_the_latest_run_with_sparklines(web):
    data = get(web, "/api/v1/trends?scope=tech")
    assert [trend["term"] for trend in data["trends"]] == ["rust"]
    assert data["trending"] == 1
    assert data["last_run"] == HOUR.isoformat().replace("+00:00", "Z")
    # the hour before the run: 3 comments mentioned rust in tech
    assert data["sparklines"]["rust"][-1] == 3
    assert get(web, "/api/v1/trends?scope=tech&kinds=phrase")["trends"] == []


def test_as_of_shows_the_past(web):
    before = (HOUR - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ")
    data = get(web, f"/api/v1/trends?scope=tech&as_of={before}")
    assert (data["last_run"], data["trends"]) == (None, [])
    assert get(web, f"/api/v1/explore/mentions?scope=tech&terms=rust&as_of={before}") == []


def test_missing_is_null_not_1970(web):
    edges = get(web, "/api/v1/edges")
    assert edges["edges_learned"] is None and edges["precision_30d"] is None
    assert get(web, "/api/v1/long-term?scope=tech")["last_run"] is None


def test_explore_counts_mentions_and_shares(web):
    data = get(web, "/api/v1/explore?scope=tech&terms=Rust&range=2d")
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
    channel = get(web, "/api/v1/explore?scope=tech&terms=rust&channels=r/programming")
    assert channel["points"][0]["mentions"] == 1
    assert len(get(web, "/api/v1/explore/mentions?scope=tech&terms=rust")) == 3


def test_intents_show_the_switch_and_its_comment(web):
    flows = get(web, "/api/v1/intents/flows?scope=tech")["flows"]
    assert [(flow["from"], flow["to"], flow["mentions"]) for flow in flows] == [
        ("notion", "obsidian", 1)
    ]
    examples = get(web, "/api/v1/intents/examples?scope=tech&term=notion → obsidian")
    assert [row["found"] for row in examples] == [["notion → obsidian"]]
    assert get(web, "/api/v1/intents/examples?scope=tech&intent_kinds=need") == []


def test_the_server_says_when_the_page_isn_t_built(stored):
    with TestClient(create_app(stored, Settings(dist=None))) as web:
        response = web.get("/")
        assert response.status_code == 503 and "pnpm build" in response.text
        assert web.get("/api/v1/meta").status_code == 200


def test_the_server_serves_the_built_app(stored, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<title>Undercurrent</title><div id=root>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path / "assets" / "index-abc.js").write_text("console.log(1)")
    (tmp_path / "assets" / "index-abc.js.br").write_bytes(b"brotli")
    with TestClient(create_app(stored, Settings(dist=tmp_path))) as web:
        # the router handles every path the server doesn't know
        for path in ["/", "/trending", "/t/word/claude?scope=tech"]:
            response = web.get(path)
            assert response.status_code == 200 and b"id=root" in response.content
            assert response.headers["cache-control"] == "no-cache"
            assert "default-src 'self'" in response.headers["content-security-policy"]
        asset = web.get("/assets/index-abc.js", headers={"Accept-Encoding": "br"})
        assert asset.headers["content-encoding"] == "br"
        assert "immutable" in asset.headers["cache-control"]
        assert asset.headers["content-type"].startswith("text/javascript")
        plain = web.get("/assets/index-abc.js", headers={"Accept-Encoding": "identity"})
        assert plain.text == "console.log(1)"
        assert web.get("/favicon.svg").text == "<svg/>"
        assert web.get("/assets/missing.js").status_code == 404
        # nothing outside the build is served
        assert web.get("/assets/%2e%2e/%2e%2e/pyproject.toml").status_code == 404
        assert b"id=root" in web.get("/%2e%2e/pyproject.toml").content
        assert web.get("/api/v1/nothing").status_code == 404


def test_the_server_refuses_bad_requests(web):
    assert web.get("/api/v1/nothing").status_code == 404
    assert web.get("/api/nothing").json() == {"error": "no endpoint nothing"}
    assert web.get("/api/trending").status_code == 404
    response = web.get("/api/v1/trends?horizon=1h")
    assert response.status_code == 400 and "horizon" in response.json()["error"]
    response = web.get("/api/v1/explore?terms=,")
    assert response.status_code == 400 and "term" in response.json()["error"]


def test_the_server_asks_for_the_password(stored):
    app = create_app(stored, Settings(password="secret"))
    with TestClient(app) as web:

        def status(password: str | None) -> int:
            headers = {}
            if password is not None:
                token = base64.b64encode(f"me:{password}".encode()).decode()
                headers["Authorization"] = f"Basic {token}"
            return web.get("/api/v1/meta", headers=headers).status_code

        assert status(None) == 401
        assert status("wrong") == 401
        assert status("secret") == 200


def test_the_server_answers_while_another_request_runs(web):
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(web.get("/api/v1/meta").status_code))
        for _ in range(4)
    ]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [200] * 4
    assert time.monotonic() - started < 10


def test_the_schema_is_json():
    json.dumps(openapi())


USERS = Path(__file__).parent.parent / "clickhouse" / "users.d" / "web.xml"


@pytest.fixture
def readonly(stored):
    """The dashboard's ClickHouse user, created with SQL from clickhouse/users.d/web.xml
    (CI's ClickHouse can't mount the file), on the test database."""
    root = ElementTree.parse(USERS).getroot()
    [profile] = root.findall("profiles/*")
    [user] = root.findall("users/*")
    settings = ", ".join(f"{setting.tag} = {setting.text}" for setting in profile)
    grants = [
        re.sub(r"ON (?!system\.)\w+\.", f"ON {stored.database}.", query.text or "")
        for query in user.findall("grants/query")
    ]
    name, password = f"web_test_{secrets.token_hex(4)}", secrets.token_hex(16)
    try:
        stored.command(f"CREATE SETTINGS PROFILE {name} SETTINGS {settings}")
    except DatabaseError as error:
        if "ACCESS_DENIED" in str(error) and not os.environ.get("CI"):
            pytest.skip("this ClickHouse user can't create users (CI's can)")
        raise
    try:
        stored.command(f"CREATE USER {name} IDENTIFIED BY '{password}' SETTINGS PROFILE {name}")
        for grant in grants:
            stored.command(f"{grant} TO {name}")
        env = replace(Env.from_environ(), clickhouse_user=name, clickhouse_password=password)
        yield env
    finally:
        stored.command(f"DROP USER IF EXISTS {name}")
        stored.command(f"DROP SETTINGS PROFILE IF EXISTS {name}")


def test_the_dashboard_s_user_can_read_but_not_write(stored, readonly):
    reader = web_client(readonly, stored.database)
    writer = connect(readonly, stored.database, autogenerate_session_id=False)
    with TestClient(create_app(reader, Settings(), writer)) as web:
        assert get(web, "/api/v1/trends?scope=tech")["trending"] == 1
        assert get(web, "/api/v1/ingestion")["storage"]
        # its pins and views, and nothing else
        pinned = web.put("/api/v1/pins", json={"kind": "word", "term": "x"})
        assert pinned.status_code == 200, pinned.text
        assert web.delete("/api/v1/pins?kind=word&term=x").status_code == 204
    for statement in [
        "INSERT INTO notifications (kind, term) VALUES ('test', 'x')",
        "CREATE TABLE nothing (x UInt8) ENGINE = Memory",
        "DROP TABLE trends",
        "ALTER TABLE trends DELETE WHERE 1",
    ]:
        with pytest.raises(DatabaseError):
            writer.command(statement)


def test_the_term_page_summarizes_the_term(web):
    data = get(web, "/api/v1/terms/word/rust?scope=tech")
    assert [(trend["scope"], trend["horizon"]) for trend in data["trending"]] == [("tech", "24h")]
    assert (data["mentions_7d"], data["authors_7d"]) == (3, 3)
    assert sum(data["sparkline"]) == 3 and len(data["sparkline"]) == 7 * 24
    annotations = get(web, "/api/v1/terms/word/rust/annotations?scope=tech&range=2d")
    assert [run["scope"] for run in annotations["runs"]] == ["tech"]
    assert web.get("/api/v1/terms/word/rust/explain?scope=r/de").status_code == 404


def test_a_term_with_a_slash_is_the_rest_of_the_path(web):
    data = get(web, "/api/v1/terms/repo/ollama/ollama?scope=tech")
    assert (data["kind"], data["term"]) == ("repo", "ollama/ollama")
    assert get(web, "/api/v1/terms/repo/ollama/ollama/events") == []


def test_the_explainer_recomputes_the_detector_s_score(stored, web):
    # a trend scored like the detector does: no background share, so α is the floor
    counts = Counts(mentions=40, total=2_000, reference_mentions=6, reference_total=50_000)
    score = counts.score(Prior(total=1, weight=0.05, floor=1.0))
    write_trends(
        stored,
        [
            make_trend(
                "rust", kind="word", scope="r/de", horizon="6h", detected_at=HOUR,
                mentions=40, total=2_000, reference_mentions=6, reference_total=50_000,
                authors=30, prior=score.alpha, log_odds=score.log_odds, ratio=score.ratio,
                z=score.z, reference_days=2,
            )
        ],
    )  # fmt: skip
    app = create_app(stored, Settings(config=make_config()))
    with TestClient(app) as client:
        data = get(client, "/api/v1/terms/word/rust/explain?scope=r/de&horizon=6h")
    assert data["recomputed_score"] == pytest.approx(score.z)
    assert data["share_now"] == pytest.approx(0.02)
    assert data["platform_share"] == pytest.approx(0)
    gates = {gate["name"]: gate["passed"] for gate in data["gates"]}
    assert gates["mentions"] and gates["authors"] and not gates["history"]


def test_scope_product_alerts_and_search(stored, web):
    tech = get(web, "/api/v1/scopes/tech")
    assert (tech["type"], tech["platform"]) == ("group", "reddit")
    assert {member["channel"] for member in tech["members"]} == {"r/technology", "r/programming"}
    assert web.get("/api/v1/scopes/nothing").status_code == 404
    assert get(web, "/api/v1/scopes/r/technology")["groups"] == ["reddit", "tech"]

    notion = get(web, "/api/v1/products/Notion?scope=tech")
    assert [flow["product"] for flow in notion["flows_out"]] == ["obsidian"]
    assert notion["counts"] == {"switch": 1}

    stored.insert(
        "notifications",
        [[HOUR, "alert", "tech", "rust", "rust · tech", "×12", True, ""]],
        column_names=["sent_at", "kind", "scope", "term", "title", "message", "ok", "error"],
    )
    [alert] = get(web, "/api/v1/alerts")
    assert (alert["term"], alert["scope"], alert["term_kind"]) == ("rust", "tech", None)

    stored.insert(
        "term_catalog",
        [["word", "rustacean", 5, HOUR], ["word", "rust", 50, HOUR]],
        column_names=["kind", "term", "mentions", "last_seen"],
    )
    assert [hit["term"] for hit in get(web, "/api/v1/search?q=Rus")][:2] == ["rust", "rustacean"]
    assert get(web, "/api/v1/edge?leader=r/a&follower=tech")["edge"] is None


def test_beyond_grafana_endpoints(web):
    related = get(web, "/api/v1/terms/word/rust/related?scope=tech")
    # the three comments with "rust" in tech, none sharing another term three times
    assert (related["documents"], related["terms"]) == (3, [])
    channels = get(web, "/api/v1/terms/word/rust/channels?scope=tech&range=2d")
    assert channels["bucket"] == "hour"
    assert {series["channel"]: series["mentions"] for series in channels["channels"]} == {
        "r/technology": 2,
        "r/programming": 1,
    }
    # 2 of 4 comments in r/technology, 1 of 1 in r/programming
    assert channels["channels"][0]["points"][0][1] == pytest.approx(500)
    rhythm = get(web, "/api/v1/terms/word/rust/rhythm?scope=tech")
    [hour] = [row for row in rhythm["hours"] if row["mentions"]]
    assert hour["relative"] == pytest.approx(1)
    assert sum(day["mentions"] for day in rhythm["days"]) == 3
    assert [point["term"] for point in get(web, "/api/v1/trends/ranks?scope=tech")] == ["rust"]
    assert get(web, "/api/v1/spread/map") == []


def test_a_story_s_page(stored, web):
    start = HOUR - timedelta(hours=2)
    onsets = [
        ("r/technology", "", HOUR - timedelta(hours=1), 2, 4.0, 6.0),
        ("r/programming", "", HOUR, 1, 3.0, 4.0),
    ]
    stored.insert(
        "lead_lag_events",
        [["word", "rust", start, HOUR, "tech", {}, {}, onsets, HOUR, False]],
        column_names=[
            "kind", "term", "start", "last_seen", "topic", "scopes", "first_scopes", "onsets",
            "onsets_until", "closed",
        ],
    )  # fmt: skip
    path = f"/api/v1/events/word/{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/rust"
    story = get(web, path)
    assert [onset["scope"] for onset in story["onsets"]] == ["r/technology", "r/programming"]
    assert {point["scope"] for point in story["series"]} == {"r/technology", "r/programming"}
    [event] = get(web, "/api/v1/terms/word/rust/events")
    assert [onset["scope"] for onset in event["cascade"]] == ["r/technology", "r/programming"]
    nodes = {node["scope"]: node["median_lag"] for node in get(web, "/api/v1/spread/map")}
    assert nodes == {"r/technology": 0, "r/programming": 1}


def test_the_stream_says_what_changed():
    run = datetime(2026, 11, 1, 12, tzinfo=UTC)
    before = State(day_run=run, polled=run)
    assert changes(before, before) == []
    later = State(day_run=run + timedelta(minutes=15), polled=run, notified=run)
    assert changes(before, later) == ["run", "alert"]


def test_the_stream_starts_with_hello_and_polls_once_for_every_tab(stored):
    app = create_app(web_client(Env.from_environ(), stored.database), Settings(stream_seconds=0.5))
    with TestClient(app) as web, web.stream("GET", "/api/v1/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in response.headers
        lines = response.iter_lines()
        assert next(lines) == "event: hello"
    state = read_state(stored)
    assert state.day_run is not None and state.day_run.replace(tzinfo=UTC) == HOUR
    assert read_alerts(stored, None) == []
    stored.insert(
        "notifications",
        [[HOUR + timedelta(minutes=5), "forecast", "r/de", "rust", "rust: a → b?", "", True, ""]],
        column_names=["sent_at", "kind", "scope", "term", "title", "message", "ok", "error"],
    )
    sent = read_alerts(stored, HOUR + timedelta(minutes=1))
    assert [(alert["kind"], alert["scope"]) for alert in sent] == [("forecast", "r/de")]


def test_pins_and_saved_views(web):
    assert get(web, "/api/v1/pins") == []
    assert web.get("/api/v1/pins").headers["cache-control"] == "no-cache"
    pinned = web.put("/api/v1/pins", json={"kind": "word", "term": "rust", "scope": "tech"})
    assert pinned.status_code == 200 and pinned.json()["term"] == "rust"
    assert [(pin["kind"], pin["term"]) for pin in get(web, "/api/v1/pins")] == [("word", "rust")]
    assert web.delete("/api/v1/pins?kind=word&term=rust").status_code == 204
    assert get(web, "/api/v1/pins") == []

    view = {"name": "AI in tech", "url": "/trending?scope=tech&kinds=word"}
    assert web.put("/api/v1/views", json=view).status_code == 200
    assert [saved["url"] for saved in get(web, "/api/v1/views")] == [view["url"]]
    assert (
        web.put("/api/v1/views", json={"name": "x", "url": "https://elsewhere"}).status_code == 400
    )
    assert web.delete("/api/v1/views?name=AI in tech").status_code == 204
    assert get(web, "/api/v1/views") == []


def test_writes_come_from_the_dashboard_s_own_pages(web):
    body = {"kind": "word", "term": "rust"}
    foreign = web.put("/api/v1/pins", json=body, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    form = web.put("/api/v1/pins", content="kind=word", headers={"Content-Type": "text/plain"})
    assert form.status_code == 415
    own = web.put("/api/v1/pins", json=body, headers={"Origin": "http://testserver"})
    assert own.status_code == 200
    web.delete("/api/v1/pins?kind=word&term=rust", headers={"Origin": "http://testserver"})
