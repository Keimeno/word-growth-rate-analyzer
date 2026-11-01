# Churn radar: plan

**Status: phases 1 and 2 built on 2026-10-31 and collecting; phase 2's precision isn't
measured yet.** Phase 0 runs on a laptop for now. Phases 3–5 are a reference for building
them later.

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

* **Nothing was collecting.** The ingester and the analyzer stopped on 2026-10-12 at
  07:56 UTC, and the stored data covered only 2026-10-10 08:00 to 07:00 that day.
  Migrations 004 (lead–lag) and 005 (intents) were never applied. The stack was restarted
  on 2026-10-31 at 14:13 UTC from the repository root (phase 0), with both migrations, so
  the history that long-term trends, lead–lag and this radar need starts then.
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
  Phase 2 fixed these, not measured yet.
* **No stance, no reasons.** The patterns drop "thinking of leaving Notion" as a
  hypothetical. "Moved to Obsidian because Notion is useless offline" counts as
  `notion → obsidian`, and "useless offline", the part a customer cares about, is lost.
  Phase 2 added the stance (`considering`), phase 3 is the reasons.

## 2. Design

### 2.1 Watchlists

A watchlist is a set of products in one category, their names as written, and the
subreddits where the category talks. It lives in `config.yaml`, and its subreddits are a
group like any other, so the ingester tracks them completely and every dashboard and
detector already works on them. As built (`radar:` in [config.yaml](../config.yaml)):

```yaml
groups:
  pkm: [r/Notion, r/ObsidianMD, r/Evernote, r/OneNote, r/logseq, r/PKMS, r/NoteTaking, r/Zettelkasten]

radar:
  enabled: true
  search_interval_minutes: 15
  tree_after_hours: 24
  watchlists:
    pkm:
      group: pkm
      search: true            # also search all of reddit for posts naming a product
      products:               # canonical name: the other ways it's written
        notion: [Notion AI, notion.so]
        obsidian: [ObsidianMD, obsidian.md]
        evernote: []
        onenote: [One Note]
        logseq: []
        joplin: []
        anytype: []
        apple notes: []
        roam research: [RoamResearch]
```

Names are lowercased, and the canonical name is always one of them. A name can belong to
only one product of a watchlist. Products named with everyday words ("Bear", "Craft",
"Capacities") are left out of the pilot, since search would bring hundreds of unrelated
posts a day for them.

Watchlists do two jobs:

* **Recall.** Every single-word name counts as a name in any case and position, like the
  hand-kept `products_*.txt`, so "switched from evernote to obsidian" in lowercase counts
  (before, only "obsidian" was on the lists, so it didn't).
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
2. **Brand search** ([`sources/reddit/search.py`](../src/undercurrent/sources/reddit/search.py)). Every 15
   minutes per product, reddit search for new posts naming any of its names, anywhere
   (`"notion" OR "notion ai" OR "notion.so"`, newest first). Checked on 2026-10-31:
   * Search finds posts only. `type=comment` is ignored.
   * New posts show up within about 2 minutes.
   * `"Notion"` matched 100 posts in 12 hours from 97 subreddits, most of them about the
     word (r/spirituality, r/teslore). `title:"Notion"` matched 100 in 87 hours, a third
     of them in r/Notion.

   The radar searches the full text anyway. Unrelated posts cost little to store, the
   watchlist filter drops them, and the full text finds posts whose title doesn't name the
   product.
3. **Comment trees.** A post from search whose title names a watched product and asks or
   tells about a switch ("alternatives", "switch", "leaving", "vs", "migrate", "replace",
   "moving") gets its full comment tree fetched once, 24 hours after it was posted. That's
   up to 500 comments in one request, without those behind "load more". The answers under
   "Alternatives to Notion?" are where the reasons are.

Search hits from tracked subreddits are skipped, since the stream already has them. A
tree's comments that are already stored (the r/all sample caught them, or the tree was
fetched before a restart) are skipped too. The rest are stored and extracted like any item,
in a channel of their own, `r/_search`, like the sample's `r/all`. Its counts aren't shares
of anything (search isn't a complete stream), so it's in no group and not `analyzed` in the
`channels` table: the detectors and alerts never see it. Only the radar counts it. Budget:
each search is polled at a fixed interval, and its share comes off the tracked feeds' budget
like the r/all sample's. For 9 products
that's 36 requests an hour, plus a few dozen trees a day.

### 2.3 Precision without a model

On top of the watchlist filter, take the open fixes from §4.7 "Still open":

* Fix the trimming bug: when x isn't a name, reject the match instead of skipping forward
  to a later name ("a free alternative to photoshop use Krita" counts `krita`).
* Reject cuts that drop a lowercase head noun ("Figma's components").
* Add game characters and languages to `generic_en.txt`, regenerate `names_en.txt` from
  48 hours of items (`bench/intent_names.py`).

Measure with `bench/intent_precision.py`, with a new `--watchlist pkm` option that samples
only intents about watched products. Hand-labeling is the only cost.

As built (phase 2): the filter is `products_of` in
[`radar/candidates.py`](../src/undercurrent/radar/candidates.py), which
`undercurrent radar candidates` and `bench/intent_precision.py sample --watchlist` share.
The fixes are in
[ARCHITECTURE.md §4.7](ARCHITECTURE.md#47-intents-why-people-mention-things): one word in
front of a name can be trimmed, more can't; a name with lowercase words cut after it doesn't
count when it's possessive, has a determiner or the pattern ends the entity ("Figma's
components", "the Windows sound panel"); 210 languages, countries, country codes and game
characters in `generic_en.txt`. `names_en.txt` isn't regenerated yet: that needs 48 hours
of items, which are there after 2026-11-02 15:00 UTC.

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

As built (phase 2), in [`text/intents.py`](../src/undercurrent/text/intents.py), english
only:

* The considering verbs as planned, plus "planning to" or "on", with adverbs in between
  ("I'm seriously thinking of"), and with the "I" left out at the start of a sentence
  ("Thinking about leaving Notion"). Negated ("I'm not thinking of"), "why should I" and
  third persons ("my boss is thinking of") count as nothing, and so does "if", "would",
  "could", "might" or "unless" anywhere before the first product.
* `x → y`: switching, migrating, moving or jumping ship from x to y (or to y from x, with up
  to two words in between: "moving my notes from Notion to Obsidian"), leaving, quitting,
  ditching or abandoning x for y, replacing x with y.
* `x`: leaving, quitting, ditching, abandoning, cancelling, uninstalling or deleting x,
  getting rid of it, unsubscribing from it, switching or moving (away) from or off it. What
  follows x has to end the thought ("for good", "because …", the end of the sentence), so
  "leaving Notion open" counts as nothing. When a sentence also names where to, only the
  flow counts ("leaving Notion for Obsidian" is `notion → obsidian`, not also `notion`).
* A switch still needs to have happened: "should I switch from Notion to Obsidian?" is
  only `considering`, and advice ("you should switch from …") is nothing.

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

`items.intents` loses its urls with the text after 48 hours, but a weekly report needs
links from the whole week. A new table `intent_items`, filled by a materialized view from
`items` for every intent term: id, url, the channel, created_at, kind and term (the real
subreddit is in the url). There is no text and no author, and it's kept for 90 days.

**Quotes respect deletions.** The report fetches the evidence items' current text through
`/api/info` (100 ids per request) when it's built. Deleted and removed items are left out,
and the quote is the sentence that carries the intent (`source_sentence`). Nothing quoted
is stored.

### 2.7 The weekly report

`undercurrent radar report --watchlist pkm [--week 2026-W45]`, from `term_daily` and
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

### Phase 0: collect again (half a day; running since 2026-10-31, on a laptop)

* Run the stack on an always-on machine you already have (an old computer at home) or a
  free one (Oracle Cloud's Always Free ARM machine is the usual choice; check its current
  terms). A laptop works, but every hour it sleeps is lost, since raw text only lives for
  48 hours. Deploy lead–lag and intents (ARCHITECTURE.md §6, "Deploying it").
* Done on 2026-10-31: the stack runs from the repository root on `develop`, migrations 004
  and 005 applied, on the laptop it was developed on. Still open: an always-on machine.
* **Done when:** `undercurrent status` and the ingestion dashboard show 7 complete days, and
  `undercurrent intents --scope r/all --days 1` counts intents.

### Phase 1: watchlists and collection (built 2026-10-31, collecting)

Built:

* `radar:` in `config.yaml` with validation (every name belongs to one product of a
  watchlist, the group exists, product names can't contain `→`, `:` or `·`), the pilot
  watchlist and its group `pkm`, single-word names as names in intents (`configure_names`
  in `text/intents.py`, set by the ingester and the backfill).
* Brand search as feeds of their own (`Feed.search`, fixed interval, budget taken off the
  tracked feeds), comment trees every 10 minutes, the `_search` scope (since the
  cross-platform phase 1 the channel `r/_search`,
  [`sources/reddit/search.py`](../src/undercurrent/sources/reddit/search.py)). What reddit's
  search returns is in §2.2.
* `undercurrent radar candidates [--watchlist pkm] [--days 1]`
  ([`radar/candidates.py`](../src/undercurrent/radar/candidates.py)): per product and where
  it comes from, the comments and posts naming it (by its most named name) and those with an
  intent about it, per kind.
* 26 tests: config, names, the search scope, titles that want a tree, the candidates, and
  against ClickHouse the due trees and the candidates query.

**Done when:** a week of candidates tells us, per product and day, how many items name it
and how many intents the patterns find. That's 2026-11-07 at the earliest.

### Phase 2: precision and stance (built 2026-10-31, measurement pending)

Built:

* The watchlist filter: `products_of` counts an intent for a product when its entity is a
  watched alias, or for a switch or a switch considered either side is. Needs are never
  about a product. `undercurrent radar candidates` shows switch, considering, alternative
  and complaint per product.
* The fixes of §2.3 in `text/intents.py` and `generic_en.txt` (the trimming bug, cuts that
  drop a part of the product, languages, countries and game characters), and advice ("you
  should switch from …") no longer counts as a switch.
* The `considering` kind (§2.4), with its gates in `config.yaml` (3 mentions by 3 authors
  short term, 2 a week long term, onsets at 3), `--kind considering` in
  `undercurrent intents`, a stat and a "Rising: switches considered" table on the Intent
  radar dashboard.
* `bench/intent_precision.py sample --watchlist pkm`: only intents about the watchlist's
  products, with the products each is about. It sets the watched names like the ingester
  and refuses to write the sample inside the repository.
* 55 more test cases (422 in all): golden tests of every fix and of `considering`
  (positives and the negatives of §2.4), the filter on extracted intents, the candidates
  with `considering`, against ClickHouse included, and the shipped gates for every kind.

Still open:

* Regenerate `names_en.txt` from 48 hours of items (`bench/intent_names.py`), after
  2026-11-02 15:00 UTC.
* Measure: sample a held-out week with `--watchlist pkm` and label it. Nothing is labeled
  yet. The sample holds reddit text, so it stays outside the repository and is deleted
  after labeling.

**Done when:** both judges agree that at least 80% of watched-product switch, alternative,
complaint and considering items are correct, 50 per kind on a held-out week. A paid
product would need 90% (§7).

### Phase 3: reasons (about 3 days)

* `reason` and `missing` kinds, the word lists, golden tests from real sentences, and their
  gates in `config.yaml`.
* **Done when:** at least 75% of `reason` and `missing` items are judged right (50 each,
  held-out).

### Phase 4: the report (about 3 days)

* Migration 006 and `intent_items`, `undercurrent radar report`, quotes through `/api/info`,
  the HTML file, ntfy, the Grafana dashboard, and the weekly schedule in the analyzer loop.
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
* **Reddit search finds posts only** (checked, §2.2). Comments that name a product in a
  subreddit we don't track are only found inside a comment tree or by the r/all sample.
  Still unknown: how deep search pages go, which only matters if a product gets more than
  100 new posts in 15 minutes.
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
