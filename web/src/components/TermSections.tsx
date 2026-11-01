/** The term page's sections beyond Grafana (WEB-DASHBOARD.md §7.1): the term in every
 * channel, the terms mentioned with it, and its rhythm. */
import { useMemo } from "react";
import { useTermChannels, useTermRelated, useTermRhythm } from "@/api/generated/endpoints";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { calendar, heatmap, timeSeries } from "@/charts/options";
import { seriesColor } from "@/lib/colors";
import { count, decimal, formatDateTime, perThousand, times } from "@/lib/format";
import { pathPart } from "@/lib/links";
import { DataTable } from "./DataTable";
import { KindBadge, ScopeLink, TermLink } from "./Entity";
import { EmptyState, Loaded, Panel } from "./Panel";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** One small chart per channel on one scale, in the order they took the term up. */
export function ChannelsPanel({
  kind,
  term,
  scope,
  range,
}: {
  kind: string;
  term: string;
  scope: string;
  range: string;
}) {
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const query = useTermChannels(kind, pathPart(term), { ...asOf, scope, range });
  const charts = useMemo(() => {
    const channels = (query.data?.channels ?? []).slice(0, 12);
    const max = Math.max(
      ...channels.flatMap((series) => series.points.map((point) => point[1] ?? 0)),
      0,
    );
    return channels.map((series, index) => ({
      series,
      option: {
        ...timeSeries(
          {
            series: [
              {
                name: series.channel,
                color: seriesColor(index % 3),
                points: series.points.map(([time, share]) => [Date.parse(time), share]),
              },
            ],
            format: perThousand,
            daily: query.data?.bucket !== "hour",
            reducedMotion,
            marks: series.onset ? [{ at: Date.parse(series.onset), label: "" }] : [],
          },
          tokens,
        ),
        yAxis: {
          type: "value",
          min: 0,
          max: max || undefined,
          axisLabel: { formatter: perThousand },
        },
        grid: { left: 4, right: 8, top: 8, bottom: 4, containLabel: true },
      },
    }));
  }, [query.data, tokens, reducedMotion]);
  return (
    <Panel
      title="In each channel"
      subtitle="Share per 1,000 on one scale, in the order each channel took it up (half of its own peak, the line)"
    >
      <Loaded query={query} height={200}>
        {(data) =>
          data.channels.length ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {charts.map(({ series, option }) => (
                <div key={series.channel}>
                  <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
                    <ScopeLink scope={series.channel} />
                    <span className="text-ink-muted">
                      {count(series.mentions)} · {series.onset ? formatDateTime(series.onset) : "–"}
                    </span>
                  </div>
                  <Chart
                    option={option}
                    height={110}
                    label={`${series.channel}: share of ${term}`}
                    group="channels"
                  />
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="Not mentioned in these channels in this range" />
          )
        }
      </Loaded>
    </Panel>
  );
}

/** Terms mentioned with it in the last 48 hours, far more than without it. */
export function RelatedPanel({ kind, term, scope }: { kind: string; term: string; scope: string }) {
  const asOf = useAsOf();
  const query = useTermRelated(kind, pathPart(term), { ...asOf, scope });
  return (
    <Panel
      title="Mentioned with it"
      flush
      subtitle={
        query.data
          ? `In the ${count(query.data.documents)} comments and posts of the last 48 hours that mention it`
          : "The last 48 hours"
      }
      help="Ranked by how much more often a term appears in the comments with this one than in the rest of the scope's comments (the detector's weighted log odds). Raw text is kept for 48 hours, so this only covers them."
    >
      <Loaded query={query}>
        {(data) => (
          <DataTable
            label="Terms mentioned with it"
            rows={data.terms}
            rowKey={(row) => `${row.kind}|${row.term}`}
            limit={12}
            empty={
              <EmptyState title="Nothing stands out with it">
                Few comments mention it, or the terms with it are common everywhere.
              </EmptyState>
            }
            columns={[
              {
                id: "term",
                header: "Term",
                cell: (row) => (
                  <>
                    <TermLink term={row.term} kind={row.kind} scope={scope} />
                    <KindBadge kind={row.kind} />
                  </>
                ),
              },
              {
                id: "together",
                header: "Together",
                numeric: true,
                sort: (row) => row.together,
                cell: (row) => `${row.together} of ${data.documents}`,
              },
              {
                id: "ratio",
                header: "× elsewhere",
                numeric: true,
                sort: (row) => row.ratio,
                cell: (row) => (row.ratio === null ? "only with it" : times(row.ratio)),
              },
              {
                id: "score",
                header: "z",
                numeric: true,
                wide: true,
                sort: (row) => row.score,
                cell: (row) => decimal(row.score),
              },
            ]}
          />
        )}
      </Loaded>
    </Panel>
  );
}

/** Hour of week against its usual share, and a year of days. */
export function RhythmPanel({ kind, term, scope }: { kind: string; term: string; scope: string }) {
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const query = useTermRhythm(kind, pathPart(term), { ...asOf, scope });
  const options = useMemo(() => {
    if (!query.data) return undefined;
    const hours = heatmap(
      {
        x: Array.from({ length: 24 }, (_, hour) => `${hour}`),
        y: WEEKDAYS,
        cells: query.data.hours.map((cell) => [cell.hour, cell.weekday - 1, cell.relative ?? null]),
        format: (value) => `${decimal(value)}× its usual share`,
        reducedMotion,
      },
      tokens,
    );
    const days = calendar(
      {
        days: query.data.days.map((day) => [day.day, day.per_1000 ?? null]),
        format: (value) => `${perThousand(value)} per 1,000`,
        reducedMotion,
      },
      tokens,
    );
    return { hours, days };
  }, [query.data, tokens, reducedMotion]);
  return (
    <Panel
      title="Rhythm"
      subtitle="When it's talked about more than the scope talks at all: hour of week over 28 days (UTC), and a year of days"
    >
      <Loaded query={query} height={220}>
        {(data) =>
          data.hours.some((cell) => cell.mentions) && options ? (
            <div className="flex flex-col gap-4">
              <Chart option={options.hours} height={220} label={`${term}: share by hour of week`} />
              <Chart
                option={options.days}
                height={140}
                label={`${term}: share per day over a year`}
              />
            </div>
          ) : (
            <EmptyState title="Not mentioned in the last 28 days" />
          )
        }
      </Loaded>
    </Panel>
  );
}
