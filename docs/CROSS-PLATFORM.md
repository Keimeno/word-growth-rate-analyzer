# Cross-platform spread map: plan

**Status: planned, not started.** A reference for building it later. Nothing below exists
yet except what it builds on.

Today the analyzer learns which subreddits pick up a term before others
([ARCHITECTURE.md §4.6](ARCHITECTURE.md#46-lead-lag-early-warning)). This plan makes
collection source-agnostic, adds Hacker News, Bluesky, GitHub and app-store reviews next to
Reddit, and runs the same lead–lag over all of them, to say things like "starts on HN,
reaches r/programming in 18 hours and Wikipedia in 4 days". Two things come out of it:

* **The spread map.** For each story, the path it took across platforms and the time
  between the steps. In aggregate, which platform picks up which topics first, and how long
  each takes to reach the next.
* **Earlier warning.** A term rising on HN or among GitHub stars becomes a forecast for
  Reddit and for the mainstream: the forecasts of §4.6, with more leaders.

Nobody shows this today. It's for personal use for now; a commercial product comes later.
When it does, the stack can run with Reddit switched off, but that eases the licensing
problem less than hoped: of the new sources only Bluesky clearly allows a product, GitHub
probably does with care, and Hacker News's terms forbid commercial use unless YC allows it
(§5).

Phase 1 is planned in detail in §8: Reddit behind a source interface, with the same results
as today.

**It costs nothing to run**, like the rest of v2. Every new source is free; GitHub needs a
free token.

## 1. Where things stand (checked 2026-10-31)

* **Nothing is deployed.** The stack runs locally and collects again since 2026-10-31:
  51 hours of Reddit (2026-10-10 to 10-12, and today), 1.1 million comments and posts, 95%
  of them from the r/all sample, in about 270 MB. So there's no migration: the schema is
  changed in place and the local database recreated (§8.3).
* **Reddit is built into three layers:**
  * Storage: the `subreddit` column of `items`, `scope_hourly`, `term_hourly`, `term_daily`
    and `subreddit_groups`. It's in the sorting key of each, and ClickHouse can't rename key
    columns. `source` means comment or post, `id` is a Reddit fullname.
  * Ingest: `reddit/` (the client and the listing parser), `ingest/feeds.py` (multireddit
    scheduling), `ingest/run.py` (restart state from base-36 ids) and the skip rules in
    `ingest/pipeline.py` (AutoModerator, distinguished, stickied).
  * Analysis: scopes are `r/<name>` and groups (`detect/short_term.py`), the prior of every
    score is the r/all sample (`SAMPLE_SCOPE`), and in lead–lag only subreddits can lead
    (`Network` in `leadlag/edges.py`).

  In all, `subreddit` appears in 32 Python and SQL files, 68 times in the dashboard builder.
* **The churn radar's phases 1 and 2 are in** (`1d8972f`, `c9fc201`, 2026-10-31): Reddit
  search, comment trees and a `_search` scope, in `ingest/`, `reddit/`, `radar/` and the
  config. It's more Reddit-only collection, and it moves into `sources/reddit/` with the
  rest.
* **The math is already platform-neutral.** Every score compares a scope's share of its own
  documents with its own past, so a channel with 12,000 items a day and one with millions
  are scored the same way. Wikipedia pageviews are already compared with onsets
  (`leadlag/wikipedia.py`), but as a one-off check, not as a follower.
* **GitHub's public event stream is no longer usable.** Since October 2025 GitHub trims event
  payloads: a star carries only the repo's id and name. GH Archive, built from that stream,
  fell from 156,094 events in one hour of June 2025 to 4,423 in the same hour of
  2026-10-29 (stars: 5,016 to 306), with no word from its maintainer. The trending page has
  no API and may not be scraped (§5). GitHub has to be watched repo by repo (§2.3).

## 2. Design

### 2.1 Platforms, channels, scopes

* A **platform** is where data comes from: reddit, hn, bluesky, github, appstore. External
  daily series can only follow: wikipedia, later google.
* A **channel** is what's collected and counted, what a subreddit is today. Its id carries
  its platform, so ids can't clash and need no mapping:

  | Channel | What |
  | --- | --- |
  | `r/programming` | a tracked subreddit, as today |
  | `r/all` | the r/all sample, today `_sample` and the scope "sample" |
  | `hn` | all of Hacker News, stories and comments |
  | `bsky` | a hashed sample of all Bluesky posts; per language (`bsky/de`) optionally |
  | `gh/stars` | every star of the watched repos, as a document about the starred repo |
  | `ios/<app>` | App Store reviews of one app |
  | `wiki` | daily pageviews of the Wikipedia articles that event terms name; follows only |

* Every platform has one **platform channel**, the whole platform: its node on the platform
  map and the prior of its channels' scores. They are `r/all`, `hn`, `bsky`, `gh/stars`, and
  the group `ios` of all tracked apps.
* **Groups** list channel ids (`r/technology`, not `technology`) and may mix platforms. A
  group pools its channels' counts, so a group with `bsky` in it is mostly Bluesky, and the
  config check warns about groups that mix platforms. The spread map uses channels and
  platform channels; mixed groups are for topics (an event's topic is the group it trended
  in most in its first hour, §4.6). The implicit group `tracked` becomes `reddit`: every
  tracked subreddit. Nothing pools across platforms unless a group says so.
* A **scope** is a channel id or a group name, and a group can't be named like a channel.
  Code never tells them apart by a prefix: it looks the name up in `channels` or uses the
  stored scope type.

### 2.2 Storage

Nothing is deployed, so the schema files are edited in place and the local database is
recreated, without migrations, for as long as that holds. Phase 1 renames `subreddit` to
`channel` and `source` to `doc_type` everywhere, and adds `channels` (§8.3). Later phases
add their tables the same way:

* `ingest_cursors` (phase 2): where each source resumes after a restart, such as an HN
  item id or a Jetstream time. Reddit keeps restoring from `items`.
* `gh_repos` (phase 2): the watched repos, why each is watched (linked, searched,
  configured), since when, its description and topics, and how far back its stars are
  fetched.
* `follower_type` gains `external` for `wiki` (phase 2).

Once something is deployed with history worth keeping, schema changes go back to being
migrations.

### 2.3 Collection: one interface, a module per source

* `wgra/sources/base.py` defines an `Item` (id, platform, channel, doc_type, author,
  created_at, text, url, lang, and `skip`: why the source drops it, such as bot, moderation
  or deleted) and a `Source` that runs forever and hands items and poll rows to the shared
  pipeline.
* Each source owns its schedule, its request budget and its restart state. Today's
  `reddit/`, `ingest/feeds.py` and the restart logic move into `sources/reddit/` unchanged,
  and the Reddit-only skip rules move with them.
* The `Processor` stays shared: author hash, copypasta filter, terms, intents. The author is
  hashed together with its platform (`hn:pg`, `bsky:did:plc:…`). The same name on two
  platforms counts as two people, and identities are never linked across platforms.
* One process per source: `wgra ingest --source hn`, one Compose service each. A Bluesky
  reconnect or a GitHub backfill can't stall Reddit's polling, and Bluesky gets a core of
  its own. `wgra ingest` without `--source` runs every enabled source in one process, for a
  laptop.
* `REDDIT_*` are only required while Reddit is enabled. With `platforms.reddit.enabled:
  false` the stack runs without Reddit (§5).

Per source:

* **Hacker News.** The official API: no key, no published rate limit, items readable about
  a minute after they're written. Poll `maxitem` every 30 seconds and fetch each new id,
  about 12,000 a day. Stories (title and text) and comments; dead and deleted items are
  dropped. Backfill through the Algolia search API by date (1,000 items a request, 10,000
  requests an hour): 120 days, about 1.4 million items, in well under an hour. HN has its
  reference period on the first day.
* **A new term kind `repo`** (`ollama/ollama`), from github.com links on every platform and
  from star events. It's the cleanest key across platforms: the same repo is the same
  string everywhere, without the ambiguity of words. Detected and ranked like `domain`.
* **GitHub: watched repos.** The global stream is gone (§1), so the ingester watches repos:
  * Found three ways: `repo` terms mentioned on any other platform (the HN backfill seeds
    the list with months of them), the search API for young repos gaining stars (created
    in the last 30 days, sorted by stars, every hour: the trending page's job), and a list
    in `config.yaml`.
  * For each, the GraphQL API returns every star with its time (`stargazers` ordered by
    `starredAt`), and the description and topics. A newly watched repo's stars are fetched
    back to the backfill horizon, so its history doesn't start the day it was found; later
    polls fetch only new stars. Hourly polls of 1,000 repos fit easily in a free token's
    5,000 points an hour; a repo with tens of thousands of stars in the horizon takes a few
    hundred to backfill.
  * Each star is a `gh/stars` document: the repo's name split into words, `owner/name` as a
    `repo` term, its description and topics. The stargazer is the hashed author. The
    denominator is every star of every watched repo in the hour.
  * Backfilled stars go into past hours, so past denominators include repos found later:
    every hour is measured against the repos watched now, consistently.
* **Bluesky.** Jetstream v2 (`jetstream.us-east.bsky.network`), the JSON firehose, posts
  only, about a second behind. The network writes about 4.4 million posts a day (measured;
  3.9 million on average in 2025, per Bluesky's transparency report), about 4 GB a day of
  JSON. A hash of the post's id keeps `sample_rate` of them, 10% to start, about 440,000 a
  day. Unlike Reddit's r/all, that's an unbiased sample. The language comes from the post's
  `langs`. Bluesky's developer guidelines require a way to delete what a user asks to have
  deleted: deletes arrive in the stream, and a sampled post's are deleted from `items`
  (batched lightweight deletes) while its counts stay, like a Reddit comment deleted after
  it was counted. Jetstream resumes up to 36 hours back, longer replay needs an API key, so
  there's no backfill: the reference period fills in 4 weeks, as Reddit's did.
* **App Store.** Apple's customer review RSS feed, still working: the newest 500 reviews per
  app and country (10 pages of 50), no key. The newest review in it was 34 hours old when
  checked, so reviews arrive late. Polled every 6 hours for a watchlist of apps in
  `config.yaml`. Reviews are where complaints land: a follower for the intents and the
  churn radar ([CHURN-RADAR.md](CHURN-RADAR.md)) more than a leader. Its terms are the
  least clear of the sources (§5). Google Play has no way to read other companies' reviews
  except scraping, which its terms forbid, so it's left out.
* **Wikipedia** becomes a follower: `wiki` onsets (the first day with 100 views and 3× the
  median of the 28 days before, as today) join the events' onsets, at day resolution.
* **Google Trends** only through Google's official API, still an alpha by application. It
  has daily data at best, up to 2 days ago, with 1,800 days of history: good enough for "in
  4 days", too late for warnings. Never scraped. Until access comes, Wikipedia is the free
  mainstream end.

### 2.4 Analysis

* **Scopes** come from `channels` and `channel_groups`: every channel, every group, every
  platform channel. Short-term and long-term detection and intents run on them unchanged.
* **Priors** come from each scope's platform channel: an HN term is damped by HN's usual
  vocabulary, not Reddit's. A group that mixes platforms uses the mixture, weighted by the
  group's documents from each. `score_arrays` takes a prior per series instead of one.
* `detect.sources` becomes `doc_types`, by default every type of every platform.
* **Thresholds per platform**, between today's defaults and those per scope: HN and single
  apps are small, so 5 mentions by 3 people there, as `r/de_EDV` has today.
* **Onsets** for every channel, every group and every group without each of its members,
  as today with more columns.
* **Leaders** are every channel (today: subreddits only). **Followers** are every other
  channel, every group (without the leader if it's a member) and `wiki`. Platform channels
  are channels, so `hn → r/all` ("HN leads Reddit as a whole") is an edge like any other.
* With HN, two Bluesky channels and GitHub, about 50 leaders × 57 followers per topic
  instead of 45 × 52 today (with the churn radar's `pkm` group). Benjamini–Hochberg absorbs
  that, at some cost in power.

### 2.5 Volume bias: big platforms look like leaders

An onset is the first hour the evidence is strong enough, and evidence grows with volume.
On the same relative rise, a big channel crosses sooner than a small one, so it looks like a
leader for being big. §7 of the architecture lists this bias between subreddits. Between
platforms the volumes differ by a factor of 30 or more (HN's 12,000 items a day, Bluesky's
440,000 at a 10% sample), so it can't stay a footnote. Three counters:

1. **Rise onsets for the map.** Once a scope has crossed, look back for where the rise
   started: the first hour of the run before the crossing in which every 6-hour window's
   share, with the prior, stays above twice the reference share. The map's lags come from
   rise onsets. The detectable onset of today stays for forecasts, which can only use what
   was provable at the time.
2. **Thinning.** Before the map says "A leads B", the bigger channel's hourly counts are
   thinned binomially to the smaller one's volume, both onsets are recomputed 20 times, and
   the lead share under thinning is reported. An edge whose lead disappears is marked
   volume-driven and left off the map. The onset code is vectorized already, so this is a
   few numpy lines.
3. **No lead without its numbers.** Every lag on the map shows n, the hit rate and the lead
   share, as the edges do today.

How late an item is read doesn't bias the lags: onsets use the time it was written. It does
delay forecasts. GitHub's stars are polled hourly, app reviews show up in the feed a day or
more late, and Google Trends 2 days late.

### 2.6 What it shows

* **Cascades.** Per event, its onsets in order with the time since the first. For example:
  "llama 4: hn 0 h → gh/stars 5 h → r/LocalLLaMA 9 h → r/all 31 h → bsky 40 h → wiki 4 d".
  In `wgra spread --term "llama 4"`, and as a table on the new dashboard.
* **First movers.** Per topic, the share of events that started on each platform (the
  earliest rise onset), with n: "of 212 tech events in the last 90 days, 41% started on HN".
* **The platform map.** For each pair of platforms: the median lag (and IQR), the hit rate
  and the lead share, as a Grafana node graph with the lags on the edges. The strongest
  channel edges below it.
* **Common paths.** The most frequent orders of platforms per topic (hn → r/all → wiki).
* **Forecasts across platforms.** Today's forecasts with the new leaders: "rising on HN for
  3 hours, r/programming expected in about 18 hours (55%, 40–68%)".
* **The weekly report** gets a short "where it started" section: the week's biggest events
  and the platform each started on.

The numbers in these examples are made up; they show the form.

### 2.7 config.yaml

```yaml
platforms:
  reddit:
    enabled: true
    requests_per_minute: 90
    background: {subreddit: all, requests_per_minute: 20}
  hn:
    enabled: true
    backfill_days: 120
  github:
    enabled: true
    backfill_days: 120               # how far back a newly watched repo's stars are fetched
    search_young_repos: true         # created in the last 30 days, gaining stars
    max_watched: 1000
    repos: [ollama/ollama]           # always watched, besides those found
  bluesky:
    enabled: true
    sample_rate: 0.1                 # share of posts kept, by a hash of the post
    language_channels: [de]          # bsky/de besides bsky
  appstore:
    enabled: false
    countries: [us, de]
    every_hours: 6
    apps:                            # a name, and the id from the App Store url
      example-app: 1234567890

groups:
  tech: [r/technology, r/programming, r/localllama, hn, gh/stars]

detect:
  platforms:                         # per platform, only what differs
    hn: {min_mentions: 5, min_authors: 3}
```

Today's `background:` section and the Reddit keys of `ingest:` move under
`platforms.reddit` in phase 1 (§8.6), without compatibility for the old keys: `config.yaml`
changes with the code.

## 3. Delivery plan

### Phase 0: accounts (an hour)

* For personal use: a GitHub token (phase 2), and a contact email in the user agents.
  Apply for the Google Trends API alpha if it's wanted; it costs only the application.
* The written permissions of §5 wait until it becomes a product (gate 3).

### Phase 1: the source-agnostic core, Reddit only (about 3 days)

* Detailed in §8. Names and structure change, results don't: storage, analysis and
  dashboards stop knowing Reddit, and Reddit moves behind a source interface.
* **Done when:** a seeded benchmark history gives the same trends, onsets and edges before
  and after, apart from the names (§8.7), and a day of live collection on the recreated
  database looks right.

### Phase 2: Hacker News and GitHub, with history (about 5 days)

* What phase 1 leaves out because it changes results (§8.9): priors per platform and their
  mixture for mixed groups, any channel as a leader, thresholds per platform, a Compose
  service per source, `ingest_cursors`.
* HN with its Algolia backfill, the `repo` kind, GitHub's watched repos and their star
  backfill, `wiki` as a follower.
* Run the detector over the backfilled weeks and store the trends, so they become events.
  `wgra replay` already runs it as of past hours; it gets a `--store` option.
* **Done when:** 120 days of HN and of the watched repos' stars are in, and each source's
  daily volume, CPU and disk are measured and written into §4.
* Both backfill, so HN, GitHub and Wikipedia have months of history on the first day.
  Their edges can be learned in the first week, long before Reddit has enough history.

### Phase 3: the spread map (about 4 days)

* Rise onsets, thinning, first movers, cascades, common paths, `wgra spread`, the Spread map
  dashboard, the weekly report's section, and `wgra replay --forecast` across platforms.
* **Done when:** gate 1 (§6) can be answered from the HN, GitHub and Wikipedia history.

### Phase 4: Bluesky (about 2 days)

* The Jetstream source, sampling, deletions, its cursor. Raise `sample_rate` as far as the
  disk allows.
* **Done when:** a week runs without gaps on the ingestion dashboard, and its disk per day
  is known.

### Phase 5: app reviews (about 2 days), with the churn radar

* The App Store source and its watchlist, built once the churn radar's watchlists exist
  (CHURN-RADAR.md §2.1), and only if its terms are acceptable for the use (§5).

About 3 weeks of work in all. Then waiting: edges involving Reddit need 4–6 weeks of
history counted from 2026-10-31, those involving Bluesky 4–6 weeks from phase 4.

## 4. Cost

| Item | Cost |
| --- | --- |
| Sources | Free: the HN API and Algolia, Jetstream, a GitHub token, Apple's RSS feed, Wikimedia. |
| Disk | About 250 MB per million documents at today's ratio (1.1 million in 270 MB), less once ClickHouse has merged the daily rows. HN adds about 3 MB a day. Bluesky at 10% adds about 110 MB a day, about what Reddit's r/all sample brought in on 2026-10-11 (575,000 documents); at 100%, about 1.1 GB. Set the sample rate by the disk. |
| Bandwidth | Jetstream sends all posts, about 4 GB a day, whatever the sample rate: sampling happens here. The rest is small. |
| CPU | Bluesky's 4.4 million posts a day are about 50 a second to parse, a share of them to tokenize. A core is plenty; a fraction of one for each other source. |
| Machine | The same one. |

## 5. Terms (checked 2026-10-31)

For personal use none of this blocks anything; the obligations that apply anyway are
Bluesky's deletions and polite rate limits. It matters once this becomes a product. Read
from the primary sources on 2026-10-31: a reading for planning, not legal advice; a product
needs a lawyer's reading (gate 3).

| Source | Commercial use | Conditions and obligations | Primary source |
| --- | --- | --- | --- |
| Hacker News (API, Algolia) | Not without permission | YC's terms of use cover all its subdomains and forbid scraping and commercial use unless expressly authorized. The API's MIT license covers its code, not the data. Algolia's API page gives only the rate limit. | ycombinator.com/legal, github.com/HackerNews/API, hn.algolia.com/api |
| Bluesky (Jetstream) | Allowed, with conditions | A way to delete what a user asks to have deleted; no spam; a public contact email. Nothing on analytics or AI training. A draft proposal ("user intents") would let users opt out of bulk datasets; not binding, worth honoring if it lands. No SLA for the public instances. | bsky.network/docs/developer-guidelines, bsky.network/docs/jetstream |
| GitHub (REST and GraphQL) | Probably, with conditions; a gray area | API terms: no spam, no selling personal data, no shared tokens. The Acceptable Use Policies allow scraped data only for open-access research and archiving and want written permission for commercial exploitation; their wording may cover API data too. The trending page may not be scraped. GH Archive has no data license. | docs.github.com/en/site-policy (acceptable use, terms of service §H) |
| App Store (RSS) | Unclear, risky | The feed has no terms of its own. Apple's website terms (2009) forbid robots on associated sites; unclear whether that covers the feed. Reviews carry author names. | apple.com/legal/internet-services/terms/site.html |
| Google Play | No | No way to read other companies' reviews except scraping, which conflicts with robots.txt, Google's terms and the Play terms (collecting other users' account names). | play.google.com/about/play-terms, play.google.com/robots.txt |
| Google Trends API | Unknown | Alpha by application; quotas, pricing and terms unpublished. Scraping it (pytrends, now archived) is unsanctioned. | developers.google.com/search/apis/trends |
| Wikimedia | Free, as today | Not re-checked; see ARCHITECTURE.md §4.6. | |
| Reddit | Needs a contract | Free tier non-commercial; commercial use needs a separate agreement (ARCHITECTURE.md §7, checked 2026-10-10; Reddit's pages blocked today's check). | redditinc.com/policies/data-api-terms |

So a product without Reddit is possible today on Bluesky, Wikipedia and, with care, GitHub.
With Hacker News, the source the examples lean on, it needs YC's written permission.

## 6. Gates

1. **Is there a map (end of phase 3, from the backfilled history).** Continue if HN, GitHub
   and Wikipedia show at least 3 directed edges between platforms that survive thinning,
   each with n ≥ 10, or first movers that differ clearly from each platform's share of the
   volume. If not, the thesis is weak where it should be strongest: stop before Bluesky.
2. **Forecasts across platforms (6 weeks after phase 4).** `wgra replay --forecast` across
   platforms: calibrated within 10 points per bin, a lift of at least 2 over the follower's
   base rate, and a median warning of at least 12 hours. Until then they're hints on the
   dashboard, without alerts.
3. **Data rights (when it becomes a product, before anyone outside sees it).** Written
   answers from YC and GitHub, or
   those sources off for the product; App Store reviews only after a lawyer's reading;
   Reddit licensed or switched off.

## 7. Risks and open questions

* **Volume bias** (§2.5) is the main risk to what the map claims. Thinning and rise onsets
  are the counters, and gate 1 is measured after them.
* **GitHub only sees watched repos.** Repos are found mostly through links on other
  platforms, so events about repos nobody links are missing, and the HN backfill seeds the
  list. Timing stays honest, since every watched repo's stars are fetched with their times
  from before it was found. A star removed later is missing from the history.
* **The same word means different things on different platforms:** "rust" is a language on
  HN and a game in r/gaming, "swift" a language and a singer. Topics separate some of it,
  and `repo` and `domain` terms are exact. Cascades show each term's top channels, so a
  reader can tell.
* **Coordinated launches.** A company posting on HN, Reddit and Bluesky in the same hour
  shows up as simultaneous onsets; one posting on HN first and on Reddit the next day looks
  like an edge. Distinct authors help within a platform. Across platforms the same person
  can't be recognized, by design.
* **Stars aren't conversation.** Star farming exists; one star per account and repo, and
  the distinct-author gate, limit it.
* **Audiences and time zones differ.** 24-hour windows absorb the daily cycle, but a German
  story may rightly start in r/de.
* **Bluesky's sample** keeps shares unbiased, but author counts shrink with it, so
  `min_authors` is set per platform. The public Jetstream instances come without a
  guarantee, and Jetstream was rewritten in 2026 (v2, August); it can be self-hosted.
* **Sources change under us.** GitHub's event stream went from complete to useless in a
  year. Each source keeps its poll rows, and the ingestion dashboard shows its volume per
  day, so a collapse shows up as a drop, not as a quiet bias.
* **Personal data.** Usernames on every platform are personal data. The design keeps what
  it keeps for Reddit: hashed authors, raw text for 48 hours, aggregates otherwise. The
  legal basis for a product is part of gate 3.
* Open: whether the product is the map (descriptive, sellable as a report soon) or the
  forecasts (which need gate 2), and which topics to start with (proposed: tech, where HN
  and GitHub are strongest).

## 8. Phase 1 in detail: Reddit behind a source interface

The same system with new names and a new structure, and the same results. Afterwards only
these know Reddit: `sources/reddit/`, the churn radar's search and comment trees (`radar/`
and the `r/_search` channel), `wgra suggest-subreddits` (it finds untracked subreddits in
r/all items), and the `subreddit` term kind (mentions of r/x, which HN and Bluesky have
too). Everything that changes results waits for phase 2 (§8.9), so phase 1 can be checked
by comparing numbers (§8.7).

### 8.1 Before starting

* The churn radar's phases 1 and 2 are committed (`1d8972f`, `c9fc201`). Phase 1 touches
  most of the files they did (`cli.py`, `config.yaml`, `radar/`, `text/intents.py`, the
  dashboard builder, tests), so it runs while no other work edits the checkout.
* The reference run of §8.7, on the code before phase 1.

### 8.2 Names

| Today | Phase 1 |
| --- | --- |
| column `subreddit` | `channel` |
| column `source` (comment, post) | `doc_type` |
| `technology` stored, `r/technology` as a scope | `r/technology` in both |
| `_sample` stored, `sample` as a scope and a group | the channel `r/all` |
| `_search` stored | the channel `r/_search` (subreddit names can't start with `_`) |
| the group `tracked` | `reddit`: every tracked subreddit |
| scope type `subreddit` | `channel` |
| follower type `subreddit`, `sample` | `channel`, `platform` |
| `subreddit_groups` | `channel_groups`, and the new `channels` |
| `permalink` (relative) | `url` (absolute) |
| `polls.background` | `polls.sample` |
| `detect.sources` | `detect.doc_types`, empty for every type |
| `wiki_leads.reddit_onset`, `reddit_scope` | `first_onset`, `first_scope` |
| the Grafana variable `subreddit` | `channel` |
| `SAMPLE_SCOPE`, `SAMPLE_GROUP`, `SEARCH_SCOPE`, `subreddit_scope()` | gone from the shared code; the Reddit source has `r/all` and `r/_search` |

Channel ids are lowercase, like subreddit names today. A group name that equals a channel id
is a config error. Wherever the code tells a channel from a group by its `r/` prefix today
(`notify/messages.py`, `query.py`, the dashboards), it uses `channels` or the stored scope
type instead.

### 8.3 Storage

* Migrations 001–004 are edited in place, and 005 (the `intents` column) is folded into
  001.
* `items`: id, platform, channel, doc_type, created_at, author_hash, text, url, lang,
  token_count, intents, ingested_at. Sorted by (channel, created_at, id), deleted after 48
  hours. `lang` is stored so `wgra backfill-intents` no longer needs to parse the subreddit
  out of the permalink.
* `scope_hourly`, `term_events`, `term_hourly`, `term_daily`: `channel` and `doc_type`,
  otherwise unchanged, with the same materialized views.
* `channels` (channel, platform, language, analyzed, background) and `channel_groups`
  (group_name, channel), rewritten from `config.yaml` on every ingester start like
  `subreddit_groups` today. `analyzed`: the detectors see it (not `r/_search`).
  `background`: the platform channel, the prior of its platform's scopes (`r/all`).
* `polls`: plus `platform`, `background` renamed to `sample`. The other columns already fit
  any polled source (`id_span` is how far the platform's id sequence advanced).
* `trends`, `long_term_trends`, `lead_lag_events`, `propagation_edges`, `forecasts`: the
  new values of §8.2, no new columns. `wiki_leads`: the renamed columns.
* Recreating the local database: `docker compose down`, `docker volume rm
  wgra_clickhouse_data`, `docker compose up -d --build`. What was collected since
  2026-10-31 is lost, a few days at most, and history restarts. Alert cooldowns restart
  with `trends`. If those days are worth keeping, a one-off `INSERT … SELECT` from the old
  tables into a second database carries them over. It's a command for that day, not a
  migration.

### 8.4 Collection

```python
@dataclass(frozen=True, slots=True)
class Item:
    id: str                    # unique within its platform: "t1_abc"
    platform: str              # "reddit"
    channel: str               # where its counts go: "r/technology", "r/all", "r/_search"
    doc_type: str              # comment | post
    author: str                # as the platform writes it
    created_at: datetime
    text: str
    url: str
    lang: str                  # the channel's language, unless the item says otherwise
    skip: str | None = None    # why the source drops it: bot, moderation, deleted


class Sink(Protocol):
    """The shared part: dedup, terms, intents, buffered writes."""

    client: Client                 # for restart state and lookups, like seed_state today
    def add(self, item: Item) -> bool: ...   # False when skipped
    def add_poll(self, poll: Poll) -> None: ...


class Source(Protocol):
    platform: str
    async def run(self, sink: Sink, stop: asyncio.Event) -> None: ...
```

| Today | Phase 1 |
| --- | --- |
| `reddit/client.py`, `reddit/models.py` | `sources/reddit/client.py`, `models.py`; `RedditItem.to_item()` |
| `ingest/feeds.py` | `sources/reddit/feeds.py` |
| `ingest/search.py` | `sources/reddit/search.py` |
| `Ingester` in `ingest/run.py`: polls, comment trees, `seed_state`, `usable_subreddits`, the report | `RedditSource` in `sources/reddit/source.py` |
| `Config.scope()`: a tracked subreddit's own channel, otherwise the sample; search results in `_search` | `RedditSource` decides the channel |
| `is_bot`, distinguished, stickied, `[deleted]` / `[removed]` in `Processor.skip_reason` | `RedditSource` sets `skip` |
| `MAX_ITEM_AGE`, the seen-ids set across feeds | `RedditSource` (later sources backfill on purpose) |
| `REDDIT_*` in `Env` | read by `RedditSource` when Reddit is enabled; `Env.from_environ(require_reddit)` goes away |

What stays shared: `ingest/pipeline.py` (the `Processor`: copypasta filter, terms, intents,
the author hash), `ingest/writer.py`, `ingest/backfill.py`, and `ingest/run.py`, which
writes `channels` and `channel_groups`, starts every enabled source with one `Sink`, and
reports. The author hash takes `platform:author`, so every hash changes once, which the
recreated database absorbs. `max_ngram` and whether intents are extracted come from the
item's channel (background channels: 2-grams, `intents.sample`). `wgra ingest` gets
`--source`, defaulting to every enabled platform; one Compose service stays as today.

### 8.5 Analysis

| Module | Change |
| --- | --- |
| `detect/short_term.py` | `Scope(name, type, channels)`; `load_scopes` reads `channels` (analyzed) and `channel_groups`; `subreddit_scope()` goes; the prior's channel is the platform's background from `channels`, not a constant. One platform, one prior, as today. |
| `detect/long_term.py` | Renames. A channel's first data counts any doc type (today `source = 'comment'`). |
| `detect/run.py`, `replay.py`, `alerts.py` | A group's members are channel ids already, no prefix mapping. |
| `detect/scoring.py` | Docstrings: "the platform's background" for "the r/all sample". |
| `leadlag/onsets.py` | Matrix columns are the analyzed channels, the background among them instead of appended; series as today. |
| `leadlag/edges.py` | `Network` from channels and groups; leaders are the analyzed channels that aren't a background, as today; follower types of §8.2. |
| `leadlag/events.py` | Topics compare channel ids, no `f"r/{member}"`. |
| `leadlag/wikipedia.py` | The renamed columns; "first onset" for "reddit onset". |
| `leadlag/suggest.py` | Stays Reddit-only; reads the subreddit from `url`. |
| `notify/messages.py` | Scope type instead of the `r/` prefix; a background channel's label from the config ("reddit-wide (the r/all sample)"). |
| `query.py`, `cli.py` | `--scope` takes a group or a channel id; `wgra status` lists channels with their platform. |
| `radar/candidates.py` | Buckets by the watchlist's group, `reddit`, `r/all` and `r/_search`. |
| `text/` | Unchanged; the `subreddit` kind is text. |

### 8.6 Config, dashboards, docs, tests

* `config.yaml`:
  ```yaml
  platforms:
    reddit:
      enabled: true
      requests_per_minute: 90          # of the free tier's 100 per client id
      max_subreddits_per_feed: 25
      min_poll_interval: 2
      max_comment_poll_interval: 300
      max_post_poll_interval: 900
      sample:                          # the channel r/all
        requests_per_minute: 20
        max_ngram: 2
  ingest:
    max_ngram: 3
  groups:
    tech: [r/technology, r/programming, …]
  languages:
    de: [r/de, r/finanzen, r/de_edv]
  notify:
    skip_scopes: [r/all]
  ```
  `Config.channels()` derives every channel with its platform, language, `analyzed` and
  `background`. A bare name in a group, or a group named like a channel, is an error that
  says what to write instead.
* `grafana/build_dashboards.py`: the variable `channel`, `channel_groups`, `url` for links
  ("Open" instead of "Open on reddit"), `r/all` for `_sample`, links from the scope type,
  the ingestion dashboard per platform (the r/all coverage panel filtered to Reddit). The
  JSON regenerated.
* README, ARCHITECTURE.md (§3.1, §3.2, §4.4, appendix A) and CHURN-RADAR.md in the new
  names.
* `bench/*.py`: renames (they write `term_hourly` and `scope_hourly` themselves).
* Tests: renames throughout, and new ones: a fake source through the `Sink` into
  ClickHouse; `RedditSource` choosing `r/x`, `r/all` and `r/_search` and setting `skip`;
  the config errors; a scope lookup that doesn't rely on prefixes.

### 8.7 How we know nothing changed

1. **Before**, on the code before phase 1: `bench/lead_lag.py` (seed 1) generates its
   history into a bench database. Dump a `wgra replay --csv` over its last 3 days, and the
   events with onsets and the edges of `run backfill`.
2. **After**, the same on the phase 1 code, on the same day (the generator's history ends
   today).
3. Compare after mapping the names of §8.2: the same rows with the same numbers. Long-term
   trends are covered by their integration tests, which run unchanged apart from names.
4. `uv run pytest`, `ruff check`, `ruff format --check` and `mypy` pass.
5. Recreate the local database (§8.3), run a day, and check `wgra status`, the ingestion
   dashboard and Trending now.

### 8.8 Order of work

Each step leaves the tests green and is committed on `develop`.

1. **Config** (half a day): `platforms.reddit`, channel ids in groups and languages,
   `Config.channels()`, the errors, their tests.
2. **Schema and analysis** (a day and a half): §8.3, §8.5 and their tests. Mostly
   mechanical, the biggest diff.
3. **Sources** (half a day): `Item`, `Sink`, `Source`; Reddit moved into `sources/reddit/`;
   the shared `Processor`.
4. **Dashboards, CLI, docs, bench** (half a day).
5. **Check and switch** (§8.7): compare, recreate the database, a day of collection.

### 8.9 Left for phase 2

Each changes results, so each comes with the platform that needs it, where it can be
tested:

* priors per platform, the mixture for groups that mix platforms, and a prior per series
  in `score_arrays`
* every channel as a leader, the backgrounds included (`r/all → hn` needs it)
* thresholds per platform (`detect.platforms`)
* `ingest_cursors`, and a Compose service per source
* rise onsets and thinning come in phase 3
