"""Production-scale synthetic history for the lead–lag layer, and what each part costs.

Run it against a ClickHouse of its own (never the live one), for example one limited to
the planned VPS (4 CPUs, 8 GB):

    docker run -d --name wgra-dev-bench-clickhouse --cpus 4 --memory 8g \\
        -p 127.0.0.1:3617:8123 -e CLICKHOUSE_USER=wgra -e CLICKHOUSE_PASSWORD=bench \\
        -v "$PWD/clickhouse/wgra.xml:/etc/clickhouse-server/config.d/wgra.xml:ro" \\
        clickhouse/clickhouse-server:26.8
    export CLICKHOUSE_PORT=3617 CLICKHOUSE_PASSWORD=bench
    uv run python bench/lead_lag.py --database wgra_bench_ll generate
    uv run python bench/lead_lag.py --database wgra_bench_ll run backfill
    # then: run daily, run forecast, run learn, run replay

`generate` writes `term_hourly` and `scope_hourly` for `--days` days up to today: the 37
subreddits of config.yaml with about 130k comments a day between them and the r/all sample
with 400k, a Zipf-like vocabulary (bench/synthetic.py's) with the tail scaled to the
distinct term rows per hour measured live in the first hour (about 87k tracked, 97k
sample). In the last `--event-days` days it plants `--events-per-day` events: a term of
log-uniform rank between 50 and 500k (a quarter are words used every hour in most
subreddits) bursting for 48 hours at three times its usual share (at least 2 mentions an
hour) in 1–4 subreddits or the sample. Five leader subreddits pass 60% of their terms on to
a fixed follower 2–4 days later, everything else is random. Every burst is a trend in
`trends`, one row an hour for a day from 6 hours in.

`run <step>` measures one part, in a process of its own so the peak memory is the part's:

* backfill: the first daily run, every event's onsets and the edges
* daily: a run a day later, the open events' onsets again and the edges
* forecast: one analyze run's forecast step, 30 terms trending in leaders, 300 pending
* learn: learning the edges from 180 days of events (the stored ones six times over)
* replay: `wgra replay --forecast --events stored` over the event days, hourly steps

Per part: the wall time, the Python process's peak memory, and from system.query_log the
queries' time, peak memory and rows read.
"""

from __future__ import annotations

import argparse
import math
import resource
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from wgra.config import SAMPLE_SCOPE, Env, load_config
from wgra.detect.short_term import TREND_COLUMNS, Trend
from wgra.store import connect, migrate

sys.path.insert(0, str(Path(__file__).parent))
from synthetic import (
    HAPAX_PER_COMMENT,
    KIND,
    MAX_SHARE,
    NOISY,
    SAMPLE_PER_DAY,
    TERM,
    VOCABULARY,
    A,
    S,
    comments_per_day,
    dense_ranks,
    tail_rows,
)

# the tail of the vocabulary, scaled to the distinct term rows per hour measured live
TAIL_SCALE = {"tracked": 0.3, "sample": 0.45}
LEADERS = 5
BURST_HOURS = 48

HOURS_SQL = f"""
INSERT INTO term_hourly (hour, subreddit, source, kind, term, occurrences, docs)
SELECT hour, subreddit, 'comment', {KIND}, {TERM}, docs, docs
FROM (
    SELECT toDateTime({{day:Date}}, 'UTC') + toIntervalHour(intDiv(number, {{dense:UInt64}}))
               AS hour,
           {{subreddit:String}} AS subreddit,
           number % {{dense:UInt64}} + 1 AS rank,
           {{per_hour:Float64}} * least({MAX_SHARE}, {A} / pow(rank, {S})) AS expected,
           toUInt64({NOISY}) AS docs
    FROM numbers(24 * {{dense:UInt64}})
)
WHERE docs > 0
UNION ALL
SELECT toDateTime({{day:Date}}, 'UTC') + toIntervalHour(intDiv(number, {{tail:UInt64}})),
       {{subreddit:String}}, 'comment', {KIND}, {TERM}, 1, 1
FROM (
    SELECT number,
           toUInt64({{dense:UInt64}} * pow(
               1 - randCanonical() * (1 - pow({VOCABULARY} / {{dense:UInt64}}, {1 - S})),
               {1 / (1 - S)})) AS rank
    FROM numbers(24 * {{tail:UInt64}})
)
UNION ALL
SELECT toDateTime({{day:Date}}, 'UTC')
           + toIntervalHour(intDiv(number, greatest({{hapax:UInt64}}, 1))),
       {{subreddit:String}}, 'comment', 'phrase', concat('h', hex(rand64())), 1, 1
FROM numbers(24 * {{hapax:UInt64}})
"""

TOTALS_SQL = """
INSERT INTO scope_hourly (hour, subreddit, source, docs, tokens)
SELECT toDateTime({day:Date}, 'UTC') + toIntervalHour(number), {subreddit:String}, 'comment',
       {per_hour:UInt64}, {per_hour:UInt64} * 30
FROM numbers(24)
"""


def term_name(rank: int) -> str:
    return f"{'w' if rank % 3 == 0 else 'p'}{rank:09d}"


def kind_of(rank: int) -> str:
    return "word" if rank % 3 == 0 else "phrase"


def generate(client, config, days: int, event_days: int, events_per_day: int, seed: int) -> None:
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    volumes = comments_per_day(list(config.subreddits))
    volumes[SAMPLE_SCOPE] = SAMPLE_PER_DAY
    started = time.monotonic()
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        for subreddit, per_day in volumes.items():
            per_hour = per_day / 24
            sample = subreddit == SAMPLE_SCOPE
            scale = TAIL_SCALE["sample" if sample else "tracked"]
            parameters = {
                "day": day,
                "subreddit": subreddit,
                "per_hour": per_hour,
                "dense": dense_ranks(int(per_hour)),
                "tail": int(scale * tail_rows(int(per_hour))),
                "hapax": 0 if sample else int(HAPAX_PER_COMMENT * per_hour),
            }
            client.command(HOURS_SQL, parameters=parameters)
            client.command(TOTALS_SQL, parameters=parameters | {"per_hour": int(per_hour)})
        print(f"{day}  {offset + 1}/{days} days  {time.monotonic() - started:.0f}s", flush=True)

    rng = np.random.default_rng(seed)
    subreddits = list(config.subreddits)
    leaders = [subreddits[index] for index in rng.choice(len(subreddits), LEADERS, replace=False)]
    others = [sub for sub in subreddits if sub not in leaders]
    follower_of = {leader: str(rng.choice([*others, SAMPLE_SCOPE])) for leader in leaders}
    print("planted leaders:", follower_of)

    bursts: list[tuple[str, int, datetime]] = []
    first_event = end - timedelta(days=event_days)
    for number in range(event_days * events_per_day):
        rank = int(math.exp(rng.uniform(math.log(50), math.log(500_000))))
        at = first_event + timedelta(hours=int(rng.integers(0, (event_days - 2) * 24)))
        if number % 4 == 0:
            leader = str(rng.choice(leaders))
            bursts.append((leader, rank, at))
            if rng.random() < 0.6:
                lag = timedelta(hours=int(rng.integers(48, 97)))
                bursts.append((follower_of[leader], rank, at + lag))
        else:
            for sub in rng.choice([*subreddits, SAMPLE_SCOPE], rng.integers(1, 5), replace=False):
                bursts.append((str(sub), rank, at + timedelta(hours=int(rng.integers(0, 120)))))

    rows, trend_rows = [], []
    for subreddit, rank, at in bursts:
        per_hour = volumes[subreddit] / 24
        rate = max(2.0, 3 * per_hour * min(MAX_SHARE, A / rank**S))
        for hour in range(BURST_HOURS):
            docs = int(rng.poisson(rate))
            moment = at + timedelta(hours=hour)
            if docs and moment < end:
                rows.append(
                    (moment, subreddit, "comment", kind_of(rank), term_name(rank), docs, docs)
                )
        scope = "sample" if subreddit == SAMPLE_SCOPE else f"r/{subreddit}"
        for hour in range(6, 30):
            detected = at + timedelta(hours=hour)
            if detected < end:
                trend_rows.append(trend_row(scope, rank, detected))
    for first in range(0, len(rows), 500_000):
        client.insert(
            "term_hourly",
            rows[first : first + 500_000],
            column_names=["hour", "subreddit", "source", "kind", "term", "occurrences", "docs"],
        )
    client.insert("trends", trend_rows, column_names=list(TREND_COLUMNS))
    print(f"{len(bursts):,} bursts, {len(rows):,} burst rows, {len(trend_rows):,} trend rows")


def trend_row(scope: str, rank: int, detected: datetime) -> list[object]:
    trend = Trend(
        horizon="24h",
        scope=scope,
        term=term_name(rank),
        detected_at=detected,
        scope_type="group" if scope == "sample" else "subreddit",
        kind=kind_of(rank),
        window_start=detected - timedelta(hours=24),
        window_end=detected,
        mentions=50,
        total=10_000,
        reference_mentions=10,
        reference_total=280_000,
        authors=40,
        prior=1.0,
        log_odds=2.0,
        ratio=7.0,
        z=8.0,
        is_new=False,
        reference_days=28,
    )
    return list(trend.row())


def peak_memory_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # bytes on macOS, KiB on Linux
    return peak / 2**20 if sys.platform == "darwin" else peak / 2**10


def query_stats(client, database: str, since: datetime) -> str:
    client.command("SYSTEM FLUSH LOGS")
    rows = client.query(
        """
        SELECT count(), sum(query_duration_ms), max(query_duration_ms), max(memory_usage),
               sum(read_rows)
        FROM system.query_log
        WHERE type = 'QueryFinish' AND current_database = {database:String}
          AND event_time >= {since:DateTime} AND query_kind = 'Select'
        """,
        parameters={"database": database, "since": since},
    ).result_rows
    count, total, slowest, memory, read = rows[0]
    return (
        f"ClickHouse: {count} queries, {total / 1000:.1f}s in all, slowest {slowest / 1000:.1f}s, "
        f"at most {memory / 2**20:.0f} MiB, {read / 1e6:.0f}M rows read"
    )


def run(client, config, database: str, step: str) -> None:
    from wgra.detect.replay import stored_steps
    from wgra.leadlag.edges import Network, learn_edges
    from wgra.leadlag.evaluate import evaluate, report
    from wgra.leadlag.events import Onset, load_events
    from wgra.leadlag.forecasts import Forecast, write_forecasts
    from wgra.leadlag.run import LeadLag

    (latest,) = client.query("SELECT max(hour) FROM scope_hourly").result_rows[0]
    now = latest.replace(tzinfo=UTC) + timedelta(hours=1, minutes=30)
    since = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
    started = time.monotonic()
    lead_lag = LeadLag(client, config)
    if step == "backfill":
        client.command("TRUNCATE TABLE IF EXISTS lead_lag_events")
        client.command("TRUNCATE TABLE IF EXISTS propagation_edges")
        result = lead_lag.learn(now)
        print(
            f"backfill: {result.new_sightings:,} sightings, onsets of {result.computed:,} events, "
            f"{result.edges.tested:,} pairs tested, {len(result.edges.edges)} edges"
        )
    elif step == "daily":
        result = lead_lag.learn(now + timedelta(days=1))
        print(
            f"daily: {result.new_sightings:,} sightings, onsets of {result.computed:,} open "
            f"events, {result.edges.training_events:,} training events, "
            f"{len(result.edges.edges)} edges"
        )
    elif step == "forecast":
        recent = [e for e in load_events(client, now - timedelta(days=3), now) if e.onsets]
        leaders = {edge.leader for edge in lead_lag.edges()[1]}
        candidates = [
            (event, onset)
            for event in recent
            for onset in event.onsets
            if onset.scope in leaders and not onset.without
        ][:30]
        trends = [
            Trend(**dict(zip(TREND_COLUMNS, trend_row(o.scope, int(e.term[1:]), now), strict=True)))
            for e, o in candidates
        ]
        older = [e for e in load_events(client, now - timedelta(days=10), now) if e.onsets][:300]
        pending = [
            Forecast(
                kind=e.kind,
                term=e.term,
                event_start=e.start,
                follower="sample",
                leader=e.onsets[0].scope,
                follower_type="sample",
                without_leader=False,
                topic="all",
                created_at=now - timedelta(days=1),
                leader_onset=e.onsets[0].at,
                expected_at=now,
                due_by=now + timedelta(days=3),
                probability=0.5,
                probability_low=0.4,
                probability_high=0.6,
                base_rate=0.2,
                lift=2.5,
                edge_events=20,
                edge_hits=10,
                lag_q25=24.0,
                lag_median=48.0,
                lag_q75=72.0,
            )
            for e in older
        ]
        write_forecasts(client, pending)
        timed = time.monotonic()
        made = lead_lag.forecast(now, trends)
        print(
            f"forecast step: {len(trends)} leading terms, {len(pending)} pending, onsets of "
            f"{made.terms} events, {len(made.new)} new, {len(made.resolved)} resolved, "
            f"{time.monotonic() - timed:.1f}s"
        )
        client.command("TRUNCATE TABLE forecasts")
    elif step == "learn":
        events = load_events(client, now - timedelta(days=60), now)
        copies = []
        for copy in range(6):
            shift = timedelta(days=30 * copy)
            for event in events:
                copies.append(
                    replace(
                        event,
                        start=event.start - shift,
                        onsets=[
                            Onset(o.scope, o.without, o.at - shift, o.mentions, o.ratio, o.z)
                            for o in event.onsets
                        ],
                        onsets_until=now,
                    )
                )
        onsets = sum(len(event.onsets) for event in copies)
        timed = time.monotonic()
        result = learn_edges(copies, Network.load(client), now, config.lead_lag)
        print(
            f"learn: {len(copies):,} events with {onsets:,} onsets, {result.tested:,} pairs "
            f"tested, {len(result.edges)} edges, {time.monotonic() - timed:.1f}s"
        )
    elif step == "replay":
        (first,) = client.query("SELECT min(detected_at) FROM trends").result_rows[0]
        steps = stored_steps(
            client, first.replace(tzinfo=UTC), now, timedelta(hours=1), config.lead_lag.event_min_z
        )
        evaluation = evaluate(client, config, steps, now)
        print(report(evaluation))
    print(
        f"{step}: {time.monotonic() - started:.1f}s, Python peak {peak_memory_mib():.0f} MiB | "
        + query_stats(client, database, since)
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", required=True)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("generate")
    make.add_argument("--days", type=int, default=60)
    make.add_argument("--event-days", type=int, default=30)
    make.add_argument("--events-per-day", type=int, default=400)
    make.add_argument("--seed", type=int, default=1)
    measure = commands.add_parser("run")
    measure.add_argument("step", choices=["backfill", "daily", "forecast", "learn", "replay"])
    args = parser.parse_args()

    env = Env.from_environ(require_reddit=False)
    if args.database == "wgra" or env.clickhouse_port == 3607:
        raise SystemExit("never against the live database or ClickHouse")
    config = load_config(args.config)
    admin = connect(env, database="default")
    admin.command(f"CREATE DATABASE IF NOT EXISTS {args.database}")
    client = connect(env, database=args.database)
    migrate(client)
    if args.command == "generate":
        client.command("TRUNCATE TABLE subreddit_groups")
        client.insert(
            "subreddit_groups",
            config.group_memberships(),
            column_names=["group_name", "subreddit"],
        )
        generate(client, config, args.days, args.event_days, args.events_per_day, args.seed)
    else:
        run(client, config, args.database, args.step)


if __name__ == "__main__":
    main()
