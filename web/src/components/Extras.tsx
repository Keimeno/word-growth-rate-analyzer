/** Panels beyond Grafana for the overview pages (WEB-DASHBOARD.md §7.1): ranks over time,
 * what-if gates, switching flows. */
import { useMemo, useState } from "react";
import { useTrendRanks } from "@/api/generated/endpoints";
import type { Flow, Trend } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { BarList } from "@/charts/micro";
import { bump, flows, type Series } from "@/charts/options";
import { assignSlots, colorOf } from "@/lib/colors";
import { count, decimal } from "@/lib/format";
import { TermLink } from "./Entity";
import { EmptyState, Loaded, Panel } from "./Panel";

/** A scope's top 10 over the last 7 days, an hour at a time. */
export function BumpPanel({ scope, horizon }: { scope: string; horizon: "24h" | "6h" }) {
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const query = useTrendRanks({ ...asOf, scope, horizon, top: 10 });
  const option = useMemo(() => {
    const points = query.data ?? [];
    const slots = assignSlots(points.map((point) => point.term));
    const byTerm = new Map<string, Series>();
    for (const point of points) {
      const line = byTerm.get(point.term) ?? {
        name: point.term,
        color: colorOf(slots, point.term),
        points: [],
      };
      line.points.push([Date.parse(point.time), point.rank]);
      byTerm.set(point.term, line);
    }
    return bump({ series: [...byTerm.values()].slice(0, 8), top: 10, reducedMotion }, tokens);
  }, [query.data, tokens, reducedMotion]);
  return (
    <Panel
      title="Ranks over the week"
      subtitle={`The top of ${scope} every hour for 7 days, the 8 that were there most`}
    >
      <Loaded query={query} height={260}>
        {(points) =>
          points.length ? (
            <Chart option={option} height={260} label={`Ranks of the top terms in ${scope}`} />
          ) : (
            <EmptyState title="No ranked runs in 7 days" />
          )
        }
      </Loaded>
    </Panel>
  );
}

interface Gates {
  mentions: number;
  authors: number;
  ratio: number;
  score: number;
}

const passes = (trend: Trend, gates: Gates) =>
  trend.mentions >= gates.mentions &&
  trend.authors >= gates.authors &&
  (trend.is_new || (trend.ratio ?? 0) >= gates.ratio) &&
  (trend.score ?? 0) >= gates.score;

/** Sliders over the latest run's stored trends, recomputed in the browser: what would trend
 * at other gates. Only raising them shows anything: the detector stores what passed its own. */
export function WhatIfPanel({ trends, defaults }: { trends: Trend[]; defaults: Gates }) {
  const [gates, setGates] = useState<Gates>(defaults);
  const kept = trends.filter((trend) => passes(trend, gates));
  const dropped = trends.filter((trend) => !passes(trend, gates));
  const slider = (key: keyof Gates, label: string, max: number, step: number) => (
    <label className="flex flex-col gap-1 text-xs text-ink-muted">
      <span className="flex justify-between">
        {label}{" "}
        <span className="font-medium text-ink tabular-nums">
          {decimal(gates[key], step < 1 ? 1 : 0)}
        </span>
      </span>
      <input
        type="range"
        min={step < 1 ? 1 : 1}
        max={max}
        step={step}
        value={gates[key]}
        onChange={(event) => setGates({ ...gates, [key]: Number(event.target.value) })}
        className="h-6 accent-[var(--primary)]"
      />
    </label>
  );
  return (
    <Panel
      title="What if the gates were stricter"
      subtitle="Recomputed over the latest run's stored trends; the detector only stores what passed its own gates, so loosening them shows nothing new"
    >
      <div className="grid gap-4 sm:grid-cols-4">
        {slider("mentions", "Mentions at least", 200, 1)}
        {slider("authors", "People at least", 100, 1)}
        {slider("ratio", "Times usual at least", 20, 0.5)}
        {slider("score", "Strength (z) at least", 30, 0.5)}
      </div>
      <p className="mt-3 text-sm text-ink-secondary">
        <span className="font-medium text-ink">{count(kept.length)}</span> of {count(trends.length)}{" "}
        would still trend.{" "}
        {dropped.length > 0 && (
          <>
            Out:{" "}
            {dropped.slice(0, 12).map((trend, index) => (
              <span key={`${trend.kind}|${trend.term}|${trend.scope}`}>
                {index > 0 && ", "}
                <TermLink term={trend.term} kind={trend.kind} />
              </span>
            ))}
            {dropped.length > 12 ? ` and ${dropped.length - 12} more` : ""}.
          </>
        )}
      </p>
      <button
        type="button"
        className="mt-2 text-xs text-primary hover:underline"
        onClick={() => setGates(defaults)}
      >
        Back to the configured gates
      </button>
    </Panel>
  );
}

/** Who switches from what to what, as a Sankey, and each product's net. */
export function FlowsPanel({ rows }: { rows: Flow[] }) {
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const top = rows.slice(0, 20);
  const option = useMemo(
    () =>
      flows(
        {
          flows: top.map((flow) => ({ from: flow.from, to: flow.to, mentions: flow.mentions })),
          reducedMotion,
        },
        tokens,
      ),
    [top, tokens, reducedMotion],
  );
  const net = useMemo(() => {
    const totals = new Map<string, number>();
    for (const flow of rows) {
      totals.set(flow.to, (totals.get(flow.to) ?? 0) + flow.mentions);
      totals.set(flow.from, (totals.get(flow.from) ?? 0) - flow.mentions);
    }
    return [...totals].sort((a, b) => b[1] - a[1]);
  }, [rows]);
  if (!rows.length) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <Panel title="Flows" subtitle="From the left to the right, by mentions; the 20 biggest">
        <Chart
          option={option}
          height={Math.max(220, 22 * new Set(top.map((flow) => flow.from)).size + 60)}
          label="Switching flows between products"
        />
      </Panel>
      <Panel title="Net" subtitle="Switches to it minus away from it">
        <BarList
          rows={net.slice(0, 12).map(([product, value]) => ({
            key: product,
            label: product,
            value: Math.abs(value),
            note: value >= 0 ? "gaining" : "losing",
          }))}
          format={(value) => count(value)}
        />
      </Panel>
    </div>
  );
}
