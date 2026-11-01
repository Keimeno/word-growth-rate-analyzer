"""The dashboard's SQL, split like its routes: what the Grafana dashboards show
(grafana/build_dashboards.py) and more, with bound parameters instead of Grafana's variables.

Every query runs through a `Db`: as of a time (`now`, by default the present, or the
request's `as_of`), so results are deterministic in tests and the past can be shown, and with
`log_comment` set to its endpoint, so `system.query_log` shows what each one costs. A scope is
a group or a channel, as everywhere: `scope` picks it, `channels` and `doc_types` narrow it
down (empty means all of them), `scopes` picks among the group and its channels for the
tables of trends.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from clickhouse_connect.driver.client import Client
from pydantic import BaseModel, BeforeValidator, Field

WORD_KINDS = ["word", "phrase", "domain", "subreddit"]

# Queries in flight at once, below the web user's max_concurrent_queries_for_user (6,
# clickhouse/users.d/web.xml) with one to spare: requests beyond it wait their turn instead
# of failing with TOO_MANY_SIMULTANEOUS_QUERIES.
CONCURRENT = threading.BoundedSemaphore(5)


@dataclass(frozen=True)
class Db:
    client: Client
    endpoint: str
    now: datetime
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def timestamp(self) -> int:
        return int(self.now.timestamp())

    def rows(self, sql: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        with CONCURRENT:
            result = self.client.query(
                sql,
                parameters={"now": self.timestamp, **parameters},
                settings={"log_comment": f"web {self.endpoint}", **self.settings},
            )
        return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]

    def one(self, sql: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return self.rows(sql, parameters)[0]

    def value(self, sql: str, parameters: dict[str, Any]) -> Any:
        found = self.rows(sql, parameters)
        return next(iter(found[0].values())) if found else None


# Instead of now() and today(), so every query is as of `now`
NOW = "toDateTime({now:UInt32}, 'UTC')"
TODAY = f"toDate({NOW})"

# A scope's channels: a group's, or the channel itself. Groups and channels are looked up,
# never told apart by their names.
GROUP_CHANNELS = (
    "SELECT channel FROM channel_groups WHERE group_name = {scope:String} "
    "UNION ALL SELECT channel FROM channels WHERE channel = {scope:String}"
)
SCOPE = (
    f"channel IN ({GROUP_CHANNELS}) "
    "AND (empty({channels:Array(String)}) OR has({channels:Array(String)}, channel)) "
    "AND (empty({doc_types:Array(String)}) OR has({doc_types:Array(String)}, doc_type))"
)
# the scopes of a table of trends: the group and its channels, or some of them
TREND_SCOPES = (
    "(scope IN (SELECT {scope:String} UNION ALL "
    "SELECT channel FROM channel_groups WHERE group_name = {scope:String}) "
    "AND (empty({scopes:Array(String)}) OR has({scopes:Array(String)}, scope)))"
)
# the platform's background channel, the prior of its scores (r/all)
BACKGROUND = "SELECT channel FROM channels WHERE background"
FROM = "toDateTime({from:UInt32}, 'UTC')"
TO = "toDateTime({to:UInt32}, 'UTC')"
TIME_FILTER = f"hour >= {FROM} AND hour <= {TO}"
# whole days, for term_daily and the hours of the same days
DAYS = f"day >= toDate({FROM}) AND day <= toDate({TO})"
WHOLE_DAYS = (
    f"hour >= toDateTime(toDate({FROM}), 'UTC') AND hour < toDateTime(toDate({TO}) + 1, 'UTC')"
)


def _items(value: Any) -> list[str]:
    """A list from repeated parameters, comma separated ones, or both."""
    values = [value] if isinstance(value, str) else list(value or [])
    return [item.strip() for text in values for item in str(text).split(",") if item.strip()]


# a list parameter: `kinds=word,phrase` or `kinds=word&kinds=phrase`; `kinds=` is empty
Items = Annotated[list[str], BeforeValidator(_items)]
RANGE = re.compile(r"^(\d+)([hdw])$")


class ScopeQuery(BaseModel):
    scope: str = Field("reddit", description="a platform, group or channel")
    channels: Items = Field([], description="only these of the scope's channels")
    doc_types: Items = Field([], description="only these document types (post, comment)")
    scopes: Items = Field([], description="tables of trends: only the group or these channels")

    def parameters(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "channels": self.channels,
            "doc_types": self.doc_types,
            "scopes": self.scopes,
        }


class WindowQuery(BaseModel):
    range: str | None = Field(None, pattern=RANGE.pattern, description="back from now: 6h, 7d, 26w")
    from_: int | None = Field(None, alias="from", ge=0, description="unix seconds")
    to: int | None = Field(None, ge=0, description="unix seconds")

    def window(self, now: datetime, default: str) -> dict[str, int]:
        """The time range as unix seconds: `range` back from now, or `from` and `to`."""
        end = int(now.timestamp())
        if self.from_ is not None:
            start = min(self.from_, end)
            to = self.to if self.to is not None else end
            return {"from": start, "to": min(max(to, start + 1), end + 86400)}
        match = RANGE.match(self.range or default)
        if not match:
            raise ValueError("range must look like 6h, 7d or 26w")
        seconds = int(match[1]) * {"h": 3600, "d": 86400, "w": 7 * 86400}[match[2]]
        return {"from": end - min(seconds, 5 * 365 * 86400), "to": end}


def step(seconds: int, minimum: int, points: int = 300) -> int:
    """A bucket of whole multiples of `minimum` that keeps a series near `points` long."""
    return max(minimum, math.ceil(seconds / points / minimum) * minimum)


def utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def hourly_series(points: Iterable[dict[str, Any]], end: datetime, hours: int) -> dict[str, list]:
    """Each term's counts per hour in the `hours` up to `end`, zeros where it had none."""
    first = utc(end).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    series: dict[str, list] = {}
    for point in points:
        index = int((utc(point["time"]) - first).total_seconds() // 3600)
        if 0 <= index < hours:
            series.setdefault(point["term"], [0] * hours)[index] += point["mentions"]
    return series


def daily_series(points: Iterable[dict[str, Any]], first: date, days: int) -> dict[str, list]:
    series: dict[str, list] = {}
    for point in points:
        index = (point["day"] - first).days
        if 0 <= index < days:
            series.setdefault(point["term"], [0] * days)[index] += point["mentions"]
    return series
