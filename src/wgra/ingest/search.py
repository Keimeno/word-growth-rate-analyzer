"""The churn radar's own collection: posts naming a watched product anywhere on reddit, and
the comment trees under those that ask or tell about a switch (docs/CHURN-RADAR.md §2.2).

reddit's search only finds posts (``type=comment`` is ignored) and has new posts within
minutes. A product like Notion is named in about 200 posts a day, most of them about the
word, not the product. They're cheap to store, and the watchlist filter of the report
drops what isn't about the product. The answers under "Alternatives to Notion?" are where
people say why they switched, so those posts get their comment tree fetched once, a day
after they were posted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from clickhouse_connect.driver.client import Client

from wgra.config import SEARCH_SCOPE, RadarConfig

# a post that asks or tells about a switch: "Alternatives to Notion?", "Obsidian vs Notion",
# "Leaving Evernote", "Moving from OneNote to Obsidian", "Wechsel von Notion zu Obsidian"
TREE_CUES = re.compile(
    r"\b(?:alternatives?|switch\w*|leav(?:e|ing)|left|migrat\w*|replac\w*|mov(?:e|ed|ing)|"
    r"instead|cancel\w*|quit\w*|ditch\w*|vs|versus|wechsel\w*|umstieg\w*|umsteigen)\b",
    re.IGNORECASE,
)
# trees are looked for in posts this many hours older than tree_after_hours, so every one is
# due in several checks and a short outage doesn't skip it
TREE_WINDOW_HOURS = 6


def search_query(aliases: Iterable[str]) -> str:
    """reddit search syntax for posts naming any of the aliases: "notion" OR "notion ai"."""
    return " OR ".join(f'"{alias}"' for alias in aliases)


def names_any(aliases: Iterable[str]) -> re.Pattern[str]:
    """Finds any of the aliases as words."""
    names = sorted({re.escape(alias) for alias in aliases}, key=len, reverse=True)
    return re.compile(rf"(?<!\w)(?:{'|'.join(names)})(?!\w)", re.IGNORECASE)


def wants_tree(title: str, products: re.Pattern[str]) -> bool:
    """Whether a post's title names a watched product and asks or tells about a switch."""
    return bool(products.search(title) and TREE_CUES.search(title))


DUE_TREES_SQL = """
SELECT DISTINCT id, text
FROM items
WHERE subreddit = {scope:String}
  AND source = 'post'
  AND created_at BETWEEN now() - toIntervalSecond({oldest:UInt32})
                     AND now() - toIntervalSecond({newest:UInt32})
"""


def due_trees(client: Client, radar: RadarConfig, done: Sequence[str] | set[str]) -> list[str]:
    """Fullnames of the posts the search found whose comment tree is due: tree_after_hours
    old, a title that names a watched product and asks or tells about a switch, and not
    fetched yet."""
    newest = int(radar.tree_after_hours * 3600)
    rows = client.query(
        DUE_TREES_SQL,
        parameters={
            "scope": SEARCH_SCOPE,
            "oldest": newest + TREE_WINDOW_HOURS * 3600,
            "newest": newest,
        },
    ).result_rows
    products = names_any(alias for aliases in radar.searches.values() for alias in aliases)
    return sorted(
        fullname
        for fullname, text in rows
        if fullname not in done and wants_tree(text.partition("\n")[0], products)
    )


def stored_ids(client: Client, fullnames: Sequence[str]) -> set[str]:
    """Which of these items are stored already: a tree's comments the r/all sample caught,
    or a tree fetched before the ingester restarted."""
    if not fullnames:
        return set()
    rows = client.query(
        "SELECT DISTINCT id FROM items WHERE id IN {ids:Array(String)}",
        parameters={"ids": list(fullnames)},
    ).result_rows
    return {fullname for (fullname,) in rows}
