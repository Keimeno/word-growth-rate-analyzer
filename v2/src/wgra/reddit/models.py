from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Source = Literal["comment", "post"]


@dataclass(frozen=True, slots=True)
class RedditItem:
    # reddit's fullname, "t1_…" for comments and "t3_…" for posts. Comment and post ids
    # are separate sequences, only the fullname is unique across both.
    fullname: str
    source: Source
    subreddit: str
    author: str
    created_utc: int
    text: str
    permalink: str
    distinguished: str | None
    stickied: bool

    @property
    def id36(self) -> int:
        """The base 36 id as a number, it increases with every new comment (or post)."""
        return int(self.fullname[3:], 36)


def _parse_child(child: dict[str, Any]) -> RedditItem | None:
    kind, data = child.get("kind"), child.get("data") or {}
    if kind == "t1":
        source: Source = "comment"
        text = data.get("body") or ""
    elif kind == "t3":
        source = "post"
        title, selftext = data.get("title") or "", data.get("selftext") or ""
        # a removed post keeps its title, only the selftext is replaced
        if selftext in ("[deleted]", "[removed]"):
            selftext = ""
        text = f"{title}\n\n{selftext}" if selftext else title
    else:
        return None

    return RedditItem(
        fullname=data["name"],
        source=source,
        subreddit=(data.get("subreddit") or "").lower(),
        author=data.get("author") or "[deleted]",
        created_utc=int(data.get("created_utc") or 0),
        text=text,
        permalink=data.get("permalink") or "",
        distinguished=data.get("distinguished"),
        stickied=bool(data.get("stickied")),
    )


def parse_listing(payload: dict[str, Any]) -> list[RedditItem]:
    """Items of a listing response, newest first like reddit returns them."""
    children = (payload.get("data") or {}).get("children") or []
    return [item for child in children if (item := _parse_child(child)) is not None]
