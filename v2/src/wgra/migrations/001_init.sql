-- Raw comments and posts. Only kept for 48 hours: reddit asks API users to delete
-- stored content within 48h, so it can't outlive a deletion on reddit for long. It's
-- used for example comments in the dashboards, everything long-lived is aggregated.
CREATE TABLE items
(
    id          String,                    -- reddit fullname, t1_* comment, t3_* post
    source      LowCardinality(String),    -- comment | post
    subreddit   LowCardinality(String),
    created_at  DateTime('UTC'),
    author_hash UInt64,                    -- keyed hash, never the username
    text        String,
    permalink   String,
    token_count UInt32,
    ingested_at DateTime('UTC') DEFAULT now()
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMMDD(created_at)
ORDER BY (subreddit, created_at, id)
TTL created_at + INTERVAL 48 HOUR;

-- Denominators: how many comments/posts, words and authors a subreddit had per hour.
CREATE TABLE scope_hourly
(
    hour      DateTime('UTC'),
    subreddit LowCardinality(String),
    source    LowCardinality(String),
    docs      SimpleAggregateFunction(sum, UInt64),
    tokens    SimpleAggregateFunction(sum, UInt64),
    authors   AggregateFunction(uniqCombined(12), UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (subreddit, source, hour);

CREATE MATERIALIZED VIEW scope_hourly_mv TO scope_hourly AS
SELECT
    toStartOfHour(created_at) AS hour,
    subreddit,
    source,
    toUInt64(count()) AS docs,
    toUInt64(sum(token_count)) AS tokens,
    uniqCombinedState(12)(author_hash) AS authors
FROM items
GROUP BY hour, subreddit, source;

-- One row per (comment or post, distinct term). Never stored, the materialized views
-- below aggregate every insert into hourly and daily counts.
CREATE TABLE term_events
(
    hour        DateTime('UTC'),
    subreddit   LowCardinality(String),
    source      LowCardinality(String),
    kind        LowCardinality(String),    -- word | phrase | domain | subreddit
    term        String,
    author_hash UInt64,
    occurrences UInt32
)
ENGINE = Null;

-- docs: comments/posts containing the term, the main measure, a single comment can't
-- add more than one. authors: distinct authors, to tell a trend from one spammer.
CREATE TABLE term_hourly
(
    hour        DateTime('UTC'),
    subreddit   LowCardinality(String),
    source      LowCardinality(String),
    kind        LowCardinality(String),
    term        String,
    occurrences SimpleAggregateFunction(sum, UInt64),
    docs        SimpleAggregateFunction(sum, UInt64),
    authors     AggregateFunction(uniqCombined(12), UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (subreddit, term, kind, source, hour)
TTL hour + INTERVAL 180 DAY;

CREATE MATERIALIZED VIEW term_hourly_mv TO term_hourly AS
SELECT
    hour,
    subreddit,
    source,
    kind,
    term,
    sum(toUInt64(occurrences)) AS occurrences,
    toUInt64(count()) AS docs,
    uniqCombinedState(12)(author_hash) AS authors
FROM term_events
GROUP BY hour, subreddit, source, kind, term;

-- The long term history, kept forever.
CREATE TABLE term_daily
(
    day         Date,
    subreddit   LowCardinality(String),
    source      LowCardinality(String),
    kind        LowCardinality(String),
    term        String,
    occurrences SimpleAggregateFunction(sum, UInt64),
    docs        SimpleAggregateFunction(sum, UInt64),
    authors     AggregateFunction(uniqCombined(12), UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYear(day)
ORDER BY (subreddit, term, kind, source, day);

CREATE MATERIALIZED VIEW term_daily_mv TO term_daily AS
SELECT
    toDate(hour) AS day,
    subreddit,
    source,
    kind,
    term,
    sum(toUInt64(occurrences)) AS occurrences,
    toUInt64(count()) AS docs,
    uniqCombinedState(12)(author_hash) AS authors
FROM term_events
GROUP BY day, subreddit, source, kind, term;

-- Every request to reddit, for the ingestion health dashboard.
CREATE TABLE polls
(
    ts                  DateTime64(3, 'UTC'),
    feed                LowCardinality(String),
    kind                LowCardinality(String),   -- comments | posts
    background          Bool,
    status              UInt16,                   -- http status, 0 for network errors
    items               UInt16,
    new_items           UInt16,
    gap                 Bool,
    id_span             UInt64,
    latency_ms          UInt32,
    interval_s          Float32,
    rate                Float32,                  -- estimated items per second
    ratelimit_remaining Float32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (feed, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY;

-- The groups from config.yaml, rewritten on every start of the ingester, so dashboards
-- and queries can filter by group.
CREATE TABLE subreddit_groups
(
    group_name String,
    subreddit  String
)
ENGINE = MergeTree
ORDER BY (group_name, subreddit);
