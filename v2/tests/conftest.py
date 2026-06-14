import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from dotenv import load_dotenv

from wgra.config import Env
from wgra.store import connect


@contextmanager
def throwaway_database() -> Iterator:
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


@pytest.fixture
def client() -> Iterator:
    with throwaway_database() as database:
        yield database


@pytest.fixture(scope="module")
def module_client() -> Iterator:
    """The same, shared by the tests of a module: for histories that take a while to build."""
    with throwaway_database() as database:
        yield database
