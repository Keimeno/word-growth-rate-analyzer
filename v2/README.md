# WGRA v2

Finds out which words and phrases are gaining or losing share of the conversation in
subreddits and groups of subreddits, over hours (short term) and months (long term).
The design and the roadmap are in [../docs/ARCHITECTURE-V2.md](../docs/ARCHITECTURE-V2.md).

This is phase 1: the data foundation. The ingester collects comments and posts from the
subreddits in [config.yaml](config.yaml) into ClickHouse, and Grafana shows them. Trend
scoring and alerts (phase 2) build on the data it collects, so it should start
collecting as early as possible.

## Cost

Everything runs on free, open source software: ClickHouse, Grafana OSS, Python. Reddit's
API is used within its free tier (100 requests per minute, non-commercial use). The only
cost is the machine it runs on, locally that's your own computer.

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

3. Start ClickHouse, Grafana and the ingester:

   ```bash
   docker compose up -d --build
   ```

4. Open Grafana at <http://localhost:3608>, log in as `admin` with `GRAFANA_ADMIN_PASSWORD`.
   The dashboards are in the WGRA folder:
   * **Term explorer**: how often terms are mentioned over time, where, and recent
     examples.
   * **Rising (preview)**: what's mentioned more than usual in the last 24 hours. A simple
     first version, the real scoring comes in phase 2.
   * **Ingestion**: is the ingester healthy and complete.

On a server the ports only listen on localhost. Reach Grafana through an SSH tunnel:

```bash
ssh -L 3608:localhost:3608 your-server
```

The ingester keeps running (and restarts with Docker) until you stop it:

```bash
docker compose stop ingest
```

## Command line

Needs [uv](https://docs.astral.sh/uv/). It reads `.env`, so it reaches the ClickHouse
started by Docker Compose.

```bash
uv sync
uv run wgra status
uv run wgra term "claude code" --scope tech --days 14
uv run wgra term rust --scope programming --bucket hour --days 2
```

A scope is a group from `config.yaml`, a single subreddit, `tracked` (every tracked
subreddit) or `sample` (the r/all sample of everything else).

To run the ingester outside of Docker, stop the container first (both would share one
API budget), then run `uv run wgra ingest`.

## How the data is stored

| Table | What | Kept |
| --- | --- | --- |
| `items` | Raw comments and posts, for examples in the dashboards | 48 hours |
| `term_hourly` | Per hour, subreddit and term: comments mentioning it, occurrences, distinct authors | 180 days |
| `term_daily` | The same per day | forever |
| `scope_hourly` | Per hour and subreddit: all comments, words and authors (the denominators) | forever |
| `polls` | Every request to Reddit, for the ingestion dashboard | 90 days |

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
