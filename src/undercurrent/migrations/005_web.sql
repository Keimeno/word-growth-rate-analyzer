-- What the web dashboard needs on top (docs/WEB-DASHBOARD.md §6.6, §7.1).

-- A term's scored runs across every scope (the term page): trends is ordered by scope first,
-- so finding one term in 90 days would read the whole term column. A few MB.
ALTER TABLE trends ADD INDEX IF NOT EXISTS term_bloom term TYPE bloom_filter(0.01) GRANULARITY 4;
ALTER TABLE trends MATERIALIZE INDEX term_bloom;

-- The search of the command palette: every term that ever trended, and the 200,000 most
-- mentioned of the last 90 days, with kind, mentions and when last seen. Under a million
-- rows, so a prefix answers in milliseconds. Kept by the refreshable views below; a row is
-- replaced by its newest version.
CREATE TABLE IF NOT EXISTS term_catalog
(
    kind       LowCardinality(String),
    term       String,
    mentions   UInt64,           -- the most it had: in a scored run, or in 90 days
    last_seen  DateTime('UTC'),
    updated_at DateTime('UTC') DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (term, kind);

-- Every hour: the terms that trended, cheap (one column of trends)
CREATE MATERIALIZED VIEW IF NOT EXISTS term_catalog_trended
REFRESH EVERY 1 HOUR APPEND TO term_catalog
AS SELECT kind, term, max(mentions) AS mentions, max(detected_at) AS last_seen,
          now() AS updated_at
FROM trends
GROUP BY kind, term;

-- Once a day at a quiet hour: the most mentioned terms of 90 days (about 270 million rows
-- of term_daily at production scale, 10–20 s)
CREATE MATERIALIZED VIEW IF NOT EXISTS term_catalog_mentioned
REFRESH EVERY 1 DAY OFFSET 3 HOUR APPEND TO term_catalog
AS SELECT kind, term, sum(docs) AS mentions, toDateTime(max(day), 'UTC') AS last_seen,
          now() AS updated_at
FROM term_daily
WHERE day > today() - 90
GROUP BY kind, term
ORDER BY mentions DESC
LIMIT 200000;
