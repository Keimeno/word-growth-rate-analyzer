"""Configuration: what to track (config.yaml) and secrets/connections (environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
class Horizon:
    """A window compared with the reference period before it."""

    name: str
    window_hours: int
    reference_days: int = 28
    # compare with the same hours of the day only, so a 6h window in the morning isn't
    # compared with nights ("breakfast" is always up in the morning)
    same_hours: bool = False


@dataclass(frozen=True)
class Thresholds:
    """What a term needs in the window to count as trending."""

    # comments and posts mentioning it
    min_mentions: int = 10
    # different people mentioning it, so one spammer or one thread can't make a trend
    min_authors: int = 5
    # times its usual share, exp(log odds)
    min_ratio: float = 2.0
    # strength of the evidence, the log odds divided by their standard error
    min_z: float = 3.0


@dataclass(frozen=True)
class DetectConfig:
    interval_minutes: int = 15
    horizons: tuple[Horizon, ...] = (
        Horizon("24h", 24),
        Horizon("6h", 6, same_hours=True),
    )
    thresholds: Thresholds = field(default_factory=Thresholds)
    # per scope ("tech", "r/de_EDV"), only the thresholds that differ
    scope_thresholds: dict[str, Thresholds] = field(default_factory=dict)
    sources: tuple[str, ...] = ("comment", "post")
    kinds: tuple[str, ...] = ("word", "phrase", "domain", "subreddit")
    # the prior: every term's share in the r/all sample over this many days
    prior_days: int = 90
    # how many documents the prior is worth, as a share of the window's documents
    prior_weight: float = 0.05
    # pseudo-mentions every term gets on top, so brand-new terms get finite scores
    prior_floor: float = 1.0
    # a term with at most this many mentions in the reference period is "new"
    new_max_reference: int = 2
    # breadth of a group trend: member subreddits where the term has z above this
    breadth_min_z: float = 3.0
    breadth_min_mentions: int = 3
    # stored per scope and horizon on every run, by score
    max_per_scope: int = 50
    # no alerts until the reference period has data from this many days
    min_reference_days: int = 3
    # scopes that aren't scored at all
    exclude_scopes: tuple[str, ...] = ()

    def thresholds_for(self, scope: str) -> Thresholds:
        return self.scope_thresholds.get(scope, self.thresholds)


@dataclass(frozen=True)
class NotifyConfig:
    # instant alerts, only for the strongest trends
    alert_min_z: float = 10.0
    alert_min_authors: int = 20
    # or for a group, when the term trends in this many of its subreddits at once, and in
    # this share of those mentioning it
    alert_min_breadth: int = 3
    alert_min_breadth_share: float = 0.3
    max_alerts_per_day: int = 5
    # a term isn't alerted again within this time unless its score doubles
    cooldown_hours: int = 72
    # scopes that never alert and get no digest (they're still scored and shown)
    skip_scopes: tuple[str, ...] = ("sample",)
    # one digest per group every day at this local time
    digest_time: str = "08:00"
    timezone: str = "UTC"
    digest_size: int = 10


@dataclass(frozen=True)
class Config:
    groups: dict[str, tuple[str, ...]]
    # subreddit -> language code, subreddits without an entry are english
    languages: dict[str, str] = field(default_factory=dict)
    background: BackgroundConfig = field(default_factory=BackgroundConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    detect: DetectConfig = field(default_factory=DetectConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

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
        detect=parse_detect(raw.get("detect") or {}),
        notify=parse_notify(raw.get("notify") or {}),
    )


def _normalize_scope(scope: str) -> str:
    """Groups by name, subreddits as "r/name" (lowercase, like everywhere else)."""
    scope = scope.strip().removeprefix("/")
    return f"r/{_normalize_subreddit(scope)}" if scope.lower().startswith("r/") else scope


def parse_detect(raw: dict[str, Any]) -> DetectConfig:
    raw = dict(raw)
    threshold_names = set(Thresholds.__dataclass_fields__)
    thresholds = Thresholds(**{key: raw.pop(key) for key in list(raw) if key in threshold_names})
    scope_thresholds = {
        _normalize_scope(str(scope)): replace(thresholds, **overrides)
        for scope, overrides in (raw.pop("scopes", None) or {}).items()
    }
    detect = DetectConfig(thresholds=thresholds, scope_thresholds=scope_thresholds)
    if "horizons" in raw:
        horizons = tuple(
            Horizon(name=str(name), **(options or {}))
            for name, options in (raw.pop("horizons") or {}).items()
        )
        if not horizons:
            raise ValueError("config: detect.horizons needs at least one horizon")
        detect = replace(detect, horizons=horizons)
    for name in ("sources", "kinds"):
        if name in raw:
            raw[name] = tuple(raw[name] or ())
    if "exclude_scopes" in raw:
        raw["exclude_scopes"] = tuple(map(_normalize_scope, raw["exclude_scopes"] or ()))
    return replace(detect, **raw)


def parse_notify(raw: dict[str, Any]) -> NotifyConfig:
    raw = dict(raw)
    if "skip_scopes" in raw:
        raw["skip_scopes"] = tuple(map(_normalize_scope, raw["skip_scopes"] or ()))
    notify = NotifyConfig(**raw)
    hours, _, minutes = notify.digest_time.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and int(hours) < 24 and int(minutes) < 60):
        raise ValueError(f"config: notify.digest_time must look like 08:00: {notify.digest_time}")
    ZoneInfo(notify.timezone)  # raises for unknown time zones
    return notify


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
    # where alerts go: a self-hosted ntfy (see docker-compose.yml) or https://ntfy.sh
    ntfy_url: str = "http://localhost:3609"
    ntfy_topic: str = "wgra"
    # only for ntfy servers with access control
    ntfy_token: str = ""
    # how the phone reaches grafana, for the links in alerts
    grafana_url: str = "http://localhost:3608"

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
            # empty counts as unset, .env.example lists them empty
            ntfy_url=(os.environ.get("NTFY_URL") or "http://localhost:3609").rstrip("/"),
            ntfy_topic=os.environ.get("NTFY_TOPIC") or "wgra",
            ntfy_token=os.environ.get("NTFY_TOKEN", ""),
            grafana_url=(os.environ.get("GRAFANA_URL") or "http://localhost:3608").rstrip("/"),
        )
