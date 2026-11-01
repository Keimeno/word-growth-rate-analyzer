-- Pinned terms and saved views of the web dashboard (docs/WEB-DASHBOARD.md §7.1, item 17),
-- the same on every device. The dashboard's ClickHouse user may insert into these two and
-- nothing else (clickhouse/users.d/web.xml); a row is replaced by its newest version, and
-- unpinning or deleting writes one with `deleted`.
CREATE TABLE IF NOT EXISTS web_pins
(
    kind       LowCardinality(String),
    term       String,
    scope      String,                      -- where it was pinned, its page's scope
    pinned_at  DateTime('UTC'),
    deleted    Bool DEFAULT false,
    updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (kind, term);

CREATE TABLE IF NOT EXISTS web_views
(
    name       String,
    url        String,                      -- a path and query of the dashboard
    saved_at   DateTime('UTC'),
    deleted    Bool DEFAULT false,
    updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY name;
