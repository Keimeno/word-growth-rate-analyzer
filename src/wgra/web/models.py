"""What the API returns: one Pydantic model per response, from which FastAPI writes the
OpenAPI schema and orval the page's TypeScript types (web/src/api/generated/).

Conventions (docs/WEB-DASHBOARD.md §5.2): times are UTC with a Z, days ISO dates; what can be
missing is `None` (null), never 1970-01-01; numbers that can be infinite or NaN are typed
`float | None` and serialized as null. Field names follow the SQL's column aliases.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _utc(value: datetime) -> datetime:
    # ClickHouse's DateTime('UTC') arrives without a timezone or with UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


Time = Annotated[datetime, AfterValidator(_utc)]
# a ratio, share or score: NaN and infinity become null
Num = float | None


class Model(BaseModel):
    model_config = ConfigDict(ser_json_inf_nan="null", validate_by_name=True)


ScopeType = Literal["platform", "group", "channel"]


# --- meta ---------------------------------------------------------------------------------


class Scope(Model):
    name: str
    type: ScopeType


class Meta(Model):
    """What the pickers offer, and what the page needs to know about the server."""

    scopes: list[Scope]
    groups: dict[str, list[str]]
    doc_types: list[str]
    platforms: list[str]
    word_kinds: list[str]
    intent_kinds: list[str]
    grafana_url: str
    now: Time = Field(description="The time every query is as of: now, or `as_of`")


# --- trends -------------------------------------------------------------------------------


class Trend(Model):
    scope: str
    scope_type: str
    term: str
    kind: str
    score: Num = Field(description="z: how far above its usual share, in standard errors")
    ratio: Num = Field(description="times its usual share")
    is_new: bool
    mentions: int
    authors: int
    breadth: int
    members: int
    mentions_before: int
    alert: str
    subsumed_by: str


class Trends(Model):
    last_run: Time | None
    reference_days: int | None
    trending: int
    alerts_sent: int
    trends: list[Trend]
    sparklines: dict[str, list[int]] = Field(
        description="each term's mentions per hour in the scope, the 7 days up to the run"
    )


class SharePoint(Model):
    time: Time
    term: str
    per_1000: Num


class DigestEntry(Model):
    term: str
    term_kind: str
    strongest_in: str
    score: Num
    is_new: bool
    ratio: Num
    mentions: int
    first_seen: Time
    last_seen: Time
    horizons: list[str]


class Alert(Model):
    time: Time
    horizon: str
    scope: str
    term: str
    kind: str
    alert: str
    score: Num
    is_new: bool
    ratio: Num
    mentions: int
    authors: int


class Rising(Model):
    term: str
    kind: str
    mentions: int
    authors: int
    mentions_before: int
    mentions_background: int
    usual_share: Num
    per_1000_now: Num
    per_1000_usual: Num
    times_usual: Num


# --- long-term ----------------------------------------------------------------------------


class LongTermTrend(Model):
    scope: str
    term: str
    kind: str
    category: str
    growth: Num
    q: Num
    start_share: Num
    end_share: Num
    mentions: int
    spike_share: Num
    peak: Num
    change: Num
    window_start: date
    weekly: list[Num]


class LongTerm(Model):
    last_run: Time | None
    analyzed_until: date | None
    weeks_of_history: int
    trends: list[LongTermTrend]


# --- spread: edges, forecasts, events -----------------------------------------------------


class Edge(Model):
    leader: str
    follower: str
    without_leader: bool
    follower_type: str
    lag_median: Num
    lag_q25: Num
    lag_q75: Num
    events: int
    hits: int
    hit_rate: Num
    base_rate: Num
    probability: Num
    probability_low: Num
    probability_high: Num
    lift: Num
    lead_share: Num
    q: Num
    leader_onsets: int


class Edges(Model):
    edges_learned: Time | None
    edge_count: int
    events: int
    closed_events: int
    pending: int
    precision_30d: Num
    resolved_30d: int
    forecast_alerts: int
    topics: list[str]
    leaders: list[str]
    edges: list[Edge]


class Forecast(Model):
    term: str
    kind: str
    leader: str
    follower: str
    without_leader: bool
    follower_type: str
    probability: Num
    probability_low: Num
    probability_high: Num
    base_rate: Num
    expected_at: Time
    due_by: Time
    leader_onset: Time
    created_at: Time
    edge_events: int
    lift: Num
    alert: str


class Onset(Model):
    scope: str
    at: Time


class Cascade(Model):
    term: str
    kind: str
    start: Time
    topic: str
    cascade: list[Onset]
    closed: bool


class ResolvedForecast(Model):
    created_at: Time
    term: str
    kind: str
    leader: str
    follower: str
    without_leader: bool
    probability: Num
    outcome: str
    warning_hours: int | None
    lag_hours: int | None
    expected_lag_hours: Num


class CalibrationBin(Model):
    bin: int
    forecasts: int
    predicted: Num
    came_true: Num
    base_rate: Num


class ForecastDay(Model):
    time: Time
    came_true: int
    missed: int
    pending: int


class WikipediaRecord(Model):
    events: int
    with_interest: int
    onset_first: int
    same_day: int
    wikipedia_first: int
    median_lead_days: Num


class ForecastRecord(Model):
    resolved: list[ResolvedForecast]
    calibration: list[CalibrationBin]
    daily: list[ForecastDay]
    wikipedia: WikipediaRecord


# --- intents ------------------------------------------------------------------------------


class IntentDay(Model):
    time: Time
    kind: str
    mentions: int


class Intents(Model):
    counts: dict[str, int]
    daily: list[IntentDay]
    since: date | None


class Flow(Model):
    from_: str = Field(alias="from")
    to: str
    mentions: int
    authors: int
    other_way: int
    per_10k: Num
    term: str


class Flows(Model):
    flows: list[Flow]
    first_day: date
    sparklines: dict[str, list[int]]


class RisingIntent(Model):
    entity: str
    mentions: int
    authors: int
    per_week_before: Num
    times_usual: Num
    excess: Num
    trend_z: Num
    term: str


class RisingIntents(Model):
    entries: list[RisingIntent]
    first_day: date
    sparklines: dict[str, list[int]]


class Need(Model):
    group_name: str
    need: str
    mentions: int
    authors: int
    term: str


class IntentExample(Model):
    time: Time
    channel: str
    doc_type: str
    found: list[str]
    text: str
    url: str


# --- explore ------------------------------------------------------------------------------


class ExplorePoint(Model):
    time: Time
    term: str
    mentions: int
    authors: int
    pooled: Num = Field(description="all mentions over all documents, per 1,000")
    macro: Num = Field(description="the average of the channels' shares, per 1,000")


class ExploreWhere(Model):
    term: str
    channel: str
    mentions: int
    authors: int
    per_1000: Num


class Bucket(StrEnum):
    hour = "hour"
    day = "day"
    week = "week"


class Explore(Model):
    terms: list[str]
    bucket: Bucket
    step: int | None = Field(description="seconds per bucket, for hours")
    from_: int = Field(alias="from")
    to: int
    points: list[ExplorePoint]
    where: list[ExploreWhere]


class Mention(Model):
    time: Time
    channel: str
    doc_type: str
    text: str
    url: str
    intents: list[str]


# --- ingestion ----------------------------------------------------------------------------


class Feed(Model):
    platform: str
    feed: str
    polls: int
    errors: int
    new_items: int
    gaps: int
    poll_every_s: Num
    items_per_minute: Num
    last_poll: Time


class ChannelVolume(Model):
    channel: str
    platform: str
    background: bool
    analyzed: bool
    documents: int
    by_type: list[tuple[str, int]]
    authors: int


class TableSize(Model):
    table: str
    rows: int
    bytes: int


class Ingestion(Model):
    documents_24h: int
    requests_10m: int
    gaps_24h: int
    sampled_share: Num
    last_poll: Time | None
    feeds: list[Feed]
    channels: list[ChannelVolume]
    storage: list[TableSize]


class FeedRate(Model):
    time: Time
    feed: str
    per_minute: Num


class RequestRate(Model):
    time: Time
    requests: Num
    errors: Num
    gaps: Num


class IngestionSeries(Model):
    step: int
    items: list[FeedRate]
    requests: list[RequestRate]


class Error(Model):
    error: str


# --- entities: terms, scopes, events, edges, products, alerts -----------------------------


class TermTrend(Model):
    """A term in the latest run of a horizon, in one scope."""

    horizon: str
    scope: str
    scope_type: str
    detected_at: Time
    score: Num
    ratio: Num
    is_new: bool
    mentions: int
    authors: int
    breadth: int
    members: int
    alert: str
    subsumed_by: str


class TermLongTerm(Model):
    horizon: str
    scope: str
    category: str
    growth: Num
    change: Num
    q: Num
    window_start: date
    week: date


class TermSummary(Model):
    kind: str
    term: str
    scope: str
    trending: list[TermTrend] = Field(description="the latest run of each horizon, strongest first")
    long_term: list[TermLongTerm]
    mentions_7d: int
    authors_7d: int
    first_seen: date | None
    sparkline: list[int] = Field(description="mentions per hour in the scope, the last 7 days")
    events: int
    pending_forecasts: int


class Run(Model):
    time: Time
    horizon: str
    scope: str
    score: Num
    ratio: Num
    alert: str


class TermOnset(Model):
    scope: str
    at: Time
    event_start: Time


class TermForecast(Model):
    leader: str
    follower: str
    without_leader: bool
    created_at: Time
    leader_onset: Time
    expected_at: Time
    due_by: Time
    probability: Num
    outcome: str
    follower_onset: Time | None


class Annotations(Model):
    runs: list[Run] = Field(
        description="the scored runs where it trended, in the scope or its members"
    )
    onsets: list[TermOnset]
    forecasts: list[TermForecast]
    long_term: list[TermLongTerm]


class Gate(Model):
    name: str
    label: str
    value: Num
    threshold: Num
    passed: bool


class MemberScore(Model):
    scope: str
    score: Num
    ratio: Num
    mentions: int


class Explanation(Model):
    """What a trend's score is made of, recomputed with the detector's own code."""

    scope: str
    scope_type: str
    horizon: str
    detected_at: Time
    mentions: int
    total: int
    reference_mentions: int
    reference_total: int
    authors: int
    reference_days: int
    share_now: Num = Field(description="mentions / total in the window")
    share_before: Num = Field(description="the same in the reference period")
    share_now_with_prior: Num
    share_before_with_prior: Num
    platform_share: Num = Field(description="the term's share in the platform's background")
    prior: Num = Field(description="α: pseudo-mentions the window got from the prior")
    log_odds: Num
    sigma: Num
    score: Num
    ratio: Num
    is_new: bool
    recomputed_score: Num = Field(description="z from detect/scoring.py with today's settings")
    gates: list[Gate]
    alert: str
    subsumed_by: str
    members: list[MemberScore]


class ScopeMember(Model):
    channel: str
    documents: int
    authors: int
    share: Num


class VolumePoint(Model):
    time: Time
    documents: int
    authors: int


class ScopeEdge(Model):
    leader: str
    follower: str
    without_leader: bool
    lift: Num
    probability: Num
    lag_median: Num
    events: int
    hits: int


class ScopeDetail(Model):
    name: str
    type: str
    platform: str | None
    members: list[ScopeMember]
    groups: list[str] = Field(description="the groups it's in")
    volume: list[VolumePoint]
    leads: list[ScopeEdge] = Field(description="edges where it or its channels lead")
    follows: list[ScopeEdge] = Field(description="edges where it or its channels follow")


class FullOnset(Model):
    scope: str
    without: str
    at: Time
    mentions: int
    ratio: Num
    score: Num


class EventSeries(Model):
    scope: str
    time: Time
    mentions: int
    per_1000: Num


class EventForecast(Model):
    leader: str
    follower: str
    created_at: Time
    probability: Num
    outcome: str
    expected_at: Time
    follower_onset: Time | None


class EventDetail(Model):
    kind: str
    term: str
    start: Time
    last_seen: Time
    topic: str
    closed: bool
    onsets: list[FullOnset]
    forecasts: list[EventForecast]
    series: list[EventSeries] = Field(description="per scope with an onset, share per hour")
    wikipedia_onset: date | None


class TermEvent(Model):
    kind: str
    term: str
    start: Time
    topic: str
    closed: bool
    cascade: list[Onset]


class TrainingEvent(Model):
    kind: str
    term: str
    start: Time
    leader_at: Time
    follower_at: Time | None
    lag_hours: Num


class EdgeForecast(Model):
    kind: str
    term: str
    created_at: Time
    probability: Num
    outcome: str
    lag_hours: Num


class EdgeDetail(Model):
    edge: Edge | None
    topic: str
    day: date | None
    lags: list[float]
    base_rate: Num
    training: list[TrainingEvent]
    forecasts: list[EdgeForecast]


class ProductFlow(Model):
    product: str
    mentions: int
    authors: int


class ProductDay(Model):
    time: Time
    kind: str
    mentions: int


class ProductDetail(Model):
    name: str
    flows_in: list[ProductFlow] = Field(description="switches to it, from where")
    flows_out: list[ProductFlow] = Field(description="switches away from it, to where")
    counts: dict[str, int] = Field(description="mentions per intent kind about it")
    daily: list[ProductDay]
    terms: list[str] = Field(description="its intent terms, for the comments")


class SentAlert(Model):
    time: Time
    kind: str
    scope: str
    term: str
    title: str
    message: str
    ok: bool
    term_kind: str | None
    horizon: str | None
    score: Num


class SearchHit(Model):
    kind: str
    term: str
    mentions: int
    last_seen: Time | None


# --- beyond Grafana -----------------------------------------------------------------------


class RelatedTerm(Model):
    kind: str
    term: str
    together: int = Field(description="comments and posts with both, of `documents`")
    ratio: Num = Field(description="how much more often it appears with the term than without")
    score: Num


class Related(Model):
    documents: int = Field(description="comments and posts of the last 48 hours with the term")
    terms: list[RelatedTerm]


class ChannelSeries(Model):
    channel: str
    onset: Time | None = Field(description="when its share first reached half its peak")
    mentions: int
    points: list[tuple[Time, Num]] = Field(description="share per 1,000 per bucket")


class SmallMultiples(Model):
    bucket: Bucket
    channels: list[ChannelSeries]


class HourOfWeek(Model):
    weekday: int = Field(description="1 is Monday")
    hour: int = Field(description="UTC")
    mentions: int
    relative: Num = Field(description="its share at that hour, divided by its overall share")


class CalendarDay(Model):
    day: date
    mentions: int
    per_1000: Num


class Rhythm(Model):
    hours: list[HourOfWeek]
    days: list[CalendarDay]


class RankPoint(Model):
    time: Time
    kind: str
    term: str
    rank: int


class MapNode(Model):
    scope: str
    median_lag: Num = Field(description="hours from a story's first onset to its own")
    events: int
    first_mover: int = Field(description="stories it was first in")
