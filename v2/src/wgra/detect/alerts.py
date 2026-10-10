"""Which trends become instant alerts. Shared by the live loop and the replay harness.

Only the strongest trends alert, at most a handful per day, and a story alerts once:

* alert-worthy: a score of at least `alert_min_z` with `alert_min_authors` people, or,
  for a group, trending in `alert_min_breadth` of its subreddits at once (and in a good
  share of those mentioning it: 6 of 9 is a story, 3 of 31 isn't)
* warmup: no alerts until a scope has `min_reference_days` of history, before that
  everything looks new
* one alert per term and run, for the scope and horizon with the highest score.
  "openai" bursting in r/OpenAI, tech and tracked is one story, not three alerts
* cooldown: a term isn't alerted again within `cooldown_hours` unless its score has
  doubled since its last alert. It applies across scopes, for the same reason
* daily cap: at most `max_alerts_per_day` alerts in any 24 hours. The rest still show
  up in the digest and on the dashboard
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from clickhouse_connect.driver.client import Client

from wgra.config import DetectConfig, NotifyConfig
from wgra.detect.short_term import GROUP, Trend, as_utc

SENT = "sent"
FAILED = "failed"
CAPPED = "capped"
COOLDOWN = "cooldown"
WARMUP = "warmup"
SKIPPED = "skipped"
# runs without notifications (wgra analyze --no-notify, replays) mark what they'd send
MUTED = "muted"


@dataclass(frozen=True)
class SentAlert:
    term: str
    z: float
    detected_at: datetime


def alert_worthy(trend: Trend, notify: NotifyConfig) -> bool:
    if trend.subsumed_by:
        return False
    strong = trend.z >= notify.alert_min_z and trend.authors >= notify.alert_min_authors
    broad = (
        trend.scope_type == GROUP
        and trend.breadth >= notify.alert_min_breadth
        and trend.breadth >= notify.alert_min_breadth_share * trend.members
    )
    return strong or broad


def decide_alerts(
    trends: Sequence[Trend],
    recent: Iterable[SentAlert],
    now: datetime,
    detect: DetectConfig,
    notify: NotifyConfig,
) -> list[Trend]:
    """Sets `alert` on every alert-worthy trend, returns those that should be sent now.

    `recent` are the alerts sent before, at least those of the last `cooldown_hours`.
    """
    recent = list(recent)
    last_alert: dict[str, SentAlert] = {}
    cooldown_start = now - timedelta(hours=notify.cooldown_hours)
    for alert in sorted(recent, key=lambda alert: alert.detected_at):
        if alert.detected_at > cooldown_start:
            last_alert[alert.term] = alert
    sent_today = sum(alert.detected_at > now - timedelta(hours=24) for alert in recent)

    to_send: list[Trend] = []
    seen_terms: set[str] = set()
    for trend in sorted(trends, key=lambda trend: trend.z, reverse=True):
        if not alert_worthy(trend, notify) or trend.term in seen_terms:
            continue
        seen_terms.add(trend.term)
        if trend.scope in notify.skip_scopes:
            trend.alert = SKIPPED
        elif trend.reference_days < detect.min_reference_days:
            trend.alert = WARMUP
        elif (last := last_alert.get(trend.term)) and trend.z < 2 * last.z:
            trend.alert = COOLDOWN
        elif sent_today + len(to_send) >= notify.max_alerts_per_day:
            trend.alert = CAPPED
        else:
            to_send.append(trend)
    return to_send


def recent_alerts(client: Client, now: datetime, hours: int) -> list[SentAlert]:
    rows = client.query(
        "SELECT term, z, detected_at FROM trends "
        "WHERE alert = {sent:String} AND detected_at > toDateTime({since:UInt32}, 'UTC') "
        "AND detected_at <= toDateTime({now:UInt32}, 'UTC')",
        parameters={
            "sent": SENT,
            "since": int((now - timedelta(hours=max(hours, 24))).timestamp()),
            "now": int(now.timestamp()),
        },
    ).result_rows
    return [SentAlert(term, z, as_utc(detected_at)) for term, z, detected_at in rows]
