import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useEdgeDetail } from "@/api/generated/endpoints";
import type { EdgeDetail } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { strip } from "@/charts/options";
import { PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { EventLink, ScopeLink, StatusBadge, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { KpiRow, StatTile } from "@/components/Stat";
import { decimal, duration, formatDateTime, percent } from "@/lib/format";
import { edgeDefaults, edgeSearch } from "@/lib/search";

export const Route = createFileRoute("/edge")({
  validateSearch: edgeSearch,
  search: { middlewares: [stripSearchParams(edgeDefaults)] },
  component: EdgePage,
});

/** A leader → follower pair (WEB-DASHBOARD.md §6.3), its numbers in words. */
function EdgePage() {
  const search = Route.useSearch();
  const asOf = useAsOf();
  const query = useEdgeDetail({
    ...asOf,
    leader: search.leader,
    follower: search.follower,
    topic: search.topic,
    without_leader: search.without_leader,
  });
  const follower = `${search.follower}${search.without_leader ? " (rest)" : ""}`;
  return (
    <>
      <PageHeader title={`${search.leader} → ${follower}`}>
        How often {follower} picks up what {search.leader} starts talking about, and how long it
        takes.
      </PageHeader>
      <Loaded query={query} height={300}>
        {(data) => <Pair data={data} leader={search.leader} follower={follower} />}
      </Loaded>
    </>
  );
}

function Pair({ data, leader, follower }: { data: EdgeDetail; leader: string; follower: string }) {
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const edge = data.edge;
  const lags = useMemo(
    () => strip({ values: data.lags, format: duration, label: "lag", reducedMotion }, tokens),
    [data.lags, tokens, reducedMotion],
  );
  return (
    <div className="flex flex-col gap-4">
      {edge ? (
        <p className="max-w-3xl text-sm text-ink-secondary">
          <ScopeLink scope={follower.replace(" (rest)", "")}>{follower}</ScopeLink> picks up{" "}
          {percent(edge.probability)} of <ScopeLink scope={leader} />
          's terms ({percent(edge.probability_low)}–{percent(edge.probability_high)}), ×
          {decimal(edge.lift)} its usual rate of {percent(edge.base_rate)}, after a median{" "}
          {duration(edge.lag_median)} (half within {duration(edge.lag_q25)}–{duration(edge.lag_q75)}
          ). Learned from {edge.events} events, {edge.hits} of them hits; the leader was first in{" "}
          {percent(edge.lead_share)} of the events both picked up.
        </p>
      ) : (
        <EmptyState title="Not a learned pair (as of this day)">
          The pair didn't pass the tests in the latest learned edges, or doesn't exist. Its events
          and forecasts are below, if any.
        </EmptyState>
      )}
      {edge && (
        <KpiRow>
          <StatTile
            label="Chance"
            value={percent(edge.probability)}
            hint={`usually ${percent(edge.base_rate)}`}
          />
          <StatTile label="Lift" value={`×${decimal(edge.lift)}`} />
          <StatTile label="Median lead" value={duration(edge.lag_median)} />
          <StatTile label="Hits" value={`${edge.hits} of ${edge.events}`} />
        </KpiRow>
      )}
      {data.lags.length > 0 && (
        <Panel
          title="Lags"
          subtitle="Hours from the leader's onset to the follower's, every hit, with the median"
        >
          <Chart option={lags} height={120} label="Lags of the pair" />
        </Panel>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Events it was learned from"
          flush
          subtitle="The leader's onsets of the last 180 days, and whether the follower followed"
        >
          <DataTable
            label="Training events"
            rows={data.training}
            rowKey={(row) => `${row.kind}|${row.term}|${row.start}`}
            limit={15}
            empty={<EmptyState title="No events with this leader yet" />}
            columns={[
              {
                id: "term",
                header: "Term",
                cell: (row) => <TermLink term={row.term} kind={row.kind} />,
              },
              {
                id: "start",
                header: "Story",
                cell: (row) => (
                  <EventLink kind={row.kind} term={row.term} start={row.start}>
                    {formatDateTime(row.leader_at)}
                  </EventLink>
                ),
              },
              {
                id: "lag",
                header: "Followed after",
                numeric: true,
                sort: (row) => row.lag_hours,
                cell: (row) => (row.lag_hours === null ? "–" : duration(row.lag_hours)),
              },
            ]}
          />
        </Panel>
        <Panel title="Its forecasts" flush>
          <DataTable
            label="Forecasts of the pair"
            rows={data.forecasts}
            rowKey={(row) => `${row.kind}|${row.term}|${row.created_at}`}
            limit={15}
            empty={<EmptyState title="No forecasts on this pair yet" />}
            columns={[
              {
                id: "term",
                header: "Term",
                cell: (row) => <TermLink term={row.term} kind={row.kind} />,
              },
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
              {
                id: "lag",
                header: "Lag",
                numeric: true,
                wide: true,
                cell: (row) => (row.lag_hours === null ? "–" : duration(row.lag_hours)),
              },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
