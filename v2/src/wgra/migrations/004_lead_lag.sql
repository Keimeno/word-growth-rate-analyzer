-- Lead–lag early warning (docs/ARCHITECTURE-V2.md §4.6): which subreddits pick up terms
-- before other scopes, and forecasts of which current bursts will reach them.
-- IF NOT EXISTS: the ingester and the analyzer both migrate when they start.

-- An event: a term trending somewhere (in `trends`, not subsumed, z >= event_min_z), and
-- every scope's onset for it, the first hour the scope's share of comments and posts
-- mentioning the term crossed the onset gates. Kept forever (unlike `trends`, 90 days):
-- they're what the edges are learned from. An event's onsets are recomputed until its
-- span is over (`closed`), every rewrite replaces the row.
CREATE TABLE IF NOT EXISTS lead_lag_events
(
    kind          LowCardinality(String),
    term          String,
    start         DateTime('UTC'),          -- the event's first trend
    last_seen     DateTime('UTC'),          -- its latest trend
    topic         LowCardinality(String),   -- the configured group it trended in most, or ''
    -- the scopes it trended in, with their highest score
    scopes        Map(LowCardinality(String), Float32),
    -- scope: "r/name", a group, or "sample" (reddit-wide). without: a group measured
    -- without one of its subreddits ("r/name"), to see whether the rest of the group follows
    -- that subreddit; '' otherwise. at: the hour the window ending with it crossed.
    onsets        Array(Tuple(scope String, without String, at DateTime('UTC'),
                              mentions UInt32, ratio Float32, z Float32)),
    onsets_until  DateTime('UTC'),          -- the data the onsets were computed from ends here
    closed        Bool,                     -- the span is over, the onsets are final
    updated_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(start)
ORDER BY (kind, term, start);

-- Leader subreddit -> follower scope, learned every day from the events of the training
-- period. Only pairs that pass the edge gates are stored. A follower group the leader
-- belongs to is measured without the leader's own mentions (without_leader).
CREATE TABLE IF NOT EXISTS propagation_edges
(
    day              Date,                    -- the UTC day of the run, rows are kept per day
    computed_at      DateTime('UTC'),
    topic            LowCardinality(String),  -- 'all', or the group the events trended in
    leader           LowCardinality(String),  -- "r/name"
    follower         LowCardinality(String),  -- "r/name", a group, or "sample"
    follower_type    LowCardinality(String),  -- subreddit | group | sample
    without_leader   Bool,
    leader_onsets    UInt32,                  -- the leader's onsets in the training events
    events           UInt32,                  -- n: those the follower hadn't started before
    hits             UInt32,                  -- of them, followed within max_lag_days
    hit_rate         Float64,                 -- hits / events
    base_rate        Float64,                 -- share of all events with a follower onset
    probability      Float64,                 -- hit rate shrunk to the base rate (Beta mean)
    probability_low  Float64,                 -- and its interval
    probability_high Float64,
    lift             Float64,                 -- probability / base rate
    p_value          Float64,                 -- one-sided binomial test of hits vs base rate
    q_value          Float64,                 -- Benjamini–Hochberg over all pairs tested
    lag_median       Float64,                 -- hours from the leader's onset to the follower's
    lag_q25          Float64,
    lag_q75          Float64,
    lags             Array(Float32),          -- every hit's lag in hours, sorted
    training_start   DateTime('UTC'),
    training_events  UInt32,                  -- events in the training period (all topics)
    updated_at       DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (day, topic, leader, follower)
TTL day + INTERVAL 180 DAY;

-- A leader's burst its follower hasn't picked up yet, with the probability that it will
-- within max_lag_days. The probability is the one at creation, adjusted for the time since
-- the leader's onset; later runs only resolve the outcome.
CREATE TABLE IF NOT EXISTS forecasts
(
    kind              LowCardinality(String),
    term              String,
    event_start       DateTime('UTC'),
    follower          LowCardinality(String),
    leader            LowCardinality(String),
    follower_type     LowCardinality(String),
    without_leader    Bool,                    -- a group of the leader's, measured without it
    topic             LowCardinality(String),  -- the edge's topic
    created_at        DateTime('UTC'),
    leader_onset      DateTime('UTC'),
    expected_at       DateTime('UTC'),         -- leader onset + the edge's median lag
    due_by            DateTime('UTC'),         -- leader onset + max_lag_days
    probability       Float64,
    probability_low   Float64,
    probability_high  Float64,
    base_rate         Float64,
    lift              Float64,
    edge_events       UInt32,
    edge_hits         UInt32,
    lag_q25           Float64,                 -- hours, the edge's
    lag_median        Float64,
    lag_q75           Float64,
    outcome           LowCardinality(String),  -- pending | hit | miss
    follower_onset    Nullable(DateTime('UTC')),
    resolved_at       Nullable(DateTime('UTC')),
    -- '' (no alert), sent, failed, capped, muted (a run without notifications), off
    alert             LowCardinality(String),
    updated_at        DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (kind, term, event_start, follower, leader);

-- Optional (wikipedia.enabled): Wikipedia articles of event terms and their daily
-- pageviews, cached so each is fetched once, and when interest started there.
CREATE TABLE IF NOT EXISTS wiki_articles
(
    project    LowCardinality(String),
    term       String,
    article    String,   -- '' when no article (missing or a disambiguation page)
    checked_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(checked_at)
ORDER BY (project, term);

CREATE TABLE IF NOT EXISTS wiki_pageviews
(
    project    LowCardinality(String),
    article    String,
    day        Date,
    views      UInt64,
    fetched_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (project, article, day);

CREATE TABLE IF NOT EXISTS wiki_leads
(
    kind          LowCardinality(String),
    term          String,
    start         DateTime('UTC'),
    project       LowCardinality(String),
    article       String,
    reddit_onset  DateTime('UTC'),           -- the event's first onset in any scope
    reddit_scope  LowCardinality(String),
    wiki_onset    Nullable(Date),            -- the first day of elevated views, if any
    lead_days     Nullable(Float64),         -- wiki onset (start of day) − reddit onset
    updated_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (kind, term, start, project);
