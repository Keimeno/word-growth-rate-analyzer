"""What the pickers offer: scopes (platforms, groups, channels), kinds, document types."""

from __future__ import annotations

from wgra.text.intents import INTENT_KINDS
from wgra.web.models import Meta, Scope
from wgra.web.queries import WORD_KINDS, Db


def meta(db: Db, grafana_url: str) -> Meta:
    scopes = db.rows(
        "SELECT name, position, platform FROM ("
        "SELECT DISTINCT group_name AS name, 0 AS position, "
        "group_name IN (SELECT platform FROM channels) AS platform FROM channel_groups "
        "UNION ALL SELECT channel, 1, false FROM channels WHERE analyzed) "
        "ORDER BY position, platform DESC, name",
        {},
    )
    groups = db.rows(
        "SELECT group_name, arraySort(groupArray(channel)) AS channels FROM channel_groups "
        "GROUP BY group_name",
        {},
    )
    return Meta(
        scopes=[
            Scope(
                name=scope["name"],
                type="platform"
                if scope["platform"]
                else ("group" if scope["position"] == 0 else "channel"),
            )
            for scope in scopes
        ],
        groups={group["group_name"]: group["channels"] for group in groups},
        doc_types=[
            row["doc_type"]
            for row in db.rows("SELECT DISTINCT doc_type FROM scope_hourly ORDER BY 1", {})
        ],
        platforms=[
            row["platform"]
            for row in db.rows("SELECT DISTINCT platform FROM channels ORDER BY 1", {})
        ],
        word_kinds=WORD_KINDS,
        intent_kinds=list(INTENT_KINDS),
        grafana_url=grafana_url,
        now=db.now,
    )
