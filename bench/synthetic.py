"""Production-scale synthetic history, to measure the long-term detector.

Writes `term_daily` and `scope_hourly` straight into a ClickHouse database (never the
live one): the 37 subreddits of config.yaml with about 130k comments a day between them,
and the r/all sample with 400k a day, for as many weeks as asked. Run it against a
ClickHouse of its own, for example one limited to the planned VPS (4 CPUs, 8 GB):

    docker run -d --name wgra-dev-bench-clickhouse --cpus 4 --memory 8g \\
        -p 127.0.0.1:3617:8123 -e CLICKHOUSE_USER=wgra -e CLICKHOUSE_PASSWORD=bench \\
        -v "$PWD/clickhouse/wgra.xml:/etc/clickhouse-server/config.d/wgra.xml:ro" \\
        clickhouse/clickhouse-server:26.8
    CLICKHOUSE_PORT=3617 CLICKHOUSE_PASSWORD=bench uv run python bench/synthetic.py \\
        --database wgra_bench --weeks 53

The vocabulary is shared by all subreddits and Zipf-like: the share of comments
mentioning the term of rank r is min(0.1, 110 / r^1.34). Per subreddit and day, every
term expected at least once is written with Poisson counts, rarer ones are drawn from the
same law with one mention each, and two terms per comment are never seen again (most
phrases). That gives about 1.6M rows a day for the tracked subreddits and 1.3M for the
sample, close to the hourly rows measured live (about 86k and 96k an hour) after rolling
them up into days, and about 90k terms above a floor of 20 mentions a week in all
tracked subreddits together. Counts are noise around a constant level, no trends.
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from wgra.config import SAMPLE_SCOPE, Env, load_config
from wgra.store import connect, migrate

A, S, VOCABULARY = 110.0, 1.34, 5_000_000
MAX_SHARE = 0.1
SAMPLE_PER_DAY = 400_000
# comments a day of the i-th largest subreddit, about 130k a day in all
LARGEST = 40_000
HAPAX_PER_COMMENT = 2


def comments_per_day(subreddits: list[str]) -> dict[str, int]:
    return {sub: round(LARGEST / (index + 1) ** 1.2) for index, sub in enumerate(subreddits)}


def dense_ranks(per_day: int) -> int:
    """Ranks expected at least once a day: share × comments >= 1."""
    return int((A * per_day) ** (1 / S))


def tail_rows(per_day: int) -> int:
    """Expected number of rarer ranks mentioned (once) in a day."""
    dense = dense_ranks(per_day)
    return int(A * per_day * (dense ** (1 - S) - VOCABULARY ** (1 - S)) / (S - 1))


TERM = "concat(if(rank % 3 = 0, 'w', 'p'), leftPad(toString(rank), 9, '0'))"
KIND = "if(rank % 3 = 0, 'word', 'phrase')"

# Poisson noise for expected counts of at least 1, approximated by a normal distribution
# (randPoisson only takes a constant mean)
NOISY = (
    "greatest(0, round(expected + sqrt(expected) "
    "* sqrt(-2 * log(randCanonical())) * cos(2 * pi() * randCanonical())))"
)

DAY_SQL = f"""
INSERT INTO term_daily (day, subreddit, source, kind, term, occurrences, docs)
SELECT day, subreddit, 'comment', {KIND}, {TERM}, docs, docs
FROM (
    SELECT {{day:Date}} AS day, {{subreddit:String}} AS subreddit,
           number + 1 AS rank,
           {{per_day:UInt64}} * least({MAX_SHARE}, {A} / pow(rank, {S})) AS expected,
           toUInt64({NOISY}) AS docs
    FROM numbers({{dense:UInt64}})
)
WHERE docs > 0
UNION ALL
SELECT day, subreddit, 'comment', {KIND}, {TERM}, 1, 1
FROM (
    SELECT {{day:Date}} AS day, {{subreddit:String}} AS subreddit,
           -- inverse of the cumulative r^-S between the dense ranks and the vocabulary's end
           toUInt64({{dense:UInt64}} * pow(
               1 - randCanonical() * (1 - pow({VOCABULARY} / {{dense:UInt64}}, {1 - S})),
               {1 / (1 - S)})) AS rank
    FROM numbers({{tail:UInt64}})
)
UNION ALL
SELECT {{day:Date}}, {{subreddit:String}}, 'comment', 'phrase',
       concat('h', hex(rand64())), 1, 1
FROM numbers({{hapax:UInt64}})
"""

HOURS_SQL = """
INSERT INTO scope_hourly (hour, subreddit, source, docs, tokens)
SELECT toDateTime({day:Date}, 'UTC') + INTERVAL number HOUR, {subreddit:String}, 'comment',
       intDiv({per_day:UInt64}, 24), intDiv({per_day:UInt64} * 30, 24)
FROM numbers(24)
"""


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", required=True)
    parser.add_argument("--weeks", type=int, default=53)
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 12))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    if args.database == "wgra":
        raise SystemExit("never into the live database")

    config = load_config(args.config)
    env = Env.from_environ(require_reddit=False)
    admin = connect(env)
    admin.command(f"CREATE DATABASE IF NOT EXISTS {args.database}")
    client = connect(env, database=args.database)
    migrate(client)
    client.command("TRUNCATE TABLE subreddit_groups")
    client.insert(
        "subreddit_groups", config.group_memberships(), column_names=["group_name", "subreddit"]
    )

    scopes = comments_per_day(list(config.subreddits))
    scopes[SAMPLE_SCOPE] = SAMPLE_PER_DAY
    start = args.end - timedelta(weeks=args.weeks)
    days = [start + timedelta(days=offset) for offset in range(7 * args.weeks)]
    started = time.monotonic()
    for number, day in enumerate(days, start=1):
        for subreddit, per_day in scopes.items():
            # the sample is mostly unrelated subreddits: words and two-word phrases only
            hapax = 0 if subreddit == SAMPLE_SCOPE else HAPAX_PER_COMMENT * per_day
            parameters = {
                "day": day,
                "subreddit": subreddit,
                "per_day": per_day,
                "dense": dense_ranks(per_day),
                "tail": tail_rows(per_day),
                "hapax": hapax,
            }
            client.command(DAY_SQL, parameters=parameters)
            client.command(HOURS_SQL, parameters=parameters)
        elapsed = time.monotonic() - started
        print(f"{day}  {number}/{len(days)} days  {elapsed:.0f}s", flush=True)


if __name__ == "__main__":
    main()
