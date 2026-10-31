"""Intents: why people mention things, not only that they do.

Five more kinds of terms, extracted from the same cleaned text as words and phrases:

* ``switch``: "x → y", someone switched from x to y ("I switched from Notion to Obsidian",
  "dropped Claude for Grok", "we replaced our Jenkins with GitHub Actions", "the Jira to
  Linear migration")
* ``alternative``: x, someone looks for or uses something in place of x ("alternatives
  to LastPass", "a good Plex alternative?", "I use Firefox instead of Chrome")
* ``complaint``: x, someone complains about x ("is Reddit down?", "Teams is unusable",
  "cancelled my Netflix subscription", "Spotify raised prices", "YouTube enshittification")
* ``need``: what someone wants a tool or a way for ("is there an app to track sleep",
  "I wish there was a way to mute subreddits", "I'd pay for an app that syncs notes")
* ``considering``: "x → y" or x, someone thinks of switching from x to y or of leaving x,
  in the first person ("I'm thinking of switching from Notion to Obsidian", "should I
  ditch Notion?", "about to cancel Netflix")

They are counted like words, under terms of their own: "notion → obsidian",
"alternative: lastpass", "complaint: netflix", "need: track sleep", "considering: notion
→ obsidian", "considering: notion". The trends tables are keyed by term, so an intent
can't share its term with the word "netflix".

Raw text is deleted after 48 hours, so this happens at ingest time or not at all.

Precision over recall (measured on live data, docs/ARCHITECTURE.md §4.7):

* A pattern only counts where the words around it make the intent explicit: "is down"
  only before nothing, "again" or "for me" (not "is down 5%" or "down today"), "broken"
  only as "broken again" or "broken for me" (gamers call strong characters broken),
  "instead of" only after a verb of using or choosing ("use Y instead of X", not "instead
  of going outside"), a switch only when a person switched ("I switched", not "the traffic
  light switched", "should I switch?"), considering only in the first person and not after
  if, would or could ("should I switch?", not "if you switch" or "you could switch").
* In english text, the thing has to be written like a name: capitalized in the middle of a
  sentence ("moved to Proton"), mixed case ("iPhone"), an acronym ("AWS") or letters with
  digits ("gpt-5"). Lowercase words ("switched from yellow to red"), numbers with units
  ("from 60 to 144 hz"), Title Case and ALL CAPS sentences (where every word is
  capitalized) don't count, and neither do generic words in any case
  (intent_words/generic_*.txt: "the UK", "EU", "AI"). Words the corpus usually capitalizes
  ("reddit") and products named with everyday words ("notion") are names in any case.
* German capitalizes every noun, so there a capital letter says nothing: a name has to be
  on the lists of names (the english ones, brands are international, and a few german
  brands), or have digits, mixed case or be an acronym.

Entities are 1–3 words, ended by stopwords, punctuation and words that can't be part of a
name (intent_words/boundary_*.txt: time expressions, adjectives like "free" or "cheaper",
adverbs), and normalized like words and phrases: lowercase, possessive 's removed. They're
trimmed to the name, but not past more than one word ("a free alternative to photoshop use
Krita" isn't about Krita) or a part of the product ("Figma's components", "the Windows
sound panel" aren't Figma or Windows). A need
is a phrase like any other (inner stopwords allowed, not at the edges) of 2–3 words: "is
there a way to fix this" says nothing about the need.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cache

from wgra.text.lexicon import stopwords, word_list

SWITCH = "switch"
ALTERNATIVE = "alternative"
COMPLAINT = "complaint"
NEED = "need"
CONSIDERING = "considering"
INTENT_KINDS = (SWITCH, ALTERNATIVE, COMPLAINT, NEED, CONSIDERING)

# between the two sides of a switch: "notion → obsidian", "considering: notion → obsidian"
ARROW = " → "
# between the kind and the entity of the other intents: "complaint: netflix". The tables
# of trends are keyed by term, not kind, so an intent's term must differ from the word
# "netflix"; no word or phrase contains a colon (it ends a phrase), and neither does an
# entity, so the term of a switch has none.
KIND_SEPARATOR = ": "
MAX_ENTITY_TOKENS = 3
MIN_NEED_TOKENS = 2

# within a sentence, a comma, dash, parenthesis or slash: entities don't cross it, patterns
# may ("gibt es eine App, die ...")
SOFT_BREAK = ","
# the end of a sentence that asked something: "is Reddit down?"
QUESTION = "?"

_TOKEN = re.compile(r"[^\W_]+(?:[-'.][^\W_]+)*")
# what ends a sentence: after these a capital letter says nothing
_HARD_BREAK = re.compile(r"[.!?;:…]+(?=\s|$)|[!?;\n\r…•|]+|\s[-*+]\s|^\s*[-*+]\s", re.M)
_SOFT_BREAK = re.compile(r"[,()\[\]{}\"“”„«»\\/~^=<>*]+|\s+[-–—]+(?=\s)|[–—]")
_NUMBER_WITH_UNIT = re.compile(
    r"^[$€£]?\d[\d.,]*(?:k|m|b|x|s|p|st|nd|rd|th|gb|tb|mb|kb|hz|khz|mhz|ghz|fps|w|kw|kwh|v|"
    r"mah|mm|cm|km|m|kg|g|lb|lbs|oz|in|ft|ms|h|hr|hrs|min|mins|yo|yr|yrs|gen|bit|core|cores|"
    r"usd|eur|pts|gbs|tbs)?$"
)
_I_WORDS = frozenset({"i", "i'm", "i've", "i'd", "i'll"})


def intent_term(kind: str, entity: str) -> str:
    """The term an intent is counted as: "notion → obsidian", "alternative: notion",
    "considering: notion → obsidian"."""
    return entity if kind == SWITCH else f"{kind}{KIND_SEPARATOR}{entity}"


def intent_entity(term: str) -> str:
    """What an intent is about: "complaint: netflix" -> "netflix", "considering: notion →
    obsidian" -> "notion → obsidian", switches unchanged."""
    kind, separator, entity = term.partition(KIND_SEPARATOR)
    return entity if separator and kind in INTENT_KINDS else term


@cache
def generic_words(language: str) -> frozenset[str]:
    """Words that never name a thing someone switches to, looks for an alternative to or
    complains about ("phone", "economy", "EU"). English is mixed into every subreddit."""
    return word_list("intent_words/generic_en") | word_list(f"intent_words/generic_{language}")


# The single-word names of the churn radar's watched products (config.yaml), set by
# `configure_names` when the ingester starts. They count like the lists below.
_configured_names: frozenset[str] = frozenset()


def configure_names(words: Iterable[str]) -> None:
    """Makes these words names in any case and position, like products_*.txt."""
    global _configured_names
    _configured_names = frozenset(word.lower() for word in words)
    name_words.cache_clear()


@cache
def name_words(language: str) -> frozenset[str]:
    """Words that are names even when written in lowercase or at the start of a sentence:
    the ones the corpus usually capitalizes in the middle of a sentence ("reddit",
    "spotify", generated from live data by bench/intent_names.py), products named with
    everyday words ("notion", "windows", lists kept by hand), and the watched products of
    `configure_names`. The english lists count everywhere: brands are international, and
    in german a capital letter says nothing."""
    lists = ("names_en", "products_en", f"names_{language}", f"products_{language}")
    listed = frozenset().union(*(word_list(f"intent_words/{name}") for name in lists))
    return listed | _configured_names


@cache
def boundary_words(language: str) -> frozenset[str]:
    """Words that end an entity besides stopwords: time expressions and adjectives in front
    of a name ("switched to Linux last year", "a free Notion alternative")."""
    return (
        stopwords(language)
        | word_list("intent_words/boundary_en")
        | word_list(f"intent_words/boundary_{language}")
    )


@dataclass(frozen=True, slots=True)
class Token:
    lower: str
    # written like a name: capitalized in the middle of a sentence, mixed case, an acronym,
    # or letters with digits, or on the lists of names
    name: bool = False
    # more than capitalized: mixed case, an acronym, letters with digits, or on the lists.
    # "Emboar" or "Middle" are capitalized, "Spotify", "iX3" and "AWS" are known.
    known: bool = False
    # written with a possessive 's, which `lower` leaves out: "Figma's components"
    possessive: bool = False

    @property
    def is_break(self) -> bool:
        return self.lower in (SOFT_BREAK, QUESTION)


NOT_A_NAME, CAPITALIZED, WRITTEN_LIKE_A_NAME = 0, 1, 2


# What capital letters say in a sentence: everything (english prose), nothing about the
# first letter (german capitalizes every noun, Title Case capitalizes every word), nothing at
# all (ALL CAPS: every word looks like an acronym)
CAPITALS, NO_INITIALS, SHOUTING = 0, 1, 2


def _written_like_a_name(word: str, initial: bool, case: int) -> int:
    """How much the way a word is written says it's a name."""
    letters = [char for char in word if char.isalpha()]
    if not letters:
        return NOT_A_NAME
    if any(char.isdigit() for char in word) and not _NUMBER_WITH_UNIT.match(word.lower()):
        return WRITTEN_LIKE_A_NAME
    if case == SHOUTING:
        return NOT_A_NAME
    upper = [char.isupper() for char in letters]
    if all(upper):
        # an acronym
        return WRITTEN_LIKE_A_NAME if 2 <= len(word) <= 6 else NOT_A_NAME
    if any(upper[1:]):
        return WRITTEN_LIKE_A_NAME  # iPhone, YouTube, macOS, GitLab
    if case == CAPITALS and upper[0] and not initial:
        return CAPITALIZED
    return NOT_A_NAME


def _case(words: Sequence[str], english: frozenset[str], german: frozenset[str]) -> int:
    """What capital letters say in a sentence (CAPITALS, NO_INITIALS or SHOUTING)."""
    letters = [word for word in words if any(char.isalpha() for char in word)]
    shouted = sum(word.isupper() and len(word) > 1 for word in letters)
    if len(letters) >= 2 and shouted >= 0.6 * len(letters):
        return SHOUTING
    if any(word.lower() in german for word in words):
        return NO_INITIALS
    function_words = [
        word for word in letters[1:] if word.lower() in english and word.lower() not in _I_WORDS
    ]
    capitalized = sum(word[0].isupper() for word in function_words)
    if function_words and capitalized >= max(1, len(function_words) / 2):
        return NO_INITIALS  # Title Case
    return CAPITALS


def sentences_as_written(
    text: str, language: str, only: re.Pattern[str] | None = None
) -> Iterator[tuple[str, list[Token]]]:
    """The cleaned text as sentences: (the sentence as written, its tokens), of the
    sentences `only` finds something in. Soft breaks are tokens of their own, and a sentence
    that ends with a question mark ends with one."""
    stop = stopwords(language)
    names = name_words(language)
    english = stopwords("en")
    # german-only function words: german capitalizes every noun, a capital letter says
    # nothing in a german sentence. English sentences are mixed into every subreddit.
    other = stop - english
    position = 0
    for end in [*_HARD_BREAK.finditer(text), None]:
        sentence = text[position : end.start() if end else len(text)]
        question = bool(end and "?" in end.group())
        if end:
            position = end.end()
        if only and not only.search(sentence):
            continue
        stretches = [
            [
                (word.removesuffix("'s").removesuffix("'S"), word.endswith(("'s", "'S")))
                for word in _TOKEN.findall(stretch)
            ]
            for stretch in _SOFT_BREAK.split(sentence)
        ]
        case = _case([word for stretch in stretches for word, _ in stretch], english, other)
        tokens: list[Token] = []
        initial = True
        for stretch in stretches:
            if tokens and not tokens[-1].is_break:
                tokens.append(Token(SOFT_BREAK))
            for word, possessive in stretch:
                if word:
                    lower = word.lower()
                    written = _written_like_a_name(word, initial, case)
                    listed = lower in names or _strip_suffix(lower) in names
                    tokens.append(
                        Token(
                            lower,
                            name=listed or written > NOT_A_NAME,
                            known=listed or written == WRITTEN_LIKE_A_NAME,
                            possessive=possessive,
                        )
                    )
                    initial = False
        while tokens and tokens[-1].is_break:
            tokens.pop()
        if tokens:
            if question:
                tokens.append(Token(QUESTION))
            yield sentence.strip() + (end.group().strip() if end else ""), tokens


class Span(Enum):
    """How a pattern's group becomes an entity."""

    # the group's tokens are the entity: "from (X) to"
    EXACT = 1
    # the entity starts at the group and runs to the next boundary: "alternatives to (X …"
    FORWARD = 2
    # the entity ends before the group and runs back to the previous boundary:
    # "… X) alternative"
    BACKWARD = 3
    # a need: a phrase from the group on, after helper words ("an app that lets me …")
    NEED = 4


@dataclass(frozen=True)
class Pattern:
    kind: str
    regex: re.Pattern[str]
    # group -> how it becomes an entity; switches have "x" (from) and "y" (to)
    groups: dict[str, Span]
    # a BACKWARD entity can't follow these: "the AMD alternative" is AMD's, not one to AMD
    not_after: frozenset[str] = frozenset()
    # nor end like this: a "Linux-compatible alternative" runs on Linux, it doesn't replace it
    not_ending: tuple[str, ...] = ()
    # switches and considering: one side must be known, not only capitalized ("Emboar →
    # Stoutland"), and the sentence must say where it stands: a switch happened (not a
    # question or a hypothetical, "if you switch"), someone considers one (not after "if",
    # "would" or "could")
    one_known: bool = False
    # what it matches, for measuring precision per pattern
    label: str = ""


# The patterns match the lowercase tokens of a sentence joined by single spaces, with
# "," for soft breaks and a final "?" for questions. These mark the edges of tokens.
B = r"(?<!\S)"
E = r"(?!\S)"
TOKEN = r"[^\s,?]+"
# 1-3 tokens, as few as possible: the anchor after "from (X) to" decides
SPAN = rf"{TOKEN}(?: {TOKEN}){{0,2}}?"
# what "alternatives for" can't be followed by
PLATFORMS = (
    r"(?:mac|macos|windows|linux|android|ios|iphone|ipad|pc|console|consoles|xbox|playstation|"
    r"ps4|ps5|switch)"
)
POSSESSIVES = r"(?:my|your|his|her|our|their)"
# a determiner in front of an entity, left out of it
DET = r"(?:(?:the|a|an|my|our|their|his|her|your|its|some) )?"
# up to two adjectives: "is there a (good free) app"
ADJECTIVES = rf"(?:{TOKEN} ){{0,2}}?"
# a token that isn't the end of a phrase: the noun "alternative", not "alternative rock"
NOUN_END = (
    r"(?= [?,]| (?:is|are|was|were|that|which|you|i|for|with|but|and|or|if|out|on|in|at)(?!\S)|$)"
)


# what makes a word a qualifier of an alternative, not the thing it replaces
_QUALIFIERS = tuple(
    f"-{suffix}"
    for suffix in (
        "compatible",
        "based",
        "friendly",
        "native",
        "only",
        "free",
        "focused",
        "centric",
        "first",
        "style",
        "like",
        "hosted",
        "made",
        "owned",
        "ai",
    )
)


def _anchor(name: str) -> str:
    """Where a FORWARD or NEED entity starts."""
    return f"(?P<{name}>)"


def _before(name: str) -> str:
    """Where a BACKWARD entity ends: the start of the next token."""
    return f"{B}(?P<{name}>)"


def _english() -> list[Pattern]:
    i = r"(?:(?:i|we|i've|we've|i have|we have|i'm|we're|i am|we are|i just|we just|finally|just) )"
    # someone switching: "i (finally) switched", "people have migrated", "after switching",
    # "made the switch", and "Switched from …" opening a sentence (the "I" left out). Not
    # "the traffic light switched", "they switched (the starter)", "made the jump from E2
    # to E6" (levels of a game).
    person = (
        r"(?:i|we|i've|we've|i'm|we're|i'd|we'd|i'll|we'll|people|users|everyone|everybody|"
        r"many|folks|devs|developers|designers|companies|you)"
    )
    switch = (
        rf"(?:switching|migrating|^(?:(?:finally|just|recently) )?(?:switched|migrated)|"
        rf"{person} (?:{TOKEN} ){{0,2}}?(?:switched|switch|migrated|migrate)|"
        rf"(?:made|make|making) the switch)"
    )
    adverbs = r"(?: (?:over|back|completely|fully|entirely|permanently|finally|all|everything))*"
    # not "dropped" (fantasy sports rosters) or "left" (people, jobs)
    leave = r"(?:ditched|abandoned|quit)"
    # "bought" and "picked" are as often football transfers as purchases
    choose = (
        r"(?:use|using|used|went with|go with|going with|switched to|switch to|chose|choose|"
        r"run|running|installed|install|recommend|tried|try|prefer)"
    )
    # "is there a way to" / "an app for", but "an option for" is anything
    tool = (
        r"(?:(?:apps?|tools?|services?|programs?|software|websites?|sites?|extensions?|plugins?|"
        r"add-?ons?|scripts?|bots?|platforms?|ways?) (?:to|for|that|which|where)|"
        r"(?:options?|features?|settings?|buttons?|versions?|modes?|filters?|toggles?) "
        r"(?:to|that|which))"
    )
    # what "any app that …?" can ask for: "any way to" is any how-to question
    product = (
        r"(?:(?:apps?|tools?|services?|programs?|software|websites?|sites?|extensions?|plugins?|"
        r"add-?ons?|scripts?|bots?|platforms?) (?:to|for|that|which|where))"
    )
    adverb = (
        r"(?:still|completely|totally|literally|so|just|now|basically|absolutely|fucking|kinda|"
        r"pretty much|almost|practically|currently|again)"
    )
    # "Reddit is down again", "… down for me", not "NVDA is down today" (a price)
    outage = (
        r"(?= ?$| ,| \?| (?:again|for (?:me|anyone|everyone|anybody|you|us|hours|days)|"
        r"everywhere|globally|worldwide)(?!\S))"
    )
    # someone considering it, in the first person: "i'm (seriously) thinking of", "we're
    # considering", "about to", "should i", and opening a sentence with the "I" left out
    # ("Thinking about leaving Notion"). Not negated ("i'm not thinking of"), not "you", not
    # "why should i".
    me = r"(?:i|im|i'm|i am|we|we're|we are|i've been|we've been|i have been|we have been)"
    really = (
        r"(?:(?:really|seriously|actually|honestly|genuinely|kinda|kind of|sort of|now|also|"
        r"currently|still|already|just|slowly|finally) )*"
    )
    thinking = (
        r"(?:thinking (?:of|about)|considering|debating(?: whether to)?|about to|"
        r"planning (?:to|on))"
    )
    considering = rf"(?:(?:{B}{me} |^){really}{thinking} |{B}(?<!why )should (?:i|we) {really})"
    moving = r"(?:switch|switching|migrate|migrating|move|moving|jump ship|jumping ship)"
    # leaving x, the thing being left named after it: "thinking of (leaving) Notion"
    leaving = (
        rf"(?:leave|leaving|quit|quitting|ditch|ditching|abandon|abandoning|cancel|canceling|"
        rf"cancelling|uninstall|uninstalling|delete|deleting|unsubscribe from|"
        rf"unsubscribing from|(?:get|getting) rid of|{moving}(?: away)? (?:from|off)(?: of)?) "
    )
    # what can follow the thing someone thinks of leaving: "leaving Notion (for good)",
    # "(because) …", the end of the sentence; not "leaving Notion open"
    left = (
        r"(?= ?$| [,?]| (?:for|to|and|or|but|because|cause|cuz|bc|since|after|before|when|"
        r"once|in|at|this|next|soon|now|already|too|yet|altogether|entirely|forever|behind|"
        r"so|then|as|due|over|if|until|though|lol|tbh|today|tomorrow|[^\s,?]+ly)(?!\S))"
    )
    return [
        Pattern(
            SWITCH,
            re.compile(
                rf"{B}{switch}{adverbs} from {DET}(?P<x>{SPAN}) (?:over )?to {_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="switched from x to y",
        ),
        Pattern(
            SWITCH,
            re.compile(rf"{B}{switch}{adverbs} to {DET}(?P<y>{SPAN}) from {_anchor('x')}"),
            {"x": Span.FORWARD, "y": Span.EXACT},
            one_known=True,
            label="switched to y from x",
        ),
        Pattern(
            SWITCH,
            re.compile(
                rf"(?:{B}{person} (?:{TOKEN} ){{0,2}}?|^(?:just )?){leave} {DET}(?P<x>{SPAN}) "
                rf"for {_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="ditched x for y",
        ),
        Pattern(
            SWITCH,
            re.compile(
                rf"{B}{i}(?:(?:already|recently|finally|eventually|have|just) )?replaced {DET}"
                rf"(?P<x>{SPAN}) (?:with|by) {_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="replaced x with y",
        ),
        Pattern(
            SWITCH,
            re.compile(rf"{_before('x')}to (?P<y>{SPAN}) migrations?{E}"),
            {"x": Span.BACKWARD, "y": Span.EXACT},
            one_known=True,
            label="x to y migration",
        ),
        Pattern(
            SWITCH,
            re.compile(rf"{B}migrations? from {DET}(?P<x>{SPAN}) to {_anchor('y')}"),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="migration from x to y",
        ),
        Pattern(
            CONSIDERING,
            # "thinking of moving (my notes) from Notion to Obsidian"
            re.compile(
                rf"{considering}{moving}(?: {TOKEN}){{0,2}}? from {DET}(?P<x>{SPAN}) "
                rf"(?:over )?to {_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="considering: thinking of switching from x to y",
        ),
        Pattern(
            CONSIDERING,
            re.compile(
                rf"{considering}{moving}(?: {TOKEN}){{0,2}}? to {DET}(?P<y>{SPAN}) "
                rf"from {_anchor('x')}"
            ),
            {"x": Span.FORWARD, "y": Span.EXACT},
            one_known=True,
            label="considering: thinking of switching to y from x",
        ),
        Pattern(
            CONSIDERING,
            re.compile(
                rf"{considering}(?:leave|leaving|quit|quitting|ditch|ditching|abandon|"
                rf"abandoning) {DET}(?P<x>{SPAN}) for {_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="considering: thinking of leaving x for y",
        ),
        Pattern(
            CONSIDERING,
            re.compile(
                rf"{considering}(?:replace|replacing) {DET}(?P<x>{SPAN}) (?:with|by) "
                rf"{_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            one_known=True,
            label="considering: thinking of replacing x with y",
        ),
        Pattern(
            CONSIDERING,
            re.compile(rf"{considering}{leaving}{DET}(?P<x>{SPAN}){left}"),
            {"x": Span.EXACT},
            one_known=True,
            label="considering: thinking of leaving x",
        ),
        Pattern(
            ALTERNATIVE,
            re.compile(rf"{B}alternatives? to {_anchor('x')}"),
            {"x": Span.FORWARD},
            label="alternative to x",
        ),
        Pattern(
            ALTERNATIVE,
            # "an alternative for Mac" is a version for the Mac, "alternatives for my MB" are
            # for my motherboard
            re.compile(rf"{B}alternatives for (?!{PLATFORMS}{E}|{POSSESSIVES} ){_anchor('x')}"),
            {"x": Span.FORWARD},
            label="alternatives for x",
        ),
        Pattern(
            ALTERNATIVE,
            re.compile(rf"{_before('x')}alternatives?{NOUN_END}"),
            {"x": Span.BACKWARD},
            not_after=frozenset({"the", "their", "his", "her", "its"}),
            not_ending=_QUALIFIERS,
            label="x alternative",
        ),
        Pattern(
            ALTERNATIVE,
            re.compile(
                rf"{B}(?:looking for|need|want|recommend|suggest|any|is there) (?:a |an |some )?"
                rf"{ADJECTIVES}replacements? (?:for|to) {_anchor('x')}"
            ),
            {"x": Span.FORWARD},
            label="replacement for x",
        ),
        Pattern(
            ALTERNATIVE,
            re.compile(rf"{B}{choose} {DET}{SPAN} instead of {_anchor('x')}"),
            {"x": Span.FORWARD},
            label="use y instead of x",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{_before('x')}(?:is|are|was|has been|keeps going) (?:{adverb} )?down{outage}"
            ),
            {"x": Span.BACKWARD},
            label="x is down",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"(?:(?<!why )(?<!how )(?<!much ){B}(?:is|are) |^){DET}(?P<x>{SPAN}) down"
                rf"(?: for (?:anyone|everyone|anybody|you)(?: else)?)?"
                rf"(?: (?:again|rn|atm|right now|now|today))? \?$"
            ),
            {"x": Span.EXACT},
            label="is x down?",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{_before('x')}(?:is|are|was|has been|have been|keeps getting|is getting|has "
                rf"gotten|got) (?:{adverb} )?(?:unusable|getting worse|worse and worse|"
                rf"broken (?:again|for (?:me|anyone|everyone|many|some|us)|since))"
            ),
            {"x": Span.BACKWARD},
            label="x is unusable/getting worse/broken again",
        ),
        Pattern(
            COMPLAINT,
            re.compile(rf"{B}cancel(?:l)?(?:ed|ing) (?:my|our) {_anchor('x')}"),
            {"x": Span.FORWARD},
            label="cancelled my x",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{_before('x')}(?:just |again |has |have |is |are )?(?:raised|raises|raising|"
                rf"hiked|hikes|hiking|increased|increases|increasing|jacked up|jacking up) "
                rf"(?:its |their |the )?(?:subscription |monthly |membership )?prices?{E}"
            ),
            {"x": Span.BACKWARD},
            label="x raised prices",
        ),
        Pattern(
            COMPLAINT,
            re.compile(rf"{_before('x')}price (?:hikes?|increases?){E}"),
            {"x": Span.BACKWARD},
            label="x price hike",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{_before('x')}(?:enshittification|"
                rf"(?:is |has been |got |getting )enshittified){E}"
            ),
            {"x": Span.BACKWARD},
            label="x enshittification",
        ),
        Pattern(
            COMPLAINT,
            re.compile(rf"{B}enshittification of {_anchor('x')}"),
            {"x": Span.FORWARD},
            label="enshittification of x",
        ),
        Pattern(
            NEED,
            re.compile(rf"{B}is there (?:a|an|any|some) {ADJECTIVES}{tool} {_anchor('need')}"),
            {"need": Span.NEED},
            label="is there an app to",
        ),
        Pattern(
            NEED,
            re.compile(
                rf"{B}i wish (?:there (?:was|were|is|existed)|someone would (?:make|build|create)) "
                rf"(?:a|an|some) {ADJECTIVES}{tool} {_anchor('need')}"
            ),
            {"need": Span.NEED},
            label="i wish there was an app to",
        ),
        Pattern(
            NEED,
            re.compile(
                rf"{B}(?:i'd|i would|id|i'll|i will) (?:{TOKEN} )?pay "
                rf"(?:good money |so much |a lot |extra |money |real money )?"
                rf"for (?:a|an|some) {ADJECTIVES}{tool} {_anchor('need')}"
            ),
            {"need": Span.NEED},
            label="i'd pay for an app that",
        ),
        Pattern(
            NEED,
            re.compile(
                rf"{B}(?:does |do )?(?:anyone|anybody|any of you|you guys) know (?:of )?"
                rf"(?:a|an|any|some) {ADJECTIVES}{tool} {_anchor('need')}"
            ),
            {"need": Span.NEED},
            label="does anyone know an app to",
        ),
        Pattern(
            NEED,
            re.compile(
                rf"{B}(?:i'm|im|i am|we're|we are) (?:{TOKEN} )?looking for "
                rf"(?:a|an|some) {ADJECTIVES}{tool} {_anchor('need')}"
            ),
            {"need": Span.NEED},
            label="looking for an app to",
        ),
        Pattern(
            NEED,
            re.compile(
                rf"(?:{B}(?:can|could) (?:anyone|anybody|someone|you) |^)(?:recommend|suggest) "
                rf"(?:me )?(?:a|an|any|some) {ADJECTIVES}{tool} {_anchor('need')}"
            ),
            {"need": Span.NEED},
            label="recommend an app to",
        ),
        Pattern(
            NEED,
            re.compile(rf"^any {ADJECTIVES}{product} {_anchor('need')}(?=.* \?$)"),
            {"need": Span.NEED},
            label="any app to",
        ),
    ]


def _german() -> list[Pattern]:
    switched = r"(?:gewechselt|umgestiegen|migriert|umgezogen|umgestellt)"
    to = r"(?:zu|zum|zur|auf|aufs|nach)"
    article = r"(?:(?:den|die|das|dem|der|ein|eine|einen|einem|mein|meine|meinen|meinem) )?"
    tool = (
        r"(?:app|apps|tool|tools|programm|software|seite|webseite|website|dienst|möglichkeit|"
        r"erweiterung|plugin|addon|lösung|anbieter)"
    )
    some = r"(?:eine|ein|einen|irgendeine|irgendein|irgendeinen)"
    return [
        Pattern(
            SWITCH,
            re.compile(
                rf"{B}(?:von|vom) {article}(?P<x>{SPAN}) {to} {article}(?P<y>{SPAN}) {switched}{E}"
            ),
            {"x": Span.EXACT, "y": Span.EXACT},
            label="de: von x zu y gewechselt",
        ),
        Pattern(
            SWITCH,
            re.compile(
                rf"{B}(?:{switched}|wechsel|wechseln|wechsle|wechselte|umstieg|umsteigen|"
                rf"migration) "
                rf"(?:{TOKEN} ){{0,2}}?"
                rf"(?:von|vom) {article}(?P<x>{SPAN}) {to} {_anchor('y')}"
            ),
            {"x": Span.EXACT, "y": Span.FORWARD},
            label="de: wechsel von x zu y",
        ),
        Pattern(
            ALTERNATIVE,
            re.compile(rf"{B}(?:alternativen?|ersatz) (?:zu|zum|zur|für) {_anchor('x')}"),
            {"x": Span.FORWARD},
            label="de: alternative zu x",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{_before('x')}(?:ist|sind|war|waren) "
                rf"(?:(?:mal |schon )?wieder |komplett |total |"
                rf"gerade |einfach |mittlerweile |inzwischen )*(?:down|kaputt|unbrauchbar|offline)"
                rf"(?= ?$| [,?]| (?:seit|heute|gerade)(?!\S))"
            ),
            {"x": Span.BACKWARD},
            label="de: x ist down",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{B}(?:ist|sind) {article}(?P<x>{SPAN}) (?:(?:gerade|mal wieder|wieder|"
                rf"auch|schon wieder|bei euch) )*(?:down|offline|kaputt) \?$"
            ),
            {"x": Span.EXACT},
            label="de: ist x down?",
        ),
        Pattern(
            COMPLAINT,
            re.compile(rf"{_before('x')}(?:wird|werden) (?:{TOKEN} )?immer schlechter{E}"),
            {"x": Span.BACKWARD},
            label="de: x wird immer schlechter",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{_before('x')}(?:erhöht|erhöhte|erhöhen|hat|haben) (?:schon )?(?:wieder )?"
                rf"(?:die|ihre|seine) preise{E}"
            ),
            {"x": Span.BACKWARD},
            label="de: x erhöht die preise",
        ),
        Pattern(
            COMPLAINT,
            re.compile(rf"{B}preiserhöhung (?:bei|von) {_anchor('x')}"),
            {"x": Span.FORWARD},
            label="de: preiserhöhung bei x",
        ),
        Pattern(
            COMPLAINT,
            re.compile(
                rf"{B}(?:habe|hab|haben) (?:{TOKEN} )?(?:mein|meine|meinen|unser|unsere) "
                rf"(?P<x>{SPAN}) gekündigt{E}"
            ),
            {"x": Span.EXACT},
            label="de: mein x gekündigt",
        ),
        Pattern(
            NEED,
            re.compile(
                rf"{B}(?:gibt es|kennt (?:jemand|ihr)|gäbe es) {some} {ADJECTIVES}{tool} (?:, )?"
                rf"(?:für|zum|zur|um|mit der man|mit dem man|womit man) {_anchor('need')}"
            ),
            {"need": Span.NEED},
            label="de: gibt es eine app für",
        ),
    ]


@cache
def patterns(language: str) -> tuple[Pattern, ...]:
    """English patterns everywhere (english is mixed into every subreddit), and the
    patterns of the subreddit's language."""
    found = _english()
    if language == "de":
        found += _german()
    return tuple(found)


# left out in front of an entity: "alternatives to (the) X"
_DETERMINERS = frozenset(
    {"the", "a", "an", "my", "our", "your", "their", "his", "her", "its", "some", "any"}
    | {"der", "die", "das", "den", "dem", "ein", "eine", "einen", "einem", "mein", "meine"}
    | {"meinen", "meinem"}
)
# what a cancelled or switched thing is called besides its name: "my Netflix subscription"
_PRODUCT_SUFFIXES = frozenset(
    {"subscription", "subscriptions", "sub", "membership", "account", "plan", "order"}
    | {"preorder", "pre-order", "service", "contract", "app", "premium", "abo", "abonnement"}
    | {"vertrag", "mitgliedschaft", "konto"}
)
# in front of a need: "an app that (lets me) track sleep"
_NEED_HELPERS = frozenset(
    {"can", "could", "will", "would", "does", "do", "lets", "let", "allows", "allow", "helps"}
    | {"help", "me", "you", "us", "users", "people", "one", "someone", "i", "we", "to"}
    | {"man", "ich", "kann", "könnte", "um", "die", "das", "der", "mit", "zu", "mir", "uns"}
)
# stopwords a need may start with: "a way to (get) notifications"
_NEED_VERBS = frozenset({"get"})
_TIME_UNITS = frozenset(
    {"year", "years", "month", "months", "week", "weeks", "day", "days", "hour", "hours"}
    | {"minutes", "times", "jahre", "jahren", "monate", "monaten", "wochen", "tage", "tagen"}
)
_VAGUE = frozenset(
    {"idea", "ideas", "ability", "game", "games", "thing", "things", "stuff", "way", "ways"}
    | {"option", "options", "something", "anything", "problem", "issue", "one", "ones"}
    | {"this", "that"}
)
# a need about "it" or "this" says nothing on its own
_PRONOUNS = frozenset(
    {"it", "this", "that", "these", "those", "them", "him", "her", "he", "she", "they"}
    | {"es", "das", "diese", "dieses", "ihn", "sie"}
)


# a word every pattern needs one of, to skip the texts without any quickly
_TRIGGERS = re.compile(
    r"switch|migrat|left|ditched|dropped|abandoned|quit|replac|alternativ|instead|"
    r"down|unusable|worse|broken|cancel|price|enshittif|is there|wish|pay|know|looking for|"
    r"recommend|suggest|any|wechsel|wechsl|migri|umgestiegen|umgezogen|umgestellt|umstieg|umsteig|"
    r"ersatz|kaputt|unbrauchbar|offline|schlechter|preis|gekündigt|gibt es|gäbe es|kennt|"
    r"thinking\s+(?:of|about)|considering|debating|about\s+to|planning\s+(?:to|on)|"
    r"should\s+(?:i|we)\b",
    re.IGNORECASE,
)


def _is_number(word: str) -> bool:
    return bool(_NUMBER_WITH_UNIT.match(word))


def _strip_suffix(word: str) -> str:
    """ "netflix-abo" -> "netflix" """
    head, dash, tail = word.rpartition("-")
    return head if dash and head and tail in _PRODUCT_SUFFIXES else word


# before a switch, these make it a question or a possibility, not something that happened
_HYPOTHETICAL = frozenset(
    {"if", "whether", "would", "should", "could", "might", "wanna", "unless", "consider"}
    | {"considering", "thinking", "debating", "worth", "wenn", "ob", "würde", "sollte"}
    | {"überlege", "überlegen"}
)


def _hypothetical(tokens: Sequence[Token], start: int, starts: list[int]) -> bool:
    """Whether the sentence asks about a switch or only considers it: "should I switch
    from …?", "if I want that I need to switch from …", "thinking about switching"."""
    if tokens and tokens[-1].lower == QUESTION:
        return True
    before = bisect_right(starts, start)
    return any(token.lower in _HYPOTHETICAL for token in tokens[:before])


# before someone considering a switch, these make it a condition or a possibility: "if I'm
# thinking of leaving", "I would be about to switch"
_CONDITIONAL = frozenset(
    {"if", "would", "could", "might", "unless", "i'd", "we'd", "wouldn't", "couldn't"}
)


def _conditional(tokens: Sequence[Token], start: int, starts: list[int]) -> bool:
    before = bisect_right(starts, start)
    return any(token.lower in _CONDITIONAL for token in tokens[:before])


def _qualifies(pattern: Pattern, tokens: Sequence[Token], indexes: list[int]) -> bool:
    """Whether the words in front of "alternative" say what kind of alternative it is
    ("the AMD alternative", "a Linux-compatible alternative", "non-US alternatives")
    instead of what it replaces."""
    if indexes[0] > 0 and tokens[indexes[0] - 1].lower in pattern.not_after:
        return True
    return bool(pattern.not_ending) and (
        tokens[indexes[-1]].lower.endswith(pattern.not_ending)
        or tokens[indexes[0]].lower.startswith("non-")
    )


class Extractor:
    """Finds the intents in the texts of one language."""

    def __init__(self, language: str = "en"):
        self.language = language
        self.patterns = patterns(language)
        self.stop = stopwords(language)
        self.boundary = boundary_words(language)
        self.generic = generic_words(language)

    def extract(self, text: str) -> Counter[tuple[str, str]]:
        """(kind, term) -> occurrences in a text cleaned like terms.clean cleans it."""
        counts: Counter[tuple[str, str]] = Counter()
        # most sentences have none of the words any pattern needs
        for _, tokens in sentences_as_written(text, self.language, only=_TRIGGERS):
            counts.update(self.sentence_intents(tokens))
        return counts

    def sentence_intents(self, tokens: Sequence[Token]) -> set[tuple[str, str]]:
        return {(pattern.kind, term) for pattern, term in self.matches(tokens)}

    def matches(self, tokens: Sequence[Token]) -> list[tuple[Pattern, str]]:
        """Every pattern that matched the sentence, with the term it found."""
        line = " ".join(token.lower for token in tokens)
        starts = []
        position = 0
        for token in tokens:
            starts.append(position)
            position += len(token.lower) + 1
        found = []
        for pattern in self.patterns:
            for match in pattern.regex.finditer(line):
                if term := self._term(pattern, match, tokens, starts):
                    found.append((pattern, term))
        # "thinking of leaving Notion for Obsidian" considers one switch, not also leaving
        # Notion for anything
        flows = {
            intent_entity(term).split(ARROW)[0]
            for pattern, term in found
            if pattern.kind == CONSIDERING and ARROW in term
        }
        return [
            (pattern, term)
            for pattern, term in found
            if not (pattern.kind == CONSIDERING and intent_entity(term) in flows)
        ]

    def _term(
        self, pattern: Pattern, match: re.Match[str], tokens: Sequence[Token], starts: list[int]
    ) -> str | None:
        entities: dict[str, str] = {}
        known: dict[str, bool] = {}
        for group, span in pattern.groups.items():
            start, end = match.span(group)
            if start >= len(match.string):
                return None
            first = bisect_right(starts, start) - 1
            if span is Span.NEED:
                need = self._need(tokens, first)
                return intent_term(NEED, need) if need else None
            if span is Span.EXACT:
                indexes = self._exact(tokens, first, bisect_right(starts, end - 1) - 1)
            elif span is Span.FORWARD:
                indexes = self._forward(tokens, first)
            else:
                indexes = self._backward(tokens, first)
            if span is Span.BACKWARD and indexes and _qualifies(pattern, tokens, indexes):
                return None
            entity = self._entity(tokens, indexes, span) if indexes else None
            if not entity:
                return None
            entities[group], known[group] = entity
        if pattern.one_known:
            unsaid = _conditional if pattern.kind == CONSIDERING else _hypothetical
            # the words up to the first entity: "you should switch from" is advice
            said = min(match.start(group) for group in pattern.groups)
            if not any(known.values()) or unsaid(tokens, said, starts):
                return None
        if "y" in entities:
            if entities["x"] == entities["y"]:
                return None
            return intent_term(pattern.kind, f"{entities['x']}{ARROW}{entities['y']}")
        return intent_term(pattern.kind, entities["x"])

    def _bounds(self, token: Token) -> bool:
        """Whether the token ends an entity."""
        if token.is_break:
            return True
        if token.name:
            # "Grammarly", "Bitly": names, even if they look like adverbs
            return token.lower in self.stop
        word = token.lower
        return word in self.boundary or (word.endswith("ly") and len(word) > 4)

    def _exact(self, tokens: Sequence[Token], first: int, last: int) -> list[int] | None:
        while first <= last and tokens[first].lower in _DETERMINERS:
            first += 1
        indexes = list(range(first, last + 1))
        if not indexes or len(indexes) > MAX_ENTITY_TOKENS:
            return None
        if any(tokens[i].is_break for i in indexes):
            return None
        if self._bounds(tokens[first]) or self._bounds(tokens[last]):
            return None
        return indexes

    def _forward(self, tokens: Sequence[Token], index: int) -> list[int]:
        while index < len(tokens) and tokens[index].lower in _DETERMINERS:
            index += 1
        indexes: list[int] = []
        while (
            index < len(tokens)
            and len(indexes) < MAX_ENTITY_TOKENS
            and not self._bounds(tokens[index])
        ):
            indexes.append(index)
            index += 1
        # "my Netflix subscription": the name is enough
        while len(indexes) > 1 and tokens[indexes[-1]].lower in _PRODUCT_SUFFIXES:
            indexes.pop()
        # "a 7800XT (2) years ago"
        if (
            len(indexes) > 1
            and index < len(tokens)
            and tokens[index].lower in _TIME_UNITS
            and _is_number(tokens[indexes[-1]].lower)
        ):
            indexes.pop()
        return indexes

    def _backward(self, tokens: Sequence[Token], index: int) -> list[int]:
        indexes: list[int] = []
        index -= 1
        while index >= 0 and len(indexes) < MAX_ENTITY_TOKENS and not self._bounds(tokens[index]):
            indexes.insert(0, index)
            index -= 1
        return indexes

    def _entity(
        self, tokens: Sequence[Token], indexes: list[int], span: Span
    ) -> tuple[str, bool] | None:
        """The entity the tokens name and whether it's known (not only capitalized), None
        if they don't name one."""
        # "alternatives to (the) X": a determiner says the words up to the anchor are one
        # thing
        determined = indexes[0] > 0 and tokens[indexes[0] - 1].lower in _DETERMINERS
        # trimmed to the name: "the crappy (Lattafa)", "people say (Reddit) is down"; numbers
        # after a name stay ("Model 3", "Windows 11")
        first, last = 0, len(indexes)
        while first < last and not tokens[indexes[first]].name:
            first += 1
        while last > first and not (
            tokens[indexes[last - 1]].name or _is_number(tokens[indexes[last - 1]].lower)
        ):
            last -= 1
        # An entity that starts at the anchor is what stands there: in "a free alternative to
        # photoshop use Krita" it's photoshop, not Krita. One word in front of the name is an
        # adjective ("the crappy Lattafa"), more aren't.
        if span is not Span.BACKWARD and first > 1:
            return None
        # A name with words cut after it is a part of the product when it's possessive, has
        # a determiner or the pattern ends the entity: "Figma's components", "the Windows
        # sound panel", "should I delete Notion pages?" aren't about Figma, Windows or
        # Notion. Otherwise it's the brand of a product ("Google search is getting worse")
        # or a verb follows ("the enshittification of Reddit continues"). What a product is
        # called besides its name can go: "my Netflix subscription".
        if (
            last > first
            and (span is Span.EXACT or determined or tokens[indexes[last - 1]].possessive)
            and any(tokens[i].lower not in _PRODUCT_SUFFIXES for i in indexes[last:])
        ):
            return None
        indexes = indexes[first:last]
        if not any(tokens[i].name and tokens[i].lower not in self.generic for i in indexes):
            return None
        words = [_strip_suffix(tokens[i].lower) for i in indexes]
        if not any(char.isalpha() for char in "".join(words)) or _is_number(words[0]):
            return None
        if all(word in self.generic or word in _PRODUCT_SUFFIXES for word in words):
            return None
        known = any(tokens[i].known and tokens[i].lower not in self.generic for i in indexes)
        return " ".join(words), known

    def _need(self, tokens: Sequence[Token], index: int) -> str | None:
        # "is there any way that you could send it": asking someone, not for a tool
        if index < len(tokens) and tokens[index].lower in ("you", "u"):
            return None
        while index < len(tokens) and (
            tokens[index].lower in _NEED_HELPERS
            or (tokens[index].lower.endswith("ly") and not tokens[index].name)
        ):
            index += 1
        words: list[str] = []
        while index < len(tokens) and len(words) < MAX_ENTITY_TOKENS and not tokens[index].is_break:
            words.append(tokens[index].lower)
            index += 1
        if not words or (words[0] in self.stop and words[0] not in _NEED_VERBS):
            return None
        while words and words[-1] in self.boundary:
            words.pop()
        # one german word can be a whole need: "eine App für (Haushaltsbuch)"
        compound = self.language == "de" and len(words) == 1 and len(words[0]) >= 10
        if (len(words) < MIN_NEED_TOKENS and not compound) or _is_number(words[0]):
            return None
        if any(word in _PRONOUNS or _is_number(word) for word in words):
            return None
        # "is there a way to (get an idea)", "(play the game)": no need in particular
        if words[-1] in _VAGUE:
            return None
        return " ".join(words)


def source_sentence(text: str, term: str, language: str = "en") -> str | None:
    """The sentence of a cleaned text an intent's term came from, as written."""
    extract = extractor(language)
    for sentence, tokens in sentences_as_written(text, language):
        if any(found == term for _, found in extract.sentence_intents(tokens)):
            return " ".join(sentence.split())
    return None


@cache
def extractor(language: str) -> Extractor:
    return Extractor(language)


def extract_intents(text: str, language: str = "en") -> Counter[tuple[str, str]]:
    """(kind, term) -> occurrences, in a text cleaned like terms.clean cleans it."""
    return extractor(language).extract(text)
