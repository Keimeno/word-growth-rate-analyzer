"""Reddit as a source: polls the tracked subreddits, r/all (its posts, a sample of its
comments) and the churn radar's searches forever, and hands what it finds to the shared
pipeline.

The source decides where an item's counts go: a tracked subreddit's own channel, r/all
for everything r/all shows from elsewhere, r/_search for search results, every other
untracked post naming a watched product and the comment trees under them. It also
decides which items the pipeline skips: bots, moderators' and stickied comments, and
deleted ones.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime

from clickhouse_connect.driver.client import Client

from undercurrent.config import Config
from undercurrent.ingest.pipeline import RecentKeys
from undercurrent.sources.base import Item, Poll, Sink
from undercurrent.sources.reddit.channels import PLATFORM, SAMPLE, SEARCH, channel_of, subreddit_of
from undercurrent.sources.reddit.client import RedditClient, RedditError
from undercurrent.sources.reddit.feeds import Feed, FeedScheduler, build_feeds
from undercurrent.sources.reddit.models import RedditItem
from undercurrent.sources.reddit.search import due_trees, names_any, stored_ids

log = logging.getLogger(__name__)

# items older than this are ignored. They may have been counted before and since
# expired from the raw items table (48h), so we can't tell whether they're new.
MAX_ITEM_AGE = 36 * 3600
# ids of items seen recently, to catch the r/all sample overlapping tracked feeds
SEEN_CAPACITY = 300_000
REPORT_INTERVAL = 60.0
# how often due comment trees are looked for (search.TREE_WINDOW_HOURS gives each of them
# many chances)
TREE_CHECK_INTERVAL = 600.0

DELETED_TEXTS = frozenset({"[deleted]", "[removed]"})


def is_bot(author: str) -> bool:
    author = author.lower()
    return author == "automoderator" or author.endswith("bot")


def skip_reason(item: RedditItem) -> str | None:
    """Why the pipeline shouldn't count an item: deleted, a bot, or moderation."""
    if item.text.strip() in DELETED_TEXTS:
        return "deleted"
    if is_bot(item.author):
        return "bot"
    if item.distinguished in ("moderator", "admin") or item.stickied:
        return "moderation"
    return None


def to_item(item: RedditItem, config: Config, channel: str | None = None) -> Item:
    """The item for the pipeline: its counts in `channel` if given (the search's), in its
    subreddit's channel if tracked, otherwise in r/all with every other subreddit the
    sample finds (the url still names the real subreddit). Its language is its real
    subreddit's."""
    subreddit = channel_of(item.subreddit)
    if channel is None:
        channel = subreddit if config.is_tracked(subreddit) else SAMPLE
    return item.to_item(channel, config.language(subreddit), skip_reason(item))


def reddit_credentials() -> tuple[str, str, str]:
    """REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT, only needed while
    reddit is enabled."""
    names = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
    if missing := [name for name in names if not os.environ.get(name)]:
        raise RuntimeError(f"missing environment variables: {', '.join(missing)} (see .env)")
    client_id, secret, user_agent = (os.environ[name] for name in names)
    return client_id, secret, user_agent


def seed_state(client: Client, feeds: list[Feed], seen: RecentKeys) -> None:
    """Restores what a previous run already ingested, so a restart doesn't count it twice."""
    newest = client.query(
        "SELECT doc_type, channel, argMax(id, created_at) FROM items "
        "WHERE platform = {platform:String} AND created_at > now() - INTERVAL 40 HOUR "
        "GROUP BY doc_type, channel",
        parameters={"platform": PLATFORM},
    ).result_rows
    newest_id = {
        (doc_type, channel): int(fullname[3:], 36) for doc_type, channel, fullname in newest
    }
    for feed in feeds:
        doc_type = "comment" if feed.kind == "comments" else "post"
        channels = [(doc_type, channel_of(subreddit)) for subreddit in feed.subreddits]
        ids = [newest_id[key] for key in channels if key in newest_id]
        if ids and feed.complete:
            feed.newest_id = max(ids)

    # not r/all's posts: a million a day would push the others out of `seen`, and
    # posts-all's newest id guards them. (Its posts that reddit's search finds but
    # names_any doesn't may count again in r/_search after a restart, a handful.)
    recent = client.query(
        "SELECT id FROM items WHERE platform = {platform:String} AND ("
        "doc_type = 'post' AND channel != {sample:String} "
        "AND created_at > now() - INTERVAL 40 HOUR "
        "OR doc_type = 'comment' AND ingested_at > now() - INTERVAL 30 MINUTE)",
        parameters={"platform": PLATFORM, "sample": SAMPLE},
    ).result_rows
    for (fullname,) in recent:
        seen.add(fullname)
    log.info("restored %d recently ingested ids", len(recent))


async def usable_subreddits(reddit: RedditClient, subreddits: tuple[str, ...]) -> list[str]:
    """Drops subreddits that can't be read. A multireddit silently ignores them."""
    usable = []
    for subreddit in subreddits:
        try:
            problem = await reddit.subreddit_problem(subreddit)
        except RedditError as error:
            log.warning("couldn't check r/%s (%s), tracking it anyway", subreddit, error)
            problem = None
        if problem:
            log.warning("not tracking r/%s: %s", subreddit, problem)
        else:
            usable.append(subreddit)
    return usable


class RedditSource:
    platform = PLATFORM

    def __init__(self, config: Config, reddit: RedditClient):
        self._config = config
        self._reddit = reddit
        self._seen = RecentKeys(SEEN_CAPACITY)
        self._requests_at_report = 0
        self._subreddits = tuple(map(subreddit_of, config.tracked(PLATFORM)))
        self._tracked = frozenset(self._subreddits)
        # posts whose comment tree was fetched; after a restart a tree may be fetched again,
        # its comments stored before are recognized then
        self._trees_done: set[str] = set()
        # an untracked post naming a watched product counts in r/_search, whichever feed
        # finds it: r/all's posts find most of the search's results first
        aliases = [alias for names in config.radar.searches.values() for alias in names]
        self._products = names_any(aliases) if aliases else None
        self.scheduler: FeedScheduler | None = None

    @classmethod
    def from_environ(cls, config: Config) -> RedditSource:
        client_id, secret, user_agent = reddit_credentials()
        reddit = RedditClient(
            client_id, secret, user_agent, config.platforms.reddit.requests_per_minute
        )
        return cls(config, reddit)

    async def run(self, sink: Sink, stop: asyncio.Event) -> None:
        async with self._reddit:
            subreddits = await usable_subreddits(self._reddit, self._subreddits)
            feeds = build_feeds(self._config, subreddits)
            await asyncio.to_thread(seed_state, sink.client, feeds, self._seen)
            self.scheduler = FeedScheduler(feeds, self._config)
            log.info(
                "tracking %d subreddits in %d feeds: %s",
                len(subreddits),
                len(feeds),
                ", ".join(f"{feed.name} ({len(feed.subreddits)} subs)" for feed in feeds),
            )

            tasks = [asyncio.create_task(self._report_forever())]
            if self._config.radar.searches:
                tasks.append(asyncio.create_task(self._trees_forever(sink)))
            try:
                await self._poll_forever(sink, stop)
            finally:
                for task in tasks:
                    task.cancel()

    async def _poll_forever(self, sink: Sink, stop: asyncio.Event) -> None:
        """Starts each feed's polls when they're due, without waiting for other feeds' answers
        (the client paces the requests)."""
        assert self.scheduler is not None
        polls: dict[asyncio.Task[object], Feed] = {}
        stopped: asyncio.Task[object] = asyncio.create_task(stop.wait())
        try:
            while not stop.is_set():
                now = time.monotonic()
                for feed in self.scheduler.due(now):
                    self.scheduler.start(feed, now)
                    polls[asyncio.create_task(self.poll(feed, sink))] = feed
                due_at = self.scheduler.next_due_at()
                done, _ = await asyncio.wait(
                    {stopped, *polls},
                    timeout=None if due_at is None else max(due_at - time.monotonic(), 0.0),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done - {stopped}:
                    self.scheduler.finish(polls.pop(task))
                    # an unexpected error stops the source, as when polls ran one at a time
                    task.result()
        finally:
            # an unanswered poll hands nothing to the sink, a restart polls its feed again
            for task in (stopped, *polls):
                task.cancel()

    async def poll(self, feed: Feed, sink: Sink) -> None:
        assert self.scheduler is not None
        polled_at = datetime.now(UTC)
        # the next poll is scheduled from the start of this one, a slow response (r/all
        # takes seconds) shouldn't stretch the interval
        started = time.monotonic()
        # what this feed's polls had found when this one started is counted; another poll
        # may answer first, the ids seen recently tell what's new beyond it
        counted_up_to = feed.newest_id
        try:
            items = await self._reddit.listing(feed.path, feed.params)
        except RedditError as error:
            self.scheduler.record_failure(feed, time.monotonic(), error.retry_after)
            log.warning("polling %s failed: %s", feed.name, error)
            sink.add_poll(self._poll(feed, polled_at, error.status, 0, 0, False, 0))
            return

        new_items = 0
        for item in items:
            # the sample's polls overlap too, and its listing shows only a second or two:
            # the ids seen recently tell what's new there
            if feed.complete:
                if counted_up_to is not None and item.id36 <= counted_up_to:
                    continue
            # search results aren't strictly newest first (posts are indexed with a delay),
            # and those in tracked subreddits are in their feeds already
            elif feed.search is not None and item.subreddit in self._tracked:
                continue
            new_items += self.ingest(item, sink, self.channel_of(item, feed))

        outcome = self.scheduler.record_success(feed, items, started)
        if outcome.gap:
            log.info("%s: possible gap, polling more often", feed.name)
        sink.add_poll(
            self._poll(feed, polled_at, 200, len(items), new_items, outcome.gap, outcome.id_span)
        )

    def channel_of(self, item: RedditItem, feed: Feed) -> str | None:
        """r/_search for the search's results and every other untracked post naming a
        watched product, otherwise None: to_item decides."""
        if feed.search is not None:
            return SEARCH
        if (
            self._products is not None
            and item.doc_type == "post"
            and item.subreddit not in self._tracked
            and self._products.search(item.text)
        ):
            return SEARCH
        return None

    def ingest(self, item: RedditItem, sink: Sink, channel: str | None = None) -> bool:
        """Hands an item to the sink unless it's too old or seen before. Whether it was new
        (a skipped item is new too)."""
        if item.created_utc < time.time() - MAX_ITEM_AGE or not self._seen.add(item.fullname):
            return False
        sink.add(to_item(item, self._config, channel))
        return True

    async def _trees_forever(self, sink: Sink) -> None:
        while True:
            await asyncio.sleep(TREE_CHECK_INTERVAL)
            try:
                await self.fetch_trees(sink)
            except Exception:
                # ClickHouse unreachable for a moment: the next check catches up
                log.exception("fetching comment trees failed")

    async def fetch_trees(self, sink: Sink) -> None:
        """The comment trees of posts the search found that ask or tell about a switch,
        once, when they are radar.tree_after_hours old (docs/CHURN-RADAR.md §2.2)."""
        radar = self._config.radar
        due = await asyncio.to_thread(due_trees, sink.client, radar, self._trees_done)
        new_comments = 0
        for fullname in due:
            self._trees_done.add(fullname)
            try:
                comments = await self._reddit.comment_tree(fullname.removeprefix("t3_"))
            except RedditError as error:
                log.warning("comment tree of %s failed: %s", fullname, error)
                continue
            stored = await asyncio.to_thread(
                stored_ids, sink.client, [comment.fullname for comment in comments]
            )
            new_comments += sum(
                self.ingest(comment, sink, SEARCH)
                for comment in comments
                if comment.fullname not in stored
            )
        if due:
            log.info("comment trees: %d posts, %d new comments", len(due), new_comments)

    def _poll(
        self,
        feed: Feed,
        polled_at: datetime,
        status: int,
        items: int,
        new_items: int,
        gap: bool,
        id_span: int,
    ) -> Poll:
        remaining = self._reddit.ratelimit.remaining
        return Poll(
            ts=polled_at,
            platform=PLATFORM,
            feed=feed.name,
            kind=feed.kind,
            sample=feed.sample,
            status=status,
            items=items,
            new_items=new_items,
            gap=gap,
            id_span=id_span,
            latency_ms=round(self._reddit.last_latency * 1000),
            interval_s=feed.interval,
            rate=feed.rate or 0.0,
            ratelimit_remaining=remaining if remaining is not None else -1,
        )

    async def _report_forever(self) -> None:
        while True:
            await asyncio.sleep(REPORT_INTERVAL)
            self.report()

    def report(self) -> None:
        assert self.scheduler is not None
        requests = self._reddit.requests - self._requests_at_report
        self._requests_at_report = self._reddit.requests
        log.info(
            "reddit: %d requests/min, %.0f left in window",
            requests,
            self._reddit.ratelimit.remaining or 0,
        )
        for feed in self.scheduler.feeds:
            stats = feed.stats
            log.info(
                "  %-22s polls %3d  items %5d  gaps %d  errors %d  every %5.1fs  ~%.0f/min",
                feed.name,
                stats.polls,
                stats.items,
                stats.gaps,
                stats.errors,
                feed.interval,
                (feed.rate or 0) * 60,
            )
            feed.stats = type(stats)()
