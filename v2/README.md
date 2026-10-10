# WGRA v2

Finds out which words and phrases are gaining or losing share of the conversation in
subreddits and groups of subreddits, over hours (short term) and months (long term).
The design and the roadmap are in [../docs/ARCHITECTURE-V2.md](../docs/ARCHITECTURE-V2.md).

Phases 1 and 2 are built. The ingester collects comments and posts from the subreddits
in [config.yaml](config.yaml) into ClickHouse. Every 15 minutes the analyzer scores what
is mentioned far more than usual, per subreddit and per group, stores it for Grafana and
sends the strongest trends and a daily digest to your phone through ntfy. Long-term
trends (phase 4) need months of history, so collecting should start as early as
possible.

## Cost

Everything runs on free, open source software: ClickHouse, Grafana OSS, ntfy, Python.
Reddit's API is used within its free tier (100 requests per minute, non-commercial use).
No paid APIs. The only cost is the machine it runs on, locally that's your own computer.

## Run it

Requires Docker. Works the same on a laptop and on a server.

1. Create `.env` from the example and fill it in:

   ```bash
   cp .env.example .env
   ```

   * `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` of a Reddit "script" app. No Reddit
     username or password needed.
   * `AUTHOR_HASH_KEY`, `CLICKHOUSE_PASSWORD` and `GRAFANA_ADMIN_PASSWORD`: generate each
     with `openssl rand -hex 32`. Never change `AUTHOR_HASH_KEY` afterwards.

2. Choose subreddits and groups in `config.yaml`.

3. Start ClickHouse, Grafana, ntfy, the ingester and the analyzer:

   ```bash
   docker compose up -d --build
   ```

4. Open Grafana at <http://localhost:3608>, log in as `admin` with `GRAFANA_ADMIN_PASSWORD`.
   The dashboards are in the WGRA folder:
   * **Trending now**: what the analyzer found, per group and its subreddits: score,
     times the usual share, mentions, authors, breadth, a sparkline of the last week,
     and the alerts. Click a term to explore it.
   * **Term explorer**: how often terms are mentioned over time, where, and recent
     examples.
   * **Rising (preview)**: a simpler first look at what's mentioned more than usual.
   * **Ingestion**: is the ingester healthy and complete.

5. Subscribe to the alerts: open <http://localhost:3609/wgra> in a browser, or see
   [Notifications on your phone](#notifications-on-your-phone). Check that they arrive:

   ```bash
   uv run wgra notify-test
   ```

On a server the ports only listen on localhost. Reach Grafana through an SSH tunnel:

```bash
ssh -L 3608:localhost:3608 your-server
```

The ingester and the analyzer keep running (and restart with Docker) until you stop them:

```bash
docker compose stop ingest analyze
```

## Trends and alerts

Every 15 minutes, `wgra analyze` compares, for every tracked subreddit and every group,
the share of comments and posts mentioning each term in a window with its share before:

* **24h**: the last 24 hours against the 28 days before.
* **6h**: the last 6 hours against the same 6 hours of the day on the 28 days before, so
  mornings are compared with mornings.

A term is trending with at least 10 mentions by 5 different people, twice its usual
share, and a score (the strength of the evidence, a z-score of the weighted log odds
with a prior from the r/all sample, see the
[architecture](../docs/ARCHITECTURE-V2.md#42-short-term-burst-detection)) of at least
3. "pro" isn't shown as trending when "vision pro" explains it. For groups, breadth
counts the subreddits the term trends in. All of it is in the `detect:` section of
[config.yaml](config.yaml), overridable per scope.

What reaches your phone:

* **Instant alerts**, at most 5 a day: a score of at least 10 with 20 authors, or a
  term trending in many subreddits of a group at once. A term alerts once per story:
  not again for 72 hours unless its score doubles, and only in the scope where it's
  strongest.
* **A daily digest per group** at 08:00 (Europe/Berlin, set in `notify:`): the 10
  strongest trends of the last 24 hours in the group and its subreddits.
* Tapping either opens Grafana.

**The first days.** Without history, the window is compared with the share on all of
reddit, so on day one Trending now shows what's distinctive for each group (tech: ai,
code, claude) rather than what's rising. Alerts and digests wait until there are 3 days
of history. The full 28-day reference period takes 4 weeks.

### Tuning without waiting

`wgra replay` runs the detector as of past hours on the stored data and simulates the
alert rules. It writes and sends nothing, so it can run next to the live analyzer:

```bash
uv run wgra replay --from 2026-10-14T00:00 --to 2026-10-21T00:00 --horizon 24h
uv run wgra replay --from 2026-10-14T00:00 --min-z 4 --alert-min-z 8 --csv trends.csv
```

It prints how many alerts each day and group would get, and lists them.

### Notifications on your phone

Install the ntfy app (Android, iOS) and subscribe to the topic `wgra` on your server.
The phone has to reach ntfy and, for the links, Grafana:

* **On a server:** put ntfy (port 3609) and Grafana (3608) behind a reverse proxy with
  TLS, set `NTFY_BASE_URL` and `GRAFANA_URL` in `.env` to their public urls, and protect
  them (ntfy supports [access control](https://docs.ntfy.sh/config/#access-control),
  pass a token as `NTFY_TOKEN`). On iOS, also set
  `NTFY_UPSTREAM_BASE_URL=https://ntfy.sh` for instant delivery (free, only message ids
  pass through ntfy.sh).
* **Without a server of your own:** set `NTFY_URL=https://ntfy.sh` and a long random
  `NTFY_TOPIC`. Free and without an account (up to 250 messages a day, WGRA sends about
  a dozen), but anyone who knows the topic can read it.

## Command line

Needs [uv](https://docs.astral.sh/uv/). It reads `.env`, so it reaches the ClickHouse
started by Docker Compose.

```bash
uv sync
uv run wgra status
uv run wgra term "claude code" --scope tech --days 14
uv run wgra term rust --scope programming --bucket hour --days 2
uv run wgra trends --scope tech                 # the latest trends
uv run wgra analyze --once --no-notify          # one analysis run, prints the top trends
uv run wgra notify-test
```

A scope is a group from `config.yaml`, a single subreddit, `tracked` (every tracked
subreddit) or `sample` (the r/all sample of everything else).

To run the ingester outside of Docker, stop the container first (both would share one
API budget), then run `uv run wgra ingest`. The analyzer can run anywhere, but run only
one of it with notifications on, or alerts go out twice.

## How the data is stored

| Table | What | Kept |
| --- | --- | --- |
| `items` | Raw comments and posts, for examples in the dashboards | 48 hours |
| `term_hourly` | Per hour, subreddit and term: comments mentioning it, occurrences, distinct authors | 180 days |
| `term_daily` | The same per day | forever |
| `scope_hourly` | Per hour and subreddit: all comments, words and authors (the denominators) | forever |
| `polls` | Every request to Reddit, for the ingestion dashboard | 90 days |
| `trends` | Every 15 minutes, the top 50 trends per scope and horizon, with the numbers behind them and what happened with the alert | 90 days, alerts forever |
| `notifications` | Every message sent to ntfy | forever |

* Terms are single words, 2-3 word phrases that don't start or end with a stopword, linked
  domains and mentioned subreddits.
* A comment counts once per term however often it repeats it, and distinct authors are
  counted too, so one spammer can't make a trend.
* Authors are only stored as a keyed hash, never as usernames. Raw text is deleted after
  48 hours, as Reddit asks of API users.
* Tracked subreddits are polled completely as multireddits (`r/a+b+c`), each feed as often
  as its volume needs. A sample of r/all serves as the "normal" vocabulary. Reddit only
  returns its last second or two, so it's a sample of a few percent. Its counts are
  pooled into one scope, `_sample`.

## Development

```bash
uv run pytest            # integration tests need ClickHouse: docker compose up -d clickhouse
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

* Schema changes go into a new file in `src/wgra/migrations/`, applied on the next start
  (or with `uv run wgra migrate`).
* The dashboards are generated: edit `grafana/build_dashboards.py` and run
  `uv run python grafana/build_dashboards.py`. Grafana reloads them within 10 seconds.
