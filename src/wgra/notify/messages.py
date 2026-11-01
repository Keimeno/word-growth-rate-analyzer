"""What alerts, digests and weekly reports say, and where tapping them leads: the web
dashboard's term page (notify.links: web, the default), or Grafana's term explorer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from wgra.notify.ntfy import Message

TERM_EXPLORER_UID = "wgra-terms"
TRENDING_UID = "wgra-trending"
LONG_TERM_UID = "wgra-long-term"
EARLY_WARNING_UID = "wgra-early-warning"


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
    # word, phrase, or an intent's kind: the term page's url needs it
    kind: str = "word"


def explorer_url(grafana_url: str, term: str, scope: str, weeks: int | None = None) -> str:
    """The term explorer, showing the term in the scope (a group or a channel, the
    dashboards' scope variable takes either) over the last week, or weekly shares over the
    last `weeks` weeks (a group's as the average of its channels')."""
    variables = {"var-group": scope}
    if weeks:
        variables |= {"var-bucket": "week", "var-rate": "macro"}
    since = f"now-{weeks}w" if weeks else "now-7d"
    query = {"var-terms": term, **variables, "from": since, "to": "now"}
    return f"{grafana_url}/d/{TERM_EXPLORER_UID}?{urlencode(query)}"


def trending_url(grafana_url: str, scope: str, horizon: str = "24h") -> str:
    query = {"var-group": scope, "var-horizon": horizon}
    return f"{grafana_url}/d/{TRENDING_UID}?{urlencode(query)}"


def long_term_url(grafana_url: str, group: str) -> str:
    return f"{grafana_url}/d/{LONG_TERM_UID}?{urlencode({'var-group': group})}"


@dataclass(frozen=True)
class Links:
    """Where tapping a notification leads. With a web url and `web` first, the dashboard's
    pages (the term page for a term), with the matching Grafana dashboard as a second
    button; otherwise Grafana's, as before. The icon comes from the dashboard either way."""

    grafana_url: str
    web_url: str = ""
    web_first: bool = True

    @classmethod
    def of(cls, links: Links | str) -> Links:
        return links if isinstance(links, Links) else cls(grafana_url=links)

    @property
    def web(self) -> bool:
        return bool(self.web_url) and self.web_first

    @property
    def icon(self) -> str:
        # docs/brand/notification-icon.png, served by the dashboard
        return f"{self.web_url}/notification-icon.png" if self.web_url else ""

    def term(self, term: str, scope: str, kind: str = "word", weeks: int | None = None) -> str:
        if not self.web:
            return explorer_url(self.grafana_url, term, scope, weeks)
        query = {"scope": scope}
        if weeks:
            query["range"] = "90d" if weeks <= 13 else "26w" if weeks <= 26 else "52w"
        path = f"/t/{quote(kind, safe='')}/{quote(term, safe='/')}"
        return f"{self.web_url}{path}?{urlencode(query, quote_via=quote, safe='/')}"

    def trending(self, scope: str, horizon: str = "24h") -> str:
        if not self.web:
            return trending_url(self.grafana_url, scope, horizon)
        query = {"scope": scope} | ({"horizon": horizon} if horizon != "24h" else {})
        return f"{self.web_url}/trending?{urlencode(query, quote_via=quote, safe='/')}"

    def long_term(self, group: str) -> str:
        if not self.web:
            return long_term_url(self.grafana_url, group)
        return f"{self.web_url}/long-term?{urlencode({'scope': group}, quote_via=quote)}"

    def early_warning(self) -> str:
        return f"{self.web_url}/spread" if self.web else early_warning_url(self.grafana_url)

    def pro(self, label: str, url: str) -> tuple[tuple[str, str], ...]:
        """The second button: Grafana, when the first link went to the dashboard."""
        return ((label, url),) if self.web else ()


def _times(trend: TrendSummary) -> str:
    if trend.is_new:
        return "new"
    return f"{trend.ratio:.0f}×" if trend.ratio >= 10 else f"{trend.ratio:.1f}×"


def alert_message(trend: TrendSummary, links: Links | str) -> Message:
    links = Links.of(links)
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
        lines.append(f"Trending in {trend.breadth} of the {trend.members} channels mentioning it.")
    lines.append(f"Score {trend.z:.1f}")
    term = links.term(trend.term, trend.scope, trend.kind)
    return Message(
        title=f"{trend.term} · {trend.scope}",
        body="\n\n".join(lines),
        click=term,
        icon=links.icon,
        priority=4,
        links=(
            ("Open" if links.web else "Explore", term),
            ("Trending now", links.trending(trend.scope, trend.horizon)),
            *links.pro("Pro mode", explorer_url(links.grafana_url, trend.term, trend.scope)),
        ),
    )


def digest_message(
    group: str, day: date, trends: Sequence[TrendSummary], links: Links | str
) -> Message:
    links = Links.of(links)
    lines = []
    for number, trend in enumerate(trends, start=1):
        details = [_times(trend), f"{trend.mentions} mentions"]
        if trend.scope != group:
            details.append(trend.scope)
        if trend.breadth > 1:
            details.append(f"in {trend.breadth} channels")
        url = links.term(trend.term, trend.scope, trend.kind)
        lines.append(f"{number}. [{trend.term}]({url}) · {' · '.join(details)}")
    return Message(
        title=f"Trending in {group}, {day:%a %d %b}",
        body="\n".join(lines),
        click=links.trending(group),
        icon=links.icon,
        priority=3,
    )


def ping_message(links: Links | str) -> Message:
    links = Links.of(links)
    return Message(
        title="WGRA test notification",
        body="Notifications work. Alerts and daily digests will arrive here.",
        click=links.trending("reddit") if links.web else f"{links.grafana_url}/d/{TRENDING_UID}",
        icon=links.icon,
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
    kind: str = "word"


REPORTED = ("emerging", "mainstreaming", "fading")


def per_month_text(growth: float) -> str:
    """+9% a month, −12% a month, or ×2.5 a month for fast growth."""
    if growth >= 2:
        return f"×{growth:.1f} a month"
    change = round((growth - 1) * 100)
    return f"{'+' if change >= 0 else '−'}{abs(change)}% a month"


def weekly_report_message(
    group: str, week: date, trends: Sequence[LongTermSummary], links: Links | str
) -> Message:
    """`week` is the Monday the analyzed weeks end before."""
    links = Links.of(links)
    sections = []
    for category in REPORTED:
        lines = [f"**{category.capitalize()}**"]
        for number, trend in enumerate(
            (trend for trend in trends if trend.category == category), start=1
        ):
            url = links.term(trend.term, trend.scope, trend.kind, trend.weeks)
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
        click=links.long_term(group),
        icon=links.icon,
        priority=3,
    )


@dataclass(frozen=True)
class ForecastSummary:
    """What a forecast alert needs to know."""

    term: str
    leader: str
    follower: str
    leader_onset: datetime
    expected_at: datetime
    due_by: datetime
    probability: float
    probability_low: float
    probability_high: float
    base_rate: float
    # the edge: leader onsets the follower hadn't started before, and those it followed
    edge_events: int
    edge_hits: int
    # hours
    lag_median: float
    # how the follower reads, when not by its name: "reddit-wide (the r/all sample)"
    follower_label: str = ""
    kind: str = "word"


def early_warning_url(grafana_url: str) -> str:
    return f"{grafana_url}/d/{EARLY_WARNING_UID}"


def _duration(hours: float) -> str:
    return f"{hours / 24:.1f} days" if hours >= 36 else f"{hours:.0f} hours"


def forecast_message(forecast: ForecastSummary, links: Links | str) -> Message:
    links = Links.of(links)
    follower = forecast.follower_label or forecast.follower
    window = (forecast.due_by - forecast.leader_onset).total_seconds() / 3600
    lines = [
        f"Rising in {forecast.leader} since {forecast.leader_onset:%a %H:%M} UTC.",
        f"Of {forecast.edge_events} terms that rose in {forecast.leader} before {follower}, "
        f"{forecast.edge_hits} reached it within {_duration(window)}, "
        f"after {_duration(forecast.lag_median)} (median).",
        f"Chance this time: {forecast.probability:.0%} ({forecast.probability_low:.0%}–"
        f"{forecast.probability_high:.0%}), against {forecast.base_rate:.0%} for any trending "
        f"term. Expected around {forecast.expected_at:%a %d %b %H:00} UTC.",
    ]
    term = links.term(forecast.term, forecast.leader, forecast.kind)
    return Message(
        title=f"{forecast.term}: {forecast.leader} → {forecast.follower}?",
        body="\n\n".join(lines),
        click=term,
        icon=links.icon,
        priority=3,
        links=(
            ("Open" if links.web else "Explore", term),
            ("Early warning", links.early_warning()),
            *links.pro("Pro mode", explorer_url(links.grafana_url, forecast.term, forecast.leader)),
        ),
    )
