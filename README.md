<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/readme-header-dark.svg">
  <img src="docs/brand/readme-header.svg" alt="Undercurrent" width="640">
</picture>

# Undercurrent

**Early signals in online conversation.** What's rising, where it starts, where it spreads
next, and why people switch products.

Formerly Word Growth Rate Analyzer (WGRA). The repository keeps its name.

Know on Monday what the rest of the internet reads about on Thursday. Stories start small:
a Show HN, a subreddit of a few thousand people, a thread of complaints nobody outside it
reads. Undercurrent follows the places where things start, notices the hour a word, a
product or a complaint breaks from its usual share, and learns which communities pick
things up before others. Then it tells you what will spread, where, roughly when, and how
sure it is. It reads why, too: who switches from what to what, what they complain about,
and what they wish existed.

It runs on a laptop, on free and open source software, with no paid APIs and no language
model. Reddit is the first source; Hacker News, GitHub, Bluesky and app reviews come next,
on the same core.

[A week with Undercurrent](#a-week-with-undercurrent) ·
[Try it on the demo database](#try-it-on-the-demo-database) · [Run it](#run-it) ·
[How it works](#how-it-works) · [Sources](#sources-reddit-today-the-rest-next) ·
[Architecture](docs/ARCHITECTURE.md)

## A week with Undercurrent

*An illustration: Driftwood, the dates and every number below are made up. Each block is
what Undercurrent prints today, run through its own formatters. The last part needs the
sources that are [planned](#sources-reddit-today-the-rest-next).*

Driftwood, an open source notes app that syncs without a server, is posted to Hacker News
on Monday morning. Nobody you follow has mentioned it.

**Monday 18:15 UTC, your phone.**

> **driftwood · r/selfhosted**
>
> New: 87 comments and posts by 61 people in the last 24h, barely mentioned in the 28 days
> before.
>
> Score 11.4 · `Open` · `Trending now` · `Pro mode`

**The same minute, where it goes next.** From the last 180 days, Undercurrent has learned
that terms rising in r/selfhosted usually reach r/homelab within a day, and sometimes the
note-taking communities and the rest of reddit after that. It forecasts each, with an 80%
interval, against a base rate of 9% (r/homelab), 7% (pkm) and 6% (all of reddit) for any
trending term:

```text
$ uv run undercurrent forecasts --pending
forecasts of the last 7 days: 3 pending, 38 resolved, 26 came true (68%)

    created       term        leader   follower         chance     expected          due  outcome  alert
-----------  ---------  ------------  ---------  -------------  -----------  -----------  -------  -----
03-08 18:15  driftwood  r/selfhosted  r/homelab  70% (56%–80%)  03-09 13:00  03-15 18:00  pending    off
03-08 18:15  driftwood  r/selfhosted        pkm  44% (30%–59%)  03-09 22:00  03-15 18:00  pending    off
03-08 18:15  driftwood  r/selfhosted      r/all  31% (18%–46%)  03-10 17:00  03-15 18:00  pending    off
```

**Tuesday 11:00**, r/homelab picks it up, two hours before the expected time. **Tuesday
22:00**, the note-taking group, on the hour. **Wednesday 20:00**, all of reddit, 50 hours
after your phone buzzed. All three come true this time. Not all do, and the first line
keeps the record.

**Meanwhile, why.** In the note-taking communities people aren't only talking about
Driftwood, they're moving to it, and the switches say from what:

```text
$ uv run undercurrent intents --scope pkm --kind switch --days 2
Switches in pkm, 2027-03-09 to 2027-03-10 vs the 2 days before: 31 flows, 118 mentions in 61,240 comments and posts

           from → to  mentions  authors  per 10k  before  change  trending  last 48h
--------------------  --------  -------  -------  ------  ------  --------  --------
  notion → driftwood        41       39     6.69       0             z 9.8        41
obsidian → driftwood        23       22     3.76       0             z 7.1        23
   notion → obsidian        14       14     2.29      12    1.2x                  14
evernote → driftwood         9        9     1.47       0             z 4.2         9
   evernote → notion         5        5     0.82       4    1.3x                   5
```

And the reason is trending too: `need: sync without a server`, asked for by 19 people in two
days against 3 in the two days before.

Nobody told Undercurrent to look for Driftwood. Every 15 minutes it scores every word and
phrase in every community it follows against that community's own past; this one broke
out, and the rest followed from what it had learned by itself. By Wednesday evening, when
Driftwood reached the rest of reddit, you'd had two days' notice, the odds that it would
get there and when, the three apps it was taking users from, and what those users had been
asking for.

**With Hacker News, GitHub and Bluesky connected**, the same story starts nine hours
earlier, and the spread map tells it as a path, the hours counted from the first platform
that took it up:

```text
driftwood: hn 0 h → gh/stars 4 h → r/selfhosted 9 h → r/homelab 26 h → pkm 37 h → r/all 59 h → bsky 66 h
```

Hacker News becomes a leader with a record of its own, so the first forecast goes out on
Monday morning, before any subreddit has moved.

## What you get

* **What's rising, with the evidence.** Every 15 minutes, every word, phrase, linked site
  and intent in every community is compared with its own past. A trend comes with how many
  times its usual share, how many comments, how many people, in how many channels, and how
  strong the evidence is, in words ("very strong", the statistic on hover).
  [Trends and alerts](#trends-and-alerts)
* **Where it goes next.** Undercurrent learns which communities pick up terms before which
  others, and how long they take, then forecasts which of today's bursts will spread, where
  and when, with an interval and the base rate beside it. Every forecast is graded when it
  resolves. [Early warning](#early-warning)
* **Why people mention things.** Switches (`notion → obsidian`), switches considered,
  alternatives sought, complaints, and needs ("is there an app that …"), counted like
  words, so they trend, emerge and spread like words. [Intents](#intents)
* **What's changing slowly.** Terms emerging, going mainstream or fading over 13, 26 and 52
  weeks, with growth per month and a test for a steady trend, so a one-week spike doesn't
  pass for a movement. [Long-term trends](#long-term-trends)
* **Who's leaving which product, for what.** The churn radar: per product and its
  competitors, the flows in and out and the reasons. [Churn radar](#churn-radar)
* **On your phone and in a dashboard.** Alerts, a daily digest and a weekly report through
  ntfy. A web dashboard where every term, community, story, leader → follower pair and
  product has a page of its own, one click from the comments behind it, with Grafana as the
  pro mode. [Run it](#run-it)

## Why the numbers hold up

* **It says how sure it is.** A trend needs enough mentions, enough different people and
  twice its usual share, and its score weighs the evidence. Forecasts carry an interval and
  the base rate they beat. Counts below 10 stay counts ("9 of 14").
* **It checks itself.** `undercurrent replay` reruns the detector and the forecasts over
  stored history, using only what was known at the time, and reports precision, recall,
  warning time and calibration: do 60% forecasts come true 60% of the time. The planned
  [forecast ledger](docs/FORECAST-LEDGER.md) publishes every forecast the moment it's made,
  timestamped through OpenTimestamps, so none can be backdated or quietly dropped.
* **One loud account can't make a trend.** A comment counts once per term however often it
  repeats it, and the people behind a term are counted beside its mentions.
* **Small communities count.** Every channel is compared with its own past, and a group's
  long-term share is the average of its channels', so a big subreddit doesn't drown out the
  small ones.
* **It says where it falls short.** Intents put precision before recall, and their measured
  precision is published below, including where it misses the target.
* **It keeps little.** Authors are stored only as a keyed hash, raw text is deleted after
  48 hours, and what's kept are counts.

## Sources: Reddit today, the rest next

Things rarely start where they end up. A model is on Hacker News and GitHub before
r/LocalLLaMA, on r/LocalLLaMA before r/technology, and on Bluesky and Wikipedia after that.
Undercurrent's core is built for it: storage, detection, dashboards and alerts count
**channels**, not subreddits, and every score compares a channel with its own past, so one
with 12,000 items a day and one with millions are scored the same way. A new platform is a
module in `src/undercurrent/sources/` (an `Item`, a `Sink`, a `Source`), like
`sources/reddit/`, and everything after it works unchanged.

| Platform | Channels | What it adds | Status |
| --- | --- | --- | --- |
| Reddit | `r/<name>` per tracked subreddit, `r/all` for a sample of the rest | Communities by topic, product subreddits, the reaction to everything | Running |
| Hacker News | `hn` | Where developer tools, models and launches often surface first; 120 days of history on the first day | Planned, phase 2 |
| GitHub | `gh/stars` | Every star of the watched repos, and young repos gaining them | Planned, phase 2 |
| Wikipedia | `wiki` | Daily pageviews: when mainstream interest arrives. Follows, never leads | A check today (`undercurrent wikipedia`), a follower in phase 2 |
| Bluesky | `bsky`, `bsky/de` | A sample of every post, by language | Planned, phase 4 |
| App Store | `ios/<app>` | Reviews of the apps on the churn radar's watchlists | Planned, phase 5 |

More than one platform makes three things possible:

* **The spread map.** For every story, the path it took across platforms and the hours
  between the steps. Per topic, which platform usually moves first, the common paths, and
  the lag between each pair.
* **Earlier warning.** A term rising on Hacker News or among GitHub stars becomes a
  forecast for Reddit and the mainstream before any subreddit has moved. Both come with
  months of history, so their edges can be learned in the first week.
* **Fair comparisons.** A big platform crosses sooner just for being big. Before the map
  says one platform leads another, the bigger one's counts are thinned to the smaller one's
  volume and the lead is tested again; a lead that disappears is left off.

Every new source is free: the HN API and Algolia, Bluesky's Jetstream, a GitHub token,
Apple's RSS feed, Wikimedia. The plan, the costs, and each platform's terms for personal and
commercial use are in [docs/CROSS-PLATFORM.md](docs/CROSS-PLATFORM.md).

## Where it stands

| Part | State |
| --- | --- |
| Collection from Reddit, short-term trends and alerts | Collecting locally since 2026-11-01 15:07 UTC, on a fresh database. Alerts after 3 days of history, the full 28-day reference after 4 weeks |
| [Intents](#intents) | Collecting since 2026-11-01. 50–79% precise per kind on 40 hours of October data against a target of 80%; stricter rules added since, not yet measured |
| [Early warning](#early-warning) | Built. The first edges between about 2026-11-29 and 2026-12-13 |
| [Long-term trends](#long-term-trends) | Built. 13-week results from Monday 2027-02-01, 26-week ones from 2027-05-03 |
| Web dashboard | Built 2026-11-01 ([docs/WEB-DASHBOARD.md](docs/WEB-DASHBOARD.md)) |
| [Churn radar](#churn-radar) | Phases 1 and 2 collecting, the weekly report planned ([docs/CHURN-RADAR.md](docs/CHURN-RADAR.md)) |
| [More sources](#sources-reddit-today-the-rest-next) | Phase 1, the source-agnostic core, built; Hacker News, GitHub, the spread map, Bluesky and app reviews planned |
| Public forecast ledger | Planned ([docs/FORECAST-LEDGER.md](docs/FORECAST-LEDGER.md)) |

Long-term trends and the early warning learn from history, so collecting should start as
early as possible. Until there's enough of it, the
[demo database](#try-it-on-the-demo-database) shows every page with planted stories.

## How it works

![Undercurrent architecture](docs/architecture.png)

The diagram is generated from [docs/architecture.html](docs/architecture.html), the command
to render it is at the top of that file.

1. **Collect.** The ingester polls each platform within its free API budget: the tracked
   subreddits completely, each as often as its volume needs, and a sample of r/all as the
   usual vocabulary. Every comment and post becomes terms (words, 2–3 word phrases, linked
   domains, mentioned subreddits) and intents, counted per hour, channel and term in
   ClickHouse.
2. **Detect.** Every 15 minutes the analyzer compares every term's share in every channel
   and group with its own past and scores the evidence. Once a day it looks for long-term
   trends over 13, 26 and 52 weeks.
3. **Learn and forecast.** Every term that trends becomes an event, with the hour each
   channel and group took it up. From 180 days of events the analyzer learns which channels
   lead which, and after every run it forecasts where today's trends go next.
4. **Tell you.** Alerts, digests and weekly reports go to your phone through ntfy. The web
   dashboard and Grafana show everything, every number one click from the comments behind
   it.

This is version 2, in Python and ClickHouse. Version 1 (TypeScript, MongoDB and Redis) was
replaced on 2026-10-31 and is in the git history up to commit `eef466c`. The design, the
statistics and the roadmap are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), the look and
the voice in [docs/BRAND.md](docs/BRAND.md).

## Cost

Everything runs on free, open source software: ClickHouse, Grafana OSS, ntfy, Python.
Reddit's API is used within its free tier (100 requests per minute, non-commercial use).
No paid APIs. The only cost is the machine it runs on, locally that's your own computer.

## Try it on the demo database

Live history takes weeks to build; the small demo database takes about a minute and a half,
and no Reddit account. `bench/demo.py` writes a deterministic history with planted stories
into a ClickHouse of its own, then runs the real detectors, the lead–lag layer and the alert
rules over it (nothing is sent). With `--small`, the tech and note-taking groups: a new
model name spreading from r/LocalLLaMA to r/singularity, a coordinated launch, a Notion
outage with the complaints, alternatives and switches that follow, an Evernote price hike,
terms emerging and fading over months, and a gap in collection.

Requires Docker, [uv](https://docs.astral.sh/uv/), Node 26 and pnpm 12. Start a ClickHouse
for it, never the live one:

```bash
docker run -d --name undercurrent-dev-bench-clickhouse --cpus 4 --memory 8g \
    -p 127.0.0.1:3617:8123 -e CLICKHOUSE_USER=undercurrent -e CLICKHOUSE_PASSWORD=bench \
    -v "$PWD/clickhouse/undercurrent.xml:/etc/clickhouse-server/config.d/undercurrent.xml:ro" \
    clickhouse/clickhouse-server:26.8
```

```bash
export CLICKHOUSE_PORT=3617 CLICKHOUSE_USER=undercurrent CLICKHOUSE_PASSWORD=bench
```

```bash
uv run python bench/demo.py seed --database undercurrent_demo --small
```

Build the page once, then serve it with the clock stopped where the history ends, Sunday
2026-11-01 12:00 UTC:

```bash
cd web && pnpm install && pnpm build && cd ..
```

```bash
UNDERCURRENT_NOW=2026-11-01T12:00:00Z CLICKHOUSE_DB=undercurrent_demo uv run undercurrent web
```

Open <http://localhost:3610>. Without `--small`, every group of [config.yaml](config.yaml)
and four months of hourly history, which takes several minutes more.

## Run it

Requires Docker. Works the same on a laptop and on a server.

1. Create `.env` from the example and fill it in:

   ```bash
   cp .env.example .env
   ```

   * `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` of a Reddit "script" app. No Reddit
     username or password needed, and only while `platforms.reddit` is enabled.
   * `AUTHOR_HASH_KEY`, `CLICKHOUSE_PASSWORD`, `WEB_CLICKHOUSE_PASSWORD` and
     `GRAFANA_ADMIN_PASSWORD`: generate each with `openssl rand -hex 32`. Never change
     `AUTHOR_HASH_KEY` afterwards. `WEB_CLICKHOUSE_PASSWORD` is the web dashboard's own
     ClickHouse user, which can only read (and keep its pins and saved views).

2. Choose subreddits and groups in `config.yaml`. A group lists channels: a subreddit is
   written `r/technology`.

3. Start ClickHouse, Grafana, the web dashboard, ntfy, the ingester and the analyzer:

   ```bash
   docker compose up -d --build
   ```

4. Open the web dashboard at <http://localhost:3610>
   ([docs/WEB-DASHBOARD.md](docs/WEB-DASHBOARD.md)). Its pages are Trending (with a Quick
   look and what-if gates), Long-term, Why people switch, Early warning (the spread map,
   arrivals, the forecasts' record), Explore, Alerts, Pinned and Collection. Every term,
   channel, story, leader → follower pair and product has a page of its own, one click
   from wherever it appears:
   * **A term's page**, the page an alert opens: its share over time with the runs where
     it trended, the alerts sent and the onsets marked; why it's trending (the parts of
     its score and the gates, recomputed with the detector's own code); where it's
     discussed and the order its channels took it up; the stories it was part of; the
     terms mentioned with it; its rhythm by hour of week and over a year; the comments
     behind it. A plain click on a term opens it in a side panel instead.
   * **A story's page** replays how it spread, hour by hour; a pair's page says in words
     how often and how fast the follower picks up the leader's terms.
   * Words instead of statistics' names (a q-value is "very strong", the number on hover),
     counts below 10 stay counts, every chart has its table (focus it, press `t`) and
     CSV, PNG and SVG exports.
   * `⌘K` or `/` searches pages, scopes and terms, saves the view under a name, and shows
     the dashboard as of a past date (type `2026-10-30 12:00`). `?` lists the shortcuts.
   * It updates itself when the analyzer runs, and a new alert shows as a notice. Pinned
     terms come first on Trending and are the same on every device.

   Every view is a link, and "Pro mode" opens the same view in Grafana. Set `WEB_PASSWORD`
   in `.env` to ask for a password.

   Grafana stays as the pro mode, with every panel and setting: open
   <http://localhost:3608>, log in as `admin` with `GRAFANA_ADMIN_PASSWORD`.
   The dashboards are in the Undercurrent folder:
   * **Trending now**: what the analyzer found, per group and its channels: score,
     times the usual share, mentions, authors, breadth, a sparkline of the last week,
     and the alerts. Click a term to explore it.
   * **Long-term trends**: per group and its channels, the emerging, mainstreaming,
     fading and one-off terms of the last 13, 26 or 52 weeks, with growth per month,
     significance and the weekly share as a sparkline.
   * **Early warning**: which channels lead which (lead time, hit rate, lift, sample
     size, as a table and a graph), recent cascades, the current forecasts and how past
     forecasts turned out.
   * **Intent radar**: the top switching flows (x → y) with the flow the other way and a
     daily sparkline, rising alternatives sought, complaints and switches considered, the
     top needs per group, and the comments behind each of them from the last 48 hours.
   * **Term explorer**: how often terms are mentioned over time, where, and recent
     examples. Per hour, day or week, and for groups pooled or as the average of the
     channels' shares.
   * **Rising (preview)**: a simpler first look at what's mentioned more than usual.
   * **Ingestion**: is the ingester healthy and complete, per platform.

   Every dashboard picks a group or a single channel: `reddit` is every tracked subreddit,
   `r/all` the sample of the rest of reddit.

5. Subscribe to the alerts: open <http://localhost:3609/undercurrent> in a browser, or see
   [Notifications on your phone](#notifications-on-your-phone). Check that they arrive:

   ```bash
   uv run undercurrent notify-test
   ```

On a server the ports only listen on localhost. Reach the dashboards through an SSH tunnel:

```bash
ssh -L 3610:localhost:3610 -L 3608:localhost:3608 your-server
```

The ingester and the analyzer keep running (and restart with Docker) until you stop them:

```bash
docker compose stop ingest analyze
```

## Trends and alerts

Every 15 minutes, `undercurrent analyze` compares, for every channel (each tracked
subreddit, and r/all) and every group,
the share of comments and posts mentioning each term in a window with its share before:

* **24h**: the last 24 hours against the 28 days before.
* **6h**: the last 6 hours against the same 6 hours of the day on the 28 days before, so
  mornings are compared with mornings.

A term is trending with at least 10 mentions by 5 different people, twice its usual
share, and a score (the strength of the evidence, a z-score of the weighted log odds
with a prior from the r/all sample, see the
[architecture](docs/ARCHITECTURE.md#42-short-term-burst-detection)) of at least
3. "pro" isn't shown as trending when "vision pro" explains it. For groups, breadth
counts the channels the term trends in. All of it is in the `detect:` section of
[config.yaml](config.yaml), overridable per scope.

What reaches your phone:

* **Instant alerts**, at most 5 a day: a score of at least 10 with 20 authors, or a
  term trending in many channels of a group at once. A term alerts once per story:
  not again for 72 hours unless its score doubles, and only in the scope where it's
  strongest.
* **A daily digest per group** at 08:00 (Europe/Berlin, set in `notify:`): the 10
  strongest trends of the last 24 hours in the group and its channels.
* Tapping either opens the web dashboard, or Grafana with `notify.links: grafana`
  ([Notifications on your phone](#notifications-on-your-phone)).

**The first days.** Without history, the window is compared with the share on all of
reddit, so on day one Trending now shows what's distinctive for each group (tech: ai,
code, claude) rather than what's rising. Alerts and digests wait until there are 3 days
of history. The full 28-day reference period takes 4 weeks.

### Tuning without waiting

`undercurrent replay` runs the detector as of past hours on the stored data and simulates
the alert rules. It writes and sends nothing, so it can run next to the live analyzer:

```bash
uv run undercurrent replay --from 2026-10-14T00:00 --to 2026-10-21T00:00 --horizon 24h
uv run undercurrent replay --from 2026-10-14T00:00 --min-z 4 --alert-min-z 8 --csv trends.csv
```

It prints how many alerts each day and group would get, and lists them.

### Notifications on your phone

Install the ntfy app (Android, iOS) and subscribe to the topic `undercurrent` on your
server. Tapping an alert opens the term's page in the web dashboard (`WEB_URL`), with a
second button for Grafana (`GRAFANA_URL`); `notify.links: grafana` in `config.yaml` opens
Grafana instead. The phone has to reach ntfy and, for the links, the dashboard and Grafana:

* **On a server:** put ntfy (port 3609), the web dashboard (3610) and Grafana (3608)
  behind a reverse proxy with TLS, set `NTFY_BASE_URL`, `WEB_URL` and `GRAFANA_URL` in
  `.env` to their public urls, and protect
  them (ntfy supports [access control](https://docs.ntfy.sh/config/#access-control),
  pass a token as `NTFY_TOKEN`). On iOS, also set
  `NTFY_UPSTREAM_BASE_URL=https://ntfy.sh` for instant delivery (free, only message ids
  pass through ntfy.sh).
* **Without a server of your own:** set `NTFY_URL=https://ntfy.sh` and a long random
  `NTFY_TOPIC`. Free and without an account (up to 250 messages a day, Undercurrent sends
  about a dozen), but anyone who knows the topic can read it.

## Long-term trends

Once a day after 00:30 UTC, `undercurrent analyze` looks at weekly shares: per ISO week
(Monday to Sunday, UTC), the comments and posts mentioning a term divided by all of them.
The current week is left out, so the results change on Mondays. For every channel and group,
over the last 13, 26 and 52 weeks:

* Terms mentioned at least 20 times a week on average are tested. ClickHouse fits a
  least squares line through every one's log share and picks the fastest growing and
  fading, at most 100 per scope and window.
* For those: the Theil–Sen slope as growth per month (robust against single spikes), the
  Mann–Kendall test for a steady trend, corrected for testing many terms at once
  (Benjamini–Hochberg over every term tested), and how much of the change comes from
  the two highest weeks.
* Each is **emerging** (significant growth, from at most 1 in 1,000 comments),
  **mainstreaming** (significant growth of a common term), **fading**, **one-off**
  (most of the change is one or two weeks far above the rest) or flat (not stored).
* A group's share is the average of its channels' shares, so a big subreddit doesn't
  drown out the small ones. `group_rate: pooled` divides all mentions by all comments
  instead.

A window runs once there are that many complete weeks of data, so the 13-week window
starts 13 weeks after collection begins, and the 52-week window after a year. Until then
the run reports "insufficient history". Every Monday at 08:00 (`notify:`) each group gets
a report with its fastest emerging, mainstreaming and fading terms. All settings are in
the `long_term:` section of [config.yaml](config.yaml), the statistics are explained in
the [architecture](docs/ARCHITECTURE.md#43-long-term-sustained-trends).

```bash
uv run undercurrent long-term --once                      # run now, store and print the result
uv run undercurrent long-term --once --as-of 2027-03-01   # as of a past date: the weeks before it
uv run undercurrent long-term --once --dry-run            # store nothing
uv run undercurrent trends --horizon 26w --scope tech     # the stored results
```

`--as-of` replays a past date over the stored data: it analyzes the complete weeks before
that date's week and stores them under that week (runs of the same week replace each
other). `undercurrent analyze --no-long-term` turns the daily run off,
`undercurrent long-term` without `--once` runs only the daily long-term loop and the
reports.

## Early warning

Some communities pick up terms days before others: a model name in r/LocalLLaMA before
r/technology, a product in a niche subreddit before all of reddit. The analyzer learns
these leader → follower edges from its own trends and turns them into forecasts.

* **Events and onsets.** Every term that trends (score 5 or more) becomes an event. For
  each event, every channel (each tracked subreddit, and r/all, reddit-wide) and every
  group gets an onset: the first hour its last 24 hours mentioned the term at least 5 times,
  twice its usual share, with a score of 3 (the same scoring as trends, against its own
  28 days before). A group a channel belongs to is also measured without it, so "the
  rest of tech follows r/LocalLLaMA" isn't just r/LocalLLaMA's own mentions.
* **Edges**, learned every day after 01:00 UTC from the events of the last 180 days: for
  each leader (a tracked subreddit) and follower, how often the follower crossed within 7
  days after
  the leader (when it hadn't before), after how long (median and IQR), against how often
  it crosses on any trending term (the base rate). A pair is an edge with at least 5
  events and 3 hits, significantly more hits than the base rate explains, and the leader
  significantly more often first than second (at least 70% of the events where both
  crossed): two subreddits that pick up the same big stories in either order are related,
  but neither leads. Both tests are corrected for testing every pair. The probability
  shown is shrunk towards the base rate, with an 80%
  interval, so 3 hits of 3 don't read as a certainty. Per topic too: a channel can lead
  on tech terms and follow on everything else.
* **Forecasts**, after every analysis run: a term trending in a leader whose followers
  haven't crossed yet, with the chance they will (lowered for the time that already
  passed) and when. They're resolved as hits or misses later, and shown in Grafana.
  Alerts for them are **off** (`forecast.alert`) until a replay shows they're worth it;
  switched on they count against the daily alert cap.

Edges need history: an event takes 17 days to be over, and a pair needs several of them.
Expect the first edges after 4–6 weeks of collection, and treat them as hints until
`undercurrent replay --forecast` says how often forecasts come true. Settings are in the
`lead_lag:` and `forecast:` sections of [config.yaml](config.yaml), the method in the
[architecture](docs/ARCHITECTURE.md#46-lead-lag-early-warning).

```bash
uv run undercurrent lead-lag --once                 # turn new trends into events, learn the edges
uv run undercurrent edges --leader r/localllama     # the latest edges
uv run undercurrent forecasts --pending             # what's expected to spread
uv run undercurrent forecasts --days 30             # and how earlier forecasts turned out
```

`undercurrent analyze --no-lead-lag` turns the layer off, `lead_lag.enabled: false` too.

**How good are the forecasts?** `undercurrent replay --forecast` replays them over stored
history, learning the edges as of each day like the live loop, so nothing it uses comes
from after the forecast. It reports precision (forecasts that came true), recall
(followers that followed and were forecast before they did), the warning time and the
calibration (do 60% forecasts come true 60% of the time). `--events stored` uses the
trends the analyzer stored instead of re-running the detector, which is much faster:

```bash
uv run undercurrent replay --forecast --events stored --from 2026-11-01 --to 2026-12-01
uv run undercurrent replay --forecast --events stored --min-events 8 --max-q 0.01
uv run undercurrent replay --forecast --step 6 --horizon 24h    # re-running the detector
```

**Publishing them** is planned in [docs/FORECAST-LEDGER.md](docs/FORECAST-LEDGER.md): every
forecast in a public ledger the moment it's made, timestamped through OpenTimestamps so it
can't be backdated, and graded when it resolves.

**Which subreddits to add?** `undercurrent suggest-subreddits` looks at the r/all sample's
comments and posts of the last 48 hours: their urls name the untracked subreddit they come
from. It lists those that mentioned the terms rising now early (before they trended) or
far more than their size explains, as lines to paste into a group of `config.yaml`. It
never changes the config.

**Do the onsets come first?** Optionally (`wikipedia.enabled`, or `undercurrent wikipedia`),
events whose term names a Wikipedia article are compared with its daily pageviews
(Wikimedia's free API, cached, rate limited): did interest there rise after the event's
first onset? It prints how often the onset was first and a sign test.

## Intents

Every comment and post is also searched for why something is mentioned. Five kinds, each
counted like a word under a term of its own. They can only be extracted while the raw text
is kept (48 hours), so they're counted from the moment the ingester extracts them.

| Kind | Term | From, for example |
| --- | --- | --- |
| switch | `notion → obsidian` | "I switched from Notion to Obsidian", "dropped ChatGPT for Claude", "we replaced our Jira with Linear", "the Jenkins to GitHub Actions migration" |
| alternative | `alternative: lastpass` | "any alternatives to LastPass?", "a good Plex alternative", "I use Firefox instead of Chrome" |
| complaint | `complaint: reddit` | "is Reddit down?", "Teams is unusable", "cancelled my Netflix subscription", "Spotify raised prices", "YouTube enshittification" |
| need | `need: track my sleep` | "is there an app to track my sleep?", "I wish there was a way to mute subreddits", "I'd pay for an app that …" |
| considering | `considering: notion → obsidian`, `considering: notion` | "I'm thinking of switching from Notion to Obsidian", "should I switch from Notion to Obsidian?", "thinking about leaving Notion", "about to cancel Notion", "should I ditch Notion?" |

English patterns run everywhere, german ones ("von Windows zu Linux gewechselt", "Alternative
zu Notion", "Gibt es eine App für …") in german subreddits. Precision comes first: a pattern
only counts with the exact wording, and what it's about has to be written like a name
("Notion", "iPhone", "AWS", "gpt-5", or on the lists of known names), so "switched from 2 to 3
monitors", "went from 60 to 144 Hz" and "instead of going outside" count as nothing. A
switch has to have happened; a switch only thought about counts as `considering`, and only
in the first person ("I'm thinking of", "should I"), not as advice ("you could switch") or
after "if", "would" or "could". The price is recall: on the first days about 1 item in 6,000
had an intent. Precision is not where it should be yet: on the first 40 hours of live data
50–79% per kind were judged correct (the target is 80%), mostly because game characters,
countries and languages look like names. Lists of those and stricter cuts ("Figma's
components" isn't Figma) were added since, and haven't been measured yet. Check the comments
behind a surprising intent (the Intent radar links them). How the patterns were tuned and
measured is in the [architecture](docs/ARCHITECTURE.md#47-intents-why-people-mention-things).

Intents go through the same detection as words: a switch trending in a subreddit, a
complaint emerging over months, a need picked up by one community before others. They have
lower gates (3 mentions by 3 people in a day instead of 10 by 5, 2 a week instead of 20 for
long-term trends) and are ranked apart from words, in `config.yaml` (`detect.kind_thresholds`,
`long_term.kind_min_mentions_per_week`, `lead_lag.kind_onset_min_mentions`).

```bash
uv run undercurrent intents --scope tech                           # all five kinds, last 7 days
uv run undercurrent intents --scope r/all --kind switch --days 30 --examples 2
uv run undercurrent term "complaint: reddit" --scope tech --bucket hour --days 2
```

`undercurrent intents` shows the most mentioned intents of a scope with the number of
authors, the share per 10,000 comments and posts, the change against the days before,
whether the analyzer finds them trending, and with `--examples` the sentences they came
from.

**After upgrading the ingester**, count the intents of the items it stored before, once:
their text is still there for up to 48 hours. `--before` is when the new ingester started:

```bash
uv run undercurrent backfill-intents --before 2026-10-12T09:30 --dry-run
uv run undercurrent backfill-intents --before 2026-10-12T09:30
```

## Churn radar

Being built, see [docs/CHURN-RADAR.md](docs/CHURN-RADAR.md): a weekly report per product
and its competitors of who leaves which product, for what and why, at no cost. Phases 1
(collection) and 2 (precision and the `considering` kind) run. In `radar:` of
[config.yaml](config.yaml), a watchlist names a category's products and the group of its
subreddits (the pilot: note-taking, `pkm`). For its products the ingester:

* counts their single-word names as names in intents in any case ("switched from evernote
  to obsidian"),
* searches all of reddit for new posts naming them, every 15 minutes per product,
* and fetches, once, the comment tree of a post found that way whose title asks or tells
  about a switch ("Alternatives to Notion?"), a day after it was posted.

What search finds outside the tracked subreddits is counted in the channel `r/_search`. It
isn't a complete stream, so it's in no group and no detector sees it.

The radar only counts intents about a watched product: a switch or a switch considered
with a watched product on either side ("considering: notion → obsidian" counts for both),
an alternative sought to one, a complaint about one. A game character, a country or a
language can't be a watched name, so the most common errors of intents never reach it. To
see how much there is to report on, per product and where it comes from (the watchlist's
subreddits, the other tracked ones, the r/all sample, the search):

```bash
uv run undercurrent radar candidates --days 1
```

## Command line

Needs [uv](https://docs.astral.sh/uv/). It reads `.env`, so it reaches the ClickHouse
started by Docker Compose. `uc` is short for `undercurrent`: `uv run uc status`.

```bash
uv sync
uv run undercurrent status
uv run undercurrent term "claude code" --scope tech --days 14
uv run undercurrent term rust --scope r/programming --bucket hour --days 2
uv run undercurrent term ai --scope tech --bucket week --days 180
uv run undercurrent trends --scope tech                 # the latest trends
uv run undercurrent trends --horizon 13w                # the latest long-term trends
uv run undercurrent analyze --once --no-notify          # one analysis run, prints the top trends
uv run undercurrent long-term --once --dry-run          # one long-term run
uv run undercurrent lead-lag --once --dry-run           # one lead–lag run, prints the edges
uv run undercurrent edges && uv run undercurrent forecasts
uv run undercurrent suggest-subreddits                  # untracked subreddits worth adding
uv run undercurrent intents --scope tech --kind switch  # who switches from what to what
uv run undercurrent radar candidates                    # the churn radar's material per product
uv run undercurrent wikipedia                           # onsets vs Wikipedia pageviews
uv run undercurrent notify-test
```

A scope is a group from `config.yaml`, a channel (`r/technology`), `reddit` (every tracked
subreddit) or `r/all` (the r/all sample of everything else). `undercurrent status` lists
every channel with its platform and what it collected in the last 24 hours.

To run the ingester outside of Docker, stop the container first (both would share one
API budget), then run `uv run undercurrent ingest` (every enabled platform, or `--source reddit`). The analyzer can run anywhere, but run only
one of it with notifications on, or alerts go out twice.

## How the data is stored

| Table | What | Kept |
| --- | --- | --- |
| `items` | Raw comments and posts, their channel, url, language and the intents found in them, for examples in the dashboards | 48 hours |
| `term_hourly` | Per hour, channel, document type and term: comments mentioning it, occurrences, distinct authors | 180 days |
| `term_daily` | The same per day | forever |
| `scope_hourly` | Per hour, channel and document type: all comments, words and authors (the denominators) | forever |
| `channels`, `channel_groups` | The channels and groups of `config.yaml`, rewritten when the ingester starts | |
| `polls` | Every request to a platform, for the ingestion dashboard | 90 days |
| `trends` | Every 15 minutes, the top 50 trends per scope and horizon (and the top 20 of each intent kind), with the numbers behind them and what happened with the alert | 90 days, alerts forever |
| `long_term_trends` | Every week, the emerging, mainstreaming, fading and one-off terms per scope and window, with the statistics and weekly shares behind them | forever |
| `notifications` | Every message sent to ntfy (alerts, digests, weekly reports, forecast alerts) | forever |
| `lead_lag_events` | Every term that trended, with every scope's onset hour for it | forever |
| `propagation_edges` | Every day, the leader → follower edges with lead time, hit rate, base rate, lift, probability and sample size | 180 days |
| `forecasts` | Every forecast, its probability when made and how it turned out | forever |
| `wiki_articles`, `wiki_pageviews`, `wiki_leads` | Optional: Wikipedia articles of event terms, their daily views, when interest rose there | forever |

* Terms are single words, 2-3 word phrases that don't start or end with a stopword, linked
  domains, mentioned subreddits, and intents (`notion → obsidian`, `complaint: reddit`).
* A comment counts once per term however often it repeats it, and distinct authors are
  counted too, so one spammer can't make a trend.
* Authors are only stored as a keyed hash, never as usernames. Raw text is deleted after
  48 hours, as Reddit asks of API users.
* Tracked subreddits are polled completely as multireddits (`r/a+b+c`), each feed as often
  as its volume needs. A sample of r/all serves as the "normal" vocabulary. Reddit only
  returns its last second or two, so it's a sample of a few percent. What it finds outside
  the tracked subreddits is pooled into one channel, `r/all`. What the churn radar's
  search finds is pooled into `r/_search` the same way.
* Authors are hashed together with their platform, so the same name on two platforms
  counts as two people.

## Development

```bash
uv run pytest            # integration tests need ClickHouse: docker compose up -d clickhouse
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

* While nothing is deployed, schema changes edit the files in `src/undercurrent/migrations/`
  in place and the local database is recreated (`docker compose down`, `docker volume rm
  undercurrent_clickhouse_data`, `docker compose up -d --build`), see
  [docs/CROSS-PLATFORM.md](docs/CROSS-PLATFORM.md) §2.2. Once there's history worth
  keeping they go into a new file again, applied on the next start (or with
  `uv run undercurrent migrate`).
* A new platform is a source in `src/undercurrent/sources/` (`sources/base.py`: an `Item`, a
  `Sink`, a `Source`), like `sources/reddit/`.
* The dashboards are generated: edit `grafana/build_dashboards.py` and run
  `uv run python grafana/build_dashboards.py`. Grafana reloads them within 10 seconds.
* The web dashboard ([docs/WEB-DASHBOARD.md](docs/WEB-DASHBOARD.md)) has two halves:
  * **The API** in `src/undercurrent/web/`: FastAPI under `/api/v1/`, the SQL in `queries/`,
    a Pydantic model per response in `models.py`, the routes in `routes/`, the live stream
    in `stream.py`. Every query runs as of a time (`as_of`, or `UNDERCURRENT_NOW` for
    the demo database). A change to a panel's numbers usually belongs in Grafana's builder
    too. `uv run undercurrent web --dev --port 3612 --reload` serves only the API.
  * **The page** in `web/`: React and TypeScript, built by Vite, on Node 26 and pnpm 12
    ([web/AGENTS.md](web/AGENTS.md) has the conventions). In `web/`: `pnpm install`,
    `pnpm dev` (port 3611, `/api` proxied to 3610 or `UNDERCURRENT_API`), `pnpm check`
    (types, lint, format, unit tests), `pnpm e2e` (Playwright and axe against a running
    API, `E2E_URL`), `pnpm build`.
  * A change to the API's data is a change to a model, then
    `uv run undercurrent web openapi > web/src/api/openapi.json` and
    `cd web && pnpm gen:api`. CI fails when the two disagree.
* `bench/demo.py` seeds a deterministic demo database with planted stories into a
  ClickHouse of its own (`--small` in about a minute and a half, the full one in about 11
  minutes), the data the end-to-end tests and screenshots run on.
  `bench/web.py` calls every endpoint against a database and reports each one's queries,
  time, memory and rows from the query log, against a budget of 1 s and 500 MB.
* `bench/` measures at production scale: `bench/synthetic.py` writes a year of synthetic
  history into a database of its own, `bench/long_term.py` runs the long-term detector
  over it and reports time and memory per query. `bench/lead_lag.py` writes hourly
  history with planted events and measures the lead–lag runs, forecasts and replays. Run
  them against a ClickHouse of their own, never the live one (see the docstrings).
* `bench/intent_names.py` rebuilds the list of words the corpus writes like names from the
  live items, `bench/intent_precision.py` samples intents from them for labeling and scores
  the labels. Both only read; keep the samples, which hold reddit text, out of the
  repository.
