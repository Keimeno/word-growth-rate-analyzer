from wgra.config import Config, parse_config
from wgra.reddit.models import RedditItem


def make_config(**overrides: object) -> Config:
    raw: dict[str, object] = {
        "groups": {"tech": ["technology", "programming"], "de": ["de"]},
        "languages": {"de": ["de"]},
    }
    raw.update(overrides)
    return parse_config(raw)


def make_item(
    id36: int,
    created_utc: int = 1_700_000_000,
    *,
    source: str = "comment",
    subreddit: str = "technology",
    author: str = "someone",
    text: str = "hello world",
    distinguished: str | None = None,
    stickied: bool = False,
) -> RedditItem:
    prefix = "t1" if source == "comment" else "t3"
    return RedditItem(
        fullname=f"{prefix}_{_base36(id36)}",
        source="comment" if source == "comment" else "post",
        subreddit=subreddit,
        author=author,
        created_utc=created_utc,
        text=text,
        permalink=f"/r/{subreddit}/comments/x/{id36}",
        distinguished=distinguished,
        stickied=stickied,
    )


def _base36(number: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        number, remainder = divmod(number, 36)
        out = digits[remainder] + out
        if number == 0:
            return out
