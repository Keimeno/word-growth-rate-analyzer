"""From reddit items to the rows we store."""

from __future__ import annotations

import hashlib
import hmac
from collections import OrderedDict
from collections.abc import Hashable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from wgra.config import SAMPLE_SCOPE, Config
from wgra.reddit.models import RedditItem
from wgra.text import extract_terms

ITEM_COLUMNS = (
    "id",
    "source",
    "subreddit",
    "created_at",
    "author_hash",
    "text",
    "permalink",
    "token_count",
)
TERM_COLUMNS = ("hour", "subreddit", "source", "kind", "term", "author_hash", "occurrences")

DELETED_AUTHOR = "[deleted]"
DELETED_TEXTS = frozenset({"[deleted]", "[removed]"})
# raw text is only kept for 48h, for examples, it doesn't need to be complete
MAX_STORED_TEXT = 10_000
# short texts like "this" or "lol" are repeated naturally, only longer ones are copypasta
MIN_DUPLICATE_LENGTH = 40


class RecentKeys:
    """Remembers the most recently added keys, forgetting the oldest beyond capacity."""

    def __init__(self, capacity: int):
        self._capacity = capacity
        self._keys: OrderedDict[Hashable, None] = OrderedDict()

    def __len__(self) -> int:
        return len(self._keys)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._keys

    def add(self, key: Hashable) -> bool:
        """Adds the key, returns False if it was already known."""
        if key in self._keys:
            self._keys.move_to_end(key)
            return False
        self._keys[key] = None
        if len(self._keys) > self._capacity:
            self._keys.popitem(last=False)
        return True


@dataclass(frozen=True, slots=True)
class ProcessedItem:
    item_row: tuple[Any, ...]
    term_rows: list[tuple[Any, ...]]


def is_bot(author: str) -> bool:
    author = author.lower()
    return author == "automoderator" or author.endswith("bot")


class Processor:
    def __init__(self, config: Config, author_hash_key: bytes):
        self._config = config
        self._author_hash_key = author_hash_key
        self._recent_texts = RecentKeys(capacity=50_000)

    def author_hash(self, author: str) -> int:
        """A keyed hash, so stored values can't be linked back to reddit accounts."""
        if author == DELETED_AUTHOR:
            return 0
        digest = hmac.new(self._author_hash_key, author.lower().encode(), hashlib.sha256)
        return int.from_bytes(digest.digest()[:8], "big")

    def skip_reason(self, item: RedditItem) -> str | None:
        if item.text.strip() in DELETED_TEXTS:
            return "deleted"
        if is_bot(item.author):
            return "bot"
        if item.distinguished in ("moderator", "admin") or item.stickied:
            return "moderation"

        normalized = " ".join(item.text.lower().split())
        if len(normalized) >= MIN_DUPLICATE_LENGTH and not self._recent_texts.add(
            hashlib.blake2b(normalized.encode(), digest_size=16).digest()
        ):
            return "duplicate"
        return None

    def process(self, item: RedditItem) -> ProcessedItem:
        # untracked subreddits only reach us through the background sample, their counts
        # are pooled (the permalink still names the real subreddit)
        scope = self._config.scope(item.subreddit)
        terms = extract_terms(
            item.text,
            language=self._config.language(item.subreddit),
            max_ngram=(
                self._config.background.max_ngram
                if scope == SAMPLE_SCOPE
                else self._config.ingest.max_ngram
            ),
        )
        created_at = datetime.fromtimestamp(item.created_utc, UTC)
        hour = created_at.replace(minute=0, second=0, microsecond=0)
        author_hash = self.author_hash(item.author)

        item_row = (
            item.fullname,
            item.source,
            scope,
            created_at,
            author_hash,
            item.text[:MAX_STORED_TEXT],
            item.permalink,
            terms.token_count,
        )
        term_rows = [
            (hour, scope, item.source, kind, term, author_hash, occurrences)
            for (kind, term), occurrences in terms.counts.items()
        ]
        return ProcessedItem(item_row=item_row, term_rows=term_rows)
