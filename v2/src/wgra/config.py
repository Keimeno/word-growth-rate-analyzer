"""Configuration: what to track (config.yaml) and secrets/connections (environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

# every tracked subreddit is also part of this group, so dashboards and queries can
# always fall back to "everything we track completely"
TRACKED_GROUP = "tracked"
# Everything the background sample finds in subreddits we don't track is counted under
# this one name. Per subreddit, a sample of a few percent would be far too thin to say
# anything, and thousands of tiny subreddits would mostly add rows that are counted
# once. Subreddit names can't start with an underscore, so it can't clash with one.
SAMPLE_SCOPE = "_sample"
SAMPLE_GROUP = "sample"


@dataclass(frozen=True)
class IngestConfig:
    # reddit allows 100 requests per minute per OAuth client, keep some headroom
    requests_per_minute: float = 90
    # subreddits are polled together as multireddits (r/a+b+c), this caps the url length
    max_subreddits_per_feed: int = 25
    min_poll_interval: float = 2.0
    max_comment_poll_interval: float = 300.0
    max_post_poll_interval: float = 900.0
    # longest phrase (in words) that is counted
    max_ngram: int = 3


@dataclass(frozen=True)
class BackgroundConfig:
    """A sample of all of reddit, used as the "normal" vocabulary to compare against."""

    subreddit: str = "all"
    # 0 disables the background sample
    requests_per_minute: float = 20
    # the sample is only the "normal" vocabulary to compare against, trigrams of thousands
    # of unrelated subreddits would mostly be stored once and never looked at again
    max_ngram: int = 2


@dataclass(frozen=True)
class Config:
    groups: dict[str, tuple[str, ...]]
    # subreddit -> language code, subreddits without an entry are english
    languages: dict[str, str] = field(default_factory=dict)
    background: BackgroundConfig = field(default_factory=BackgroundConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)

    @cached_property
    def subreddits(self) -> tuple[str, ...]:
        return tuple(sorted({sub for subs in self.groups.values() for sub in subs}))

    def language(self, subreddit: str) -> str:
        return self.languages.get(subreddit.lower(), "en")

    def scope(self, subreddit: str) -> str:
        """Where an item's counts go: its subreddit if tracked, the sample otherwise."""
        return subreddit if subreddit in self._tracked else SAMPLE_SCOPE

    @cached_property
    def _tracked(self) -> frozenset[str]:
        return frozenset(self.subreddits)

    def group_memberships(self) -> list[tuple[str, str]]:
        """(group, subreddit) pairs, including the implicit "tracked" and "sample" groups."""
        pairs = [(group, sub) for group, subs in self.groups.items() for sub in subs]
        pairs += [(TRACKED_GROUP, sub) for sub in self.subreddits]
        pairs.append((SAMPLE_GROUP, SAMPLE_SCOPE))
        return sorted(set(pairs))


def _normalize_subreddit(name: str) -> str:
    return name.strip().removeprefix("/").removeprefix("r/").lower()


def parse_config(raw: dict[str, Any]) -> Config:
    groups = {
        str(group): tuple(sorted({_normalize_subreddit(sub) for sub in subs}))
        for group, subs in (raw.get("groups") or {}).items()
    }
    if not any(groups.values()):
        raise ValueError("config: at least one group with subreddits is required")
    for reserved in (TRACKED_GROUP, SAMPLE_GROUP):
        if reserved in groups:
            raise ValueError(f"config: the group name '{reserved}' is reserved")

    languages = {
        _normalize_subreddit(sub): str(language)
        for language, subs in (raw.get("languages") or {}).items()
        for sub in subs
    }

    return Config(
        groups=groups,
        languages=languages,
        background=BackgroundConfig(**(raw.get("background") or {})),
        ingest=IngestConfig(**(raw.get("ingest") or {})),
    )


def load_config(path: Path) -> Config:
    with path.open() as file:
        return parse_config(yaml.safe_load(file) or {})


@dataclass(frozen=True)
class Env:
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    author_hash_key: bytes
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_database: str

    @classmethod
    def from_environ(cls, require_reddit: bool = True) -> Env:
        required = ["CLICKHOUSE_PASSWORD"]
        if require_reddit:
            required += [
                "REDDIT_CLIENT_ID",
                "REDDIT_CLIENT_SECRET",
                "REDDIT_USER_AGENT",
                "AUTHOR_HASH_KEY",
            ]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)} (see .env)")

        return cls(
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
            reddit_user_agent=os.environ.get("REDDIT_USER_AGENT", ""),
            author_hash_key=os.environ.get("AUTHOR_HASH_KEY", "").encode(),
            clickhouse_host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
            clickhouse_port=int(os.environ.get("CLICKHOUSE_PORT", "3607")),
            clickhouse_user=os.environ.get("CLICKHOUSE_USER", "wgra"),
            clickhouse_password=os.environ["CLICKHOUSE_PASSWORD"],
            clickhouse_database=os.environ.get("CLICKHOUSE_DB", "wgra"),
        )
