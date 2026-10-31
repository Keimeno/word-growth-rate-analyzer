"""Golden tests for intent extraction: realistic sentences, and the tricky negatives that
made the patterns what they are (docs/ARCHITECTURE.md §4.7)."""

import pytest

from wgra.text import extract_terms
from wgra.text.intents import (
    ALTERNATIVE,
    COMPLAINT,
    CONSIDERING,
    NEED,
    SWITCH,
    extract_intents,
    intent_entity,
    intent_term,
    source_sentence,
)
from wgra.text.terms import clean


def intents(text: str, language: str = "en") -> set[tuple[str, str]]:
    return set(extract_intents(clean(text), language))


def switch(x: str, y: str) -> tuple[str, str]:
    return SWITCH, f"{x} → {y}"


def considering(x: str, y: str | None = None) -> tuple[str, str]:
    return CONSIDERING, intent_term(CONSIDERING, f"{x} → {y}" if y else x)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "I switched from Notion to Obsidian last year and never looked back.",
            switch("notion", "obsidian"),
        ),
        (
            "We migrated from Jenkins to GitHub Actions in March.",
            switch("jenkins", "github actions"),
        ),
        ("Finally made the switch from Windows to Linux Mint.", switch("windows", "linux mint")),
        ("switched over from Spotify to Tidal because of the payouts", switch("spotify", "tidal")),
        (
            "I'm switching to Bitwarden from LastPass after the breach.",
            switch("lastpass", "bitwarden"),
        ),
        ("I ditched ChatGPT for Claude a few months ago.", switch("chatgpt", "claude")),
        ("We replaced our Jira with Linear and the team loves it.", switch("jira", "linear")),
        ("The Jira to Linear migration took two weeks.", switch("jira", "linear")),
        # products named with everyday words, written in lowercase
        ("honestly i switched from windows to linux and it's fine", switch("windows", "linux")),
        # a title: every word capitalized, the lists still know the names
        ("Switched From Notion To Obsidian", switch("notion", "obsidian")),
        # numbers after a name are part of it, before a time unit they aren't
        ("I switched from a GoPro 8 to an Osmo Action 4", switch("gopro 8", "osmo action 4")),
        ("switched from Ubuntu to Fedora 2 years ago", switch("ubuntu", "fedora")),
    ],
)
def test_switches(text, expected):
    assert intents(text) == {expected}


@pytest.mark.parametrize(
    "text",
    [
        "I switched from 2 to 3 monitors.",
        "Went from 60 to 144 Hz and it's night and day.",
        "The traffic light switched from yellow to red.",
        "She switched from engineering to medicine.",
        "We moved from Texas to Ohio last year.",
        "We went from Bangkok to Koh Phangan by car.",
        # imperatives in team-building threads
        "Replace Zhongli with Jean and you're good.",
        "He left the house for work.",
        "If you switch from X to Y, nothing changes.",
        "I SWITCHED FROM YELLOW TO RED",
        # not a person switching
        "They switched from Emboar to Stoutland in Black and White.",
        "The presale suddenly switched from AXS to Ticketmaster.",
        # capitalized, but nothing says these are products
        "I switched from Tremor Scorch to Middle in this run.",
        # hypotheticals and advice: nobody switched (questions and "thinking about
        # switching" are considering, see test_considering)
        "If you want speed you need to switch from Chrome to Firefox.",
        "You should switch from Notion to Obsidian.",
        "We would switch from Jira to Linear if we could.",
        # languages, game characters
        "I switched from Hungarian to Portuguese on Duolingo.",
        "I switched from Loucha to Robin for the boss.",
        # a part of the product, not the product
        "I switched from Notion's database to Obsidian.",
        # fantasy sports rosters, settings
        "Just dropped Bryce Young for Roman.",
        "Ronaldo left Real Madrid for Juventus.",
        "Ronaldo ditched Real Madrid for Juventus.",
        "When I switched from PNG to Video the description changed.",
    ],
)
def test_switch_negatives(text):
    assert intents(text) == set()


@pytest.mark.parametrize(
    ("text", "entity"),
    [
        ("Are there any good alternatives to LastPass?", "lastpass"),
        ("Looking for a self-hosted Plex alternative.", "plex"),
        ("Is there a decent replacement for Google Photos?", "google photos"),
        ("I'm looking for a replacement for Evernote", "evernote"),
        ("I use Firefox instead of Chrome these days.", "chrome"),
        ("an open source alternative to Notion would be nice", "notion"),
        # "Windows" qualifies the alternative, MacWhisper is what it replaces
        ("I wanted a Windows alternative to MacWhisper for transcripts.", "macwhisper"),
        # what a product is called besides its name goes, even after a determiner
        ("Any alternatives to the Notion app?", "notion"),
    ],
)
def test_alternatives(text, entity):
    assert intents(text) == {(ALTERNATIVE, intent_term(ALTERNATIVE, entity))}


@pytest.mark.parametrize(
    "text",
    [
        "Instead of going outside, I stayed in.",
        "We need an alternative to college.",
        # the AMD alternative is AMD's, not one to AMD
        "The AMD alternative is cheaper if prices drop.",
        "I mostly listen to alternative rock.",
        "Arsenal bought Jackson instead of Mudryk.",
        "Are there EU alternatives?",
        "Is there a Linux-compatible alternative?",
        "Looking for non-AI alternatives.",
        "We need more non-US alternatives.",
        "I'd rather go to the beach instead of the mountains.",
        "I moved away from Norfolk 20 years ago.",
        "Is there an alternative for Mac?",
        "Any other alternatives for my MB?",
        # x isn't a name, and Krita is what's used instead, not what's replaced
        "a free alternative to photoshop use Krita",
        # a part of the product: possessive, or after a determiner
        "Is there an alternative to Figma's components?",
        "Is there an alternative to the Windows sound panel?",
        # game characters, languages
        "Is there a good alternative to Faruzan for Wanderer?",
        "Any alternatives to Yae?",
        "Looking for a Hungarian alternative.",
    ],
)
def test_alternative_negatives(text):
    assert intents(text) == set()


@pytest.mark.parametrize(
    ("text", "entity"),
    [
        ("Is Reddit down for anyone else?", "reddit"),
        ("YouTube is down again.", "youtube"),
        ("Microsoft Teams has been completely unusable since the update.", "microsoft teams"),
        ("Honestly Google search is getting worse every year.", "google"),
        ("I cancelled my Netflix subscription last week.", "netflix"),
        ("Spotify raised prices again.", "spotify"),
        ("Thanks to the latest Disney+ price hike I'm out.", "disney"),
        ("The enshittification of Reddit continues.", "reddit"),
        ("After the update Windows is broken again", "windows"),
        # one word in front of the name is trimmed
        ("I cancelled my crappy Lattafa subscription.", "lattafa"),
    ],
)
def test_complaints(text, entity):
    assert intents(text) == {(COMPLAINT, intent_term(COMPLAINT, entity))}


@pytest.mark.parametrize(
    "text",
    [
        "Nvidia is down 5% today.",
        "NVDA is down today.",
        "Why is NVDA down today?",
        "The market is down today.",
        # gamers call strong characters broken
        "Lancelot is broken in this patch.",
        "My keyboard is broken.",
        "The economy is getting worse.",
        "I'm down for that.",
        "These noise cancelling headphones are great.",
        "They cancelled the show after one season.",
        "Gas prices went up and the price hike hurts.",
        "When the chips are down, you find out who your friends are.",
        "FIRST DOWN?",
        # a part of the product
        "The Windows sound panel is broken again.",
        "My Steam library is broken again.",
        "Is Figma's autosave down?",
    ],
)
def test_complaint_negatives(text):
    assert intents(text) == set()


@pytest.mark.parametrize(
    ("text", "need"),
    [
        ("Is there an app to track my sleep?", "track my sleep"),
        ("Is there a tool that converts PDFs to Word?", "converts pdfs"),
        ("I wish there was a way to mute subreddits on the app.", "mute subreddits"),
        ("I'd pay for an app that syncs notes between devices.", "syncs notes"),
        ("Does anyone know a tool for batch renaming files?", "batch renaming files"),
        (
            "Is there a browser extension that lets you block YouTube Shorts?",
            "block youtube shorts",
        ),
        ("Can anyone recommend an app for meal planning?", "meal planning"),
        ("Any app that tracks screen time on Linux?", "tracks screen time"),
    ],
)
def test_needs(text, need):
    assert intents(text) == {(NEED, intent_term(NEED, need))}


@pytest.mark.parametrize(
    "text",
    [
        "Is there a way to fix this?",
        "Is there any way that you could send me the file?",
        "is there a way to do it",
        "I don't need a plugin to learn my behaviour.",
        "Any way to get a taste?",
        "Is there an app for that?",
        "Is there a way to play the game in English?",
        "Is there a way to work 7 days straight?",
        "Any program that controls the keyboard can get flagged.",
    ],
)
def test_need_negatives(text):
    assert intents(text) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "I'm thinking of switching from Notion to Obsidian.",
            considering("notion", "obsidian"),
        ),
        ("Should I switch from Notion to Obsidian?", considering("notion", "obsidian")),
        (
            "Considering moving from Notion to Obsidian, any tips?",
            considering("notion", "obsidian"),
        ),
        ("I'm thinking about switching from Windows to Linux.", considering("windows", "linux")),
        ("I'm thinking of leaving Notion for Obsidian.", considering("notion", "obsidian")),
        (
            "I'm thinking of moving my notes from Notion to Obsidian.",
            considering("notion", "obsidian"),
        ),
        ("We're considering migrating to Linear from Jira.", considering("jira", "linear")),
        (
            "I'm seriously thinking about replacing Notion with Obsidian.",
            considering("notion", "obsidian"),
        ),
        (
            "should we migrate from Jenkins to GitHub Actions?",
            considering("jenkins", "github actions"),
        ),
        ("Thinking about leaving Notion.", considering("notion")),
        ("About to cancel Notion.", considering("notion")),
        ("Should I ditch Notion?", considering("notion")),
        ("Thinking of leaving Notion for good.", considering("notion")),
        ("I'm about to cancel my Notion subscription.", considering("notion")),
        ("I've been thinking about getting rid of Spotify.", considering("spotify")),
        # the destination isn't named
        (
            "I'm thinking about switching from Notion to something else.",
            considering("notion"),
        ),
    ],
)
def test_considering(text, expected):
    assert intents(text) == {expected}


@pytest.mark.parametrize(
    "text",
    [
        # not the first person: advice, someone else, a question to someone
        "If you switch from Chrome to Firefox, nothing changes.",
        "You could switch to Obsidian.",
        "You should switch from Notion to Obsidian.",
        "Are you thinking of switching from Notion to Obsidian?",
        "My boss is thinking of switching from Notion to Obsidian.",
        "Why should I switch from Notion to Obsidian?",
        # if, would, could, negated
        "If we're considering moving from Notion to Obsidian, we need an export.",
        "I would be thinking of leaving Notion if it got slower.",
        "We could be about to cancel Notion.",
        "I'm not thinking of leaving Notion.",
        # leaving something else, or a part of the product
        "Leaving Notion open all day drains my battery.",
        "I'm thinking of leaving Notion open on my second monitor.",
        "Should I leave a comment in Notion?",
        "I'm thinking of leaving the Notion team.",
        "Should I delete Notion pages?",
        # places, nothing known
        "I'm thinking of moving from Texas to Ohio.",
        "I'm thinking of switching from Loucha to Robin.",
    ],
)
def test_considering_negatives(text):
    assert intents(text) == set()


def test_a_switch_and_a_switch_considered_in_one_sentence():
    text = "I switched from Notion to Obsidian and I'm thinking about leaving Spotify."
    assert intents(text) == {switch("notion", "obsidian"), considering("spotify")}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ich bin letztes Jahr von Windows zu Linux gewechselt.", switch("windows", "linux")),
        ("Wechsel von der Sparkasse zur DKB, endlich.", switch("sparkasse", "dkb")),
        ("Ich wechsle gerade von iCloud zu Proton.", switch("icloud", "proton")),
        ("Ich will umsteigen von Windows zu Linux.", switch("windows", "linux")),
        ("Wir sind von GitHub auf GitLab migriert.", switch("github", "gitlab")),
        ("Teams ist mal wieder komplett unbrauchbar.", (COMPLAINT, "complaint: teams")),
        ("Gibt es eine gute Alternative zu Notion?", (ALTERNATIVE, "alternative: notion")),
        ("Ist Reddit gerade down?", (COMPLAINT, "complaint: reddit")),
        ("Netflix hat schon wieder die Preise erhöht.", (COMPLAINT, "complaint: netflix")),
        ("Habe mein Spotify-Abo gekündigt.", (COMPLAINT, "complaint: spotify")),
        (
            "Gibt es eine App, mit der man Belege scannen kann?",
            (NEED, "need: belege scannen"),
        ),
        ("Gibt es eine App für Haushaltsbuch?", (NEED, "need: haushaltsbuch")),
        # english is mixed into every subreddit
        ("Any alternatives to Evernote?", (ALTERNATIVE, "alternative: evernote")),
    ],
)
def test_german(text, expected):
    assert intents(text, "de") == {expected}


@pytest.mark.parametrize(
    "text",
    [
        "Ich bin von Teilzeit auf Vollzeit gewechselt.",
        "Alternativen zum Rauchen gibt es viele.",
        "Eine Alternative zur Armut gibt es nicht.",
        "Wir arbeiten von 9 bis 17 Uhr.",
        "Gibt es eine Seite, die anhand der Modellnummer Ersatzteile findet?",
        "Der DAX ist heute 2% down.",
    ],
)
def test_german_negatives(text):
    assert intents(text, "de") == set()


def test_every_pattern_has_a_trigger_word():
    """The prefilter skips sentences without any word a pattern needs: every golden
    example must get through it."""
    from wgra.text.intents import _TRIGGERS

    examples = [
        "made the switch from Windows to Linux",
        "the Jira to Linear migration",
        "Teams ist unbrauchbar",
        "ich wechsle zu Proton",
        "ich will umsteigen von Windows",
        "wir sind auf GitLab migriert",
        "Preiserhöhung bei Netflix",
        "gibt es eine App",
        "does anyone know a tool",
        "I'd pay for an app",
        "thinking about leaving Notion",
        "Should I ditch Notion",
        "about to cancel Notion",
        "debating whether to quit Reddit",
        "planning on getting rid of Spotify",
    ]
    assert all(_TRIGGERS.search(example) for example in examples)


def test_german_patterns_only_run_in_german_subreddits():
    assert intents("Ich bin von Windows zu Linux gewechselt.", "en") == set()


def test_intents_are_counted_once_per_text():
    text = "Is Reddit down? Reddit is down again. Is Reddit down for anyone?"
    assert extract_intents(clean(text)) == {(COMPLAINT, "complaint: reddit"): 3}


def test_quotes_and_code_are_ignored():
    assert intents("> I switched from Notion to Obsidian\n\nme too") == set()
    assert intents("`switched from Notion to Obsidian` is the title") == set()


def test_intent_terms_never_collide_with_words_or_phrases():
    terms = extract_terms("Any alternatives to LastPass? I cancelled my Netflix.").counts
    assert ("alternative", "alternative: lastpass") in terms
    assert ("complaint", "complaint: netflix") in terms
    assert ("word", "lastpass") in terms
    phrases = {term for kind, term in terms if kind == "phrase"}
    words = {term for kind, term in terms if kind == "word"}
    intent_terms = {term for kind, term in terms if kind in (ALTERNATIVE, COMPLAINT)}
    assert not intent_terms & (phrases | words)


def test_extract_terms_can_leave_intents_out():
    terms = extract_terms("I switched from Notion to Obsidian.", intents=False).counts
    assert not {kind for kind, _ in terms} - {"word", "phrase"}


def test_intent_entity():
    assert intent_entity("complaint: netflix") == "netflix"
    assert intent_entity("need: track my sleep") == "track my sleep"
    assert intent_entity("notion → obsidian") == "notion → obsidian"
    assert intent_entity("considering: notion → obsidian") == "notion → obsidian"
    assert intent_entity("considering: notion") == "notion"
    assert intent_entity("word: with a colon") == "word: with a colon"


def test_source_sentence_is_the_sentence_as_written():
    text = "Great product. But I switched from Notion to Obsidian last year!  Love it."
    assert source_sentence(text, "notion → obsidian") == (
        "But I switched from Notion to Obsidian last year!"
    )
    assert source_sentence(text, "complaint: reddit") is None
    assert source_sentence("Hi all. Should I ditch Notion? Thanks", "considering: notion") == (
        "Should I ditch Notion?"
    )
