"""Intents through the whole system, against a real ClickHouse: ingest, short-term,
long-term and lead-lag detection with their per-kind thresholds, the reports and the
backfill. Uses throwaway databases (conftest.py), skipped when ClickHouse isn't reachable
locally."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from helpers import make_config, make_item

from wgra.config import SAMPLE_SCOPE, IntentsConfig, LongTermConfig
from wgra.detect.long_term import LongTermDetector
from wgra.detect.short_term import Detector
from wgra.ingest.backfill import backfill_intents, real_subreddit
from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor
from wgra.leadlag.events import Event
from wgra.leadlag.onsets import OnsetFinder
from wgra.query import intent_examples, intent_report
from wgra.store import migrate
from wgra.text.intents import INTENT_KINDS

FLOW = "notion → obsidian"
CONFIG = make_config(groups={"tech": ["r/technology", "r/programming"]})


class Comments:
    """Comments as the ingester writes them: items, and one term row per term."""

    def __init__(self) -> None:
        self.items: list[tuple[object, ...]] = []
        self.terms: list[tuple[object, ...]] = []

    def add(
        self, subreddit: str, hour: datetime, count: int, terms: Sequence[tuple[str, str]] = ()
    ) -> None:
        for index in range(count):
            number = len(self.items) + 1
            self.items.append(
                (
                    f"t1_{number}",
                    "comment",
                    subreddit,
                    hour + timedelta(minutes=index % 60),
                    number,
                    "text",
                    f"/r/{subreddit}/comments/x/{number}",
                    10,
                    sorted(term for kind, term in terms if kind in INTENT_KINDS),
                )
            )
            for kind, term in terms:
                self.terms.append((hour, subreddit, "comment", kind, term, number, 1))

    def insert(self, client) -> None:
        client.insert("items", self.items, column_names=list(ITEM_COLUMNS))
        client.insert("term_events", self.terms, column_names=list(TERM_COLUMNS))


def hours(start: datetime, end: datetime) -> list[datetime]:
    return [start + timedelta(hours=n) for n in range(int((end - start) / timedelta(hours=1)))]


def setup(client) -> None:
    migrate(client)
    client.insert(
        "subreddit_groups", CONFIG.group_memberships(), column_names=["group_name", "subreddit"]
    )


# short term: the 24h window ends Sep 30 12:00
END = datetime(2026, 9, 30, 12, tzinfo=UTC)
START = END - timedelta(days=29)


def short_term_history(client) -> None:
    setup(client)
    comments = Comments()
    for hour in hours(START, END):
        comments.add("technology", hour, 20)
        comments.add("programming", hour, 10)
        comments.add(SAMPLE_SCOPE, hour, 40)
        if hour.hour == 9:
            # complained about every day: never a trend
            comments.add("technology", hour, 1, [("complaint", "complaint: reddit")])
    burst = END - timedelta(hours=3)
    # four people switching: rare for words, news for a switch
    comments.add("technology", burst, 4, [("switch", FLOW), ("word", "notion")])
    # and the word bursting much harder
    comments.add("technology", burst, 30, [("word", "notion")])
    comments.insert(client)


def test_short_term_detection_scores_intents_with_their_own_gates(client):
    short_term_history(client)
    trends = {
        (trend.scope, trend.term): trend
        for trend in Detector(client, CONFIG).run(END)
        if trend.horizon == "24h"
    }
    flow = trends["r/technology", FLOW]
    assert (flow.kind, flow.mentions, flow.authors, flow.reference_mentions) == ("switch", 4, 4, 0)
    assert flow.z > 3
    assert flow.rank == 1  # ranked among switches, not among words
    assert trends["r/technology", "notion"].rank == 1
    assert trends["tech", FLOW].kind == "switch"
    assert ("r/technology", "complaint: reddit") not in trends


def test_intents_have_their_own_share_of_the_stored_trends(client):
    short_term_history(client)
    one_each = replace(CONFIG, detect=replace(CONFIG.detect, max_per_scope=1, max_per_intent=1))
    stored = [
        (trend.term, trend.rank)
        for trend in Detector(client, one_each).run(END)
        if (trend.horizon, trend.scope) == ("24h", "r/technology")
    ]
    assert sorted(stored) == [("notion", 1), (FLOW, 1)]


def test_without_the_intent_gates_switches_need_as_many_mentions_as_words(client):
    short_term_history(client)
    gates_of_words = replace(CONFIG, detect=replace(CONFIG.detect, kind_thresholds={}))
    terms = {trend.term for trend in Detector(client, gates_of_words).run(END)}
    assert "notion" in terms
    assert FLOW not in terms


# long term: as of Monday 2026-06-22, 14 weeks of history
WEEKS_END = date(2026, 6, 22)
WEEKS_START = WEEKS_END - timedelta(weeks=14)


def long_term_history(client) -> None:
    setup(client)
    totals, terms = [], []
    for offset in range((WEEKS_END - WEEKS_START).days):
        day = WEEKS_START + timedelta(days=offset)
        week = offset // 7
        totals.append((datetime(day.year, day.month, day.day), "technology", "comment", 2000, 0))
        if day.weekday() == 0:
            # one more switch every week: 1 to 14 a week, far below the 20 words need
            terms.append((day, "technology", "comment", "switch", FLOW, week + 1, week + 1))
        # a word growing too, with the volume words need
        terms.append((day, "technology", "comment", "word", "obsidian", 5 + week, 5 + week))
    client.insert(
        "scope_hourly", totals, column_names=["hour", "subreddit", "source", "docs", "tokens"]
    )
    client.insert(
        "term_daily",
        terms,
        column_names=["day", "subreddit", "source", "kind", "term", "occurrences", "docs"],
    )


def long_term(client, settings: LongTermConfig) -> dict[str, str]:
    config = replace(CONFIG, long_term=settings)
    result = LongTermDetector(client, config).run(
        datetime(2026, 6, 22, 0, 30, tzinfo=UTC), horizons=[13]
    )
    return {trend.term: trend.category for trend in result.trends if trend.scope == "r/technology"}


def test_long_term_detection_floors_intents_lower(client):
    long_term_history(client)
    assert long_term(client, LongTermConfig(horizons=(13,))) == {
        FLOW: "emerging",
        "obsidian": "mainstreaming",
    }
    # at the words' floor the switch isn't tested
    words_floor = LongTermConfig(horizons=(13,), kind_min_mentions_per_week={})
    assert long_term(client, words_floor) == {"obsidian": "mainstreaming"}


def test_long_term_candidates_are_limited_per_ranking(client):
    long_term_history(client)
    one = LongTermConfig(horizons=(13,), max_candidates=1)
    assert set(long_term(client, one)) == {FLOW, "obsidian"}


# lead–lag: a switch picked up in r/technology, with the onset gates of its kind
EVENT = datetime(2026, 9, 1, 12, tzinfo=UTC)


def test_onsets_use_the_gates_of_the_kind(client):
    setup(client)
    comments = Comments()
    for hour in hours(EVENT - timedelta(days=33), EVENT + timedelta(days=1)):
        comments.add("technology", hour, 20)
        comments.add(SAMPLE_SCOPE, hour, 20)
    comments.add(
        "technology", EVENT - timedelta(hours=2), 4, [("switch", FLOW), ("word", "newword")]
    )
    comments.insert(client)

    switch = Event("switch", FLOW, EVENT, EVENT)
    word = Event("word", "newword", EVENT, EVENT)
    OnsetFinder(client, CONFIG).find([switch, word], EVENT + timedelta(days=1))
    # 4 mentions: enough for a switch (3), not for a word (5)
    assert sorted((onset.scope, onset.without, onset.mentions) for onset in switch.onsets) == [
        ("r/technology", "", 4),
        ("tech", "", 4),
        # the rest of the group without r/programming, which never mentions it
        ("tech", "r/programming", 4),
    ]
    assert word.onsets == []


def test_intent_report_and_examples(client):
    setup(client)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    comments = Comments()
    for day in range(14):
        comments.add("technology", now - timedelta(days=day), 100)
    complaint = [("complaint", "complaint: reddit")]
    # 6 complaints this week (4 in the last 48 hours), 2 the week before
    for day in (0, 1, 3):
        comments.add("technology", now - timedelta(days=day), 2, complaint)
    comments.add("programming", now - timedelta(days=9), 2, complaint)
    comments.add("technology", now - timedelta(hours=1), 1, [("complaint", "complaint: teams")])
    comments.insert(client)

    report = intent_report(client, "tech", "complaint", days=7, today=now.date())
    assert [(row.term, row.mentions, row.authors, row.before) for row in report.rows] == [
        ("complaint: reddit", 6, 6, 2),
        ("complaint: teams", 1, 1, 0),
    ]
    assert (report.terms, report.mentions) == (2, 7)
    reddit = report.rows[0]
    # per 10k comments and posts, and the change of the share against the week before
    assert report.per_10k(reddit) == 10_000 * 6 / report.total
    change = report.change(reddit)
    assert change is not None
    assert change > 2
    # the raw items of the last 48 hours behind it
    assert reddit.recent == 4

    examples = intent_examples(client, "tech", ["complaint: reddit"], per_term=3)
    assert len(examples) == 3
    assert {example.term for example in examples} == {"complaint: reddit"}
    assert intent_report(client, "r/programming", "complaint", 7, today=now.date()).rows == []


def test_the_pipeline_counts_intents_and_remembers_them_with_the_item():
    processor = Processor(CONFIG, b"key")
    processed = processor.process(
        make_item(1, text="Honestly, I switched from Notion to Obsidian. Is Reddit down?")
    )
    item = dict(zip(ITEM_COLUMNS, processed.item_row, strict=True))
    assert item["intents"] == ["complaint: reddit", FLOW]
    rows = {(row[3], row[4]) for row in processed.term_rows}
    assert {("switch", FLOW), ("complaint", "complaint: reddit"), ("word", "notion")} <= rows

    # the sample too, unless switched off
    sample_item = make_item(2, subreddit="askreddit", text="Is Reddit down?")
    assert dict(zip(ITEM_COLUMNS, processor.process(sample_item).item_row, strict=True))[
        "intents"
    ] == ["complaint: reddit"]
    without_sample = Processor(replace(CONFIG, intents=IntentsConfig(sample=False)), b"key")
    row = without_sample.process(make_item(3, subreddit="askreddit", text="Is Reddit down?"))
    assert dict(zip(ITEM_COLUMNS, row.item_row, strict=True))["intents"] == []
    assert not {kind for _, _, _, kind, *_ in row.term_rows} & set(INTENT_KINDS)


def test_german_patterns_follow_the_subreddit_language():
    processor = Processor(make_config(), b"key")
    text = "Ich bin von Windows zu Linux gewechselt."
    german = processor.process(make_item(1, subreddit="de", text=text))
    english = processor.process(make_item(2, subreddit="technology", text=text))
    assert ("switch", "windows → linux") in {(row[3], row[4]) for row in german.term_rows}
    assert "windows → linux" not in {row[4] for row in english.term_rows}


def test_backfill_counts_the_intents_of_items_stored_before(client):
    setup(client)
    old = Processor(replace(CONFIG, intents=IntentsConfig(enabled=False)), b"key")
    now = datetime.now(UTC).replace(microsecond=0)
    texts = [
        ("technology", "Any good alternatives to LastPass?"),
        ("technology", "nothing to see here"),
        ("askreddit", "Is Reddit down for anyone else?"),
    ]
    processed = [
        old.process(
            make_item(n, int((now - timedelta(hours=1)).timestamp()), subreddit=sub, text=t)
        )
        for n, (sub, t) in enumerate(texts)
    ]
    client.insert("items", [p.item_row for p in processed], column_names=list(ITEM_COLUMNS))
    client.insert(
        "term_events", [r for p in processed for r in p.term_rows], column_names=list(TERM_COLUMNS)
    )

    def counts() -> dict[tuple[str, str, str], int]:
        rows = client.query(
            "SELECT subreddit, kind, term, sum(docs) FROM term_hourly "
            "GROUP BY subreddit, kind, term"
        ).result_rows
        return {(sub, kind, term): docs for sub, kind, term, docs in rows}

    before = counts()
    dry = backfill_intents(
        client, client, CONFIG, now + timedelta(minutes=1), client.database, dry_run=True
    )
    assert (dry.items, dry.with_intents) == (3, 2)
    assert counts() == before

    result = backfill_intents(client, client, CONFIG, now + timedelta(minutes=1), client.database)
    assert result.kinds == {"alternative": 1, "complaint": 1}
    # in the hour the item was created, UTC, whatever the time zone of the machine
    ((hour,),) = client.query("SELECT hour FROM term_hourly WHERE kind = 'alternative'").result_rows
    assert hour.replace(tzinfo=UTC) == (now - timedelta(hours=1)).replace(minute=0, second=0)
    after = counts()
    assert after["technology", "alternative", "alternative: lastpass"] == 1
    assert after[SAMPLE_SCOPE, "complaint", "complaint: reddit"] == 1
    # the words were counted at ingest, not again
    assert {key: n for key, n in after.items() if key[1] not in INTENT_KINDS} == before
    # items ingested after the new ingester started are its own
    late = backfill_intents(client, client, CONFIG, now - timedelta(days=1), client.database)
    assert late.items == 0


def test_real_subreddit():
    assert real_subreddit("/r/AskReddit/comments/abc/title/def/") == "askreddit"
    assert real_subreddit("") == ""
