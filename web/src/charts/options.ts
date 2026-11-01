/**
 * The kit's option builders: pure functions from typed data to an ECharts option, where the
 * dataviz rules live (thin lines, one y axis, direct labels for up to 4 series, tooltips that
 * lead with the value, hairline grid), so pages can't break them. Pure, so unit tests can
 * render them to SVG in Node (options.test.ts).
 */
import type { EChartsOption } from "./echarts";
import type { ChartTokens } from "./theme";

export type Point = [time: number, value: number | null];

export interface Series {
  name: string;
  /** a series colour as a CSS variable (`var(--series-3)`) or a hex value */
  color?: string | undefined;
  points: Point[];
}

export interface Annotation {
  /** a dashed line at a value: "×2 usual", "z 3" */
  thresholds?: Array<{ value: number; label: string }>;
  /** a band between two times: a trending run, a forecast window */
  bands?: Array<{ from: number; to: number; label: string }>;
  /** a vertical line at a time: an alert sent, an onset */
  marks?: Array<{ at: number; label: string }>;
}

export interface TimeSeriesSpec extends Annotation {
  series: Series[];
  form?: "line" | "area" | "bars" | "stacked";
  format?: (value: number) => string;
  /** buckets of a day or more: dates without hours */
  daily?: boolean;
  /** a brush along x that reports the picked range */
  brush?: boolean;
  reducedMotion?: boolean;
}

const escape = (text: string): string =>
  text.replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] ?? char,
  );

/** `var(--series-3)` as the hex value the canvas needs; anything else as it is. */
export function resolveColor(color: string | undefined, tokens: ChartTokens): string | undefined {
  const match = color?.match(/^var\(--series-(\d)\)$/);
  if (match) return tokens.series[Number(match[1]) - 1];
  const named = color?.match(/^var\(--([\w-]+)\)$/);
  if (named?.[1]) {
    const known: Record<string, string> = {
      primary: tokens.primary,
      ink: tokens.ink,
      "ink-secondary": tokens.inkSecondary,
      "chart-axis": tokens.axis,
      "status-critical": tokens.critical,
    };
    return known[named[1]] ?? color;
  }
  return color;
}

const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});
const date = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});
const plain = (value: number): string => value.toLocaleString("en", { maximumFractionDigits: 2 });

interface TooltipParam {
  seriesName: string;
  value: [number, number | null];
  color: string;
}

function tooltip(spec: TimeSeriesSpec, tokens: ChartTokens) {
  const format = spec.format ?? plain;
  return {
    trigger: "axis",
    confine: true,
    formatter: (params: TooltipParam | TooltipParam[]) => {
      const rows = (Array.isArray(params) ? params : [params])
        .filter((param) => param.value[1] !== null)
        .sort((a, b) => (b.value[1] ?? 0) - (a.value[1] ?? 0));
      const time = rows[0]?.value[0] ?? (Array.isArray(params) ? params[0]?.value[0] : 0) ?? 0;
      const head = `<div style="color:${tokens.muted};margin-bottom:4px">${
        spec.daily ? date.format(time) : `${dateTime.format(time)} UTC`
      }</div>`;
      return (
        head +
        rows
          .slice(0, 12)
          .map(
            (row) =>
              `<div style="display:flex;gap:8px;align-items:center;justify-content:space-between">` +
              `<span style="display:flex;gap:6px;align-items:center"><span style="width:10px;height:2px;background:${row.color};display:inline-block"></span>${escape(row.seriesName)}</span>` +
              `<b style="font-weight:500">${format(row.value[1] ?? 0)}</b></div>`,
          )
          .join("") +
        (rows.length > 12
          ? `<div style="color:${tokens.muted}">+${rows.length - 12} more</div>`
          : "")
      );
    },
  };
}

/** Lines (an area for a single series), bars, or stacked bars over time. */
export function timeSeries(spec: TimeSeriesSpec, tokens: ChartTokens): EChartsOption {
  const form = spec.form ?? (spec.series.length === 1 ? "area" : "line");
  const bars = form === "bars" || form === "stacked";
  const labelled = !bars && spec.series.length <= 4;
  const format = spec.format ?? plain;
  const annotations = annotate(spec, tokens);
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    legend: spec.series.length > 1 ? { type: "scroll" } : { show: false },
    grid: {
      left: 8,
      right: labelled ? 96 : 16,
      top: spec.series.length > 1 ? 32 : 16,
      bottom: 8,
      containLabel: true,
    },
    tooltip: tooltip(spec, tokens),
    xAxis: {
      type: "time",
      axisLabel: { hideOverlap: true },
      ...(bars ? { boundaryGap: ["2%", "2%"] } : {}),
    },
    yAxis: { type: "value", axisLabel: { formatter: format }, min: 0 },
    ...(spec.brush
      ? {
          brush: {
            xAxisIndex: 0,
            brushType: "lineX",
            brushMode: "single",
            throttleType: "debounce",
          },
          toolbox: { show: false },
        }
      : {}),
    series: spec.series.map((series, index) => {
      const color = resolveColor(series.color, tokens) ?? tokens.series[index % 8];
      return {
        name: series.name,
        type: bars ? "bar" : "line",
        data: series.points,
        color,
        ...(form === "stacked" ? { stack: "total", barMaxWidth: 24 } : {}),
        ...(form === "bars" ? { barMaxWidth: 16, barGap: "10%" } : {}),
        ...(form === "area" ? { areaStyle: { opacity: 0.12 } } : {}),
        ...(labelled
          ? {
              endLabel: {
                show: true,
                formatter: ({ seriesName }: { seriesName: string }) =>
                  seriesName.length > 14 ? `${seriesName.slice(0, 13)}…` : seriesName,
              },
              labelLayout: { moveOverlap: "shiftY" },
            }
          : {}),
        connectNulls: false,
        ...(index === 0 ? annotations : {}),
      };
    }),
  };
}

function annotate(spec: Annotation, tokens: ChartTokens) {
  const label = { color: tokens.muted, fontFamily: tokens.sans, fontSize: 11 };
  return {
    markLine: {
      symbol: "none",
      silent: true,
      animation: false,
      data: [
        ...(spec.thresholds ?? []).map((line) => ({
          yAxis: line.value,
          lineStyle: { color: tokens.threshold, width: 1, type: [4, 3] },
          label: { ...label, formatter: line.label, position: "insideEndTop" },
        })),
        ...(spec.marks ?? []).map((mark) => ({
          xAxis: mark.at,
          lineStyle: { color: tokens.ink, width: 1, type: "solid" },
          label: { ...label, color: tokens.ink, formatter: mark.label, position: "insideEndTop" },
        })),
      ],
    },
    markArea: {
      silent: true,
      itemStyle: { color: tokens.band },
      label: { ...label, position: "insideTop" },
      data: (spec.bands ?? []).map((band) => [
        { xAxis: band.from, name: band.label },
        { xAxis: band.to },
      ]),
    },
  };
}

export interface HeatmapSpec {
  x: string[];
  y: string[];
  /** [x index, y index, value] */
  cells: Array<[number, number, number | null]>;
  format?: (value: number) => string;
  /** signed values: diverging rust ↔ Current around zero */
  diverging?: boolean;
  reducedMotion?: boolean;
}

/** Cells on two axes, sequential Current for magnitude or diverging for signed values. */
export function heatmap(spec: HeatmapSpec, tokens: ChartTokens): EChartsOption {
  const values = spec.cells
    .map((cell) => cell[2])
    .filter((value): value is number => value !== null);
  const max = Math.max(...values.map(Math.abs), 0) || 1;
  const format = spec.format ?? plain;
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    grid: { left: 8, right: 16, top: 8, bottom: 40, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: ({ value }: { value: [number, number, number | null] }) =>
        `${escape(spec.y[value[1]] ?? "")} · ${escape(spec.x[value[0]] ?? "")}<br><b style="font-weight:500">${
          value[2] === null ? "–" : format(value[2])
        }</b>`,
    },
    xAxis: {
      type: "category",
      data: spec.x,
      splitLine: { show: false },
      axisLine: { show: false },
    },
    yAxis: {
      type: "category",
      data: spec.y,
      splitLine: { show: false },
      axisLine: { show: false },
    },
    visualMap: {
      min: spec.diverging ? -max : 0,
      max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemHeight: 120,
      itemWidth: 10,
      inRange: { color: spec.diverging ? tokens.diverging : tokens.sequential.slice(0, 8) },
      formatter: (value: number) => format(value),
    },
    series: [
      { type: "heatmap", data: spec.cells, emphasis: { itemStyle: { borderColor: tokens.ink } } },
    ],
  };
}

export interface NetworkNode {
  id: string;
  /** 0–1 across, 0–1 down: positions that mean something (leaders left, followers right) */
  x: number;
  y: number;
  size?: number;
  label?: string;
}

export interface NetworkEdge {
  source: string;
  target: string;
  /** 0–1, the line's weight */
  weight: number;
  label?: string;
  tooltip?: string;
}

/** A graph with fixed positions, edges weighted by strength. */
export function network(
  spec: { nodes: NetworkNode[]; edges: NetworkEdge[]; reducedMotion?: boolean },
  tokens: ChartTokens,
): EChartsOption {
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    tooltip: {
      trigger: "item",
      formatter: (param: { dataType: string; data: { tooltip?: string; name?: string } }) =>
        param.data.tooltip ?? escape(param.data.name ?? ""),
    },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: false,
        left: 96,
        right: 96,
        top: 24,
        bottom: 24,
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 7,
        label: { show: true, position: "right", color: tokens.inkSecondary, fontSize: 12 },
        itemStyle: { color: tokens.primary, borderColor: tokens.surface, borderWidth: 2 },
        lineStyle: { color: tokens.axis, curveness: 0.15 },
        data: spec.nodes.map((node) => ({
          name: node.id,
          x: node.x * 1000,
          y: node.y * 1000,
          symbolSize: node.size ?? 10,
          label: { formatter: node.label ?? node.id },
          tooltip: escape(node.label ?? node.id),
        })),
        links: spec.edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          tooltip: edge.tooltip,
          lineStyle: {
            width: 1 + 5 * edge.weight,
            opacity: 0.35 + 0.6 * edge.weight,
            color: edge.weight > 0.5 ? tokens.primary : tokens.axis,
          },
        })),
      },
    ],
  };
}

/** Dots with jitter along one axis, the median as a line: an edge's lags. */
export function strip(
  spec: {
    values: number[];
    format: (value: number) => string;
    label: string;
    reducedMotion?: boolean;
  },
  tokens: ChartTokens,
): EChartsOption {
  const sorted = [...spec.values].sort((a, b) => a - b);
  const median = sorted.length ? (sorted[Math.floor((sorted.length - 1) / 2)] ?? 0) : 0;
  // a fixed jitter per index, so the chart is the same every render
  const jitter = (index: number) => ((index * 0.618_034) % 1) - 0.5;
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: ({ value }: { value: [number, number] }) => spec.format(value[0]),
    },
    xAxis: { type: "value", min: 0, axisLabel: { formatter: spec.format } },
    yAxis: { type: "value", min: -1, max: 1, show: false },
    series: [
      {
        type: "scatter",
        name: spec.label,
        data: spec.values.map((value, index) => [value, jitter(index)]),
        symbolSize: 7,
        itemStyle: { color: tokens.series[0], opacity: 0.8 },
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { color: tokens.ink, width: 1.5 },
          label: { formatter: `median ${spec.format(median)}`, color: tokens.ink, fontSize: 11 },
          data: [{ xAxis: median }],
        },
      },
    ],
  };
}

/** Switching flows as a bipartite Sankey: products on the left as "from", on the right as
 * "to", so flows both ways don't make cycles. */
export function flows(
  spec: { flows: Array<{ from: string; to: string; mentions: number }>; reducedMotion?: boolean },
  tokens: ChartTokens,
): EChartsOption {
  const left = [...new Set(spec.flows.map((flow) => flow.from))];
  const right = [...new Set(spec.flows.map((flow) => flow.to))];
  const colors = new Map(
    [...left, ...right].map((name, index) => [name, tokens.series[index % 8]]),
  );
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    tooltip: {
      trigger: "item",
      formatter: (param: {
        dataType: string;
        data: { source?: string; target?: string; value?: number; name?: string };
      }) =>
        param.dataType === "edge"
          ? `${escape((param.data.source ?? "").slice(5))} → ${escape((param.data.target ?? "").slice(3))}<br><b style="font-weight:500">${param.data.value ?? 0} mentions</b>`
          : escape((param.data.name ?? "").replace(/^(from|to): /, "")),
    },
    series: [
      {
        type: "sankey",
        left: 8,
        right: 96,
        top: 8,
        bottom: 8,
        nodeAlign: "justify",
        layoutIterations: 0,
        label: {
          color: tokens.inkSecondary,
          fontSize: 12,
          formatter: ({ name }: { name: string }) => name.replace(/^(from|to): /, ""),
        },
        lineStyle: { color: "source", opacity: 0.35, curveness: 0.5 },
        data: [
          ...left.map((name) => ({
            name: `from: ${name}`,
            itemStyle: { color: colors.get(name) },
          })),
          ...right.map((name) => ({ name: `to: ${name}`, itemStyle: { color: colors.get(name) } })),
        ],
        links: spec.flows.map((flow) => ({
          source: `from: ${flow.from}`,
          target: `to: ${flow.to}`,
          value: flow.mentions,
        })),
      },
    ],
  };
}

/** Ranks over time on an inverted axis, one line per term: a bump chart. */
export function bump(
  spec: { series: Series[]; top: number; reducedMotion?: boolean },
  tokens: ChartTokens,
): EChartsOption {
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    legend: { type: "scroll" },
    grid: { left: 8, right: 112, top: 32, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis" },
    xAxis: { type: "time", axisLabel: { hideOverlap: true } },
    yAxis: {
      type: "value",
      inverse: true,
      min: 1,
      max: spec.top,
      interval: 1,
      axisLabel: { formatter: (value: number) => `#${value}` },
    },
    series: spec.series.map((series, index) => ({
      name: series.name,
      type: "line",
      data: series.points,
      color: resolveColor(series.color, tokens) ?? tokens.series[index % 8],
      showSymbol: true,
      symbolSize: 5,
      connectNulls: false,
      endLabel: { show: true, formatter: ({ seriesName }: { seriesName: string }) => seriesName },
      labelLayout: { moveOverlap: "shiftY" },
      emphasis: { focus: "series" },
    })),
  };
}

/** A year of days, sequential Current by value. */
export function calendar(
  spec: {
    days: Array<[string, number | null]>;
    format: (value: number) => string;
    reducedMotion?: boolean;
  },
  tokens: ChartTokens,
): EChartsOption {
  const values = spec.days.map((day) => day[1]).filter((value): value is number => value !== null);
  const first = spec.days[0]?.[0];
  const last = spec.days.at(-1)?.[0];
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    tooltip: {
      trigger: "item",
      formatter: ({ value }: { value: [string, number | null] }) =>
        `${value[0]}<br><b style="font-weight:500">${value[1] === null ? "–" : spec.format(value[1])}</b>`,
    },
    visualMap: {
      show: false,
      min: 0,
      max: Math.max(...values, 0) || 1,
      inRange: { color: tokens.sequential.slice(0, 8) },
    },
    calendar: {
      range: first && last ? [first, last] : undefined,
      top: 24,
      left: 32,
      right: 8,
      cellSize: ["auto", 12],
      splitLine: { show: false },
      itemStyle: { color: tokens.surface, borderColor: tokens.surface, borderWidth: 2 },
      dayLabel: {
        color: tokens.muted,
        fontSize: 10,
        firstDay: 1,
        nameMap: ["S", "M", "T", "W", "T", "F", "S"],
      },
      monthLabel: { color: tokens.muted, fontSize: 10 },
      yearLabel: { show: false },
    },
    series: [{ type: "heatmap", coordinateSystem: "calendar", data: spec.days }],
  };
}

/** Forecast calibration: what was said against what came true per bin, with Wilson
 * intervals, the diagonal of perfect calibration and the base rate. */
export function calibration(
  spec: {
    bins: Array<{
      predicted: number;
      cameTrue: number;
      low: number;
      high: number;
      forecasts: number;
      baseRate: number;
    }>;
    reducedMotion?: boolean;
  },
  tokens: ChartTokens,
): EChartsOption {
  const percent = (value: number) => `${Math.round(100 * value)}%`;
  return {
    animation: !spec.reducedMotion,
    aria: { enabled: true },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: ({ value }: { value: [number, number, number] }) =>
        `Said ${percent(value[0])}, came true ${percent(value[1])}<br>${value[2]} forecasts`,
    },
    xAxis: {
      type: "value",
      min: 0,
      max: 1,
      name: "said",
      nameLocation: "middle",
      nameGap: 24,
      axisLabel: { formatter: percent },
    },
    yAxis: { type: "value", min: 0, max: 1, axisLabel: { formatter: percent } },
    series: [
      {
        type: "line",
        silent: true,
        symbol: "none",
        data: [
          [0, 0],
          [1, 1],
        ],
        lineStyle: { color: tokens.threshold, type: [4, 3], width: 1 },
      },
      {
        type: "line",
        silent: true,
        symbol: "none",
        connectNulls: false,
        lineStyle: { color: tokens.series[0], width: 2, opacity: 0.6 },
        data: spec.bins.flatMap((bin) => [
          [bin.predicted, bin.low],
          [bin.predicted, bin.high],
          null,
        ]),
      },
      {
        type: "scatter",
        name: "came true",
        data: spec.bins.map((bin) => [bin.predicted, bin.cameTrue, bin.forecasts]),
        symbolSize: (value: [number, number, number]) => 6 + Math.min(14, Math.sqrt(value[2]) * 2),
        itemStyle: { color: tokens.series[0] },
      },
      {
        type: "scatter",
        name: "usually",
        data: spec.bins.map((bin) => [bin.predicted, bin.baseRate, bin.forecasts]),
        symbol: "diamond",
        symbolSize: 7,
        itemStyle: { color: tokens.muted },
      },
    ],
  };
}

/** Wilson's interval for `hits` of `trials`, at about 90%. */
export function wilson(hits: number, trials: number, z = 1.645): [number, number] {
  if (!trials) return [0, 1];
  const p = hits / trials;
  const denominator = 1 + (z * z) / trials;
  const centre = (p + (z * z) / (2 * trials)) / denominator;
  const margin =
    (z * Math.sqrt((p * (1 - p)) / trials + (z * z) / (4 * trials * trials))) / denominator;
  return [Math.max(0, centre - margin), Math.min(1, centre + margin)];
}
