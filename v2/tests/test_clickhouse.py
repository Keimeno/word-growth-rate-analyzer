"""Runs the migrations against a real ClickHouse, in a throwaway database (conftest.py)."""

from datetime import UTC, datetime

import pytest
from helpers import make_config, make_item

from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor
from wgra.query import term_series
from wgra.store import migrate, split_statements


def test_split_statements_ignores_comment_lines():
    sql = "-- a comment; with a semicolon\nCREATE TABLE a (x UInt8) ENGINE = Memory;\n\nSELECT 1;\n"
    assert split_statements(sql) == ["CREATE TABLE a (x UInt8) ENGINE = Memory", "SELECT 1"]


def test_migrations_are_applied_once(client):
    assert migrate(client) == ["001_init", "002_trends", "003_long_term_trends"]
    assert migrate(client) == []


def test_views_count_docs_occurrences_and_distinct_authors(client):
    migrate(client)
    config = make_config()
    processor = Processor(config, b"key")
    client.insert(
        "subreddit_groups", config.group_memberships(), column_names=["group_name", "subreddit"]
    )

    created = int(datetime(2026, 10, 10, 14, 5, tzinfo=UTC).timestamp())
    items = [
        make_item(1, created, author="alice", text="rust rust rust is great"),
        make_item(2, created + 60, author="bob", text="I like rust"),
        make_item(3, created + 120, author="alice", text="rust again"),
        make_item(4, created + 3600, author="carol", text="python only"),
        make_item(5, created, subreddit="programming", author="dave", text="rust in programming"),
    ]
    processed = [processor.process(item) for item in items]
    client.insert("items", [p.item_row for p in processed], column_names=list(ITEM_COLUMNS))
    client.insert(
        "term_events",
        [row for p in processed for row in p.term_rows],
        column_names=list(TERM_COLUMNS),
    )

    hourly = client.query(
        "SELECT hour, sum(docs), sum(occurrences), uniqCombinedMerge(12)(authors) FROM term_hourly "
        "WHERE subreddit = 'technology' AND term = 'rust' GROUP BY hour"
    ).result_rows
    # 3 comments mention rust, 5 times in total, written by 2 people
    assert hourly == [(datetime(2026, 10, 10, 14), 3, 5, 2)]

    daily = client.query(
        "SELECT sum(docs), uniqCombinedMerge(12)(authors) FROM term_daily WHERE term = 'rust'"
    ).result_rows
    assert daily == [(4, 3)]

    scope = client.query(
        "SELECT hour, sum(docs), sum(tokens), uniqCombinedMerge(12)(authors) FROM scope_hourly "
        "WHERE subreddit = 'technology' GROUP BY hour ORDER BY hour"
    ).result_rows
    assert scope == [
        (datetime(2026, 10, 10, 14), 3, 10, 2),
        (datetime(2026, 10, 10, 15), 1, 2, 1),
    ]

    series = term_series(client, "Rust", "tech", days=3650, bucket="day")
    assert [(point.docs, point.authors, point.total_docs) for point in series] == [(4, 3, 5)]
    assert series[0].per_thousand == pytest.approx(800)
