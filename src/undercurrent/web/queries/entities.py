"""The entities' pages (docs/WEB-DASHBOARD.md §6): a term, a scope, an event, an edge, a
product, the alerts sent, and the palette's search. Each query is a key range on the tables'
sorting keys or a small table; the term's runs across scopes use the bloom filter on
`trends.term` (migration 005)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from undercurrent.config import Config
from undercurrent.detect.scoring import Counts, Prior
from undercurrent.text.intents import INTENT_KINDS
from undercurrent.web.models import (
    Annotations,
    Edge,
    EdgeDetail,
    EdgeForecast,
    EventDetail,
    EventForecast,
    EventSeries,
    Explanation,
    FullOnset,
    Gate,
    MemberScore,
    ProductDay,
    ProductDetail,
    ProductFlow,
    Run,
    ScopeDetail,
    ScopeEdge,
    ScopeMember,
    SearchHit,
    SentAlert,
    TermEvent,
    TermForecast,
    TermLongTerm,
    TermOnset,
    TermSummary,
    TermTrend,
    TrainingEvent,
    VolumePoint,
)
from undercurrent.web.queries import (
    DAYS,
    FROM,
    GROUP_CHANNELS,
    NOW,
    SCOPE,
    TO,
    TODAY,
    Db,
    WindowQuery,
    hourly_series,
    utc,
)

# the scope and, for a group, its channels: where a term's trends are looked for
SCOPE_AND_MEMBERS = (
    "(SELECT {scope:String} UNION ALL "
    "SELECT channel FROM channel_groups WHERE group_name = {scope:String})"
)
TERM = "term = {term:String} AND kind = {kind:String}"


class NotFound(LookupError):
    """An entity that doesn't exist: a 404."""


class TermQuery(BaseModel):
    scope: str = Field("reddit", description="a platform, group or channel")


class TermWindowQuery(TermQuery, WindowQuery):
    pass


def term_summary(db: Db, kind: str, term: str, scope: str) -> TermSummary:
    parameters = {"kind": kind, "term": term, "scope": scope}
    trending = db.rows(
        f"""
        WITH
            (SELECT maxOrNull(detected_at) FROM trends
             WHERE horizon = '24h' AND detected_at <= {NOW}) AS day_run,
            (SELECT maxOrNull(detected_at) FROM trends
             WHERE horizon = '6h' AND detected_at <= {NOW}) AS hours_run
        SELECT horizon, scope, scope_type, detected_at, z AS score, ratio, is_new, mentions,
               authors, breadth, members, alert, subsumed_by
        FROM trends FINAL
        WHERE {TERM} AND scope IN {SCOPE_AND_MEMBERS}
          AND ((horizon = '24h' AND detected_at = day_run)
               OR (horizon = '6h' AND detected_at = hours_run))
        ORDER BY z DESC
        """,
        parameters,
    )
    long_term = _long_term(db, parameters)
    volume = db.one(
        f"""
        SELECT sumIf(docs, day >= {TODAY} - 6) AS mentions_7d,
               uniqCombinedMergeIf(12)(authors, day >= {TODAY} - 6) AS authors_7d,
               minOrNull(day) AS first_seen
        FROM term_daily
        WHERE channel IN ({GROUP_CHANNELS}) AND {TERM} AND day <= {TODAY}
        """,
        parameters,
    )
    points = db.rows(
        f"""
        SELECT hour AS time, term, sum(docs) AS mentions
        FROM term_hourly
        WHERE channel IN ({GROUP_CHANNELS}) AND {TERM}
          AND hour > {NOW} - INTERVAL 7 DAY AND hour <= {NOW}
        GROUP BY time, term
        """,
        parameters,
    )
    counts = db.one(
        f"""
        SELECT
            (SELECT count() FROM lead_lag_events FINAL WHERE {TERM} AND start <= {NOW})
                AS events,
            (SELECT count() FROM forecasts FINAL
             WHERE {TERM} AND outcome = 'pending' AND created_at <= {NOW}) AS pending_forecasts
        """,
        parameters,
    )
    return TermSummary(
        kind=kind,
        term=term,
        scope=scope,
        trending=[TermTrend.model_validate(row) for row in trending],
        long_term=long_term,
        mentions_7d=volume["mentions_7d"],
        authors_7d=volume["authors_7d"],
        first_seen=volume["first_seen"],
        sparkline=hourly_series(points, db.now, 7 * 24).get(term, [0] * (7 * 24)),
        **counts,
    )


def _long_term(db: Db, parameters: dict[str, Any]) -> list[TermLongTerm]:
    rows = db.rows(
        f"""
        SELECT horizon, scope, category, growth, change, q_value AS q, window_start, week
        FROM long_term_trends FINAL
        WHERE {TERM} AND scope IN {SCOPE_AND_MEMBERS} AND detected_at <= {NOW}
          AND (horizon, week) IN (
              SELECT horizon, max(week) FROM long_term_trends
              WHERE detected_at <= {NOW} GROUP BY horizon
          )
        ORDER BY horizon, abs(log(growth)) DESC
        """,
        parameters,
    )
    return [TermLongTerm.model_validate(row) for row in rows]


def term_annotations(db: Db, kind: str, term: str, query: TermWindowQuery) -> Annotations:
    """What happened to the term, to mark on its series: the runs where it trended (the
    scope and its members), event onsets, forecasts, long-term windows."""
    parameters = {
        "kind": kind,
        "term": term,
        "scope": query.scope,
        **query.window(db.now, "30d"),
    }
    runs = db.rows(
        f"""
        SELECT detected_at AS time, horizon, scope, z AS score, ratio, alert
        FROM trends
        WHERE {TERM} AND scope IN {SCOPE_AND_MEMBERS}
          AND detected_at >= {FROM} AND detected_at <= {TO} AND subsumed_by = ''
        ORDER BY detected_at
        LIMIT 5000
        """,
        parameters,
    )
    onsets = db.rows(
        f"""
        SELECT onset.1 AS scope, onset.3 AS at, start AS event_start
        FROM lead_lag_events FINAL
        ARRAY JOIN onsets AS onset
        WHERE {TERM} AND start <= {NOW} AND onset.2 = ''
          AND onset.3 >= {FROM} - INTERVAL 3 DAY AND onset.3 <= {TO}
        ORDER BY at
        """,
        parameters,
    )
    forecasts = db.rows(
        f"""
        SELECT leader, follower, without_leader, created_at, leader_onset, expected_at,
               due_by, probability, outcome, follower_onset
        FROM forecasts FINAL
        WHERE {TERM} AND created_at <= {NOW} AND due_by >= {FROM}
        ORDER BY created_at
        LIMIT 200
        """,
        parameters,
    )
    return Annotations(
        runs=[Run.model_validate(row) for row in runs],
        onsets=[TermOnset.model_validate(row) for row in onsets],
        forecasts=[TermForecast.model_validate(row) for row in forecasts],
        long_term=_long_term(db, parameters),
    )


def term_events(db: Db, kind: str, term: str) -> list[TermEvent]:
    rows = db.rows(
        f"""
        SELECT kind, term, start, topic, closed,
               arrayMap(o -> (o.1, o.3),
                        arraySort(o -> o.3, arrayFilter(o -> o.2 = '', onsets))) AS cascade
        FROM lead_lag_events FINAL
        WHERE {TERM} AND start <= {NOW}
        ORDER BY start DESC
        LIMIT 50
        """,
        {"kind": kind, "term": term},
    )
    return [
        TermEvent.model_validate(
            {**row, "cascade": [{"scope": scope, "at": at} for scope, at in row["cascade"]]}
        )
        for row in rows
    ]


class ExplainQuery(TermQuery):
    horizon: str = Field("24h", pattern="^(24h|6h)$")
    at: datetime | None = Field(None, description="the run; the latest one by default")


ALERTS = {
    "sent": "Sent: strong enough for an instant alert, and none was held back.",
    "failed": "Strong enough, but sending failed (ntfy unreachable or refusing).",
    "capped": "Strong enough, but the day's alerts (notify.max_alerts_per_day) were sent.",
    "cooldown": "Strong enough, but it was alerted in the last notify.cooldown_hours "
    "and its score hasn't doubled since.",
    "warmup": "Strong enough, but the scope has fewer days of history than alerts wait for.",
    "skipped": "Strong enough, but this scope never alerts (notify.skip_scopes).",
    "muted": "Strong enough, but the run sent no notifications.",
}


def explain(
    db: Db, config: Config | None, kind: str, term: str, query: ExplainQuery
) -> Explanation:
    """What a trend's score is made of: the shares against each other and against the
    platform, how far the prior pulled each side, the gates with their values, the alert's
    outcome, and the member channels of a group in the same run. δ and σ are recomputed
    with detect/scoring.py, so they can't disagree with the detector."""
    at = utc(query.at) if query.at else db.now
    parameters = {
        "kind": kind,
        "term": term,
        "scope": query.scope,
        "horizon": query.horizon,
        "at": int(at.timestamp()),
    }
    found = db.rows(
        f"""
        SELECT scope, scope_type, horizon, detected_at, mentions, total, reference_mentions,
               reference_total, authors, reference_days, prior, log_odds, ratio, z, is_new,
               alert, subsumed_by, breadth, members
        FROM trends FINAL
        WHERE horizon = {{horizon:String}} AND scope = {{scope:String}} AND {TERM}
          AND detected_at <= toDateTime({{at:UInt32}}, 'UTC') AND detected_at <= {NOW}
        ORDER BY detected_at DESC
        LIMIT 1
        """,
        parameters,
    )
    if not found:
        raise NotFound(f"{term} hasn't trended in {query.scope} ({query.horizon})")
    row = found[0]
    members = db.rows(
        f"""
        SELECT scope, z AS score, ratio, mentions
        FROM trends FINAL
        WHERE horizon = {{horizon:String}} AND detected_at = {{run:DateTime}} AND {TERM}
          AND scope IN (SELECT channel FROM channel_groups WHERE group_name = {{scope:String}})
        ORDER BY z DESC
        """,
        {**parameters, "run": row["detected_at"]},
    )
    detect = config.detect if config else None
    weight = detect.prior_weight if detect else 0.05
    floor = detect.prior_floor if detect else 1.0
    total, reference_total = row["total"], row["reference_total"]
    # the stored α is weight × total × share + floor: the platform's share, back out of it
    share = max((row["prior"] - floor) / (weight * total), 0.0) if total else 0.0
    scale = 10**12
    prior = Prior(total=scale, weight=weight, floor=floor)
    counts = Counts(
        mentions=row["mentions"],
        total=total,
        reference_mentions=row["reference_mentions"],
        reference_total=reference_total,
        background_mentions=round(share * scale),
    )
    score = counts.score(prior)
    alpha, beta = prior.pseudo_counts(counts.background_mentions, weight * total)
    reference_alpha, reference_beta = prior.pseudo_counts(
        counts.background_mentions,
        weight * reference_total + max(total - reference_total, 0),
    )
    return Explanation(
        scope=row["scope"],
        scope_type=row["scope_type"],
        horizon=row["horizon"],
        detected_at=row["detected_at"],
        mentions=row["mentions"],
        total=total,
        reference_mentions=row["reference_mentions"],
        reference_total=reference_total,
        authors=row["authors"],
        reference_days=row["reference_days"],
        share_now=row["mentions"] / total if total else None,
        share_before=row["reference_mentions"] / reference_total if reference_total else None,
        share_now_with_prior=(row["mentions"] + alpha) / (total + alpha + beta),
        share_before_with_prior=(row["reference_mentions"] + reference_alpha)
        / (reference_total + reference_alpha + reference_beta),
        platform_share=share,
        prior=row["prior"],
        log_odds=row["log_odds"],
        sigma=row["log_odds"] / row["z"] if row["z"] else None,
        score=row["z"],
        ratio=row["ratio"],
        is_new=row["is_new"],
        recomputed_score=score.z,
        gates=_gates(config, row, kind),
        alert=row["alert"],
        subsumed_by=row["subsumed_by"],
        members=[MemberScore.model_validate(member) for member in members],
    )


def _gates(config: Config | None, row: dict[str, Any], kind: str) -> list[Gate]:
    if config is None:
        return []
    thresholds = config.detect.thresholds_for(row["scope"], kind)
    notify = config.notify

    def gate(name: str, label: str, value: float, threshold: float) -> Gate:
        return Gate(
            name=name, label=label, value=value, threshold=threshold, passed=value >= threshold
        )

    gates = [
        gate("mentions", "Comments and posts", row["mentions"], thresholds.min_mentions),
        gate("authors", "People", row["authors"], thresholds.min_authors),
        gate("ratio", "Times its usual share", row["ratio"], thresholds.min_ratio),
        gate("score", "Strength (z)", row["z"], thresholds.min_z),
        gate(
            "history",
            "Days of history, for alerts",
            row["reference_days"],
            config.detect.min_reference_days,
        ),
        gate("alert_score", "Strength for an instant alert", row["z"], notify.alert_min_z),
        gate(
            "alert_authors", "People for an instant alert", row["authors"], notify.alert_min_authors
        ),
    ]
    if row["scope_type"] == "group" and row["members"]:
        gates.append(
            gate(
                "breadth",
                "Channels where it trends, for a group's alert",
                row["breadth"],
                max(notify.alert_min_breadth, notify.alert_min_breadth_share * row["members"]),
            )
        )
    return gates


def scope_detail(db: Db, scope: str) -> ScopeDetail:
    parameters = {"scope": scope}
    kind = db.one(
        """
        SELECT
            {scope:String} IN (SELECT platform FROM channels) AS is_platform,
            {scope:String} IN (SELECT group_name FROM channel_groups) AS is_group,
            {scope:String} IN (SELECT channel FROM channels) AS is_channel,
            (SELECT any(platform) FROM channels WHERE channel IN (
                SELECT channel FROM channel_groups WHERE group_name = {scope:String}
                UNION ALL SELECT {scope:String})) AS platform
        """,
        parameters,
    )
    if not (kind["is_group"] or kind["is_channel"]):
        raise NotFound(f"no scope {scope}")
    members = db.rows(
        f"""
        SELECT channel, sum(docs) AS documents, uniqCombinedMerge(12)(authors) AS authors,
               documents / sum(documents) OVER () AS share
        FROM scope_hourly
        WHERE channel IN ({GROUP_CHANNELS})
          AND hour > {NOW} - INTERVAL 7 DAY AND hour <= {NOW}
        GROUP BY channel
        ORDER BY documents DESC
        """,
        parameters,
    )
    groups = db.rows(
        "SELECT group_name FROM channel_groups WHERE channel = {scope:String} ORDER BY 1",
        parameters,
    )
    volume = db.rows(
        f"""
        SELECT toStartOfDay(hour) AS time, sum(docs) AS documents,
               uniqCombinedMerge(12)(authors) AS authors
        FROM scope_hourly
        WHERE channel IN ({GROUP_CHANNELS})
          AND hour >= toDateTime({TODAY} - 89, 'UTC') AND hour <= {NOW}
        GROUP BY time
        ORDER BY time
        """,
        parameters,
    )
    edges = db.rows(
        f"""
        SELECT leader, follower, without_leader, lift, probability, lag_median, events, hits,
               leader IN ({GROUP_CHANNELS}) AS leads
        FROM propagation_edges FINAL
        WHERE day = (SELECT max(day) FROM propagation_edges WHERE computed_at <= {NOW})
          AND topic = 'all'
          AND (leader IN ({GROUP_CHANNELS}) OR follower IN ({GROUP_CHANNELS})
               OR follower = {{scope:String}})
        ORDER BY lift DESC
        LIMIT 200
        """,
        parameters,
    )
    scope_type = "platform" if kind["is_platform"] else "group" if kind["is_group"] else "channel"
    return ScopeDetail(
        name=scope,
        type=scope_type,
        platform=kind["platform"] or None,
        members=[ScopeMember.model_validate(row) for row in members],
        groups=[row["group_name"] for row in groups],
        volume=[VolumePoint.model_validate(row) for row in volume],
        leads=[ScopeEdge.model_validate(edge) for edge in edges if edge["leads"]],
        follows=[ScopeEdge.model_validate(edge) for edge in edges if not edge["leads"]],
    )


def event_detail(db: Db, kind: str, term: str, start: datetime) -> EventDetail:
    """A story: its onsets in order, the forecasts made during it, every scope's share of
    the term over its span (3 days before to 14 after its start)."""
    parameters = {"kind": kind, "term": term, "start": int(utc(start).timestamp())}
    found = db.rows(
        f"""
        SELECT kind, term, start, last_seen, topic, closed, onsets
        FROM lead_lag_events FINAL
        WHERE {TERM} AND start = toDateTime({{start:UInt32}}, 'UTC')
        """,
        parameters,
    )
    if not found:
        raise NotFound(f"no event of {term} starting {start:%Y-%m-%d %H:%M}")
    event = found[0]
    # named tuples arrive as dicts
    onsets = sorted(
        (
            FullOnset(
                scope=onset["scope"],
                without=onset["without"],
                at=onset["at"],
                mentions=onset["mentions"],
                ratio=onset["ratio"],
                score=onset["z"],
            )
            for onset in event["onsets"]
        ),
        key=lambda onset: onset.at,
    )
    forecasts = db.rows(
        f"""
        SELECT leader, follower, created_at, probability, outcome, expected_at, follower_onset
        FROM forecasts FINAL
        WHERE {TERM} AND event_start = toDateTime({{start:UInt32}}, 'UTC')
          AND created_at <= {NOW}
        ORDER BY created_at
        """,
        parameters,
    )
    wikipedia = db.value(
        f"SELECT any(wiki_onset) FROM wiki_leads FINAL "
        f"WHERE {TERM} AND start = toDateTime({{start:UInt32}}, 'UTC')",
        parameters,
    )
    return EventDetail(
        kind=kind,
        term=term,
        start=event["start"],
        last_seen=event["last_seen"],
        topic=event["topic"],
        closed=event["closed"],
        onsets=onsets,
        forecasts=[EventForecast.model_validate(row) for row in forecasts],
        series=_event_series(db, parameters, sorted({onset.scope for onset in onsets})),
        wikipedia_onset=wikipedia,
    )


def _event_series(db: Db, parameters: dict[str, Any], scopes: list[str]) -> list[EventSeries]:
    """Per scope, mentions and share per hour over the span; groups summed from their
    channels here, so ClickHouse reads only (channel, term) key ranges."""
    if not scopes:
        return []
    members = db.rows(
        "SELECT scope, channel FROM ("
        "SELECT group_name AS scope, channel FROM channel_groups "
        "WHERE group_name IN {scopes:Array(String)} "
        "UNION ALL SELECT channel AS scope, channel FROM channels "
        "WHERE channel IN {scopes:Array(String)})",
        {"scopes": scopes},
    )
    channels_of: dict[str, set[str]] = defaultdict(set)
    for row in members:
        channels_of[row["scope"]].add(row["channel"])
    channels = sorted(set().union(*channels_of.values())) if channels_of else []
    span = {
        **parameters,
        "channels": channels,
        "from": parameters["start"] - 3 * 86400,
        "to": parameters["start"] + 14 * 86400,
    }
    window = f"hour >= {FROM} AND hour <= least({TO}, {NOW})"
    mentions = db.rows(
        f"""
        SELECT channel, hour, sum(docs) AS docs FROM term_hourly
        WHERE channel IN {{channels:Array(String)}} AND {TERM} AND {window}
        GROUP BY channel, hour
        """,
        span,
    )
    totals = db.rows(
        f"""
        SELECT channel, hour, sum(docs) AS docs FROM scope_hourly
        WHERE channel IN {{channels:Array(String)}} AND {window}
        GROUP BY channel, hour
        """,
        span,
    )
    by_channel: dict[tuple[str, datetime], list[int]] = defaultdict(lambda: [0, 0])
    for row in mentions:
        by_channel[(row["channel"], utc(row["hour"]))][0] += row["docs"]
    for row in totals:
        by_channel[(row["channel"], utc(row["hour"]))][1] += row["docs"]
    series: list[EventSeries] = []
    for scope in scopes:
        per_hour: dict[datetime, list[int]] = defaultdict(lambda: [0, 0])
        for (channel, hour), (docs, total) in by_channel.items():
            if channel in channels_of.get(scope, ()):
                per_hour[hour][0] += docs
                per_hour[hour][1] += total
        series.extend(
            EventSeries(
                scope=scope,
                time=hour,
                mentions=docs,
                per_1000=1000 * docs / total if total else None,
            )
            for hour, (docs, total) in sorted(per_hour.items())
        )
    return series


class EdgeQuery(BaseModel):
    leader: str
    follower: str
    topic: str = "all"
    without_leader: bool = False


def edge_detail(db: Db, query: EdgeQuery) -> EdgeDetail:
    """One leader → follower pair: its numbers, lags, the events it was learned from, and
    how its forecasts turned out."""
    parameters = {
        "leader": query.leader,
        "follower": query.follower,
        "topic": query.topic,
        "without": int(query.without_leader),
    }
    found = db.rows(
        f"""
        SELECT day, leader, follower, without_leader, follower_type, lag_median, lag_q25,
               lag_q75, events, hits, hit_rate, base_rate, probability, probability_low,
               probability_high, lift, lead_share, greatest(q_value, direction_q) AS q,
               leader_onsets, lags
        FROM propagation_edges FINAL
        WHERE day = (SELECT max(day) FROM propagation_edges WHERE computed_at <= {NOW})
          AND topic = {{topic:String}} AND leader = {{leader:String}}
          AND follower = {{follower:String}} AND without_leader = {{without:UInt8}}
        """,
        parameters,
    )
    edge = found[0] if found else None
    # the follower's onset as the edge measures it: without the leader for "(rest)"
    follower_onset = (
        "arrayFirst(o -> o.1 = {follower:String} AND o.2 = if({without:UInt8} = 1, "
        "{leader:String}, ''), onsets)"
    )
    training = db.rows(
        f"""
        SELECT kind, term, start,
               arrayFirst(o -> o.1 = {{leader:String}} AND o.2 = '', onsets).3 AS leader_at,
               {follower_onset} AS found,
               if(found.1 = '', NULL, found.3) AS follower_at,
               if(follower_at IS NULL, NULL,
                  dateDiff('second', leader_at, follower_at) / 3600) AS lag_hours
        FROM lead_lag_events FINAL
        WHERE start > {NOW} - INTERVAL 180 DAY AND start <= {NOW}
          AND arrayExists(o -> o.1 = {{leader:String}} AND o.2 = '', onsets)
        ORDER BY start DESC
        LIMIT 200
        """,
        parameters,
    )
    forecasts = db.rows(
        f"""
        SELECT kind, term, created_at, probability, outcome,
               if(follower_onset IS NULL, NULL,
                  dateDiff('second', leader_onset, follower_onset) / 3600) AS lag_hours
        FROM forecasts FINAL
        WHERE leader = {{leader:String}} AND follower = {{follower:String}}
          AND without_leader = {{without:UInt8}} AND created_at <= {NOW}
        ORDER BY created_at DESC
        LIMIT 200
        """,
        parameters,
    )
    return EdgeDetail(
        edge=Edge.model_validate(edge) if edge else None,
        topic=query.topic,
        day=edge["day"] if edge else None,
        lags=list(edge["lags"]) if edge else [],
        base_rate=edge["base_rate"] if edge else None,
        training=[TrainingEvent.model_validate(row) for row in training],
        forecasts=[EdgeForecast.model_validate(row) for row in forecasts],
    )


class ProductQuery(WindowQuery):
    scope: str = "reddit"


def product_detail(db: Db, name: str, query: ProductQuery) -> ProductDetail:
    """A product as the intents mention it: switches to and from it, considering a switch,
    complaints, alternatives sought."""
    product = " ".join(name.lower().split())
    parameters = {
        "scope": query.scope,
        "channels": [],
        "doc_types": [],
        "product": product,
        "intent_kinds": list(INTENT_KINDS),
        **query.window(db.now, "90d"),
    }
    about = (
        "(startsWith(term, concat({product:String}, ' → '))"
        " OR endsWith(term, concat(' → ', {product:String}))"
        " OR term IN (concat('complaint: ', {product:String}),"
        " concat('alternative: ', {product:String}), concat('considering: ', {product:String}))"
        " OR startsWith(term, concat('considering: ', {product:String}, ' → ')))"
    )
    rows = db.rows(
        f"""
        SELECT kind, term, sum(docs) AS mentions, uniqCombinedMerge(12)(authors) AS authors
        FROM term_daily
        WHERE {SCOPE} AND {DAYS} AND has({{intent_kinds:Array(String)}}, kind) AND {about}
        GROUP BY kind, term
        ORDER BY mentions DESC
        """,
        parameters,
    )
    daily = db.rows(
        f"""
        SELECT toDateTime(day, 'UTC') AS time, kind, sum(docs) AS mentions
        FROM term_daily
        WHERE {SCOPE} AND {DAYS} AND has({{intent_kinds:Array(String)}}, kind) AND {about}
        GROUP BY time, kind
        ORDER BY time
        """,
        parameters,
    )
    flows_in: list[ProductFlow] = []
    flows_out: list[ProductFlow] = []
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["kind"]] += row["mentions"]
        if row["kind"] != "switch":
            continue
        source, _, target = row["term"].partition(" → ")
        flow = {"mentions": row["mentions"], "authors": row["authors"]}
        if target == product:
            flows_in.append(ProductFlow(product=source, **flow))
        if source == product:
            flows_out.append(ProductFlow(product=target, **flow))
    return ProductDetail(
        name=product,
        flows_in=flows_in,
        flows_out=flows_out,
        counts=dict(counts),
        daily=[ProductDay.model_validate(row) for row in daily],
        terms=[row["term"] for row in rows],
    )


def sent_alerts(db: Db, query: WindowQuery) -> list[SentAlert]:
    """Every alert and forecast alert sent, newest first, with the trend behind it."""
    rows = db.rows(
        f"""
        SELECT n.sent_at AS time, n.kind AS kind, n.scope AS scope, n.term AS term,
               n.title AS title, n.message AS message, n.ok AS ok,
               t.run_kind AS term_kind, t.run_horizon AS horizon, t.top_z AS score
        FROM notifications AS n
        LEFT JOIN (
            SELECT scope, term, argMax(kind, z) AS run_kind, argMax(horizon, z) AS run_horizon,
                   max(z) AS top_z
            FROM trends
            WHERE alert = 'sent' AND detected_at >= {FROM} - INTERVAL 1 DAY
              AND detected_at <= {TO}
            GROUP BY scope, term
        ) AS t ON t.scope = n.scope AND t.term = n.term
        WHERE n.kind IN ('alert', 'forecast') AND n.sent_at >= {FROM} AND n.sent_at <= {TO}
        ORDER BY n.sent_at DESC
        LIMIT 500
        SETTINGS join_use_nulls = 1
        """,
        query.window(db.now, "30d"),
    )
    return [SentAlert.model_validate(row) for row in rows]


def search(db: Db, text: str, limit: int = 20) -> list[SearchHit]:
    """Terms starting with what was typed, the most mentioned first (term_catalog)."""
    prefix = " ".join(text.lower().split())
    if not prefix:
        return []
    rows = db.rows(
        """
        SELECT kind, term, max(mentions) AS mentions, max(last_seen) AS last_seen
        FROM term_catalog
        WHERE startsWith(term, {prefix:String})
        GROUP BY kind, term
        ORDER BY mentions DESC, term
        LIMIT {limit:UInt32}
        """,
        {"prefix": prefix, "limit": limit},
    )
    return [SearchHit.model_validate(row) for row in rows]
