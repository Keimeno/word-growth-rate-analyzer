"""`wgra suggest-subreddits`: untracked subreddits where rising terms show up early or
often, as candidates for config.yaml. It only prints, the config is never changed.

The r/all sample pools every untracked subreddit into one scope (`_sample`), but its raw
comments and posts (kept 48 hours) still name the real subreddit in their permalink. For
the terms trending now (the strongest of the last `hours` in any scope, words and
phrases, past the detector's warmup), every sampled item mentioning one is found (words
of the text and of the term matched the way the term explorer does).

A big subreddit mentions everything a lot (r/askreddit), so a subreddit only counts for a
term it over-indexes on: at least `min_mentions` mentions, and `min_ratio` times what its
share of the sampled items would give it. Per subreddit:

* terms: the rising terms it over-indexes on
* first: of those, the ones it was the first sampled subreddit to mention
* early: of those, the ones it mentioned before they first trended anywhere
* mentions, and its sampled items

Candidates are ranked by early, first, terms and mentions, and need `min_terms`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from clickhouse_connect.driver.client import Client

from wgra.config import SAMPLE_SCOPE
from wgra.detect.short_term import as_utc

# multiSearchAllPositions takes at most 255 needles
MAX_TERMS = 250

RISING_SQL = """
SELECT term, min(detected_at) AS first_trend
FROM trends
WHERE detected_at > toDateTime({since:UInt32}, 'UTC') - INTERVAL 7 DAY
  AND detected_at <= toDateTime({now:UInt32}, 'UTC')
  AND term IN (
      SELECT term FROM trends
      WHERE detected_at > toDateTime({since:UInt32}, 'UTC')
        AND detected_at <= toDateTime({now:UInt32}, 'UTC')
        AND subsumed_by = '' AND kind IN ('word', 'phrase') AND scope != 'sample'
        AND reference_days >= {min_reference_days:UInt16}
      GROUP BY term
      ORDER BY max(z) DESC
      LIMIT {limit:UInt32}
  )
GROUP BY term
"""

# the words of the text and of each term joined by single spaces, so "GPT-5" matches "gpt 5"
_WORDS = "concat(' ', arrayStringConcat(splitByNonAlpha(lowerUTF8({value})), ' '), ' ')"
_COMMUNITY = "lowerUTF8(extract(permalink, '^/r/([^/]+)/'))"

MATCHES_SQL = f"""
WITH arrayMap(t -> {_WORDS.format(value="t")}, {{terms:Array(String)}}) AS needles
SELECT community, term_index, min(created_at) AS first_at, count() AS mentions
FROM (
    SELECT {_COMMUNITY} AS community, created_at,
           multiSearchAllPositionsUTF8({_WORDS.format(value="text")}, needles) AS positions
    FROM items
    WHERE subreddit = {{sample:String}}
      AND created_at > toDateTime({{since:UInt32}}, 'UTC')
      AND created_at <= toDateTime({{now:UInt32}}, 'UTC')
)
ARRAY JOIN arrayFilter(i -> positions[i] > 0, arrayEnumerate(positions)) AS term_index
WHERE community != ''
GROUP BY community, term_index
"""

ITEMS_SQL = f"""
SELECT {_COMMUNITY} AS community, count()
FROM items
WHERE subreddit = {{sample:String}}
  AND created_at > toDateTime({{since:UInt32}}, 'UTC')
  AND created_at <= toDateTime({{now:UInt32}}, 'UTC')
GROUP BY community
"""


@dataclass
class Candidate:
    subreddit: str
    items: int
    terms: int = 0
    first: int = 0
    early: int = 0
    mentions: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        """The share of its sampled items mentioning a rising term (an item mentioning two
        counts twice)."""
        return self.mentions / self.items if self.items else 0.0


@dataclass
class Suggestions:
    since: datetime
    now: datetime
    rising: int
    sampled_items: int
    candidates: list[Candidate]


def suggest(
    client: Client,
    tracked: Collection[str],
    now: datetime,
    hours: int = 48,
    terms: int = 100,
    min_terms: int = 2,
    min_mentions: int = 2,
    min_ratio: float = 3.0,
    min_reference_days: int = 3,
    limit: int = 25,
) -> Suggestions:
    """Untracked subreddits to consider, from the sample's items of the last `hours` (at
    most 48, they're deleted after that) and the strongest trends of the same time.
    `min_reference_days`: trends of scopes with less history don't count (warmup), 0
    counts them."""
    now = as_utc(now)
    since = now - timedelta(hours=min(hours, 48))
    parameters = {
        "since": int(since.timestamp()),
        "now": int(now.timestamp()),
        "limit": min(terms, MAX_TERMS),
        "sample": SAMPLE_SCOPE,
        "min_reference_days": min_reference_days,
    }
    rising = {
        term: as_utc(first)
        for term, first in client.query(RISING_SQL, parameters=parameters).result_rows
    }
    items: dict[str, int] = {
        community: int(count)
        for community, count in client.query(ITEMS_SQL, parameters=parameters).result_rows
    }
    sampled = sum(items.values())
    if not rising or not sampled:
        return Suggestions(since, now, len(rising), sampled, [])

    ordered = sorted(rising)
    rows = client.query(MATCHES_SQL, parameters=parameters | {"terms": ordered}).result_rows
    # per term: its mentions in the whole sample, and who mentioned it first
    total: dict[str, int] = {}
    first_seen: dict[str, tuple[datetime, str]] = {}
    for community, term_index, first_at, mentions in rows:
        term = ordered[term_index - 1]
        total[term] = total.get(term, 0) + int(mentions)
        if term not in first_seen or as_utc(first_at) < first_seen[term][0]:
            first_seen[term] = (as_utc(first_at), community)

    excluded = {subreddit.lower() for subreddit in tracked}
    candidates: dict[str, Candidate] = {}
    for community, term_index, first_at, mentions in rows:
        term = ordered[term_index - 1]
        expected = items.get(community, 0) * total[term] / sampled
        if community in excluded or mentions < max(min_mentions, min_ratio * expected):
            continue
        candidate = candidates.setdefault(community, Candidate(community, items.get(community, 0)))
        candidate.terms += 1
        candidate.mentions += int(mentions)
        candidate.early += as_utc(first_at) < rising[term]
        candidate.first += first_seen[term][1] == community
        candidate.examples.append(term)

    ranked = sorted(
        (c for c in candidates.values() if c.terms >= min_terms),
        key=lambda c: (c.early, c.first, c.terms, c.mentions, c.share),
        reverse=True,
    )
    for candidate in ranked:
        candidate.examples.sort(key=lambda term: (first_seen[term][1] != candidate.subreddit, term))
    return Suggestions(since, now, len(rising), sampled, ranked[:limit])


def yaml_snippet(candidates: list[Candidate]) -> str:
    """Lines to paste under a group in config.yaml, with why each is suggested."""
    return "\n".join(
        f"    - {c.subreddit:<24} # {c.terms} rising terms, first for {c.first}, "
        f"{c.early} before they trended"
        for c in candidates
    )
