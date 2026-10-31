"""How much there is to report on (docs/CHURN-RADAR.md, phase 1): per watched product and
where it comes from, the comments and posts naming it and those with an intent about it.

Where from:

* ``watchlist``: the channels of the watchlist's group, tracked completely
* ``reddit``: every other tracked subreddit
* ``r/all``: the r/all sample, a few percent of the rest of reddit
* ``r/_search``: posts naming a product anywhere, and the comment trees under some of them
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from clickhouse_connect.driver.client import Client

from wgra.config import TEXT_KINDS, Config, Watchlist
from wgra.sources.reddit.channels import PLATFORM, SAMPLE, SEARCH
from wgra.text.intents import (
    ALTERNATIVE,
    ARROW,
    COMPLAINT,
    CONSIDERING,
    INTENT_KINDS,
    NEED,
    SWITCH,
    intent_entity,
)

ORIGINS = ("watchlist", PLATFORM, SAMPLE, SEARCH)
# the intents about a product (a need is about what someone wants to do)
RADAR_KINDS = (SWITCH, CONSIDERING, ALTERNATIVE, COMPLAINT)

CANDIDATES_SQL = """
SELECT
    multiIf(
        has({watchlist:Array(String)}, channel), 'watchlist',
        channel IN ({search:String}, {sample:String}), toString(channel),
        {platform:String}
    ) AS origin,
    kind,
    term,
    sum(docs) AS mentions,
    uniqCombinedMerge(12)(authors) AS people
FROM term_hourly
WHERE hour >= toStartOfHour(now()) - toIntervalHour({hours:UInt32})
  AND channel IN (
      SELECT channel FROM channel_groups WHERE group_name = {platform:String}
      UNION ALL SELECT arrayJoin({watchlist:Array(String)})
      UNION ALL SELECT arrayJoin([{search:String}, {sample:String}])
  )
  AND (
    kind IN {text_kinds:Array(String)} AND term IN {aliases:Array(String)}
    OR kind IN {intent_kinds:Array(String)} AND multiSearchAny(term, {aliases:Array(String)})
  )
GROUP BY origin, kind, term
"""


@dataclass
class Candidates:
    product: str
    origin: str
    # comments and posts naming it, by its most named alias: an item naming two of its
    # aliases ("Notion", "Notion AI") must count once, so this is a lower bound
    named: int = 0
    named_authors: int = 0
    # kind -> comments and posts with an intent about it (either side of a switch)
    intents: Counter[str] = field(default_factory=Counter)

    @property
    def empty(self) -> bool:
        return not self.named and not self.intents


def products_of(watchlist: Watchlist, kind: str, term: str) -> list[str]:
    """The watched products an intent is about: "evernote → obsidian" and "considering:
    evernote → obsidian" are about both, "alternative: notion ai" about notion.

    This is the radar's filter: only intents about a watched product count, so a game
    character, a country or a language can never be one (docs/CHURN-RADAR.md §2.1)."""
    if kind == NEED:
        return []
    # no name contains the arrow (the config checks), so the sides of a flow are names
    sides = intent_entity(term).split(ARROW)
    return list(dict.fromkeys(product for side in sides if (product := watchlist.product(side))))


def summarize(
    watchlist: Watchlist, rows: Iterable[Sequence[object]]
) -> dict[tuple[str, str], Candidates]:
    """(product, origin) -> candidates, from rows of (origin, kind, term, mentions, authors)."""
    table = {
        (product, origin): Candidates(product, origin)
        for product in watchlist.products
        for origin in ORIGINS
    }
    for origin, kind, term, mentions, authors in rows:
        assert isinstance(origin, str) and isinstance(kind, str) and isinstance(term, str)
        assert isinstance(mentions, int) and isinstance(authors, int)
        if kind in INTENT_KINDS:
            for product in products_of(watchlist, kind, term):
                table[product, origin].intents[kind] += mentions
        elif (named := watchlist.product(term)) and mentions > table[named, origin].named:
            table[named, origin].named = mentions
            table[named, origin].named_authors = authors
    return table


def candidates(
    client: Client, config: Config, watchlist: Watchlist, days: int
) -> dict[tuple[str, str], Candidates]:
    aliases = [alias for names in watchlist.products.values() for alias in names]
    rows = client.query(
        CANDIDATES_SQL,
        parameters={
            "platform": PLATFORM,
            "search": SEARCH,
            "sample": SAMPLE,
            "watchlist": list(config.groups[watchlist.group]),
            "hours": days * 24,
            "text_kinds": [kind for kind in TEXT_KINDS if kind != "subreddit"],
            "intent_kinds": list(RADAR_KINDS),
            "aliases": aliases,
        },
    ).result_rows
    return summarize(watchlist, rows)
