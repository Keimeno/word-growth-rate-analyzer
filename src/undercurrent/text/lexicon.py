"""Word lists shipped with the package: stopwords, and the lists intents are checked against."""

from __future__ import annotations

from functools import cache
from importlib import resources


@cache
def word_list(name: str) -> frozenset[str]:
    """The lowercase words of `undercurrent/text/<name>.txt`, one per line, # starts a comment.
    Empty if there's no such list (a language without one)."""
    path = resources.files("undercurrent.text").joinpath(f"{name}.txt")
    if not path.is_file():
        return frozenset()
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


@cache
def stopwords(language: str) -> frozenset[str]:
    # english is mixed into every subreddit
    return word_list("stopwords/en") | word_list(f"stopwords/{language}")
