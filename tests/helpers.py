from datetime import UTC, datetime, timedelta

from wgra.config import Config, parse_config
from wgra.detect.short_term import Trend
from wgra.sources.base import Item
from wgra.sources.reddit.models import RedditItem
from wgra.sources.reddit.source import to_item


def no_sample(**reddit: object) -> dict[str, object]:
    """config.yaml's platforms section without the r/all sample."""
    return {"reddit": {"sample": {"requests_per_minute": 0}, **reddit}}


def make_config(**overrides: object) -> Config:
    raw: dict[str, object] = {
        "groups": {"tech": ["r/technology", "r/programming"], "de": ["r/de"]},
        "languages": {"de": ["r/de"]},
    }
    raw.update(overrides)
    return parse_config(raw)


def make_item(
    id36: int,
    created_utc: int = 1_700_000_000,
    *,
    doc_type: str = "comment",
    subreddit: str = "technology",
    author: str = "someone",
    text: str = "hello world",
    distinguished: str | None = None,
    stickied: bool = False,
) -> RedditItem:
    prefix = "t1" if doc_type == "comment" else "t3"
    return RedditItem(
        fullname=f"{prefix}_{_base36(id36)}",
        doc_type="comment" if doc_type == "comment" else "post",
        subreddit=subreddit,
        author=author,
        created_utc=created_utc,
        text=text,
        permalink=f"/r/{subreddit}/comments/x/{id36}",
        distinguished=distinguished,
        stickied=stickied,
    )


def make_doc(
    config: Config, id36: int, *args: object, channel: str | None = None, **values: object
) -> Item:
    """A reddit item as the Reddit source hands it to the pipeline (make_item's arguments),
    in its subreddit's channel or r/all, or in `channel`."""
    return to_item(make_item(id36, *args, **values), config, channel)  # type: ignore[arg-type]


def _base36(number: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        number, remainder = divmod(number, 36)
        out = digits[remainder] + out
        if number == 0:
            return out


def make_trend(term: str = "vision pro", **overrides: object) -> Trend:
    detected_at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    values: dict[str, object] = {
        "horizon": "24h",
        "scope": "r/technology",
        "term": term,
        "detected_at": detected_at,
        "scope_type": "channel",
        "kind": "phrase",
        "window_start": detected_at - timedelta(hours=24),
        "window_end": detected_at,
        "mentions": 300,
        "total": 10_000,
        "reference_mentions": 5,
        "reference_total": 280_000,
        "authors": 250,
        "prior": 1.0,
        "log_odds": 6.0,
        "ratio": 400.0,
        "z": 12.0,
        "is_new": False,
        "reference_days": 28,
    }
    values.update(overrides)
    return Trend(**values)  # type: ignore[arg-type]
