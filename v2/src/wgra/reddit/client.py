"""A small client for the two things we need from reddit: listings and subreddit info.

Authentication uses reddit's app-only OAuth flow (client id + secret, no user account),
which is enough to read public listings. Requests are sent one at a time and paced so
that we never exceed our budget, using reddit's x-ratelimit-* headers as the source of
truth (they also account for other programs using the same client id).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Self

import httpx

from wgra.reddit.models import RedditItem, parse_listing

log = logging.getLogger(__name__)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_URL = "https://oauth.reddit.com"
LISTING_LIMIT = 100

# app-only tokens can't be refreshed, request a new one well before it expires
TOKEN_REFRESH_MARGIN = 3600.0
# don't hammer the token endpoint when the credentials are wrong
AUTH_RETRY_DELAY = 60.0


class RedditError(Exception):
    def __init__(self, status: int, message: str, retry_after: float | None = None):
        super().__init__(f"{status or 'network error'}: {message}")
        self.status = status
        self.retry_after = retry_after


@dataclass
class RateLimit:
    remaining: float | None = None
    used: int | None = None
    # time.monotonic() at which the current window resets
    reset_at: float | None = None


class RedditClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        requests_per_minute: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._credentials = (client_id, client_secret)
        self._http = httpx.AsyncClient(
            headers={"User-Agent": user_agent}, timeout=30, transport=transport
        )
        self._spacing = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._token: str | None = None
        self._token_refresh_at = 0.0
        self._auth_blocked_until = 0.0
        self.ratelimit = RateLimit()
        self.requests = 0
        # seconds the last request took, without waiting for the rate limit
        self.last_latency = 0.0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def listing(self, path: str) -> list[RedditItem]:
        """Newest items of a listing such as ``/r/rust+golang/comments``."""
        response = await self._get(path, {"limit": LISTING_LIMIT, "raw_json": 1})
        return parse_listing(response.json())

    async def subreddit_problem(self, name: str) -> str | None:
        """Why a subreddit can't be read (private, banned, missing), or None if it can."""
        try:
            response = await self._get(f"/r/{name}/about", {"raw_json": 1})
        except RedditError as error:
            if error.status in (302, 403, 404):
                return {302: "does not exist", 403: "private", 404: "banned or missing"}[
                    error.status
                ]
            raise
        data = response.json().get("data") or {}
        if data.get("subreddit_type") not in (None, "public", "restricted", "archived"):
            return str(data.get("subreddit_type"))
        return None

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        async with self._lock:
            await self._pace()
            for attempt in range(2):
                token = await self._access_token()
                started = self._clock()
                try:
                    response = await self._http.get(
                        f"{API_URL}{path}",
                        params=params,
                        headers={"Authorization": f"bearer {token}"},
                    )
                except httpx.HTTPError as error:
                    self._next_request_at = self._clock() + self._current_spacing()
                    raise RedditError(0, repr(error)) from error
                finally:
                    self.requests += 1
                    self.last_latency = self._clock() - started

                # pace the next request with the rate limit reddit just reported
                self._update_ratelimit(response)
                self._next_request_at = self._clock() + self._current_spacing()
                # the token may have expired early, get a new one and retry once
                if response.status_code == 401 and attempt == 0:
                    self._token = None
                    continue
                break

        if response.status_code == 429:
            raise RedditError(429, "rate limited", retry_after=self._seconds_until_reset())
        if response.status_code >= 300:
            raise RedditError(response.status_code, response.text[:200])
        return response

    def _current_spacing(self) -> float:
        """Seconds between requests: our own budget, or more if reddit says we're low."""
        spacing = self._spacing
        reset_in = self._seconds_until_reset()
        if self.ratelimit.remaining is not None and reset_in is not None:
            spacing = max(spacing, reset_in / max(self.ratelimit.remaining, 1.0))
        return spacing

    def _seconds_until_reset(self) -> float | None:
        if self.ratelimit.reset_at is None:
            return None
        return max(self.ratelimit.reset_at - self._clock(), 0.0)

    async def _pace(self) -> None:
        wait = self._next_request_at - self._clock()
        reset_in = self._seconds_until_reset()
        if self.ratelimit.remaining is not None and self.ratelimit.remaining < 1 and reset_in:
            log.warning("reddit rate limit exhausted, waiting %.0fs", reset_in)
            wait = max(wait, reset_in)
        if wait > 0:
            await self._sleep(wait)

    def _update_ratelimit(self, response: httpx.Response) -> None:
        headers = response.headers
        try:
            if "x-ratelimit-remaining" in headers:
                self.ratelimit.remaining = float(headers["x-ratelimit-remaining"])
            if "x-ratelimit-used" in headers:
                self.ratelimit.used = int(float(headers["x-ratelimit-used"]))
            if "x-ratelimit-reset" in headers:
                self.ratelimit.reset_at = self._clock() + float(headers["x-ratelimit-reset"])
        except ValueError:
            log.debug("unparsable rate limit headers: %s", dict(headers))

    async def _access_token(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._token_refresh_at:
            return self._token
        if now < self._auth_blocked_until:
            raise RedditError(0, "authentication failed recently, not retrying yet")

        try:
            response = await self._http.post(
                TOKEN_URL, auth=self._credentials, data={"grant_type": "client_credentials"}
            )
            body = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError) as error:
            self._auth_blocked_until = now + AUTH_RETRY_DELAY
            raise RedditError(0, f"authentication failed: {error!r}") from error

        if "access_token" not in body:
            self._auth_blocked_until = now + AUTH_RETRY_DELAY
            raise RedditError(response.status_code, f"authentication failed: {response.text[:200]}")

        expires_in = float(body.get("expires_in", 3600))
        self._token = str(body["access_token"])
        self._token_refresh_at = now + max(expires_in - TOKEN_REFRESH_MARGIN, expires_in / 2)
        log.info("got a reddit access token, valid for %.0fh", expires_in / 3600)
        return self._token
