"""What Grafana can't show (docs/WEB-DASHBOARD.md §7.1, P2): co-occurring terms, a term
in every channel of a scope, its rhythm, ranks over time, and the layout of the spread map.
Each says what it reads; all are key ranges on the tables' sorting keys or small tables,
except co-occurring terms, which scan 48 hours of items and are cached for 15 minutes."""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from wgra.config import Config
from wgra.detect.scoring import log_odds
from wgra.text import extract_terms
from wgra.text.intents import INTENT_KINDS
from wgra.text.lexicon import stopwords
from wgra.web.models import (
    CalendarDay,
    ChannelSeries,
    HourOfWeek,
    MapNode,
    RankPoint,
    Related,
    RelatedTerm,
    Rhythm,
    SmallMultiples,
)
from wgra.web.queries import (
    DAYS,
    GROUP_CHANNELS,
    NOW,
    TIME_FILTER,
    TODAY,
    WHOLE_DAYS,
    Db,
    WindowQuery,
    step,
    utc,
)
from wgra.web.queries.explore import TEXT_MATCHES_TERMS

TERM = "term = {term:String} AND kind = {kind:String}"
CHANNELS = (
    "channel IN ("
    f"{GROUP_CHANNELS}) AND channel NOT IN (SELECT channel FROM channels WHERE background)"
)


class Cache:
    """Answers of expensive endpoints for `seconds`, keyed by everything they depend on."""

    def __init__(self, seconds: int = 900, size: int = 256):
        self._seconds, self._size = seconds, size
        self._entries: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[Any, ...]) -> Any:
        with self._lock:
            found = self._entries.get(key)
            return found[1] if found and found[0] > time.monotonic() else None

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        with self._lock:
            if len(self._entries) >= self._size:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (time.monotonic() + self._seconds, value)


RELATED = Cache()


def related(db: Db, config: Config | None, kind: str, term: str, scope: str) -> Related:
    """The terms mentioned most in the same comments and posts of the last 48 hours, ranked
    by how much more often they appear with the term than without it: the weighted log
    odds of the detector, the comments with the term against the rest of the scope's 48
    hours. The comments go through the ingester's own term extraction, so related terms
    are terms as the detector counts them."""
    key = (db.endpoint, kind, term, scope, db.timestamp // 900)
    if (cached := RELATED.get(key)) is not None:
        return cached
    parameters = {"kind": kind, "term": term, "scope": scope, "terms": [term]}
    matches = "has(intents, {term:String})" if kind in INTENT_KINDS else TEXT_MATCHES_TERMS
    texts = db.rows(
        f"""
        SELECT text, lang, channel
        FROM items
        WHERE {CHANNELS} AND created_at > {NOW} - INTERVAL 48 HOUR AND created_at <= {NOW}
          AND {matches}
        ORDER BY created_at DESC
        LIMIT 2000
        """,
        parameters,
    )
    together: Counter[tuple[str, str]] = Counter()
    languages: set[str] = set()
    for row in texts:
        languages.add(row["lang"] or "en")
        max_ngram = config.max_ngram(row["channel"]) if config else 3
        found = extract_terms(row["text"], language=row["lang"] or "en", max_ngram=max_ngram)
        together.update(set(found.counts))
    # the term's own words and the languages' function words say nothing about it
    own = set(term.lower().split())
    common = set().union(*(stopwords(language) for language in languages or {"en"}))
    candidates = [
        (found_kind, found)
        for (found_kind, found), count in together.most_common(600)
        if count >= 3
        and (found_kind, found) != (kind, term)
        and not (found_kind == "word" and (found in own or found in common))
    ][:500]
    documents = len(texts)
    result = Related(documents=documents, terms=[])
    if candidates:
        background = db.rows(
            f"""
            SELECT kind, term, sum(docs) AS mentions
            FROM term_hourly
            WHERE {CHANNELS} AND hour > {NOW} - INTERVAL 48 HOUR AND hour <= {NOW}
              AND (kind, term) IN {{candidates:Array(Tuple(String, String))}}
            GROUP BY kind, term
            """,
            {**parameters, "candidates": candidates},
        )
        total = (
            db.value(
                f"SELECT sum(docs) FROM scope_hourly WHERE {CHANNELS} "
                f"AND hour > {NOW} - INTERVAL 48 HOUR AND hour <= {NOW}",
                parameters,
            )
            or 0
        )
        mentions = {(row["kind"], row["term"]): row["mentions"] for row in background}
        scored = []
        for candidate in candidates:
            with_term = together[candidate]
            without = max(mentions.get(candidate, with_term) - with_term, 0)
            rest = max(total - documents, 1)
            score = log_odds(with_term, documents, without, rest, (1.0, 1.0), (1.0, 1.0))
            if score.z >= 3 and score.ratio >= 2:
                scored.append((score, candidate, with_term))
        scored.sort(key=lambda found: found[0].z, reverse=True)
        result = Related(
            documents=documents,
            terms=[
                RelatedTerm(
                    kind=candidate[0],
                    term=candidate[1],
                    together=with_term,
                    # never without it: no ratio to speak of
                    ratio=score.ratio if mentions.get(candidate, with_term) > with_term else None,
                    score=score.z,
                )
                for score, candidate, with_term in scored[:30]
            ],
        )
    RELATED.put(key, result)
    return result


class SeriesQuery(WindowQuery):
    scope: str = Field("reddit", description="a platform or group: its channels")


def small_multiples(db: Db, kind: str, term: str, query: SeriesQuery) -> SmallMultiples:
    """The term in every channel of the scope, sorted by when each crossed half of its own
    peak: the static version of the replay. `(channel, term)` key ranges."""
    window = query.window(db.now, "30d")
    days = (window["to"] - window["from"]) / 86400
    hourly = days <= 14
    parameters = {"kind": kind, "term": term, "scope": query.scope, **window}
    if hourly:
        parameters["step"] = step(window["to"] - window["from"], 3600, 200)
        bucket = "toStartOfInterval(hour, toIntervalSecond({step:UInt32}))"
        mentions_sql = f"""
            SELECT channel, {bucket} AS time, sum(docs) AS docs FROM term_hourly
            WHERE {CHANNELS} AND {TERM} AND {TIME_FILTER} GROUP BY channel, time"""
        totals_sql = f"""
            SELECT channel, {bucket} AS time, sum(docs) AS docs FROM scope_hourly
            WHERE {CHANNELS} AND {TIME_FILTER} GROUP BY channel, time"""
    else:
        mentions_sql = f"""
            SELECT channel, toDateTime(day, 'UTC') AS time, sum(docs) AS docs FROM term_daily
            WHERE {CHANNELS} AND {TERM} AND {DAYS} GROUP BY channel, time"""
        totals_sql = f"""
            SELECT channel, toStartOfDay(hour) AS time, sum(docs) AS docs FROM scope_hourly
            WHERE {CHANNELS} AND {WHOLE_DAYS} GROUP BY channel, time"""
    mentions = db.rows(mentions_sql, parameters)
    totals = {
        (row["channel"], utc(row["time"])): row["docs"] for row in db.rows(totals_sql, parameters)
    }
    per_channel: dict[str, list[tuple[datetime, int, float | None]]] = defaultdict(list)
    for row in sorted(mentions, key=lambda row: row["time"]):
        moment = utc(row["time"])
        total = totals.get((row["channel"], moment), 0)
        per_channel[row["channel"]].append(
            (moment, row["docs"], 1000 * row["docs"] / total if total else None)
        )
    channels = []
    for channel, points in per_channel.items():
        peak = max((share or 0 for _, _, share in points), default=0)
        onset = next((moment for moment, _, share in points if (share or 0) >= peak / 2), None)
        channels.append(
            ChannelSeries(
                channel=channel,
                onset=onset,
                mentions=sum(docs for _, docs, _ in points),
                points=[(moment, share) for moment, _, share in points],
            )
        )
    channels.sort(key=lambda series: (series.onset is None, series.onset or db.now))
    return SmallMultiples(bucket="hour" if hourly else "day", channels=channels)


def rhythm(db: Db, kind: str, term: str, scope: str) -> Rhythm:
    """When it's talked about: its share by hour of week over 28 days divided by the share
    it has overall, so the scope's own rhythm cancels out; and a year of daily shares."""
    parameters = {"kind": kind, "term": term, "scope": scope}
    hours = db.rows(
        f"""
        WITH
            term AS (
                SELECT toDayOfWeek(hour) AS weekday, toHour(hour) AS hour_of_day,
                       sum(docs) AS mentions
                FROM term_hourly
                WHERE {CHANNELS} AND {TERM} AND hour > {NOW} - INTERVAL 28 DAY
                  AND hour <= {NOW}
                GROUP BY weekday, hour_of_day
            ),
            scope AS (
                SELECT toDayOfWeek(hour) AS weekday, toHour(hour) AS hour_of_day,
                       sum(docs) AS documents
                FROM scope_hourly
                WHERE {CHANNELS} AND hour > {NOW} - INTERVAL 28 DAY AND hour <= {NOW}
                GROUP BY weekday, hour_of_day
            )
        SELECT s.weekday AS weekday, s.hour_of_day AS hour, t.mentions AS mentions,
               s.documents AS documents
        FROM scope AS s LEFT JOIN term AS t USING (weekday, hour_of_day)
        ORDER BY weekday, hour
        """,
        parameters,
    )
    mentioned = sum(row["mentions"] for row in hours)
    documents = sum(row["documents"] for row in hours)
    overall = mentioned / documents if documents else 0
    days = db.rows(
        f"""
        SELECT d.day AS day, t.mentions AS mentions, d.documents AS documents
        FROM (
            SELECT toDate(hour) AS day, sum(docs) AS documents FROM scope_hourly
            WHERE {CHANNELS} AND hour >= toDateTime({TODAY} - 364, 'UTC') AND hour <= {NOW}
            GROUP BY day
        ) AS d
        LEFT JOIN (
            SELECT day, sum(docs) AS mentions FROM term_daily
            WHERE {CHANNELS} AND {TERM} AND day >= {TODAY} - 364 AND day <= {TODAY}
            GROUP BY day
        ) AS t USING day
        ORDER BY day
        """,
        parameters,
    )
    return Rhythm(
        hours=[
            HourOfWeek(
                weekday=row["weekday"],
                hour=row["hour"],
                mentions=row["mentions"],
                relative=(row["mentions"] / row["documents"]) / overall
                if overall and row["documents"]
                else None,
            )
            for row in hours
        ],
        days=[
            CalendarDay(
                day=row["day"],
                mentions=row["mentions"],
                per_1000=1000 * row["mentions"] / row["documents"] if row["documents"] else None,
            )
            for row in days
        ],
    )


class RankQuery(BaseModel):
    scope: str = "reddit"
    horizon: str = Field("24h", pattern="^(24h|6h)$")
    top: int = Field(10, ge=3, le=20)


def ranks(db: Db, query: RankQuery) -> list[RankPoint]:
    """The scope's top terms over the last 7 days, one run an hour, for a bump chart.
    `(horizon, scope)` is the key prefix: 7 days × 24 runs × 50 rows."""
    rows = db.rows(
        f"""
        WITH top AS (
            SELECT kind, term FROM trends
            WHERE horizon = {{horizon:String}} AND scope = {{scope:String}}
              AND detected_at > {NOW} - INTERVAL 7 DAY AND detected_at <= {NOW}
              AND toMinute(detected_at) = 0 AND subsumed_by = '' AND rank <= {{top:UInt8}}
            GROUP BY kind, term
            ORDER BY count() DESC, min(rank)
            LIMIT {{top:UInt8}}
        )
        SELECT detected_at AS time, kind, term, rank
        FROM trends FINAL
        WHERE horizon = {{horizon:String}} AND scope = {{scope:String}}
          AND detected_at > {NOW} - INTERVAL 7 DAY AND detected_at <= {NOW}
          AND toMinute(detected_at) = 0 AND subsumed_by = ''
          AND (kind, term) IN (SELECT kind, term FROM top)
        ORDER BY time, rank
        """,
        {"scope": query.scope, "horizon": query.horizon, "top": query.top},
    )
    return [RankPoint.model_validate(row) for row in rows]


def spread_map(db: Db) -> list[MapNode]:
    """Where each scope usually is in a story: the median time from the story's first onset
    to its own, over the events of 180 days. Left to right on the spread map and the
    replay, so the usual direction of spread reads as a wave."""
    rows = db.rows(
        f"""
        SELECT o.1 AS scope,
               quantileExact(0.5)(dateDiff('second', first, o.3) / 3600) AS median_lag,
               count() AS events,
               countIf(o.3 = first) AS first_mover
        FROM (
            SELECT onsets,
                   arrayMin(arrayMap(x -> x.3, arrayFilter(x -> x.2 = '', onsets))) AS first
            FROM lead_lag_events FINAL
            WHERE start > {NOW} - INTERVAL 180 DAY AND start <= {NOW}
              AND length(arrayFilter(x -> x.2 = '', onsets)) > 0
        )
        ARRAY JOIN onsets AS o
        WHERE o.2 = ''
        GROUP BY scope
        ORDER BY median_lag, scope
        """,
        {},
    )
    return [MapNode.model_validate(row) for row in rows]
