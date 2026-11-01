"""Running the dashboard (app.py) with uvicorn, and exporting its OpenAPI schema."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import uvicorn
from clickhouse_connect.driver.client import Client
from fastapi import FastAPI

from wgra.config import Env
from wgra.store import connect
from wgra.web.app import Settings, create_app

log = logging.getLogger(__name__)


def settings_from_environ(env: Env) -> Settings:
    now = os.environ.get("UNDERCURRENT_NOW")
    return Settings(
        grafana_url=env.grafana_url,
        password=os.environ.get("WEB_PASSWORD", ""),
        now=datetime.fromisoformat(now) if now else None,
        page=not os.environ.get("WEB_API_ONLY"),
    )


def web_client(env: Env, database: str | None = None) -> Client:
    """No session: requests run in parallel, and a session takes one query at a time. Read
    only even as a user that could write; the web user's profile says the same."""
    return connect(
        env,
        database,
        autogenerate_session_id=False,
        settings={"readonly": 2, "max_execution_time": 30},
    )


def app_from_environ() -> FastAPI:
    """The app as `wgra web` builds it, for uvicorn's --reload, which imports a factory."""
    env = Env.from_environ()
    return create_app(web_client(env), settings_from_environ(env))


def serve(host: str, port: int, reload: bool = False) -> None:
    log.info(
        "web dashboard on http://%s:%d", "localhost" if host in ("", "0.0.0.0") else host, port
    )
    uvicorn.run(
        "wgra.web.server:app_from_environ",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level="warning",
        # behind an ssh tunnel or a proxy on the same machine
        proxy_headers=True,
    )


def openapi() -> dict[str, Any]:
    """The API's schema, without a database."""
    return create_app(None, Settings()).openapi()  # type: ignore[arg-type]


def print_openapi() -> None:
    print(json.dumps(openapi(), indent=2, ensure_ascii=False))
