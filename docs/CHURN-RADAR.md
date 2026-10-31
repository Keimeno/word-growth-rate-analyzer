# Churn radar: plan

**Status: planned, not started.** A reference for building it later. Nothing below exists
yet except what it builds on.

A weekly report for one product and its competitors: who is leaving which product, for
what, why, who is thinking about it, and what people in the category wish existed. Every
number links to the threads behind it. It builds on intents
([ARCHITECTURE.md §4.7](ARCHITECTURE.md#47-intents-why-people-mention-things)), the
short-term and long-term detectors (§4.2, §4.3) and the r/all sample, and adds three things
they lack: enough volume per product, precision on the products that matter, and the
reasons.

**It costs nothing to run.** No paid APIs and no model: patterns and word lists, like the
rest of v2, on a machine you already have or a free one. A model is a later upgrade (§7),
worth it only once the pilot shows there's enough to label.

Who it's for: product marketing, competitive intelligence and founders at software
companies, people who today read their competitors' subreddits by hand. Whether anyone may
sell it depends on Reddit's terms (§6, gate 2). Everything up to the pilot is for your own
use and doesn't need that decided.

## 1. Where things stand (checked 2026-10-31)

* **Nothing is collecting on this machine.** The ingester and the analyzer stopped on
  2026-10-12 at 07:56 UTC, and the stored data covers only 2026-10-10 08:00 to 07:00 that day.
  Migrations 004 (lead–lag) and 005 (intents) were never applied there, so it holds no
  intents. If the stack isn't running on a server either, nothing has been collected since,
  and the features that wait for history (long-term trends, lead–lag) haven't started
  waiting yet.
* **Brand volume is far too thin.** In the 40 hours from 2026-10-10 08:00, the word
  counts per product (items mentioning it, tracked subreddits + r/all sample) were:
  notion 13 + 84, obsidian 5 + 23, bitwarden 23 + 11, keepass 14 + 4, 1password 3 + 0,
  onenote 0 + 3, logseq 1 + 1, lastpass 1 + 0, evernote 1 + 0. That's 39,917 tracked items
  and 616,996 sample items in all. The sample is a few percent of reddit, and most product
  conversation happens in subreddits we don't track. At these volumes Obsidian would get a
  counted switch about once a month.
* **Precision is below 80%.** It was measured at 50–79% per kind on the first 40 hours
  (§4.7). The most common errors are names that aren't products (game characters,
  countries, languages), entities cut so they lose what they are, and a trimming bug.
* **No stance, no reasons.** The patterns drop "thinking of leaving Notion" as a
  hypothetical. "Moved to Obsidian because Notion is useless offline" counts as
  `notion → obsidian`, and "useless offline", the part a customer cares about, is lost.

## 2. Design

### 2.1 Watchlists

A watchlist is a set of products in one category, their names as written, and the
subreddits where the category talks. It lives in `config.yaml`, and its subreddits are a
group like any other, so the ingester tracks them completely and every dashboard and
detector already works on them:

```yaml
groups:
  pkm: [Notion, ObsidianMD, Evernote, OneNote, logseq, PKMS, NoteTaking, Zettelkasten]

radar:
  enabled: true
  watchlists:
    pkm:
      group: pkm
      products:               # canonical name: aliases as people write them
        notion: [Notion, notion.so, Notion AI]
        obsidian: [Obsidian, obsidian.md]
        evernote: [Evernote]
        onenote: [OneNote]
        logseq: [Logseq]
        apple notes: [Apple Notes]
      search: true            # also search all of reddit for posts naming a product
      report: {day: monday, time: "08:00"}
```

Watchlists do two jobs:

* **Recall.** Every alias counts as a name in any case and position, like the hand-kept
  `products_*.txt`, so "switched from notion to obsidian" in lowercase counts.
* **Precision.** The report only counts intents whose entity is a watched alias, or, for a
  switch, one side of it. A game character, a country or a language can never match an
  alias, which removes the most common class of errors without a model. Products that
  aren't on the list still appear as destinations ("notion → capacities").

The pilot category is note-taking (PKM). It has a famous switching flow, vendors with their
own active subreddits, and small vendors (Capacities, Anytype, Reflect) who are the most
likely early buyers. Password managers (LastPass, Bitwarden, 1Password, KeePass) are the
alternative.

### 2.2 Collection

Three sources, in order of cost (all of it within reddit's free API tier):

1. **The watchlist's subreddits** (no new code). The vendors' own subreddits and the
   category subreddits are where "I'm leaving Notion" gets written. They join the tracked
   multireddits and count like every other subreddit.
2. **Brand search** (new, `ingest/search.py`). Every 15 minutes per product, reddit search
   for new posts naming an alias, anywhere. To verify first: as far as known, the API's
   search covers posts, not comments, and how quickly it indexes new posts is unknown.
3. **Comment trees** (new). Posts from search whose title has an intent cue
   ("alternative", "switch", "leaving", "vs", "migrate", "replace") get their full comment
   tree fetched once, when they are about 24 hours old. The answers under "Alternatives to
   Notion?" are where the reasons are.

Search hits from tracked subreddits are skipped, since the stream already has them, and the
ingester's duplicate check catches overlaps with the sample. The rest are stored and
extracted like any item, under a scope of their own, `_search`, like `_sample`. Its counts
aren't shares of anything (search isn't a complete stream), so the detectors and alerts skip
it, and only the radar counts it. Budget: 10 products × 4 searches an hour is under 1
request a minute, plus a few dozen trees a day. Lower `ingest.requests_per_minute` from 90
to 85 to leave room.

### 2.3 Precision without a model

On top of the watchlist filter, take the open fixes from §4.7 "Still open":

* Fix the trimming bug: when x isn't a name, reject the match instead of skipping forward
  to a later name ("a free alternative to photoshop use Krita" counts `krita`).
* Reject cuts that drop a lowercase head noun ("Figma's components").
* Add game characters and languages to `generic_en.txt`, regenerate `names_en.txt` from
  48 hours of items (`bench/intent_names.py`).

Measure with `bench/intent_precision.py`, with a new `--watchlist pkm` option that samples
only intents about watched products. Hand-labeling is the only cost.

### 2.4 Stance: considering

Today `_hypothetical` drops a switch that's asked about or only considered. A new kind,
`considering`, keeps the first-person ones:

| Term | From, for example | Not |
| --- | --- | --- |
| `considering: notion → obsidian` | "I'm thinking of switching from Notion to Obsidian", "should I switch from Notion to Obsidian?", "considering moving from Notion to Obsidian" | "if you switch from Chrome to Firefox", "you could switch to …" (advice) |
| `considering: notion` | "thinking about leaving Notion", "about to cancel Notion", "should I ditch Notion?" | "leaving Notion open", "should I leave a comment in Notion" |

The rules: a first-person subject (`i`, `we`), a verb of considering (thinking of or about,
considering, debating, about to, should I), and one known side, like switches. "If",
"would" and "could" stay hypothetical and count as nothing. Golden tests for each line of
the table, positives and negatives, like the 118 that exist.

### 2.5 Reasons and missing features without a model

Two more kinds, extracted only from sentences that carry an intent about a product
(switch, considering, alternative, complaint) and from the sentence right after it:

* **`reason`**, term `reason: notion · price`: the product the intent is about (the
  side being left, for a switch) and a reason from a word list. The lists live in
  `intent_words/reasons/<reason>_en.txt`, one per reason:

  | Reason | Words and phrases, for example |
  | --- | --- |
  | price | price, pricing, expensive, subscription, price hike, paywall, free tier, per month |
  | reliability | buggy, crashes, sync issues, lost my notes, data loss, corrupted |
  | performance | slow, laggy, sluggish, bloated, takes forever to load |
  | offline | offline, local files, local-first, self-host, no internet |
  | lock-in | export, markdown, proprietary, lock-in, plain text, own my data |
  | privacy | privacy, encryption, e2ee, end-to-end, tracking, telemetry |
  | ai | ai, llm, chatgpt, copilot, ai features |
  | ease of use | clunky, complicated, learning curve, cluttered, ui, ux |
  | outage | down, outage, can't log in |

* **`missing`**, term `missing: notion · offline mode`: a 2–3 word phrase after "has no",
  "there's no", "lacks", "lack of", "doesn't have", "doesn't support", "missing" or "no …
  support". It's built like a need: no stopwords at the edges, no pronouns, numbers or vague
  words.

The `·` can't occur in a word, so the product and the reason can always be told apart.
Reasons mix push and pull ("moved to Obsidian because local files" is a reason to arrive,
counted against Notion), and they only catch reasons that are spelled out. Implied reasons
and sarcasm are lost. That's the gap a model would close (§7).

All three new kinds are counted like words, through `term_events` into `term_hourly` and
`term_daily`, with gates of their own in `detect.kind_thresholds`. So the detectors work on
them for free: `reason: notion · price` spiking after a price change is a short-term
trend, and `missing: notion · offline mode` growing for months is a long-term one.

### 2.6 Evidence

`items.intents` loses its permalinks with the text after 48 hours, but a weekly report needs
links from the whole week. Migration `006_radar.sql` adds `intent_items`, filled by a
materialized view from `items` for every intent term: id, permalink, the real subreddit,
created_at, kind and term. There is no text and no author, and it's kept for 90 days.

**Quotes respect deletions.** The report fetches the evidence items' current text through
`/api/info` (100 ids per request) when it's built. Deleted and removed items are left out,
and the quote is the sentence that carries the intent (`source_sentence`). Nothing quoted
is stored.

### 2.7 The weekly report

`wgra radar report --watchlist pkm [--week 2026-W45]`, from `term_daily` and
`intent_items`, every watchlist's `report` day. Per product:

1. **Flows:** switched to it and away from it, with the top destinations and origins,
   against the average of the 4 weeks before.
2. **At risk:** `considering` away from it, and alternatives sought to it.
3. **Why:** its top `reason` and `missing` terms.
4. **Complaints:** counts, plus complaint spikes the short-term detector found.
5. **Needs** in the watchlist's subreddits, grouped by shared phrases.
6. **Evidence:** up to 3 threads per line.

Every count shows the number of distinct authors. A line is marked rising only at twice
its 4-week average and at least 5 authors, the same kind of gate as `detect:`. Below 10,
counts are shown as counts, never as percentages.

**Delivery, free:** an HTML file (`--html report.html`), an ntfy message when it's ready,
and a "Churn radar" dashboard in Grafana. Email is optional, over SMTP (the standard
library, `SMTP_URL` in `.env`), through your own mailbox.

## 3. Delivery plan

### Phase 0: collect again (half a day)

* Run the stack on an always-on machine you already have (an old computer at home) or a
  free one (Oracle Cloud's Always Free ARM machine is the usual choice; check its current
  terms). A laptop works, but every hour it sleeps is lost, since raw text only lives for
  48 hours. Deploy lead–lag and intents (ARCHITECTURE.md §6, "Deploying it").
* **Done when:** `wgra status` and the ingestion dashboard show 7 complete days, and
  `wgra intents --scope sample --days 1` counts intents.

### Phase 1: watchlists and collection (about 3 days)

* `radar:` in `config.yaml` with validation (every alias belongs to one product, and the
  group exists), the pilot watchlist and its group, aliases as names.
* Brand search and comment trees, after checking what reddit's search API returns
  (comments or not, indexing delay, the result limit), and the `_search` scope.
* `wgra radar candidates --watchlist pkm --days 1`: per product and source, the items that
  name it and how many have an intent.
* **Done when:** a week of candidates tells us, per product and day, how many items name it
  and how many intents the patterns find.

### Phase 2: precision and stance (about 3 days)

* The watchlist filter, the fixes of §2.3, the `considering` kind with golden tests.
* `bench/intent_precision.py --watchlist`.
* **Done when:** both judges agree that at least 80% of watched-product switch, alternative,
  complaint and considering items are correct, 50 per kind on a held-out week. A paid
  product would need 90% (§7).

### Phase 3: reasons (about 3 days)

* `reason` and `missing` kinds, the word lists, golden tests from real sentences, and their
  gates in `config.yaml`.
* **Done when:** at least 75% of `reason` and `missing` items are judged right (50 each,
  held-out).

### Phase 4: the report (about 3 days)

* Migration 006 and `intent_items`, `wgra radar report`, quotes through `/api/info`, the
  HTML file, ntfy, the Grafana dashboard, and the weekly schedule in the analyzer loop.
* **Done when:** the report for a pilot week reads correctly end to end, and every number
  in it opens the threads behind it.

### Phase 5: pilot (4 weeks, about an hour a week)

* Run the PKM watchlist and read every report. Log per product and week: intents, distinct
  authors, and the share that has a reason.
* Gate 1 follows (§6).

## 4. Cost

| Item | Cost |
| --- | --- |
| Software | ClickHouse, Grafana OSS, ntfy, Python, as today. |
| Reddit | The free tier (100 requests a minute), for personal, non-commercial use. |
| Machine | One you have, or a free cloud tier. |
| Labeling | Your time: about 300 items for the precision checks of phases 2 and 3. |

## 5. Risks and open questions

* **Volume** is the main risk, and gate 1 tests it before anything else is built on it.
  Patterns miss paraphrases ("finally done with Notion"), so the pilot undercounts: read
  gate 1 as a lower bound. If it passes without a model, it would pass with one.
* **Reddit search** is unverified: whether it covers comments, how fast it indexes, and
  its result limits.
* **Reasons from word lists** catch what's spelled out. A report that says "no reason
  given" for most switches is honest but less useful. Phase 3 measures how many have one.
* **Astroturfing:** vendors' marketing posing as switchers. Distinct authors help, but
  account age isn't checked (it costs extra API calls, §7 of the architecture).
* **Everyday-word products** (Notion, Linear, Signal, Teams): aliases count in any case
  only inside a pattern, as `products_en.txt` does today, and phase 2 measures it.
* **Small numbers mislead.** The report shows counts and authors and marks only what
  passes the gates.
* Open: which category for the pilot (PKM proposed), and whether the first buyer is a
  vendor (their own churn) or an investor or analyst (a whole category).

## 6. Gates

1. **Volume (after the pilot).** Continue if at least 5 of the watchlist's products get 10
   or more switch, considering, alternative or complaint items a week from at least 8
   people. If not, reddit alone is too thin: add sources first (Hacker News, app store
   reviews, Bluesky) or stop.
2. **Data rights (before anyone outside sees a report).** Commercial use of reddit's API
   needs an agreement with Reddit (ARCHITECTURE.md §7). GummySearch, a reddit research
   product, shut down in late 2025 over licensing. The options:
   * Apply to Reddit for commercial access.
   * Sell a product built on sources whose terms allow it, and keep reddit for your own use.
   * Keep it personal.
3. **Demand (after gate 2).** Show a pilot report to 5 people who would buy it (product
   marketing or founders in the category). Continue if 3 ask for the next one or name a
   price.

## 7. Later: upgrades that cost something

Only after gate 1, and the paid ones only after gate 2.

* **A local model, free** (ARCHITECTURE.md §4.5). A small open model through Ollama, on
  the same machine if it has the memory, labels candidates while their text still exists:
  kind, stance, products, reasons and the missing feature. A CPU handles a few thousand
  short items a day. It replaces the word lists of §2.5 where it's measurably better, and
  recall goes up because it reads paraphrases.
* **A hosted model, paid.** The same labels from `claude-haiku-5-5` at low effort through
  the Message Batches API (50% off, results within 24 hours, inside the text window), with
  structured outputs. At 20,000 items a day, 20 per request, that's about $2 a day, or $1
  with the Batch API, at the list price of $0.10 per million input tokens and $0.50 per
  million output tokens. Target 90% precision, the bar for a paid report. Labels can't be
  redone once the text is gone, so every label stores the model and a prompt version.
* **The product** (after gates 1–3, 2–3 weeks):
  * Self-serve watchlists: enter a product and its competitors, get suggested aliases and
    subreddits (`suggest-subreddits` already finds subreddits by the terms they mention).
  * A report page per customer behind a login instead of Grafana, and billing.
  * An instant alert when complaints about a customer's own product spike (an outage or
    price backlash).
