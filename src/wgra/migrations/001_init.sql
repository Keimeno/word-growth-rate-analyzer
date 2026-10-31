-- Raw documents: comments and posts. Only kept for 48 hours: reddit asks API users to
-- delete stored content within 48h, so it can't outlive a deletion on reddit for long.
-- It's used for example comments in the dashboards, everything long-lived is aggregated.
--
-- The documents remember which intents (docs/ARCHITECTURE.md §4.7) they carry, so
-- dashboards can show the comments behind an intent exactly. Like the text, this is gone
-- after 48 hours.
CREATE TABLE items
(
    id          String,                    -- unique within its platform: reddit's fullname
    platform    LowCardinality(String),    -- reddit
    channel     LowCardinality(String),    -- where its counts go: "r/technology", "r/all"
    doc_type    LowCardinality(String),    -- comment | post
    created_at  DateTime('UTC'),
    author_hash UInt64,                    -- keyed hash, never the username
    text        String,
    url         String,
    lang        LowCardinality(String),    -- its language: the channel's, or what it says
    token_count UInt32,
    intents     Array(String),             -- the intents' terms ("notion → obsidian")
    ingested_at DateTime('UTC') DEFAULT now()
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMMDD(created_at)
ORDER BY (channel, created_at, id)
TTL created_at + INTERVAL 48 HOUR;

-- Denominators: how many documents, words and authors a channel had per hour.
CREATE TABLE scope_hourly
(
    hour      DateTime('UTC'),
    channel   LowCardinality(String),
    doc_type  LowCardinality(String),
    docs      SimpleAggregateFunction(sum, UInt64),
    tokens    SimpleAggregateFunction(sum, UInt64),
    authors   AggregateFunction(uniqCombined(12), UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (channel, doc_type, hour);

CREATE MATERIALIZED VIEW scope_hourly_mv TO scope_hourly AS
SELECT
    toStartOfHour(created_at) AS hour,
    channel,
    doc_type,
    toUInt64(count()) AS docs,
    toUInt64(sum(token_count)) AS tokens,
    uniqCombinedState(12)(author_hash) AS authors
FROM items
GROUP BY hour, channel, doc_type;

-- One row per (document, distinct term). Never stored, the materialized views
-- below aggregate every insert into hourly and daily counts.
CREATE TABLE term_events
(
    hour        DateTime('UTC'),
    channel     LowCardinality(String),
    doc_type    LowCardinality(String),
    kind        LowCardinality(String),    -- word | phrase | domain | subreddit, or an intent
    term        String,
    author_hash UInt64,
    occurrences UInt32
)
ENGINE = Null;

-- docs: documents containing the term, the main measure, a single comment can't add
-- more than one. authors: distinct authors, to tell a trend from one spammer.
CREATE TABLE term_hourly
(
    hour        DateTime('UTC'),
    channel     LowCardinality(String),
    doc_type    LowCardinality(String),
    kind        LowCardinality(String),
    term        String,
    occurrences SimpleAggregateFunction(sum, UInt64),
    docs        SimpleAggregateFunction(sum, UInt64),
    authors     AggregateFunction(uniqCombined(12), UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (channel, term, kind, doc_type, hour)
TTL hour + INTERVAL 180 DAY;

CREATE MATERIALIZED VIEW term_hourly_mv TO term_hourly AS
SELECT
    hour,
    channel,
    doc_type,
    kind,
    term,
    sum(toUInt64(occurrences)) AS occurrences,
    toUInt64(count()) AS docs,
    uniqCombinedState(12)(author_hash) AS authors
FROM term_events
GROUP BY hour, channel, doc_type, kind, term;

-- The long term history, kept forever.
CREATE TABLE term_daily
(
    day         Date,
    channel     LowCardinality(String),
    doc_type    LowCardinality(String),
    kind        LowCardinality(String),
    term        String,
    occurrences SimpleAggregateFunction(sum, UInt64),
    docs        SimpleAggregateFunction(sum, UInt64),
    authors     AggregateFunction(uniqCombined(12), UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYear(day)
ORDER BY (channel, term, kind, doc_type, day);

CREATE MATERIALIZED VIEW term_daily_mv TO term_daily AS
SELECT
    toDate(hour) AS day,
    channel,
    doc_type,
    kind,
    term,
    sum(toUInt64(occurrences)) AS occurrences,
    toUInt64(count()) AS docs,
    uniqCombinedState(12)(author_hash) AS authors
FROM term_events
GROUP BY day, channel, doc_type, kind, term;

-- Every request to a platform, for the ingestion health dashboard.
CREATE TABLE polls
(
    ts                  DateTime64(3, 'UTC'),
    platform            LowCardinality(String),
    feed                LowCardinality(String),
    kind                LowCardinality(String),   -- comments | posts
    sample              Bool,                     -- a sample, never complete (r/all)
    status              UInt16,                   -- http status, 0 for network errors
    items               UInt16,
    new_items           UInt16,
    gap                 Bool,
    id_span             UInt64,                   -- how far the platform's ids advanced
    latency_ms          UInt32,
    interval_s          Float32,
    rate                Float32,                  -- estimated items per second
    ratelimit_remaining Float32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (platform, feed, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY;

-- The channels and groups from config.yaml, rewritten on every start of the ingester, so
-- the detectors, dashboards and queries know them. A scope is a channel or a group.
-- analyzed: the detectors see it (not r/_search). background: the platform channel, the
-- prior of its platform's scopes (r/all).
CREATE TABLE channels
(
    channel    String,
    platform   LowCardinality(String),
    language   LowCardinality(String),
    analyzed   Bool,
    background Bool
)
ENGINE = MergeTree
ORDER BY channel;

-- Groups list channels, the group named like a platform ("reddit") every tracked channel
-- of it.
CREATE TABLE channel_groups
(
    group_name String,
    channel    String
)
ENGINE = MergeTree
ORDER BY (group_name, channel);
