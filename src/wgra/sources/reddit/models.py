"""Reddit's listings and comment trees, and what an item of them is."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from wgra.sources.base import Item
from wgra.sources.reddit.channels import PLATFORM

DocType = Literal["comment", "post"]

DELETED_AUTHOR = "[deleted]"


@dataclass(frozen=True, slots=True)
class RedditItem:
    # reddit's fullname, "t1_…" for comments and "t3_…" for posts. Comment and post ids
    # are separate sequences, only the fullname is unique across both.
    fullname: str
    doc_type: DocType
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

    def to_item(self, channel: str, lang: str, skip: str | None = None) -> Item:
        """The item as the shared pipeline takes it, its counts in `channel`."""
        return Item(
            id=self.fullname,
            platform=PLATFORM,
            channel=channel,
            doc_type=self.doc_type,
            author="" if self.author == DELETED_AUTHOR else self.author,
            created_at=datetime.fromtimestamp(self.created_utc, UTC),
            text=self.text,
            url=f"https://www.reddit.com{self.permalink}",
            lang=lang,
            skip=skip,
        )


def _parse_child(child: dict[str, Any]) -> RedditItem | None:
    kind, data = child.get("kind"), child.get("data") or {}
    if kind == "t1":
        doc_type: DocType = "comment"
        text = data.get("body") or ""
    elif kind == "t3":
        doc_type = "post"
        title, selftext = data.get("title") or "", data.get("selftext") or ""
        # a removed post keeps its title, only the selftext is replaced
        if selftext in ("[deleted]", "[removed]"):
            selftext = ""
        text = f"{title}\n\n{selftext}" if selftext else title
    else:
        return None

    return RedditItem(
        fullname=data["name"],
        doc_type=doc_type,
        subreddit=(data.get("subreddit") or "").lower(),
        author=data.get("author") or DELETED_AUTHOR,
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


def parse_tree(payload: dict[str, Any]) -> list[RedditItem]:
    """The comments of a post's comment tree (the second listing of /comments/<id>),
    replies included, in no particular order. Comments behind "load more" aren't in it."""
    items = []
    stack = list((payload.get("data") or {}).get("children") or [])
    while stack:
        child = stack.pop()
        if (item := _parse_child(child)) is not None:
            items.append(item)
        replies = (child.get("data") or {}).get("replies")
        # a comment without replies has "" instead of a listing
        if isinstance(replies, dict):
            stack.extend((replies.get("data") or {}).get("children") or [])
    return items
