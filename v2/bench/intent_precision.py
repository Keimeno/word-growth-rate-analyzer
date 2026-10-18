"""Measures the precision of intent extraction on live data.

1. `sample` runs the extractor over the raw items in ClickHouse (read-only, the last 48
   hours) and writes up to N random extractions per kind to a JSON lines file, with the
   sentence each came from. The file holds reddit text: keep it out of the repository and
   delete it after labeling (reddit asks API users to delete stored content within 48h).
2. Label it: set "correct" to true or false on every line (docs/ARCHITECTURE-V2.md §4.7
   has the rules).
3. `score` prints the precision per kind and per pattern, with 95% Wilson intervals.

    uv run python bench/intent_precision.py sample /tmp/intents.jsonl --per-kind 50 \\
        --since 2026-10-11T11:09:20
    uv run python bench/intent_precision.py score /tmp/intents.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from wgra.config import Env, load_config
from wgra.ingest.backfill import real_subreddit
from wgra.store import connect
from wgra.text.intents import INTENT_KINDS, extractor, sentences_as_written
from wgra.text.terms import clean


def sample(args: argparse.Namespace) -> None:
    load_dotenv()
    config = load_config(args.config)
    client = connect(Env.from_environ(require_reddit=False))
    found: dict[str, list[dict[str, object]]] = defaultdict(list)
    items = 0
    with client.query_rows_stream(
        "SELECT id, subreddit, created_at, permalink, text FROM items FINAL "
        "WHERE created_at > toDateTime({since:UInt32}, 'UTC')",
        parameters={"since": int(args.since.timestamp())},
    ) as stream:
        for item_id, scope, created_at, permalink, text in stream:
            items += 1
            language = config.language(real_subreddit(permalink))
            extract = extractor(language)
            for sentence, tokens in sentences_as_written(clean(text), language):
                for pattern, term in extract.matches(tokens):
                    found[pattern.kind].append(
                        {
                            "kind": pattern.kind,
                            "term": term,
                            "pattern": pattern.label,
                            "language": language,
                            "scope": scope,
                            "subreddit": real_subreddit(permalink),
                            "created_at": f"{created_at:%Y-%m-%d %H:%M}",
                            "id": item_id,
                            "sentence": " ".join(sentence.split()),
                            "correct": None,
                        }
                    )
    rng = random.Random(args.seed)
    with args.out.open("w", encoding="utf-8") as out:
        for kind in INTENT_KINDS:
            chosen = rng.sample(found[kind], min(args.per_kind, len(found[kind])))
            for row in chosen:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{kind}: {len(found[kind])} extractions, {len(chosen)} sampled")
    print(f"from {items:,} items created after {args.since:%Y-%m-%d %H:%M} UTC -> {args.out}")


def wilson(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if not total:
        return 0.0, 1.0
    share = correct / total
    middle = share + z * z / (2 * total)
    spread = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total))
    denominator = 1 + z * z / total
    return (middle - spread) / denominator, (middle + spread) / denominator


def score(args: argparse.Namespace) -> None:
    rows = [json.loads(line) for line in args.labels.open(encoding="utf-8") if line.strip()]
    unlabeled = [row for row in rows if row["correct"] is None]
    if unlabeled:
        raise SystemExit(f"{len(unlabeled)} rows have no label yet")

    def report(name: str, group: list[dict[str, object]]) -> None:
        correct = sum(bool(row["correct"]) for row in group)
        low, high = wilson(correct, len(group))
        print(
            f"{name:40} {correct:3} of {len(group):3}  {correct / len(group):5.0%}  "
            f"({low:.0%}–{high:.0%})"
        )

    by_kind: dict[str, list[dict[str, object]]] = defaultdict(list)
    by_pattern: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_kind[str(row["kind"])].append(row)
        by_pattern[f"{row['kind']}: {row['pattern']}"].append(row)
    print("precision per kind (95% Wilson interval)")
    for kind in INTENT_KINDS:
        if by_kind[kind]:
            report(kind, by_kind[kind])
    print("\nper pattern")
    for name in sorted(by_pattern):
        report(name, by_pattern[name])


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    sampler = commands.add_parser("sample", help="sample extractions from the live items")
    sampler.add_argument("out", type=Path, help="JSON lines file, outside the repository")
    sampler.add_argument("--per-kind", type=int, default=50)
    sampler.add_argument("--since", type=_utc, default=datetime(2000, 1, 1, tzinfo=UTC))
    sampler.add_argument("--seed", type=int, default=1)
    sampler.add_argument("--config", type=Path, default=Path("config.yaml"))
    sampler.set_defaults(func=sample)
    scorer = commands.add_parser("score", help="precision of a labeled sample")
    scorer.add_argument("labels", type=Path)
    scorer.set_defaults(func=score)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
