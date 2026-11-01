"""Configuration: what to track (config.yaml) and secrets/connections (environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from undercurrent.sources.reddit import channels as reddit_channels
from undercurrent.text.intents import INTENT_KINDS

# The platforms and the kinds of documents each has. Every platform's tracked channels
# also form a group named like the platform ("reddit": every tracked subreddit), so
# dashboards and queries can always fall back to "everything we track completely".
PLATFORM_DOC_TYPES = {reddit_channels.PLATFORM: reddit_channels.DOC_TYPES}

# what the text says: words, phrases, linked domains, mentioned subreddits. The intents
# behind it (switches, alternatives, complaints, needs) are kinds of terms too.
TEXT_KINDS = ("word", "phrase", "domain", "subreddit")
KINDS = (*TEXT_KINDS, *INTENT_KINDS)


def ranking(kind: str) -> str:
    """Terms are ranked against the others of their ranking: words, phrases, domains and
    subreddits together, each intent kind on its own. A switch between two products is
    mentioned a few times a day, it would never make the top 50 of a scope's words."""
    return kind if kind in INTENT_KINDS else "text"


def _intent_defaults[T](value: T) -> dict[str, T]:
    return dict.fromkeys(INTENT_KINDS, value)


@dataclass(frozen=True)
class IngestConfig:
    # longest phrase (in words) that is counted, background channels have their own
    max_ngram: int = 3


@dataclass(frozen=True)
class IntentsConfig:
    """Why people mention things: switches, alternatives, complaints and needs, extracted
    by the ingester (raw text is deleted after 48 hours, later is too late). See
    docs/ARCHITECTURE.md §4.7."""

    enabled: bool = True
    # also in background channels (the r/all sample): platform-wide intents, and the prior
    # for scoring them
    sample: bool = True


@dataclass(frozen=True)
class RedditSampleConfig:
    """A sample of all of reddit, the channel r/all: the "normal" vocabulary to compare
    against."""

    # 0 disables the sample
    requests_per_minute: float = 20
    # the sample is only the "normal" vocabulary to compare against, trigrams of thousands
    # of unrelated subreddits would mostly be stored once and never looked at again
    max_ngram: int = 2


@dataclass(frozen=True)
class RedditConfig:
    enabled: bool = True
    # reddit allows 100 requests per minute per OAuth client, keep some headroom
    requests_per_minute: float = 90
    # subreddits are polled together as multireddits (r/a+b+c), this caps the url length
    max_subreddits_per_feed: int = 25
    min_poll_interval: float = 2.0
    max_comment_poll_interval: float = 300.0
    max_post_poll_interval: float = 900.0
    sample: RedditSampleConfig = field(default_factory=RedditSampleConfig)


@dataclass(frozen=True)
class PlatformsConfig:
    """Where documents come from, each platform a source of its own."""

    reddit: RedditConfig = field(default_factory=RedditConfig)

    def enabled(self) -> list[str]:
        return [reddit_channels.PLATFORM] if self.reddit.enabled else []


@dataclass(frozen=True)
class Channel:
    """What's collected and counted, a tracked subreddit or the r/all sample. Its id
    carries its platform ("r/technology"), so ids of different platforms can't clash."""

    id: str
    platform: str
    language: str = "en"
    # the detectors see it: not r/_search, whose counts aren't shares of anything
    analyzed: bool = True
    # the platform channel, its whole platform: the prior of its platform's scores
    background: bool = False
    # how it reads in messages, when not by its id
    label: str = ""


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
    # the kinds of documents counted (comment, post), empty for every type of every platform
    doc_types: tuple[str, ...] = ()
    kinds: tuple[str, ...] = KINDS
    # per kind, only the thresholds that differ (on top of the scope's): intents are far
    # rarer than words, a switch between two products is news at 3 mentions a day
    kind_thresholds: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            kind: {"min_mentions": 3, "min_authors": 3} for kind in INTENT_KINDS
        }
    )
    # the prior: every term's share in the r/all sample over this many days
    prior_days: int = 90
    # how many documents the prior is worth, as a share of the window's documents
    prior_weight: float = 0.05
    # pseudo-mentions every term gets on top, so brand-new terms get finite scores
    prior_floor: float = 1.0
    # a term with at most this many mentions in the reference period is "new"
    new_max_reference: int = 2
    # breadth of a group trend: member channels where the term has z above this
    breadth_min_z: float = 3.0
    breadth_min_mentions: int = 3
    # stored per scope and horizon on every run, by score: the words, phrases, domains and
    # subreddits, and separately each intent kind (see `ranking`)
    max_per_scope: int = 50
    max_per_intent: int = 20
    # no alerts until the reference period has data from this many days
    min_reference_days: int = 3
    # scopes that aren't scored at all
    exclude_scopes: tuple[str, ...] = ()

    def thresholds_for(self, scope: str, kind: str | None = None) -> Thresholds:
        thresholds = self.scope_thresholds.get(scope, self.thresholds)
        if kind and (overrides := self.kind_thresholds.get(kind)):
            thresholds = replace(thresholds, **overrides)
        return thresholds

    def max_stored(self, kind: str) -> int:
        return self.max_per_scope if ranking(kind) == "text" else self.max_per_intent


MACRO = "macro"
POOLED = "pooled"


@dataclass(frozen=True)
class LongTermConfig:
    """Long-term trends on weekly shares, see docs/ARCHITECTURE.md §4.3."""

    # windows in weeks, each runs once every scope's channels have that many complete
    # weeks of history (Monday to Sunday, UTC)
    horizons: tuple[int, ...] = (13, 26, 52)
    # when `undercurrent analyze` runs it every day, UTC. Posts are polled every 15 minutes, so
    # the last ones of Sunday are in by then.
    run_at: str = "00:30"
    # the volume floor: comments and posts mentioning the term per week, on average over
    # the window and in all of the scope's channels together
    min_mentions_per_week: float = 20
    # per kind, where it differs: intents are far rarer than words
    kind_min_mentions_per_week: dict[str, float] = field(
        default_factory=lambda: _intent_defaults(2.0)
    )
    # a group's weekly share: "macro" averages its channels' shares, so a big channel
    # doesn't drown out the small ones; "pooled" divides all mentions by all comments
    group_rate: str = MACRO
    # a group is analyzed over its channels with history for the whole window, if at
    # least this share of them have it
    min_member_share: float = 0.5
    # the first pass (least squares in ClickHouse) picks the terms growing or shrinking by
    # at least min_growth, the strongest this many per scope, window and ranking (the
    # words, phrases, domains and subreddits, and each intent kind) get the robust
    # statistics and are tested
    max_candidates: int = 100
    # added to the mentions of every week, so weeks without one have a finite log share
    pseudo_mentions: float = 0.5
    # a trend: Mann–Kendall p-value after Benjamini–Hochberg at most this (false discovery
    # rate across all terms tested in a run), and growing or shrinking by at least
    # min_growth per month (Theil–Sen)
    max_q: float = 0.05
    min_growth: float = 1.05
    # one-off: this share of the change comes from its spike_weeks highest weeks, and the
    # highest week is at least min_peak_ratio times the median week
    max_spike_share: float = 0.5
    spike_weeks: int = 2
    min_peak_ratio: float = 3.0
    # emerging when the trend line starts at most this many per 1,000 comments and posts,
    # mainstreaming above
    emerging_max_base: float = 1.0
    # stored per scope, window, category and ranking, by growth
    max_per_category: int = 25
    exclude_scopes: tuple[str, ...] = ()

    def min_mentions_per_week_for(self, kind: str) -> float:
        return self.kind_min_mentions_per_week.get(kind, self.min_mentions_per_week)


@dataclass(frozen=True)
class NotifyConfig:
    # instant alerts, only for the strongest trends
    alert_min_z: float = 10.0
    alert_min_authors: int = 20
    # or for a group, when the term trends in this many of its channels at once, and in
    # this share of those mentioning it
    alert_min_breadth: int = 3
    alert_min_breadth_share: float = 0.3
    max_alerts_per_day: int = 5
    # a term isn't alerted again within this time unless its score doubles
    cooldown_hours: int = 72
    # scopes that never alert and get no digest (they're still scored and shown)
    skip_scopes: tuple[str, ...] = (reddit_channels.SAMPLE,)
    # one digest per group every day at this local time
    digest_time: str = "08:00"
    timezone: str = "UTC"
    digest_size: int = 10
    # one report of long-term trends per group every week, on this day at this local time
    report_day: str = "monday"
    report_time: str = "08:00"
    # terms per category (emerging, mainstreaming, fading)
    report_size: int = 5
    # where tapping a notification leads: the web dashboard's term page (WEB_URL), with
    # Grafana as a second button, or Grafana's term explorer (GRAFANA_URL)
    links: str = "web"


@dataclass(frozen=True)
class LeadLagConfig:
    """Which channels pick up terms before others, see docs/ARCHITECTURE.md §4.6."""

    enabled: bool = True
    # when `undercurrent analyze` relearns the edges every day, UTC
    run_at: str = "01:00"
    # an event: a term trending (not subsumed) with at least this score in any scope; its
    # trends within the event's span belong to it, later ones start the next event
    event_min_z: float = 5.0
    # a scope's onset: the first hour in which its last window_hours, against the
    # reference_days before them (phase 2's scoring), pass these gates
    window_hours: int = 24
    reference_days: int = 28
    onset_min_mentions: int = 5
    # per kind, where it differs: intents are far rarer than words
    kind_onset_min_mentions: dict[str, int] = field(default_factory=lambda: _intent_defaults(3))
    onset_min_ratio: float = 2.0
    onset_min_z: float = 3.0
    # no onsets in a scope with less history than this
    min_reference_days: int = 3
    # onsets are looked for from this many hours before an event's first trend
    lookback_hours: int = 72
    # a follower follows when its onset comes after the leader's, at most this many days
    # later. An event spans lookback_hours before its first trend to 2 × max_lag_days after.
    max_lag_days: int = 7
    # edges are learned from the events of this many days
    training_days: int = 180
    # an edge: at least min_events leader onsets the follower hadn't started before (and
    # whose outcome is known), min_hits of them followed, and a q-value of at most max_q:
    # a one-sided binomial test against the follower's base rate, Benjamini–Hochberg over
    # every pair with min_events
    min_events: int = 5
    min_hits: int = 3
    max_q: float = 0.05
    # and the leader must be first in at least this share of the events where both crossed
    # within max_lag_days of each other: scopes that pick up the same stories in either
    # order are associated, but neither leads
    min_lead_share: float = 0.7
    # the probability shrinks to the base rate by this many pseudo-events, so a handful of
    # events can't make a certainty
    prior_events: float = 4.0
    # the central probability interval stored with edges and forecasts: 0.8 is the 10th to
    # the 90th percentile
    interval: float = 0.8
    # edges per topic (the group an event trended in most) besides those over all events.
    # Each topic is another look at the same data: their edges need max_q / topics.
    topics: bool = True

    def onset_min_mentions_for(self, kind: str) -> int:
        return self.kind_onset_min_mentions.get(kind, self.onset_min_mentions)


@dataclass(frozen=True)
class ForecastConfig:
    """Forecasts: a leader's burst that its followers haven't picked up yet."""

    enabled: bool = True
    # a forecast needs an edge with at least this lift and, after the time since the
    # leader's onset, at least this probability
    min_probability: float = 0.3
    min_lift: float = 1.5
    # ntfy alerts for forecasts, off until `undercurrent replay --forecast` shows they're worth it.
    # They count against notify.max_alerts_per_day like trend alerts, and get at most
    # alert_max_per_day of it.
    alert: bool = False
    alert_min_probability: float = 0.6
    alert_min_events: int = 10
    alert_max_per_day: int = 2


@dataclass(frozen=True)
class WikipediaConfig:
    """Optional: do reddit onsets come before interest on Wikipedia? Free, no key."""

    enabled: bool = False
    project: str = "en.wikipedia"
    # Wikimedia asks for a descriptive user agent with a way to contact you
    user_agent: str = "undercurrent/2.0 (https://github.com/Keimeno/word-growth-rate-analyzer)"
    # far below the API's limits
    requests_per_second: float = 5.0
    # interest on Wikipedia starts on the first day with at least min_views views and
    # min_ratio times the median of the 28 days before
    min_views: int = 100
    min_ratio: float = 3.0
    # events looked up per daily run
    max_events_per_day: int = 200


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# what separates the parts of intent terms ("notion → obsidian", "reason: notion · price")
# can't be part of a product's name
_PRODUCT_RESERVED = ("→", ":", "·")


@dataclass(frozen=True)
class Watchlist:
    """Products of one category and the channels where the category talks, see
    docs/CHURN-RADAR.md §2.1."""

    name: str
    # the group of config.yaml whose channels are the category's, tracked completely
    group: str
    # canonical name -> every name it's written as, lowercase, the canonical one first
    products: dict[str, tuple[str, ...]]
    # also search all of reddit for posts naming a product
    search: bool = True

    @cached_property
    def _products_by_alias(self) -> dict[str, str]:
        return {alias: product for product, aliases in self.products.items() for alias in aliases}

    def product(self, name: str) -> str | None:
        """The product an alias or an intent's entity names, None if it isn't watched."""
        return self._products_by_alias.get(name.lower())


@dataclass(frozen=True)
class RadarConfig:
    """The churn radar: per watchlist, who leaves which product, for what and why. See
    docs/CHURN-RADAR.md."""

    enabled: bool = False
    watchlists: dict[str, Watchlist] = field(default_factory=dict)
    # every product of a watchlist with search is searched for this often
    search_interval_minutes: float = 15
    # a post the search found whose title asks or tells about a switch gets its comment
    # tree fetched once, this long after it was posted, when most answers are in
    tree_after_hours: float = 24

    @cached_property
    def searches(self) -> dict[str, tuple[str, ...]]:
        """Product -> its aliases, for every product searched for (once, however many
        watchlists have it)."""
        searches: dict[str, tuple[str, ...]] = {}
        for watchlist in self.watchlists.values():
            if self.enabled and watchlist.search:
                for product, aliases in watchlist.products.items():
                    searches[product] = tuple(dict.fromkeys((*searches.get(product, ()), *aliases)))
        return searches

    @cached_property
    def names(self) -> frozenset[str]:
        """Single-word aliases of the watched products. Intents count them as names in any
        case, like the hand-kept products_*.txt: "switched from evernote to obsidian"."""
        if not self.enabled:
            return frozenset()
        return frozenset(
            alias
            for watchlist in self.watchlists.values()
            for aliases in watchlist.products.values()
            for alias in aliases
            if " " not in alias
        )


@dataclass(frozen=True)
class Config:
    # group -> the ids of its channels ("r/technology")
    groups: dict[str, tuple[str, ...]]
    # channel -> language code, channels without an entry are english
    languages: dict[str, str] = field(default_factory=dict)
    platforms: PlatformsConfig = field(default_factory=PlatformsConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    intents: IntentsConfig = field(default_factory=IntentsConfig)
    detect: DetectConfig = field(default_factory=DetectConfig)
    long_term: LongTermConfig = field(default_factory=LongTermConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    lead_lag: LeadLagConfig = field(default_factory=LeadLagConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    wikipedia: WikipediaConfig = field(default_factory=WikipediaConfig)
    radar: RadarConfig = field(default_factory=RadarConfig)

    @cached_property
    def _channels(self) -> dict[str, Channel]:
        listed = sorted({channel for channels in self.groups.values() for channel in channels})
        channels = {
            channel: Channel(channel, reddit_channels.PLATFORM, self.language(channel))
            for channel in listed
        }
        channels[reddit_channels.SAMPLE] = Channel(
            reddit_channels.SAMPLE,
            reddit_channels.PLATFORM,
            self.language(reddit_channels.SAMPLE),
            background=True,
            label=reddit_channels.SAMPLE_LABEL,
        )
        channels[reddit_channels.SEARCH] = Channel(
            reddit_channels.SEARCH, reddit_channels.PLATFORM, analyzed=False
        )
        return channels

    def channels(self) -> tuple[Channel, ...]:
        """Every channel: those the groups list, and each platform's own (r/all, r/_search)."""
        return tuple(self._channels.values())

    def channel(self, channel: str) -> Channel | None:
        return self._channels.get(channel)

    def tracked(self, platform: str) -> tuple[str, ...]:
        """The channels of a platform that groups list, collected completely: for reddit
        the tracked subreddits."""
        return tuple(
            channel.id
            for channel in self._channels.values()
            if channel.platform == platform and channel.analyzed and not channel.background
        )

    def language(self, channel: str) -> str:
        return self.languages.get(channel.lower(), "en")

    def doc_types(self) -> tuple[str, ...]:
        """The kinds of documents the detectors count: detect.doc_types, or every type of
        every platform."""
        return self.detect.doc_types or tuple(
            doc_type for types in PLATFORM_DOC_TYPES.values() for doc_type in types
        )

    def scope_names(self) -> frozenset[str]:
        """Every scope: each channel, each group, each platform's group."""
        return frozenset(
            [*self._channels, *self.groups, *(name for name, _ in self.group_memberships())]
        )

    def max_ngram(self, channel: str) -> int:
        """The longest phrase counted in a channel: background channels have their own."""
        info = self._channels.get(channel)
        if info is not None and info.background:
            return self.platforms.reddit.sample.max_ngram
        return self.ingest.max_ngram

    def counts_intents(self, channel: str) -> bool:
        info = self._channels.get(channel)
        background = info is not None and info.background
        return self.intents.enabled and (self.intents.sample or not background)

    def is_tracked(self, channel: str) -> bool:
        return channel in self._tracked

    @cached_property
    def _tracked(self) -> frozenset[str]:
        return frozenset(
            channel
            for channel, info in self._channels.items()
            if info.analyzed and not info.background
        )

    def group_memberships(self) -> list[tuple[str, str]]:
        """(group, channel) pairs, including each platform's group of its tracked channels
        ("reddit")."""
        pairs = [
            (group, channel) for group, channels in self.groups.items() for channel in channels
        ]
        for platform in PLATFORM_DOC_TYPES:
            pairs += [(platform, channel) for channel in self.tracked(platform)]
        return sorted(set(pairs))


def _channel_id(name: object, where: str) -> str:
    """A channel id as config.yaml writes it, lowercase. Bare names are an error, they're
    subreddits or groups."""
    channel = str(name).strip().removeprefix("/").lower()
    if reddit_channels.is_channel(channel):
        return channel
    hint = f"write r/{channel}" if channel and "/" not in channel else "like r/technology"
    raise ValueError(f"config: {where}: '{name}' isn't a channel id, {hint}")


def parse_groups(raw: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    groups = {
        str(group): tuple(
            sorted({_channel_id(channel, f"groups.{group}") for channel in channels or ()})
        )
        for group, channels in raw.items()
    }
    if not any(groups.values()):
        raise ValueError("config: at least one group with channels is required")
    for group, channels in groups.items():
        if group.lower() in PLATFORM_DOC_TYPES:
            raise ValueError(
                f"config: the group name '{group}' is reserved, it's every tracked channel of "
                "the platform"
            )
        if reddit_channels.is_channel(group.strip().removeprefix("/").lower()):
            raise ValueError(
                f"config: the group '{group}' is named like a channel, give it another name"
            )
        if reddit_channels.SEARCH in channels:
            raise ValueError(
                f"config: groups.{group}: {reddit_channels.SEARCH} can't be in a group, the "
                "detectors don't see it"
            )
    return groups


# where the reddit keys of before the platforms section went
_MOVED = {"background": "platforms.reddit.sample"}


def parse_platforms(raw: dict[str, Any]) -> PlatformsConfig:
    raw = dict(raw)
    reddit = dict(raw.pop("reddit", None) or {})
    if raw:
        raise ValueError(f"config: platforms: unknown {', '.join(sorted(raw))}")
    sample = RedditSampleConfig(**(reddit.pop("sample", None) or {}))
    return PlatformsConfig(reddit=RedditConfig(sample=sample, **reddit))


def parse_ingest(raw: dict[str, Any]) -> IngestConfig:
    moved = sorted(set(raw) & set(RedditConfig.__dataclass_fields__))
    if moved:
        raise ValueError(f"config: ingest.{moved[0]} is now in platforms.reddit")
    return IngestConfig(**raw)


def parse_config(raw: dict[str, Any]) -> Config:
    for old, new in _MOVED.items():
        if old in raw:
            raise ValueError(f"config: {old} is now {new}")
    groups = parse_groups(raw.get("groups") or {})
    languages = {
        _channel_id(channel, f"languages.{language}"): str(language)
        for language, channels in (raw.get("languages") or {}).items()
        for channel in channels or ()
    }

    config = Config(
        groups=groups,
        languages=languages,
        platforms=parse_platforms(raw.get("platforms") or {}),
        ingest=parse_ingest(raw.get("ingest") or {}),
        intents=IntentsConfig(**(raw.get("intents") or {})),
        detect=parse_detect(raw.get("detect") or {}),
        long_term=parse_long_term(raw.get("long_term") or {}),
        notify=parse_notify(raw.get("notify") or {}),
        lead_lag=parse_lead_lag(raw.get("lead_lag") or {}),
        forecast=parse_forecast(raw.get("forecast") or {}),
        wikipedia=WikipediaConfig(**(raw.get("wikipedia") or {})),
        radar=parse_radar(raw.get("radar") or {}, groups),
    )
    _check_scopes(config)
    return config


def _check_scopes(config: Config) -> None:
    """Scopes named in the settings must exist: a channel id or a group."""
    known = config.scope_names()
    named = {
        "detect.scopes": config.detect.scope_thresholds,
        "detect.exclude_scopes": config.detect.exclude_scopes,
        "long_term.exclude_scopes": config.long_term.exclude_scopes,
        "notify.skip_scopes": config.notify.skip_scopes,
    }
    for where, scopes in named.items():
        if unknown := sorted(set(scopes) - known):
            raise ValueError(
                f"config: {where}: no channel or group {', '.join(map(repr, unknown))}"
            )


def _check_time(name: str, value: str) -> None:
    hours, _, minutes = value.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and int(hours) < 24 and int(minutes) < 60):
        raise ValueError(f"config: {name} must look like 08:00: {value}")


def _normalize_scope(scope: str) -> str:
    """Groups by name, channels by their id (lowercase, like everywhere else)."""
    scope = scope.strip().removeprefix("/")
    return scope.lower() if reddit_channels.is_channel(scope.lower()) else scope


def _per_kind(name: str, raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Per-kind settings from config.yaml on top of the defaults, kinds checked."""
    unknown = set(raw) - set(KINDS)
    if unknown:
        raise ValueError(f"config: {name} has unknown kinds: {', '.join(sorted(unknown))}")
    return defaults | raw


def parse_detect(raw: dict[str, Any]) -> DetectConfig:
    raw = dict(raw)
    threshold_names = set(Thresholds.__dataclass_fields__)
    thresholds = Thresholds(**{key: raw.pop(key) for key in list(raw) if key in threshold_names})
    scope_thresholds = {
        _normalize_scope(str(scope)): replace(thresholds, **overrides)
        for scope, overrides in (raw.pop("scopes", None) or {}).items()
    }
    detect = DetectConfig(thresholds=thresholds, scope_thresholds=scope_thresholds)
    if "kind_thresholds" in raw:
        kind_thresholds = _per_kind(
            "detect.kind_thresholds",
            {
                kind: {**detect.kind_thresholds.get(kind, {}), **(overrides or {})}
                for kind, overrides in (raw.pop("kind_thresholds") or {}).items()
            },
            detect.kind_thresholds,
        )
        for kind, overrides in kind_thresholds.items():
            if unknown := set(overrides) - threshold_names:
                raise ValueError(
                    f"config: detect.kind_thresholds.{kind}: unknown {', '.join(sorted(unknown))}"
                )
        detect = replace(detect, kind_thresholds=kind_thresholds)
    if "horizons" in raw:
        horizons = tuple(
            Horizon(name=str(name), **(options or {}))
            for name, options in (raw.pop("horizons") or {}).items()
        )
        if not horizons:
            raise ValueError("config: detect.horizons needs at least one horizon")
        detect = replace(detect, horizons=horizons)
    for name in ("doc_types", "kinds"):
        if name in raw:
            raw[name] = tuple(raw[name] or ())
    if "exclude_scopes" in raw:
        raw["exclude_scopes"] = tuple(map(_normalize_scope, raw["exclude_scopes"] or ()))
    return replace(detect, **raw)


def parse_long_term(raw: dict[str, Any]) -> LongTermConfig:
    raw = dict(raw)
    if "kind_min_mentions_per_week" in raw:
        raw["kind_min_mentions_per_week"] = _per_kind(
            "long_term.kind_min_mentions_per_week",
            raw["kind_min_mentions_per_week"] or {},
            LongTermConfig().kind_min_mentions_per_week,
        )
    if "horizons" in raw:
        raw["horizons"] = tuple(sorted({int(weeks) for weeks in raw["horizons"] or ()}))
        if any(weeks < 4 for weeks in raw["horizons"]):
            raise ValueError("config: long_term.horizons are weeks, at least 4")
    if "exclude_scopes" in raw:
        raw["exclude_scopes"] = tuple(map(_normalize_scope, raw["exclude_scopes"] or ()))
    long_term = LongTermConfig(**raw)
    _check_time("long_term.run_at", long_term.run_at)
    if long_term.group_rate not in (MACRO, POOLED):
        raise ValueError(f"config: long_term.group_rate is macro or pooled: {long_term.group_rate}")
    if long_term.min_growth <= 1:
        raise ValueError("config: long_term.min_growth is a factor above 1, like 1.05 for 5%")
    return long_term


def parse_notify(raw: dict[str, Any]) -> NotifyConfig:
    raw = dict(raw)
    if "skip_scopes" in raw:
        raw["skip_scopes"] = tuple(map(_normalize_scope, raw["skip_scopes"] or ()))
    if "report_day" in raw:
        raw["report_day"] = str(raw["report_day"]).lower()
    notify = NotifyConfig(**raw)
    _check_time("notify.digest_time", notify.digest_time)
    _check_time("notify.report_time", notify.report_time)
    if notify.report_day not in WEEKDAYS:
        raise ValueError(f"config: notify.report_day is a weekday: {notify.report_day}")
    if notify.links not in ("web", "grafana"):
        raise ValueError(f"config: notify.links is web or grafana: {notify.links}")
    ZoneInfo(notify.timezone)  # raises for unknown time zones
    return notify


def parse_lead_lag(raw: dict[str, Any]) -> LeadLagConfig:
    raw = dict(raw)
    if "kind_onset_min_mentions" in raw:
        raw["kind_onset_min_mentions"] = _per_kind(
            "lead_lag.kind_onset_min_mentions",
            raw["kind_onset_min_mentions"] or {},
            LeadLagConfig().kind_onset_min_mentions,
        )
    lead_lag = LeadLagConfig(**raw)
    _check_time("lead_lag.run_at", lead_lag.run_at)
    if not 0 < lead_lag.interval < 1:
        raise ValueError(f"config: lead_lag.interval is between 0 and 1: {lead_lag.interval}")
    if lead_lag.max_lag_days < 1 or lead_lag.window_hours < 1:
        raise ValueError("config: lead_lag.max_lag_days and window_hours must be positive")
    return lead_lag


def parse_forecast(raw: dict[str, Any]) -> ForecastConfig:
    forecast = ForecastConfig(**raw)
    for name in ("min_probability", "alert_min_probability"):
        if not 0 <= getattr(forecast, name) <= 1:
            raise ValueError(f"config: forecast.{name} is a probability, between 0 and 1")
    return forecast


def _product_name(value: object) -> str:
    return " ".join(str(value).lower().split())


def parse_watchlist(
    name: str, raw: dict[str, Any], groups: dict[str, tuple[str, ...]]
) -> Watchlist:
    raw = dict(raw)
    where = f"config: radar.watchlists.{name}"
    group = str(raw.pop("group", name))
    if group not in groups:
        raise ValueError(f"{where}: there is no group '{group}'")
    products: dict[str, tuple[str, ...]] = {}
    owners: dict[str, str] = {}
    for product, aliases in (raw.pop("products", None) or {}).items():
        canonical = _product_name(product)
        if not canonical or any(mark in canonical for mark in _PRODUCT_RESERVED):
            raise ValueError(f"{where}: '{product}' can't be a product's name")
        if isinstance(aliases, str):
            aliases = [aliases]
        written = dict.fromkeys([canonical, *map(_product_name, aliases or ())])
        names = tuple(alias for alias in written if alias)
        for alias in names:
            if owners.setdefault(alias, canonical) != canonical:
                raise ValueError(f"{where}: '{alias}' names both {owners[alias]} and {canonical}")
        products[canonical] = names
    if not products:
        raise ValueError(f"{where} needs products")
    return Watchlist(name=name, group=group, products=products, **raw)


def parse_radar(raw: dict[str, Any], groups: dict[str, tuple[str, ...]]) -> RadarConfig:
    raw = dict(raw)
    watchlists = {
        str(name): parse_watchlist(str(name), options or {}, groups)
        for name, options in (raw.pop("watchlists", None) or {}).items()
    }
    radar = RadarConfig(watchlists=watchlists, **raw)
    if radar.enabled and not radar.watchlists:
        raise ValueError("config: radar is enabled, but has no watchlists")
    if radar.search_interval_minutes < 1 or radar.tree_after_hours <= 0:
        raise ValueError("config: radar.search_interval_minutes and tree_after_hours too short")
    return radar


def load_config(path: Path) -> Config:
    with path.open() as file:
        return parse_config(yaml.safe_load(file) or {})


@dataclass(frozen=True)
class Env:
    """The connections and secrets every command needs. Each source reads its own
    credentials (REDDIT_* for reddit) when it's enabled."""

    # the ingester's secret for hashing author names
    author_hash_key: bytes
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_database: str
    # where alerts go: a self-hosted ntfy (see docker-compose.yml) or https://ntfy.sh
    ntfy_url: str = "http://localhost:3609"
    ntfy_topic: str = "undercurrent"
    # only for ntfy servers with access control
    ntfy_token: str = ""
    # how the phone reaches grafana, for the links in alerts
    grafana_url: str = "http://localhost:3608"
    # and the web dashboard, for the term page an alert opens and the notification's icon
    web_url: str = "http://localhost:3610"

    @classmethod
    def from_environ(cls, require_author_hash_key: bool = False) -> Env:
        """`require_author_hash_key`: for the ingester, which stores author hashes."""
        required = ["CLICKHOUSE_PASSWORD"]
        if require_author_hash_key:
            required.append("AUTHOR_HASH_KEY")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)} (see .env)")

        return cls(
            author_hash_key=os.environ.get("AUTHOR_HASH_KEY", "").encode(),
            clickhouse_host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
            clickhouse_port=int(os.environ.get("CLICKHOUSE_PORT", "3607")),
            clickhouse_user=os.environ.get("CLICKHOUSE_USER", "undercurrent"),
            clickhouse_password=os.environ["CLICKHOUSE_PASSWORD"],
            clickhouse_database=os.environ.get("CLICKHOUSE_DB", "undercurrent"),
            # empty counts as unset, .env.example lists them empty
            ntfy_url=(os.environ.get("NTFY_URL") or "http://localhost:3609").rstrip("/"),
            ntfy_topic=os.environ.get("NTFY_TOPIC") or "undercurrent",
            ntfy_token=os.environ.get("NTFY_TOKEN", ""),
            grafana_url=(os.environ.get("GRAFANA_URL") or "http://localhost:3608").rstrip("/"),
            web_url=(os.environ.get("WEB_URL") or "http://localhost:3610").rstrip("/"),
        )
