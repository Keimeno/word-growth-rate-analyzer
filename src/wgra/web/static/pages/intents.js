// Why people mention things: switches, switches considered, alternatives, complaints, needs.
import { html } from "../vendor/preact-htm.js";
import { TimeChart } from "../charts.js";
import { Comments } from "../comments.js";
import { SERIES, count, decimal, formatDate, listParam, perThousand, setParams, times, useApi } from "../lib.js";
import {
  Badge, Card, DataCard, Empty, Field, MultiPicker, ScopePicker, Segmented, Select, Sparkline, Stat, Table, Tabs,
  TermButton,
} from "../ui.js";

const KINDS = [
  ["switch", "Switches", "Someone switched from one product to another: “switched from Notion to Obsidian”, “dropped ChatGPT for Claude”."],
  ["considering", "Considering a switch", "Someone thinks of switching or leaving, in the first person: “I'm thinking of switching from Notion to Obsidian”, “should I ditch Notion?”."],
  ["alternative", "Alternatives sought", "“Any alternatives to LastPass?”, “a good Plex alternative”, “I use Firefox instead of Chrome”."],
  ["complaint", "Complaints", "“Is Reddit down?”, “Teams is unusable”, “cancelled my Netflix subscription”, “Spotify raised prices”."],
  ["need", "Unmet needs", "“Is there an app to track my sleep?”, “I wish there was a way to …”, “I'd pay for an app that …”."],
];
const KIND_COLORS = Object.fromEntries(KINDS.map(([key], index) => [key, SERIES[index]]));
const RISING = [
  ["alternative", "Alternatives sought"],
  ["complaint", "Complaints"],
  ["considering", "Switches considered"],
];

export function IntentsPage({ params, scope, setScope, meta, openTerm }) {
  const range = params.range || "30d";
  const channels = listParam(params, "channels");
  const docTypes = listParam(params, "doc_types");
  const minAuthors = params.min_authors || "1";
  const minMentions = params.min_mentions || "2";
  const commentKinds = listParam(params, "comment_kinds");
  const term = params.term || "";
  const rising = params.rising || "alternative";
  const query = { scope, channels, doc_types: docTypes, range, min_authors: minAuthors, min_mentions: minMentions };
  const summary = useApi("intents", query, { refresh: 15 * 60e3 });
  const switches = useApi("intents-switches", query, { refresh: 15 * 60e3 });
  const risingState = useApi("intents-rising", { ...query, kind: rising }, { refresh: 15 * 60e3 });
  const needs = useApi("intents-needs", query, { refresh: 15 * 60e3 });
  const groupChannels = meta?.groups?.[scope] || [];
  const open = (intent, kind) => openTerm({ term: intent, kind, scope, range: "90d", bucket: "day" });
  const showComments = (intent) => {
    setParams({ term: intent || undefined });
    document.getElementById("comments")?.scrollIntoView({ behavior: "smooth" });
  };
  const toggleKind = (kind) => {
    const next = commentKinds.length === 1 && commentKinds[0] === kind ? [] : [kind];
    setParams({ comment_kinds: next.join(",") || undefined, term: undefined });
  };

  return html`
    <div class="page-head"><div>
      <h1>Why people switch</h1>
      <p>Why things are mentioned: who switches from what to what, who thinks about it, what they look for instead, what they complain about, and what they wish existed.</p>
    </div></div>
    <div class="filters">
      <${ScopePicker} meta=${meta} value=${scope} onChange=${setScope} />
      <${Field} label="Over"><${Segmented} label="Range" value=${range} onChange=${(v) => setParams({ range: v })}
        options=${[["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"]]} /><//>
      ${groupChannels.length > 0 && html`<${MultiPicker} label="Channels" options=${groupChannels.map((c) => [c, c])}
        value=${channels} onChange=${(v) => setParams({ channels: v.join(",") || undefined })} allLabel="All channels" />`}
      <${MultiPicker} label="Type" options=${(meta?.doc_types || []).map((t) => [t, `${t}s`])} value=${docTypes}
        onChange=${(v) => setParams({ doc_types: v.join(",") || undefined })} allLabel="Comments and posts" />
      <${Field} label="At least"><${Select} label="Minimum people" value=${minAuthors} onChange=${(v) => setParams({ min_authors: v })}
        options=${["1", "2", "3", "5", "10"].map((n) => [n, n === "1" ? "1 person" : `${n} people`])} /><//>
      <${Select} label="Minimum mentions in 7 days" value=${minMentions} onChange=${(v) => setParams({ min_mentions: v })}
        options=${["1", "2", "3", "5", "10"].map((n) => [n, `${n} mention${n === "1" ? "" : "s"} a week`])} />
    </div>

    <div class="stats" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      ${KINDS.map(([key, label, help]) => html`<${Stat} label=${label} help=${help}
        value=${summary.data ? count(summary.data.counts[key] || 0) : "…"}
        hint=${commentKinds.includes(key) ? "showing its comments" : "click for its comments"}
        pressed=${commentKinds.includes(key)} onClick=${() => {
          toggleKind(key);
          document.getElementById("comments")?.scrollIntoView({ behavior: "smooth" });
        }} />`)}
      <${Stat} label="Counting since" value=${summary.data?.since ? formatDate(summary.data.since) : "–"}
        help="Intents are found when comments are collected, so there's no history before that (plus the 48 hours of raw text before, with wgra backfill-intents)." />
    </div>

    <div class="stack">
      <${DataCard} state=${switches} title="Who switches from what to what" flush
        sub="Switches that happened, in this range. Click one for its trend and the comments behind it."
        help="mentions: comments and posts (each counts once). The other way: mentions of the reverse switch, so you see who's winning. Per 10,000: of all comments and posts here.">
        ${(d) => html`<${Table} rows=${d.flows} limit=${15} onRowClick=${(r) => open(r.term, "switch")}
          empty=${html`<${Empty} title="No switches in this range">Switches are rare: about 1 comment in 6,000 has any intent. Try a longer range or a bigger group.<//>`}
          columns=${[
            { key: "flow", label: "Switch", render: (r) => html`<${TermButton} term=${`${r.from} → ${r.to}`} onOpen=${() => open(r.term, "switch")} />` },
            { key: "mentions", label: "Mentions", num: true, sort: (r) => r.mentions, render: (r) => count(r.mentions) },
            { key: "authors", label: "People", num: true, sort: (r) => r.authors, render: (r) => count(r.authors) },
            { key: "other", label: "The other way", num: true, sort: (r) => r.other_way, render: (r) => count(r.other_way) },
            { key: "balance", label: "Balance", help: "This way (blue) against the other way (orange).",
              render: (r) => html`<div class="flow-bar" title=${`${r.mentions} this way, ${r.other_way} the other way`}>
                <span style=${`width:${(100 * r.mentions) / (r.mentions + r.other_way)}%;background:var(--s1)`}></span>
                ${r.other_way > 0 && html`<span style=${`width:${(100 * r.other_way) / (r.mentions + r.other_way)}%;background:var(--s2)`}></span>`}
              </div>` },
            { key: "per_10k", label: "Per 10,000", num: true, sort: (r) => r.per_10k, render: (r) => perThousand(r.per_10k) },
            { key: "daily", label: "Per day", render: (r) => html`<${Sparkline} values=${d.sparklines[r.term]} width=${120} label=${`${r.term} per day`} />` },
            { key: "comments", label: "", render: (r) => html`<button type="button" class="link-button small" onClick=${() => showComments(r.term)}>Comments</button>` },
          ]} />`}
      <//>

      <${DataCard} state=${risingState} flush>
        ${(d) => html`
          <${Tabs} value=${rising} onChange=${(v) => setParams({ rising: v })} tabs=${RISING} />
          <p class="secondary small" style="padding:10px 16px 0;margin:0">
            Rising: the last 7 days (today included) against the 28 days before, the most extra mentions first. Ignores the range above.
          </p>
          <${Table} key=${rising} rows=${d.entries} limit=${15} onRowClick=${(r) => open(r.term, rising)}
            empty=${html`<${Empty} title="Nothing rising here this week">Try fewer minimum mentions or people, or a bigger group.<//>`}
            columns=${[
              { key: "entity", label: rising === "considering" ? "Switch considered" : rising === "complaint" ? "About" : "Alternative to",
                render: (r) => html`<${TermButton} term=${r.entity} onOpen=${() => open(r.term, rising)} />
                  ${r.trend_z > 0 && html` <${Badge} tone="accent" title=${`strength ${decimal(r.trend_z)}`}>trending<//>`}` },
              { key: "mentions", label: "This week", num: true, sort: (r) => r.mentions, render: (r) => count(r.mentions) },
              { key: "daily", label: "Last 35 days", render: (r) => html`<${Sparkline} values=${d.sparklines[r.term]} width=${120} label=${`${r.entity} per day`} />` },
              { key: "excess", label: "Extra", num: true, sort: (r) => r.excess, render: (r) => `+${decimal(r.excess, r.excess >= 10 ? 0 : 1)}`,
                help: "Mentions above what its share before would give." },
              { key: "ratio", label: "vs usual", num: true, sort: (r) => r.times_usual, render: (r) => times(r.times_usual) },
              { key: "before", label: "Before, a week", num: true, sort: (r) => r.per_week_before, render: (r) => decimal(r.per_week_before),
                help: "The weekly average of the 28 days before." },
              { key: "authors", label: "People", num: true, sort: (r) => r.authors, render: (r) => count(r.authors) },
              { key: "comments", label: "", render: (r) => html`<button type="button" class="link-button small" onClick=${() => showComments(r.term)}>Comments</button>` },
            ]} />`}
      <//>

      <div class="grid grid-2">
        <${DataCard} state=${needs} title="Unmet needs" flush
          sub="The 10 needs mentioned most in each group and in the r/all sample, in this range. Not narrowed to the group picked above."
          help="A need is the 2–3 words after “is there an app to …”, “I wish there was a way to …”, “I'd pay for an app that …”, “does anyone know a tool for …”.">
          ${(rows) => rows.length ? html`<div class="needs">${Object.entries(groupBy(rows, "group_name")).map(([group, items]) => html`
            <div class="need-group"><h3>${group}</h3><ol>${items.map((item) => html`<li>
              <${TermButton} term=${item.need} onOpen=${() => openTerm({ term: item.term, kind: "need", scope: group, range: "90d", bucket: "day" })} />
              <span class="muted small"> ${count(item.mentions)}</span></li>`)}</ol></div>`)}
          </div>` : html`<${Empty} title="No needs in this range" />`}
        <//>
        <${DataCard} state=${summary} title="Intents per day" sub="Comments and posts with an intent, by kind">
          ${(d) => html`<${TimeChart} mode="stacked" daily height=${240} series=${KINDS.map(([key, label]) => ({
            name: label, color: KIND_COLORS[key],
            points: d.daily.filter((row) => row.kind === key).map((row) => [row.time, row.mentions]),
          })).filter((s) => s.points.length)} />`}
        <//>
      </div>

      <${Card} id="comments" title="Comments behind the intents" flush
        sub=${term ? html`Showing <strong>${term}</strong> · <button type="button" class="link-button" onClick=${() => setParams({ term: undefined })}>show all</button>`
          : "The newest first, from the last 48 hours. Click a kind above or Comments in a table to narrow it down."}
        actions=${html`<div class="chips">${KINDS.map(([key, label]) => html`<button type="button" class="chip"
          aria-pressed=${commentKinds.length === 0 || commentKinds.includes(key) ? "true" : "false"}
          onClick=${() => toggleKind(key)}>${label}</button>`)}</div>`}>
        <${Comments} intent term=${term} scope=${scope} kinds=${commentKinds} channels=${channels} doc_types=${docTypes} />
      <//>
    </div>`;
}

function groupBy(rows, key) {
  const groups = {};
  for (const row of rows) (groups[row[key]] ||= []).push(row);
  return groups;
}
