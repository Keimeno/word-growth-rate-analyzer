// SVG charts: time series (lines, grouped or stacked bars) and the leader -> follower graph.
// Thin marks, hairline grid, one y axis, a crosshair with every series' value on hover.
import { html, useCallback, useEffect, useMemo, useRef, useState } from "./vendor/preact-htm.js";
import { SERIES, count, decimal, toDate } from "./lib.js";
import { Empty } from "./ui.js";

/** The width of the element the returned ref is put on, whichever node that ends up being. */
function useWidth() {
  const [width, setWidth] = useState(0);
  const observer = useRef(null);
  const ref = useCallback((node) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node) return;
    observer.current = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.current.observe(node);
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, width];
}

function niceMax(value) {
  if (!(value > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * magnitude >= value / 4) * magnitude;
  return Math.ceil(value / step) * step;
}

function compactNumber(value) {
  if (value === 0) return "0";
  if (Math.abs(value) >= 1000) return count(value);
  if (Math.abs(value) >= 10) return decimal(value, 0);
  if (Math.abs(value) >= 1) return decimal(value, value % 1 ? 1 : 0);
  return value.toLocaleString(undefined, { maximumSignificantDigits: 2 });
}

const hourFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const fullFormat = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
// days and weeks are UTC days, shown as such wherever the reader is
const dayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const utcDayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
const monthFormat = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
const dayOnly = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function timeTicks(min, max, count, daily) {
  const span = max - min;
  const hour = 3600e3, day = 24 * hour;
  const steps = [hour, 3 * hour, 6 * hour, 12 * hour, day, 2 * day, 7 * day, 14 * day, 30 * day, 91 * day, 182 * day, 365 * day];
  const step = steps.find((s) => s >= (daily ? day : 0) && span / s <= count) || steps[steps.length - 1];
  const offset = daily ? 0 : new Date(min).getTimezoneOffset() * 60e3;
  const ticks = [];
  // local midnights and whole hours
  let tick = Math.ceil((min - offset) / Math.min(step, day)) * Math.min(step, day) + offset;
  if (step > day) tick = Math.ceil((min - offset) / day) * day + offset;
  for (; tick <= max; tick += step) ticks.push(tick);
  const format = step < day ? (t) => (new Date(t).getHours() === 0 ? dayFormat.format(t) : hourFormat.format(t))
    : step < 30 * day ? (t) => (daily ? utcDayFormat : dayFormat).format(t) : (t) => monthFormat.format(t);
  return ticks.map((t) => [t, format(t)]);
}

/**
 * series: [{ name, points: [[time, value], ...], color? }] with times as ms or ISO strings.
 * mode: line | bars | stacked. `daily`: the points are whole days (tooltips show the date).
 */
export function TimeChart({ series, mode = "line", height = 220, format = compactNumber, daily = false, empty, unit = "" }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const prepared = useMemo(() => {
    const all = series.map((s, index) => ({
      ...s,
      color: s.color || SERIES[index % SERIES.length],
      points: s.points.map(([t, v]) => [toDate(t).getTime(), v ?? 0]).sort((a, b) => a[0] - b[0]),
    }));
    const xs = [...new Set(all.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b);
    const lookup = all.map((s) => new Map(s.points));
    let max = 0;
    if (mode === "stacked") {
      for (const x of xs) max = Math.max(max, lookup.reduce((sum, m) => sum + (m.get(x) || 0), 0));
    } else {
      for (const s of all) for (const [, v] of s.points) max = Math.max(max, v);
    }
    return { all, xs, lookup, max: niceMax(max) };
  }, [series, mode]);

  const { all, xs, lookup, max } = prepared;
  if (!xs.length) {
    return html`<div ref=${ref}>${empty || html`<${Empty} title="No data in this range" />`}</div>`;
  }
  const left = 44, right = 12, top = 8, bottom = 26;
  const plotWidth = Math.max(10, width - left - right);
  const plotHeight = height - top - bottom;
  const bars = mode !== "line";
  const minX = xs[0], maxX = xs[xs.length - 1];
  const gap = xs.length > 1 ? Math.min(...xs.slice(1).map((x, i) => x - xs[i])) : daily ? 864e5 : 3600e3;
  // bars sit in bands, so the domain reaches half a band past each end
  const domainMin = bars ? minX - gap / 2 : minX;
  const domainMax = bars ? maxX + gap / 2 : maxX === minX ? minX + 1 : maxX;
  const x = (t) => left + ((t - domainMin) / (domainMax - domainMin || 1)) * plotWidth;
  const y = (v) => top + plotHeight - (v / max) * plotHeight;
  const band = (gap / (domainMax - domainMin || 1)) * plotWidth;
  const grouped = mode === "bars" ? all.length : 1;
  const barWidth = Math.max(1, Math.min(24, (band * 0.72) / grouped - (grouped > 1 ? 1 : 0)));
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const xTicks = width ? timeTicks(domainMin, domainMax, Math.max(2, Math.floor(plotWidth / 90)), daily) : [];

  const move = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left;
    let nearest = 0;
    for (let i = 1; i < xs.length; i++) if (Math.abs(x(xs[i]) - px) < Math.abs(x(xs[nearest]) - px)) nearest = i;
    setHover({ index: nearest, px: x(xs[nearest]) });
  };

  const marks = [];
  if (mode === "line") {
    all.forEach((s, index) => {
      if (!s.points.length) return;
      const d = s.points.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("");
      if (all.length === 1) {
        const area = `${d}L${x(s.points[s.points.length - 1][0]).toFixed(1)},${y(0)}L${x(s.points[0][0]).toFixed(1)},${y(0)}Z`;
        marks.push(html`<path d=${area} fill=${s.color} opacity="0.1" />`);
      }
      marks.push(html`<path key=${index} d=${d} fill="none" stroke=${s.color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />`);
      if (s.points.length === 1) {
        const [t, v] = s.points[0];
        marks.push(html`<circle cx=${x(t)} cy=${y(v)} r="4" fill=${s.color} stroke="var(--surface)" stroke-width="2" />`);
      }
    });
  } else {
    xs.forEach((t, i) => {
      let base = 0;
      all.forEach((s, index) => {
        const v = lookup[index].get(t) || 0;
        if (!v) return;
        const bx = mode === "bars" ? x(t) - (grouped * (barWidth + 1)) / 2 + index * (barWidth + 1) : x(t) - barWidth / 2;
        const y0 = y(base), y1 = y(base + v);
        // a 2px surface gap between stacked segments
        const h = Math.max(1, y0 - y1 - (mode === "stacked" && base > 0 ? 2 : 0));
        const radius = Math.min(3, barWidth / 2, h / 2);
        marks.push(html`<path key=${`${i}-${index}`} fill=${s.color} opacity=${hover && hover.index !== i ? 0.55 : 1}
          d=${roundedTop(bx, y0 - (mode === "stacked" && base > 0 ? 2 : 0), barWidth, h, radius)} />`);
        if (mode === "stacked") base += v;
      });
    });
  }

  const tooltip = hover && (() => {
    const t = xs[hover.index];
    const rows = all.map((s, index) => [s, lookup[index].get(t)]).filter(([, v]) => v !== undefined);
    if (mode === "line") rows.sort((a, b) => b[1] - a[1]);
    const total = mode === "stacked" ? rows.reduce((sum, [, v]) => sum + v, 0) : null;
    const leftSide = hover.px > width / 2;
    return html`<div class="tooltip" style=${`top:${top}px;${leftSide ? `right:${width - hover.px + 12}px` : `left:${hover.px + 12}px`}`}>
      <div class="when">${daily ? dayOnly.format(t) : fullFormat.format(t)}</div>
      ${rows.slice(0, 10).map(([s, v]) => html`<div class="row">
        <span><span class="key" style=${`background:${s.color}`}></span>${s.name}</span><strong>${format(v)}${unit}</strong>
      </div>`)}
      ${total !== null && rows.length > 1 && html`<div class="row"><span>Total</span><strong>${format(total)}${unit}</strong></div>`}
    </div>`;
  })();

  return html`<div class="chart" ref=${ref}>
    ${all.length > 1 && html`<div class="legend">${all.map((s) => html`<span>
      <span class="key" style=${`background:${s.color};${bars ? "height:8px;width:8px" : ""}`}></span>${s.name}</span>`)}</div>`}
    ${width > 0 && html`<svg height=${height} viewBox=${`0 0 ${width} ${height}`} role="img"
      aria-label=${`${all.map((s) => s.name).join(", ")} over time`}>
      ${yTicks.map((v) => html`<g>
        <line x1=${left} x2=${left + plotWidth} y1=${y(v)} y2=${y(v)} stroke=${v === 0 ? "var(--axis)" : "var(--grid)"} stroke-width="1" />
        <text x=${left - 8} y=${y(v) + 4} text-anchor="end">${format(v)}</text>
      </g>`)}
      ${xTicks.map(([t, label]) => html`<text x=${x(t)} y=${height - 6} text-anchor="middle">${label}</text>`)}
      ${marks}
      ${hover && mode === "line" && html`<g>
        <line x1=${hover.px} x2=${hover.px} y1=${top} y2=${top + plotHeight} stroke="var(--axis)" stroke-width="1" />
        ${all.map((s, index) => {
          const v = lookup[index].get(xs[hover.index]);
          return v === undefined ? null : html`<circle cx=${hover.px} cy=${y(v)} r="4" fill=${s.color} stroke="var(--surface)" stroke-width="2" />`;
        })}
      </g>`}
      <rect x=${left} y=${top} width=${plotWidth} height=${plotHeight} fill="transparent"
        onPointerMove=${move} onPointerLeave=${() => setHover(null)} />
    </svg>`}
    ${tooltip}
  </div>`;
}

function roundedTop(x, bottom, width, height, r) {
  const top = bottom - height;
  return `M${x},${bottom}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${bottom}Z`;
}

/**
 * Leaders on the left, followers on the right, a curve per edge: thicker the likelier the
 * follower picks a leader's term up. Hover an edge or a node for the numbers.
 */
export function LeadGraph({ edges, describe }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState(null);
  const leaders = [...new Set(edges.map((e) => e.leader))];
  const followers = [...new Set(edges.map((e) => e.followerLabel))];
  const rowHeight = 30;
  const height = Math.max(leaders.length, followers.length) * rowHeight + 16;
  if (!edges.length) return html`<div ref=${ref}></div>`;
  const labelWidth = Math.min(170, width * 0.3);
  const x0 = labelWidth + 8, x1 = width - labelWidth - 8;
  const ly = (name) => 8 + (leaders.indexOf(name) + 0.5) * (height - 16) / leaders.length;
  const fy = (name) => 8 + (followers.indexOf(name) + 0.5) * (height - 16) / followers.length;
  const isActive = (edge) => !active || active === edge || active === edge.leader || active === edge.followerLabel;
  const hovered = typeof active === "object" && active;
  return html`<div class="chart" ref=${ref} onPointerLeave=${() => setActive(null)}>
    ${width > 0 && html`<svg height=${height} viewBox=${`0 0 ${width} ${height}`} role="img" aria-label="Which channels lead which">
      ${edges.map((edge) => {
        const ya = ly(edge.leader), yb = fy(edge.followerLabel), mid = (x0 + x1) / 2;
        return html`<path d=${`M${x0},${ya}C${mid},${ya} ${mid},${yb} ${x1},${yb}`} fill="none"
          stroke="var(--s1)" stroke-width=${1 + 4 * (edge.probability || 0)} stroke-linecap="round"
          opacity=${isActive(edge) ? 0.75 : 0.12} style="cursor:pointer"
          onPointerEnter=${() => setActive(edge)} />`;
      })}
      ${leaders.map((name) => html`<g style="cursor:default" onPointerEnter=${() => setActive(name)}>
        <circle cx=${x0} cy=${ly(name)} r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2" />
        <text x=${x0 - 10} y=${ly(name) + 4} text-anchor="end" style=${`fill:var(--ink);font-size:12px;opacity:${!active || active === name || hovered?.leader === name ? 1 : 0.5}`}>${name}</text>
      </g>`)}
      ${followers.map((name) => html`<g style="cursor:default" onPointerEnter=${() => setActive(name)}>
        <circle cx=${x1} cy=${fy(name)} r="5" fill="var(--s2)" stroke="var(--surface)" stroke-width="2" />
        <text x=${x1 + 10} y=${fy(name) + 4} style=${`fill:var(--ink);font-size:12px;opacity:${!active || active === name || hovered?.followerLabel === name ? 1 : 0.5}`}>${name}</text>
      </g>`)}
    </svg>`}
    ${hovered && html`<div class="tooltip" style=${`top:${Math.min((ly(hovered.leader) + fy(hovered.followerLabel)) / 2, height - 90)}px;left:${width / 2 - 140}px;max-width:280px`}>
      ${describe(hovered)}
    </div>`}
  </div>`;
}
