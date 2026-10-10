"""wgra command line: ``wgra ingest | migrate | status | term``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from wgra.config import Env, load_config
from wgra.query import ingestion_status, term_series
from wgra.store import connect, migrate


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
    commands.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    commands.add_parser("status", help="ingestion health").set_defaults(func=cmd_status)

    term = commands.add_parser("term", help="how often a term was mentioned")
    term.add_argument("term")
    term.add_argument("--scope", default="tracked", help="group or subreddit (default: tracked)")
    term.add_argument("--days", type=int, default=7)
    term.add_argument("--bucket", choices=["day", "hour"], default="day")
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
