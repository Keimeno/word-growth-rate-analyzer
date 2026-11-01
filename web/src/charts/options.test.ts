/**
 * The kit's option builders rendered to SVG in Node with ECharts' server-side renderer and
 * the light theme's tokens from tokens.css: a broken chart shows up as a failing check or a
 * changed snapshot an agent can read.
 */
import { readFileSync } from "node:fs";
import * as echarts from "echarts";
import { describe, expect, it } from "vitest";
import { flows, heatmap, network, resolveColor, timeSeries } from "./options";
import { buildTheme, chartTokens } from "./theme";

const css = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");
const light = css.slice(
  css.indexOf('[data-theme="light"] {'),
  css.indexOf("/* Semantic tokens, dark"),
);
const all = new Map(
  [...css.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1] ?? "", m[2]?.trim() ?? ""]),
);
const lightValues = new Map(
  [...light.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1] ?? "", m[2]?.trim() ?? ""]),
);
const tokens = chartTokens((name) => lightValues.get(name) ?? all.get(name) ?? "");
echarts.registerTheme("test", buildTheme(tokens));

function render(option: object, width = 640, height = 240): string {
  const chart = echarts.init(null, "test", { renderer: "svg", ssr: true, width, height });
  chart.setOption({ ...option, animation: false });
  const svg = chart.renderToSVGString();
  chart.dispose();
  return svg;
}

const HOUR = 3_600_000;
const start = Date.UTC(2026, 10, 1);
const line = (name: string, values: number[], color?: string) => ({
  name,
  color,
  points: values.map((value, index): [number, number] => [start + index * HOUR, value]),
});

describe("timeSeries", () => {
  it("draws one area with the brand's first colour", () => {
    const svg = render(timeSeries({ series: [line("claude", [1, 3, 2, 5])] }, tokens));
    expect(svg).toContain("#15a0a1");
    expect(svg).toMatchSnapshot();
  });

  it("labels up to 4 series at their ends, with a legend", () => {
    const option = timeSeries(
      { series: [line("claude", [1, 2, 3]), line("gemini", [2, 1, 2], "var(--series-2)")] },
      tokens,
    ) as { legend: { show?: boolean }; series: Array<{ endLabel?: unknown; color: string }> };
    expect(option.legend.show).not.toBe(false);
    expect(option.series[0]?.endLabel).toBeDefined();
    expect(option.series[1]?.color).toBe("#b24b0a");
    expect(render(option)).toContain("gemini");
  });

  it("keeps thresholds and bands", () => {
    const svg = render(
      timeSeries(
        {
          series: [line("claude", [1, 4, 9, 4])],
          thresholds: [{ value: 3, label: "×2 usual" }],
          bands: [{ from: start + HOUR, to: start + 2 * HOUR, label: "trending" }],
        },
        tokens,
      ),
    );
    expect(svg).toContain("×2 usual");
    expect(svg).toContain(tokens.band);
  });

  it("stacks bars", () => {
    const option = timeSeries(
      { form: "stacked", series: [line("a", [1, 2]), line("b", [2, 1])] },
      tokens,
    ) as {
      series: Array<{ type: string; stack?: string }>;
    };
    expect(option.series.every((series) => series.type === "bar" && series.stack === "total")).toBe(
      true,
    );
  });
});

describe("heatmap and network", () => {
  it("colours cells on the sequential scale", () => {
    const svg = render(
      heatmap(
        {
          x: ["Mon", "Tue"],
          y: ["0h", "1h"],
          cells: [
            [0, 0, 1],
            [1, 1, 4],
          ],
        },
        tokens,
      ),
    );
    expect(svg).toMatchSnapshot();
  });

  it("draws leaders and followers where they're placed", () => {
    const svg = render(
      network(
        {
          nodes: [
            { id: "r/localllama", x: 0, y: 0.5 },
            { id: "tech", x: 1, y: 0.5 },
          ],
          edges: [{ source: "r/localllama", target: "tech", weight: 0.8 }],
        },
        tokens,
      ),
    );
    expect(svg).toContain("r/localllama");
    expect(svg).toMatchSnapshot();
  });
});

describe("resolveColor", () => {
  it("turns series variables into the hex the canvas needs", () => {
    expect(resolveColor("var(--series-3)", tokens)).toBe("#8e65d4");
    expect(resolveColor("#123456", tokens)).toBe("#123456");
  });
});

describe("flows", () => {
  it("draws both sides and the links between them", () => {
    const svg = render(
      flows(
        {
          flows: [
            { from: "notion", to: "obsidian", mentions: 61 },
            { from: "obsidian", to: "notion", mentions: 11 },
            { from: "evernote", to: "notion", mentions: 54 },
          ],
        },
        tokens,
      ),
    );
    expect(svg).toContain("evernote");
    expect(svg).toContain(">obsidian<");
    expect((svg.match(/<path/g) ?? []).length).toBeGreaterThanOrEqual(3);
  });
});
