-- What the short-term detector found: every 15 minutes, the top trending terms of every
-- scope (a tracked subreddit "r/name" or a group) and horizon (24h, 6h), with the
-- numbers behind the score and what happened with the alert. Running the detector
-- twice for the same time replaces its rows instead of adding them.
-- IF NOT EXISTS: the ingester and the analyzer both migrate when they start.
CREATE TABLE IF NOT EXISTS trends
(
    horizon            LowCardinality(String),  -- 24h | 6h
    scope              LowCardinality(String),  -- "r/technology" or a group, "tech"
    term               String,
    detected_at        DateTime('UTC'),         -- the time the detector ran "as of"
    scope_type         LowCardinality(String),  -- subreddit | group
    kind               LowCardinality(String),  -- word | phrase | domain | subreddit
    window_start       DateTime('UTC'),
    window_end         DateTime('UTC'),
    mentions           UInt64,                  -- y_W: comments and posts in the window
    total              UInt64,                  -- n_W: all comments and posts in the window
    reference_mentions UInt64,                  -- y_B: the same in the reference period
    reference_total    UInt64,                  -- n_B
    authors            UInt64,                  -- distinct authors in the window
    prior              Float64,                 -- α_w, pseudo-mentions from the r/all sample
    log_odds           Float64,                 -- δ
    ratio              Float64,                 -- exp(δ), "times its usual share"
    z                  Float64,                 -- δ / σ, the score trends are ranked by
    is_new             Bool,                    -- (almost) never mentioned before
    breadth            UInt16,                  -- groups: member subreddits where it trends
    members            UInt16,                  -- groups: member subreddits mentioning it
    subsumed_by        String,                  -- a phrase that explains this burst, or ''
    rank               UInt16,                  -- 1 = highest score in its scope and run
    reference_days     UInt16,                  -- days of history in the reference period
    -- '' (not alert-worthy), sent, failed, capped (daily limit), cooldown, warmup (not
    -- enough history yet), skipped (scope never alerts), muted (run without notifications)
    alert              LowCardinality(String),
    updated_at         DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(detected_at)
ORDER BY (horizon, scope, term, detected_at)
-- runs every 15 minutes add up, keep the details for 90 days and alerts forever
TTL detected_at + INTERVAL 90 DAY DELETE WHERE alert != 'sent';

-- Every message sent to ntfy, also used to send each daily digest only once.
CREATE TABLE IF NOT EXISTS notifications
(
    sent_at DateTime64(3, 'UTC'),
    kind    LowCardinality(String),  -- alert | digest | test
    scope   LowCardinality(String),
    term    String,
    title   String,
    message String,
    ok      Bool,
    error   String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(sent_at)
ORDER BY (kind, sent_at);
