"""Which listings to poll and when.

Tracked subreddits are packed into multireddit feeds (``/r/a+b+c/comments``), one for
comments and one for posts. A listing returns at most 100 items, so a feed has to be
polled again before 100 new items have arrived, otherwise we miss some. Each feed
estimates its own item rate from the timestamps in the listing and is polled so that a
poll sees about half a listing of new items. That keeps busy feeds complete and quiet
feeds cheap.

r/all's posts are a feed like these: its newest 100 reach back about 12 seconds, so a
poll every 6 or so sees every post r/all lists.

The sample feed (a sample of r/all's comments) is different: reddit only returns the last
second or two of them, so it can never be complete, and the more often it's polled the
more it sees. It gets what the tracked feeds and searches leave of the request budget,
and its polls overlap: r/all takes seconds to answer, more than the interval between two
polls. It's treated as a random sample.

The churn radar's searches (posts naming a watched product, docs/CHURN-RADAR.md §2.2)
aren't complete either: each is polled at a fixed interval, and its budget comes off
first, before the tracked feeds' and the sample's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import batched
from typing import Literal

from undercurrent.config import Config
from undercurrent.sources.reddit.channels import PLATFORM, SAMPLE, subreddit_of
from undercurrent.sources.reddit.client import LISTING_LIMIT
from undercurrent.sources.reddit.models import RedditItem
from undercurrent.sources.reddit.search import search_query

FeedKind = Literal["comments", "posts"]

# aim for half a listing of new items per poll, the other half absorbs bursts
TARGET_NEW_ITEMS = LISTING_LIMIT / 2
# a full listing without any item we've seen before means we probably missed some
GAP_THRESHOLD = int(LISTING_LIMIT * 0.9)
RATE_SMOOTHING = 0.5
MAX_BACKOFF = 300.0
# polls of the sample waiting for their answer at most, should reddit slow down
MAX_SAMPLE_POLLS_IN_FLIGHT = 8
# a complete feed's: one slow answer (r/all's posts sometimes take 15s) shouldn't hold up
# the next poll past what the listing reaches back
MAX_COMPLETE_POLLS_IN_FLIGHT = 2


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
    # the r/all sample, never complete
    sample: bool = False
    # a search for posts naming a watched product (the churn radar), all over reddit
    search: str | None = None
    # estimated new items per second
    rate: float | None = None
    interval: float = 0.0
    next_poll_at: float = 0.0
    failures: int = 0
    newest_id: int | None = None
    # polls sent and not answered yet, and when the last one started
    in_flight: int = 0
    last_started: float = 0.0
    stats: FeedStats = field(default_factory=FeedStats)

    @property
    def path(self) -> str:
        if self.search is not None:
            return "/search"
        endpoint = "comments" if self.kind == "comments" else "new"
        return f"/r/{'+'.join(self.subreddits)}/{endpoint}"

    @property
    def params(self) -> dict[str, str]:
        return {} if self.search is None else {"q": self.search, "sort": "new", "type": "link"}

    @property
    def complete(self) -> bool:
        """Whether polling it often enough sees every item: tracked subreddits do, the r/all
        sample and searches don't, they get fixed intervals instead."""
        return not self.sample and self.search is None

    @property
    def max_in_flight(self) -> int:
        """The sample's polls overlap, a complete feed's when an answer is slow. A search's
        wait, 15 minutes apart."""
        if self.sample:
            return MAX_SAMPLE_POLLS_IN_FLIGHT
        return MAX_COMPLETE_POLLS_IN_FLIGHT if self.complete else 1


@dataclass(frozen=True)
class PollOutcome:
    gap: bool
    # how far reddit's id sequence advanced since the last poll, for the r/all
    # sample this is roughly the number of comments posted on all of reddit
    id_span: int


def build_feeds(config: Config, subreddits: Sequence[str] | None = None) -> list[Feed]:
    if subreddits is None:
        subreddits = tuple(map(subreddit_of, config.tracked(PLATFORM)))
    feeds = []
    for index, chunk in enumerate(
        batched(subreddits, config.platforms.reddit.max_subreddits_per_feed, strict=False)
    ):
        for kind in ("comments", "posts"):
            feeds.append(Feed(name=f"{kind}-{index + 1}", kind=kind, subreddits=chunk))

    sample = config.platforms.reddit.sample
    if sample.requests_per_minute > 0:
        if sample.posts:
            feeds.append(
                Feed(
                    name=f"posts-{subreddit_of(SAMPLE)}",
                    kind="posts",
                    subreddits=(subreddit_of(SAMPLE),),
                )
            )
        feeds.append(
            Feed(
                name=f"sample-{subreddit_of(SAMPLE)}",
                kind="comments",
                subreddits=(subreddit_of(SAMPLE),),
                sample=True,
            )
        )

    for product, aliases in config.radar.searches.items():
        feeds.append(
            Feed(
                name=f"search-{product.replace(' ', '-')}",
                kind="posts",
                subreddits=(),
                search=search_query(aliases),
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
        self._reddit = config.platforms.reddit
        sample = self._reddit.sample
        self._sample_max = sample.requests_per_minute if self._sample else 0.0
        self._sample_min = min(sample.min_requests_per_minute, self._sample_max)
        self._search_interval = config.radar.search_interval_minutes * 60
        self._search_budget = sum(60.0 / self._search_interval for feed in feeds if feed.search)
        # the tracked feeds come before the sample, which keeps its minimum
        self._tracked_budget = max(
            self._reddit.requests_per_minute - self._sample_min - self._search_budget, 1.0
        )

    @property
    def _sample(self) -> list[Feed]:
        return [feed for feed in self.feeds if feed.sample]

    def due(self, now: float) -> list[Feed]:
        """The feeds to poll now: due, and not waiting for as many answers as they may."""
        return [
            feed
            for feed in self.feeds
            if feed.next_poll_at <= now and feed.in_flight < feed.max_in_flight
        ]

    def next_due_at(self) -> float | None:
        """When the next feed is due, None while every feed waits for answers."""
        return min(
            (feed.next_poll_at for feed in self.feeds if feed.in_flight < feed.max_in_flight),
            default=None,
        )

    def start(self, feed: Feed, now: float) -> None:
        """The next poll is due an interval later, answered or not; an answer reschedules it
        with what it found."""
        feed.in_flight += 1
        feed.last_started = now
        feed.interval = self.interval(feed)
        feed.next_poll_at = now + feed.interval

    def finish(self, feed: Feed) -> None:
        feed.in_flight -= 1

    def record_success(self, feed: Feed, items: Sequence[RedditItem], now: float) -> PollOutcome:
        ids = [item.id36 for item in items]
        gap = (
            feed.complete
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
        # from the last poll started, which may not be this one
        feed.next_poll_at = max(now, feed.last_started) + feed.interval
        return PollOutcome(gap=gap, id_span=max(id_span, 0))

    def record_failure(self, feed: Feed, now: float, retry_after: float | None = None) -> None:
        feed.failures += 1
        feed.stats.errors += 1
        backoff = min(5.0 * 2 ** (feed.failures - 1), MAX_BACKOFF)
        feed.next_poll_at = now + max(backoff, retry_after or 0.0)

    def interval(self, feed: Feed) -> float:
        if feed.sample:
            return 60.0 / max(self.sample_requests_per_minute(), 1.0)
        if feed.search is not None:
            return self._search_interval
        return self._desired_interval(feed) * self._budget_scale()

    def _desired_interval(self, feed: Feed) -> float:
        maximum = (
            self._reddit.max_comment_poll_interval
            if feed.kind == "comments"
            else self._reddit.max_post_poll_interval
        )
        if not feed.rate:
            return maximum
        return min(max(TARGET_NEW_ITEMS / feed.rate, self._reddit.min_poll_interval), maximum)

    def sample_requests_per_minute(self) -> float:
        """What the tracked feeds and searches leave of the budget, at most the sample's
        requests_per_minute, at least its min_requests_per_minute."""
        tracked = min(self._tracked_demand(), self._tracked_budget)
        left = self._reddit.requests_per_minute - self._search_budget - tracked
        return min(max(left, self._sample_min), self._sample_max)

    def _tracked_demand(self) -> float:
        """Requests per minute the tracked feeds need to see every item."""
        return sum(60.0 / self._desired_interval(feed) for feed in self.feeds if feed.complete)

    def _budget_scale(self) -> float:
        """Stretch all tracked intervals when they'd need more than the budget."""
        return max(self._tracked_demand() / self._tracked_budget, 1.0)
