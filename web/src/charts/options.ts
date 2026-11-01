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
