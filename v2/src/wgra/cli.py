"""wgra command line: ``wgra ingest | analyze | long-term | lead-lag | replay | trends |
edges | forecasts | suggest-subreddits | wikipedia | notify-test | migrate | status | term``."""

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
    from clickhouse_connect.driver.client import Client

    from wgra.config import Config
    from wgra.detect.long_term import LongTermResult, LongTermTrend
    from wgra.detect.run import Analyzer
    from wgra.leadlag.edges import Edge
    from wgra.leadlag.evaluate import Step
    from wgra.leadlag.forecasts import Forecast


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
    if args.no_lead_lag:
        analyzer.lead_lag = None
    if not args.once:
        analyzer.run_forever(
            _until_stopped(), long_term=not args.no_long_term, lead_lag=not args.no_lead_lag
        )
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
    if result.forecasts and result.forecasts.new:
        print(f"\nnew forecasts ({len(result.forecasts.resolved)} resolved)")
        _print_forecasts(result.forecasts.new)


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


def _hours(value: float) -> str:
    return f"{value / 24:.1f}d" if value >= 48 else f"{value:.0f}h"


def _print_edges(edges: Sequence[Edge]) -> None:
    _print_table(
        (
            "topic",
            "leader",
            "follower",
            "lead (IQR)",
            "n",
            "hits",
            "hit rate",
            "base",
            "p (80%)",
            "lift",
            "q",
        ),
        [
            (
                edge.topic,
                edge.leader,
                edge.follower + (" (rest)" if edge.without_leader else ""),
                f"{_hours(edge.lag_median)} ({_hours(edge.lag_q25)}–{_hours(edge.lag_q75)})",
                edge.events,
                edge.hits,
                f"{edge.hit_rate:.0%}",
                f"{edge.base_rate:.0%}",
                f"{edge.probability:.0%} ({edge.probability_low:.0%}–{edge.probability_high:.0%})",
                f"{edge.lift:.1f}",
                f"{edge.q_value:.0e}",
            )
            for edge in edges
        ],
    )


def _print_forecasts(forecasts: Sequence[Forecast]) -> None:
    _print_table(
        ("created", "term", "leader", "follower", "chance", "expected", "due", "outcome", "alert"),
        [
            (
                f"{forecast.created_at:%m-%d %H:%M}",
                forecast.term,
                forecast.leader,
                forecast.follower,
                f"{forecast.probability:.0%} ({forecast.probability_low:.0%}–"
                f"{forecast.probability_high:.0%})",
                f"{forecast.expected_at:%m-%d %H:00}",
                f"{forecast.due_by:%m-%d %H:00}",
                forecast.outcome,
                forecast.alert,
            )
            for forecast in forecasts
        ],
    )


def cmd_lead_lag(args: argparse.Namespace) -> None:
    analyzer = _analyzer(args, notify=False)
    if analyzer.lead_lag is None:
        raise SystemExit("lead_lag.enabled is false in config.yaml")
    if not args.once:
        analyzer.run_forever(_until_stopped(), short_term=False, long_term=False)
        return
    learned = analyzer.run_lead_lag(args.as_of or datetime.now(UTC), write=not args.dry_run)
    result = learned.edges
    print(
        f"Lead–lag as of {learned.as_of:%Y-%m-%d %H:%M} UTC, {learned.seconds:.1f}s: "
        f"{learned.new_sightings} trend sightings, onsets of {learned.computed} open events, "
        f"{result.training_events} events since {result.training_start:%Y-%m-%d} "
        f"({result.closed_events} closed), {result.tested} pairs tested, "
        f"{len(result.edges)} edges"
    )
    if result.edges:
        print()
        _print_edges(result.edges[: args.top])
    elif result.closed_events < 50:
        print(
            "Edges need history: every event takes 2 × max_lag_days to close, and a pair "
            "needs lead_lag.min_events. Expect the first after 4–6 weeks of collection."
        )
    if args.dry_run:
        print("\ndry run, nothing stored")


def cmd_edges(args: argparse.Namespace) -> None:
    from wgra.leadlag.edges import load_edges

    client = connect(Env.from_environ(require_reddit=False))
    day, edges = load_edges(client)
    if day is None:
        print("no edges yet, see `wgra lead-lag --once`")
        return
    edges = [
        edge
        for edge in edges
        if (args.topic is None or edge.topic == args.topic)
        and (args.leader is None or edge.leader == args.leader)
        and (args.follower is None or edge.follower == args.follower)
    ]
    print(f"edges learned on {day:%Y-%m-%d}")
    _print_edges(sorted(edges, key=lambda edge: -edge.lift)[: args.limit])


def cmd_forecasts(args: argparse.Namespace) -> None:
    from wgra.leadlag.forecasts import HIT, MISS, PENDING, load_forecasts

    client = connect(Env.from_environ(require_reddit=False))
    forecasts = load_forecasts(client, since=datetime.now(UTC) - timedelta(days=args.days))
    pending = [f for f in forecasts if f.outcome == PENDING]
    resolved = [f for f in forecasts if f.outcome in (HIT, MISS)]
    hits = sum(f.outcome == HIT for f in resolved)
    print(
        f"forecasts of the last {args.days} days: {len(pending)} pending, {len(resolved)} "
        "resolved" + (f", {hits} came true ({hits / len(resolved):.0%})" if resolved else "")
    )
    shown = pending if args.pending else forecasts
    if shown:
        print()
        _print_forecasts(sorted(shown, key=lambda f: f.created_at, reverse=True)[: args.limit])


def cmd_suggest_subreddits(args: argparse.Namespace) -> None:
    from wgra.leadlag.suggest import suggest, yaml_snippet

    config = load_config(args.config)
    client = connect(Env.from_environ(require_reddit=False))
    result = suggest(
        client,
        config.subreddits,
        datetime.now(UTC),
        hours=args.hours,
        terms=args.terms,
        min_terms=args.min_terms,
        min_reference_days=0 if args.include_warmup else config.detect.min_reference_days,
        limit=args.limit,
    )
    print(
        f"{result.rising} rising terms, {result.sampled_items:,} sampled comments and posts "
        f"from untracked subreddits since {result.since:%Y-%m-%d %H:%M} UTC"
    )
    if not result.candidates:
        print("no candidates" + ("" if result.rising else ": nothing rising past the warmup"))
        return
    print()
    _print_table(
        (
            "subreddit",
            "rising terms",
            "first",
            "before trending",
            "mentions",
            "sampled",
            "examples",
        ),
        [
            (c.subreddit, c.terms, c.first, c.early, c.mentions, c.items, ", ".join(c.examples[:4]))
            for c in result.candidates
        ],
    )
    print(
        "\nCandidates for config.yaml (nothing was changed). Add the ones you want to a group "
        "and restart the ingester:\n"
    )
    print(yaml_snippet(result.candidates))


def cmd_wikipedia(args: argparse.Namespace) -> None:
    from wgra.leadlag.wikipedia import (
        Wikimedia,
        WikipediaCheck,
        load_leads,
        summarize,
        summary_text,
    )

    config = load_config(args.config)
    client = connect(Env.from_environ(require_reddit=False))
    migrate(client)
    now = datetime.now(UTC)
    if args.fetch:
        wikimedia = Wikimedia(config.wikipedia)
        try:
            WikipediaCheck(client, config, wikimedia).run(now, args.days, args.max_events)
        finally:
            wikimedia.close()
    leads = load_leads(client, config.wikipedia.project, now - timedelta(days=args.days))
    print(
        f"Reddit onsets vs Wikipedia interest ({config.wikipedia.project}), last {args.days} days"
    )
    for line in summary_text(summarize(leads)):
        print(line)


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
    lead_lag = replace(
        config.lead_lag,
        **{
            name: getattr(args, name)
            for name in ("event_min_z", "max_lag_days", "min_events", "max_q")
            if getattr(args, name) is not None
        },
    )
    forecast = replace(
        config.forecast,
        **{
            name: getattr(args, f"forecast_{name}")
            for name in ("min_probability", "min_lift")
            if getattr(args, f"forecast_{name}") is not None
        },
    )
    config = replace(config, detect=detect, notify=notify, lead_lag=lead_lag, forecast=forecast)

    client = connect(Env.from_environ(require_reddit=False))
    scopes = load_scopes(client, config.detect.exclude_scopes)
    if args.scope:
        scopes = [scope for scope in scopes if scope.name in args.scope]
    horizons = [h for h in config.detect.horizons if not args.horizon or h.name in args.horizon]
    end = args.to or datetime.now(UTC)
    start = args.start or end - timedelta(days=7)

    def progress(at: datetime, trends: list[Trend]) -> None:
        print(f"  {at:%Y-%m-%d %H:%M}  {len(trends)} trends", file=sys.stderr)

    if args.forecast and args.events == "stored":
        # the stored trends instead of the detector: fast, with the live settings
        from wgra.detect.replay import stored_steps

        steps = stored_steps(
            client, start, end, timedelta(hours=args.step), config.lead_lag.event_min_z
        )
        _print_forecast_evaluation(client, config, steps)
        return

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
            forecast_min_z=config.lead_lag.event_min_z if args.forecast else None,
        )
    finally:
        if out:
            out.close()
    print(report(result, scopes))
    if args.forecast:
        print()
        _print_forecast_evaluation(client, config, result.sighting_steps)


def _print_forecast_evaluation(client: Client, config: Config, steps: Sequence[Step]) -> None:
    from wgra.leadlag.evaluate import evaluate
    from wgra.leadlag.evaluate import report as forecast_report

    if not steps:
        print("forecasts: nothing replayed")
        return
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    print(forecast_report(evaluate(client, config, steps, now)))


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
    analyze.add_argument(
        "--no-lead-lag", action="store_true", help="no lead–lag edges and forecasts"
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

    lead_lag = commands.add_parser(
        "lead-lag",
        help="learn which subreddits lead others (wgra analyze also runs it once a day)",
        description="Turns new trends into events, computes every scope's onset for them "
        "and learns the leader -> follower edges. Without --once, runs it every day after "
        "lead_lag.run_at.",
    )
    lead_lag.add_argument("--once", action="store_true", help="run once and print the edges")
    lead_lag.add_argument("--as-of", type=_utc, help="UTC time to run as of (default: now)")
    lead_lag.add_argument("--dry-run", action="store_true", help="store nothing")
    lead_lag.add_argument("--top", type=int, default=40, help="edges to print")
    lead_lag.set_defaults(func=cmd_lead_lag)

    edges = commands.add_parser("edges", help="the latest leader -> follower edges")
    edges.add_argument("--topic", help="all, or a group (default: every topic)")
    edges.add_argument("--leader", help="r/subreddit")
    edges.add_argument("--follower", help="r/subreddit, a group or sample")
    edges.add_argument("--limit", type=int, default=50)
    edges.set_defaults(func=cmd_edges)

    forecasts = commands.add_parser("forecasts", help="forecasts and how they turned out")
    forecasts.add_argument("--days", type=int, default=14)
    forecasts.add_argument("--pending", action="store_true", help="only those still open")
    forecasts.add_argument("--limit", type=int, default=50)
    forecasts.set_defaults(func=cmd_forecasts)

    suggest = commands.add_parser(
        "suggest-subreddits",
        help="untracked subreddits where rising terms show up early or often",
        description="From the r/all sample's comments and posts of the last 48 hours: the "
        "untracked subreddits that mention the terms trending now early or more than their "
        "size explains. Prints candidates for config.yaml, never changes it.",
    )
    suggest.add_argument("--hours", type=int, default=48, help="at most 48 (default)")
    suggest.add_argument("--terms", type=int, default=100, help="rising terms to look for")
    suggest.add_argument("--min-terms", type=int, default=2)
    suggest.add_argument("--limit", type=int, default=25)
    suggest.add_argument(
        "--include-warmup", action="store_true", help="count trends of scopes without history"
    )
    suggest.set_defaults(func=cmd_suggest_subreddits)

    wikipedia = commands.add_parser(
        "wikipedia",
        help="do reddit onsets come before interest on Wikipedia?",
        description="Looks up the Wikipedia articles of closed events' terms and their daily "
        "pageviews (cached), and compares when interest started there with the reddit onsets. "
        "Free, no key. wgra analyze does it daily with wikipedia.enabled.",
    )
    wikipedia.add_argument("--days", type=int, default=90)
    wikipedia.add_argument("--max-events", type=int, default=200)
    wikipedia.add_argument(
        "--no-fetch", dest="fetch", action="store_false", help="only summarize what's stored"
    )
    wikipedia.set_defaults(func=cmd_wikipedia)

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
    replay.add_argument(
        "--forecast",
        action="store_true",
        help="also evaluate lead–lag forecasts: precision, recall, lead time, calibration",
    )
    replay.add_argument(
        "--events",
        choices=["detector", "stored"],
        default="detector",
        help="with --forecast: re-run the detector (default), or use the stored trends (fast)",
    )
    for name, kind in [
        ("event-min-z", float),
        ("max-lag-days", int),
        ("min-events", int),
        ("max-q", float),
        ("forecast-min-probability", float),
        ("forecast-min-lift", float),
    ]:
        replay.add_argument(f"--{name}", type=kind, help="override config.yaml (lead–lag)")
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
