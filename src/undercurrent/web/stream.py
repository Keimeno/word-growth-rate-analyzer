"""Live updates (docs/WEB-DASHBOARD.md §5.3): server-sent events from one watcher that asks
ClickHouse every 30 seconds what changed, whatever the number of open tabs, and tells each
of them: `run` (a new analyzer run), `long_term`, `edges`, `alert` (a notification was
sent, with its term), `ingest` (new polls). The page invalidates the queries that depend on
them; without the stream it refetches on focus and every 5 minutes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clickhouse_connect.driver.client import Client
from fastapi.concurrency import run_in_threadpool
from fastapi.sse import ServerSentEvent

log = logging.getLogger(__name__)

INTERVAL = 30.0
# a bound on what a slow tab can fall behind; past it, it misses events, not memory
QUEUE = 100


@dataclass(frozen=True)
class State:
    """The newest of each thing the page shows, as of a poll."""

    day_run: datetime | None = None
    hours_run: datetime | None = None
    long_term: datetime | None = None
    edges: datetime | None = None
    notified: datetime | None = None
    polled: datetime | None = None


RECENT = "{column} > now() - INTERVAL {days} DAY"
STATE = f"""
SELECT
    (SELECT maxOrNull(detected_at) FROM trends
     WHERE horizon = '24h' AND {RECENT.format(column="detected_at", days=2)}) AS day_run,
    (SELECT maxOrNull(detected_at) FROM trends
     WHERE horizon = '6h' AND {RECENT.format(column="detected_at", days=2)}) AS hours_run,
    (SELECT maxOrNull(detected_at) FROM long_term_trends
     WHERE {RECENT.format(column="detected_at", days=8)}) AS long_term,
    (SELECT maxOrNull(computed_at) FROM propagation_edges
     WHERE {RECENT.format(column="computed_at", days=8)}) AS edges,
    (SELECT maxOrNull(sent_at) FROM notifications
     WHERE ok AND {RECENT.format(column="sent_at", days=2)}) AS notified,
    (SELECT maxOrNull(ts) FROM polls WHERE {RECENT.format(column="ts", days=1)}) AS polled
"""


def read_state(client: Client) -> State:
    result = client.query(STATE, settings={"log_comment": "web /stream"})
    return State(**dict(zip(result.column_names, result.result_rows[0], strict=True)))


def read_alerts(client: Client, since: datetime | None) -> list[dict[str, Any]]:
    """The alerts and forecast alerts sent after `since`."""
    if since is None:
        return []
    result = client.query(
        """
        SELECT kind, scope, term, title FROM notifications
        WHERE ok AND kind IN ('alert', 'forecast') AND sent_at > {since:DateTime64(3)}
        ORDER BY sent_at
        LIMIT 20
        """,
        parameters={"since": since},
        settings={"log_comment": "web /stream"},
    )
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def changes(before: State, after: State) -> list[str]:
    """The events between two polls; the first poll of a watcher has none."""
    events = []
    if (after.day_run, after.hours_run) != (before.day_run, before.hours_run):
        events.append("run")
    if after.long_term != before.long_term:
        events.append("long_term")
    if after.edges != before.edges:
        events.append("edges")
    if after.notified != before.notified:
        events.append("alert")
    if after.polled != before.polled:
        events.append("ingest")
    return events


class Watcher:
    """Polls while at least one tab listens, and fans the changes out to every tab."""

    def __init__(self, client: Client, interval: float = INTERVAL):
        self._client = client
        self._interval = interval
        self._listeners: set[asyncio.Queue[ServerSentEvent]] = set()
        self._task: asyncio.Task[None] | None = None

    @contextlib.asynccontextmanager
    async def listen(self) -> AsyncIterator[asyncio.Queue[ServerSentEvent]]:
        queue: asyncio.Queue[ServerSentEvent] = asyncio.Queue(QUEUE)
        self._listeners.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch())
        try:
            yield queue
        finally:
            self._listeners.discard(queue)
            if not self._listeners and self._task:
                self._task.cancel()
                self._task = None

    def _publish(self, event: ServerSentEvent) -> None:
        for queue in self._listeners:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def _watch(self) -> None:
        state: State | None = None
        while self._listeners:
            try:
                after = await run_in_threadpool(read_state, self._client)
                if state is not None:
                    for name in changes(state, after):
                        if name == "alert":
                            sent = await run_in_threadpool(
                                read_alerts, self._client, state.notified
                            )
                            for alert in sent:
                                self._publish(ServerSentEvent(event="alert", data=alert))
                        else:
                            self._publish(ServerSentEvent(event=name, data={}))
                state = after
            except Exception:
                # ClickHouse away for a moment: the tabs keep refetching on their own
                log.warning("the stream's poll failed, trying again", exc_info=True)
            await asyncio.sleep(self._interval)
