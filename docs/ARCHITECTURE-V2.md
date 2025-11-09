# WGRA v2: Architecture and Plan

Status: proposal · October 2026

## 1. What the system is for

WGRA answers one question: **which words and phrases are gaining or losing
share of the conversation in a given community, relative to their own normal
level?** It answers it on two horizons:

| Horizon | Question | Example | Delivery |
| --- | --- | --- | --- |
| Short term (hours to days) | What suddenly started being talked about? | "`vision pro` is mentioned in 14x more r/technology comments today than its 28-day norm, by 312 different people" | Push alert, daily digest |
| Long term (weeks to months) | What is steadily growing or fading? | "`local llm` grew about 9% per month in r/programming over the last 26 weeks, with no single spike explaining it" | Weekly report, dashboard |

Both work **per subreddit** and **per topic group**, for example
`tech = r/technology + r/programming + r/hardware + r/LocalLLaMA + …`.

The constraints from the original README still hold. Results must be
normalized for activity swings across the day and week, robust against spam,
cheap enough to run on one small server, and within Reddit's free API tier.

### The gap in v1

v1 can tell you how **a word you already picked** is doing. The `analyzer`
takes a word and returns its growth. The real goal is **discovery**: finding
the trending terms you didn't know to ask about. That means scoring every
term in every scope on every run. It's a bulk aggregation problem, and it
drives most of the decisions below.

## 2. Assessment of v1

| Area | v1 | Problem | v2 answer |
| --- | --- | --- | --- |
| Time resolution | One Mongo doc per (subreddit, word, **day**) | Short-term detection needs hours. Same-day spikes aren't visible until tomorrow. | Hourly buckets, rolled up to daily |
| Long tail | A nightly job deletes every count ≤ threshold | Emerging trends **start** in the long tail (3 → 30 → 300). Deleting it removes the early signal and leaves holes the analyzer has to fill with invented values. | Keep everything. Columnar compression makes it cheap. |
| Normalization | A baseline word (`the`, `die`) per subreddit | A proxy for volume that needs per-language config. The analyzer formula was inverted (fixed in Phase 0). | Divide by the exact number of comments in the scope and bucket |
| Spam | Raw occurrences | One comment repeating "foobar" 500 times looks like a trend | Count **comments containing** the term, and require a minimum number of **distinct authors** |
| Terms | Lowercase ASCII unigrams | Misses `vision pro`, `claude code`, `right to repair`. Broke on non-ASCII (`für` → `fr`) and on newlines (fixed in Phase 0). | Unicode unigrams + bigrams + trigrams, domains, `r/` mentions |
| Sources | New comments only, one request stream per subreddit | Posts carry the highest-signal text (titles). One stream per sub wastes the request budget. | Comments **and** posts, using multireddit streams (`r/a+b+c`) |
| Reddit client | snoowrap (unmaintained), password grant | Needed several workarounds just to run (see Phase 0) | Small client of our own around app-only OAuth |
| Storage | MongoDB + Redis | Mongo is a poor fit for "aggregate billions of rows by term and time". Redis is connected but never used. | ClickHouse |
| Analyzer | One word per run, one query per day, recursive | Can't rank all terms | Set-based SQL over all terms, statistics in Python |
| Product | API and browser UI drawn in the diagram, never built. HookNotifier for push. | Nothing to look at | Grafana dashboards + ntfy push |
| Ops | Kubernetes planned, pm2, Node 12 image | Overkill and outdated | One VPS, Docker Compose, GitHub Actions → GHCR |

## 3. Target architecture

```mermaid
flowchart LR
  R[Reddit API<br/>app-only OAuth<br/>100 req/min] --> I

  subgraph VPS [Single VPS · docker compose]
    I[ingest<br/>Python · asyncio<br/>budgeted pollers] -->|raw items| C[(ClickHouse)]
    I -->|one row per comment × distinct term| C
    C -->|materialized views| C
    A[analyze<br/>Python · scheduled jobs] <-->|SQL| C
    G[Grafana<br/>ClickHouse datasource] -->|SQL| C
  end

  A -->|alerts and digests| N[ntfy → phone]
  A -->|explain top trends| L[Claude API<br/>claude-haiku-5-5]
  U((you)) --> G
  N --> U
```

There are three processes and one database, all in one `docker-compose.yml`.

### 3.1 `ingest`

* **Auth:** app-only OAuth (`grant_type=client_credentials`) with the existing
  client ID and secret. No Reddit username or password is needed. The token
  is valid for 24h. Re-authenticate at about 23h, and on a 401.
  **Treat this app as an asset.** Since November 2025, Reddit's Responsible
  Builder Policy requires manual approval for new API apps. Existing apps
  keep working, and this one was verified live on 2026-10-10. Don't delete it
  or create a replacement casually.
* **Streams instead of subreddits.** A stream is one listing URL covering a
  group of subreddits with similar volume: `r/technology+gadgets+hardware/comments`.
  Each returned item carries its own `subreddit`, so attribution is free.
  Low-volume subs get packed together. High-volume subs, and `r/all` as the
  background corpus, get their own stream.
* **Budgeted scheduler.** The free tier allows 1000 requests per 10 minutes
  (the `x-ratelimit-*` headers confirm it). The scheduler spreads that budget
  across streams so that each poll **overlaps** the previous one, which means
  no gaps:
  `interval(stream) ≈ 80 items ÷ observed items-per-second`, bounded by the
  remaining budget. `r/all` gets whatever budget is left and is treated as a
  sample.
* **Measured on 2026-10-10:** the `r/all/comments` listing only reaches back
  about 1–2 seconds. Three polls returned 7, 62 and 0 items, while sitewide
  comment IDs advance at about 60/s (about 5M comments/day). So `r/all` can
  only ever be a sample. A topical multireddit is different: one request for
  `r/technology+programming+news/comments` returned 100 comments spanning
  380s, so polling it every 4–5 minutes captures **everything**. Per-community
  tracking is cheap; only the firehose is out of reach.
* **Gap detection and coverage.** Reddit IDs are base-36 and increase over
  time. If the oldest item in a batch is newer than the newest item from the
  previous poll, there may be a gap. That gets logged to a `coverage` table
  so you can see per stream and hour how complete the data is.
* **Posts too.** Poll `…/new` for submissions (title + selftext) on the same
  streams, at a lower frequency.
* **Cleaning** (in this order): drop `[deleted]`/`[removed]`, AutoModerator,
  known bots and moderator-distinguished comments. Strip quoted lines (`> …`),
  so replies don't count the parent twice. Strip code blocks and markdown
  link targets. Pull out URLs as `domain` terms and `r/xyz` as
  `sub_mention` terms. Drop exact-duplicate bodies posted across subs within
  1h (copypasta).
* **Tokenizing:** Unicode-aware, case-folded, with apostrophes kept inside
  words. Unigrams + bigrams + trigrams. An n-gram may not start or end with a
  stopword (per-language stopword lists), so you get `right to repair` but
  not `of the`. Optional light lemmatization with `simplemma` (multilingual,
  so it covers r/de too): `agents` → `agent`.
* **Output.** One row per (comment, distinct term) goes into a `Null`-engine
  table. Materialized views aggregate those rows, so the raw rows are never
  stored. The raw comment and post text also goes to a table with a **48h
  TTL** (see §7), used for re-tokenizing, examples and explanations.
* **Idempotency.** Persist the last-seen ID per stream so a restart doesn't
  reprocess the last listing. Use `insert_deduplication_token` on batch
  inserts so retries don't double count.

### 3.2 ClickHouse

The sketch below shows the tables (DDL in [Appendix A](#appendix-a-clickhouse-schema-sketch)).

| Table | Engine | Key | Retention | Purpose |
| --- | --- | --- | --- | --- |
| `comments`, `posts` | ReplacingMergeTree | (subreddit, created_at, id) | 48h TTL | Raw text: example comments, LLM context |
| `term_events` | Null | — | not stored | Insert target, feeds the views |
| `term_hourly` | AggregatingMergeTree | (subreddit, kind, term, hour) | 180 days TTL | Short-term detection |
| `term_daily` | AggregatingMergeTree | (subreddit, kind, term, day) | forever | Long-term detection |
| `scope_hourly` | AggregatingMergeTree | (subreddit, hour) | forever | Denominators: comments, tokens, distinct authors |
| `coverage` | MergeTree | (stream, minute) | 90 days | Ingestion health |
| `trends` | ReplacingMergeTree | (horizon, scope, term, detected_at) | forever | Detector output, alert state |

Each term row carries `occurrences` (sum), `docs` (number of comments
containing the term) and `authors` (`uniqCombined` state, a mergeable
HyperLogLog sketch). Distinct-author counts stay correct when you roll up
hours into days or subreddits into groups. Feed the sketch a **keyed hash**
of the author (HMAC with a secret), never the username, so stored values
can't be linked back to Reddit accounts.

**Sizing, rough.** Say 200 tracked subs plus an `r/all` sample, about 2–3M
comments/day:

* `term_hourly` gets about 10M rows/day. Columnar compression should keep
  that in the low hundreds of MB per day.
* `term_daily` is a few GB per year.
* Raw text is about 300 MB at any moment, because of the 48h TTL.

A 4 vCPU / 8 GB / 160 GB VPS should be plenty. Measure this in Phase 1
rather than trusting the estimate.

### 3.3 `analyze`

The same Python package as `ingest`, with a separate entrypoint and an
in-process scheduler:

* every 15 min: short-term burst scoring for all scopes → `trends` → alerts
* daily: long-term scoring on weekly series → `trends` → weekly report on Mondays
* hourly: LLM explanation for newly alerted trends

### 3.4 Grafana

Grafana is provisioned from files in the repo, using the official ClickHouse
datasource. There are three dashboards, and none of them need custom
front-end code:

1. **Trending now:** per scope or group, a top-N table with score, ratio,
   authors and a sparkline, linking to the explorer.
2. **Term explorer:** pick terms and scopes, see the relative-frequency time
   series with an hourly/daily/weekly toggle, plus example comments.
3. **Ingestion health:** requests/min vs budget, items/min per stream,
   coverage, gaps, error rate. A Grafana alert sends to ntfy when ingestion
   stalls.

A custom web UI is only worth building later, if you want to share this
publicly.

### 3.5 Notifications

ntfy replaces HookNotifier. It's open source and free, and you can self-host
it in the same compose file or use ntfy.sh. It has an iOS/Android app and
supports click actions, which can open the Grafana explorer for the term.

There are two notification types:

* **Instant alerts** for very high scores, capped at about 5/day.
* A **daily digest** with the top items per group.

## 4. Trend detection

### 4.1 What to measure

For scope `s` (a subreddit or a group), term `w` and time bucket `t`:

* `y` = number of comments in `s` during `t` that contain `w` (`docs`)
* `n` = number of comments in `s` during `t` (from `scope_hourly`)
* `rate = y / n`, the share of comments mentioning the term
* `a` = number of distinct authors who used `w`, used as a spam guard

This replaces both the baseline word and raw occurrences. Dividing by `n`
removes the activity swings across the day and week exactly, with no
per-language baseline word. Counting comments instead of occurrences limits
any single comment to 1. Requiring a minimum `a` limits any single user or
bot.

You don't need to see every comment. Polling is not biased toward particular
words, so a sample estimates `rate` without bias. A smaller sample only
widens the uncertainty, and the scores below use the actual counts, so they
become less confident on their own when data is thin.

### 4.2 Short term: burst detection

Compare a **window** `W` (last 24h, plus a fast 6h variant) with a
**reference** `B` (the 28 days before `W`). Score every term with the
**weighted log-odds ratio with an informative Dirichlet prior** (Monroe,
Colaresi & Quinn, *Fightin' Words*, 2008). It's the standard approach for
"which words are over-represented in corpus A vs B", and it holds up for rare
and brand-new terms:

```
α_w   = α0 · background_rate(w)        # prior from all scopes, last 90 days
δ_w   = log((y_W + α_w) / (n_W + α0 − y_W − α_w))
      − log((y_B + α_w) / (n_B + α0 − y_B − α_w))
σ²_w  ≈ 1 / (y_W + α_w) + 1 / (y_B + α_w)
z_w   = δ_w / σ_w
```

* **Rank** by `z`, the strength of evidence. **Show** `exp(δ)`, the "x times
  more than usual" figure. **Gate** on `y_W ≥ 10`, `a_W ≥ 5` and
  `exp(δ) ≥ 2`. All thresholds are per-scope config, tuned on real data.
* **New terms:** when `y_B ≈ 0`, the prior keeps the score finite. Flag these
  as `new`, since they're often product or project names.
* **N-gram subsumption:** if `vision pro` is trending, suppress `vision` and
  `pro` when their burst is mostly explained by the bigram.
* **Cooldown:** don't re-alert the same (scope, term) within 72h unless its
  score doubles.
* **Breadth:** for a group, count how many member subs show `z > 3`. A term
  bursting in 6 of 9 tech subs is a bigger story than one sub at `z = 12`.
* **Hour-of-day effects** in topic mix (for example "breakfast" in the
  morning) matter only for the 6h window. For that window, build `B` from
  the same hours of the day across the last 28 days.

### 4.3 Long term: sustained trends

* Aggregate to **weekly** rates. That removes weekday effects and smooths
  noise.
* For every (scope, term) above a volume floor (for example 20 docs/week on
  average), take the last 13, 26 and 52 weeks of `log(rate)` and compute:
  * **Theil–Sen slope**, which is robust to one-off spikes, converted to a
    growth factor per month: `exp(slope × 4.35)`.
  * **Mann–Kendall** test p-value for a monotonic trend, with
    **Benjamini–Hochberg** correction, because you're testing tens of
    thousands of terms at once.
  * **Spike share:** how much of the change comes from the top 1–2 weeks.
    High spike share means "one event", not "trend".
* Classify each term as `emerging` (low base, consistent growth),
  `mainstreaming` (high base, still growing), `fading`, `one-off` or `flat`.
* For speed, do a first pass in SQL (`simpleLinearRegression` over weekly
  log rates for every term) and then run the robust statistics in Python on
  the top few thousand candidates only.
* **History is the bottleneck.** Long-term results need about 8–12 weeks of
  data. Backfilling from historical dumps would shorten that, but it's
  legally grey (§7), so plan around collecting your own history
  (Phase 4).

### 4.4 Scoping by subreddit and topic

```yaml
# config.yaml (replaces config.json)
groups:
  tech:      [technology, programming, hardware, gadgets, LocalLLaMA, MachineLearning, webdev, apple, Android]
  finance:   [investing, stocks, wallstreetbets, personalfinance]
  de:        [de, Finanzen, de_EDV]
subreddits:
  de:        {language: de}
  Finanzen:  {language: de}
background: [all]           # sampled, used for priors and "distinctive terms"
```

* **Group rate:** the macro-average of the member subs' rates by default, so
  r/technology doesn't drown out r/hardware. The pooled rate is available as
  a toggle.
* **Distinctive vocabulary:** run the same log-odds scoring with *group vs.
  background* instead of *now vs. before*. You get the terms that make a
  community what it is, which is useful for picking topic keywords and for
  explaining what a group cares about.
* **Finding subs for a topic:** start from a hand-picked list. Later, suggest
  candidates from subs that show up a lot in `sub_mention` terms within a
  group.

### 4.5 Explaining trends with an LLM

When something alerts:

1. Pull 20–30 example comments and post titles containing the term in the
   window from the raw tables.
2. Send them, together with the other terms trending in the same scope, to
   Claude (`claude-haiku-5-5`, which is cheap and fast).
3. Ask for one or two sentences on *why it's trending*, and for a grouping
   of co-trending terms into one story. For example, `vision`, `pro`,
   `headset` and `apple` become a single story about the headset launch.

Cost stays small because only the handful of daily alerts are sent, never
the stream. Raw text is kept for only 48h (§7). That's enough for
short-term alerts. For long-term trends, fetch fresh examples from Reddit
search when generating the explanation. The explanation goes into the alert and the dashboard.

## 5. Tech stack

| Concern | v1 | v2 | Why |
| --- | --- | --- | --- |
| Language | TypeScript, Node 12 | **Python 3.13, uv** | The analyzer is the core value. Python has the stats/NLP stack (numpy, scipy, polars, simplemma, the Claude SDK). Ingest is simple I/O in either language, so one language for both wins. |
| Reddit client | snoowrap (GitHub repo archived 2024-03, deprecated on npm) | **httpx, about 150 lines of our own** | Only two endpoints plus token. You need exact control of rate-limit headers and gap detection. A maintained fallback exists: asyncpraw 8.0.3 (2026-08), which supports read-only mode. |
| Storage | MongoDB 5 (end of life since 2024-10), Redis | **ClickHouse 26.8 LTS** | Built for "group billions of (time, scope, term) rows". Has materialized views, TTL, HyperLogLog states, about 10x compression. |
| Dashboards | none | **Grafana** + ClickHouse datasource | Dashboards and alerting with zero front-end code |
| Push | HookNotifier (still running) | **ntfy** | Free, open source, self-hostable, click actions. ntfy.sh's free tier allows 250 messages/day. |
| Scheduling | node-schedule | APScheduler in `analyze` | Same idea, in-process |
| Explanations | — | Claude API | Wasn't feasible six years ago |
| Deploy | Kubernetes (planned), pm2 | **Docker Compose on one VPS**, GitHub Actions → GHCR | Right-sized for the job |
| Quality | none | ruff, mypy/pyright, pytest, golden tokenizer tests | — |

Other options considered:

* **Postgres + TimescaleDB:** workable to a few hundred million rows. Ranking
  every term gets slow.
* **DuckDB + Parquet:** excellent for offline work, and the right tool for
  the Phase 4 backfill. But its single-writer model doesn't fit "always
  ingesting while dashboards read".
* **Staying on TypeScript:** viable. The architecture stays the same, only
  the statistics libraries get thinner. Pick it if you'd rather not switch
  languages.

### Repo layout

```
wgra/
  pyproject.toml            # uv
  config.yaml
  src/wgra/
    reddit/                 # client, auth, budget scheduler, streams
    text/                   # cleaning, tokenizer, n-grams, stopwords
    store/                  # clickhouse client, migrations runner
    detect/                 # short_term.py, long_term.py, scoring.py
    notify/                 # ntfy, digest rendering
    explain/                # LLM explanations
    cli.py                  # wgra ingest | analyze | backfill | migrate | trend <term>
  migrations/*.sql
  grafana/provisioning/     # datasource + dashboards as JSON
  tests/
  deploy/docker-compose.yml
```

## 6. Delivery plan

### Phase 0: get v1 running again (done, see the commit with this document)

* App-only OAuth. **No Reddit password needed.** The token is requested
  directly, because snoowrap's own helper sends it without a User-Agent and
  Reddit answers with a 403.
* Listing `limit` set to 100 (it was 100000). The old value made snoowrap
  paginate about 10 requests per poll, roughly 3x over the free budget for
  r/all alone.
* Tokenizer: split on all whitespace, Unicode letters (`für` stays `für`),
  URLs removed.
* Publisher: `Map` instead of an O(n) array scan per word, plus one
  `bulkWrite` per flush instead of one round-trip per word. Added a compound
  index.
* Analyzer: fixed the inverted normalization (it multiplied by the activity
  change instead of dividing). It now uses the configured baseline per
  subreddit, and there's a CLI: `node dist/index.js <word> [subreddit] [days]`.
* Infra: the Mongo volume was mounted at `/db/data`, so nothing persisted.
  It's now `/data/db`. The init script now works with `mongosh` (needed for
  Mongo ≥ 6). The Dockerfile is on Node 22 + pinned pnpm 7. `.env` is no
  longer baked into the image. `config.json` is mounted in prod.

### Phase 1: foundations (about 1 week)

* uv project, CI (ruff, type-check, pytest), migrations runner, compose with
  ClickHouse + Grafana.
* Reddit client: token handling, budgeted scheduler, streams for comments
  and posts, gap detection, coverage table.
* Cleaning and tokenizer with golden tests: umlauts, apostrophes, URLs,
  quotes, code blocks, n-gram stopword boundaries, bots.
* Tables and materialized views from Appendix A. Grafana "Ingestion health"
  dashboard.
* **Done when:** it runs 72h unattended on the VPS, ≥ 99% of polls succeed,
  coverage ≥ 95% for every non-`r/all` stream, and the dashboard shows hourly
  volume per sub.

### Phase 2: short-term detection (about 1 week)

* Scoring from §4.2 (SQL aggregation, scoring in Python), `trends` table,
  cooldowns, n-gram subsumption.
* ntfy alerts and daily digest. "Trending now" and "Term explorer"
  dashboards.
* Replay harness: re-run detection over stored history with different
  thresholds, so tuning doesn't require waiting.
* **Done when:** about 10 or fewer alerts per day per group at default
  settings, and in a one-week manual review you judge at least 70% of them
  "real".

### Phase 3: groups and explanations (about 1 week)

* Group config, macro-averaged group rates, breadth score, distinctive
  vocabulary.
* LLM explanations and story clustering in alerts and on the dashboard.

### Phase 4: long-term detection and backfill (code in about 1 week; useful once history exists)

* Weekly rollups, Theil–Sen, Mann–Kendall, FDR, classification. Monday
  report per group.
* Optional, private use only: backfill chosen subs from the Arctic Shift
  monthly dumps (available through 2026-08). Process them with DuckDB and
  write `term_daily` rows marked `source = 'backfill'`. Read the caveats in
  §7 first.

### Phase 5: hardening and cutover

* GHCR images, deploy over SSH (`docker compose pull && up -d`), nightly
  ClickHouse `BACKUP` of `term_daily`, `scope_hourly` and `trends` to object
  storage.
* After v2 has 2 weeks of data, stop v1 and drop Mongo and Redis. The v1
  daily counts measure occurrences, not comments, so they aren't comparable.
  Archive them; don't merge them.

## 7. Risks and open questions

Facts below were checked against primary sources on 2026-10-10.

* **Reddit API access.**
  * The free tier is 100 queries/minute per OAuth client, averaged over 10
    minutes. Unauthenticated access is blocked entirely.
  * New apps need manual approval (Responsible Builder Policy, November
    2025), and commercial use needs a contract. Your existing app keeps
    working, so keep the project non-commercial unless you get approval.
* **Deletion obligations.** This is what shapes the design:
  * Reddit's Data API wiki requires removing stored content once it's deleted
    on Reddit, and recommends deleting stored user data within 48 hours.
  * The Data API Terms (revised 2026-07-20) require deleting data your use
    case doesn't need.
  * So: raw text gets a 48h TTL, authors are stored only as keyed hashes
    inside sketches, and long-term storage holds nothing but aggregate
    counts. Whether aggregate word counts are fully outside these rules is a
    grey area, but it's the most defensible design.
* **Research restriction.** Reddit's policy says research using Reddit data
  collected outside its Reddit for Researchers program (academics only)
  violates the policy. A personal trend tool isn't clearly "research", but
  publishing results makes the question harder to avoid.
* **Historical data for backfill.**
  * Pushshift is moderator-only.
  * Arctic Shift has a near-real-time API (no uptime guarantee; slow in
    tests) and monthly dumps through 2026-08.
  * The multi-year bundles have disappeared from Academic Torrents (reason
    unverified). The dumps carry no license.
  * Use only for private exploration, if at all.
* **Coordinated campaigns or bots** can look like trends. Distinct authors
  helps. Account age would help more but costs extra API calls, so it's left
  out for now.
* **r/all is a sample.** It's good for priors and for "what's big
  everywhere". It can't support per-sub conclusions for subs you don't track
  explicitly.
* **Unverified:** the maximum number of subreddits in one `a+b+c` URL. Reddit
  documents no limit for ad-hoc combinations; the practical ceiling is
  probably URL length. Test this in Phase 1, starting at about 50 per stream.

Open questions:

1. Which communities and groups matter first?
2. Is this for you alone (alerts) or eventually public (a site)? That decides
   whether a custom UI and the licensing questions matter.
3. Is Python acceptable, or should v2 stay TypeScript?

## Appendix A: ClickHouse schema sketch

```sql
CREATE TABLE comments
(
    id          String,
    subreddit   LowCardinality(String),
    author      String,
    created_at  DateTime,
    link_id     String,
    body        String,
    token_count UInt32
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMMDD(created_at)
ORDER BY (subreddit, created_at, id)
TTL created_at + INTERVAL 48 HOUR;

-- one row per (comment, distinct term), never stored
CREATE TABLE term_events
(
    hour        DateTime,
    subreddit   LowCardinality(String),
    kind        LowCardinality(String),   -- word | phrase | domain | sub_mention
    term        String,
    author_hash UInt64,
    occurrences UInt16
)
ENGINE = Null;

CREATE TABLE term_hourly
(
    hour        DateTime,
    subreddit   LowCardinality(String),
    kind        LowCardinality(String),
    term        String,
    occurrences SimpleAggregateFunction(sum, UInt64),
    docs        SimpleAggregateFunction(sum, UInt64),
    authors     AggregateFunction(uniqCombined, UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (subreddit, kind, term, hour)
TTL hour + INTERVAL 180 DAY;

CREATE MATERIALIZED VIEW term_hourly_mv TO term_hourly AS
SELECT hour, subreddit, kind, term,
       sum(occurrences)              AS occurrences,
       count()                       AS docs,
       uniqCombinedState(author_hash) AS authors
FROM term_events
GROUP BY hour, subreddit, kind, term;

-- term_daily: same shape with `day Date`, fed by an MV on term_events,
-- no TTL, so the long-term history doesn't depend on term_hourly's TTL.

CREATE TABLE scope_hourly
(
    hour      DateTime,
    subreddit LowCardinality(String),
    docs      SimpleAggregateFunction(sum, UInt64),
    tokens    SimpleAggregateFunction(sum, UInt64),
    authors   AggregateFunction(uniqCombined, UInt64)
)
ENGINE = AggregatingMergeTree
ORDER BY (subreddit, hour);

CREATE MATERIALIZED VIEW scope_hourly_mv TO scope_hourly AS
SELECT toStartOfHour(created_at) AS hour, subreddit,
       count() AS docs, sum(token_count) AS tokens,
       uniqCombinedState(cityHash64(author)) AS authors
FROM comments
GROUP BY hour, subreddit;
```

## Appendix B: short-term candidate query

```sql
-- window = last 24h, reference = 28 days before that, one scope
WITH now() - INTERVAL 24 HOUR AS w_start,
     w_start - INTERVAL 28 DAY AS b_start
SELECT
    kind, term,
    sumIf(docs, hour >= w_start)                    AS y_w,
    sumIf(docs, hour <  w_start)                    AS y_b,
    uniqCombinedMergeIf(authors, hour >= w_start)   AS authors_w
FROM term_hourly
WHERE subreddit = {scope:String} AND hour >= b_start
GROUP BY kind, term
HAVING y_w >= 10 AND authors_w >= 5;
-- n_w / n_b come from scope_hourly; α_w from a 90-day background table.
-- The log-odds z-score (§4.2) is computed in Python on this candidate set.
```
