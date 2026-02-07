"""What alerts and digests say, and where tapping them leads (Grafana)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from wgra.config import TRACKED_GROUP
from wgra.notify.ntfy import Message

TERM_EXPLORER_UID = "wgra-terms"
TRENDING_UID = "wgra-trending"


@dataclass(frozen=True)
class TrendSummary:
    """What a notification needs to know about a trend."""

    term: str
    scope: str
    horizon: str
    z: float
    ratio: float
    mentions: int
    authors: int
    is_new: bool
    breadth: int = 0
    members: int = 0
    reference_days: int = 28


def explorer_url(grafana_url: str, term: str, scope: str) -> str:
    """The term explorer, showing the term in the scope over the last week."""
    if scope.startswith("r/"):
        variables = {"var-group": TRACKED_GROUP, "var-subreddit": scope.removeprefix("r/")}
    else:
        variables = {"var-group": scope}
    query = {"var-terms": term, **variables, "from": "now-7d", "to": "now"}
    return f"{grafana_url}/d/{TERM_EXPLORER_UID}?{urlencode(query)}"


def trending_url(grafana_url: str, scope: str, horizon: str = "24h") -> str:
    group = TRACKED_GROUP if scope.startswith("r/") else scope
    query = {"var-group": group, "var-horizon": horizon}
    return f"{grafana_url}/d/{TRENDING_UID}?{urlencode(query)}"


def _times(trend: TrendSummary) -> str:
    if trend.is_new:
        return "new"
    return f"{trend.ratio:.0f}×" if trend.ratio >= 10 else f"{trend.ratio:.1f}×"


def alert_message(trend: TrendSummary, grafana_url: str) -> Message:
    lines = []
    if trend.is_new:
        lines.append(
            f"New: {trend.mentions} comments and posts by {trend.authors} people in the "
            f"last {trend.horizon}, barely mentioned in the {trend.reference_days} days before."
        )
    else:
        lines.append(
            f"{_times(trend)} its usual share: {trend.mentions} comments and posts by "
            f"{trend.authors} people in the last {trend.horizon}."
        )
    if trend.breadth:
        lines.append(
            f"Trending in {trend.breadth} of the {trend.members} subreddits mentioning it."
        )
    lines.append(f"Score {trend.z:.1f}")
    explorer = explorer_url(grafana_url, trend.term, trend.scope)
    return Message(
        title=f"{trend.term} · {trend.scope}",
        body="\n\n".join(lines),
        click=explorer,
        tags=("sparkles" if trend.is_new else "chart_with_upwards_trend",),
        priority=4,
        links=(
            ("Explore", explorer),
            ("Trending now", trending_url(grafana_url, trend.scope, trend.horizon)),
        ),
    )


def digest_message(
    group: str, day: date, trends: Sequence[TrendSummary], grafana_url: str
) -> Message:
    lines = []
    for number, trend in enumerate(trends, start=1):
        details = [_times(trend), f"{trend.mentions} mentions"]
        if trend.scope != group:
            details.append(trend.scope)
        if trend.breadth > 1:
            details.append(f"in {trend.breadth} subreddits")
        url = explorer_url(grafana_url, trend.term, trend.scope)
        lines.append(f"{number}. [{trend.term}]({url}) · {' · '.join(details)}")
    return Message(
        title=f"Trending in {group}, {day:%a %d %b}",
        body="\n".join(lines),
        click=trending_url(grafana_url, group),
        tags=("bar_chart",),
        priority=3,
    )


def ping_message(grafana_url: str) -> Message:
    return Message(
        title="WGRA test notification",
        body="Notifications work. Alerts and daily digests will arrive here.",
        click=f"{grafana_url}/d/{TRENDING_UID}",
        tags=("white_check_mark",),
    )
