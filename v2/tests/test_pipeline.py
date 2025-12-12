from datetime import UTC, datetime

from helpers import make_config, make_item

from wgra.config import SAMPLE_SCOPE
from wgra.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor, RecentKeys


def processor() -> Processor:
    return Processor(make_config(), b"secret-key")


def test_recent_keys_forget_the_oldest():
    keys = RecentKeys(capacity=2)
    assert keys.add("a")
    assert keys.add("b")
    assert not keys.add("a")
    assert keys.add("c")  # evicts "b", "a" was used more recently
    assert "a" in keys
    assert "b" not in keys


def test_author_hash_is_keyed_stable_and_case_insensitive():
    first, other_key = processor(), Processor(make_config(), b"other-key")
    assert first.author_hash("Someone") == first.author_hash("someone")
    assert first.author_hash("someone") != other_key.author_hash("someone")
    assert first.author_hash("[deleted]") == 0


def test_skip_reasons():
    p = processor()
    assert p.skip_reason(make_item(1, text="[removed]")) == "deleted"
    assert p.skip_reason(make_item(2, author="AutoModerator")) == "bot"
    assert p.skip_reason(make_item(3, author="RemindMeBot")) == "bot"
    assert p.skip_reason(make_item(4, distinguished="moderator")) == "moderation"
    assert p.skip_reason(make_item(5, stickied=True)) == "moderation"
    assert p.skip_reason(make_item(6, text="an ordinary comment")) is None


def test_long_identical_texts_are_copypasta_short_ones_are_not():
    p = processor()
    copypasta = "This is a long copypasta that gets posted under every single thread"
    assert p.skip_reason(make_item(1, text=copypasta)) is None
    assert p.skip_reason(make_item(2, text=copypasta.upper())) == "duplicate"
    assert p.skip_reason(make_item(3, text="this")) is None
    assert p.skip_reason(make_item(4, text="this")) is None


def test_process_builds_item_and_term_rows():
    p = processor()
    created = int(datetime(2026, 10, 10, 14, 35, 12, tzinfo=UTC).timestamp())
    item = make_item(
        42, created, subreddit="de", author="Someone", text="Das E-Auto ist günstig, E-Auto!"
    )
    processed = p.process(item)

    item_row = dict(zip(ITEM_COLUMNS, processed.item_row, strict=True))
    assert item_row["id"] == "t1_16"
    assert (item_row["source"], item_row["subreddit"]) == ("comment", "de")
    assert item_row["created_at"] == datetime(2026, 10, 10, 14, 35, 12, tzinfo=UTC)
    assert item_row["author_hash"] == p.author_hash("someone")
    assert item_row["token_count"] == 5

    rows = {
        (row[3], row[4]): dict(zip(TERM_COLUMNS, row, strict=True)) for row in processed.term_rows
    }
    e_auto = rows["word", "e-auto"]
    assert e_auto["hour"] == datetime(2026, 10, 10, 14, tzinfo=UTC)
    assert (e_auto["subreddit"], e_auto["source"]) == ("de", "comment")
    assert e_auto["author_hash"] == item_row["author_hash"]
    assert e_auto["occurrences"] == 2
    # german stopwords: "das" and "ist" can't start or end a phrase
    assert ("phrase", "e-auto ist günstig") in rows
    assert ("phrase", "das e-auto") not in rows


def test_untracked_subreddits_are_pooled_into_the_sample_with_bigrams_only():
    processed = processor().process(
        make_item(7, subreddit="askreddit", text="the right to repair movement")
    )
    item_row = dict(zip(ITEM_COLUMNS, processed.item_row, strict=True))
    assert item_row["subreddit"] == SAMPLE_SCOPE
    assert item_row["permalink"].startswith("/r/askreddit/")

    assert {row[1] for row in processed.term_rows} == {SAMPLE_SCOPE}
    terms = {(row[3], row[4]) for row in processed.term_rows}
    assert ("phrase", "repair movement") in terms
    assert ("phrase", "right to repair") not in terms


def test_tracked_subreddits_keep_their_name_and_trigrams():
    processed = processor().process(
        make_item(8, subreddit="technology", text="the right to repair movement")
    )
    assert {row[1] for row in processed.term_rows} == {"technology"}
    assert ("phrase", "right to repair") in {(row[3], row[4]) for row in processed.term_rows}
