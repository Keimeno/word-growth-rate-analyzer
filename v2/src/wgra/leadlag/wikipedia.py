"""Optional (wikipedia.enabled): does interest on Wikipedia follow reddit's onsets?

For events whose term names a Wikipedia article, daily pageviews of the article are
compared with the event's onsets. Free, no key:

* the article: the action API resolves the term (as written, then in title case) through
  redirects; missing pages and disambiguation pages don't count
* pageviews: the Wikimedia REST API, per day, human views on all devices
* both are cached in ClickHouse (wiki_articles, wiki_pageviews), each fetched once
* a descriptive user agent and a rate limit (wikipedia.requests_per_second), as
  Wikimedia's API etiquette asks

Interest on Wikipedia starts on the first day of the event's span with at least
`min_views` views and `min_ratio` times the median of the 28 days before. The lead is that
day minus the day of the event's first reddit onset (any scope): positive when reddit was
first. A sign test over the events with an onset on both says whether reddit leads more
often than chance.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

import httpx
from clickhouse_connect.driver.client import Client

from wgra.config import Config, WikipediaConfig
from wgra.detect.short_term import as_utc
from wgra.leadlag.events import Event, event_span, load_events
from wgra.leadlag.stats import binomial_tail

log = logging.getLogger(__name__)

PAGEVIEWS_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "{project}/all-access/user/{article}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00"
)
# the action API takes up to 50 titles at once
TITLES_PER_REQUEST = 50
# the median the views are compared with
BASELINE_DAYS = 28
KINDS = ("word", "phrase")


class WikimediaError(Exception):
    pass


class Wikimedia:
    """The two Wikimedia APIs, at most `requests_per_second`."""

    def __init__(
        self,
        settings: WikipediaConfig,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.project = settings.project
        self._interval = 1 / settings.requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._last = -math.inf
        self.requests = 0
        self._http = httpx.Client(
            headers={"User-Agent": f"{settings.user_agent} httpx/{httpx.__version__}"},
            timeout=20.0,
            transport=transport,
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        wait = self._last + self._interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()
        self.requests += 1
        try:
            return self._http.get(url, params=params)
        except httpx.HTTPError as error:
            raise WikimediaError(f"Wikimedia unreachable: {error}") from error

    def articles(self, terms: Sequence[str]) -> dict[str, str]:
        """Each term's article title, '' when none: missing, or a disambiguation page."""
        found: dict[str, str] = {}
        candidates = {term: [term, term.title()] for term in terms}
        titles = sorted({title for options in candidates.values() for title in options})
        resolved: dict[str, str] = {}
        for first in range(0, len(titles), TITLES_PER_REQUEST):
            resolved |= self._resolve(titles[first : first + TITLES_PER_REQUEST])
        for term, options in candidates.items():
            found[term] = next((resolved[t] for t in options if resolved.get(t)), "")
        return found

    def _resolve(self, titles: Sequence[str]) -> dict[str, str]:
        """title -> the article it leads to, '' for none."""
        response = self._get(
            f"https://{self.project}.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "pageprops",
                "ppprop": "disambiguation",
                "titles": "|".join(titles),
            },
        )
        if response.status_code != 200:
            raise WikimediaError(f"action API answered {response.status_code}")
        query = response.json().get("query", {})
        steps = {item["from"]: item["to"] for item in query.get("normalized", [])}
        steps |= {item["from"]: item["to"] for item in query.get("redirects", [])}
        pages = {
            page["title"]: not page.get("missing")
            and not page.get("invalid")
            and "disambiguation" not in page.get("pageprops", {})
            for page in query.get("pages", [])
        }
        result = {}
        for title in titles:
            current, seen = title, set()
            while current in steps and current not in seen:
                seen.add(current)
                current = steps[current]
            result[title] = current if pages.get(current) else ""
        return result

    def pageviews(self, article: str, start: date, end: date) -> dict[date, int]:
        """Daily views of the article from start to end (inclusive), {} without data."""
        url = PAGEVIEWS_URL.format(
            project=self.project,
            article=quote(article.replace(" ", "_"), safe=""),
            start=start,
            end=end,
        )
        response = self._get(url)
        if response.status_code == 404:
            return {}
        if response.status_code != 200:
            raise WikimediaError(f"pageviews API answered {response.status_code}")
        return {
            datetime.strptime(item["timestamp"][:8], "%Y%m%d").date(): int(item["views"])
            for item in response.json().get("items", [])
        }

    def close(self) -> None:
        self._http.close()


def interest_onset(
    views: dict[date, int], first: date, last: date, settings: WikipediaConfig
) -> date | None:
    """The first day from first to last with at least min_views views and min_ratio times
    the median of the 28 days before (days without data count as 0 views)."""
    day = first
    while day <= last:
        before = sorted(
            views.get(day - timedelta(days=offset), 0) for offset in range(1, BASELINE_DAYS + 1)
        )
        median = (before[BASELINE_DAYS // 2 - 1] + before[BASELINE_DAYS // 2]) / 2
        today = views.get(day, 0)
        if today >= settings.min_views and today >= settings.min_ratio * median:
            return day
        day += timedelta(days=1)
    return None


@dataclass(frozen=True)
class Lead:
    kind: str
    term: str
    start: datetime
    article: str
    reddit_onset: datetime
    reddit_scope: str
    wiki_onset: date | None

    @property
    def lead_days(self) -> int | None:
        """Days from reddit's first onset to Wikipedia's, positive when reddit was first."""
        if self.wiki_onset is None:
            return None
        return (self.wiki_onset - self.reddit_onset.date()).days


LEAD_COLUMNS = (
    "kind",
    "term",
    "start",
    "project",
    "article",
    "reddit_onset",
    "reddit_scope",
    "wiki_onset",
    "lead_days",
)


class WikipediaCheck:
    """Looks up the events' articles and pageviews (cached) and compares the onsets."""

    def __init__(self, client: Client, config: Config, wikimedia: Wikimedia):
        self._client = client
        self._config = config
        self._wikimedia = wikimedia

    @property
    def settings(self) -> WikipediaConfig:
        return self._config.wikipedia

    def run(self, now: datetime, days: int, max_events: int) -> list[Lead]:
        """Compares the closed events of the last `days` that aren't compared yet."""
        done = {
            (kind, term, as_utc(start))
            for kind, term, start in self._client.query(
                "SELECT kind, term, start FROM wiki_leads FINAL WHERE project = {project:String}",
                parameters={"project": self.settings.project},
            ).result_rows
        }
        events = [
            event
            for event in load_events(self._client, now - timedelta(days=days), now)
            if event.closed and event.kind in KINDS and event.onsets and event.key not in done
        ][:max_events]
        if not events:
            return []
        articles = self._articles({event.term for event in events})
        leads = []
        for event in events:
            article = articles.get(event.term, "")
            if article:
                leads.append(self._compare(event, article))
        if leads:
            self._client.insert(
                "wiki_leads",
                [
                    (
                        lead.kind,
                        lead.term,
                        lead.start,
                        self.settings.project,
                        lead.article,
                        lead.reddit_onset,
                        lead.reddit_scope,
                        lead.wiki_onset,
                        lead.lead_days,
                    )
                    for lead in leads
                ],
                column_names=list(LEAD_COLUMNS),
            )
        log.info(
            "wikipedia: %d events, %d with an article, %d requests",
            len(events),
            len(leads),
            self._wikimedia.requests,
        )
        return leads

    def _articles(self, terms: Iterable[str]) -> dict[str, str]:
        terms = sorted(set(terms))
        rows = self._client.query(
            "SELECT term, article FROM wiki_articles FINAL "
            "WHERE project = {project:String} AND term IN {terms:Array(String)}",
            parameters={"project": self.settings.project, "terms": terms},
        ).result_rows
        cached: dict[str, str] = {term: article for term, article in rows}
        missing = [term for term in terms if term not in cached]
        if missing:
            found = self._wikimedia.articles(missing)
            now = datetime.now(UTC)
            self._client.insert(
                "wiki_articles",
                [(self.settings.project, term, found[term], now) for term in missing],
                column_names=["project", "term", "article", "checked_at"],
            )
            cached |= found
        return cached

    def _views(self, article: str, first: date, last: date) -> dict[date, int]:
        rows = self._client.query(
            "SELECT day, views FROM wiki_pageviews FINAL WHERE project = {project:String} "
            "AND article = {article:String} AND day BETWEEN {first:Date} AND {last:Date}",
            parameters={
                "project": self.settings.project,
                "article": article,
                "first": first,
                "last": last,
            },
        ).result_rows
        views: dict[date, int] = {day: int(count) for day, count in rows}
        if len(views) < (last - first).days + 1:
            fetched = self._wikimedia.pageviews(article, first, last)
            # days without views are stored as 0, so they aren't fetched again
            days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
            now = datetime.now(UTC)
            self._client.insert(
                "wiki_pageviews",
                [(self.settings.project, article, day, fetched.get(day, 0), now) for day in days],
                column_names=["project", "article", "day", "views", "fetched_at"],
            )
            views = {day: fetched.get(day, 0) for day in days}
        return views

    def _compare(self, event: Event, article: str) -> Lead:
        span = event_span(event.start, self._config.lead_lag)
        first, last = span.start.date(), (span.end - timedelta(seconds=1)).date()
        views = self._views(article, first - timedelta(days=BASELINE_DAYS), last)
        reddit = min(
            (onset for onset in event.onsets if not onset.without), key=lambda onset: onset.at
        )
        return Lead(
            kind=event.kind,
            term=event.term,
            start=event.start,
            article=article,
            reddit_onset=reddit.at,
            reddit_scope=reddit.scope,
            wiki_onset=interest_onset(views, first, last, self.settings),
        )


@dataclass(frozen=True)
class LeadSummary:
    events: int
    with_onset: int
    reddit_first: int
    same_day: int
    wiki_first: int
    median_lead: float | None
    # two-sided sign test of reddit first vs Wikipedia first (same day left out)
    p_value: float | None


def summarize(leads: Sequence[Lead]) -> LeadSummary:
    days = sorted(lead.lead_days for lead in leads if lead.lead_days is not None)
    reddit_first = sum(1 for value in days if value > 0)
    wiki_first = sum(1 for value in days if value < 0)
    decided = reddit_first + wiki_first
    p_value = None
    if decided:
        p_value = min(1.0, 2 * binomial_tail(max(reddit_first, wiki_first), decided, 0.5))
    median = None
    if days:
        middle = len(days) // 2
        median = days[middle] if len(days) % 2 else (days[middle - 1] + days[middle]) / 2
    return LeadSummary(
        events=len(leads),
        with_onset=len(days),
        reddit_first=reddit_first,
        same_day=sum(1 for value in days if value == 0),
        wiki_first=wiki_first,
        median_lead=median,
        p_value=p_value,
    )


def load_leads(client: Client, project: str, since: datetime) -> list[Lead]:
    rows = client.query(
        "SELECT kind, term, start, article, reddit_onset, reddit_scope, wiki_onset "
        "FROM wiki_leads FINAL WHERE project = {project:String} "
        "AND start >= toDateTime({since:UInt32}, 'UTC')",
        parameters={"project": project, "since": int(since.timestamp())},
    ).result_rows
    return [
        Lead(kind, term, as_utc(start), article, as_utc(onset), scope, wiki_onset)
        for kind, term, start, article, onset, scope, wiki_onset in rows
    ]


def summary_text(summary: LeadSummary) -> list[str]:
    lines = [
        f"{summary.events} events with a Wikipedia article, {summary.with_onset} with rising "
        "interest there"
    ]
    if summary.with_onset:
        assert summary.median_lead is not None
        lines.append(
            f"  reddit first {summary.reddit_first}, same day {summary.same_day}, Wikipedia "
            f"first {summary.wiki_first}; median lead {summary.median_lead:+.1f} days"
        )
    if summary.p_value is not None:
        lines.append(f"  sign test (reddit first vs Wikipedia first): p = {summary.p_value:.3f}")
    return lines
