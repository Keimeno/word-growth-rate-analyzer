"""`wgra analyze`: detection every 15 minutes, instant alerts and the daily digests."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

from clickhouse_connect.driver.client import Client

from wgra.config import Config, Env
from wgra.detect.alerts import FAILED, MUTED, SENT, decide_alerts, recent_alerts
from wgra.detect.short_term import (
    GROUP,
    Detector,
    Scope,
    Trend,
    as_utc,
    load_scopes,
    next_hour,
    subreddit_scope,
    write_trends,
)
from wgra.notify.messages import TrendSummary, alert_message, digest_message
from wgra.notify.ntfy import Message, Ntfy, NtfyError

log = logging.getLogger(__name__)

NOTIFICATION_COLUMNS = ("sent_at", "kind", "scope", "term", "title", "message", "ok", "error")


def summary(trend: Trend) -> TrendSummary:
    return TrendSummary(
        term=trend.term,
        scope=trend.scope,
        horizon=trend.horizon,
        z=trend.z,
        ratio=trend.ratio,
        mentions=trend.mentions,
        authors=trend.authors,
        is_new=trend.is_new,
        breadth=trend.breadth,
        members=trend.members,
        reference_days=trend.reference_days,
    )


@dataclass
class RunResult:
    detected_at: datetime
    trends: list[Trend]
    seconds: float
    digests: list[str] = field(default_factory=list)

    @property
    def alerts(self) -> Counter[str]:
        return Counter(trend.alert for trend in self.trends if trend.alert)


def digest_trends(
    client: Client, group: Scope, now: datetime, size: int, min_reference_days: int
) -> list[TrendSummary]:
    """The group's strongest trends of the last 24 hours, in the group or its subreddits."""
    rows = client.query(
        """
        SELECT term, argMax(scope, z), argMax(horizon, z), max(z), argMax(ratio, z),
               argMax(mentions, z), argMax(authors, z), argMax(is_new, z),
               argMax(breadth, z), argMax(members, z), argMax(reference_days, z)
        FROM trends
        WHERE detected_at > toDateTime({since:UInt32}, 'UTC')
          AND detected_at <= toDateTime({now:UInt32}, 'UTC')
          AND scope IN {scopes:Array(String)} AND subsumed_by = ''
          AND reference_days >= {min_reference_days:UInt16}
        GROUP BY term
        ORDER BY max(z) DESC
        LIMIT {size:UInt32}
        """,
        parameters={
            "since": int((now - timedelta(hours=24)).timestamp()),
            "now": int(now.timestamp()),
            "scopes": [group.name, *map(subreddit_scope, group.subreddits)],
            "min_reference_days": min_reference_days,
            "size": size,
        },
    ).result_rows
    return [TrendSummary(*row) for row in rows]


class Analyzer:
    def __init__(self, config: Config, env: Env, client: Client, ntfy: Ntfy | None):
        """Without ntfy, nothing is sent: alerts that would be sent are marked "muted"."""
        self._config = config
        self._env = env
        self._client = client
        self._ntfy = ntfy

    def run_once(self, now: datetime | None = None) -> RunResult:
        now = as_utc(now or datetime.now(UTC)).replace(microsecond=0)
        started = time.monotonic()
        scopes = load_scopes(self._client, self._config.detect.exclude_scopes)
        trends = Detector(self._client, self._config).run(
            next_hour(now), detected_at=now, scopes=scopes
        )

        notify = self._config.notify
        recent = recent_alerts(self._client, now, notify.cooldown_hours)
        for trend in decide_alerts(trends, recent, now, self._config.detect, notify):
            if self._ntfy is None:
                trend.alert = MUTED
                continue
            message = alert_message(summary(trend), self._env.grafana_url)
            ok = self._send("alert", trend.scope, trend.term, message)
            trend.alert = SENT if ok else FAILED
        write_trends(self._client, trends)

        digests = self.send_digests(now, scopes) if self._ntfy else []
        result = RunResult(now, trends, time.monotonic() - started, digests)
        log.info(
            "%d trends in %d scopes, %.1fs | alerts %s | digests %s",
            len(trends),
            len({trend.scope for trend in trends}),
            result.seconds,
            dict(result.alerts) or "none",
            ", ".join(digests) or "none",
        )
        return result

    def digest_day(self, now: datetime) -> date | None:
        """The local day whose digest is due, None before the digest time."""
        notify = self._config.notify
        local = now.astimezone(ZoneInfo(notify.timezone))
        hours, minutes = map(int, notify.digest_time.split(":"))
        return local.date() if local.time() >= clock_time(hours, minutes) else None

    def send_digests(self, now: datetime, scopes: Sequence[Scope]) -> list[str]:
        """Sends today's digest of every group that hasn't had one yet, returns the groups."""
        day = self.digest_day(now)
        if day is None:
            return []
        notify = self._config.notify
        day_start = datetime.combine(day, clock_time(), ZoneInfo(notify.timezone))
        handled = {
            scope
            for (scope,) in self._client.query(
                "SELECT DISTINCT scope FROM notifications WHERE kind = 'digest' AND ok "
                "AND sent_at >= toDateTime64({since:UInt32}, 3, 'UTC')",
                parameters={"since": int(day_start.timestamp())},
            ).result_rows
        }
        sent = []
        for group in scopes:
            if (
                group.type != GROUP
                or group.name not in self._config.groups
                or group.name in notify.skip_scopes
                or group.name in handled
            ):
                continue
            trends = digest_trends(
                self._client,
                group,
                now,
                notify.digest_size,
                self._config.detect.min_reference_days,
            )
            if not trends:
                # nothing to say today, remember that the digest is done
                self._log_notification("digest", group.name, "", "nothing trending", "", True)
                continue
            message = digest_message(group.name, day, trends, self._env.grafana_url)
            if self._send("digest", group.name, "", message):
                sent.append(group.name)
        return sent

    def send_test(self) -> None:
        from wgra.notify.messages import ping_message

        if self._ntfy is None:
            raise RuntimeError("notifications are off")
        if not self._send("test", "", "", ping_message(self._env.grafana_url)):
            raise RuntimeError("the test notification couldn't be sent, see the log")

    def _send(self, kind: str, scope: str, term: str, message: Message) -> bool:
        assert self._ntfy is not None
        error = ""
        try:
            self._ntfy.send(message)
        except NtfyError as failure:
            error = str(failure)
            log.warning("sending %s failed: %s", kind, error)
        self._log_notification(kind, scope, term, message.title, message.body, not error, error)
        return not error

    def _log_notification(
        self,
        kind: str,
        scope: str,
        term: str,
        title: str,
        body: str,
        ok: bool,
        error: str = "",
    ) -> None:
        self._client.insert(
            "notifications",
            [[datetime.now(UTC), kind, scope, term, title, body, ok, error]],
            column_names=list(NOTIFICATION_COLUMNS),
        )

    def run_forever(self, stop: threading.Event) -> None:
        interval = self._config.detect.interval_minutes * 60
        while not stop.is_set():
            try:
                self.run_once()
            except Exception:
                # ClickHouse restarting or ntfy down shouldn't end the loop
                log.exception("analysis run failed, trying again at the next interval")
            # runs start on the clock: :00, :15, :30, :45
            stop.wait(interval - time.time() % interval)
