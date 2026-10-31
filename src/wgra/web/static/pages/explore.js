// Explore: how often terms are mentioned over time, where, and the comments behind them.
import { html, useState } from "../vendor/preact-htm.js";
import { TimeChart } from "../charts.js";
import { Comments } from "../comments.js";
import { SERIES, count, listParam, perThousand, setParams, useApi } from "../lib.js";
import { Card, DataCard, Empty, Field, MultiPicker, ScopePicker, Segmented, Select, Table } from "../ui.js";

const RANGES = [["24h", "24h"], ["2d", "2 days"], ["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"], ["26w", "6 months"], ["52w", "1 year"]];
const MAX_TERMS = 8;

function TermsInput({ terms, onChange }) {
  const [draft, setDraft] = useState("");
  const add = (text) => {
    const added = text.split(",").map((t) => t.trim().toLowerCase().replace(/\s+/g, " ")).filter(Boolean);
    const next = [...new Set([...terms, ...added])].slice(0, MAX_TERMS);
    if (next.length !== terms.length) onChange(next);
    setDraft("");
  };
  return html`<div class="field" style="flex:1 1 360px">
    <span class="label">Terms</span>
    <div class="chips" style="flex:1;align-items:center">
      ${terms.map((term, index) => html`<button type="button" class="chip" aria-pressed="true" title="Remove"
        onClick=${() => onChange(terms.filter((t) => t !== term))}>
        <span class="key" style=${`background:${SERIES[index]};margin-right:0`}></span>${term}<span class="x">✕</span></button>`)}
      ${terms.length < MAX_TERMS && html`<input class="input" style="flex:1;min-width:140px" value=${draft}
        placeholder=${terms.length ? "Add a term…" : "Type a term, then Enter"} aria-label="Add a term"
        onInput=${(event) => {
          const value = event.target.value;
          if (value.includes(",")) add(value);
          else setDraft(value);
        }}
        onKeyDown=${(event) => {
          if (event.key === "Enter" && draft.trim()) add(draft);
          if (event.key === "Backspace" && !draft && terms.length) onChange(terms.slice(0, -1));
        }}
        onBlur=${() => draft.trim() && add(draft)} />`}
    </div>
  </div>`;
}

export function ExplorePage({ params, scope, setScope, meta }) {
  const terms = listParam(params, "terms", ["ai", "claude", "gpt"]).map((t) => t.trim()).filter(Boolean);
  const range = params.range || "2d";
  const bucket = params.bucket || "auto";
  const rate = params.rate || "pooled";
  const channels = listParam(params, "channels");
  const docTypes = listParam(params, "doc_types");
  const isGroup = Boolean(meta?.groups?.[scope]);
  const query = { terms, scope, range, bucket, channels, doc_types: docTypes };
  const state = useApi("explore", query, { skip: !terms.length });
  const colors = Object.fromEntries(terms.map((term, index) => [term, SERIES[index]]));
  const series = (value) => (data) => terms.map((term) => ({
    name: term, color: colors[term],
    points: data.points.filter((p) => p.term === term).map((p) => [p.time, p[value]]),
  })).filter((s) => s.points.length);
  const shareKey = rate === "macro" && isGroup ? "macro" : "pooled";
  const daily = state.data && state.data.bucket !== "hour";
  const groupChannels = meta?.groups?.[scope] || [];

  return html`
    <div class="page-head"><div>
      <h1>Explore</h1>
      <p>How often terms are mentioned over time, where, and by whom. Shares are per 1,000 comments and posts, so the daily and weekly swings in activity cancel out.</p>
    </div></div>
    <div class="filters">
      <${TermsInput} terms=${terms} onChange=${(next) => setParams({ terms: next.join(",") })} />
    </div>
    <div class="filters" style="padding-top:0">
      <${ScopePicker} meta=${meta} value=${scope} onChange=${setScope} />
      <${Field} label="Over"><${Segmented} label="Range" value=${range} onChange=${(v) => setParams({ range: v })} options=${RANGES} /><//>
      <${Field} label="Per"><${Select} label="Bucket" value=${bucket} onChange=${(v) => setParams({ bucket: v })}
        options=${[["auto", "Automatic"], ["hour", "Hour"], ["day", "Day"], ["week", "Week (Mon–Sun)"]]} /><//>
      ${isGroup && html`<${Field} label="Group share"><${Segmented} label="Group share" value=${rate} onChange=${(v) => setParams({ rate: v })}
        options=${[["pooled", "All together"], ["macro", "Average of channels"]]} /><//>`}
      ${groupChannels.length > 0 && html`<${MultiPicker} label="Channels" options=${groupChannels.map((c) => [c, c])}
        value=${channels} onChange=${(v) => setParams({ channels: v.join(",") || undefined })} allLabel="All channels" />`}
      <${MultiPicker} label="Type" options=${(meta?.doc_types || []).map((t) => [t, `${t}s`])} value=${docTypes}
        onChange=${(v) => setParams({ doc_types: v.join(",") || undefined })} allLabel="Comments and posts" />
    </div>

    ${!terms.length ? html`<${Card}><${Empty} title="Name a term to explore">Words, phrases (“claude code”), domains, subreddits or intents (“notion → obsidian”, “complaint: reddit”).<//><//>` : html`
    <div class="stack">
      <${DataCard} state=${state} title="Share of the conversation"
        sub=${`Comments and posts mentioning each term, per 1,000 in ${scope}${shareKey === "macro" ? ", averaged over its channels so a big one doesn't drown out the small ones" : ""}${state.data ? ` · per ${state.data.bucket === "hour" && state.data.step > 3600 ? `${state.data.step / 3600} hours` : state.data.bucket}` : ""}`}
        help="Hours reach back 180 days, days and weeks forever. Weeks are whole ISO weeks, Monday to Sunday UTC, as the long-term trends use. “All together” divides all mentions by all comments and posts; “average of channels” averages each channel's share (the long-term trends of groups use it).">
        ${(d) => html`<${TimeChart} height=${300} daily=${daily} format=${perThousand} series=${series(shareKey)(d)}
          empty=${html`<${Empty} title="No mentions in this range">Check the spelling, or try a longer range or a bigger group.<//>`} />`}
      <//>
      <div class="grid grid-2">
        <${DataCard} state=${state} title="Mentions" sub="Comments and posts containing the term, each counted once">
          ${(d) => html`<${TimeChart} mode="bars" height=${220} daily=${daily} series=${series("mentions")(d)} />`}
        <//>
        <${DataCard} state=${state} title="People" sub="Different authors. Few people and many mentions usually means spam or one heated thread.">
          ${(d) => html`<${TimeChart} mode="bars" height=${220} daily=${daily} series=${series("authors")(d)} />`}
        <//>
      </div>
      <div class="grid grid-2">
        <${DataCard} state=${state} title="Where it's discussed" flush sub="In this range">
          ${(d) => html`<${Table} rows=${d.where} limit=${12}
            columns=${[
              { key: "term", label: "Term", render: (r) => html`<span class="key" style=${`background:${colors[r.term]}`}></span>${r.term}`, sort: (r) => r.term },
              { key: "channel", label: "Channel", sort: (r) => r.channel },
              { key: "mentions", label: "Mentions", num: true, sort: (r) => r.mentions, render: (r) => count(r.mentions) },
              { key: "authors", label: "People", num: true, sort: (r) => r.authors, render: (r) => count(r.authors) },
              { key: "per_1000", label: "Per 1,000", num: true, sort: (r) => r.per_1000, render: (r) => perThousand(r.per_1000) },
            ]} />`}
        <//>
        <${Card} title="Recent mentions" sub="The last 48 hours: raw text isn't kept longer" flush>
          <${Comments} terms=${terms.join(",")} scope=${scope} channels=${channels} doc_types=${docTypes} limit=${30} />
        <//>
      </div>
    </div>`}`;
}
