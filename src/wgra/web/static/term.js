// The term drawer: any term, opened from any table, without leaving the page.
import { html, useEffect, useState } from "./vendor/preact-htm.js";
import { TimeChart } from "./charts.js";
import { count, href, intentKind, perThousand, useApi } from "./lib.js";
import { Card, DataCard, Empty, ExternalLink, Kind, Segmented, Table } from "./ui.js";
import { Comments } from "./comments.js";
import { grafanaLink } from "./grafana.js";

const INTENT_KINDS = ["switch", "alternative", "complaint", "need", "considering"];
const RANGES = [["2d", "2 days"], ["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"], ["26w", "26 weeks"]];

/** target: { term, kind, scope, range, bucket, rate, from } (from: ms, a long-term window). */
export function TermDrawer({ target, onClose, config }) {
  const [range, setRange] = useState(target.from ? "window" : target.range || "7d");
  useEffect(() => {
    const key = (event) => event.key === "Escape" && onClose();
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, [onClose]);
  const intent = INTENT_KINDS.includes(target.kind) || (!target.kind && Boolean(intentKind(target.term)));
  const span = range === "window"
    ? { from: Math.floor(target.from / 1000), to: Math.floor(Date.now() / 1000) }
    : { range };
  const bucket = range === "window" ? "week" : target.bucket || "auto";
  const rate = target.rate || "pooled";
  const query = { terms: target.term, scope: target.scope, bucket, ...span };
  const series = useApi("explore", query);
  const ranges = target.from ? [["window", "Trend window"], ...RANGES] : RANGES;
  const exploreParams = { terms: target.term, scope: target.scope, bucket, rate, range: range === "window" ? "26w" : range };

  return html`<div>
    <div class="scrim" onClick=${onClose}></div>
    <aside class="drawer" role="dialog" aria-label=${target.term}>
      <div class="drawer-head">
        <div>
          <h2>${target.term}<${Kind} kind=${target.kind} /></h2>
          <div class="secondary">in ${target.scope}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end">
          <a class="icon-button" href=${href("explore", exploreParams)} onClick=${onClose}>Open in Explore</a>
          <a class="icon-button" href=${grafanaLink(config, "explore", exploreParams)} target="_blank" rel="noopener">Grafana ↗</a>
          <button type="button" class="icon-button" onClick=${onClose} aria-label="Close">✕</button>
        </div>
      </div>
      <div class="drawer-body">
        <${Segmented} label="Range" options=${ranges} value=${range} onChange=${setRange} />
        <${DataCard} state=${series} title="Share of the conversation"
          sub=${`comments and posts mentioning it, per 1,000 in ${target.scope}${rate === "macro" ? " (average of the channels' shares)" : ""}`}>
          ${(data) => html`
            <${TimeChart} daily=${data.bucket !== "hour"} format=${perThousand}
              series=${[{ name: target.term, points: data.points.map((p) => [p.time, rate === "macro" ? p.macro : p.pooled]) }]} />
            <${Totals} data=${data} />`}
        <//>
        <${DataCard} state=${series} title="Where it's discussed" flush>
          ${(data) => html`<${Table} limit=${8} rows=${data.where} empty=${html`<${Empty} title="No mentions in this range" />`}
            columns=${[
              { key: "channel", label: "Channel", render: (r) => r.channel },
              { key: "mentions", label: "Mentions", num: true, render: (r) => count(r.mentions), sort: (r) => r.mentions },
              { key: "authors", label: "People", num: true, render: (r) => count(r.authors), sort: (r) => r.authors },
              { key: "per_1000", label: "Per 1,000", num: true, render: (r) => perThousand(r.per_1000), sort: (r) => r.per_1000 },
            ]} />`}
        <//>
        <${Card} title="Recent comments" sub="the last 48 hours, raw text isn't kept longer" flush>
          <${Comments} intent=${intent} term=${target.term} scope=${target.scope} />
        <//>
      </div>
    </aside>
  </div>`;
}

function Totals({ data }) {
  const mentions = data.points.reduce((sum, p) => sum + p.mentions, 0);
  const peak = data.points.reduce((best, p) => (p.pooled > (best?.pooled ?? -1) ? p : best), null);
  return html`<div class="secondary small" style="margin-top:8px">
    ${count(mentions)} mentions in this range${peak && html`, highest ${perThousand(peak.pooled)} per 1,000`}
  </div>`;
}
