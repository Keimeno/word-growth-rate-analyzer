# Public forecast ledger: plan

**Status: planned, not started.** Nothing of it exists yet. It needs real edges first,
which need 4–6 weeks of history (§1).

The analyzer already forecasts which subreddits will pick up a term that is rising
somewhere else, and when ([ARCHITECTURE.md §4.6](ARCHITECTURE.md#46-lead-lag-early-warning)).
Those forecasts live in a table we can rewrite, so showing them to anyone afterwards proves
nothing: a forecast shown after the outcome looks like hindsight, however it was made.

The ledger publishes every forecast at the moment it's made, in a form nobody can backdate
or quietly drop, us included, and grades each one when it resolves:

* **Calls**, one per story and follower: what will reach where, with what probability
  against what base rate, expected when, and due by when.
* **A proof of when.** Every call is a line in an append-only hash chain, and the chain's
  latest hash is timestamped in the Bitcoin blockchain through OpenTimestamps after every
  run. Free, no account, and anyone can check it without trusting us.
* **The record**: hits, misses, calibration against the base rate, and the warning time,
  over every call made, never a selection.
* **A public page**, and optionally a Bluesky account that posts the strongest calls and
  replies to each when it resolves.

It's also the demonstration. A post can link a call made two days before the story arrived,
with its proof, instead of a screenshot. It's only worth that if the record is good, so
the ledger runs privately first, already stamped, and goes public only past gate 1 (§6).

**It costs nothing to run**, like the rest of v2.

## 1. Where things stand (checked 2026-11-01)

* **Forecasts are built** (ARCHITECTURE.md §4.6, `src/undercurrent/leadlag/forecasts.py`).
  After every analysis run, `decide` makes a forecast for each leader burst that a follower
  hasn't picked up, with its probability at creation, its interval, the base rate, the
  expected time and the due time (7 days after the leader's onset). `resolve` marks it a
  hit or a miss later. The probability is never updated afterwards, so the record is what
  was said when it was said. Forecast alerts are off (`forecast.alert`).
* **There are no edges and no forecasts.** The database was recreated on 2026-10-31 at 15:50
  UTC for cross-platform phase 1 (CROSS-PLATFORM.md §8.10), and history restarted then.
  `undercurrent edges` says "no edges yet" and `undercurrent forecasts` has none. The first
  edges are expected after 4–6 weeks (2026-11-28 to 2026-12-12). Replay numbers are worth
  reading after 6 weeks.
* **The only measured record is synthetic.** On the benchmark history,
  `undercurrent replay --forecast` gave a precision of 87% with daily steps. On the harder
  history with planted followers it gave 43%, calibrated, with a median warning of 2.7 days.
  There is no number from real data.
* **Nothing proves when a forecast was made.** `forecasts` is a ReplacingMergeTree: rows
  are rewritten when they resolve, and could be deleted or backdated. That's fine for a
  dashboard and worthless as evidence.
* **The stack runs on a laptop.** Every hour it sleeps, collection stops, and Reddit's
  listings don't go back far enough to fill the gap. A follower crossing during a gap
  goes unseen, so its forecast looks like a miss. An always-on machine is still open
  (CHURN-RADAR.md phase 0).

## 2. Design

### 2.1 What a call is

A call is the unit the replay scores (`evaluate.first_per_follower`): per event (kind,
term, start) and follower, the earliest forecast, and the likeliest leader's if several
were made in the same run. A forecast for the same follower made later, after another
leader picked the term up, is not a new call. That keeps the ledger and the replay counting
the same thing, so the replay's numbers predict the ledger's.

Every call with a probability of at least `ledger.min_probability` goes in, by default
`forecast.min_probability` (0.3), so every forecast the analyzer stores. Misses at 35% are
part of what makes 60% mean something. The rule is fixed before the ledger starts and
written on the page. Changing it later starts a new section of the record rather than
rewriting the old one (§2.6).

A call says what the forecast row says, and nothing from the text:

* the kind and term (`claude code`, `notion → obsidian`), the leader and its onset, the
  follower and whether it's a group measured without the leader;
* the probability with its interval, the base rate and the lift;
* the edge it came from: its events, hits and median lag (IQR);
* the expected time and the due time.

No comment text, no authors, no links to comments, no examples. Terms and subreddit names
are aggregates. The page links the term to a Reddit search at most.

### 2.2 The chain

The ledger is a sequence of lines, JSON with sorted keys and no spaces, UTF-8, one object a
line, numbered from 1. Each line carries the SHA-256 of the line before it (`prev`), so
changing or removing any line changes every hash after it. Lines are only ever appended. A
correction is a new line that says what it corrects.

```json
{"at":"2026-12-15T09:15:04Z","call":{"base_rate":0.12,"due_by":"2026-12-22T06:00:00Z","edge":{"events":14,"hits":8,"lag_median_h":30,"lag_q25_h":19,"lag_q75_h":44},"expected_at":"2026-12-16T12:00:00Z","follower":"r/technology","interval":[0.41,0.73],"kind":"phrase","leader":"r/LocalLLaMA","leader_onset":"2026-12-15T06:00:00Z","lift":4.8,"probability":0.58,"term":"<term>","topic":"tech","without_leader":false},"prev":"9f2c…","seq":1042,"type":"call"}
{"at":"2026-12-16T15:15:02Z","prev":"41aa…","resolution":{"call":1042,"follower_onset":"2026-12-16T15:00:00Z","outcome":"hit","warning_h":29.8},"seq":1107,"type":"resolution"}
```

The numbers show the form; there are no real ones yet.

Line types:

| Type | Written | What it says |
| --- | --- | --- |
| `call` | when the forecast that is the call is stored | §2.1 |
| `resolution` | when `resolve` marks it | hit or miss, the follower's onset, the warning time (onset − call), the lag against the expected one |
| `revision` | when the event closes and its final onsets disagree with a resolution | the old and the new outcome, why (§2.4) |
| `void` | when a call's window had a collection gap (§2.4) | the gap, from `polls` |
| `reveal` | at the resolution of a withheld call (§2.5) | the term and its salt |
| `edges` | after the daily edge run | the SHA-256 of that day's edges, exported as a file next to the ledger |
| `rules` | at the start, and when a rule changes | the ledger's settings and the analyzer's version |

The `edges` line commits the edges a day's calls will come from, before they're made. A
reader can see that the calls follow from them, and that the edges weren't fitted
afterwards.

**Storage.** A ClickHouse table `ledger` (plain MergeTree, ordered by `seq`, never
replaced or deleted) with `seq`, `type`, `line` (the exact bytes), `hash` and `at`, and a
table `ledger_stamps` with the hash of every stamped head and its `.ots` proof. Migration
00N, the next free number (the churn radar's phase 4 plans 006). The `forecasts` table
stays the working store. The ledger is appended in `run_forecasts`, after
`write_forecasts`, from what that run made and resolved. A ledger failure is logged and
retried at the next run, and doesn't stop alerts or digests, like forecasts today.

One writer: only the analyzer with `ledger.enabled` appends, the way only one analyzer may
send notifications (README). A second writer would fork the chain. `seq` is read and
written in one process, and the append checks that `prev` is still the last hash.

### 2.3 The proof: OpenTimestamps

After every run that appended lines, the analyzer submits the SHA-256 of the newest line
to the OpenTimestamps calendars (`a.pool.opentimestamps.org`, `b.pool.opentimestamps.org`,
`a.pool.eternitywall.com`; free, no account or key). Each calendar answers at once with a
pending proof and puts the hash into a Bitcoin transaction within hours. An hourly step
upgrades pending proofs (`ots upgrade`) until they carry the block header. Since every
line's hash is inside the next one's, a proof of the newest line covers every line before
it.

What it proves: this line, and so every call before it, existed no later than that
block's time. Anyone can check it at opentimestamps.org, or with `ots verify` and a Bitcoin
node (a pruned one is enough). The calendars' pending answer comes within seconds, and the
calendars are run by others, so it's already evidence before Bitcoin confirms.

Why not something simpler:

* **Bluesky posts** can't prove a time: `createdAt` is set by the client and can be
  backdated (Bluesky's timestamp guide), and posts can be deleted. They're the readable
  channel (§2.7), not the proof.
* **Git commits** carry dates the committer chooses. A public mirror of the ledger on
  GitHub is still useful for diffs and history, as an extra.
* **A timestamping authority** (RFC 3161) is trusted, not verified, and the free ones
  promise nothing.

Python: the OpenTimestamps client (`opentimestamps-client`, and the library under it) for
the proof format, with the calendars reached over httpx. Full verification needs a Bitcoin
node, which the stack doesn't run. So `undercurrent ledger verify` follows each proof to its
block and takes the block's header from a public block explorer's API, and the page sends
readers to opentimestamps.org (§2.6). Phase 1 checks the current versions and the explorer.

### 2.4 Resolution, revisions and gaps

**Resolution** is `resolve` as it is: a hit when the follower crosses by the due time, a
miss an hour after the due time passes. The resolution line adds the warning time, from
the call to the follower's onset.

**Hits without warning.** Onsets are recomputed until an event's span is over, and a
recomputed onset can move to before the call (ARCHITECTURE.md §4.6). The forecast was
true, so it counts as a hit for the record and the calibration. But it gave no warning, so
the page marks it "hit, no warning" and leaves it out of the median warning time.

**Revisions.** When an event closes (its span is over, about 17 days), the ledger compares
its final onsets with every resolution of its calls. Where they disagree, a `revision` line
records the new outcome and the record counts the final one. The number of revisions is on
the page. Resolving only at closing would be cleaner, but would take two and a half weeks
per call, and the point is to see a call come true.

**Gaps.** A call is void when the ingester had no successful poll (`polls.status` 200) of
a feed the follower is collected through for more than `ledger.void_gap_hours` (6) inside
the call's window. `polls` is kept per feed, not per channel. The follower's feeds come from
the same packing the ingester uses (`build_feeds`): its subreddits' multireddit feeds,
every member's for a group, and `sample-all` for r/all. The rule is fixed before the
ledger starts. A void is written as a line, listed,
and counted on the page, never removed. It can't be used to hide a miss, because it
depends only on the polls and not on the outcome. The check runs before resolution, for
hits too.

### 2.5 Withheld terms

Terms come from Reddit. Now and then one is a slur, or the name of a private person in a
news story. That shouldn't be published as a live prediction. A word list,
`ledger.withhold` (`src/undercurrent/ledger/withhold_en.txt`, one term a line, like the
intent lists), decides automatically. For a matching term,
the call line carries `sha256(salt + term)` instead of the term, with a random 16-byte salt
kept in `ledger_secrets`. The `reveal` line at resolution publishes both, so anyone can
check that the withheld call said what it now says. A withheld call counts in the record
like any other. The page shows "withheld until it resolves" and the number of them.

The list starts as a slur list. A word list can't recognise people's names, so gate 3
reads a week of private calls by hand before anything is public, and adds what it finds.

**Redaction**, for what the list missed: `undercurrent ledger redact <seq>` publishes that
line's hash in place of the line, in the page and in the downloadable ledger. The chain
still verifies, because the next line only needs the hash. The call still counts, and the
page lists every redaction with its line number, so it can't hide a miss either.

### 2.6 The page

`undercurrent ledger site --out <dir>` builds a static site from the ledger, with no server
and no JavaScript beyond small scripts, in the brand of [BRAND.md](BRAND.md):

* **Record.** Calls, hits, misses, pending, void, withheld. Calibration per probability
  band with Wilson intervals and the base rate beside it. Brier score against forecasting
  the base rate. Median warning time and its IQR. Counts below 10 stay counts. Each
  number has its date range and a "since" when a `rules` line split the record.
* **Pending calls**, the next expected first: term, leader → follower, probability with
  interval against the base rate, expected time, due by, the call's line number and hash.
* **Resolved calls**, newest first, with outcome, warning and lag against the expected one.
* **Per edge**: its calls and how they turned out.
* **Method**: what a call is (§2.1), the rules fixed in advance (the `rules` lines), how
  revisions and voids work, and what the ledger can't prove (§2.8).
* **Verify**: the ledger as `ledger.jsonl`, the edges files, the `.ots` proofs, and the
  steps to check a call. Recompute the chain with a dozen lines of Python, printed on the
  page, then drop the proof on opentimestamps.org.

Hosting, free: Cloudflare Workers static assets, as for zenarios-web (`wrangler deploy`
with a token limited to that Worker), or GitHub Pages. Rebuilt and deployed after every run
that appended lines, at most every 15 minutes. Check the free tier's current limits in
phase 2.

### 2.7 Bluesky (optional)

A bot account (self-labelled as a bot, as Bluesky's developer guidance asks), posting with
an app password through the XRPC API over httpx. It keeps its session and refreshes it,
because logins are limited to about 30 per 5 minutes and 300 a day. The write limits
(about 5,000 points an hour, 3 per post) are far above what it needs.

* **Calls**, by a rule fixed in advance: the same as forecast alerts (probability ≥ 0.6, an
  edge of at least 10 events, one per term), at most `ledger.bluesky.max_per_day` (3).
  Worded like `forecast_message`, with no emoji (BRAND.md §2), with the line number, the
  first 12 characters of its hash and a link to it.
* **Resolutions** as a reply to their call, misses included: "Came true: r/technology
  crossed Wed 15:00 UTC, 30 hours after the call." / "Missed: r/technology didn't cross by
  Tue 22 Dec."
* **A weekly record** post: the week's calls and outcomes, the running calibration.

Posts are a window onto the ledger, not the record. The record always counts every call,
so choosing what to post can't improve it. The posting rule is on the method page.

### 2.8 What it can't prove

The page says this plainly:

* **That nothing was withheld before it was written.** The chain proves when a line
  existed, not that every forecast became a line. Running two ledgers and publishing the
  luckier one is possible in principle. What speaks against it: the rules and the daily
  edges committed in advance, calls that follow from those edges, steady numbers of calls
  per day, and the code, if the repository is public.
* **That a hit is skill rather than a story going everywhere at once.** The base rate and
  the lift answer that: a 58% call against a 12% base rate claims something, and one
  against 50% doesn't. The Brier score against the base rate is the headline, not the hit
  rate.
* **The future.** A good record over three months says the edges held then.

### 2.9 config.yaml

```yaml
ledger:
  enabled: false
  # calls: every stored forecast at this probability or more (forecast.min_probability)
  min_probability: 0.3
  # a call is void when a feed of its follower had no successful poll for this long
  # inside its window
  void_gap_hours: 6
  withhold: withhold_en.txt  # in src/undercurrent/ledger/
  stamp: true                # OpenTimestamps after every run that appended lines
  calendars:
    - https://a.pool.opentimestamps.org
    - https://b.pool.opentimestamps.org
    - https://a.pool.eternitywall.com
  site:
    deploy: false            # build and deploy the page after appending (wrangler)
  bluesky:
    enabled: false
    min_probability: 0.6
    min_edge_events: 10
    max_per_day: 3
```

In `.env`: `LEDGER_DEPLOY_TOKEN` (the Worker's), `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`.
Changing `min_probability`, `void_gap_hours` or the posting rule writes a `rules` line.

## 3. Delivery plan

### Phase 0: history and a machine (waiting, no work)

* An always-on machine for the stack (CHURN-RADAR.md phase 0). On the laptop, voids would
  make the record unreadable.
* The first edges (2026-11-28 to 2026-12-12), and
  `undercurrent replay --forecast --events stored` over the real history, read as in
  ARCHITECTURE.md §4.6.
* **Done when:** there are edges, and the replay's precision and calibration are known,
  good or bad.

### Phase 1: the ledger, private (about 2 days)

* Migration: `ledger`, `ledger_stamps`, `ledger_secrets`. `ledger:` in `config.yaml` with
  validation. The withhold list.
* `src/undercurrent/ledger/`: the call selection (§2.1, sharing `first_per_follower`), the
  line format and the chain, appending in `run_forecasts`, revisions at event closing (in
  the daily lead–lag run), voids from `polls`, the daily `edges` line, OpenTimestamps
  stamping and the hourly upgrade.
* CLI: `undercurrent ledger show [--pending]`, `undercurrent ledger verify` (recomputes the
  chain, checks every proof, prints the first line that doesn't match),
  `undercurrent ledger record` (the numbers of §2.6), `undercurrent ledger export --out`,
  `undercurrent ledger redact <seq>`.
* Tests: the selection against `evaluate`'s on the same forecasts, the chain (a changed,
  removed or reordered line fails `verify`, a redacted one doesn't), canonical JSON (the
  same object gives the same bytes), revisions, voids, withhold and reveal, one writer,
  stamping with a mocked calendar. End to end in a throwaway ClickHouse database on the
  synthetic history: the ledger's calls and outcomes equal `evaluate`'s for the same steps.
* Then it runs privately, stamped from the first line. Its proofs stay valid when it's
  published later, so the record that goes public is already weeks old and checkable.
* **Done when:** `undercurrent ledger verify` passes on two weeks of live ledger, and the
  record agrees with `undercurrent forecasts --days 14`.

### Phase 2: the page (about 2 days)

* `undercurrent ledger site`, its pages (§2.6), the brand's tokens, light and dark, a phone
  width.
* Deploy after appending (`site.deploy`), on Cloudflare or GitHub Pages, not public until
  gates 1–3 pass: an unlisted address, or Cloudflare Access in front.
* **Done when:** someone who has never seen the project checks a call from the page alone
  and opentimestamps.org, and says what it claimed and whether it came true.

### Phase 3: Bluesky (about 1 day)

* The poster, replies on resolution, the weekly record, the posting rule as a `rules`
  line. A handle under the project's name once the trademark search of BRAND.md §3 is done.
* **Done when:** a week of calls and resolutions posted on a private test account matches
  the ledger line for line.

### Phase 4: public

* Gates 1–3 (§6), then the page's address public, Bluesky on. The post that announces it
  links the oldest call that came true with a long warning, and the record page.

## 4. Cost

| Item | Cost |
| --- | --- |
| OpenTimestamps | Free: public calendars, no account. Bitcoin fees are paid by the calendars. |
| Hosting | Cloudflare Workers' or GitHub Pages' free tier: a static site of a few MB. |
| Bluesky | Free. |
| Machine | The one the stack runs on. The ledger adds a few queries per run and a few MB a year. |

## 5. Risks and open questions

* **The record may be bad.** That's what it's for. If gate 1 fails, the ledger stays
  private and the edges get tuned. The private ledger stays stamped, so a later public
  start can still show the earlier calls, bad ones included.
* **Too few calls.** Edges need history and pass strict gates, so for months there may be a
  few calls a week. Below 30 resolved calls the page shows counts and no calibration
  chart.
* **Trivial hits.** A launch posted everywhere in the same hour makes calls that come
  true with no warning. The warning time, "hit, no warning" and the base rate show it. A
  minimum warning for calls (call only if the expected lag is at least 6 hours) is an
  option once there's data.
* **Volume bias** (§7 of the architecture, CROSS-PLATFORM.md §2.5): big subreddits cross
  sooner, so some edges are size, not influence. The record measures the forecasts as they
  are, whatever the reason they work.
* **Content.** The withhold list misses what it doesn't list. Gate 3 reads a week by hand,
  and redaction (§2.5) handles the rest after the fact. A redacted term was public until
  then, on the page and on Bluesky if it was posted, so the posting rule stays strict.
* **Reddit's terms.** The ledger publishes no user content, only terms, subreddit names
  and numbers derived from them. Whether Reddit's Data API Terms allow publishing that for
  free, outside a product, needs reading. A third-party summary says the terms were
  revised in July 2026 and require an agreement for any use they don't expressly permit.
  An announcement on LinkedIn may also read as promoting a product. Gate 2.
* **The calendars** may be down. The next run stamps the newer head, which covers the
  older lines. A head that was never stamped is listed on the page.
* **The name.** Public under "Undercurrent" before the trademark search of BRAND.md §3 is
  a risk, small while nothing is sold.
* Open: whether intents (`notion → obsidian` spreading) are calls from the start or after
  their precision is measured (CHURN-RADAR.md phase 2). Proposed: words, phrases and
  domains first.

## 6. Gates

1. **Worth publishing (after 4 weeks of private ledger).** At least 30 resolved calls,
   calibrated within 10 points in every band with 10 or more calls, a Brier score below the
   base rate's, and a median warning of at least 12 hours (the thresholds of
   CROSS-PLATFORM.md gate 2). If not, keep it private and tune.
2. **Data rights (before the page is public).** A reading of Reddit's current Data API
   Terms and Developer Terms on publishing derived, non-user content for free, or an answer
   from Reddit. If no, wait for the cross-platform sources whose terms allow it (Bluesky,
   Wikipedia; CROSS-PLATFORM.md §5) and publish calls about those only.
3. **Content (before the page is public).** A week of private calls read by hand. Nothing
   that would embarrass the project is published in plain text.

The earliest public start: the first edges around 2026-12-05, four weeks of private
ledger, so early January 2027.

## 7. Decisions

| Question | Proposed |
| --- | --- |
| Which forecasts are calls | Every stored one (≥ 0.3), so the calibration covers every band |
| One call per | Event and follower, the earliest (the replay's unit) |
| Proof | Hash chain + OpenTimestamps; Bluesky and git only as readable copies |
| Resolution | Immediate, with revision lines at event closing |
| Gaps | Void by a fixed rule on `polls`, listed and counted |
| Sensitive terms | Withheld by a word list, salted hash, revealed at resolution; redaction for misses of the list |
| Hosting | Cloudflare Workers static assets, as zenarios-web |
| Bluesky | After the page, alert-level calls only, at most 3 a day |
