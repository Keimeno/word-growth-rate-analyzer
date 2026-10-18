"""Push notifications through ntfy (https://ntfy.sh), self-hosted or the public server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class Message:
    title: str
    # markdown, ntfy's apps render it
    body: str
    # opened when the notification is tapped
    click: str = ""
    # emoji shortcodes or plain tags, https://docs.ntfy.sh/emojis/
    tags: tuple[str, ...] = ()
    # 1 (min) to 5 (max), 3 is the default
    priority: int = 3
    # buttons, (label, url), at most three
    links: tuple[tuple[str, str], ...] = field(default=())

    def payload(self, topic: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "topic": topic,
            "title": self.title,
            "message": self.body,
            "priority": self.priority,
            "markdown": True,
        }
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.click:
            payload["click"] = self.click
        if self.links:
            payload["actions"] = [
                {"action": "view", "label": label, "url": url, "clear": False}
                for label, url in self.links[:3]
            ]
        return payload


class NtfyError(Exception):
    pass


class Ntfy:
    """Publishes as JSON, so titles and terms can contain any unicode ("für")."""

    def __init__(
        self,
        url: str,
        topic: str,
        token: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.topic = topic
        self._http = httpx.Client(base_url=url, headers=headers, timeout=10.0, transport=transport)

    def send(self, message: Message) -> None:
        try:
            response = self._http.post("/", json=message.payload(self.topic))
        except httpx.HTTPError as error:
            raise NtfyError(f"ntfy unreachable: {error}") from error
        if response.status_code != 200:
            raise NtfyError(f"ntfy answered {response.status_code}: {response.text[:200]}")

    def close(self) -> None:
        self._http.close()
