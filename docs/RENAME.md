# Rename to Undercurrent: plan

**Status: code renamed 2026-11-01 (§3.2–§3.4); the switch of the running stack (§3.5) is
next.** The project becomes Undercurrent everywhere except the GitHub repository, which
keeps its name for now.

"Word Growth Rate Analyzer" describes the first engine: which words gain share of the
conversation. The project now also says where a term starts and where it goes next (§4.6
of [ARCHITECTURE.md](ARCHITECTURE.md)), why people mention products (§4.7), who is leaving
which product ([CHURN-RADAR.md](CHURN-RADAR.md)), and soon across platforms
([CROSS-PLATFORM.md](CROSS-PLATFORM.md)). Undercurrent covers all of it without naming a
platform.

It's mechanical: about two hours, then a restart of the stack.

## 1. Where things stand (checked 2026-10-31)

* The old name appears about 580 times in 82 tracked files. 252 of those are imports
  (`from wgra…`); the rest are the command in docs and help texts, config defaults, the
  Compose project, the ClickHouse database and user, test and bench database names, the
  Grafana folder and dashboard uids, the ntfy topic and the user agents. Phase 1 of the
  cross-platform plan adds more (`sources/reddit/`), so the rename works by pattern
  (§3.2), not from a list of files.
* **Cross-platform phase 1 is in progress in this checkout**: step 1 is committed
  (`c593f8c`), step 2 is being edited. The rename touches every Python file, so it can't
  run at the same time.
* The stack runs as the Compose project `wgra` (5 containers, volumes
  `wgra_clickhouse_data`, `wgra_grafana_data`, `wgra_ntfy_cache`). Nothing is deployed.
* Neither `undercurrent` nor `uc` is a command on this machine.

## 2. Names

| Today | After |
| --- | --- |
| Word Growth Rate Analyzer, WGRA (prose, titles) | Undercurrent |
| package `wgra`, `src/wgra/` | `undercurrent`, `src/undercurrent/` |
| command `wgra` | `undercurrent`, and `uc` for short (both in `[project.scripts]`) |
| `WGRA_CONFIG` | `UNDERCURRENT_CONFIG` |
| Compose project `wgra`: containers `wgra-ingest-1`, volumes `wgra_*`, images `wgra-*` | `undercurrent` |
| ClickHouse database and user `wgra` | `undercurrent` |
| `clickhouse/wgra.xml` | `clickhouse/undercurrent.xml` |
| test and bench databases `wgra_test_*`, `wgra_bench`, `wgra_bench_ll`; container `wgra-dev-bench-clickhouse` | `undercurrent_test_*`, `undercurrent_bench`, `undercurrent_bench_ll`, `undercurrent-dev-bench-clickhouse` |
| Grafana provider `wgra`, folder `WGRA`, tag `wgra`, `provisioning/dashboards/wgra.yaml` | `undercurrent`, `Undercurrent`, `undercurrent`, `undercurrent.yaml` |
| dashboard uids `wgra-terms`, `-trending`, `-long-term`, `-early-warning`, `-intents`, `-rising`, `-ingestion` | `undercurrent-terms` and so on |
| ntfy topic `wgra` | `undercurrent` |
| Reddit user agent `python:wgra:2.0 (by /u/…)` | `python:undercurrent:2.0 (by /u/…)` |
| Wikipedia user agent `wgra/2.0 (https://github.com/Keimeno/word-growth-rate-analyzer)` | `undercurrent/2.0 (…)`, same url |
| pyproject description "short and long term trends per subreddit" | what it does now (§3.3) |

What stays:

* The GitHub repository `Keimeno/word-growth-rate-analyzer`, every url to it (the user
  agents, links in docs) and the local checkout's directory name.
* Git history: branch names (`wgra-v2`, `claude/*`), commit messages.
* The version (2.0), ports 3607–3609, `AUTHOR_HASH_KEY` and the passwords.
* Dashboard file names, which don't carry the name.
* Untracked leftovers from v1 and the move to the root (`v2/`, `node_modules/`,
  `packages/`, `config.json`, `.claude/worktrees/`). Deleting them is a separate cleanup.

## 3. How

### 3.1 When

Between steps 4 and 5 of cross-platform phase 1
([CROSS-PLATFORM.md §8.8](CROSS-PLATFORM.md#88-order-of-work)): after its code, docs and
bench are done, before it checks and switches. Then step 5's
database recreation covers the rename too, and history restarts once. The "after" run of
§8.7 uses the new command and bench database names; their output doesn't contain the
name, so the comparison is unchanged. The switch then follows §3.5 below, not §8.3's
commands: the step-2 replacement turns those into `undercurrent` names, and a plain
`docker compose down` would miss the old stack.

If phase 1 has already switched by then, run it afterwards. The stack restarts once more
and loses the days since phase 1's switch. That isn't worth a migration while nothing is
deployed.

Like phase 1, it runs while no other work edits the checkout. `git status` is clean
before starting.

### 3.2 The mechanical part

1. Move the files that carry the name:

   ```bash
   git mv src/wgra src/undercurrent
   git mv clickhouse/wgra.xml clickhouse/undercurrent.xml
   git mv grafana/provisioning/dashboards/wgra.yaml grafana/provisioning/dashboards/undercurrent.yaml
   ```

2. Replace the name in every tracked text file except `uv.lock` and this plan, most
   specific first. Nothing else that must stay contains `wgra` (the repository's name is
   spelled out):

   ```bash
   git grep -lzI -i -e wgra -e 'word growth rate analyzer' -- ':!uv.lock' ':!docs/RENAME.md' \
     | xargs -0 sed -i '' \
     -e 's/WGRA_CONFIG/UNDERCURRENT_CONFIG/g' \
     -e 's/Word Growth Rate Analyzer/Undercurrent/g' \
     -e 's/WGRA/Undercurrent/g' \
     -e 's/wgra/undercurrent/g'
   ```

3. `pyproject.toml`: add `uc = "undercurrent.cli:main"` next to `undercurrent`. Then
   `uv lock` and `uv sync`, which regenerate the lock file under the new project name and
   replace the `wgra` command in `.venv`.

4. Regenerate the dashboards: `uv run python grafana/build_dashboards.py`.

### 3.3 By hand

* **README**: the title, an intro that covers what it does now (the trends, where they
  start and spread, why people switch), and one line: "Formerly Word Growth Rate Analyzer
  (WGRA). The repository keeps its name." Mention `uc` where the commands start.
* **ARCHITECTURE.md**: the title ("Undercurrent: Architecture and Plan", not "Undercurrent
  v2", there was no Undercurrent v1) and the opening of §1, which defines the system as
  word growth only.
* **pyproject.toml**: the description, for example "Undercurrent: what's rising in online
  conversation, where it starts, where it spreads next, and why people switch products".
* **Line lengths**: `undercurrent` is 8 characters longer than `wgra`. In a dry run on
  `c593f8c`, `ruff format` rewrapped 5 files, and 10 lines it can't wrap (docstrings, help
  texts in the dashboard builder) needed wrapping by hand (E501). The Markdown lines over
  92 characters went from 59 to 113, so about 55 lines in paragraphs to rewrap.
* **docs/architecture.png**: re-render it with the command at the top of
  `architecture.html` and check that `uv run undercurrent` still fits its box.

### 3.4 Check before committing

1. Only the "formerly" line still has the old name:

   ```bash
   git grep -nI -i -e wgra -e 'word growth' -- ':!docs/RENAME.md'
   ```

2. Everything else in the diff is the name, the hand edits of §3.3 and ruff's
   parentheses and trailing commas. `git add -u` stages tracked files only, so the
   untracked leftovers stay out:

   ```bash
   git add -u && git diff --cached -M20% --word-diff=porcelain -- . ':!uv.lock' \
     | grep -E '^[-+][^-+]' | grep -viE 'wgra|undercurrent|word growth rate analyzer'
   ```

   `-M20%`: at git's default of 50%, the small `__init__.py` files count as deleted and
   added instead of moved, and their whole content shows up here.

3. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`
   and `docker build .` pass. Run the tests while the old stack is still up: they use the
   ClickHouse in `.env` with their own `undercurrent_test_*` databases, and locally they
   skip instead of failing when it's unreachable. The output must show no "ClickHouse not
   available" skips.

4. `uv run undercurrent --help` and `uv run uc --help` work. (`status` needs the new
   database, so it waits for the switch.)

Commit on `develop`: "Rename to Undercurrent".

### 3.5 Switch

With phase 1's step 5, or on its own afterwards.

1. **Stop the old stack first:**

   ```bash
   docker compose -p wgra down
   ```

   After the rename, a plain `docker compose down` targets the project `undercurrent` and
   leaves the `wgra` containers running on ports 3607–3609, and `up` then fails.

2. In `.env` (not in git): `CLICKHOUSE_USER=undercurrent`, `CLICKHOUSE_DB=undercurrent`,
   and `REDDIT_USER_AGENT=python:undercurrent:2.0 (by /u/<you>)`. Also `NTFY_TOPIC`, if it's
   set. Leave `AUTHOR_HASH_KEY` and the passwords alone.

3. `docker compose up -d --build`. The new project gets new volumes, so:
   * ClickHouse starts empty, which is phase 1's recreation (§8.3's `docker volume rm`
     isn't needed).
   * Grafana starts fresh. The dashboards are provisioned, so only stars and preferences
     are lost.
   * ntfy's 72-hour message cache starts empty.

4. On the phone, subscribe to `undercurrent` and unsubscribe from `wgra`. Then
   `uv run undercurrent notify-test`.

5. Check `uv run undercurrent status`, and that Grafana (port 3608) has the Undercurrent
   folder with all seven dashboards and that alert links open them. Bookmarks, and links in
   alerts sent before the switch, point at `/d/wgra-…` and no longer open.

6. A day later, if it all works, delete the old volumes and images. Until then they are
   the way back (the commit before the rename, the old `.env` values, `docker compose up`):

   ```bash
   docker volume rm wgra_clickhouse_data wgra_grafana_data wgra_ntfy_cache
   docker image rm wgra-ingest wgra-analyze
   ```

## 4. Left for later

* **Renaming the GitHub repository.** GitHub redirects the old urls, but the remote, the
  Wikipedia user agent and the links in docs should then move to the new name.
* **A domain.** `undercurrent.watch` and `undercurrent.report` were unregistered on
  2026-10-31; `.com`, `.io`, `.ai`, `.app` and `.dev` are taken.
* **A trademark check** before any commercial use. For personal use it doesn't matter.
