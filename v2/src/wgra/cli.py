"""wgra command line: ``wgra ingest | analyze | long-term | replay | trends | notify-test |
migrate | status | term``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from wgra.config import Env, load_config
from wgra.detect.short_term import GROUP, Trend
from wgra.notify.messages import per_month_text
from wgra.query import ingestion_status, latest_long_term, latest_trends, term_series
from wgra.store import connect, migrate

if TYPE_CHECKING:
    from wgra.detect.long_term import LongTermResult, LongTermTrend
    from wgra.detect.run import Analyzer


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    cells = [[str(header) for header in headers]] + [[str(cell) for cell in row] for row in rows]
    widths = [max(len(row[column]) for row in cells) for column in range(len(headers))]
    for index, row in enumerate(cells):
        print("  ".join(cell.rjust(width) for cell, width in zip(row, widths, strict=True)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def cmd_ingest(args: argparse.Namespace) -> None:
    from wgra.ingest.run import run_ingest

    config = load_config(args.config)
    env = Env.from_environ()

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_ingest(config, env, stop)

    asyncio.run(main())


def _analyzer(args: argparse.Namespace, notify: bool = True) -> Analyzer:
    from wgra.detect.run import Analyzer
    from wgra.notify.ntfy import Ntfy

    config = load_config(args.config)
    env = Env.from_environ(require_reddit=False)
    client = connect(env)
    if applied := migrate(client):
        logging.getLogger(__name__).info("applied migrations: %s", ", ".join(applied))
    ntfy = Ntfy(env.ntfy_url, env.ntfy_topic, env.ntfy_token) if notify else None
    return Analyzer(config, env, client, ntfy)


def _until_stopped() -> threading.Event:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def cmd_analyze(args: argparse.Namespace) -> None:
    analyzer = _analyzer(args, notify=not args.no_notify)
    if not args.once:
        analyzer.run_forever(_until_stopped(), long_term=not args.no_long_term)
        return

    result = analyzer.run_once()
    per_horizon = Counter(trend.horizon for trend in result.trends)
    print(
        f"{result.detected_at:%Y-%m-%d %H:%M} UTC: {len(result.trends)} trends "
        f"({', '.join(f'{h}: {n}' for h, n in sorted(per_horizon.items())) or 'none'}) "
        f"in {len({trend.scope for trend in result.trends})} scopes, {result.seconds:.1f}s"
    )
    print(f"alerts: {dict(result.alerts) or 'none'}")
    print(f"digests: {', '.join(result.digests) or 'none'}")
    top = sorted(
        (trend for trend in result.trends if not trend.subsumed_by),
        key=lambda trend: trend.z,
        reverse=True,
    )
    if top:
        print()
        _print_trends(top[: args.top])


def _print_trends(trends: Sequence[Trend]) -> None:
    _print_table(
        TREND_HEADERS,
        [
            (
                trend.horizon,
                trend.scope,
                trend.term,
                f"{trend.z:.1f}",
                f"{trend.ratio:.1f}",
                trend.mentions,
                trend.authors,
                "new" if trend.is_new else "",
                f"{trend.breadth}/{trend.members}" if trend.scope_type == GROUP else "",
                f"{trend.reference_days}d",
                trend.alert,
            )
            for trend in trends
        ],
    )


TREND_HEADERS = (
    "horizon",
    "scope",
    "term",
    "z",
    "times",
    "mentions",
    "authors",
    "new",
    "breadth",
    "history",
    "alert",
)


def cmd_long_term(args: argparse.Namespace) -> None:
    analyzer = _analyzer(args, notify=not args.no_notify)
    if not args.once:
        analyzer.run_forever(_until_stopped(), short_term=False)
        return
    as_of = args.as_of or datetime.now(UTC)
    result = analyzer.run_long_term(as_of, write=not args.dry_run)
    _print_long_term_result(result)
    top = sorted(result.trends, key=lambda trend: (trend.category, trend.rank, trend.horizon))
    if top:
        print()
        _print_long_term(top[: args.top])
    if args.dry_run:
        print("\ndry run, nothing stored")


def _print_long_term_result(result: LongTermResult) -> None:
    print(
        f"Long-term trends as of {result.detected_at:%Y-%m-%d %H:%M} UTC: the complete weeks "
        f"before {result.week:%a %Y-%m-%d}, {result.seconds:.1f}s"
    )
    horizons = sorted(
        {stats.window.weeks for stats in result.windows}
        | {gap.weeks for gap in result.insufficient}
    )
    for weeks in horizons:
        windows = [stats for stats in result.windows if stats.window.weeks == weeks]
        gaps = [gap for gap in result.insufficient if gap.weeks == weeks]
        if not windows:
            most = max((gap.available for gap in gaps), default=0)
            print(
                f"  {weeks}w: insufficient history in all {len(gaps)} scopes, "
                f"at most {most} of {weeks} weeks"
            )
            continue
        categories = Counter(
            trend.category for trend in result.trends if trend.horizon == f"{weeks}w"
        )
        print(
            f"  {weeks}w: {len(windows)} scopes, {sum(s.above_floor for s in windows):,} terms "
            f"tested, {sum(s.candidates for s in windows):,} candidates: "
            + (", ".join(f"{n} {category}" for category, n in sorted(categories.items())) or "none")
        )
        if gaps:
            print(
                "       insufficient history: "
                + ", ".join(f"{gap.scope} ({gap.available} of {weeks} weeks)" for gap in gaps)
            )
    if result.first_week and not result.windows:
        print(
            f"The first complete week of data starts {result.first_week:%a %Y-%m-%d}: "
            f"{min(horizons, default=13)} weeks of history from "
            f"{result.first_week + timedelta(weeks=min(horizons, default=13)):%a %Y-%m-%d} on."
        )


def _print_long_term(trends: Sequence[LongTermTrend]) -> None:
    _print_table(
        ("horizon", "scope", "term", "category", "per month", "q", "spike", "per 1k", "mentions"),
        [
            (
                trend.horizon,
                trend.scope,
                trend.term,
                trend.category,
                per_month_text(trend.growth),
                f"{trend.q_value:.1e}",
                f"{trend.spike_share:.2f}",
                f"{trend.start_share:.2f} → {trend.end_share:.2f}",
                trend.mentions,
            )
            for trend in trends
        ],
    )


def cmd_trends(args: argparse.Namespace) -> None:
    client = connect(Env.from_environ(require_reddit=False))
    if args.horizon.endswith("w"):
        week, long_term = latest_long_term(client, args.horizon, args.scope, args.limit)
        if week is None:
            print(f"no {args.horizon} trends yet, see `wgra long-term --once`")
            return
        print(f"{args.horizon} trends of the weeks before {week:%a %Y-%m-%d}")
        _print_long_term(long_term)
        return
    detected_at, trends = latest_trends(client, args.horizon, args.scope, args.limit)
    if detected_at is None:
        print("no trends yet, run `wgra analyze --once`")
        return
    print(f"{args.horizon} trends as of {detected_at:%Y-%m-%d %H:%M} UTC")
    _print_trends(trends)


def cmd_replay(args: argparse.Namespace) -> None:
    from wgra.detect.replay import open_csv, replay, report
    from wgra.detect.short_term import load_scopes

    config = load_config(args.config)
    overrides = {
        name: getattr(args, name)
        for name in ("min_mentions", "min_authors", "min_ratio", "min_z")
        if getattr(args, name) is not None
    }
    detect = replace(
        config.detect,
        thresholds=replace(config.detect.thresholds, **overrides),
        scope_thresholds={
            scope: replace(thresholds, **overrides)
            for scope, thresholds in config.detect.scope_thresholds.items()
        },
        **{
            name: getattr(args, name)
            for name in ("prior_weight", "prior_floor")
            if getattr(args, name) is not None
        },
    )
    notify = config.notify
    if args.alert_min_z is not None:
        notify = replace(notify, alert_min_z=args.alert_min_z)
    config = replace(config, detect=detect, notify=notify)

    client = connect(Env.from_environ(require_reddit=False))
    scopes = load_scopes(client, config.detect.exclude_scopes)
    if args.scope:
        scopes = [scope for scope in scopes if scope.name in args.scope]
    horizons = [h for h in config.detect.horizons if not args.horizon or h.name in args.horizon]
    end = args.to or datetime.now(UTC)
    start = args.start or end - timedelta(days=7)

    def progress(at: datetime, trends: list[Trend]) -> None:
        print(f"  {at:%Y-%m-%d %H:%M}  {len(trends)} trends", file=sys.stderr)

    out = open_csv(args.csv)
    try:
        result = replay(
            client,
            config,
            start,
            end,
            timedelta(hours=args.step),
            scopes=scopes,
            horizons=horizons,
            out=out,
            progress=progress,
        )
    finally:
        if out:
            out.close()
    print(report(result, scopes))


def cmd_notify_test(args: argparse.Namespace) -> None:
    analyzer = _analyzer(args)
    analyzer.send_test()
    env = Env.from_environ(require_reddit=False)
    print(f"sent to {env.ntfy_url}/{env.ntfy_topic}")


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def cmd_migrate(_: argparse.Namespace) -> None:
    applied = migrate(connect(Env.from_environ(require_reddit=False)))
    print(f"applied: {', '.join(applied)}" if applied else "already up to date")


def cmd_status(_: argparse.Namespace) -> None:
    status = ingestion_status(connect(Env.from_environ(require_reddit=False)))
    print("Feeds, last hour")
    _print_table(
        ["feed", "polls", "errors", "new items", "gaps", "every s", "items/min", "last poll"],
        status["feeds"],
    )
    print("\nTracked subreddits, last 24h")
    _print_table(["subreddit", "comments", "posts"], status["subreddits"])
    print("\nStorage")
    _print_table(["table", "rows", "size"], status["tables"])


def cmd_term(args: argparse.Namespace) -> None:
    client = connect(Env.from_environ(require_reddit=False))
    points = term_series(client, args.term, args.scope, args.days, args.bucket)
    print(f'"{args.term}" in {args.scope}, comments and posts mentioning it')
    _print_table(
        ["bucket", "mentions", "authors", "of total", "per 1k"],
        [
            (point.bucket, point.docs, point.authors, point.total_docs, f"{point.per_thousand:.2f}")
            for point in points
        ],
    )


def main(argv: Sequence[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="wgra", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("WGRA_CONFIG", "config.yaml")),
        help="path to config.yaml (default: $WGRA_CONFIG or ./config.yaml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(required=True, metavar="command")

    commands.add_parser("ingest", help="poll reddit and store counts").set_defaults(func=cmd_ingest)

    analyze = commands.add_parser("analyze", help="detect trends every 15 minutes and alert")
    analyze.add_argument("--once", action="store_true", help="run once and print the result")
    analyze.add_argument(
        "--no-notify", action="store_true", help="send nothing, mark alerts as muted"
    )
    analyze.add_argument("--top", type=int, default=25, help="trends to print with --once")
    analyze.add_argument(
        "--no-long-term", action="store_true", help="no daily long-term run and weekly reports"
    )
    analyze.set_defaults(func=cmd_analyze)

    long_term = commands.add_parser(
        "long-term",
        help="detect long-term trends (wgra analyze also runs it once a day)",
        description="Theil–Sen and Mann–Kendall on weekly shares over 13, 26 and 52 weeks. "
        "Without --once, runs it every day after long_term.run_at and sends the weekly "
        "reports, for running it apart from `wgra analyze --no-long-term`.",
    )
    long_term.add_argument("--once", action="store_true", help="run once and print the result")
    long_term.add_argument(
        "--as-of",
        type=_utc,
        help="UTC date or time to run as of, e.g. 2026-12-01: analyzes the complete weeks "
        "before its week (default: now)",
    )
    long_term.add_argument("--dry-run", action="store_true", help="store nothing")
    long_term.add_argument("--no-notify", action="store_true", help="no weekly reports")
    long_term.add_argument("--top", type=int, default=30, help="trends to print with --once")
    long_term.set_defaults(func=cmd_long_term)

    trends = commands.add_parser("trends", help="the latest trends the analyzer found")
    trends.add_argument("--scope", help="a group or r/subreddit (default: all)")
    trends.add_argument("--horizon", default="24h", help="24h, 6h, or long-term: 13w, 26w, 52w")
    trends.add_argument("--limit", type=int, default=30)
    trends.set_defaults(func=cmd_trends)

    replay = commands.add_parser(
        "replay",
        help="re-run detection over stored history, to tune thresholds",
        description="Runs the detector as of past times. Writes and sends nothing.",
    )
    replay.add_argument(
        "--from", dest="start", type=_utc, help="UTC, e.g. 2026-10-12T00:00 (default: 7 days ago)"
    )
    replay.add_argument("--to", type=_utc, help="UTC (default: now)")
    replay.add_argument("--step", type=int, default=1, help="hours between runs (default: 1)")
    replay.add_argument("--horizon", action="append", help="only this horizon, repeatable")
    replay.add_argument("--scope", action="append", help="only this scope, repeatable")
    for name, kind in [
        ("min-mentions", int),
        ("min-authors", int),
        ("min-ratio", float),
        ("min-z", float),
        ("alert-min-z", float),
        ("prior-weight", float),
        ("prior-floor", float),
    ]:
        replay.add_argument(f"--{name}", type=kind, help="override config.yaml")
    replay.add_argument("--csv", type=Path, help="write every trend of every step to a csv file")
    replay.set_defaults(func=cmd_replay)

    commands.add_parser("notify-test", help="send a test notification").set_defaults(
        func=cmd_notify_test
    )
    commands.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    commands.add_parser("status", help="ingestion health").set_defaults(func=cmd_status)

    term = commands.add_parser("term", help="how often a term was mentioned")
    term.add_argument("term")
    term.add_argument("--scope", default="tracked", help="group or subreddit (default: tracked)")
    term.add_argument("--days", type=int, default=7)
    term.add_argument("--bucket", choices=["day", "hour", "week"], default="day")
    term.set_defaults(func=cmd_term)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # every request would be logged otherwise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
