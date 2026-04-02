"""What alerts, digests and weekly reports say, and where tapping them leads (Grafana)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

from wgra.config import TRACKED_GROUP
from wgra.notify.ntfy import Message

TERM_EXPLORER_UID = "wgra-terms"
TRENDING_UID = "wgra-trending"
LONG_TERM_UID = "wgra-long-term"


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


def explorer_url(grafana_url: str, term: str, scope: str, weeks: int | None = None) -> str:
    """The term explorer, showing the term in the scope over the last week, or weekly
    shares over the last `weeks` weeks (a group's as the average of its subreddits')."""
    if scope.startswith("r/"):
        variables = {"var-group": TRACKED_GROUP, "var-subreddit": scope.removeprefix("r/")}
    else:
        variables = {"var-group": scope}
    if weeks:
        variables |= {"var-bucket": "week", "var-rate": "macro"}
    since = f"now-{weeks}w" if weeks else "now-7d"
    query = {"var-terms": term, **variables, "from": since, "to": "now"}
    return f"{grafana_url}/d/{TERM_EXPLORER_UID}?{urlencode(query)}"


def trending_url(grafana_url: str, scope: str, horizon: str = "24h") -> str:
    group = TRACKED_GROUP if scope.startswith("r/") else scope
    query = {"var-group": group, "var-horizon": horizon}
    return f"{grafana_url}/d/{TRENDING_UID}?{urlencode(query)}"


def long_term_url(grafana_url: str, group: str) -> str:
    return f"{grafana_url}/d/{LONG_TERM_UID}?{urlencode({'var-group': group})}"


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


@dataclass(frozen=True)
class LongTermSummary:
    """What the weekly report needs to know about a long-term trend."""

    term: str
    scope: str
    category: str
    # weeks in the window
    weeks: int
    # per month, 1.09 is +9%
    growth: float
    # per 1,000 comments and posts, the trend line at the start and end of the window
    start_share: float
    end_share: float


REPORTED = ("emerging", "mainstreaming", "fading")


def per_month_text(growth: float) -> str:
    """+9% a month, −12% a month, or ×2.5 a month for fast growth."""
    if growth >= 2:
        return f"×{growth:.1f} a month"
    change = round((growth - 1) * 100)
    return f"{'+' if change >= 0 else '−'}{abs(change)}% a month"


def weekly_report_message(
    group: str, week: date, trends: Sequence[LongTermSummary], grafana_url: str
) -> Message:
    """`week` is the Monday the analyzed weeks end before."""
    sections = []
    for category in REPORTED:
        lines = [f"**{category.capitalize()}**"]
        for number, trend in enumerate(
            (trend for trend in trends if trend.category == category), start=1
        ):
            url = explorer_url(grafana_url, trend.term, trend.scope, trend.weeks)
            details = [per_month_text(trend.growth), f"{trend.weeks} weeks"]
            if trend.scope != group:
                details.append(trend.scope)
            lines.append(f"{number}. [{trend.term}]({url}) · {' · '.join(details)}")
        if len(lines) > 1:
            sections.append("\n".join(lines))
    last_day = week - timedelta(days=1)
    return Message(
        title=f"Long-term trends in {group}, weeks to {last_day:%a %d %b}",
        body="\n\n".join(sections),
        click=long_term_url(grafana_url, group),
        tags=("chart_with_upwards_trend",),
        priority=3,
    )
