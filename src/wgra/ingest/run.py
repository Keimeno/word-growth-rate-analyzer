"""The ingester: polls reddit forever and writes what it finds into ClickHouse."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import Counter
from datetime import UTC, datetime

from clickhouse_connect.driver.client import Client

from wgra.config import Config, Env
from wgra.ingest.feeds import Feed, FeedScheduler, build_feeds
from wgra.ingest.pipeline import Processor, RecentKeys
from wgra.ingest.writer import Writer
from wgra.reddit import RedditClient, RedditError
from wgra.store import connect, migrate

log = logging.getLogger(__name__)

# items older than this are ignored. They may have been counted before and since
# expired from the raw items table (48h), so we can't tell whether they're new.
MAX_ITEM_AGE = 36 * 3600
# ids of items seen recently, to catch the r/all sample overlapping tracked feeds
SEEN_CAPACITY = 300_000
REPORT_INTERVAL = 60.0


def write_groups(client: Client, config: Config) -> None:
    client.command("TRUNCATE TABLE subreddit_groups")
    client.insert(
        "subreddit_groups", config.group_memberships(), column_names=["group_name", "subreddit"]
    )


def seed_state(client: Client, feeds: list[Feed], seen: RecentKeys) -> None:
    """Restores what a previous run already ingested, so a restart doesn't count it twice."""
    newest = client.query(
        "SELECT source, subreddit, argMax(id, created_at) FROM items "
        "WHERE created_at > now() - INTERVAL 40 HOUR GROUP BY source, subreddit"
    ).result_rows
    newest_id = {(source, sub): int(fullname[3:], 36) for source, sub, fullname in newest}
    for feed in feeds:
        source = "comment" if feed.kind == "comments" else "post"
        ids = [newest_id[source, sub] for sub in feed.subreddits if (source, sub) in newest_id]
        if ids and not feed.background:
            feed.newest_id = max(ids)

    recent = client.query(
        "SELECT id FROM items WHERE source = 'post' AND created_at > now() - INTERVAL 40 HOUR "
        "OR source = 'comment' AND ingested_at > now() - INTERVAL 30 MINUTE"
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


class Ingester:
    def __init__(self, config: Config, env: Env, reddit: RedditClient, client: Client):
        self._config = config
        self._reddit = reddit
        self._client = client
        self._processor = Processor(config, env.author_hash_key)
        self._writer = Writer(client)
        self._seen = RecentKeys(SEEN_CAPACITY)
        self._skipped: Counter[str] = Counter()
        self._requests_at_report = 0
        self.scheduler: FeedScheduler | None = None

    async def run(self, stop: asyncio.Event) -> None:
        subreddits = await usable_subreddits(self._reddit, self._config.subreddits)
        feeds = build_feeds(self._config, subreddits)
        await asyncio.to_thread(seed_state, self._client, feeds, self._seen)
        self.scheduler = FeedScheduler(feeds, self._config)
        log.info(
            "tracking %d subreddits in %d feeds: %s",
            len(subreddits),
            len(feeds),
            ", ".join(f"{feed.name} ({len(feed.subreddits)} subs)" for feed in feeds),
        )

        tasks = [
            asyncio.create_task(self._writer.run()),
            asyncio.create_task(self._report_forever()),
        ]
        try:
            while not stop.is_set():
                feed = self.scheduler.next_feed()
                if (delay := feed.next_poll_at - time.monotonic()) > 0:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), delay)
                    continue
                await self.poll(feed)
        finally:
            for task in tasks:
                task.cancel()
            if await self._writer.flush():
                log.info("stopped, all buffered rows are written")
            else:
                log.error("final flush failed, the last few seconds of data are lost")

    async def poll(self, feed: Feed) -> None:
        assert self.scheduler is not None
        polled_at = datetime.now(UTC)
        # the next poll is scheduled from the start of this one, a slow response (r/all
        # takes seconds) shouldn't stretch the interval
        started = time.monotonic()
        try:
            items = await self._reddit.listing(feed.path)
        except RedditError as error:
            self.scheduler.record_failure(feed, time.monotonic(), error.retry_after)
            log.warning("polling %s failed: %s", feed.name, error)
            self._writer.add_poll(self._poll_row(feed, polled_at, error.status, 0, 0, False, 0))
            return

        oldest_allowed = time.time() - MAX_ITEM_AGE
        new_items = 0
        for item in items:
            if feed.newest_id is not None and item.id36 <= feed.newest_id:
                continue
            if item.created_utc < oldest_allowed or not self._seen.add(item.fullname):
                continue
            new_items += 1
            if reason := self._processor.skip_reason(item):
                self._skipped[reason] += 1
                continue
            self._writer.add(self._processor.process(item))

        outcome = self.scheduler.record_success(feed, items, started)
        if outcome.gap:
            log.info("%s: possible gap, polling more often", feed.name)
        self._writer.add_poll(
            self._poll_row(
                feed, polled_at, 200, len(items), new_items, outcome.gap, outcome.id_span
            )
        )

    def _poll_row(
        self,
        feed: Feed,
        polled_at: datetime,
        status: int,
        items: int,
        new_items: int,
        gap: bool,
        id_span: int,
    ) -> tuple[object, ...]:
        return (
            polled_at,
            feed.name,
            feed.kind,
            feed.background,
            status,
            items,
            new_items,
            gap,
            id_span,
            round(self._reddit.last_latency * 1000),
            feed.interval,
            feed.rate or 0.0,
            self._reddit.ratelimit.remaining
            if self._reddit.ratelimit.remaining is not None
            else -1,
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
            "%d requests/min, %.0f left in window | stored %d items, %d term rows | skipped %s",
            requests,
            self._reddit.ratelimit.remaining or 0,
            self._writer.inserted["items"],
            self._writer.inserted["term_events"],
            dict(self._skipped) or "nothing",
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


async def run_ingest(config: Config, env: Env, stop: asyncio.Event) -> None:
    client = connect(env)
    if applied := migrate(client):
        log.info("applied migrations: %s", ", ".join(applied))
    write_groups(client, config)

    async with RedditClient(
        env.reddit_client_id,
        env.reddit_client_secret,
        env.reddit_user_agent,
        config.ingest.requests_per_minute,
    ) as reddit:
        await Ingester(config, env, reddit, client).run(stop)
