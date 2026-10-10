"""Which listings to poll and when.

Tracked subreddits are packed into multireddit feeds (``/r/a+b+c/comments``), one for
comments and one for posts. A listing returns at most 100 items, so a feed has to be
polled again before 100 new items have arrived, otherwise we miss some. Each feed
estimates its own item rate from the timestamps in the listing and is polled so that a
poll sees about half a listing of new items. That keeps busy feeds complete and quiet
feeds cheap.

The background feed (a sample of r/all) is different: reddit only returns the last
second or two of r/all, so it can never be complete. It gets a fixed share of the
request budget and is treated as a random sample.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import batched
from typing import Literal

from wgra.config import Config
from wgra.reddit.client import LISTING_LIMIT
from wgra.reddit.models import RedditItem

FeedKind = Literal["comments", "posts"]

# aim for half a listing of new items per poll, the other half absorbs bursts
TARGET_NEW_ITEMS = LISTING_LIMIT / 2
# a full listing without any item we've seen before means we probably missed some
GAP_THRESHOLD = int(LISTING_LIMIT * 0.9)
RATE_SMOOTHING = 0.5
MAX_BACKOFF = 300.0


@dataclass
class FeedStats:
    polls: int = 0
    errors: int = 0
    items: int = 0
    gaps: int = 0


@dataclass
class Feed:
    name: str
    kind: FeedKind
    subreddits: tuple[str, ...]
    background: bool = False
    # estimated new items per second
    rate: float | None = None
    interval: float = 0.0
    next_poll_at: float = 0.0
    failures: int = 0
    newest_id: int | None = None
    stats: FeedStats = field(default_factory=FeedStats)

    @property
    def path(self) -> str:
        endpoint = "comments" if self.kind == "comments" else "new"
        return f"/r/{'+'.join(self.subreddits)}/{endpoint}"


@dataclass(frozen=True)
class PollOutcome:
    gap: bool
    # how far reddit's id sequence advanced since the last poll, for the background
    # sample this is roughly the number of comments posted on all of reddit
    id_span: int


def build_feeds(config: Config, subreddits: Sequence[str] | None = None) -> list[Feed]:
    subreddits = config.subreddits if subreddits is None else subreddits
    feeds = []
    for index, chunk in enumerate(
        batched(subreddits, config.ingest.max_subreddits_per_feed, strict=False)
    ):
        for kind in ("comments", "posts"):
            feeds.append(Feed(name=f"{kind}-{index + 1}", kind=kind, subreddits=chunk))

    background = config.background
    if background.requests_per_minute > 0:
        feeds.append(
            Feed(
                name=f"background-{background.subreddit}",
                kind="comments",
                subreddits=(background.subreddit,),
                background=True,
            )
        )
    return feeds


def observed_rate(items: Sequence[RedditItem]) -> float | None:
    """Items per second within the time span the listing covers."""
    if len(items) < 2:
        return None
    timestamps = [item.created_utc for item in items]
    span = max(timestamps) - min(timestamps)
    # timestamps have a resolution of one second
    return (len(items) - 1) / max(span, 1)


class FeedScheduler:
    def __init__(self, feeds: list[Feed], config: Config):
        self.feeds = feeds
        self._ingest = config.ingest
        background_budget = config.background.requests_per_minute if self._background else 0
        self._background_interval = 60.0 / background_budget if background_budget else 0.0
        self._tracked_budget = max(config.ingest.requests_per_minute - background_budget, 1.0)

    @property
    def _background(self) -> list[Feed]:
        return [feed for feed in self.feeds if feed.background]

    def next_feed(self) -> Feed:
        return min(self.feeds, key=lambda feed: feed.next_poll_at)

    def record_success(self, feed: Feed, items: Sequence[RedditItem], now: float) -> PollOutcome:
        ids = [item.id36 for item in items]
        gap = (
            not feed.background
            and feed.newest_id is not None
            and len(ids) >= GAP_THRESHOLD
            and min(ids) > feed.newest_id
        )
        id_span = max(ids) - feed.newest_id if ids and feed.newest_id is not None else 0
        if ids:
            feed.newest_id = max(max(ids), feed.newest_id or 0)

        if (rate := observed_rate(items)) is not None:
            feed.rate = (
                rate
                if feed.rate is None
                else (RATE_SMOOTHING * rate + (1 - RATE_SMOOTHING) * feed.rate)
            )
        if gap and feed.rate is not None:
            # we fell behind, the real rate is higher than our estimate
            feed.rate *= 2

        feed.failures = 0
        feed.stats.polls += 1
        feed.stats.items += len(items)
        feed.stats.gaps += gap
        feed.interval = self.interval(feed)
        feed.next_poll_at = now + feed.interval
        return PollOutcome(gap=gap, id_span=max(id_span, 0))

    def record_failure(self, feed: Feed, now: float, retry_after: float | None = None) -> None:
        feed.failures += 1
        feed.stats.errors += 1
        backoff = min(5.0 * 2 ** (feed.failures - 1), MAX_BACKOFF)
        feed.next_poll_at = now + max(backoff, retry_after or 0.0)

    def interval(self, feed: Feed) -> float:
        if feed.background:
            return self._background_interval
        return self._desired_interval(feed) * self._budget_scale()

    def _desired_interval(self, feed: Feed) -> float:
        maximum = (
            self._ingest.max_comment_poll_interval
            if feed.kind == "comments"
            else self._ingest.max_post_poll_interval
        )
        if not feed.rate:
            return maximum
        return min(max(TARGET_NEW_ITEMS / feed.rate, self._ingest.min_poll_interval), maximum)

    def _budget_scale(self) -> float:
        """Stretch all tracked intervals when they'd need more than the budget."""
        demand = sum(
            60.0 / self._desired_interval(feed) for feed in self.feeds if not feed.background
        )
        return max(demand / self._tracked_budget, 1.0)
