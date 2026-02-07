"""Replays detection over stored history, "as of" past times, to tune the thresholds.

Every step runs the detector as if it were that time: only the hours before it are
used (the window ends on the step). The alert rules (warmup, cooldown, daily cap) are
simulated in memory. Nothing is written to the trends table and nothing is sent, so a
replay can run next to the live loop with any settings.
"""

from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TextIO

from clickhouse_connect.driver.client import Client

from wgra.config import Config, Horizon
from wgra.detect.alerts import SENT, SentAlert, alert_worthy, decide_alerts
from wgra.detect.short_term import (
    GROUP,
    TREND_COLUMNS,
    Detector,
    Scope,
    Trend,
    as_utc,
    load_scopes,
    subreddit_scope,
)

log = logging.getLogger(__name__)


@dataclass
class ReplayResult:
    steps: list[datetime] = field(default_factory=list)
    # trending (passing the gates) per step and horizon
    trending: Counter[tuple[datetime, str]] = field(default_factory=Counter)
    # every alert-worthy trend with what the alert rules decided
    decisions: list[Trend] = field(default_factory=list)

    @property
    def alerts(self) -> list[Trend]:
        return [trend for trend in self.decisions if trend.alert == SENT]


def hour_floor(moment: datetime) -> datetime:
    return as_utc(moment).replace(minute=0, second=0, microsecond=0)


def replay(
    client: Client,
    config: Config,
    start: datetime,
    end: datetime,
    step: timedelta = timedelta(hours=1),
    scopes: Sequence[Scope] | None = None,
    horizons: Sequence[Horizon] | None = None,
    out: TextIO | None = None,
    progress: Callable[[datetime, list[Trend]], None] | None = None,
) -> ReplayResult:
    """Runs the detector at every step from start to end. `out` gets every trend as csv."""
    if step < timedelta(hours=1) or step % timedelta(hours=1):
        raise ValueError("the step must be whole hours, the data is hourly")
    detector = Detector(client, config)
    if scopes is None:
        scopes = load_scopes(client, config.detect.exclude_scopes)
    writer = None
    if out is not None:
        writer = csv.writer(out)
        writer.writerow(TREND_COLUMNS)

    result = ReplayResult()
    sent: list[SentAlert] = []
    at = hour_floor(start)
    while at <= end:
        trends = detector.run(at, scopes=scopes, horizons=horizons)
        for trend in decide_alerts(trends, sent, at, config.detect, config.notify):
            trend.alert = SENT
            sent.append(SentAlert(trend.term, trend.z, at))
        result.steps.append(at)
        for trend in trends:
            if not trend.subsumed_by:
                result.trending[at, trend.horizon] += 1
            if alert_worthy(trend, config.notify):
                result.decisions.append(trend)
        if writer:
            writer.writerows(trend.row() for trend in trends)
        if progress:
            progress(at, trends)
        at += step
    return result


def groups_of(scope: str, scopes: Sequence[Scope]) -> list[str]:
    """The groups a trend counts for: the group itself, or the groups of its subreddit."""
    return [
        group.name
        for group in scopes
        if group.type == GROUP
        and (group.name == scope or scope in map(subreddit_scope, group.subreddits))
    ]


def report(result: ReplayResult, scopes: Sequence[Scope]) -> str:
    """A plain text summary: per day and group, how many alerts the settings produce."""
    lines = []
    if not result.steps:
        return "nothing replayed"
    lines.append(
        f"{len(result.steps)} steps from {result.steps[0]:%Y-%m-%d %H:%M} "
        f"to {result.steps[-1]:%Y-%m-%d %H:%M} UTC"
    )
    per_horizon: dict[str, list[int]] = defaultdict(list)
    for (_, horizon), count in result.trending.items():
        per_horizon[horizon].append(count)
    for horizon, counts in sorted(per_horizon.items()):
        lines.append(
            f"  {horizon}: {sum(counts) / len(result.steps):.0f} trending terms per step "
            f"(all scopes, without subsumed ones)"
        )

    statuses = Counter(trend.alert for trend in result.decisions)
    lines.append(
        f"alert-worthy: {len(result.decisions)} | "
        # '' is a term already alerted in another scope or horizon of the same step
        + ", ".join(f"{status or 'same story'} {count}" for status, count in statuses.items())
    )

    worthy: Counter[tuple[date, str]] = Counter()
    sent: Counter[tuple[date, str]] = Counter()
    for trend in result.decisions:
        day = trend.detected_at.date()
        for group in groups_of(trend.scope, scopes):
            worthy[day, group] += 1
            if trend.alert == SENT:
                sent[day, group] += 1
    if worthy:
        lines.append("\nper day and group: alerts sent / alert-worthy trends (all steps)")
        for day, group in sorted(worthy):
            lines.append(f"  {day}  {group:<12} {sent[day, group]:>3} / {worthy[day, group]}")

    if result.alerts:
        lines.append("\nalerts")
        for trend in result.alerts:
            flags = ["new"] if trend.is_new else []
            if trend.breadth:
                flags.append(f"breadth {trend.breadth}/{trend.members}")
            lines.append(
                f"  {trend.detected_at:%m-%d %H:%M} {trend.horizon:>3} {trend.scope:<20} "
                f"{trend.term:<24} z {trend.z:5.1f}  {trend.ratio:6.1f}x  "
                f"{trend.mentions} mentions, {trend.authors} authors  {' '.join(flags)}"
            )
    return "\n".join(lines)


def open_csv(path: Path | None) -> TextIO | None:
    return path.open("w", newline="", encoding="utf-8") if path else None
