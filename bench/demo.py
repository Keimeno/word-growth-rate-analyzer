"""The demo database: a complete, deterministic history for the web dashboard.

Writes into a ClickHouse database of its own, never the live one (docs/WEB-DASHBOARD.md
§10.2). `seed` drops and recreates the named database (its name must contain "demo"),
migrates it, removes every table's TTL (the history ends at a fixed time in the past and
must stay), then writes:

1. Counts: `scope_hourly`, `term_hourly` and `term_daily` for the channels of config.yaml
   at about a tenth of production volume (18k comments a day in the tracked subreddits,
   40k in the r/all sample). The vocabulary is bench/demo_words.txt: function words at
   their usual shares, then everyday words Zipf-like like bench/synthetic.py's, each
   group's topical words common in its channels, drawn with numpy's seeded random numbers
   (their noise damped, so nothing trends by chance). 120 days of hourly counts, 400 of
   daily ones (documents per hour all 400).
2. The planted stories below as generated sentences, through the ingester's Processor:
   the last 48 hours as `items` and `term_events` (the materialized views count them),
   everything older straight into the counts.
3. `polls` of every feed for the last 48 hours.
4. The real code on top, nothing sent anywhere (the Analyzer's ntfy is an outbox that
   only keeps the messages; `notifications` gets the rows of what it decided to send, at
   the simulated time): the long-term detector and its weekly report as of the last 6
   Mondays; the short-term detector once a day at 12:00 from 90 days before the as-of, in
   the tracked channels and the 24h horizon (the history the lead–lag layer makes events
   of); then the live loop for the last 30 days: the lead–lag layer at 01:00 (the first
   run is the backfill of events, onsets and edges), `Analyzer.run_once` (all scopes and
   horizons, alerts, digests, forecasts) at 12:00, and every hour of the last 24 hours.

    docker run -d --name wgra-dev-bench-clickhouse --cpus 4 --memory 8g \\
        -p 127.0.0.1:3617:8123 -e CLICKHOUSE_USER=wgra -e CLICKHOUSE_PASSWORD=bench \\
        -v "$PWD/clickhouse/wgra.xml:/etc/clickhouse-server/config.d/wgra.xml:ro" \\
        clickhouse/clickhouse-server:26.8
    export CLICKHOUSE_PORT=3617 CLICKHOUSE_PASSWORD=bench CLICKHOUSE_USER=wgra
    uv run python bench/demo.py seed --database wgra_demo            # about 15 minutes
    uv run python bench/demo.py seed --database wgra_demo --small    # about 1.5 minutes
    UNDERCURRENT_NOW=2026-11-01T12:00:00Z CLICKHOUSE_DB=wgra_demo uv run wgra web

`--small` is for CI: the channels of tech and pkm, 52 days of hourly counts (the
detector needs 29 days of them before its first run, the lead–lag layer three weeks of
events before it has edges) and 120 of daily ones (13-week long-term trends), the
detector daily from 23 days before, the live loop for the last 3 days with hourly runs
for the last 12 hours, long-term as of the last 3 Mondays. Everything ends at `--as-of`
(default 2026-11-01T12:00Z, a Sunday): the API shows it with UNDERCURRENT_NOW set to it.
The same seed and as-of give the same rows, apart from `updated_at` and
`schema_migrations`.

The planted stories, relative to the as-of A (channels outside --small's groups are
left out there):

* Cascades for the lead–lag layer: a new term bursts in a leader and, after a lag, in its
  followers; a cascade per leader every 6 days (--small: 1.5) from 86 days (22) before
  A, each with a new name, followed in 80–85% of them: r/localllama → r/singularity
  after 10–20 h and → r/all after 40–70 h (half of them), model names like
  "kestrel-7b"; r/hardware → r/buildapc after 4–10 h, "cobalt-x5"; r/selfhosted →
  r/homelab after 14–30 h, "harborbox"; r/obsidianmd → r/pkms after 20–40 h,
  "quill-sync"; r/wallstreetbets → r/stocks after 3–8 h, tickers like "$OSPR" (the term
  "ospr"); r/pcgaming → r/games after 24–48 h, "emberfall". The last cascade of each
  leader is fixed (LAST_CASCADES): "lumen-8b" in r/localllama at A−30h (r/singularity at
  A−16h, r/all at A+10h: a pending forecast), "vertex-x7" in r/hardware at A−52h
  (r/buildapc at A−45h), "summitbox" in r/selfhosted at A−20h (r/homelab at A+6h),
  "prism-sync" in r/obsidianmd at A−10h (r/pkms at A+20h), "rift" in r/wallstreetbets at
  A−40h (r/stocks at A−35h), "zephyrfall" in r/pcgaming at A−70h (r/games at A−34h).
* Long-term, as shares per 1,000 documents of a group's channels, by weeks before the
  Monday M of A's week: "vibe coding" emerging in tech (0.5 at M−13w, 30% more every
  week, none before); "agent memory" emerging in tech (0.2, 12% more a week from M−26w);
  "local inference" mainstreaming in tech (2 at M−57w, 2.7% more a week); "metaverse"
  fading in tech (6 at M−57w, 3.4% less a week); "web3" fading in tech (6, 20% less a
  week from M−13w); "cloud outage" a one-off in tech (0.3, 15 times that in weeks M−2w
  and M−1w); outside --small "solar flare" a one-off in science (2, 15 times in week
  M−3w), "rate cut" mainstreaming in finance (2, 3% more a week) and "blockchain gaming"
  fading in gaming (5, 5% less a week).
* Intents every day (CHATTER): switches between note apps in pkm and r/all ("notion →
  obsidian" 2.6 a day, "evernote → notion" 1.5, "evernote → obsidian" 0.8, "obsidian →
  notion" 0.5, …), alternatives, considering, needs ("need: syncs notes", "need: export
  my notes", "need: track my sleep", …), and elsewhere "windows → linux", "chatgpt →
  claude", "plex → jellyfin" and more. A Notion outage at A−20h: "complaint: notion" in
  r/notion (45), r/all (25) and other pkm channels within 5 hours, then alternatives to
  Notion, "considering: notion → obsidian" and switches away from it. An Evernote price
  hike at A−20d: "complaint: evernote" for 3 days, then twice the switches away from
  Evernote for 2 weeks.
* A coordinated launch: "lumina x1" in 12 tech, science and news channels and r/all
  within two hours of A−26h, trending in tech with breadth.
* Collection: the comment feeds fail for 25 minutes from A−9h, the poll after finds a
  gap, and that hour counts 45% fewer comments.
"""

from __future__ import annotations

import argparse
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from clickhouse_connect.driver.client import Client
from dotenv import load_dotenv
from numpy.typing import NDArray

from wgra.config import Config, Env, load_config
from wgra.detect.long_term import week_start
from wgra.detect.run import NOTIFICATION_COLUMNS, Analyzer
from wgra.detect.short_term import CHANNEL, Detector, load_scopes, next_hour, write_trends
from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor
from wgra.ingest.run import write_channels
from wgra.notify.ntfy import Message, Ntfy
from wgra.sources.base import POLL_COLUMNS, Poll
from wgra.sources.reddit.channels import PLATFORM, SAMPLE, subreddit_of
from wgra.sources.reddit.feeds import build_feeds
from wgra.sources.reddit.models import RedditItem
from wgra.sources.reddit.source import to_item
from wgra.store import connect, migrate
from wgra.text import extract_terms
from wgra.text.lexicon import stopwords

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
DEFAULT_AS_OF = datetime(2026, 11, 1, 12, tzinfo=UTC)
SEED = 20261101
WORDS = Path(__file__).with_name("demo_words.txt")
AUTHOR_HASH_KEY = b"undercurrent demo"

# the vocabulary's law, like bench/synthetic.py's but smooth at the top and with fewer terms
# per document: the share of documents mentioning the term of rank r is
# min(0.12, 40 / (r + 75)^1.34), about 16 terms per document
A, S, RANK_OFFSET, MAX_SHARE = 40.0, 1.34, 75, 0.12
SAMPLE_PER_DAY = 40_000
# the background's counts vary 70% as much as binomial counts would
NOISE = 0.7
# comments a day per tracked channel, about a tenth of production
VOLUMES = {
    "r/technology": 1400,
    "r/programming": 350,
    "r/hardware": 300,
    "r/gadgets": 200,
    "r/localllama": 350,
    "r/machinelearning": 120,
    "r/artificial": 150,
    "r/openai": 300,
    "r/claudeai": 250,
    "r/singularity": 500,
    "r/webdev": 250,
    "r/experienceddevs": 200,
    "r/cscareerquestions": 300,
    "r/apple": 450,
    "r/android": 350,
    "r/linux": 250,
    "r/selfhosted": 250,
    "r/homelab": 200,
    "r/buildapc": 450,
    "r/science": 400,
    "r/space": 250,
    "r/futurology": 300,
    "r/news": 1500,
    "r/worldnews": 2000,
    "r/europe": 700,
    "r/investing": 300,
    "r/stocks": 400,
    "r/wallstreetbets": 1200,
    "r/personalfinance": 350,
    "r/cryptocurrency": 450,
    "r/economics": 200,
    "r/gaming": 1300,
    "r/games": 600,
    "r/pcgaming": 500,
    "r/de": 700,
    "r/finanzen": 300,
    "r/de_edv": 40,
    "r/notion": 60,
    "r/obsidianmd": 120,
    "r/evernote": 20,
    "r/onenote": 25,
    "r/logseq": 30,
    "r/pkms": 25,
    "r/notetaking": 30,
    "r/zettelkasten": 20,
}
DEFAULT_VOLUME = 200
TOKENS_PER_DOC = 31
WEEKEND = 0.9
# subreddits the r/all sample finds its planted documents in
SAMPLED_SUBREDDITS = ("AskReddit", "productivity", "NoStupidQuestions", "lifehacks", "apps")
# the ingestion gap: the comment feeds fail for a while, and the hour loses documents
GAP_BEFORE = timedelta(hours=9)
GAP_LENGTH = timedelta(minutes=25)
GAP_LOSS = 0.45
# documents of the last 48 hours are items, like the live table keeps them
ITEM_HOURS = 48
INGEST_DELAY = timedelta(seconds=20)


@dataclass(frozen=True)
class Size:
    name: str
    hourly_days: int
    daily_days: int
    # the configured groups whose channels are seeded, None for all
    groups: tuple[str, ...] | None
    # the detector's history for the lead–lag layer's events: every history_every hours
    # from this many days before the as-of, the 24h horizon in the tracked channels
    history_days: int
    history_every: int
    # then the live loop: the lead–lag layer at 01:00 and the analyzer at 12:00 every day
    # from this many days before the as-of, and the analyzer every hour of the last hours
    live_days: int
    hourly_runs: int
    # long-term runs as of the last this many Mondays
    mondays: int
    # days between two cascades of a leader, and the first cascade's days before the as-of
    cascade_every: float
    cascade_from: int


# The detector needs 29 days of hourly counts before its first run (a window and the
# reference period). Edges need events whose span (17 days) is over, and 5 of each pair.
FULL = Size("full", 120, 400, None, 90, 24, 30, 24, 6, 6.0, 86)
SMALL = Size("small", 52, 120, ("tech", "pkm"), 23, 24, 3, 12, 3, 1.5, 22)


# --- the vocabulary ---------------------------------------------------------------------

TOPICS = ("tech", "science", "news", "finance", "gaming", "pkm")


def load_words(path: Path = WORDS) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], [])
        elif current is not None and line not in current:
            current.append(line)
    return sections


@dataclass
class Vocabulary:
    """Every background term, and each channel's terms by rank with their shares."""

    terms: list[tuple[str, str]] = field(default_factory=list)
    index: dict[tuple[str, str], int] = field(default_factory=dict)

    def ids(self, terms: Iterable[tuple[str, str]]) -> NDArray[np.int64]:
        ids = []
        for term in terms:
            if term not in self.index:
                self.index[term] = len(self.terms)
                self.terms.append(term)
            ids.append(self.index[term])
        return np.array(ids, dtype=np.int64)


def ranked(*layers: tuple[Sequence[tuple[str, str]], float, float]) -> list[tuple[str, str]]:
    """Terms in rank order: each layer's terms at positions first, first + every, …"""
    keyed = []
    for terms, first, every in layers:
        keyed += [(first + every * number, number, term) for number, term in enumerate(terms)]
    seen: set[tuple[str, str]] = set()
    out = []
    for _, _, term in sorted(keyed):
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out


def channel_terms(
    channel: str, config: Config, words: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """A channel's vocabulary by rank: its language's everyday words, its groups' topical
    words among the most common, then phrases and linked sites."""

    def kind(section: str, kind: str = "word") -> list[tuple[str, str]]:
        return [(kind, word) for word in words.get(section, [])]

    phrases, domains = kind("phrases", "phrase"), kind("domains", "domain")
    if channel == SAMPLE:
        topical = [term for topic in TOPICS for term in kind(topic)]
        return ranked(
            (kind("general"), 0, 1),
            (topical, 4, 2.5),
            (phrases, 30, 9),
            (domains, 50, 40),
            (kind("de"), 300, 4),
        )
    groups = [group for group, members in config.groups.items() if channel in members]
    topical = [term for group in groups if group in TOPICS for term in kind(group)]
    if config.language(channel) == "de":
        extra = kind("tech") if channel == "r/de_edv" else kind("finance")
        if channel == "r/de":
            extra = kind("news")
        return ranked(
            (kind("de"), 0, 1), (extra, 6, 7), (kind("general"), 150, 3), (domains, 80, 40)
        )
    return ranked((kind("general"), 0, 1), (topical, 5, 6), (phrases, 30, 11), (domains, 50, 37))


def stopword_shares(count: int) -> NDArray[np.float64]:
    """Function words: "the" in 60% of documents, then 5% fewer for each."""
    return 0.6 * 0.95 ** np.arange(count, dtype=np.float64)


def shares(count: int) -> NDArray[np.float64]:
    """The share of documents mentioning the term of each rank, from 12% down."""
    ranks = np.arange(1, count + 1, dtype=np.float64)
    return np.minimum(MAX_SHARE, A / (ranks + RANK_OFFSET) ** S)


# --- time ------------------------------------------------------------------------------


def diurnal(language: str) -> NDArray[np.float64]:
    """Activity by hour of the day (UTC), averaging 1: evenings in America, or Europe."""
    peak = 11 if language == "de" else 17
    return 1 + 0.45 * np.cos(2 * np.pi * (np.arange(24) - peak) / 24)


def weekday_factor(day: date) -> float:
    return WEEKEND if day.weekday() >= 5 else 1.0


@dataclass(frozen=True)
class Plan:
    """What gets seeded: the size, the channels and the calendar."""

    size: Size
    config: Config
    as_of: datetime
    seed: int

    @property
    def hourly_start(self) -> datetime:
        return datetime.combine(
            self.as_of.date() - timedelta(days=self.size.hourly_days), datetime.min.time(), UTC
        )

    @property
    def daily_start(self) -> datetime:
        return datetime.combine(
            self.as_of.date() - timedelta(days=self.size.daily_days), datetime.min.time(), UTC
        )

    @property
    def items_start(self) -> datetime:
        return self.as_of - timedelta(hours=ITEM_HOURS)

    @property
    def gap_hour(self) -> datetime:
        return (self.as_of - GAP_BEFORE).replace(minute=0)

    @property
    def tracked(self) -> list[str]:
        return list(self.config.tracked(PLATFORM))

    @property
    def channels(self) -> list[str]:
        """The analyzed channels: the tracked ones and the r/all sample."""
        return [*self.tracked, SAMPLE]

    def volume(self, channel: str) -> int:
        return SAMPLE_PER_DAY if channel == SAMPLE else VOLUMES.get(channel, DEFAULT_VOLUME)

    def rng(self, *purpose: int) -> np.random.Generator:
        return np.random.default_rng([self.seed, *purpose])


def demo_config(config: Config, size: Size) -> Config:
    if size.groups is None:
        return config
    return replace(config, groups={group: config.groups[group] for group in size.groups})


# --- the background counts ---------------------------------------------------------------

STAGING = {
    "demo_hourly": "hour UInt32, channel UInt16, term UInt32, docs UInt32",
    "demo_daily": "day UInt32, channel UInt16, term UInt32, docs UInt32",
    "demo_scope": "hour UInt32, channel UInt16, docs UInt32",
    "demo_events": (
        "hour DateTime('UTC'), channel String, doc_type String, kind String, term String, "
        "author_hash UInt64, occurrences UInt32"
    ),
    "demo_docs": (
        "hour DateTime('UTC'), channel String, doc_type String, author_hash UInt64, tokens UInt32"
    ),
}
CHUNK_ROWS = 4_000_000


class Staged:
    """Numpy columns collected for a staging table, inserted in chunks."""

    def __init__(self, client: Client, table: str, columns: Sequence[str]):
        self._client = client
        self._table = table
        self._columns = list(columns)
        self._parts: list[list[NDArray[Any]]] = []
        self._rows = 0
        self.inserted = 0

    def add(self, *columns: NDArray[Any]) -> None:
        self._parts.append(list(columns))
        self._rows += len(columns[0])
        if self._rows >= CHUNK_ROWS:
            self.flush()

    def flush(self) -> None:
        if not self._parts:
            return
        # numpy columns, which clickhouse-connect takes as they are
        data: Any = [np.concatenate(parts) for parts in zip(*self._parts, strict=True)]
        self._client.insert(self._table, data, column_names=self._columns, column_oriented=True)
        self.inserted += len(data[0])
        self._parts, self._rows = [], 0


def damped(
    rng: np.random.Generator, docs: NDArray[np.int64], share: NDArray[np.float64]
) -> NDArray[np.int64]:
    """Documents mentioning each term (columns) per hour or day (rows): binomial, with the
    noise damped (NOISE of its spread), so the background doesn't trend by chance. At full
    noise a term of a small channel trends with z ≥ 5 now and then, starting an event the
    lead–lag layer would learn chance edges from."""
    expected = docs[:, None] * share[None, :]
    counts = rng.binomial(docs[:, None], share[None, :])
    return np.rint(expected + NOISE * (counts - expected)).clip(0).astype(np.int64)


def write_background(client: Client, plan: Plan, words: dict[str, list[str]]) -> Vocabulary:
    """The everyday vocabulary of every channel: documents per hour, and per hour (the last
    hourly_days) or per day (before) the documents mentioning each term."""
    vocabulary = Vocabulary()
    hourly = Staged(client, "demo_hourly", ["hour", "channel", "term", "docs"])
    daily = Staged(client, "demo_daily", ["day", "channel", "term", "docs"])
    scope = Staged(client, "demo_scope", ["hour", "channel", "docs"])
    hourly_start = int(plan.hourly_start.timestamp())
    hours = int((plan.as_of - plan.hourly_start) / HOUR)
    old_days = (plan.hourly_start - plan.daily_start).days
    hour_times = [plan.hourly_start + HOUR * number for number in range(hours)]
    gap = int((plan.gap_hour - plan.hourly_start) / HOUR)
    for number, channel in enumerate(plan.channels):
        rng = plan.rng(1, number)
        terms = channel_terms(channel, plan.config, words)
        share = shares(len(terms))
        if plan.config.language(channel) != "de":
            function_words = [("word", word) for word in words["stopwords"]]
            terms = function_words + terms
            share = np.concatenate([stopword_shares(len(function_words)), share])
        ids = vocabulary.ids(terms)
        per_hour = diurnal(plan.config.language(channel)) * plan.volume(channel) / 24
        expected = np.array(
            [per_hour[moment.hour] * weekday_factor(moment.date()) for moment in hour_times]
        )
        docs = rng.poisson(expected)
        if channel != SAMPLE and 0 <= gap < hours:
            docs[gap] = round(docs[gap] * (1 - GAP_LOSS))
        counts = damped(rng, docs, share)
        rows, columns = np.nonzero(counts)
        hourly.add(
            (hourly_start + 3600 * rows).astype(np.uint32),
            np.full(len(rows), number, np.uint16),
            ids[columns].astype(np.uint32),
            counts[rows, columns].astype(np.uint32),
        )
        scope.add(
            (hourly_start + 3600 * np.arange(hours)).astype(np.uint32),
            np.full(hours, number, np.uint16),
            docs.astype(np.uint32),
        )
        if old_days:
            days = [plan.daily_start.date() + timedelta(days=offset) for offset in range(old_days)]
            day_docs = rng.poisson(
                np.array([plan.volume(channel) * weekday_factor(day) for day in days])
            )
            counts = damped(rng, day_docs, share)
            rows, columns = np.nonzero(counts)
            day_start = int(plan.daily_start.timestamp())
            daily.add(
                (day_start + 86400 * rows).astype(np.uint32),
                np.full(len(rows), number, np.uint16),
                ids[columns].astype(np.uint32),
                counts[rows, columns].astype(np.uint32),
            )
            split = np.array([rng.multinomial(n, per_hour / per_hour.sum()) for n in day_docs])
            scope.add(
                (day_start + 3600 * np.arange(old_days * 24)).astype(np.uint32),
                np.full(old_days * 24, number, np.uint16),
                split.reshape(-1).astype(np.uint32),
            )
    for staged in (hourly, daily, scope):
        staged.flush()

    names = {
        "channels": plan.channels,
        "kinds": [kind for kind, _ in vocabulary.terms],
        "terms": [term for _, term in vocabulary.terms],
    }
    # every mention by someone else, hashed so the same row always gets the same people
    client.command(
        """
        INSERT INTO term_hourly (hour, channel, doc_type, kind, term, occurrences, docs, authors)
        SELECT toDateTime(hour, 'UTC'), {channels:Array(String)}[channel + 1], 'comment',
               {kinds:Array(String)}[term + 1], {terms:Array(String)}[term + 1],
               docs + intDiv(docs, 8), docs,
               arrayReduce('uniqCombinedState(12)',
                           arrayMap(i -> cityHash64(channel, term, hour, i), range(docs)))
        FROM demo_hourly
        """,
        parameters=names,
        settings={"max_insert_threads": 4},
    )
    # the days of the hourly counts, before anything else is in term_hourly
    for channel in plan.channels:
        client.command(
            """
            INSERT INTO term_daily (day, channel, doc_type, kind, term, occurrences, docs, authors)
            SELECT toDate(hour), channel, doc_type, kind, term, sum(occurrences), sum(docs),
                   uniqCombinedMergeState(12)(authors)
            FROM term_hourly
            WHERE channel = {channel:String}
            GROUP BY channel, term, kind, doc_type, toDate(hour)
            SETTINGS optimize_aggregation_in_order = 1
            """,
            parameters={"channel": channel},
        )
    client.command(
        """
        INSERT INTO term_daily (day, channel, doc_type, kind, term, occurrences, docs, authors)
        SELECT toDate(toDateTime(day, 'UTC')), {channels:Array(String)}[channel + 1], 'comment',
               {kinds:Array(String)}[term + 1], {terms:Array(String)}[term + 1],
               docs + intDiv(docs, 8), docs,
               arrayReduce('uniqCombinedState(12)',
                           arrayMap(i -> cityHash64(channel, term, day, i), range(docs)))
        FROM demo_daily
        """,
        parameters=names,
        settings={"max_insert_threads": 4},
    )
    # authors: four in five comments of a day are by someone new that day
    client.command(
        """
        INSERT INTO scope_hourly (hour, channel, doc_type, docs, tokens, authors)
        SELECT toDateTime(hour, 'UTC'), {channels:Array(String)}[channel + 1], 'comment',
               docs, docs * {tokens:UInt32},
               arrayReduce('uniqCombinedState(12)',
                           arrayMap(i -> cityHash64(channel, intDiv(hour, 86400), i),
                                    range(intDiv(docs * 4, 5))))
        FROM demo_scope
        WHERE docs > 0
        """,
        parameters={**names, "tokens": TOKENS_PER_DOC},
        settings={"max_insert_threads": 4},
    )
    return vocabulary


# --- the planted documents ---------------------------------------------------------------


@dataclass(frozen=True)
class Doc:
    at: datetime
    channel: str
    text: str
    doc_type: str = "comment"
    # the intents the ingester must find in it
    intents: tuple[str, ...] = ()


# How products are written
NAMES = {
    "notion": "Notion",
    "obsidian": "Obsidian",
    "evernote": "Evernote",
    "onenote": "OneNote",
    "logseq": "Logseq",
    "roam research": "Roam Research",
    "windows": "Windows",
    "linux": "Linux",
    "chrome": "Chrome",
    "firefox": "Firefox",
    "lastpass": "LastPass",
    "bitwarden": "Bitwarden",
    "spotify": "Spotify",
    "tidal": "Tidal",
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "jira": "Jira",
    "linear": "Linear",
    "robinhood": "Robinhood",
    "fidelity": "Fidelity",
    "plex": "Plex",
    "jellyfin": "Jellyfin",
    "dropbox": "Dropbox",
    "nextcloud": "Nextcloud",
    "google photos": "Google Photos",
    "immich": "Immich",
    "steam": "Steam",
    "discord": "Discord",
    "youtube": "YouTube",
}
MONTHS = ("January", "March", "April", "June", "September", "October")
SWITCHED = (
    "I switched from {x} to {y} last month and never looked back.",
    "Switched from {x} to {y}, everything feels faster now.",
    "We migrated from {x} to {y} in {month}.",
    "Finally made the switch from {x} to {y}.",
    "I switched from {x} to {y} and I am not going back.",
    "I switched from {x} to {y} a few weeks ago.",
)
THINKING = (
    "I'm thinking of switching from {x} to {y}.",
    "Should I switch from {x} to {y}?",
    "I'm seriously thinking about switching from {x} to {y}.",
)
LEAVING = ("Thinking about leaving {x}.", "Should I ditch {x}?", "About to cancel {x}.")
DOWN = ("Is {x} down for anyone else?", "{x} is down again.", "Is {x} down?")
PRICES = ("{x} raised prices again.", "I cancelled my {x} subscription last week.")
BROKEN = ("After the update {x} is broken again.",)
ALTERNATIVES = (
    "Are there any good alternatives to {x}?",
    "Looking for a replacement for {x}.",
    "Is there a decent replacement for {x}?",
)


def switch(x: str, y: str) -> tuple[str, tuple[str, ...]]:
    return f"{x} → {y}", SWITCHED


def considering(x: str, y: str | None = None) -> tuple[str, tuple[str, ...]]:
    if y is None:
        return f"considering: {x}", LEAVING
    return f"considering: {x} → {y}", THINKING


def complaint(x: str, texts: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    return f"complaint: {x}", texts


def alternative(x: str) -> tuple[str, tuple[str, ...]]:
    return f"alternative: {x}", ALTERNATIVES


NEEDS = {
    "syncs notes": ("I'd pay for an app that syncs notes between devices.",),
    "export my notes": ("I wish there was a way to export my notes to markdown.",),
    "tracks my habits": ("Is there an app that tracks my habits?",),
    "track my sleep": ("Is there an app to track my sleep?",),
    "meal planning": ("Can anyone recommend an app for meal planning?",),
    "split bills": ("Is there an app to split bills with roommates?",),
    "batch renaming files": ("Does anyone know a tool for batch renaming files?",),
}


def need(what: str) -> tuple[str, tuple[str, ...]]:
    return f"need: {what}", NEEDS[what]


def fill(template: str, intent: str, rng: np.random.Generator) -> str:
    """A template with its products written as names."""
    entity = intent.split(": ", 1)[-1]
    x, _, y = entity.partition(" → ")
    return template.format(
        x=NAMES.get(x, x), y=NAMES.get(y, y), month=MONTHS[int(rng.integers(len(MONTHS)))]
    )


PKM_CHANNELS = {
    "r/notion": 0.3,
    "r/obsidianmd": 0.35,
    "r/evernote": 0.08,
    "r/onenote": 0.07,
    "r/logseq": 0.08,
    "r/pkms": 0.06,
    "r/notetaking": 0.04,
    "r/zettelkasten": 0.02,
}
# The intents of every day: (what, channels and their part, per day)
CHATTER: tuple[tuple[tuple[str, tuple[str, ...]], dict[str, float], float], ...] = (
    (switch("notion", "obsidian"), PKM_CHANNELS, 2.0),
    (switch("obsidian", "notion"), PKM_CHANNELS, 0.5),
    (switch("evernote", "notion"), PKM_CHANNELS, 1.2),
    (switch("evernote", "obsidian"), PKM_CHANNELS, 0.8),
    (switch("onenote", "obsidian"), PKM_CHANNELS, 0.6),
    (switch("notion", "logseq"), PKM_CHANNELS, 0.4),
    (switch("logseq", "obsidian"), PKM_CHANNELS, 0.5),
    (switch("roam research", "logseq"), PKM_CHANNELS, 0.2),
    (switch("notion", "evernote"), PKM_CHANNELS, 0.1),
    (complaint("evernote", PRICES), PKM_CHANNELS, 0.5),
    (complaint("notion", BROKEN), PKM_CHANNELS, 0.2),
    (alternative("notion"), PKM_CHANNELS, 0.4),
    (alternative("evernote"), PKM_CHANNELS, 0.4),
    (alternative("onenote"), PKM_CHANNELS, 0.25),
    (considering("notion", "obsidian"), PKM_CHANNELS, 0.5),
    (considering("notion"), PKM_CHANNELS, 0.25),
    (considering("evernote"), PKM_CHANNELS, 0.25),
    (need("syncs notes"), PKM_CHANNELS, 0.3),
    (need("export my notes"), PKM_CHANNELS, 0.25),
    (need("tracks my habits"), PKM_CHANNELS, 0.15),
    (switch("notion", "obsidian"), {SAMPLE: 1}, 0.6),
    (switch("evernote", "notion"), {SAMPLE: 1}, 0.3),
    (switch("windows", "linux"), {SAMPLE: 1}, 0.6),
    (switch("chrome", "firefox"), {SAMPLE: 1}, 0.4),
    (switch("spotify", "tidal"), {SAMPLE: 1}, 0.2),
    (switch("chatgpt", "claude"), {SAMPLE: 1}, 0.5),
    (complaint("spotify", PRICES), {SAMPLE: 1}, 0.4),
    (complaint("youtube", DOWN), {SAMPLE: 1}, 0.2),
    (alternative("plex"), {SAMPLE: 1}, 0.15),
    (need("track my sleep"), {SAMPLE: 1}, 0.3),
    (need("meal planning"), {SAMPLE: 1}, 0.2),
    (need("split bills"), {SAMPLE: 1}, 0.15),
    (switch("windows", "linux"), {"r/linux": 1}, 0.8),
    (need("batch renaming files"), {"r/linux": 1}, 0.15),
    (switch("lastpass", "bitwarden"), {"r/selfhosted": 1}, 0.25),
    (switch("dropbox", "nextcloud"), {"r/selfhosted": 1}, 0.25),
    (switch("google photos", "immich"), {"r/selfhosted": 1}, 0.3),
    (switch("plex", "jellyfin"), {"r/selfhosted": 0.7, "r/homelab": 0.3}, 0.3),
    (alternative("plex"), {"r/selfhosted": 1}, 0.2),
    (switch("chatgpt", "claude"), {"r/openai": 0.5, "r/claudeai": 0.5}, 0.6),
    (switch("claude", "chatgpt"), {"r/openai": 0.6, "r/claudeai": 0.4}, 0.2),
    (switch("jira", "linear"), {"r/webdev": 0.5, "r/experienceddevs": 0.5}, 0.2),
    (complaint("windows", BROKEN), {"r/technology": 0.6, "r/pcgaming": 0.4}, 0.2),
    (need("track my sleep"), {"r/android": 0.6, "r/apple": 0.4}, 0.15),
    (switch("robinhood", "fidelity"), {"r/investing": 0.5, "r/personalfinance": 0.5}, 0.3),
    (need("split bills"), {"r/personalfinance": 1}, 0.15),
    (complaint("steam", DOWN), {"r/pcgaming": 0.6, "r/gaming": 0.4}, 0.15),
    (complaint("discord", DOWN), {"r/gaming": 1}, 0.1),
)
QUESTION_KINDS = ("considering", "need", "alternative")

# Cascades: (leader, followers as (channel, lag hours, chance, mentions relative to the
# leader's), how a term is made from a name, templates)
FollowerSpec = tuple[str, tuple[float, float], float, float]


@dataclass(frozen=True)
class Cascade:
    leader: str
    followers: tuple[FollowerSpec, ...]
    name: Callable[[str, int], str]
    templates: tuple[str, ...]
    mentions: tuple[int, int] = (30, 60)


# Planted terms come with stopwords only, so no other word or phrase bursts or grows with
# them (check_templates). Every cascade says one of these, or links its term.
SAYINGS = (
    "{t} is out!",
    "Oh, {t} is here.",
    "Is {t} out now?",
    "So, {t}. Yes or no?",
    "Anyone else on {t}?",
)
CASCADES = (
    Cascade(
        "r/localllama",
        (("r/singularity", (10, 20), 0.85, 0.6), ("r/all", (40, 70), 0.5, 0.7)),
        lambda base, n: f"{base.title()}-{(3, 7, 8, 14, 32, 70)[n % 6]}B",
        (*SAYINGS, "{t}: https://huggingface.co/demo/{slug}"),
    ),
    Cascade(
        "r/hardware",
        (("r/buildapc", (4, 10), 0.85, 0.7),),
        lambda base, n: f"{base.title()}-X{n % 9 + 1}",
        (*SAYINGS, "{t}: https://arstechnica.com/demo/{slug}"),
    ),
    Cascade(
        "r/selfhosted",
        (("r/homelab", (14, 30), 0.8, 0.7),),
        lambda base, n: f"{base.title()}box",
        (*SAYINGS, "{t}: https://github.com/demo/{slug}"),
    ),
    Cascade(
        "r/obsidianmd",
        (("r/pkms", (20, 40), 0.8, 0.6),),
        lambda base, n: f"{base.title()}-Sync",
        (*SAYINGS, "{t}: https://github.com/demo/{slug}"),
    ),
    Cascade(
        "r/wallstreetbets",
        (("r/stocks", (3, 8), 0.85, 0.5),),
        lambda base, n: f"${base[:4].upper()}",
        ("{t} is going up again.", "Who else is on {t}?", "All in on {t}.", *SAYINGS[:3]),
    ),
    Cascade(
        "r/pcgaming",
        (("r/games", (24, 48), 0.8, 0.7),),
        lambda base, n: f"{base.title()}fall",
        (*SAYINGS, "{t}: https://store.steampowered.com/app/{slug}"),
    ),
)
# The last cascade of each leader, the story at the as-of: (name, hours before the as-of
# it starts in the leader, the followers' lags in hours, None: doesn't follow by then)
LAST_CASCADES = {
    "r/localllama": ("Lumen-8B", 30, (14, 40)),
    "r/hardware": ("Vertex-X7", 52, (7,)),
    "r/selfhosted": ("Summitbox", 20, (26,)),
    "r/obsidianmd": ("Prism-Sync", 10, (30,)),
    "r/wallstreetbets": ("$RIFT", 40, (5,)),
    "r/pcgaming": ("Zephyrfall", 70, (36,)),
}

LAUNCH = "Lumina X1"
LAUNCH_HOURS = 26
LAUNCH_CHANNELS = {
    "r/technology": 25,
    "r/gadgets": 20,
    "r/apple": 12,
    "r/android": 12,
    "r/hardware": 10,
    "r/singularity": 8,
    "r/futurology": 8,
    "r/news": 10,
    "r/artificial": 6,
    "r/openai": 6,
    "r/programming": 5,
    "r/webdev": 5,
    "r/all": 30,
}
LAUNCH_TEXTS = (
    "The {t} is here.",
    "So the {t} is out.",
    "{t}. That is all.",
    "Oh, the {t}!",
    "{t}: https://theverge.com/demo/lumina-x1",
    "Who else is getting one? The {t}.",
)


@dataclass(frozen=True)
class LongTerm:
    """A term whose share (per 1,000 documents of the group) changes over months, as a
    function of the weeks before the Monday of the as-of's week."""

    term: str
    group: str
    share: Callable[[float], float]
    templates: tuple[str, ...]


def growing(base: float, factor: float, since: float | None = None) -> Callable[[float], float]:
    """base × factor per week from `since` (weeks before the Monday), none before, or base
    × factor per week all along (from 57 weeks before)."""

    def share(weeks: float) -> float:
        if since is None:
            return base * factor ** (weeks + 57)
        return 0.0 if weeks < -since else base * factor ** (weeks + since)

    return share


def steady_then(base: float, factor: float, since: float) -> Callable[[float], float]:
    def share(weeks: float) -> float:
        return base if weeks < -since else base * factor ** (weeks + since)

    return share


def spike(base: float, times: float, first: float, weeks: float) -> Callable[[float], float]:
    def share(at: float) -> float:
        return base * times if -first <= at < -first + weeks else base

    return share


LONG_TERM = (
    LongTerm(
        "vibe coding",
        "tech",
        growing(0.5, 1.3, since=13),
        (
            "Is it just me or is everyone into vibe coding now?",
            "Vibe coding, again.",
            "Who else is doing vibe coding?",
            "Vibe coding it is.",
        ),
    ),
    LongTerm(
        "agent memory",
        "tech",
        steady_then(0.2, 1.12, since=26),
        (
            "How do you all do agent memory?",
            "Agent memory, again.",
            "Is agent memory a thing yet?",
            "So, agent memory. Any of you?",
        ),
    ),
    LongTerm(
        "local inference",
        "tech",
        growing(2.0, 1.027),
        (
            "Is anyone else doing local inference?",
            "Local inference, again.",
            "So is local inference the way to go?",
            "Local inference it is.",
        ),
    ),
    LongTerm(
        "metaverse",
        "tech",
        growing(6.0, 0.966),
        (
            "Is the metaverse still a thing?",
            "What about the metaverse?",
            "So, the metaverse. Any of you?",
            "The metaverse is over.",
        ),
    ),
    LongTerm(
        "web3",
        "tech",
        steady_then(6.0, 0.8, since=13),
        (
            "Is anyone still doing web3?",
            "Web3, again.",
            "So is web3 over?",
            "Web3 it is.",
        ),
    ),
    LongTerm(
        "cloud outage",
        "tech",
        spike(0.3, 15, first=2, weeks=2),
        (
            "Was it the cloud outage again?",
            "Another cloud outage.",
            "Is this a cloud outage or just me?",
            "So, the cloud outage. Any of you?",
        ),
    ),
    LongTerm(
        "solar flare",
        "science",
        spike(2.0, 15, first=3, weeks=1),
        (
            "What about the solar flare?",
            "Oh, the solar flare.",
            "Did anyone else get the solar flare?",
        ),
    ),
    LongTerm(
        "rate cut",
        "finance",
        growing(2.0, 1.03),
        (
            "Is a rate cut on the way?",
            "Rate cut, again.",
            "So when is the rate cut?",
        ),
    ),
    LongTerm(
        "blockchain gaming",
        "gaming",
        growing(5.0, 0.95),
        (
            "Is anyone still into blockchain gaming?",
            "Blockchain gaming, again.",
            "So is blockchain gaming over?",
        ),
    ),
)


class Planter:
    """Collects the planted documents, in the seeded channels and the seeded time."""

    def __init__(self, plan: Plan):
        self.plan = plan
        self.docs: list[Doc] = []
        self._channels = set(plan.channels)
        self._weights = {
            language: diurnal(language) / diurnal(language).sum() for language in ("en", "de")
        }

    def has(self, channel: str) -> bool:
        return channel in self._channels

    def add(self, doc: Doc) -> None:
        if doc.channel in self._channels and self.plan.daily_start <= doc.at < self.plan.as_of:
            self.docs.append(doc)

    def times_in_day(self, rng: np.random.Generator, day: datetime, count: int) -> list[datetime]:
        hours = rng.choice(24, size=count, p=self._weights["en"])
        seconds = rng.integers(0, 3600, size=count)
        return [
            day + timedelta(hours=int(h), seconds=int(s))
            for h, s in zip(hours, seconds, strict=True)
        ]

    def burst_times(
        self, rng: np.random.Generator, start: datetime, count: int, scale_hours: float = 9.0
    ) -> list[datetime]:
        """A burst: a quick rise, then mentions fading over a day or two."""
        offsets = rng.gamma(1.6, scale_hours, size=count).clip(0, 60)
        return sorted(start + timedelta(hours=float(offset)) for offset in offsets)


def plant_chatter(planter: Planter) -> None:
    plan = planter.plan
    rng = plan.rng(2)
    days = (plan.as_of.date() - plan.daily_start.date()).days + 1
    for day_offset in range(days):
        day = plan.daily_start + day_offset * DAY
        for (intent, templates), channels, per_day in CHATTER:
            boost = evernote_boost(plan, intent, day)
            count = int(rng.poisson(per_day * boost * weekday_factor(day.date())))
            if not count:
                continue
            names, parts = zip(*channels.items(), strict=True)
            weights = np.array(parts) / sum(parts)
            for at in planter.times_in_day(rng, day, count):
                channel = str(names[int(rng.choice(len(names), p=weights))])
                kind = intent.split(":", 1)[0] if ":" in intent else "switch"
                doc_type = "post" if kind in QUESTION_KINDS and rng.random() < 0.4 else "comment"
                template = str(templates[int(rng.integers(len(templates)))])
                planter.add(Doc(at, channel, fill(template, intent, rng), doc_type, (intent,)))


EVERNOTE_HIKE_DAYS = 20


def evernote_boost(plan: Plan, intent: str, day: datetime) -> float:
    """Two weeks of switching away from Evernote after its price hike."""
    if not intent.startswith("evernote → "):
        return 1.0
    since = (day - (plan.as_of - timedelta(days=EVERNOTE_HIKE_DAYS))).days
    return 2.0 if 0 <= since < 14 else 1.0


def plant_events(planter: Planter) -> None:
    """The Notion outage and the Evernote price hike."""
    plan = planter.plan
    rng = plan.rng(3)
    outage = plan.as_of - timedelta(hours=20)
    intent = "complaint: notion"
    for channel, count in {
        "r/notion": 45,
        SAMPLE: 25,
        "r/obsidianmd": 6,
        "r/pkms": 4,
        "r/notetaking": 3,
    }.items():
        for at in sorted(
            outage + timedelta(hours=float(h)) for h in rng.exponential(1.5, count).clip(0, 5)
        ):
            text = fill(str(DOWN[int(rng.integers(len(DOWN)))]), intent, rng)
            planter.add(Doc(at, channel, text, "comment", (intent,)))
    aftermath = (
        (alternative("notion"), 12),
        (considering("notion", "obsidian"), 10),
        (considering("notion"), 6),
        (switch("notion", "obsidian"), 8),
        (switch("notion", "logseq"), 3),
    )
    for (intent, templates), count in aftermath:
        for _ in range(count):
            at = outage + timedelta(hours=float(rng.uniform(2, 19.5)))
            channel = str(rng.choice(["r/notion", "r/obsidianmd", "r/pkms", SAMPLE]))
            text = fill(str(templates[int(rng.integers(len(templates)))]), intent, rng)
            planter.add(
                Doc(at, channel, text, "post" if "considering" in intent else "comment", (intent,))
            )

    hike = plan.as_of - timedelta(days=EVERNOTE_HIKE_DAYS)
    intent = "complaint: evernote"
    for channel, count in {"r/evernote": 14, "r/pkms": 4, "r/notion": 4, SAMPLE: 8}.items():
        for at in planter.burst_times(rng, hike, count, scale_hours=20):
            text = fill(str(PRICES[int(rng.integers(len(PRICES)))]), intent, rng)
            planter.add(Doc(at, channel, text, "comment", (intent,)))


@dataclass
class PlantedCascade:
    term: str
    leader: str
    start: datetime
    # (follower, when it starts) of those that follow
    followers: list[tuple[str, datetime]]


def plant_cascades(planter: Planter, words: dict[str, list[str]]) -> list[PlantedCascade]:
    plan = planter.plan
    rng = plan.rng(4)
    # the fixed last cascades' names are taken
    used = {name.lower() for name, _, _ in LAST_CASCADES.values()}
    bases = {re.split(r"[-$]|box$|fall$", name.lower().strip("$"))[0] for name in used}
    names = [name for name in words["names"] if name not in bases]
    rng.shuffle(names)
    planted = []
    for number, cascade in enumerate(CASCADES):
        if not planter.has(cascade.leader):
            continue
        last_name, last_hours, last_lags = LAST_CASCADES[cascade.leader]
        last = plan.as_of - timedelta(hours=last_hours)
        start = plan.as_of - timedelta(days=plan.size.cascade_from) + timedelta(hours=7 * number)
        instance = 0
        while start < last - timedelta(days=plan.size.cascade_every / 2):
            term = cascade.name(names.pop(), instance)
            if term.lower() in used:
                continue
            used.add(term.lower())
            followers = []
            for channel, (low, high), chance, _ in cascade.followers:
                if rng.random() < chance:
                    followers.append(
                        (channel, start + timedelta(hours=float(rng.uniform(low, high))))
                    )
            planted.append(PlantedCascade(term, cascade.leader, start, followers))
            jitter = float(rng.uniform(-0.15, 0.15)) * plan.size.cascade_every
            start += timedelta(days=plan.size.cascade_every + jitter)
            instance += 1
        followers = [
            (channel, last + timedelta(hours=lag))
            for (channel, *_), lag in zip(cascade.followers, last_lags, strict=True)
        ]
        planted.append(PlantedCascade(last_name, cascade.leader, last, followers))

    for item in planted:
        cascade = next(c for c in CASCADES if c.leader == item.leader)
        leader_mentions = int(rng.integers(*cascade.mentions))
        bursts = [(item.leader, item.start, leader_mentions)]
        for channel, at in item.followers:
            relative = next(spec[3] for spec in cascade.followers if spec[0] == channel)
            bursts.append((channel, at, max(8, int(leader_mentions * relative))))
        slug = item.term.lower().strip("$")
        for channel, at, count in bursts:
            for moment in planter.burst_times(rng, at, count):
                template = str(cascade.templates[int(rng.integers(len(cascade.templates)))])
                text = template.format(t=item.term, slug=slug)
                planter.add(
                    Doc(moment, channel, text, "post" if rng.random() < 0.15 else "comment")
                )
    return planted


def plant_launch(planter: Planter) -> None:
    rng = planter.plan.rng(5)
    start = planter.plan.as_of - timedelta(hours=LAUNCH_HOURS)
    for channel, count in LAUNCH_CHANNELS.items():
        # everywhere within the same two hours, and twice as much over the next day
        for moment in sorted(
            [start + timedelta(hours=float(h)) for h in rng.uniform(0, 2, count)]
            + planter.burst_times(rng, start + 2 * HOUR, 2 * count, scale_hours=6)
        ):
            text = str(LAUNCH_TEXTS[int(rng.integers(len(LAUNCH_TEXTS)))]).format(t=LAUNCH)
            planter.add(Doc(moment, channel, text, "post" if rng.random() < 0.2 else "comment"))


def plant_long_term(planter: Planter) -> None:
    plan = planter.plan
    rng = plan.rng(6)
    monday = datetime.combine(week_start(plan.as_of), datetime.min.time(), UTC)
    days = (plan.as_of.date() - plan.daily_start.date()).days + 1
    for story in LONG_TERM:
        if story.group not in plan.config.groups:
            continue
        members = [channel for channel in plan.config.groups[story.group] if planter.has(channel)]
        for day_offset in range(days):
            day = plan.daily_start + day_offset * DAY
            share = story.share((day - monday) / timedelta(weeks=1)) / 1000
            for channel in members:
                expected = share * plan.volume(channel) * weekday_factor(day.date())
                count = int(rng.poisson(expected))
                for at in planter.times_in_day(rng, day, count):
                    template = str(story.templates[int(rng.integers(len(story.templates)))])
                    planter.add(Doc(at, channel, template, "comment"))


# --- through the ingester -----------------------------------------------------------------


def check_templates() -> None:
    """Every planted term must come out of its sentences alone: a word or phrase around it
    would burst or grow with it."""
    problems = []
    single = [
        (cascade.name("kestrel", 1), template)
        for cascade in CASCADES
        for template in cascade.templates
    ] + [(LAUNCH, template) for template in LAUNCH_TEXTS]
    single += [(story.term, template) for story in LONG_TERM for template in story.templates]
    stop = stopwords("en")
    for term, template in single:
        text = template.format(t=term, slug="x")
        planted = extract_terms(term).counts
        found = extract_terms(text).counts
        extra = {
            f"{kind} {t}"
            for kind, t in found
            if (kind, t) not in planted and kind != "domain" and t not in stop
        }
        if extra:
            problems.append(f"{text!r}: {sorted(extra)}")
    texts = [template.format(t=term, slug="x") for term, template in single]
    for (intent, templates), _, _ in CHATTER:
        texts += [fill(template, intent, np.random.default_rng(0)) for template in templates]
    background = set(load_words()["stopwords"])
    for text in texts:
        missing = {
            t for kind, t in extract_terms(text).counts if kind == "word" and t in stop
        } - background
        if missing:
            problems.append(f"{text!r}: stopwords without a background {sorted(missing)}")
    if problems:
        raise SystemExit("templates that plant more than their term:\n  " + "\n  ".join(problems))


def base36(number: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        number, remainder = divmod(number, 36)
        out = digits[remainder] + out
        if number == 0:
            return out


def write_docs(client: Client, plan: Plan, docs: Sequence[Doc]) -> Counter[str]:
    """The planted documents through the ingester's Processor: the last 48 hours as items
    and term_events (their materialized views count them), the rest into the counts."""
    processor = Processor(plan.config, AUTHOR_HASH_KEY)
    rng = plan.rng(7)
    items, item_terms, events, history = [], [], [], []
    mismatches: list[str] = []
    stats: Counter[str] = Counter()
    for number, doc in enumerate(sorted(docs, key=lambda doc: (doc.at, doc.channel, doc.text))):
        if doc.channel == SAMPLE:
            subreddit = str(SAMPLED_SUBREDDITS[number % len(SAMPLED_SUBREDDITS)])
        else:
            subreddit = subreddit_of(doc.channel)
        id36 = base36(10**9 + number)
        slug = re.sub(r"[^a-z0-9]+", "_", doc.text.lower())[:40].strip("_")
        post = base36(10**8 + number // 7)
        permalink = (
            f"/r/{subreddit}/comments/{id36}/{slug}/"
            if doc.doc_type == "post"
            else f"/r/{subreddit}/comments/{post}/{slug}/{id36}/"
        )
        reddit = RedditItem(
            fullname=f"{'t3' if doc.doc_type == 'post' else 't1'}_{id36}",
            doc_type="post" if doc.doc_type == "post" else "comment",
            subreddit=subreddit,
            author=f"demo{int(rng.integers(1_000_000)):06d}",
            created_utc=int(doc.at.timestamp()),
            text=doc.text,
            permalink=permalink,
            distinguished=None,
            stickied=False,
        )
        item = to_item(reddit, plan.config)
        if item.channel != doc.channel:
            raise ValueError(f"{doc} lands in {item.channel}")
        processed = processor.process(item)
        found = tuple(processed.item_row[ITEM_COLUMNS.index("intents")])
        if found != tuple(sorted(doc.intents)):
            mismatches.append(f"{doc.text!r}: {found}, planted {doc.intents}")
        stats["documents"] += 1
        if doc.at >= plan.items_start:
            items.append(processed.item_row)
            item_terms += processed.term_rows
            stats["items"] += 1
        else:
            hour = item.created_at.replace(minute=0, second=0, microsecond=0)
            author_hash = processed.item_row[ITEM_COLUMNS.index("author_hash")]
            tokens = processed.item_row[ITEM_COLUMNS.index("token_count")]
            history.append((hour, item.channel, item.doc_type, author_hash, tokens))
            events += processed.term_rows
    if mismatches:
        raise SystemExit("intents not found as planted:\n  " + "\n  ".join(mismatches[:20]))

    for first in range(0, len(events), 500_000):
        client.insert(
            "demo_events", events[first : first + 500_000], column_names=list(TERM_COLUMNS)
        )
    client.insert(
        "demo_docs", history, column_names=["hour", "channel", "doc_type", "author_hash", "tokens"]
    )
    start = {"start": int(plan.hourly_start.timestamp())}
    # what the materialized views would have made of them
    client.command(
        """
        INSERT INTO term_hourly (hour, channel, doc_type, kind, term, occurrences, docs, authors)
        SELECT hour, channel, doc_type, kind, term, sum(toUInt64(occurrences)), toUInt64(count()),
               uniqCombinedState(12)(author_hash)
        FROM demo_events
        WHERE hour >= toDateTime({start:UInt32}, 'UTC')
        GROUP BY hour, channel, doc_type, kind, term
        """,
        parameters=start,
    )
    client.command(
        """
        INSERT INTO term_daily (day, channel, doc_type, kind, term, occurrences, docs, authors)
        SELECT toDate(hour) AS day, channel, doc_type, kind, term, sum(toUInt64(occurrences)),
               toUInt64(count()), uniqCombinedState(12)(author_hash)
        FROM demo_events
        GROUP BY day, channel, doc_type, kind, term
        """
    )
    client.command(
        """
        INSERT INTO scope_hourly (hour, channel, doc_type, docs, tokens, authors)
        SELECT hour, channel, doc_type, toUInt64(count()), sum(toUInt64(tokens)),
               uniqCombinedState(12)(author_hash)
        FROM demo_docs
        GROUP BY hour, channel, doc_type
        """
    )
    # the last 48 hours like the ingester's Writer: items first, then their terms. They
    # arrived 20 seconds after they were written, not when the demo was seeded.
    created = ITEM_COLUMNS.index("created_at")
    client.insert(
        "items",
        [(*row, row[created] + INGEST_DELAY) for row in items],
        column_names=[*ITEM_COLUMNS, "ingested_at"],
    )
    for first in range(0, len(item_terms), 500_000):
        client.insert(
            "term_events", item_terms[first : first + 500_000], column_names=list(TERM_COLUMNS)
        )
    stats["term rows"] = len(events) + len(item_terms)
    return stats


# --- collection ---------------------------------------------------------------------------

# reddit's ids advance by about this many comments a second, everywhere
REDDIT_COMMENTS_PER_SECOND = 23.0


def write_polls(client: Client, plan: Plan) -> int:
    """Every feed's polls of the last 48 hours: the comment feeds every 20–40 seconds, the
    posts every 1–2 minutes, the sample every 3 seconds, the radar's searches every 15
    minutes. The comment feeds fail during the gap, the poll after it finds one."""
    rng = plan.rng(8)
    feeds = build_feeds(plan.config)
    tracked_per_second = sum(plan.volume(channel) for channel in plan.tracked) / 86400
    comment_feeds = [feed for feed in feeds if feed.kind == "comments" and not feed.sample]
    failing_feeds = {feed.name for feed in comment_feeds}
    gap_start = plan.as_of - GAP_BEFORE
    gap_end = gap_start + GAP_LENGTH
    start = plan.as_of - timedelta(hours=ITEM_HOURS)
    rows = []
    for feed in feeds:
        if feed.sample:
            interval, rate = 3.0, SAMPLE_PER_DAY / 86400
        elif feed.search is not None:
            interval, rate = 900.0, 1 / 1800
        elif feed.kind == "comments":
            interval, rate = 30.0, tracked_per_second / max(len(comment_feeds), 1)
        else:
            interval, rate = 90.0, tracked_per_second / 25 / max(len(comment_feeds), 1)
        at = start + timedelta(seconds=float(rng.uniform(0, interval)))
        failed_since: datetime | None = None
        while at < plan.as_of:
            wait = interval * float(rng.uniform(0.7, 1.3))
            hour = diurnal("en")[at.hour]
            failing = feed.name in failing_feeds and gap_start <= at < gap_end
            remaining = float(rng.integers(300, 1000))
            if failing:
                failed_since = failed_since or at
                poll = Poll(at, PLATFORM, feed.name, feed.kind, feed.sample, 503, 0, 0, False, 0,
                            int(rng.integers(8000, 10000)), wait, 0.0, remaining)  # fmt: skip
            else:
                since = (at - failed_since).total_seconds() if failed_since else wait
                gap = failed_since is not None
                expected = rate * hour * since
                new = 100 if gap else min(100, int(rng.poisson(expected)))
                id_span = int(
                    REDDIT_COMMENTS_PER_SECOND * hour * since * float(rng.uniform(0.9, 1.1))
                )
                poll = Poll(at, PLATFORM, feed.name, feed.kind, feed.sample, 200,
                            100 if feed.search is None else 25, new, gap, id_span,
                            int(rng.integers(250, 900)), wait, rate * hour, remaining)  # fmt: skip
                failed_since = None
            rows.append(poll.row())
            at += timedelta(seconds=wait)
    client.insert("polls", rows, column_names=list(POLL_COLUMNS))
    return len(rows)


# --- the real code on top -----------------------------------------------------------------


class Outbox(Ntfy):
    """ntfy that never sends: it keeps the messages the analyzer decided to send."""

    def __init__(self) -> None:
        self.topic = "demo"
        self.messages: list[Message] = []

    def send(self, message: Message) -> None:
        self.messages.append(message)

    def close(self) -> None:
        pass


class DemoAnalyzer(Analyzer):
    """The live analyzer as of simulated times: notifications are stored as sent at the
    time it runs as of, not the wall clock's."""

    clock: datetime = DEFAULT_AS_OF

    def _log_notification(
        self,
        kind: str,
        scope: str,
        term: str,
        title: str,
        body: str,
        ok: bool,
        error: str = "",
    ) -> None:
        self._client.insert(
            "notifications",
            [[self.clock, kind, scope, term, title, body, ok, error]],
            column_names=list(NOTIFICATION_COLUMNS),
        )


def run_code(client: Client, plan: Plan, env: Env, log: Callable[[str], None]) -> Counter[str]:
    """The detectors as the live analyzer would have run them."""
    analyzer = DemoAnalyzer(plan.config, env, client, Outbox())
    stats: Counter[str] = Counter()

    monday = datetime.combine(week_start(plan.as_of), datetime.min.time(), UTC)
    started = time.monotonic()
    for weeks in range(plan.size.mondays - 1, -1, -1):
        at = monday - timedelta(weeks=weeks)
        analyzer.clock = at + timedelta(minutes=30)
        result = analyzer.run_long_term(analyzer.clock)
        stats["long-term trends"] += len(result.trends)
        analyzer.clock = at + timedelta(hours=9)
        scopes = load_scopes(client, plan.config.long_term.exclude_scopes)
        stats["weekly reports"] += len(analyzer.send_weekly_reports(analyzer.clock, scopes))
    log(f"long-term as of {plan.size.mondays} Mondays: {time.monotonic() - started:.0f}s")

    # The history the lead–lag layer turns into events: the detector in the tracked
    # channels, without alerts (the live loop below has them)
    live_from = (plan.as_of - timedelta(days=plan.size.live_days)).replace(hour=1)
    detector = Detector(client, plan.config)
    channels = [
        scope
        for scope in load_scopes(client, plan.config.detect.exclude_scopes)
        if scope.type == CHANNEL and not scope.background
    ]
    horizons = [horizon for horizon in plan.config.detect.horizons if horizon.name == "24h"]
    at = (plan.as_of - timedelta(days=plan.size.history_days)).replace(hour=12)
    started = time.monotonic()
    while at < live_from:
        trends = detector.run(next_hour(at), detected_at=at, scopes=channels, horizons=horizons)
        write_trends(client, trends)
        stats["history runs"] += 1
        stats["trends"] += len(trends)
        at += timedelta(hours=plan.size.history_every)
    log(f"history: {stats['history runs']} runs, {time.monotonic() - started:.0f}s")

    first_hourly = plan.as_of - timedelta(hours=plan.size.hourly_runs - 1)
    runs = [moment.replace(hour=12) for moment in day_range(live_from, first_hourly)]
    runs = [moment for moment in runs if moment < first_hourly]
    runs += [first_hourly + HOUR * n for n in range(plan.size.hourly_runs)]
    learns = list(day_range(live_from, plan.as_of))
    steps = sorted([(moment, "run") for moment in runs] + [(moment, "learn") for moment in learns])
    started = time.monotonic()
    for number, (moment, step) in enumerate(steps, start=1):
        analyzer.clock = moment
        if step == "learn":
            learned = analyzer.run_lead_lag(moment)
            stats["lead-lag runs"] += 1
            detail = f"{len(learned.edges.edges)} edges, {learned.computed} events"
        else:
            result = analyzer.run_once(moment)
            stats["live runs"] += 1
            stats["trends"] += len(result.trends)
            stats["alerts"] += sum(trend.alert == "sent" for trend in result.trends)
            if result.forecasts:
                stats["forecasts"] += len(result.forecasts.new)
            detail = f"{len(result.trends)} trends, {result.seconds:.1f}s"
        if number % 10 == 0 or number == len(steps) or step == "learn":
            log(f"{moment:%Y-%m-%d %H:%M} {step}: {detail} ({number}/{len(steps)}, "
                f"{time.monotonic() - started:.0f}s)")  # fmt: skip
    return stats


def day_range(first: datetime, last: datetime) -> Iterable[datetime]:
    """The same time of day, every day from `first` to `last` (inclusive)."""
    while first <= last:
        yield first
        first += DAY


# --- seeding ------------------------------------------------------------------------------


def remove_ttls(client: Client) -> list[str]:
    """The history ends at a fixed time in the past: nothing may expire."""
    tables = [
        name
        for (name,) in client.query(
            "SELECT name FROM system.tables WHERE database = currentDatabase() "
            "AND create_table_query LIKE '% TTL %'"
        ).result_rows
    ]
    for table in tables:
        client.command(f"ALTER TABLE {table} REMOVE TTL")
    return tables


def seed(
    client: Client, plan: Plan, env: Env, analyze: bool = True, quiet: bool = False
) -> dict[str, Any]:
    """Seeds an empty database (the caller creates it)."""

    def log(message: str) -> None:
        if not quiet:
            print(f"{time.monotonic() - started:6.0f}s  {message}", flush=True)

    started = time.monotonic()
    check_templates()
    migrate(client)
    removed = remove_ttls(client)
    write_channels(client, plan.config)
    for table, columns in STAGING.items():
        client.command(f"CREATE TABLE {table} ({columns}) ENGINE = MergeTree ORDER BY tuple()")
    log(f"migrated, TTL removed from {', '.join(removed)}")

    words = load_words()
    vocabulary = write_background(client, plan, words)
    log(f"background counts of {len(plan.channels)} channels, {len(vocabulary.terms)} terms")

    planter = Planter(plan)
    plant_chatter(planter)
    plant_events(planter)
    cascades = plant_cascades(planter, words)
    plant_launch(planter)
    plant_long_term(planter)
    stats = write_docs(client, plan, planter.docs)
    log(f"{stats['documents']} planted documents, {stats['items']} of them items")
    polls = write_polls(client, plan)
    log(f"{polls} polls")
    for table in STAGING:
        client.command(f"DROP TABLE {table}")

    if analyze:
        stats.update(run_code(client, plan, env, log))
    log("done")
    return {"stats": stats, "cascades": cascades}


def counts(client: Client) -> dict[str, int]:
    rows = client.query(
        "SELECT table, sum(rows) FROM system.parts WHERE active AND database = currentDatabase() "
        "GROUP BY table ORDER BY table"
    ).result_rows
    return {table: int(total) for table, total in rows}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("seed", help="drop, recreate and fill the demo database")
    command.add_argument("--database", required=True, help="its name must contain 'demo'")
    command.add_argument("--small", action="store_true", help="two groups, 30 days, for CI")
    command.add_argument("--as-of", type=datetime.fromisoformat, default=DEFAULT_AS_OF)
    command.add_argument("--seed", type=int, default=SEED)
    command.add_argument("--config", type=Path, default=Path("config.yaml"))
    command.add_argument("--no-analysis", action="store_true", help="only the data, no detectors")
    args = parser.parse_args()

    env = Env.from_environ()
    if env.clickhouse_port == 3607 or "demo" not in args.database:
        raise SystemExit("only into a demo database, never the live ClickHouse (port 3607)")
    as_of = args.as_of if args.as_of.tzinfo else args.as_of.replace(tzinfo=UTC)
    if as_of.minute or as_of.second or as_of.microsecond:
        raise SystemExit("--as-of must be on a full hour")
    size = SMALL if args.small else FULL
    plan = Plan(size, demo_config(load_config(args.config), size), as_of.astimezone(UTC), args.seed)

    admin = connect(env, database="default")
    admin.command(f"DROP DATABASE IF EXISTS {args.database}")
    admin.command(f"CREATE DATABASE {args.database}")
    client = connect(env, database=args.database)
    started = time.monotonic()
    result = seed(client, plan, env, analyze=not args.no_analysis)
    print(f"\n{args.database}: {size.name}, as of {as_of:%Y-%m-%d %H:%M} UTC, "
          f"{time.monotonic() - started:.0f}s")  # fmt: skip
    for table, rows in counts(client).items():
        print(f"  {table:<20} {rows:>12,}")
    print("\nstats:", dict(result["stats"]))


if __name__ == "__main__":
    main()
