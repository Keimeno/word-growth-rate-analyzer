/** The spread map, calibration and arrivals of the Early warning page, and the replay of a
 * story (WEB-DASHBOARD.md §7.1, items 6, 7, 13, 14). */
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useEdges, useSpreadMap } from "@/api/generated/endpoints";
import type { CalibrationBin, Edge, EventDetail, Forecast, MapNode } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { calibration, heatmap, network, wilson } from "@/charts/options";
import { now } from "@/lib/clock";
import {
  decimal,
  duration,
  formatDateTime,
  formatShortDate,
  percent,
  perThousand,
} from "@/lib/format";
import { Button } from "./ui/button";
import { EmptyState, Loaded, Panel } from "./Panel";

const follower = (edge: { follower: string; without_leader: boolean }) =>
  edge.without_leader ? `${edge.follower} (rest)` : edge.follower;

/** x from the usual lag behind the first mover (log scale), y spread within each column. */
function place(scopes: string[], map: MapNode[]): Map<string, { x: number; y: number }> {
  const lag = new Map(map.map((node) => [node.scope, node.median_lag ?? 0]));
  const max = Math.log1p(Math.max(...scopes.map((scope) => lag.get(scope) ?? 0), 1));
  const columns = new Map<number, string[]>();
  for (const scope of [...scopes].sort(
    (a, b) => (lag.get(a) ?? 0) - (lag.get(b) ?? 0) || a.localeCompare(b),
  )) {
    const column = Math.round((Math.log1p(lag.get(scope) ?? max / 2) / max) * 6);
    columns.set(column, [...(columns.get(column) ?? []), scope]);
  }
  const positions = new Map<string, { x: number; y: number }>();
  for (const [column, members] of columns) {
    members.forEach((scope, index) =>
      positions.set(scope, { x: column / 6, y: (index + 1) / (members.length + 1) }),
    );
  }
  return positions;
}

export function SpreadMap({ edges }: { edges: Edge[] }) {
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const map = useSpreadMap(asOf);
  const option = useMemo(() => {
    if (!edges.length) return undefined;
    const scopes = [...new Set(edges.flatMap((edge) => [edge.leader, follower(edge)]))];
    const positions = place(scopes, map.data ?? []);
    const maxLift = Math.max(...edges.map((edge) => edge.lift ?? 1), 1);
    const nodes = new Map((map.data ?? []).map((node) => [node.scope, node]));
    return network(
      {
        reducedMotion,
        nodes: scopes.map((scope) => ({
          id: scope,
          ...(positions.get(scope) ?? { x: 0.5, y: 0.5 }),
          size: 8 + Math.min(16, Math.sqrt(nodes.get(scope)?.events ?? 1) * 1.5),
          label: scope,
        })),
        edges: edges.map((edge) => ({
          source: edge.leader,
          target: follower(edge),
          weight: Math.min(1, (edge.lift ?? 1) / maxLift),
          tooltip: `${edge.leader} → ${follower(edge)}: ${percent(edge.probability)} (usually ${percent(edge.base_rate)}), after ${duration(edge.lag_median)}`,
        })),
      },
      tokens,
    );
  }, [edges, map.data, tokens, reducedMotion]);
  const grid = useMemo(() => {
    if (!edges.length) return undefined;
    const leaders = [...new Set(edges.map((edge) => edge.leader))].sort();
    const followers = [...new Set(edges.map(follower))].sort();
    return heatmap(
      {
        x: followers,
        y: leaders,
        cells: edges.map((edge) => [
          followers.indexOf(follower(edge)),
          leaders.indexOf(edge.leader),
          edge.lift ?? null,
        ]),
        format: (value) => `×${decimal(value)} lift`,
        reducedMotion,
      },
      tokens,
    );
  }, [edges, tokens, reducedMotion]);
  if (!option || !grid) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel
        title="The spread map"
        subtitle="Left to right: how long after a story's first onset each place usually picks it up. Thicker: higher lift."
      >
        <Chart
          option={option}
          height={Math.max(280, 26 * edges.length)}
          label="The spread map of learned edges"
        />
      </Panel>
      <Panel
        title="Leader × follower"
        subtitle="Lift of each learned pair, for when the map gets dense"
      >
        <Chart
          option={grid}
          height={Math.max(220, 28 * new Set(edges.map((edge) => edge.leader)).size + 80)}
          label="Lift by leader and follower"
        />
      </Panel>
    </div>
  );
}

export function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const option = useMemo(
    () =>
      calibration(
        {
          reducedMotion,
          bins: bins.map((bin) => {
            const [low, high] = wilson(
              Math.round((bin.came_true ?? 0) * bin.forecasts),
              bin.forecasts,
            );
            return {
              predicted: bin.predicted ?? 0,
              cameTrue: bin.came_true ?? 0,
              low,
              high,
              forecasts: bin.forecasts,
              baseRate: bin.base_rate ?? 0,
            };
          }),
        },
        tokens,
      ),
    [bins, tokens, reducedMotion],
  );
  if (!bins.length) return null;
  return (
    <Chart option={option} height={240} label="Forecast calibration: said against came true" />
  );
}

/** Pending forecasts as a timeline per follower: the window from the leader's onset to the
 * due date, the expected time marked, the chance as the label. */
export function Arrivals({ forecasts }: { forecasts: Forecast[] }) {
  if (!forecasts.length) return <EmptyState title="No forecasts waiting" />;
  const rows = [...forecasts]
    .sort((a, b) => Date.parse(a.expected_at) - Date.parse(b.expected_at))
    .slice(0, 12);
  const start = Math.min(...rows.map((row) => Date.parse(row.leader_onset)));
  const end = Math.max(...rows.map((row) => Date.parse(row.due_by)));
  const x = (time: number) => `${(100 * (time - start)) / (end - start || 1)}%`;
  const current = now();
  return (
    <ul className="flex flex-col gap-2 px-4 pb-4 text-sm">
      {rows.map((row) => (
        <li
          key={`${row.term}|${row.leader}|${row.follower}|${row.created_at}`}
          className="grid gap-1 sm:grid-cols-[14rem_1fr] sm:items-center"
        >
          <span className="truncate">
            <span className="term font-medium">{row.term}</span>{" "}
            <span className="text-xs text-ink-muted">→ {follower(row)}</span>
          </span>
          <span
            className="relative h-5"
            role="img"
            aria-label={`${row.term} expected in ${follower(row)} ${formatDateTime(row.expected_at)}, chance ${percent(row.probability)}`}
          >
            <span
              className="absolute inset-y-2 rounded-full bg-primary-wash"
              style={{
                left: x(Date.parse(row.leader_onset)),
                right: `calc(100% - ${x(Date.parse(row.due_by))})`,
              }}
            />
            <span
              className="absolute inset-y-0.5 w-1 rounded-full bg-primary"
              style={{ left: x(Date.parse(row.expected_at)) }}
            />
            {current >= start && current <= end && (
              <span className="absolute inset-y-0 w-px bg-ink-muted" style={{ left: x(current) }} />
            )}
            <span
              className="absolute -top-0.5 text-xs text-ink-secondary tabular-nums"
              style={{ left: `calc(${x(Date.parse(row.expected_at))} + 8px)` }}
            >
              {percent(row.probability)} · {formatShortDate(row.expected_at)}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The replay of a story: every place on the map filled with its share of the term at the
 * hour, a ring when it crossed its onset, the learned edges between places that both have.
 * The hour is in the url (`at=`); with reduced motion it steps without animating. */
export function Replay({
  data,
  at,
  onAt,
}: {
  data: EventDetail;
  at: string | undefined;
  onAt: (at: string) => void;
}) {
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const map = useSpreadMap(asOf);
  const edges = useEdges({ ...asOf, topic: data.topic || "all" });
  const hours = useMemo(
    () => [...new Set(data.series.map((point) => point.time))].sort(),
    [data.series],
  );
  const index = Math.max(
    0,
    at ? hours.indexOf(at) : hours.findIndex((hour) => hour >= (data.onsets[0]?.at ?? data.start)),
  );
  const [playing, setPlaying] = useState(false);
  const hour = hours[index];
  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(
      () => {
        const next = hours[index + 1];
        if (next) onAt(next);
        else setPlaying(false);
      },
      reducedMotion ? 800 : 250,
    );
    return () => clearInterval(timer);
  }, [playing, index, hours, onAt, reducedMotion]);
  const option = useMemo(() => {
    if (!hour) return undefined;
    const scopes = [
      ...new Set(data.onsets.filter((onset) => !onset.without).map((onset) => onset.scope)),
    ];
    const positions = place(scopes, map.data ?? []);
    const max = Math.max(...data.series.map((point) => point.per_1000 ?? 0), 0) || 1;
    const share = new Map(
      data.series
        .filter((point) => point.time === hour)
        .map((point) => [point.scope, point.per_1000 ?? 0]),
    );
    const crossed = new Set(
      data.onsets.filter((onset) => !onset.without && onset.at <= hour).map((onset) => onset.scope),
    );
    const base = network(
      {
        reducedMotion: true,
        nodes: scopes.map((scope) => ({
          id: scope,
          ...(positions.get(scope) ?? { x: 0.5, y: 0.5 }),
          size: 10 + 22 * ((share.get(scope) ?? 0) / max),
          label: scope,
        })),
        edges: (edges.data?.edges ?? [])
          .filter(
            (edge) =>
              scopes.includes(edge.leader) &&
              scopes.includes(edge.follower) &&
              !edge.without_leader,
          )
          .map((edge) => ({
            source: edge.leader,
            target: edge.follower,
            weight: crossed.has(edge.leader) && crossed.has(edge.follower) ? 1 : 0.1,
            tooltip: `${edge.leader} → ${edge.follower}: usually after ${duration(edge.lag_median)}`,
          })),
      },
      tokens,
    ) as { series: Array<{ data: Array<Record<string, unknown>> }> };
    for (const node of base.series[0]?.data ?? []) {
      const scope = String(node.name);
      node.itemStyle = {
        color: crossed.has(scope) ? tokens.primary : tokens.sequential[1],
        borderColor: crossed.has(scope) ? tokens.ink : tokens.surface,
        borderWidth: crossed.has(scope) ? 2 : 1,
      };
      node.tooltip = `${scope}: ${perThousand(share.get(scope) ?? 0)} per 1,000${crossed.has(scope) ? ", crossed its onset" : ""}`;
    }
    return base;
  }, [hour, data, map.data, edges.data, tokens]);
  if (!hours.length || !hour || !option) return <EmptyState title="Nothing to replay yet" />;
  const first = Date.parse(data.onsets[0]?.at ?? data.start);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="icon-sm"
          variant="outline"
          aria-label="An hour back"
          onClick={() => hours[index - 1] && onAt(hours[index - 1] ?? hour)}
        >
          <SkipBack className="size-4" />
        </Button>
        <Button size="sm" onClick={() => setPlaying(!playing)}>
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}{" "}
          {playing ? "Pause" : "Play"}
        </Button>
        <Button
          size="icon-sm"
          variant="outline"
          aria-label="An hour on"
          onClick={() => hours[index + 1] && onAt(hours[index + 1] ?? hour)}
        >
          <SkipForward className="size-4" />
        </Button>
        <input
          type="range"
          aria-label="Hour of the story"
          min={0}
          max={hours.length - 1}
          value={index}
          onChange={(event) => onAt(hours[Number(event.target.value)] ?? hour)}
          className="h-6 min-w-40 flex-1 accent-[var(--primary)]"
        />
        <span className="text-sm tabular-nums text-ink-secondary">
          {formatDateTime(hour)} ·{" "}
          {Date.parse(hour) === first
            ? "the first onset"
            : Date.parse(hour) > first
              ? `${duration((Date.parse(hour) - first) / 3_600_000)} after the first onset`
              : "before the first onset"}
        </span>
      </div>
      <Chart option={option} height={320} label={`The story at ${formatDateTime(hour)}`} />
    </div>
  );
}

export function SpreadMapLoaded({ topic }: { topic: string }) {
  const asOf = useAsOf();
  const edges = useEdges({ ...asOf, topic });
  return <Loaded query={edges}>{(data) => <SpreadMap edges={data.edges} />}</Loaded>;
}
