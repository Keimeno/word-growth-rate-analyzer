"""The demo database (bench/demo.py): a tiny one, seeded the same way as the real one."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

from wgra.config import Env, load_config

sys.path.insert(0, str(Path(__file__).parent.parent / "bench"))
import demo

# pkm and r/all only, a month of hourly counts so the detector's reference period is
# covered, and the live loop for the last day
TINY = demo.Size(
    "tiny",
    hourly_days=30,
    daily_days=30,
    groups=("pkm",),
    history_days=2,
    history_every=24,
    live_days=1,
    hourly_runs=3,
    mondays=0,
    cascade_every=2.0,
    cascade_from=8,
)
CONFIG = Path(__file__).parent.parent / "config.yaml"


def tiny_plan() -> demo.Plan:
    config = demo.demo_config(load_config(CONFIG), TINY)
    return demo.Plan(TINY, config, demo.DEFAULT_AS_OF, demo.SEED)


def planted(plan: demo.Plan) -> list[demo.Doc]:
    planter = demo.Planter(plan)
    demo.plant_chatter(planter)
    demo.plant_events(planter)
    demo.plant_cascades(planter, demo.load_words())
    demo.plant_launch(planter)
    demo.plant_long_term(planter)
    return planter.docs


def test_the_templates_plant_only_their_terms():
    demo.check_templates()


def test_the_stories_are_the_same_every_time():
    plan = tiny_plan()
    docs = planted(plan)
    assert docs == planted(plan)
    assert {doc.channel for doc in docs} <= set(plan.channels)
    assert all(plan.daily_start <= doc.at < plan.as_of for doc in docs)
    # the Notion outage: 45 complaints in r/notion in the 5 hours from A−20h
    start = plan.as_of - timedelta(hours=20)
    outage = [
        doc
        for doc in docs
        if doc.intents == ("complaint: notion",) and start <= doc.at <= start + timedelta(hours=5)
    ]
    assert sum(doc.channel == "r/notion" for doc in outage) >= 45


@pytest.fixture(scope="module")
def seeded(module_client):
    plan = tiny_plan()
    result = demo.seed(module_client, plan, Env.from_environ(), quiet=True)
    return module_client, plan, result


def test_nothing_expires(seeded):
    client, *_ = seeded
    (with_ttl,) = client.query(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() "
        "AND create_table_query LIKE '% TTL %'"
    ).result_rows[0]
    assert with_ttl == 0
    tables = {row[0] for row in client.query("SHOW TABLES").result_rows}
    assert not {table for table in tables if table.startswith("demo_")}


def test_the_last_48_hours_are_items_with_their_intents(seeded):
    client, plan, _ = seeded
    first, last, switches = client.query(
        "SELECT min(created_at), max(created_at), "
        "countIf(has(intents, 'notion → obsidian')) FROM items"
    ).result_rows[0]
    assert first >= (plan.as_of - timedelta(hours=48)).replace(tzinfo=None)
    assert last < plan.as_of.replace(tzinfo=None)
    assert switches > 0
    # the items' terms went through the materialized views
    (mentions,) = client.query(
        "SELECT sum(docs) FROM term_hourly WHERE term = 'complaint: notion' "
        "AND hour >= toDateTime({start:UInt32}, 'UTC')",
        parameters={"start": int((plan.as_of - timedelta(hours=48)).timestamp())},
    ).result_rows[0]
    assert mentions >= 45


def test_the_detector_finds_the_outage_and_alerts_without_sending(seeded):
    client, plan, result = seeded
    rows = client.query(
        "SELECT scope, z FROM trends WHERE term = 'complaint: notion' "
        "AND detected_at = toDateTime({at:UInt32}, 'UTC') AND horizon = '24h'",
        parameters={"at": int(plan.as_of.timestamp())},
    ).result_rows
    assert {scope for scope, _ in rows} >= {"r/notion", "pkm"}
    assert result["stats"]["alerts"] > 0
    (alerts,) = client.query(
        "SELECT count() FROM notifications WHERE kind = 'alert' AND ok "
        "AND sent_at <= toDateTime({at:UInt32}, 'UTC')",
        parameters={"at": int(plan.as_of.timestamp())},
    ).result_rows[0]
    assert alerts == result["stats"]["alerts"]


def test_collection_has_a_gap(seeded):
    client, plan, _ = seeded
    gap_at, errors = client.query(
        "SELECT minIf(ts, gap), countIf(status != 200) FROM polls"
    ).result_rows[0]
    gap_start = plan.as_of - demo.GAP_BEFORE
    assert gap_start + demo.GAP_LENGTH <= gap_at.replace(tzinfo=gap_start.tzinfo)
    assert errors > 0
