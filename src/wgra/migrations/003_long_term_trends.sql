-- What the long-term detector found: every day, for every scope (a tracked subreddit
-- "r/name" or a group) and window (13, 26, 52 weeks), the terms that grow, fade or had a
-- one-off burst over the complete weeks before the run, with the statistics behind the
-- category. Flat terms aren't stored.
--
-- Separate from `trends`: burst rows and long-term rows share no statistics, long-term
-- rows are kept forever (they're few, and the history of what was emerging when is the
-- point), and the short-term queries (digests, alerts, Trending now) read `trends`
-- without telling horizons apart.
--
-- The results only change when a week completes. Rows are keyed by that week, so the
-- daily runs of a week replace each other, like re-running phase 2's detector for the
-- same time does.
CREATE TABLE IF NOT EXISTS long_term_trends
(
    horizon      LowCardinality(String),  -- 13w | 26w | 52w
    scope        LowCardinality(String),  -- "r/technology" or a group, "tech"
    term         String,
    week         Date,                    -- the Monday the analyzed weeks end before
    detected_at  DateTime('UTC'),         -- the time the detector ran "as of"
    scope_type   LowCardinality(String),  -- subreddit | group
    kind         LowCardinality(String),  -- word | phrase | domain | subreddit
    category     LowCardinality(String),  -- emerging | mainstreaming | fading | one-off
    window_start Date,                    -- the Monday of the first analyzed week
    weeks        UInt16,                  -- weeks with data in the window
    members      UInt16,                  -- subreddits averaged (groups), or 1
    mentions     UInt64,                  -- comments and posts mentioning it in the window
    total        UInt64,                  -- all comments and posts in the window
    growth       Float64,                 -- per month, exp(Theil–Sen slope × 4.35)
    slope        Float64,                 -- Theil–Sen slope of the log share, per week
    ols_growth   Float64,                 -- per month, the least squares first pass
    start_share  Float64,                 -- the Theil–Sen line at the first week, per 1,000
    end_share    Float64,                 -- and at the last week
    change       Float64,                 -- second half vs first half, per month like growth
    peak         Float64,                 -- the highest week's share, times the median week's
    mk_s         Int32,                   -- Mann–Kendall S: pairs of weeks up minus down
    mk_z         Float64,
    p_value      Float64,                 -- Mann–Kendall, two-sided
    q_value      Float64,                 -- Benjamini–Hochberg, over all terms the run tested
    spike_share  Float64,                 -- share of the change from the 2 highest weeks
    weekly       Array(Float64),          -- share per week per 1,000, oldest first
    rank         UInt16,                  -- 1 = strongest in its scope, window and category
    updated_at   DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYear(week)
ORDER BY (horizon, scope, term, week);
