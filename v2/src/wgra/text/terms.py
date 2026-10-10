"""Turns the text of a comment or post into the terms we count.

Terms come in four kinds:

* ``word``: every single word, lowercased ("rust", "für", "node.js", "gpt-5")
* ``phrase``: 2-3 consecutive words within a sentence that neither start nor end with a
  stopword ("vision pro", "right to repair", but never "of the")
* ``domain``: the host of every linked url ("github.com")
* ``subreddit``: mentioned subreddits ("r/selfhosted")

Quoted lines, code and user mentions are ignored. Usernames are never part of a term.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache
from importlib import resources
from urllib.parse import urlsplit

WORD = "word"
PHRASE = "phrase"
DOMAIN = "domain"
SUBREDDIT = "subreddit"

MAX_TOKEN_LENGTH = 40

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿\xad"), None)
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})

_FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
# quoted lines repeat what someone else wrote, counting them would count it twice
_QUOTE_LINE = re.compile(r"^[ \t]*>.*$", re.M)
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()\[\]{}\"'`]+", re.I)
_SUBREDDIT_MENTION = re.compile(r"(?<![\w/])/?r/([a-z0-9][a-z0-9_]{1,20})\b", re.I)
_USER_MENTION = re.compile(r"(?<![\w/])/?u/[\w-]+", re.I)

# punctuation that ends a phrase. dots and commas only end it when followed by
# whitespace, so "node.js" or "3.5" stay intact
_SEGMENT_BREAK = re.compile(
    r"[!?;:()\[\]{}\"\u201c\u201d\u201e\u00ab\u00bb|\\/*~^=<>\u2026\u2022\n\r\t]+|[.,](?=\s|$)|\s+[-\u2013\u2014]+(?=\s)|[\u2013\u2014]"
)
# letters and digits of any script, joined by inner hyphens, apostrophes and dots
_TOKEN = re.compile(r"[^\W_]+(?:[-'.][^\W_]+)*")


@dataclass(frozen=True, slots=True)
class Terms:
    # (kind, term) -> occurrences within the text
    counts: Counter[tuple[str, str]]
    # number of words, the denominator for word frequencies
    token_count: int


@cache
def _load_stopwords(language: str) -> frozenset[str]:
    path = resources.files("wgra.text") / "stopwords" / f"{language}.txt"
    if not path.is_file():
        return frozenset()
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


@cache
def stopwords(language: str) -> frozenset[str]:
    # english is mixed into every subreddit
    return _load_stopwords("en") | _load_stopwords(language)


def _domain(url: str) -> str | None:
    if not url.lower().startswith(("http://", "https://")):
        url = f"http://{url}"
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host or "." not in host:
        return None
    return host.removeprefix("www.")


def _tokens(segment: str) -> list[str]:
    tokens = []
    for token in _TOKEN.findall(segment):
        token = token.removesuffix("'s")
        if 0 < len(token) <= MAX_TOKEN_LENGTH:
            tokens.append(token)
    return tokens


def _has_letter(words: list[str]) -> bool:
    return any(char.isalpha() for word in words for char in word)


def extract_terms(text: str, language: str = "en", max_ngram: int = 3) -> Terms:
    counts: Counter[tuple[str, str]] = Counter()
    stop = stopwords(language)

    # reddit double-escapes some entities, e.g. the zero width space in "&amp;#x200B;"
    text = html.unescape(html.unescape(text)).translate(_INVISIBLE).translate(_APOSTROPHES)
    text = _FENCED_CODE.sub("\n", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _QUOTE_LINE.sub("", text)

    def replace_link(match: re.Match[str]) -> str:
        if domain := _domain(match.group(2)):
            counts[DOMAIN, domain] += 1
        return f"\n{match.group(1)}\n"

    def replace_url(match: re.Match[str]) -> str:
        if domain := _domain(match.group(0).rstrip(".,!?")):
            counts[DOMAIN, domain] += 1
        return "\n"

    def replace_subreddit(match: re.Match[str]) -> str:
        counts[SUBREDDIT, f"r/{match.group(1).lower()}"] += 1
        return "\n"

    text = _MARKDOWN_LINK.sub(replace_link, text)
    text = _URL.sub(replace_url, text)
    text = _SUBREDDIT_MENTION.sub(replace_subreddit, text)
    text = _USER_MENTION.sub("\n", text)

    token_count = 0
    for segment in _SEGMENT_BREAK.split(text.lower()):
        tokens = _tokens(segment)
        token_count += len(tokens)
        for token in tokens:
            counts[WORD, token] += 1

        for n in range(2, max_ngram + 1):
            for start in range(len(tokens) - n + 1):
                words = tokens[start : start + n]
                if words[0] in stop or words[-1] in stop or not _has_letter(words):
                    continue
                counts[PHRASE, " ".join(words)] += 1

    return Terms(counts=counts, token_count=token_count)
