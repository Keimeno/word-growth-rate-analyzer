// Long-term trends: terms growing or fading steadily over 13, 26 or 52 weeks.
import { html, useMemo } from "../vendor/preact-htm.js";
import { TimeChart } from "../charts.js";
import {
  SERIES, ago, confidence, count, decimal, formatDate, formatDateTime, listParam, percent, perThousand,
  setParams, signedPercent, useApi,
} from "../lib.js";
import {
  Badge, DataCard, Empty, Field, Kind, KindChips, MultiPicker, ScopePicker, Segmented, Sparkline, Stat, Table,
  Tabs, TermButton,
} from "../ui.js";
import { scopeOptions } from "./now.js";

const WORD_KINDS = ["word", "phrase", "domain", "subreddit"];
const INTENT_KINDS = ["switch", "considering", "alternative", "complaint", "need"];
const CATEGORIES = [
  ["emerging", "Emerging", "Rare at the start of the window (at most 1 in 1,000 comments and posts), growing significantly and steadily."],
  ["mainstreaming", "Mainstreaming", "Common already at the start of the window, still growing significantly and steadily."],
  ["fading", "Fading", "Its share shrank significantly and steadily."],
  ["one-off", "One-offs", "The change comes mostly from one or two weeks far above the rest (at least half of it, the peak at least 3 times the median week): an event, not a trend."],
];
const WEEK = 7 * 24 * 3600e3;

export function LongTermPage({ params, scope, setScope, meta, openTerm }) {
  const horizon = params.horizon || "13w";
  const kinds = listParam(params, "kinds", WORD_KINDS);
  const scopes = listParam(params, "scopes");
  const tab = params.tab || "emerging";
  const state = useApi("long-term", { scope, horizon, kinds, scopes }, { refresh: 60 * 60e3 });
  const data = state.data;
  const weeks = Number(horizon.replace("w", ""));

  const byCategory = useMemo(() => {
    const groups = Object.fromEntries(CATEGORIES.map(([key]) => [key, []]));
    for (const trend of data?.trends || []) groups[trend.category]?.push(trend);
    return groups;
  }, [data]);
  // the 8 fastest growing or fading, for the chart, and their colors in the tables
  const strongest = useMemo(() => (data?.trends || [])
    .filter((t) => t.category !== "one-off")
    .sort((a, b) => Math.abs(Math.log(b.growth)) - Math.abs(Math.log(a.growth)))
    .slice(0, 8), [data]);
  const colors = Object.fromEntries(strongest.map((t, index) => [`${t.scope}|${t.term}`, SERIES[index]]));
  const open = (row) => openTerm({
    term: row.term, kind: row.kind, scope: row.scope, bucket: "week", rate: "macro",
    from: new Date(`${row.window_start}T00:00:00Z`).getTime(),
  });
  const total = data?.trends.length || 0;

  return html`
    <div class="page-head"><div>
      <h1>Long-term trends</h1>
      <p>Terms whose share of the conversation grows or fades steadily, week after week. Found once a day; the results change on Mondays, when a week completes.</p>
    </div></div>
    <div class="filters">
      <${ScopePicker} meta=${meta} value=${scope} onChange=${setScope} />
      <${Field} label="Over"><${Segmented} label="Window" value=${horizon} onChange=${(v) => setParams({ horizon: v })}
        options=${[["13w", "13 weeks"], ["26w", "26 weeks"], ["52w", "52 weeks"]]} /><//>
      <${MultiPicker} label="In" options=${scopeOptions(meta, scope)} value=${scopes}
        onChange=${(v) => setParams({ scopes: v.join(",") || undefined })} allLabel="Group and its channels" />
      <${KindChips} kinds=${[...WORD_KINDS, ...INTENT_KINDS]} value=${kinds} onChange=${(v) => setParams({ kinds: v.join(",") })} />
    </div>

    ${data && data.weeks_of_history < weeks && html`<div class="notice">
      <span>ℹ</span>
      <span>The ${weeks}-week window needs ${weeks} complete weeks of data. ${scope} has ${data.weeks_of_history} so far,
      so its first results come in about ${weeks - data.weeks_of_history} week${weeks - data.weeks_of_history === 1 ? "" : "s"}.
      Collection has to keep running until then.</span>
    </div>`}

    <div class="stats">
      <${Stat} label="Last run" value=${data ? ago(data.last_run) : "…"} hint=${data?.last_run ? formatDateTime(data.last_run) : "once a day after 00:30 UTC"}
        help="When the stored results were found. The detector runs every day after 00:30 UTC; the results only change when a week has completed." />
      <${Stat} label="Weeks analyzed up to" value=${data?.analyzed_until ? formatDate(data.analyzed_until) : "–"}
        help="The last day of the last complete week analyzed (weeks run Monday to Sunday, UTC). The current week isn't complete yet." />
      <${Stat} label="History" value=${data?.weeks_of_history ?? "…"} unit="complete weeks" hint=${`the window needs ${weeks}`} />
      <${Stat} label="Trends found" value=${data ? count(total) : "…"}
        hint=${data ? CATEGORIES.map(([key, label]) => `${byCategory[key].length} ${label.toLowerCase()}`).join(" · ") : ""} />
    </div>

    <div class="stack">
      ${strongest.length > 0 && html`<${DataCard} state=${state} title="The fastest growing and fading"
        sub=${`Weekly share per 1,000 comments and posts${meta?.groups?.[scope] ? ", a group's the average of its channels' shares" : ""}`}>
        ${() => html`<${TimeChart} daily height=${260} format=${perThousand} series=${strongest.map((t) => ({
          name: `${t.term} · ${t.scope}`,
          color: colors[`${t.scope}|${t.term}`],
          points: t.weekly.map((value, i) => [new Date(`${t.window_start}T00:00:00Z`).getTime() + i * WEEK, value]),
        }))} />`}
      <//>`}

      <${DataCard} state=${state} flush>
        ${() => html`
          <${Tabs} value=${tab} onChange=${(v) => setParams({ tab: v })}
            tabs=${CATEGORIES.map(([key, label]) => [key, label, byCategory[key].length])} />
          <p class="secondary small" style="padding:10px 16px 0;margin:0">${CATEGORIES.find(([key]) => key === tab)[2]}</p>
          <${Table} key=${tab} rows=${byCategory[tab]} onRowClick=${open} limit=${25}
            initialSort=${tab === "one-off" ? null : { key: "growth", desc: tab !== "fading" }}
            empty=${html`<${Empty} title=${`No ${CATEGORIES.find(([key]) => key === tab)[1].toLowerCase()} terms`}>
              ${data.weeks_of_history < weeks ? `The ${weeks}-week window hasn't run yet.` : "Nothing passed the tests in this window and scope."}<//>`}
            columns=${columns(tab, colors, open)} />`}
      <//>
    </div>`;
}

function columns(tab, colors, open) {
  const oneOff = tab === "one-off";
  return [
    { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} color=${colors[`${r.scope}|${r.term}`]}
      onOpen=${() => open(r)} /><${Kind} kind=${r.kind} />` },
    { key: "scope", label: "Where", render: (r) => r.scope, sort: (r) => r.scope },
    oneOff
      ? { key: "change", label: "Change", num: true, sort: (r) => r.change, render: (r) => signedPercent(100 * (r.change - 1)),
          help: "The second half of the window against the first, per month." }
      : { key: "growth", label: "Per month", num: true, sort: (r) => r.growth, render: (r) => html`<strong>${signedPercent(100 * (r.growth - 1))}</strong>`,
          help: "Growth per month: the Theil–Sen slope of the weekly share, robust to single spikes." },
    { key: "weekly", label: "Weekly share", render: (r) => html`<${Sparkline} values=${r.weekly} width=${140}
      color=${colors[`${r.scope}|${r.term}`] || (r.category === "fading" ? "var(--s2)" : "var(--s1)")} label=${`${r.term}, weekly share`} />` },
    { key: "share", label: "Per 1,000", num: true, sort: (r) => r.end_share,
      help: "The trend line at the first and the last week of the window, per 1,000 comments and posts.",
      render: (r) => html`<span class="nowrap">${perThousand(r.start_share)} → ${perThousand(r.end_share)}</span>` },
    { key: "mentions", label: "Mentions", num: true, sort: (r) => r.mentions, render: (r) => count(r.mentions) },
    ...(oneOff
      ? [
          { key: "spike", label: "From 2 weeks", num: true, sort: (r) => r.spike_share, render: (r) => percent(r.spike_share),
            help: "How much of the change comes from the two highest weeks." },
          { key: "peak", label: "Peak", num: true, sort: (r) => r.peak, render: (r) => `×${decimal(r.peak)}`,
            help: "The highest week, times the median week." },
        ]
      : []),
    { key: "q", label: "Confidence", sort: (r) => -r.q,
      help: "How sure the trend is steady, from the Mann–Kendall test corrected for testing many terms at once (Benjamini–Hochberg q, at most 0.05 to be shown). Very strong: q under 0.001.",
      render: (r) => {
        const level = confidence(r.q);
        return html`<${Badge} tone=${level.tone} title=${`q = ${r.q?.toExponential(1)}`}>${level.label}<//>`;
      } },
  ];
}
