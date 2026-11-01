"""What the API returns: one Pydantic model per response, from which FastAPI writes the
OpenAPI schema and orval the page's TypeScript types (web/src/api/generated/).

Conventions (docs/WEB-DASHBOARD.md §5.2): times are UTC with a Z, days ISO dates; what can be
missing is `None` (null), never 1970-01-01; numbers that can be infinite or NaN are typed
`float | None` and serialized as null. Field names follow the SQL's column aliases.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
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


class Explore(Model):
    terms: list[str]
    bucket: Literal["hour", "day", "week"]
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
