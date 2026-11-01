/**
 * Undercurrent's ECharts theme, built from the CSS tokens at runtime (src/styles/tokens.css),
 * so CSS stays the single source and the theme follows light and dark.
 *
 * The rules it encodes are in docs/BRAND.md ("Charts") and WEB-DASHBOARD.md §4.4–4.5: thin
 * lines, a hairline grid, one y axis, rounded data ends only, tooltips that lead with the
 * value, threshold lines dashed, bands for annotations.
 *
 *   import * as echarts from "echarts/core";
 *   registerUndercurrentTheme(echarts);            // once, and again when data-theme changes
 *   echarts.init(el, "undercurrent", { renderer: "canvas" });
 */

type Echarts = { registerTheme(name: string, theme: object): void };

const css = (name: string, el: Element = document.documentElement): string =>
  getComputedStyle(el).getPropertyValue(`--${name}`).trim();

/** Reads a token by name (without the `--`): from the page, or from tokens.css in tests. */
export type TokenReader = (name: string) => string;

/** The tokens a chart needs, read from the page. */
export function chartTokens(read: TokenReader = (name) => css(name)) {
  const v = read;
  return {
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`series-${i}`)),
    sequential: [100, 200, 300, 400, 500, 600, 700, 800, 900].map((s) => v(`seq-${s}`)),
    diverging: [
      "div-neg-3",
      "div-neg-2",
      "div-neg-1",
      "div-mid",
      "div-pos-1",
      "div-pos-2",
      "div-pos-3",
    ].map(v),
    surface: v("surface"),
    raised: v("surface-raised"),
    ink: v("ink"),
    inkSecondary: v("ink-secondary"),
    muted: v("chart-label"),
    grid: v("chart-grid"),
    axis: v("chart-axis"),
    crosshair: v("chart-crosshair"),
    threshold: v("chart-threshold"),
    band: v("chart-band"),
    border: v("border"),
    primary: v("primary"),
    critical: v("status-critical"),
    sans: v("typeface-sans") || "IBM Plex Sans, system-ui, sans-serif",
    mono: v("typeface-mono") || "IBM Plex Mono, monospace",
  };
}

export type ChartTokens = ReturnType<typeof chartTokens>;

export function buildTheme(t: ChartTokens = chartTokens()) {
  const label = { color: t.muted, fontFamily: t.sans, fontSize: 11 };
  const axisCommon = {
    axisLine: { show: true, lineStyle: { color: t.axis, width: 1 } },
    axisTick: { show: false },
    axisLabel: { ...label, hideOverlap: true },
    splitLine: { show: true, lineStyle: { color: t.grid, width: 1 } },
    splitArea: { show: false },
    nameTextStyle: { ...label },
  };
  return {
    color: t.series, // fixed order, never cycled: past 8 series, fold into "Other"
    backgroundColor: "transparent", // the panel paints the surface
    textStyle: { fontFamily: t.sans, color: t.ink, fontSize: 13 },
    title: {
      left: 0,
      textStyle: { color: t.ink, fontFamily: t.sans, fontSize: 14, fontWeight: 600 },
      subtextStyle: { color: t.muted, fontFamily: t.sans, fontSize: 12 },
    },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    legend: {
      // a legend for 2+ series; direct labels as well for up to 4 (the kit adds endLabel)
      top: 0,
      left: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 2,
      itemGap: 14,
      textStyle: { color: t.inkSecondary, fontFamily: t.sans, fontSize: 12 },
      pageIconColor: t.inkSecondary,
      pageIconInactiveColor: t.axis,
      pageTextStyle: { color: t.muted, fontFamily: t.sans, fontSize: 11 },
      inactiveColor: t.axis,
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: t.raised,
      borderColor: t.border,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.ink, fontFamily: t.sans, fontSize: 12 },
      extraCssText:
        "box-shadow: var(--elevation-popover); border-radius: 6px; font-variant-numeric: tabular-nums; min-width: 160px;",
      axisPointer: { type: "line", lineStyle: { color: t.crosshair, width: 1, type: [3, 3] } },
    },
    axisPointer: {
      lineStyle: { color: t.crosshair, width: 1 },
      label: { backgroundColor: t.ink, color: t.surface, fontFamily: t.sans },
    },
    categoryAxis: { ...axisCommon, splitLine: { show: false } },
    valueAxis: { ...axisCommon, axisLine: { show: false } }, // horizontal gridlines carry the scale
    timeAxis: { ...axisCommon, splitLine: { show: false } },
    logAxis: { ...axisCommon, axisLine: { show: false } },
    line: {
      lineStyle: { width: 2 },
      symbol: "circle",
      symbolSize: 8,
      showSymbol: false, // markers only on hover and at the end
      smooth: false, // shares are measured per bucket: never interpolate a curve between them
      emphasis: { focus: "series", lineStyle: { width: 2.5 } },
      blur: { lineStyle: { opacity: 0.25 } },
      endLabel: { color: t.inkSecondary, fontFamily: t.sans, fontSize: 11 },
    },
    bar: {
      barMaxWidth: 24,
      itemStyle: { borderRadius: [4, 4, 0, 0], borderColor: t.surface, borderWidth: 0 }, // flip for horizontal bars
      emphasis: { focus: "series" },
      blur: { itemStyle: { opacity: 0.25 } },
    },
    scatter: { symbolSize: 8, itemStyle: { borderColor: t.surface, borderWidth: 2 } }, // the 2px ring
    heatmap: { itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 2 } },
    visualMap: {
      inRange: { color: t.sequential }, // sequential: one hue; switch to t.diverging for signed values
      textStyle: { color: t.muted, fontFamily: t.sans, fontSize: 12 },
      itemWidth: 10,
      itemHeight: 120,
    },
    graph: {
      lineStyle: { color: t.axis, width: 1, curveness: 0.15 },
      label: { color: t.inkSecondary, fontFamily: t.sans, fontSize: 12 },
      itemStyle: { borderColor: t.surface, borderWidth: 2 },
      emphasis: { focus: "adjacency", lineStyle: { width: 2 } },
    },
    sankey: {
      lineStyle: { color: "gradient", opacity: 0.35, curveness: 0.5 },
      itemStyle: { borderWidth: 0 },
      label: { color: t.inkSecondary, fontFamily: t.sans, fontSize: 12 },
      nodeGap: 8,
      nodeWidth: 10,
    },
    dataZoom: {
      backgroundColor: "transparent",
      borderColor: t.border,
      fillerColor: t.band,
      handleStyle: { color: t.surface, borderColor: t.primary },
      moveHandleStyle: { color: t.axis },
      textStyle: { color: t.muted, fontFamily: t.sans },
      dataBackground: { lineStyle: { color: t.axis }, areaStyle: { color: t.grid } },
    },
    brush: { brushStyle: { color: t.band, borderColor: t.primary, borderWidth: 1 } },
    markLine: { symbol: "none", silent: true },
    aria: { enabled: true, decal: { show: false } }, // decals on for forced-colors, print and the texture setting
    animationDuration: 300,
    animationDurationUpdate: 300,
    animationEasing: "cubicOut",
  };
}

/** A threshold or reference line: dashed, muted, labelled at the end ("2× usual", "z 3"). */
export function threshold(value: number, label: string, t: ChartTokens = chartTokens()) {
  return {
    symbol: "none",
    silent: true,
    lineStyle: { color: t.threshold, width: 1, type: [4, 3] },
    label: {
      formatter: label,
      position: "insideEndTop",
      color: t.muted,
      fontFamily: t.sans,
      fontSize: 11,
    },
    data: [{ yAxis: value }],
  };
}

/** An annotation band: a trending run, a forecast window, the long-term window. */
export function band(from: string | number, to: string | number, label: string, t = chartTokens()) {
  return {
    silent: true,
    itemStyle: { color: t.band },
    label: {
      formatter: label,
      position: "insideTop",
      color: t.muted,
      fontFamily: t.sans,
      fontSize: 11,
    },
    data: [[{ xAxis: from }, { xAxis: to }]],
  };
}

/** Alerts sent, as small ink pins on the series (not status colours: an alert is an event). */
export function alertPins(
  points: Array<{ x: string | number; y: number; label: string }>,
  t = chartTokens(),
) {
  return {
    symbol: "pin",
    symbolSize: 22,
    itemStyle: { color: t.ink },
    label: { color: t.surface, fontSize: 10, fontFamily: t.sans, formatter: "!" },
    data: points.map((p) => ({ coord: [p.x, p.y], name: p.label })),
  };
}

/** Register (or re-register after a theme switch) and return the theme's name. */
export function registerUndercurrentTheme(echarts: Echarts, t?: ChartTokens): string {
  echarts.registerTheme("undercurrent", buildTheme(t));
  return "undercurrent";
}
