from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from helpers import make_config, make_doc

from undercurrent.ingest.pipeline import ITEM_COLUMNS, TERM_COLUMNS, Processor
from undercurrent.ingest.run import write_channels
from undercurrent.radar.candidates import candidates, products_of, summarize
from undercurrent.sources.reddit.search import (
    due_trees,
    names_any,
    search_query,
    stored_ids,
    wants_tree,
)
from undercurrent.store import migrate
from undercurrent.text.intents import configure_names, extract_intents
from undercurrent.text.terms import clean

PKM = {
    "groups": {"tech": ["r/technology"], "pkm": ["r/Notion", "r/ObsidianMD"]},
    "radar": {
        "enabled": True,
        "watchlists": {
            "pkm": {
                "products": {
                    "Notion": ["Notion AI", "notion.so"],
                    "obsidian": None,
                    "evernote": "Evernote",
                    "apple notes": [],
                }
            }
        },
    },
}


@pytest.fixture(autouse=True)
def no_configured_names() -> Iterator[None]:
    """Processors configure the radar's names for the whole process, reset them after."""
    yield
    configure_names(())


def pkm_config(**radar: object):
    raw = {**PKM, "radar": {**PKM["radar"], **radar}}  # type: ignore[dict-item]
    return make_config(**raw)


def test_watchlist_products_are_lowercase_with_their_canonical_name_first():
    watchlist = pkm_config().radar.watchlists["pkm"]
    assert watchlist.group == "pkm"
    assert watchlist.products == {
        "notion": ("notion", "notion ai", "notion.so"),
        "obsidian": ("obsidian",),
        "evernote": ("evernote",),
        "apple notes": ("apple notes",),
    }
    assert watchlist.product("Notion AI") == "notion"
    assert watchlist.product("craft") is None


def test_single_word_names_count_only_while_the_radar_is_on():
    assert pkm_config().radar.names == {"notion", "notion.so", "obsidian", "evernote"}
    assert pkm_config(enabled=False).radar.names == frozenset()
    assert pkm_config(enabled=False).radar.searches == {}


def test_searches_merge_products_of_several_watchlists():
    radar = make_config(
        groups={"a": ["r/x"], "b": ["r/y"]},
        radar={
            "enabled": True,
            "watchlists": {
                "a": {"products": {"notion": ["Notion AI"]}},
                "b": {"products": {"notion": ["notion.so"], "jira": []}},
                "c": {"group": "a", "search": False, "products": {"linear": []}},
            },
        },
    ).radar
    assert radar.searches == {
        "notion": ("notion", "notion ai", "notion.so"),
        "jira": ("jira",),
    }


@pytest.mark.parametrize(
    ("watchlist", "message"),
    [
        ({"group": "nope", "products": {"a": []}}, "no group 'nope'"),
        ({"group": "tech", "products": {}}, "needs products"),
        ({"group": "tech", "products": {"a → b": []}}, "can't be a product's name"),
        ({"group": "tech", "products": {"a": ["shared"], "b": ["Shared"]}}, "names both a and b"),
    ],
)
def test_watchlists_are_checked(watchlist, message):
    with pytest.raises(ValueError, match=message):
        make_config(radar={"watchlists": {"w": watchlist}})


def test_an_enabled_radar_needs_a_watchlist():
    with pytest.raises(ValueError, match="no watchlists"):
        make_config(radar={"enabled": True})


def test_watched_names_count_in_lowercase():
    sentence = "i switched from evernote to obsidian last year"
    # obsidian is on the list of names, evernote in lowercase isn't a name
    assert not extract_intents(sentence)
    Processor(pkm_config(), b"key")
    assert extract_intents(sentence) == {("switch", "evernote → obsidian"): 1}
    Processor(make_config(), b"key")
    assert not extract_intents(sentence)


def test_search_items_are_counted_in_the_search_channel():
    config = pkm_config()
    item = make_doc(
        config,
        1,
        subreddit="productivity",
        text="I switched from Notion to Obsidian.",
        channel="r/_search",
    )
    processed = Processor(config, b"key").process(item)
    assert processed.item_row[ITEM_COLUMNS.index("channel")] == "r/_search"
    assert processed.item_row[ITEM_COLUMNS.index("intents")] == ["notion → obsidian"]
    assert {row[TERM_COLUMNS.index("channel")] for row in processed.term_rows} == {"r/_search"}


def test_search_query_quotes_every_alias():
    assert search_query(("notion", "notion ai")) == '"notion" OR "notion ai"'


@pytest.mark.parametrize(
    ("title", "wanted"),
    [
        ("Alternatives to Notion?", True),
        ("Obsidian vs Notion for a PhD", True),
        ("Finally leaving Evernote after 10 years", True),
        ("Moving my notes from Notion.so to Obsidian", True),
        ("My Notion dashboard template", False),
        ("Switching to a standing desk", False),
        ("The notional value of a switch", False),
    ],
)
def test_trees_are_wanted_for_titles_about_a_switch_from_a_product(title, wanted):
    products = names_any(("notion", "notion.so", "obsidian", "evernote"))
    assert wants_tree(title, products) is wanted


def test_intents_are_about_the_watched_products_on_either_side():
    watchlist = pkm_config().radar.watchlists["pkm"]
    assert products_of(watchlist, "switch", "notion → obsidian") == ["notion", "obsidian"]
    assert products_of(watchlist, "switch", "notion → capacities") == ["notion"]
    assert products_of(watchlist, "alternative", "alternative: notion ai") == ["notion"]
    assert products_of(watchlist, "complaint", "complaint: craft") == []
    assert products_of(watchlist, "considering", "considering: evernote → notion.so") == [
        "evernote",
        "notion",
    ]
    assert products_of(watchlist, "considering", "considering: obsidian") == ["obsidian"]
    # a need is what someone wants to do, never a product
    assert products_of(watchlist, "need", "need: apple notes") == []


@pytest.mark.parametrize(
    ("text", "products"),
    [
        ("I'm thinking of leaving Notion for Obsidian.", ["notion", "obsidian"]),
        ("Should I ditch evernote?", ["evernote"]),
        ("Any good alternatives to Notion AI?", ["notion"]),
        # not watched: a game character, a language, a product nobody watches
        ("Is there a good alternative to Faruzan for Wanderer?", []),
        ("I switched from Hungarian to Portuguese.", []),
        ("I switched from Notion to Capacities.", ["notion"]),
        ("Is Reddit down?", []),
    ],
)
def test_only_intents_about_watched_products_count(text, products):
    """The radar's filter, on what the extraction finds with the watched names set."""
    watchlist = pkm_config().radar.watchlists["pkm"]
    Processor(pkm_config(), b"key")
    found = [
        product
        for kind, term in extract_intents(clean(text))
        for product in products_of(watchlist, kind, term)
    ]
    assert found == products


def test_candidates_take_the_most_named_alias_and_add_up_intents():
    watchlist = pkm_config().radar.watchlists["pkm"]
    table = summarize(
        watchlist,
        [
            ("watchlist", "word", "notion", 40, 30),
            ("watchlist", "phrase", "notion ai", 12, 10),
            ("watchlist", "switch", "notion → obsidian", 3, 3),
            ("watchlist", "alternative", "alternative: notion", 2, 2),
            ("watchlist", "considering", "considering: notion → obsidian", 2, 1),
            ("watchlist", "considering", "considering: notion", 1, 1),
            ("r/_search", "switch", "evernote → notion", 1, 1),
            ("r/all", "word", "obsidian", 5, 5),
            ("reddit", "need", "need: apple notes", 1, 1),
        ],
    )
    notion = table["notion", "watchlist"]
    assert (notion.named, notion.named_authors) == (40, 30)
    assert notion.intents == {"switch": 3, "alternative": 2, "considering": 3}
    assert table["obsidian", "watchlist"].intents == {"switch": 3, "considering": 2}
    assert table["notion", "r/_search"].intents == {"switch": 1}
    assert table["obsidian", "r/all"].named == 5
    assert table["apple notes", "reddit"].empty


def test_candidates_from_clickhouse(client):
    migrate(client)
    config = pkm_config()
    write_channels(client, config)
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rows = []
    for author, (channel, text) in enumerate(
        [
            ("r/notion", "I switched from Notion to Obsidian, Notion is too slow"),
            ("r/technology", "Is there an alternative to Notion?"),
            ("r/technology", "Should I ditch Evernote for Obsidian?"),
            ("r/all", "Notion and Obsidian"),
            ("r/_search", "We migrated from Evernote to Notion"),
            # a channel the radar doesn't know isn't counted anywhere
            ("r/elsewhere", "Notion and Obsidian"),
        ]
    ):
        item = make_doc(
            config, author + 1, subreddit="any", author=f"a{author}", text=text, channel=channel
        )
        rows += Processor(config, b"key").process(item).term_rows
    client.insert(
        "term_events",
        [(hour, *row[1:]) for row in rows],
        column_names=list(TERM_COLUMNS),
    )

    table = candidates(client, config, config.radar.watchlists["pkm"], days=1)
    assert table["notion", "watchlist"].named == 1
    assert table["notion", "watchlist"].intents == {"switch": 1}
    assert table["notion", "reddit"].intents == {"alternative": 1}
    assert table["evernote", "reddit"].intents == {"considering": 1}
    assert table["obsidian", "reddit"].intents == {"considering": 1}
    assert table["obsidian", "r/all"].named == 1
    assert table["evernote", "r/_search"].intents == {"switch": 1}


def test_due_trees_and_stored_ids(client):
    migrate(client)
    config = pkm_config()
    now = datetime.now(UTC)
    posts = [
        (1, 25, "Alternatives to Notion?"),  # due
        (2, 25, "My Notion dashboard"),  # no switch in the title
        (3, 2, "Leaving Notion for Obsidian"),  # too young
        (4, 40, "Leaving Evernote"),  # too old
    ]
    rows = []
    for id36, hours_ago, title in posts:
        created = int((now - timedelta(hours=hours_ago)).timestamp())
        item = make_doc(
            config,
            id36,
            created,
            doc_type="post",
            subreddit="productivity",
            text=title,
            channel="r/_search",
        )
        rows.append(Processor(config, b"key").process(item).item_row)
    client.insert("items", rows, column_names=list(ITEM_COLUMNS))

    assert due_trees(client, config.radar, set()) == ["t3_1"]
    assert due_trees(client, config.radar, {"t3_1"}) == []
    assert stored_ids(client, ["t3_1", "t1_zz"]) == {"t3_1"}
