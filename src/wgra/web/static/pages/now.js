// Trending now (and the quick look, Grafana's "Rising (preview)").
import { html, useMemo } from "../vendor/preact-htm.js";
import { TimeChart } from "../charts.js";
import {
  SERIES, ago, count, decimal, formatDateTime, listParam, perThousand, setParams, times, useApi,
} from "../lib.js";
import {
  Badge, Card, DataCard, Empty, Field, Kind, KindChips, Meter, MultiPicker, ScopePicker, Segmented,
  Select, Sparkline, Stat, Table, TermButton, Toggle,
} from "../ui.js";

const WORD_KINDS = ["word", "phrase", "domain", "subreddit"];
const INTENT_KINDS = ["switch", "considering", "alternative", "complaint", "need"];
const ALERTS = {
  sent: ["good", "Sent"],
  failed: ["bad", "Failed"],
  capped: ["warn", "Daily limit"],
  cooldown: ["", "Cooldown"],
  warmup: ["", "Warming up"],
  skipped: ["", "Skipped"],
  muted: ["", "Muted"],
};
const ALERT_HELP =
  "What happened to the trends strong enough for an instant alert: sent, failed, daily limit reached (at most 5 a day), " +
  "cooldown (alerted in the last 72 hours), warming up (less than 3 days of history), skipped (the scope never alerts), " +
  "muted (a run without notifications).";

export function AlertBadge({ alert }) {
  if (!alert) return null;
  const [tone, label] = ALERTS[alert] || ["", alert];
  return html`<${Badge} tone=${tone}>${label}<//>`;
}

export function scopeOptions(meta, scope) {
  const channels = meta?.groups?.[scope] || [];
  return [[scope, `${scope} overall`], ...channels.map((channel) => [channel, channel])];
}

export function NowPage({ params, scope, setScope, meta, openTerm }) {
  const view = params.view || "scored";
  return html`
    <div class="page-head">
      <div>
        <h1>${view === "quick" ? "Quick look" : "Trending now"}</h1>
        <p>${view === "quick"
          ? "A first, rough look: the last 24 hours against the 7 days before, without the detector's scoring."
          : "Terms mentioned far more than usual, found every 15 minutes. Click a term to see it over time and the comments behind it."}</p>
      </div>
      <${Segmented} label="View" value=${view} onChange=${(v) => setParams({ view: v === "scored" ? undefined : v })}
        options=${[["scored", "Scored trends"], ["quick", "Quick look"]]} />
    </div>
    ${view === "quick"
      ? html`<${QuickLook} params=${params} scope=${scope} setScope=${setScope} meta=${meta} openTerm=${openTerm} />`
      : html`<${Scored} params=${params} scope=${scope} setScope=${setScope} meta=${meta} openTerm=${openTerm} />`}`;
}

function Scored({ params, scope, setScope, meta, openTerm }) {
  const horizon = params.horizon || "24h";
  const kinds = listParam(params, "kinds", WORD_KINDS);
  const scopes = listParam(params, "scopes");
  const subsumed = params.subsumed === "1";
  const chartRange = params.chart || "7d";
  const query = { scope, horizon, kinds, scopes, subsumed: subsumed ? 1 : 0 };
  const trending = useApi("trending", query, { refresh: 5 * 60e3 });
  const chart = useApi("trending-chart", { ...query, range: chartRange }, { refresh: 5 * 60e3 });
  const digest = useApi("trending-digest", query, { refresh: 5 * 60e3 });
  const alerts = useApi("trending-alerts", query, { refresh: 5 * 60e3 });
  const data = trending.data;

  // the chart's 8 terms keep the same color in the table
  const colors = useMemo(() => {
    const terms = [...new Set((data?.trends || []).filter((t) => !t.subsumed_by).map((t) => t.term))].slice(0, 8);
    return Object.fromEntries(terms.map((term, index) => [term, SERIES[index]]));
  }, [data]);
  // one row per term, at its strongest (the rows come strongest first), with where else
  const rows = useMemo(() => {
    const byTerm = new Map();
    for (const trend of data?.trends || []) {
      const key = `${trend.kind}|${trend.term}`;
      if (byTerm.has(key)) byTerm.get(key).others.push(trend.scope);
      else byTerm.set(key, { ...trend, others: [] });
    }
    return [...byTerm.values()];
  }, [data]);
  const maxScore = Math.max(...rows.map((t) => t.score), 1);
  const open = (row) => openTerm({ term: row.term, kind: row.kind, scope: row.scope || row.strongest_in, range: "7d" });

  return html`
    <div class="filters">
      <${ScopePicker} meta=${meta} value=${scope} onChange=${setScope} />
      <${Field} label="Window"><${Segmented} label="Window" value=${horizon} onChange=${(v) => setParams({ horizon: v })}
        options=${[["24h", "Last 24 hours"], ["6h", "Last 6 hours"]]} /><//>
      <${MultiPicker} label="In" options=${scopeOptions(meta, scope)} value=${scopes}
        onChange=${(v) => setParams({ scopes: v.join(",") || undefined })} allLabel="Group and its channels" />
      <${KindChips} kinds=${[...WORD_KINDS, ...INTENT_KINDS]} value=${kinds}
        onChange=${(v) => setParams({ kinds: v.join(",") })} />
      <${Toggle} label="Show explained bursts" checked=${subsumed} onChange=${(v) => setParams({ subsumed: v ? "1" : undefined })} />
    </div>

    ${data && data.reference_days !== null && data.reference_days < 3 && html`<div class="notice">
      <span>ℹ</span>
      <span>${data.reference_days === 0 ? "No history to compare with yet." : `Only ${data.reference_days} day${data.reference_days === 1 ? "" : "s"} of history so far.`}
      Until there's more, each window is compared with the share of the term on all of the platform, so this shows what's
      distinctive here more than what's rising. Alerts start at 3 days, the full 28-day comparison takes 4 weeks.</span>
    </div>`}

    <div class="stats">
      <${Stat} label="Last analysis" value=${data ? ago(data.last_run) : "…"}
        hint=${data?.last_run ? formatDateTime(data.last_run) : "runs every 15 minutes"}
        help="When the analyzer last scored this window. It runs every 15 minutes." />
      <${Stat} label="History compared with" value=${data?.reference_days ?? "–"} unit="of 28 days"
        help="Days of data each window is compared with, up to 28. Alerts need at least 3." />
      <${Stat} label="Trending" value=${data ? count(data.trending) : "…"} unit="terms"
        hint=${`in the latest run${scopes.length ? ", picked scopes" : ""}`} />
      <${Stat} label="Alerts sent" value=${data ? count(data.alerts_sent) : "…"} unit="in 24 hours"
        hint="at most 5 a day, every group" />
    </div>

    <div class="stack">
      <${DataCard} state=${trending} title="Trending now" flush
        sub=${data?.last_run ? `The ${horizon === "24h" ? "last 24 hours" : "last 6 hours"} against the 28 days before, as of ${formatDateTime(data.last_run)}` : ""}
        help="Ranked by strength. A term trends with at least 10 mentions by 5 different people, twice its usual share, and a strength of 3. 'pro' isn't shown as trending when 'vision pro' explains it, unless explained bursts are shown.">
        ${(d) => html`<${Table} rows=${rows} onRowClick=${open} limit=${30} rowKey=${(r) => `${r.kind}|${r.term}`}
          empty=${html`<${Empty} title="Nothing trending here right now">Try another group, the 24-hour window or more kinds.<//>`}
          columns=${[
            { key: "term", label: "Term", render: (r) => html`
              <${TermButton} term=${r.term} color=${colors[r.term]} onOpen=${() => open(r)} /><${Kind} kind=${r.kind} />
              ${r.subsumed_by && html`<div class="muted small">explained by “${r.subsumed_by}”</div>`}` },
            { key: "scope", label: "Where", sort: (r) => r.scope,
              help: "Where it's strongest. For a group: in how many of its channels it trends, of those mentioning it.",
              render: (r) => html`${r.scope}${r.scope_type === "group" && r.members > 0 &&
                html`<span class="muted small"> · ${r.breadth} of ${r.members} channels</span>`}
                ${r.others.length > 0 && html`<div class="muted small" title=${r.others.join(", ")}>also ${r.others.slice(0, 3).join(", ")}${
                  r.others.length > 3 ? ` +${r.others.length - 3}` : ""}</div>`}` },
            { key: "score", label: "Strength", num: true, sort: (r) => r.score,
              help: "How strong the evidence is that it's mentioned more than usual (the z-score of the weighted log odds). Trends are ranked by it: 3 is the minimum, instant alerts start at 10.",
              render: (r) => html`<${Meter} value=${r.score} max=${maxScore}>${decimal(r.score)}<//>` },
            { key: "ratio", label: "vs usual", num: true, sort: (r) => (r.is_new ? Infinity : r.ratio),
              help: "The share of comments and posts mentioning it now, divided by its share before. new: barely mentioned before.",
              render: (r) => html`<span title=${`${count(r.mentions)} now, ${count(r.mentions_before)} in the 28 days before`}>${times(r.ratio, r.is_new)}</span>` },
            { key: "mentions", label: "Mentions", num: true, sort: (r) => r.mentions,
              render: (r) => html`${count(r.mentions)}<div class="muted small">${count(r.authors)} people</div>` },
            { key: "before", label: "Before", num: true, sort: (r) => r.mentions_before,
              help: "Mentions in the 28 days before the window.", render: (r) => count(r.mentions_before) },
            { key: "spark", label: "Last 7 days", render: (r) => html`<${Sparkline} values=${d.sparklines[r.term]}
              color=${colors[r.term] || "var(--s1)"} label=${`${r.term}, hourly mentions over the last 7 days`} />` },
            { key: "alert", label: "Alert", help: ALERT_HELP, render: (r) => html`<${AlertBadge} alert=${r.alert} />`,
              sort: (r) => r.alert || null },
          ]} />`}
      <//>

      <${DataCard} state=${chart} title="The strongest trends over time"
        sub=${`The 8 strongest of the latest run, per 1,000 comments and posts in ${scope}`}
        actions=${html`<${Segmented} label="Chart range" value=${chartRange} onChange=${(v) => setParams({ chart: v })}
          options=${[["24h", "24h"], ["3d", "3 days"], ["7d", "7 days"], ["14d", "14 days"]]} />`}>
        ${(rows) => html`<${TimeChart} height=${260} format=${perThousand} series=${seriesByTerm(rows, colors)} />`}
      <//>

      <div class="grid grid-2">
        <${DataCard} state=${digest} title="Strongest in the last 24 hours" flush
          sub="Each term at its strongest, in any scope here and either window. The daily digest sends a group's top 10.">
          ${(rows) => html`<${Table} rows=${rows} limit=${10} onRowClick=${open}
            columns=${[
              { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} onOpen=${() => open(r)} /><${Kind} kind=${r.term_kind} />` },
              { key: "where", label: "Strongest in", render: (r) => r.strongest_in },
              { key: "score", label: "Strength", num: true, render: (r) => decimal(r.score), sort: (r) => r.score },
              { key: "ratio", label: "vs usual", num: true, render: (r) => times(r.ratio, r.is_new) },
              { key: "first", label: "Since", render: (r) => html`<span title=${formatDateTime(r.first_seen)}>${ago(r.first_seen)}</span>`,
                sort: (r) => r.first_seen },
            ]} />`}
        <//>
        <${DataCard} state=${alerts} title="Alerts, last 14 days" flush help=${ALERT_HELP}>
          ${(rows) => html`<${Table} rows=${rows} limit=${10} onRowClick=${open}
            empty=${html`<${Empty} title="No alert-worthy trends in 14 days">Instant alerts need a strength of 10 and 20 people, or a term trending in many channels of a group at once.<//>`}
            columns=${[
              { key: "time", label: "When", render: (r) => html`<span class="nowrap" title=${formatDateTime(r.time)}>${ago(r.time)}</span>` },
              { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} onOpen=${() => open(r)} />
                <div class="muted small">${r.scope} · ${r.horizon}</div>` },
              { key: "score", label: "Strength", num: true, render: (r) => decimal(r.score) },
              { key: "alert", label: "Status", render: (r) => html`<${AlertBadge} alert=${r.alert} />` },
            ]} />`}
        <//>
      </div>
    </div>`;
}

export function seriesByTerm(rows, colors = {}, value = "per_1000") {
  const series = new Map();
  for (const row of rows) {
    if (!series.has(row.term)) series.set(row.term, []);
    series.get(row.term).push([row.time, row[value]]);
  }
  // in the table's order, so the legend reads like the ranking
  const order = Object.keys(colors);
  const rank = (name) => (order.includes(name) ? order.indexOf(name) : order.length);
  return [...series]
    .sort((a, b) => rank(a[0]) - rank(b[0]))
    .map(([name, points]) => ({ name, points, color: colors[name] }));
}

function QuickLook({ params, scope, setScope, meta, openTerm }) {
  const kinds = listParam(params, "kinds", ["word", "phrase"]).filter((k) => WORD_KINDS.includes(k));
  const channels = listParam(params, "channels");
  const docTypes = listParam(params, "doc_types");
  const minMentions = params.min_mentions || "10";
  const minAuthors = params.min_authors || "5";
  const state = useApi("rising", {
    scope, channels, doc_types: docTypes, kinds: kinds.length ? kinds : ["word", "phrase"],
    min_mentions: minMentions, min_authors: minAuthors,
  }, { refresh: 5 * 60e3 });
  const groupChannels = meta?.groups?.[scope] || [];
  const open = (row) => openTerm({ term: row.term, kind: row.kind, scope, range: "7d" });
  return html`
    <div class="filters">
      <${ScopePicker} meta=${meta} value=${scope} onChange=${setScope} />
      ${groupChannels.length > 0 && html`<${MultiPicker} label="Channels" options=${groupChannels.map((c) => [c, c])}
        value=${channels} onChange=${(v) => setParams({ channels: v.join(",") || undefined })} allLabel="All channels" />`}
      <${MultiPicker} label="Type" options=${(meta?.doc_types || []).map((t) => [t, `${t}s`])} value=${docTypes}
        onChange=${(v) => setParams({ doc_types: v.join(",") || undefined })} allLabel="Comments and posts" />
      <${KindChips} kinds=${WORD_KINDS} value=${kinds.length ? kinds : ["word", "phrase"]} onChange=${(v) => setParams({ kinds: v.join(",") })} />
      <${Field} label="At least"><${Select} label="Minimum mentions" value=${minMentions} onChange=${(v) => setParams({ min_mentions: v })}
        options=${["5", "10", "25", "50", "100"].map((n) => [n, `${n} mentions`])} /><//>
      <${Select} label="Minimum people" value=${minAuthors} onChange=${(v) => setParams({ min_authors: v })}
        options=${["3", "5", "10", "25"].map((n) => [n, `${n} people`])} />
    </div>
    <${DataCard} state=${state} title="Mentioned more than usual, last 24 hours" flush
      help="vs usual: the share of comments and posts mentioning a term in the last 24 hours, divided by its usual share. Usual blends its share in the 7 days before with its share in the platform's background (the r/all sample), so without history this first shows what is distinctive for the group.">
      ${(rows) => html`<${Table} rows=${rows} limit=${40} onRowClick=${open}
        initialSort=${{ key: "ratio", desc: true }}
        columns=${[
          { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} onOpen=${() => open(r)} /><${Kind} kind=${r.kind} />` },
          { key: "ratio", label: "vs usual", num: true, sort: (r) => r.times_usual, render: (r) => times(r.times_usual) },
          { key: "mentions", label: "Mentions", num: true, sort: (r) => r.mentions, render: (r) => count(r.mentions) },
          { key: "authors", label: "People", num: true, sort: (r) => r.authors, render: (r) => count(r.authors) },
          { key: "now", label: "Per 1,000 now", num: true, sort: (r) => r.per_1000_now, render: (r) => perThousand(r.per_1000_now) },
          { key: "usual", label: "Usually", num: true, sort: (r) => r.per_1000_usual, render: (r) => perThousand(r.per_1000_usual) },
          { key: "before", label: "7 days before", num: true, sort: (r) => r.mentions_before, render: (r) => count(r.mentions_before) },
        ]} />`}
    <//>`;
}
