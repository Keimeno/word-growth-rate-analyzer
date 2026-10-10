import os
import secrets
from collections.abc import Iterator

import pytest
from dotenv import load_dotenv

from wgra.config import Env
from wgra.store import connect


@pytest.fixture
def client() -> Iterator:
    """A throwaway database in a real ClickHouse (from .env), dropped afterwards.

    Skipped locally when ClickHouse isn't reachable (start it with
    `docker compose up -d clickhouse`), but never skipped in CI.
    """
    load_dotenv()
    try:
        env = Env.from_environ(require_reddit=False)
        admin = connect(env)
        admin.command("SELECT 1")
    except Exception as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"ClickHouse not available: {error}")

    database = f"wgra_test_{secrets.token_hex(4)}"
    admin.command(f"CREATE DATABASE {database}")
    try:
        yield connect(env, database=database)
    finally:
        admin.command(f"DROP DATABASE {database}")
