"""Runs the long-term detector over a synthetic database and reports what each query cost.

    CLICKHOUSE_PORT=3617 CLICKHOUSE_PASSWORD=bench uv run python bench/long_term.py \\
        --database wgra_bench --as-of 2026-10-12T00:30

Time, peak memory and rows read per query come from system.query_log (the detector
tags its queries with a log_comment). Nothing is written to the database.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from wgra.config import Env, load_config
from wgra.detect.long_term import LongTermDetector
from wgra.store import connect, migrate


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", required=True)
    parser.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--horizon", type=int, action="append", help="weeks, repeatable")
    parser.add_argument("--scope", action="append", help="only this scope, repeatable")
    args = parser.parse_args()

    config = load_config(args.config)
    client = connect(Env.from_environ(require_reddit=False), database=args.database)
    migrate(client)
    detector = LongTermDetector(client, config)
    as_of = args.as_of.replace(tzinfo=UTC) if args.as_of.tzinfo is None else args.as_of
    scopes = None
    if args.scope:
        from wgra.detect.short_term import load_scopes

        scopes = [scope for scope in load_scopes(client) if scope.name in args.scope]

    started_at = datetime.now(UTC).replace(microsecond=0)
    started = time.monotonic()
    result = detector.run(as_of, scopes=scopes, horizons=args.horizon)
    seconds = time.monotonic() - started
    print(
        f"{len(result.windows)} scopes and windows in {seconds:.1f}s: {result.tested} terms "
        f"tested, {result.candidates} candidates, {len(result.trends)} trends, "
        f"{len(result.insufficient)} without enough history"
    )

    client.command("SYSTEM FLUSH LOGS")
    rows = client.query(
        """
        SELECT log_comment, query_duration_ms, memory_usage, read_rows, read_bytes
        FROM system.query_log
        WHERE type = 'QueryFinish' AND current_database = {database:String}
          AND event_time >= {since:DateTime} AND log_comment LIKE 'long-term %'
        ORDER BY query_duration_ms DESC
        """,
        parameters={"database": args.database, "since": started_at},
    ).result_rows
    if not rows:
        return
    print(
        f"{len(rows)} queries, slowest {rows[0][1] / 1000:.1f}s, "
        f"at most {max(row[2] for row in rows) / 2**20:.0f} MiB, "
        f"{sum(row[3] for row in rows) / 1e9:.2f} billion rows "
        f"({sum(row[4] for row in rows) / 2**30:.1f} GiB) read in all"
    )
    print(f"{'query':<32} {'seconds':>8} {'MiB':>6} {'rows (M)':>9}")
    for comment, duration, memory, read_rows, _ in rows:
        name = comment.removeprefix("long-term ")
        print(f"{name:<32} {duration / 1000:8.1f} {memory / 2**20:6.0f} {read_rows / 1e6:9.1f}")


if __name__ == "__main__":
    main()
