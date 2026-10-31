// Early warning: which channels pick terms up before others, and what's expected to spread.
import { html } from "../vendor/preact-htm.js";
import { LeadGraph, TimeChart } from "../charts.js";
import {
  ago, confidence, count, decimal, duration, formatDateTime, formatShortDate, formatTime, inFuture, listParam,
  percent, setParams, useApi,
} from "../lib.js";
import { Badge, DataCard, Empty, Field, Meter, MultiPicker, Segmented, Select, Stat, Table, TermButton } from "../ui.js";

const follower = (row) => (row.without_leader ? `${row.follower} (rest)` : row.follower);
const NO_EDGES = html`<${Empty} title="No leader → follower pairs yet">
  They're learned from terms that trended in several places: an event takes 17 days to be over, and a pair needs at least 5 of
  them. Expect the first ones after 4–6 weeks of collection.<//>`;

export function EarlyWarningPage({ params, openTerm }) {
  const topic = params.topic || "all";
  const leaders = listParam(params, "leaders");
  const range = params.range || "30d";
  const state = useApi("early-warning", { topic, leaders }, { refresh: 5 * 60e3 });
  const forecasts = useApi("early-warning-forecasts", {}, { refresh: 5 * 60e3 });
  const record = useApi("early-warning-record", { range }, { refresh: 15 * 60e3 });
  const data = state.data;
  const edges = (data?.edges || []).map((edge) => ({ ...edge, followerLabel: follower(edge) }));
  const open = (term, kind, scope) => openTerm({ term, kind, scope, range: "7d" });

  return html`
    <div class="page-head"><div>
      <h1>Early warning</h1>
      <p>Some communities pick up terms days before others. Learned from what trended, these pairs turn today's bursts into forecasts of where they'll show up next.</p>
    </div></div>
    <div class="filters">
      <${Field} label="Topic"><${Select} label="Topic" value=${topic} onChange=${(v) => setParams({ topic: v })}
        options=${(data?.topics || ["all"]).map((t) => [t, t === "all" ? "All topics" : t])} /><//>
      <${MultiPicker} label="Leaders" options=${(data?.leaders || []).map((l) => [l, l])} value=${leaders}
        onChange=${(v) => setParams({ leaders: v.join(",") || undefined })} allLabel="Every leader" />
    </div>

    <div class="stats">
      <${Stat} label="Pairs learned" value=${data ? ago(data.edges_learned) : "…"} hint=${data?.edges_learned ? formatDateTime(data.edges_learned) : "once a day after 01:00 UTC"} />
      <${Stat} label="Leader → follower pairs" value=${data ? count(data.edge_count) : "…"} hint=${topic === "all" ? "every topic" : topic}
        help="Pairs that pass the tests: at least 5 events and 3 hits, more hits than the follower's usual rate explains, and the leader first in at least 70% of the events where both picked the term up." />
      <${Stat} label="Events" value=${data ? count(data.events) : "…"} hint=${data ? `${count(data.closed_events)} closed` : ""}
        help="Terms that trended somewhere, what the pairs are learned from. An event is closed when its span (3 days before its first trend to 14 days after) is over." />
      <${Stat} label="Forecasts waiting" value=${data ? count(data.pending) : "…"} />
      <${Stat} label="Came true, 30 days" value=${data?.precision_30d === null || !data ? "–" : percent(data.precision_30d)}
        hint=${data ? `of ${count(data.resolved_30d)} resolved` : ""}
        help="Of the forecasts resolved in the last 30 days, how many came true. “wgra replay --forecast” measures it on past data, with recall and calibration." />
      <${Stat} label="Forecast alerts" value=${data ? count(data.forecast_alerts) : "…"} unit="in 24 hours"
        help="Forecast alerts are off by default (forecast.alert in config.yaml). They share the daily cap with trend alerts." />
    </div>

    <div class="stack">
      <${DataCard} state=${forecasts} title="What's expected to spread" flush
        sub="A term rising in a leader that a follower hasn't picked up yet. Click a term to see it in the leader."
        help="Chance: that the follower picks it up within 7 days of the leader's onset (the pair's probability, lowered for the time that already passed), with its 80% interval. Usually: how often the follower picks up any trending term. Expected: the leader's onset plus the pair's median lead.">
        ${(d) => html`<${Table} rows=${d.pending} limit=${15} onRowClick=${(r) => open(r.term, r.kind, r.leader)}
          empty=${html`<${Empty} title="No forecasts waiting">Forecasts are made when a term trends in a leader of a learned pair.<//>`}
          columns=${[
            { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} onOpen=${() => open(r.term, r.kind, r.leader)} />` },
            { key: "path", label: "From → to", render: (r) => html`<span class="nowrap">${r.leader} → <strong>${follower(r)}</strong></span>` },
            { key: "chance", label: "Chance", num: true, sort: (r) => r.probability,
              render: (r) => html`<${Meter} value=${r.probability} max=${1}>${percent(r.probability)}<//>
                <div class="muted small">${percent(r.probability_low)}–${percent(r.probability_high)}</div>` },
            { key: "base", label: "Usually", num: true, sort: (r) => r.base_rate, render: (r) => percent(r.base_rate) },
            { key: "expected", label: "Expected", sort: (r) => r.expected_at,
              render: (r) => html`<span title=${formatDateTime(r.expected_at)}>${inFuture(r.expected_at)}</span>
                <div class="muted small">by ${formatShortDate(r.due_by)}</div>` },
            { key: "lift", label: "Lift", num: true, sort: (r) => r.lift, render: (r) => `×${decimal(r.lift)}`,
              help: "The chance divided by the usual rate." },
            { key: "alert", label: "Alert", render: (r) => r.alert && html`<${Badge}>${r.alert}<//>` },
          ]} />`}
      <//>

      <div class="grid grid-2">
        <${DataCard} state=${state} title="Who leads whom"
          sub="Leaders left, followers right. Thicker: the likelier the follower picks the leader's terms up. Hover for the numbers.">
          ${() => edges.length ? html`<${LeadGraph} edges=${edges} describe=${(e) => html`
            <div class="when">${e.leader} → ${e.followerLabel}</div>
            <div class="row"><span>Chance</span><strong>${percent(e.probability)}</strong></div>
            <div class="row"><span>Usually</span><strong>${percent(e.base_rate)}</strong></div>
            <div class="row"><span>Lead time</span><strong>${duration(e.lag_median)}</strong></div>
            <div class="row"><span>Events, hits</span><strong>${e.events}, ${e.hits}</strong></div>`} />` : NO_EDGES}
        <//>
        <${DataCard} state=${forecasts} title="Recent cascades" flush
          sub="Terms of the last 14 days that reached more than one place, in the order they got there. What the pairs are learned from.">
          ${(d) => html`<${Table} rows=${d.cascades} limit=${8} onRowClick=${(r) => open(r.term, r.kind, r.cascade[0][0])}
            empty=${html`<${Empty} title="No cascades in 14 days" />`}
            columns=${[
              { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} onOpen=${() => open(r.term, r.kind, r.cascade[0][0])} />
                <div class="muted small">${r.topic || "no topic"}${r.closed ? " · closed" : ""}</div>` },
              { key: "cascade", label: "Path", render: (r) => html`<div class="cascade">${r.cascade.slice(0, 6).map(([scope, at], i) => html`
                ${i > 0 && html`<span class="arrow">→</span>`}
                <span class="step">${scope}<small>${formatShortDate(at)} ${formatTime(at)}</small></span>`)}
                ${r.cascade.length > 6 && html`<span class="muted small">+${r.cascade.length - 6}</span>`}</div>` },
            ]} />`}
        <//>
      </div>

      <${DataCard} state=${state} title="Leader → follower pairs" flush
        help="Learned daily from the events of the last 180 days. Lead: median time from the leader's onset to the follower's, with the middle half. Chance: hits shrunk towards the usual rate by 4 pseudo-events, with its 80% interval. Leader first: of the events where both picked it up within 7 days of each other, how often the leader was first. (rest): a group of the leader's, without the leader's own mentions.">
        ${() => html`<${Table} rows=${edges} limit=${20} initialSort=${{ key: "lift", desc: true }} empty=${NO_EDGES}
          columns=${[
            { key: "leader", label: "Leader", sort: (r) => r.leader, render: (r) => html`<strong>${r.leader}</strong>` },
            { key: "follower", label: "Follower", sort: (r) => r.followerLabel, render: (r) => html`${r.followerLabel}
              <span class="muted small"> ${r.follower_type}</span>` },
            { key: "lead", label: "Lead", num: true, sort: (r) => r.lag_median, render: (r) => html`${duration(r.lag_median)}
              <div class="muted small">${duration(r.lag_q25)}–${duration(r.lag_q75)}</div>` },
            { key: "chance", label: "Chance", num: true, sort: (r) => r.probability, render: (r) => html`${percent(r.probability)}
              <div class="muted small">${percent(r.probability_low)}–${percent(r.probability_high)}</div>` },
            { key: "base", label: "Usually", num: true, sort: (r) => r.base_rate, render: (r) => percent(r.base_rate) },
            { key: "lift", label: "Lift", num: true, sort: (r) => r.lift, render: (r) => html`<strong>×${decimal(r.lift)}</strong>` },
            { key: "hits", label: "Hits", num: true, sort: (r) => r.hits, render: (r) => `${r.hits} of ${r.events}` },
            { key: "first", label: "Leader first", num: true, sort: (r) => r.lead_share, render: (r) => percent(r.lead_share) },
            { key: "q", label: "Confidence", sort: (r) => -r.q, render: (r) => {
              const level = confidence(r.q);
              return html`<${Badge} tone=${level.tone} title=${`q = ${r.q?.toExponential(1)}`}>${level.label}<//>`;
            } },
          ]} />`}
      <//>

      <div class="grid grid-2">
        <${DataCard} state=${record} title="Track record, last 30 days" flush
          sub="Resolved forecasts: came true when the follower picked the term up in time, missed otherwise.">
          ${(d) => html`<${Table} rows=${d.resolved} limit=${10} onRowClick=${(r) => open(r.term, r.kind, follower(r).replace(" (rest)", ""))}
            empty=${html`<${Empty} title="No resolved forecasts yet" />`}
            columns=${[
              { key: "created", label: "Made", sort: (r) => r.created_at, render: (r) => html`<span title=${formatDateTime(r.created_at)}>${ago(r.created_at)}</span>` },
              { key: "term", label: "Term", render: (r) => html`<${TermButton} term=${r.term} onOpen=${() => open(r.term, r.kind, r.leader)} />
                <div class="muted small">${r.leader} → ${follower(r)}</div>` },
              { key: "chance", label: "Chance", num: true, sort: (r) => r.probability, render: (r) => percent(r.probability) },
              { key: "outcome", label: "Outcome", sort: (r) => r.outcome, render: (r) => r.outcome === "hit"
                ? html`<${Badge} tone="good">✓ came true<//>` : html`<${Badge}>✗ missed<//>` },
              { key: "warning", label: "Warning", num: true, sort: (r) => r.warning_hours,
                help: "Time from the forecast to the follower picking it up.",
                render: (r) => (r.outcome === "hit" ? duration(r.warning_hours) : "–") },
            ]} />`}
        <//>
        <${DataCard} state=${record} title="Calibration, last 90 days" flush
          help="Well calibrated forecasts come true about as often as they say. Usually: what always forecasting the follower's usual rate would say.">
          ${(d) => html`<${Table} rows=${d.calibration} limit=${5} empty=${html`<${Empty} title="Nothing resolved in 90 days" />`}
            columns=${[
              { key: "bin", label: "Forecast said", render: (r) => `${r.bin * 20}–${r.bin * 20 + 20}%` },
              { key: "n", label: "Forecasts", num: true, render: (r) => count(r.forecasts) },
              { key: "predicted", label: "On average", num: true, render: (r) => percent(r.predicted) },
              { key: "came", label: "Came true", num: true, render: (r) => html`<${Meter} value=${r.came_true} max=${1}>${percent(r.came_true)}<//>` },
              { key: "base", label: "Usually", num: true, render: (r) => percent(r.base_rate) },
            ]} />`}
        <//>
      </div>

      <div class="grid grid-2">
        <${DataCard} state=${record} title="Forecasts per day"
          actions=${html`<${Segmented} label="Range" value=${range} onChange=${(v) => setParams({ range: v })}
            options=${[["14d", "14 days"], ["30d", "30 days"], ["90d", "90 days"]]} />`}>
          ${(d) => html`<${TimeChart} mode="stacked" daily height=${220} series=${[
            ["came_true", "Came true", "var(--s3)"], ["missed", "Missed", "var(--s2)"], ["pending", "Waiting", "var(--s1)"],
          ].map(([key, name, color]) => ({ name, color, points: d.daily.map((row) => [row.time, row[key]]) }))} />`}
        <//>
        <${DataCard} state=${record} title="Onsets against Wikipedia"
          sub="Optional (wikipedia.enabled): for events whose term names a Wikipedia article, did its pageviews rise after the term's first onset? Last 90 days.">
          ${(d) => d.wikipedia.events ? html`<div class="stats" style="margin:0;grid-template-columns:repeat(2,minmax(0,1fr))">
            <${Stat} label="Events with an article" value=${count(d.wikipedia.events)} hint=${`${count(d.wikipedia.with_interest)} with rising views`} />
            <${Stat} label="Onset first" value=${count(d.wikipedia.onset_first)}
              hint=${`${count(d.wikipedia.same_day)} same day, ${count(d.wikipedia.wikipedia_first)} Wikipedia first`} />
            <${Stat} label="Median lead" value=${d.wikipedia.median_lead_days === null ? "–" : decimal(d.wikipedia.median_lead_days)} unit="days" />
          </div>` : html`<${Empty} title="Not enabled, or nothing to compare yet">Turn it on with wikipedia.enabled in config.yaml, or run wgra wikipedia.<//>`}
        <//>
      </div>
    </div>`;
}
