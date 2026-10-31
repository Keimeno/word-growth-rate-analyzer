// Collection: is the ingester healthy and complete, per platform.
import { html } from "../vendor/preact-htm.js";
import { TimeChart } from "../charts.js";
import { ago, bytes, count, decimal, formatDateTime, listParam, percent, setParams, useApi } from "../lib.js";
import { Badge, DataCard, Field, Meter, MultiPicker, Segmented, Stat, Table } from "../ui.js";

const RATE_LIMIT = 1000; // requests per 10 minutes and client id (Reddit)

function feedState(feed) {
  const age = (Date.now() - new Date(feed.last_poll).getTime()) / 1000;
  if (feed.errors > 0 && feed.errors >= feed.polls / 2) return ["bad", "failing"];
  if (age > Math.max(300, 4 * (feed.poll_every_s || 0))) return ["warn", "late"];
  if (feed.errors > 0 || feed.gaps > 0) return ["warn", feed.errors > 0 ? "errors" : "gaps"];
  return ["good", "ok"];
}

/** Every feed's items per minute, the biggest 7 on their own and the rest as "other". */
function feedSeries(items) {
  const totals = new Map();
  for (const row of items) totals.set(row.feed, (totals.get(row.feed) || 0) + row.per_minute);
  const top = [...totals].sort((a, b) => b[1] - a[1]).slice(0, 7).map(([feed]) => feed);
  const series = new Map(top.map((feed) => [feed, new Map()]));
  const other = new Map();
  for (const row of items) {
    const target = series.get(row.feed) || other;
    target.set(row.time, (target.get(row.time) || 0) + row.per_minute);
  }
  const result = [...series].map(([name, points]) => ({ name, points: [...points] }));
  if (other.size) result.push({ name: "other feeds", points: [...other] });
  return result;
}

export function HealthPage({ params, meta }) {
  const platforms = listParam(params, "platforms");
  const range = params.range || "6h";
  const state = useApi("ingestion", { platforms, range }, { refresh: 60e3 });
  const charts = useApi("ingestion-charts", { platforms, range }, { refresh: 60e3 });
  const data = state.data;
  const lastPollAge = data?.last_poll ? (Date.now() - new Date(data.last_poll).getTime()) / 1000 : null;
  const failing = (data?.feeds || []).filter((feed) => feedState(feed)[0] !== "good");
  const status = !data ? null
    : lastPollAge === null || lastPollAge > 300
      ? ["warn", `No requests for ${data.last_poll ? ago(data.last_poll).replace(" ago", "") : "a while"}. Is the ingester running? (docker compose ps)`]
      : failing.length
        ? ["warn", `${failing.length} feed${failing.length === 1 ? " needs" : "s need"} a look: ${failing.map((f) => f.feed).join(", ")}.`]
        : ["good", "Collecting normally: every feed polled recently, without errors or gaps in the last hour."];

  return html`
    <div class="page-head"><div>
      <h1>Collection</h1>
      <p>Is the ingester healthy and complete? Requests to each platform, what they found, and what's stored.</p>
    </div></div>
    <div class="filters">
      ${(meta?.platforms || []).length > 1 && html`<${MultiPicker} label="Platform" options=${meta.platforms.map((p) => [p, p])}
        value=${platforms} onChange=${(v) => setParams({ platforms: v.join(",") || undefined })} allLabel="Every platform" />`}
      <${Field} label="Charts over"><${Segmented} label="Range" value=${range} onChange=${(v) => setParams({ range: v })}
        options=${[["1h", "1 hour"], ["6h", "6 hours"], ["24h", "24 hours"], ["7d", "7 days"]]} /><//>
    </div>

    ${status && html`<div class=${`notice${status[0] === "warn" ? " warn" : ""}`}>
      <span>${status[0] === "good" ? "✓" : "!"}</span><span>${status[1]}</span>
    </div>`}

    <div class="stats">
      <${Stat} label="Collected, 24 hours" value=${data ? count(data.documents_24h) : "…"} unit="comments and posts"
        help="From the tracked channels of the selected platforms, without their samples (r/all)." />
      <${Stat} label="Requests, last 10 minutes" value=${data ? count(data.requests_10m) : "…"}
        hint=${html`<${Meter} value=${data?.requests_10m || 0} max=${RATE_LIMIT}>of ${count(RATE_LIMIT)} allowed<//>`}
        help="Reddit allows 1,000 requests per 10 minutes per client id." />
      <${Stat} label="Gaps, 24 hours" value=${data ? count(data.gaps_24h || 0) : "…"}
        hint=${data && (data.gaps_24h ? html`<${Badge} tone="warn">some items probably missed<//>` : html`<${Badge} tone="good">none<//>`)}
        help="Polls that found a full listing of unseen items: some items were probably missed. The feed then polls more often." />
      <${Stat} label="Share of reddit sampled" value=${data?.sampled_share === null || !data ? "–" : percent(data.sampled_share, 2)}
        help="The r/all sample: new comments we got against how far reddit's comment ids advanced (roughly every comment posted on reddit), over the charts' range." />
      <${Stat} label="Last request" value=${data ? ago(data.last_poll) : "…"} hint=${data?.last_poll ? formatDateTime(data.last_poll) : ""} />
    </div>

    <div class="stack">
      <div class="grid grid-2">
        <${DataCard} state=${charts} title="New items per minute" sub="By feed">
          ${(d) => html`<${TimeChart} height=${220} series=${feedSeries(d.items)} />`}
        <//>
        <${DataCard} state=${charts} title="Requests per minute" sub="With errors and gaps">
          ${(d) => html`<${TimeChart} height=${220} format=${(v) => decimal(v, v < 10 ? 1 : 0)} series=${[
            ["requests", "Requests", "var(--s1)"], ["errors", "Errors", "var(--s8)"], ["gaps", "Gaps", "var(--s4)"],
          ].map(([key, name, color]) => ({ name, color, points: d.requests.map((row) => [row.time, row[key]]) }))} />`}
        <//>
      </div>

      <${DataCard} state=${state} title="Feeds, last hour" flush>
        ${(d) => html`<${Table} rows=${d.feeds} limit=${30}
          columns=${[
            { key: "state", label: "", render: (r) => {
              const [tone, label] = feedState(r);
              return html`<${Badge} tone=${tone}>${label}<//>`;
            } },
            { key: "feed", label: "Feed", sort: (r) => r.feed, render: (r) => html`<strong>${r.feed}</strong><span class="muted small"> ${r.platform}</span>` },
            { key: "polls", label: "Requests", num: true, sort: (r) => r.polls, render: (r) => count(r.polls) },
            { key: "errors", label: "Errors", num: true, sort: (r) => r.errors, render: (r) => count(r.errors) },
            { key: "new", label: "New items", num: true, sort: (r) => r.new_items, render: (r) => count(r.new_items) },
            { key: "gaps", label: "Gaps", num: true, sort: (r) => r.gaps, render: (r) => count(r.gaps) },
            { key: "every", label: "Polled every", num: true, sort: (r) => r.poll_every_s, render: (r) => `${decimal(r.poll_every_s, r.poll_every_s < 10 ? 1 : 0)} s` },
            { key: "rate", label: "Items a minute", num: true, sort: (r) => r.items_per_minute, render: (r) => count(Math.round(r.items_per_minute)) },
            { key: "last", label: "Last request", sort: (r) => r.last_poll, render: (r) => html`<span title=${formatDateTime(r.last_poll)}>${ago(r.last_poll)}</span>` },
          ]} />`}
      <//>

      <div class="grid grid-2">
        <${DataCard} state=${state} title="Channels, last 24 hours" flush
          help="Every channel of config.yaml: the tracked ones, the samples (r/all) and the radar's search (r/_search). People add up per type: someone writing a comment and a post counts twice.">
          ${(d) => html`<${Table} rows=${d.channels} limit=${15} initialSort=${{ key: "documents", desc: true }}
            columns=${[
              { key: "channel", label: "Channel", sort: (r) => r.channel, render: (r) => html`${r.channel}
                ${r.background ? html` <${Badge}>sample<//>` : !r.analyzed ? html` <${Badge}>search<//>` : null}` },
              { key: "documents", label: "Collected", num: true, sort: (r) => r.documents, render: (r) => count(r.documents) },
              { key: "types", label: "By type", render: (r) => html`<span class="muted small">${r.by_type.map(([type, n]) => `${count(n)} ${type}s`).join(", ") || "nothing"}</span>` },
              { key: "authors", label: "People", num: true, sort: (r) => r.authors, render: (r) => count(r.authors) },
            ]} />`}
        <//>
        <${DataCard} state=${state} title="Storage" flush>
          ${(d) => html`<${Table} rows=${d.storage} limit=${20}
            columns=${[
              { key: "table", label: "Table", sort: (r) => r.table },
              { key: "rows", label: "Rows", num: true, sort: (r) => r.rows, render: (r) => count(r.rows) },
              { key: "bytes", label: "On disk", num: true, sort: (r) => r.bytes, render: (r) => bytes(r.bytes) },
            ]} />`}
        <//>
      </div>
    </div>`;
}
