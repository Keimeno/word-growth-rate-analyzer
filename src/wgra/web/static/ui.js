// Shared pieces: cards, stats, pickers, tables, sparklines.
import { html, useEffect, useMemo, useRef, useState } from "./vendor/preact-htm.js";
import { count, KIND_LABELS } from "./lib.js";

export function Help({ text }) {
  if (!text) return null;
  return html`<span class="help">
    <button type="button" aria-label="What is this?">?</button>
    <span class="bubble" role="tooltip">${text}</span>
  </span>`;
}

export function Card({ title, sub, help, actions, refreshing, children, flush, id }) {
  return html`<section class=${`card${refreshing ? " refreshing" : ""}`} id=${id}>
    ${(title || actions) &&
    html`<div class="card-head">
      <div>
        <h2>${title}<${Help} text=${help} /></h2>
        ${sub && html`<div class="sub">${sub}</div>`}
      </div>
      ${actions}
    </div>`}
    <div class=${flush ? "card-body flush" : "card-body"}>${children}</div>
  </section>`;
}

/** A card around an endpoint's state: loading, error, or its content. */
export function DataCard({ state, children, ...card }) {
  const { data, error, loading } = state;
  let body;
  if (error && !data) body = html`<div class="error">Couldn't load this: ${error.message}</div>`;
  else if (!data) body = html`<div class="loading">Loading…</div>`;
  else body = children(data);
  return html`<${Card} ...${card} refreshing=${loading && data}>${body}<//>`;
}

export function Stat({ label, value, unit, hint, help, onClick, pressed }) {
  const content = html`
    <div class="label">${label}<${Help} text=${help} /></div>
    <div class="value">${value ?? "–"}${unit && html`<span class="unit">${unit}</span>`}</div>
    ${hint && html`<div class="hint">${hint}</div>`}`;
  if (onClick) {
    return html`<button type="button" class="card stat" onClick=${onClick} aria-pressed=${pressed ? "true" : "false"}>${content}</button>`;
  }
  return html`<div class="card stat">${content}</div>`;
}

export function Empty({ title, children }) {
  return html`<div class="empty"><strong>${title}</strong>${children && html`<p>${children}</p>`}</div>`;
}

export function Badge({ tone = "", children, title }) {
  return html`<span class=${`badge ${tone}`} title=${title}>${children}</span>`;
}

export function Kind({ kind }) {
  if (!kind || kind === "word") return null;
  const label = { phrase: "phrase", domain: "link", subreddit: "subreddit" }[kind] || kind;
  return html`<span class="kind">${label}</span>`;
}

// --- Pickers --------------------------------------------------------------------------

export function Field({ label, children }) {
  return html`<label class="field"><span class="label">${label}</span>${children}</label>`;
}

export function Segmented({ options, value, onChange, label }) {
  return html`<div class="segmented" role="group" aria-label=${label}>
    ${options.map(([key, text]) => html`<button type="button" aria-pressed=${key === value ? "true" : "false"}
      onClick=${() => onChange(key)}>${text}</button>`)}
  </div>`;
}

export function Select({ value, options, onChange, label }) {
  return html`<select class="select" value=${value} aria-label=${label} onChange=${(event) => onChange(event.target.value)}>
    ${options.map((option) =>
      option.group
        ? html`<optgroup label=${option.group}>${option.options.map(
            ([key, text]) => html`<option value=${key} selected=${key === value}>${text}</option>`
          )}</optgroup>`
        : html`<option value=${option[0]} selected=${option[0] === value}>${option[1]}</option>`
    )}
  </select>`;
}

/** The scope picker: platforms ("all of reddit"), configured groups, then channels. */
export function ScopePicker({ meta, value, onChange }) {
  const options = useMemo(() => {
    if (!meta) return [[value, value]];
    const of = (type) => meta.scopes.filter((scope) => scope.type === type);
    const groupLabel = (name) => `${name} (${(meta.groups[name] || []).length} channels)`;
    const groups = [
      { group: "Everything", options: of("platform").map((s) => [s.name, `${s.name}: every tracked channel`]) },
      { group: "Groups", options: of("group").map((s) => [s.name, groupLabel(s.name)]) },
      { group: "Channels", options: of("channel").map((s) => [s.name, s.name]) },
    ];
    return groups.filter((group) => group.options.length);
  }, [meta]);
  return html`<${Field} label="Looking at"><${Select} label="Group or channel" value=${value} options=${options} onChange=${onChange} /><//>`;
}

/** Toggle chips for picking several of a few values. */
export function Chips({ options, value, onChange, label }) {
  const toggle = (key) => {
    const next = value.includes(key) ? value.filter((item) => item !== key) : [...value, key];
    if (next.length) onChange(options.map(([option]) => option).filter((option) => next.includes(option)));
  };
  return html`<div class="chips" role="group" aria-label=${label}>
    ${options.map(([key, text]) => html`<button type="button" class="chip" aria-pressed=${value.includes(key) ? "true" : "false"}
      onClick=${() => toggle(key)}>${text}</button>`)}
  </div>`;
}

export function KindChips({ kinds, value, onChange }) {
  return html`<${Chips} label="Kinds" options=${kinds.map((kind) => [kind, KIND_LABELS[kind] || kind])}
    value=${value} onChange=${onChange} />`;
}

/** A dropdown of checkboxes; an empty selection means all of them. */
export function MultiPicker({ label, options, value, onChange, allLabel = "All" }) {
  const ref = useRef();
  useEffect(() => {
    const close = (event) => ref.current && !ref.current.contains(event.target) && ref.current.removeAttribute("open");
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  const selected = value.filter((item) => options.some(([key]) => key === item));
  const summary = !selected.length ? allLabel : selected.length === 1
    ? options.find(([key]) => key === selected[0])[1] : `${selected.length} of ${options.length}`;
  const toggle = (key) => {
    const current = selected.length ? selected : [];
    const next = current.includes(key) ? current.filter((item) => item !== key) : [...current, key];
    onChange(next.length === options.length ? [] : next);
  };
  return html`<div class="field"><span class="label">${label}</span>
    <details class="dropdown" ref=${ref}>
      <summary class="select" role="button">${summary}</summary>
      <div class="dropdown-panel">
        <div class="panel-actions">
          <button type="button" class="link-button" onClick=${() => onChange([])}>${allLabel}</button>
          <span class="muted small">${options.length}</span>
        </div>
        <div class="divider"></div>
        ${options.map(([key, text]) => html`<label>
          <input type="checkbox" checked=${!selected.length || selected.includes(key)} onChange=${() =>
            selected.length ? toggle(key) : onChange([key])} />
          ${text}
        </label>`)}
      </div>
    </details>
  </div>`;
}

export function Toggle({ label, checked, onChange }) {
  return html`<label class="toggle"><input type="checkbox" checked=${checked} onChange=${(event) => onChange(event.target.checked)} />${label}</label>`;
}

export function Tabs({ tabs, value, onChange }) {
  return html`<div class="tabs" role="tablist">
    ${tabs.map(([key, text, n]) => html`<button type="button" role="tab" aria-selected=${key === value ? "true" : "false"}
      onClick=${() => onChange(key)}>${text}${n !== undefined && html`<span class="count">${count(n)}</span>`}</button>`)}
  </div>`;
}

// --- Table ----------------------------------------------------------------------------

/**
 * columns: { key, label, render(row), sort(row) -> value, num, help, width }.
 * Sorting is optional per column; `limit` rows show first, the rest behind a button.
 */
export function Table({ columns, rows, onRowClick, empty, limit = 25, initialSort, rowKey }) {
  const [sort, setSort] = useState(initialSort || null);
  const [showAll, setShowAll] = useState(false);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sort) return rows;
    const direction = sort.desc ? -1 : 1;
    return [...rows].sort((a, b) => {
      const x = column.sort(a), y = column.sort(b);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * direction;
    });
  }, [rows, sort]);
  if (!rows.length) return empty || html`<${Empty} title="Nothing here yet" />`;
  const visible = showAll ? sorted : sorted.slice(0, limit);
  const header = (column) => {
    const active = sort && sort.key === column.key;
    const click = column.sort ? () => setSort({ key: column.key, desc: active ? !sort.desc : true }) : undefined;
    return html`<th class=${`${column.num ? "num " : ""}${column.sort ? "sortable" : ""}`} style=${column.width ? `width:${column.width}` : ""}
      onClick=${click} aria-sort=${active ? (sort.desc ? "descending" : "ascending") : undefined}>
      ${column.label}${active && html`<span class="arrow">${sort.desc ? "▼" : "▲"}</span>`}
      ${column.help && html` <${Help} text=${column.help} />`}
    </th>`;
  };
  return html`<div class="table-wrap">
    <table>
      <thead><tr>${columns.map(header)}</tr></thead>
      <tbody>
        ${visible.map((row, index) => html`<tr key=${rowKey ? rowKey(row) : index} class=${onRowClick ? "clickable" : ""}
          onClick=${onRowClick ? (event) => !event.target.closest("a, button") && onRowClick(row) : undefined}>
          ${columns.map((column) => html`<td class=${column.num ? "num" : ""}>${column.render ? column.render(row) : row[column.key]}</td>`)}
        </tr>`)}
      </tbody>
    </table>
    ${rows.length > limit && html`<div class="table-more">
      <button type="button" class="icon-button" onClick=${() => setShowAll(!showAll)}>
        ${showAll ? "Show fewer" : `Show all ${rows.length}`}
      </button>
    </div>`}
  </div>`;
}

export function Meter({ value, max, children }) {
  const width = max > 0 ? Math.max(2, Math.min(100, (100 * value) / max)) : 0;
  return html`<div class="meter">${children}<div class="meter-track"><div class="meter-fill" style=${`width:${width}%`}></div></div></div>`;
}

// --- Sparkline ------------------------------------------------------------------------

/** A small line of `values` (evenly spaced), with a wash under it and the last point marked. */
export function Sparkline({ values, width = 120, height = 28, color = "var(--s1)", label }) {
  if (!values || !values.length) return html`<span class="muted small">–</span>`;
  const max = Math.max(...values, 0) || 1;
  const step = values.length > 1 ? (width - 4) / (values.length - 1) : 0;
  const y = (v) => height - 3 - ((height - 6) * v) / max;
  const points = values.map((v, i) => `${(2 + i * step).toFixed(1)},${y(v).toFixed(1)}`);
  const last = points[points.length - 1].split(",");
  return html`<svg width=${width} height=${height} viewBox=${`0 0 ${width} ${height}`} role="img" aria-label=${label || "trend"}>
    <polygon points=${`2,${height - 3} ${points.join(" ")} ${2 + (values.length - 1) * step},${height - 3}`}
      fill=${color} opacity="0.1" />
    <polyline points=${points.join(" ")} fill="none" stroke=${color} stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
    <circle cx=${last[0]} cy=${last[1]} r="2.5" fill=${color} stroke="var(--surface)" stroke-width="1.5" />
  </svg>`;
}

export function TermButton({ term, onOpen, color }) {
  return html`<button type="button" class="term-button" onClick=${onOpen}>
    ${color && html`<span class="key" style=${`background:${color}`}></span>`}${term}
  </button>`;
}

export function ExternalLink({ href, children = "Open" }) {
  return html`<a href=${href} target="_blank" rel="noopener noreferrer">${children} ↗</a>`;
}
