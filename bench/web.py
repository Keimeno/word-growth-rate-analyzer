"""What every endpoint of the web dashboard costs (docs/WEB-DASHBOARD.md §10.4).

Calls each GET endpoint of the API's schema against a database, then reads from
system.query_log, by the `log_comment` every query carries ("web /trends"), how many
queries each made, their time, peak memory and rows read. An endpoint over the budget of
§7.2 (1 s, 500 MB at production scale) is flagged: fix it or precompute it before it ships.
Run it against a ClickHouse of its own, as the other benches (bench/demo.py makes one):

    export CLICKHOUSE_PORT=3617 CLICKHOUSE_PASSWORD=bench CLICKHOUSE_USER=wgra
    uv run python bench/web.py --database wgra_demo --as-of 2026-11-01T12:00:00Z

The path parameters are filled from the database: its strongest trend, its first group, a
story's start, the busiest product of the switches.
"""

from __future__ import annotations

import argparse
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from wgra.config import Env, load_config
from wgra.store import connect
from wgra.web.app import Settings, create_app
from wgra.web.server import openapi, web_client

BUDGET_MS = 1000
BUDGET_BYTES = 500 * 1024**2


def samples(client: Any, now: datetime) -> dict[str, str]:
    """Values for the paths' parameters, from what the database holds."""

    def first(sql: str, default: Any, **parameters: Any) -> Any:
        rows = client.query(sql, parameters={"now": int(now.timestamp()), **parameters}).result_rows
        return rows[0][0] if rows and rows[0][0] not in (None, "") else default

    trend = (
        "FROM trends WHERE detected_at <= toDateTime({now:UInt32}, 'UTC') "
        "ORDER BY detected_at DESC, z DESC LIMIT 1"
    )
    term = first(f"SELECT term {trend}", "ai")
    kind = first(f"SELECT kind {trend}", "word")
    story = (
        "FROM lead_lag_events WHERE start <= toDateTime({now:UInt32}, 'UTC') "
        "ORDER BY start DESC LIMIT 1"
    )
    start = first(f"SELECT start {story}", datetime(2026, 11, 1))
    story_term = first(f"SELECT term {story}", term)
    story_kind = first(f"SELECT kind {story}", kind)
    product = first(
        "SELECT splitByString(' → ', term)[2] FROM term_daily WHERE kind = 'switch' "
        "GROUP BY term ORDER BY sum(docs) DESC LIMIT 1",
        "notion",
    )
    group = first("SELECT group_name FROM channel_groups ORDER BY group_name LIMIT 1", "reddit")
    return {
        "{kind}": kind,
        "{term}": term,
        "{scope}": group,
        "{start}": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "{name}": product,
        "story": f"/api/v1/events/{story_kind}/{start:%Y-%m-%dT%H:%M:%SZ}/{story_term}",
    }


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True)
    parser.add_argument("--as-of", help="the time the API is as of (UNDERCURRENT_NOW)")
    parser.add_argument("--scope", default="reddit", help="the scope of the queries")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()

    env = Env.from_environ()
    admin = connect(env, args.database)
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    values = samples(admin, now)
    settings = Settings(now=now, config=load_config(args.config) if args.config.is_file() else None)
    app = create_app(web_client(env, args.database), settings)
    query = f"scope={args.scope}&terms={values['{term}']}&range=7d&q={values['{term}'][:3]}"
    paths = sorted(
        path
        for path in openapi()["paths"]
        if path.startswith("/api/v1/") and path != "/api/v1/stream"
    )
    started = datetime.now(UTC).replace(microsecond=0)
    timings: dict[str, list[float]] = {}
    statuses: dict[str, int] = {}
    with TestClient(app) as web:
        for path in paths:
            url = values["story"] if path.startswith("/api/v1/events/") else path
            for placeholder, value in values.items():
                url = url.replace(placeholder, value)
            if path == "/api/v1/edge":
                leader = admin.query("SELECT leader, follower FROM propagation_edges LIMIT 1")
                pair = leader.result_rows[0] if leader.result_rows else ("r/a", "b")
                url += f"?leader={pair[0]}&follower={pair[1]}"
            for _ in range(args.repeat):
                begin = time.perf_counter()
                response = web.get(f"{url}{'&' if '?' in url else '?'}{query}")
                timings.setdefault(path, []).append(1000 * (time.perf_counter() - begin))
                statuses[path] = response.status_code

    admin.command("SYSTEM FLUSH LOGS")
    costs = {
        row[0].removeprefix("web "): row[1:]
        for row in admin.query(
            """
            SELECT log_comment, count() / {repeat:UInt32}, max(query_duration_ms),
                   max(memory_usage), sum(read_rows) / {repeat:UInt32}
            FROM system.query_log
            WHERE type = 'QueryFinish' AND log_comment LIKE 'web %'
              AND event_time >= {started:DateTime} AND current_database = {database:String}
            GROUP BY log_comment
            """,
            parameters={"started": started, "database": args.database, "repeat": args.repeat},
        ).result_rows
    }
    columns = ("status", "ms", "queries", "max ms", "peak MB", "rows")
    print(
        f"{'endpoint':42} "
        + " ".join(
            f"{name:>{width}}" for name, width in zip(columns, (6, 7, 7, 7, 8, 12), strict=True)
        )
    )
    over = []
    for path in paths:
        endpoint = path.removeprefix("/api/v1")
        queries, slowest, memory, read = costs.get(endpoint, (0, 0, 0, 0))
        wall = statistics.median(timings[path])
        flag = wall > BUDGET_MS or memory > BUDGET_BYTES
        if flag:
            over.append(endpoint)
        print(
            f"{endpoint:42} {statuses[path]:>6} {wall:>7.0f} {queries:>7.0f} {slowest:>7} "
            f"{memory / 1024**2:>8.1f} {read:>12,.0f}{'  over budget' if flag else ''}"
        )
    print(f"\n{len(paths)} endpoints, {len(over)} over the budget of 1 s or 500 MB")


if __name__ == "__main__":
    main()
