import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { useMemo } from "react";
import { useEventDetail } from "@/api/generated/endpoints";
import type { EventDetail } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { timeSeries } from "@/charts/options";
import { PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { ScopeLink, StatusBadge, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Replay } from "@/components/Spread";
import { useSetSearch } from "@/lib/navigation";
import { duration, formatDate, formatDateTime, percent, perThousand, times } from "@/lib/format";
import { pathPart } from "@/lib/links";
import { seriesColor } from "@/lib/colors";

export const Route = createFileRoute("/e/$kind/$start/$")({
  validateSearch: z.object({ at: z.string().optional().catch(undefined) }),
  component: EventPage,
});

/** A story (WEB-DASHBOARD.md §6.3): its cascade in order, every scope's share over its span
 * as small multiples on one scale, the forecasts made during it. */
function EventPage() {
  const { kind, start, _splat: term = "" } = Route.useParams();
  const asOf = useAsOf();
  const event = useEventDetail(kind, start, pathPart(term), asOf);
  return (
    <>
      <PageHeader
        eyebrow={`Story from ${formatDateTime(start)}`}
        title={term}
        titleClassName="term text-[22px] leading-7 font-normal"
      >
        A story: the term trended somewhere and the places it reached after, in the order they
        crossed their onset.
      </PageHeader>
      <Loaded query={event} height={300}>
        {(data) => <Story data={data} />}
      </Loaded>
    </>
  );
}

function Story({ data }: { data: EventDetail }) {
  const search = Route.useSearch();
  const set = useSetSearch();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const first = data.onsets[0] ? Date.parse(data.onsets[0].at) : Date.parse(data.start);
  const scopes = [
    ...new Set(data.onsets.filter((onset) => !onset.without).map((onset) => onset.scope)),
  ];
  const max = Math.max(...data.series.map((point) => point.per_1000 ?? 0), 0);
  const charts = useMemo(
    () =>
      scopes.slice(0, 12).map((scope, index) => ({
        scope,
        option: timeSeries(
          {
            series: [
              {
                name: scope,
                color: seriesColor(index % 3),
                points: data.series
                  .filter((point) => point.scope === scope)
                  .map((point) => [Date.parse(point.time), point.per_1000 ?? null]),
              },
            ],
            format: perThousand,
            reducedMotion,
            marks: data.onsets
              .filter((onset) => onset.scope === scope && !onset.without)
              .map((onset) => ({ at: Date.parse(onset.at), label: "onset" })),
          },
          tokens,
        ),
      })),
    [data, scopes, tokens, reducedMotion],
  );
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-ink-secondary">
        <TermLink term={data.term} kind={data.kind} /> · {data.topic || "no topic"} ·{" "}
        {data.closed ? "closed" : "still open"}
        {data.wikipedia_onset
          ? ` · Wikipedia views rose from ${formatDate(data.wikipedia_onset)}`
          : ""}
      </p>
      <Panel
        title="Replay"
        subtitle="Hour by hour: each place sized by its share of the term, ringed once it crossed its onset; the learned edges light up when both ends have"
      >
        <Replay data={data} at={search.at} onAt={(at) => set({ at })} />
      </Panel>
      <Panel title="The cascade" flush subtitle="Each place's onset, with the time since the first">
        <DataTable
          label="Onsets"
          rows={data.onsets}
          rowKey={(row) => `${row.scope}|${row.without}`}
          limit={30}
          columns={[
            {
              id: "scope",
              header: "Where",
              cell: (row) => (
                <span>
                  <ScopeLink scope={row.scope} />
                  {row.without ? (
                    <span className="text-xs text-ink-muted"> without {row.without}</span>
                  ) : null}
                </span>
              ),
            },
            { id: "at", header: "Onset", cell: (row) => formatDateTime(row.at) },
            {
              id: "after",
              header: "After the first",
              numeric: true,
              cell: (row) =>
                Date.parse(row.at) === first
                  ? "first"
                  : duration((Date.parse(row.at) - first) / 3_600_000),
            },
            { id: "ratio", header: "× usual", numeric: true, cell: (row) => times(row.ratio) },
            {
              id: "mentions",
              header: "Mentions that hour",
              numeric: true,
              wide: true,
              cell: (row) => row.mentions,
            },
          ]}
        />
      </Panel>
      <Panel
        title="Share in each place"
        subtitle={`Per 1,000 comments and posts per hour, 3 days before to 14 after; the same scale everywhere (up to ${perThousand(max)})`}
      >
        {charts.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {charts.map(({ scope, option }) => (
              <div key={scope}>
                <div className="mb-1 text-xs font-medium">
                  <ScopeLink scope={scope} />
                </div>
                <Chart
                  option={{ ...option, yAxis: { type: "value", max: max || undefined, min: 0 } }}
                  height={140}
                  label={`${scope}: share of ${data.term}`}
                  group="event"
                />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No onsets yet" />
        )}
      </Panel>
      <Panel title="Forecasts made during it" flush>
        <DataTable
          label="Forecasts of the story"
          rows={data.forecasts}
          rowKey={(row) => `${row.leader}|${row.follower}|${row.created_at}`}
          empty={<EmptyState title="No forecasts were made for it" />}
          columns={[
            { id: "path", header: "From → to", cell: (row) => `${row.leader} → ${row.follower}` },
            { id: "made", header: "Made", cell: (row) => formatDateTime(row.created_at) },
            {
              id: "chance",
              header: "Chance",
              numeric: true,
              cell: (row) => percent(row.probability),
            },
            {
              id: "outcome",
              header: "Outcome",
              cell: (row) =>
                row.outcome === "hit" ? (
                  <StatusBadge status="good">Came true</StatusBadge>
                ) : row.outcome === "miss" ? (
                  <StatusBadge status="neutral">Missed</StatusBadge>
                ) : (
                  <StatusBadge status="neutral">Waiting</StatusBadge>
                ),
            },
          ]}
        />
      </Panel>
    </div>
  );
}
