"""The ingester: runs every enabled source forever and writes what they find into
ClickHouse, through one shared pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Sequence

from clickhouse_connect.driver.client import Client

from undercurrent.config import Config, Env
from undercurrent.ingest.pipeline import Processor
from undercurrent.ingest.writer import Writer
from undercurrent.sources.base import Item, Poll, Source
from undercurrent.store import connect, migrate

log = logging.getLogger(__name__)

REPORT_INTERVAL = 60.0
CHANNEL_COLUMNS = ("channel", "platform", "language", "analyzed", "background")


def write_channels(client: Client, config: Config) -> None:
    """The channels and groups of config.yaml, for the detectors, dashboards and queries."""
    client.command("TRUNCATE TABLE channels")
    client.insert(
        "channels",
        [
            (channel.id, channel.platform, channel.language, channel.analyzed, channel.background)
            for channel in config.channels()
        ],
        column_names=list(CHANNEL_COLUMNS),
    )
    client.command("TRUNCATE TABLE channel_groups")
    client.insert(
        "channel_groups", config.group_memberships(), column_names=["group_name", "channel"]
    )


class Pipeline:
    """The sink every source hands its items and polls to: the copypasta filter, terms,
    intents and the author hash (Processor), and buffered writes (Writer)."""

    def __init__(self, config: Config, author_hash_key: bytes, client: Client):
        self.client = client
        self._processor = Processor(config, author_hash_key)
        self.writer = Writer(client)
        self.skipped: Counter[str] = Counter()

    def add(self, item: Item) -> bool:
        if reason := self._processor.skip_reason(item):
            self.skipped[reason] += 1
            return False
        self.writer.add(self._processor.process(item))
        return True

    def add_poll(self, poll: Poll) -> None:
        self.writer.add_poll(poll)

    def report(self) -> None:
        log.info(
            "stored %d items, %d term rows | skipped %s",
            self.writer.inserted["items"],
            self.writer.inserted["term_events"],
            dict(self.skipped) or "nothing",
        )


def source_for(platform: str, config: Config) -> Source:
    from undercurrent.sources.reddit.source import RedditSource

    if platform == RedditSource.platform:
        return RedditSource.from_environ(config)
    raise ValueError(f"no source for the platform {platform!r}")


async def _report_forever(pipeline: Pipeline) -> None:
    while True:
        await asyncio.sleep(REPORT_INTERVAL)
        pipeline.report()


async def run_sources(sources: Sequence[Source], pipeline: Pipeline, stop: asyncio.Event) -> None:
    """Runs the sources until `stop` is set, then writes what's buffered."""
    tasks = [
        asyncio.create_task(pipeline.writer.run()),
        asyncio.create_task(_report_forever(pipeline)),
    ]
    try:
        await asyncio.gather(*(source.run(pipeline, stop) for source in sources))
    finally:
        for task in tasks:
            task.cancel()
        if await pipeline.writer.flush():
            log.info("stopped, all buffered rows are written")
        else:
            log.error("final flush failed, the last few seconds of data are lost")


async def run_ingest(
    config: Config, env: Env, stop: asyncio.Event, platforms: Sequence[str] | None = None
) -> None:
    """Collects from `platforms`, by default every enabled one."""
    platforms = config.platforms.enabled() if platforms is None else platforms
    if not platforms:
        raise RuntimeError("no platform to collect from, see platforms in config.yaml")
    sources = [source_for(platform, config) for platform in platforms]
    client = connect(env)
    if applied := migrate(client):
        log.info("applied migrations: %s", ", ".join(applied))
    write_channels(client, config)
    log.info("collecting from %s", ", ".join(platforms))
    await run_sources(sources, Pipeline(config, env.author_hash_key, client), stop)
