"""Pinned terms and saved views (docs/WEB-DASHBOARD.md §7.1, item 17): two small tables,
written through the web user's narrow grant, so they're the same on every device and the
analyzer can read the pins later."""

from __future__ import annotations

from clickhouse_connect.driver.client import Client

from wgra.web.models import Pin, PinIn, View, ViewIn
from wgra.web.queries import Db


def pins(db: Db) -> list[Pin]:
    rows = db.rows(
        "SELECT kind, term, scope, pinned_at FROM web_pins FINAL WHERE NOT deleted "
        "ORDER BY pinned_at DESC",
        {},
    )
    return [Pin.model_validate(row) for row in rows]


def pin(writer: Client, db: Db, new: PinIn) -> Pin:
    pinned = Pin(**new.model_dump(), pinned_at=db.now)
    writer.insert(
        "web_pins",
        [[pinned.kind, pinned.term, pinned.scope, pinned.pinned_at, False]],
        column_names=["kind", "term", "scope", "pinned_at", "deleted"],
    )
    return pinned


def unpin(writer: Client, db: Db, kind: str, term: str) -> None:
    writer.insert(
        "web_pins",
        [[kind, term, "", db.now, True]],
        column_names=["kind", "term", "scope", "pinned_at", "deleted"],
    )


def views(db: Db) -> list[View]:
    rows = db.rows(
        "SELECT name, url, saved_at FROM web_views FINAL WHERE NOT deleted ORDER BY name", {}
    )
    return [View.model_validate(row) for row in rows]


def save_view(writer: Client, db: Db, new: ViewIn) -> View:
    saved = View(**new.model_dump(), saved_at=db.now)
    writer.insert(
        "web_views",
        [[saved.name, saved.url, saved.saved_at, False]],
        column_names=["name", "url", "saved_at", "deleted"],
    )
    return saved


def delete_view(writer: Client, db: Db, name: str) -> None:
    writer.insert(
        "web_views",
        [[name, "", db.now, True]],
        column_names=["name", "url", "saved_at", "deleted"],
    )
