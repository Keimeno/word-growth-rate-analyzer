from __future__ import annotations

import logging
import re
from importlib import resources

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from wgra.config import Env

log = logging.getLogger(__name__)

_STATEMENT_END = re.compile(r";\s*$", re.M)


def connect(env: Env, database: str | None = None) -> Client:
    return clickhouse_connect.get_client(
        host=env.clickhouse_host,
        port=env.clickhouse_port,
        username=env.clickhouse_user,
        password=env.clickhouse_password,
        database=database or env.clickhouse_database,
    )


def split_statements(sql: str) -> list[str]:
    """Statements of a migration file, which end with a semicolon at the end of a line."""
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    return [part.strip() for part in _STATEMENT_END.split(without_comments) if part.strip()]


def migrate(client: Client) -> list[str]:
    """Applies all migrations that haven't been applied yet, returns their names."""
    client.command(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version String, applied_at DateTime('UTC') DEFAULT now()) "
        "ENGINE = MergeTree ORDER BY version"
    )
    applied = {row[0] for row in client.query("SELECT version FROM schema_migrations").result_rows}

    files = sorted(
        (
            file
            for file in resources.files("wgra.migrations").iterdir()
            if file.name.endswith(".sql")
        ),
        key=lambda file: file.name,
    )
    newly_applied = []
    for file in files:
        version = file.name.removesuffix(".sql")
        if version in applied:
            continue
        log.info("applying migration %s", version)
        for statement in split_statements(file.read_text(encoding="utf-8")):
            client.command(statement)
        client.insert("schema_migrations", [[version]], column_names=["version"])
        newly_applied.append(version)
    return newly_applied
