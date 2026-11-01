"""From items to the rows we store, the same for every source: the copypasta filter,
terms, intents and the author hash."""

from __future__ import annotations

import hashlib
import hmac
from collections import OrderedDict
from collections.abc import Hashable
from dataclasses import dataclass
from typing import Any

from undercurrent.config import Config
from undercurrent.sources.base import Item
from undercurrent.text import extract_terms
from undercurrent.text.intents import INTENT_KINDS, configure_names

ITEM_COLUMNS = (
    "id",
    "platform",
    "channel",
    "doc_type",
    "created_at",
    "author_hash",
    "text",
    "url",
    "lang",
    "token_count",
    "intents",
)
TERM_COLUMNS = ("hour", "channel", "doc_type", "kind", "term", "author_hash", "occurrences")

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


class Processor:
    def __init__(self, config: Config, author_hash_key: bytes):
        self._config = config
        self._author_hash_key = author_hash_key
        self._recent_texts = RecentKeys(capacity=50_000)
        configure_names(config.radar.names)

    def author_hash(self, platform: str, author: str) -> int:
        """A keyed hash, so stored values can't be linked back to accounts. Hashed with the
        platform: the same name on two platforms counts as two people, and identities are
        never linked across platforms."""
        if not author:
            return 0
        name = f"{platform}:{author.lower()}"
        digest = hmac.new(self._author_hash_key, name.encode(), hashlib.sha256)
        return int.from_bytes(digest.digest()[:8], "big")

    def skip_reason(self, item: Item) -> str | None:
        """Why an item isn't counted: what its source says, or copypasta."""
        if item.skip:
            return item.skip
        normalized = " ".join(item.text.lower().split())
        if len(normalized) >= MIN_DUPLICATE_LENGTH and not self._recent_texts.add(
            hashlib.blake2b(normalized.encode(), digest_size=16).digest()
        ):
            return "duplicate"
        return None

    def process(self, item: Item) -> ProcessedItem:
        """The rows to store for an item, its counts in its channel. Background channels
        (r/all) count shorter phrases, and intents only if intents.sample."""
        terms = extract_terms(
            item.text,
            language=item.lang,
            max_ngram=self._config.max_ngram(item.channel),
            intents=self._config.counts_intents(item.channel),
        )
        hour = item.created_at.replace(minute=0, second=0, microsecond=0)
        author_hash = self.author_hash(item.platform, item.author)

        item_row = (
            item.id,
            item.platform,
            item.channel,
            item.doc_type,
            item.created_at,
            author_hash,
            item.text[:MAX_STORED_TEXT],
            item.url,
            item.lang,
            terms.token_count,
            # the intents' terms, so dashboards can show the comments behind an intent
            sorted(term for kind, term in terms.counts if kind in INTENT_KINDS),
        )
        term_rows = [
            (hour, item.channel, item.doc_type, kind, term, author_hash, occurrences)
            for (kind, term), occurrences in terms.counts.items()
        ]
        return ProcessedItem(item_row=item_row, term_rows=term_rows)
