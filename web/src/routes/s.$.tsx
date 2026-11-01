import { createFileRoute, Link, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useIntents, useLongTerm, useScopeDetail, useTrends } from "@/api/generated/endpoints";
import type { ScopeEdge } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { timeSeries } from "@/charts/options";
import { PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { ScopeLink, StrengthWord, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { KpiRow, StatTile } from "@/components/Stat";
import { seriesColor } from "@/lib/colors";
import { count, decimal, duration, percent, strength, times } from "@/lib/format";
import { pathPart } from "@/lib/links";
import { searchOf } from "@/lib/navigation";
import { scopePageDefaults, scopePageSearch } from "@/lib/search";

export const Route = createFileRoute("/s/$")({
  validateSearch: scopePageSearch,
  search: { middlewares: [stripSearchParams(scopePageDefaults)] },
  component: ScopePage,
});

const INTENTS: Record<string, string> = {
  switch: "Switches",
  considering: "Considering",
  alternative: "Alternatives sought",
  complaint: "Complaints",
  need: "Needs",
};

/** A scope's page (WEB-DASHBOARD.md §6.3): volume, members, what trends there now and long
 * term, the edges where it leads or follows, its intents. */
function ScopePage() {
  const { _splat: name = "" } = Route.useParams();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const detail = useScopeDetail(pathPart(name), asOf);
  const trends = useTrends({ ...asOf, scope: name });
  const longTerm = useLongTerm({ ...asOf, scope: name });
  const intents = useIntents({ ...asOf, scope: name, range: "30d" });
  const data = detail.data;
  const volume = useMemo(
    () =>
      data &&
      timeSeries(
        {
          daily: true,
          reducedMotion,
          form: "line",
          series: [
            {
              name: "Comments and posts",
              color: seriesColor(0),
              points: data.volume.map((row) => [Date.parse(row.time), row.documents]),
            },
            {
              name: "People",
              color: seriesColor(1),
              points: data.volume.map((row) => [Date.parse(row.time), row.authors]),
            },
          ],
        },
        tokens,
      ),
    [data, tokens, reducedMotion],
  );
  const edgeColumns = (side: "leader" | "follower") => [
    {
      id: side,
      header: side === "leader" ? "Leader" : "Follower",
      cell: (row: ScopeEdge) => <ScopeLink scope={row[side]} />,
    },
    {
      id: "other",
      header: side === "leader" ? "Follower" : "Leader",
      cell: (row: ScopeEdge) => (
        <Link
          to="/edge"
          search={searchOf({
            leader: row.leader,
            follower: row.follower,
            without_leader: row.without_leader,
          })}
          className="hover:text-primary hover:underline"
        >
          {side === "leader" ? `${row.follower}${row.without_leader ? " (rest)" : ""}` : row.leader}
        </Link>
      ),
    },
    {
      id: "lift",
      header: "Lift",
      numeric: true,
      sort: (row: ScopeEdge) => row.lift,
      cell: (row: ScopeEdge) => `×${decimal(row.lift)}`,
    },
    {
      id: "chance",
      header: "Chance",
      numeric: true,
      cell: (row: ScopeEdge) => percent(row.probability),
    },
    {
      id: "lead",
      header: "Lead",
      numeric: true,
      cell: (row: ScopeEdge) => duration(row.lag_median),
    },
    {
      id: "hits",
      header: "Hits",
      numeric: true,
      wide: true,
      cell: (row: ScopeEdge) => `${row.hits} of ${row.events}`,
    },
  ];

  return (
    <>
      <PageHeader title={name}>
        {data
          ? `A ${data.type}${data.platform ? ` on ${data.platform}` : ""}${data.members.length > 1 ? ` of ${data.members.length} channels` : ""}${data.groups.length ? `, in ${data.groups.join(", ")}` : ""}.`
          : "Loading…"}
      </PageHeader>
      <Loaded query={detail} height={300}>
        {(scope) => (
          <div className="flex flex-col gap-4">
            <KpiRow>
              <StatTile
                label="Comments and posts, 7 days"
                value={count(scope.members.reduce((sum, member) => sum + member.documents, 0))}
              />
              <StatTile
                label="Trending now"
                value={trends.data ? count(trends.data.trending) : "…"}
                unit="terms"
                hint="24-hour window"
              />
              <StatTile
                label="Long-term trends"
                value={longTerm.data ? count(longTerm.data.trends.length) : "…"}
                hint="13 weeks"
              />
              <StatTile
                label="Edges"
                value={count(scope.leads.length + scope.follows.length)}
                hint={`${scope.leads.length} leading, ${scope.follows.length} following`}
              />
            </KpiRow>
            <Panel title="Volume" subtitle="Comments and posts, and different people, per day">
              {scope.volume.length && volume ? (
                <Chart option={volume} height={220} label={`${name}: volume per day`} />
              ) : (
                <EmptyState title="No volume yet" />
              )}
            </Panel>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Trending now" flush subtitle="The strongest of the latest run">
                <Loaded query={trends}>
                  {(loaded) => (
                    <DataTable
                      label="Trending now"
                      rows={loaded.trends.slice(0, 50)}
                      rowKey={(row) => `${row.kind}|${row.term}|${row.scope}`}
                      limit={10}
                      empty={<EmptyState title="Nothing trending here right now" />}
                      columns={[
                        {
                          id: "term",
                          header: "Term",
                          cell: (row) => <TermLink term={row.term} kind={row.kind} scope={name} />,
                        },
                        {
                          id: "ratio",
                          header: "× usual",
                          numeric: true,
                          cell: (row) => times(row.ratio, row.is_new),
                        },
                        {
                          id: "strength",
                          header: "Strength",
                          cell: (row) => <StrengthWord value={strength(row.score)} />,
                        },
                      ]}
                    />
                  )}
                </Loaded>
              </Panel>
              <Panel
                title={scope.members.length > 1 ? "Members" : "Channel"}
                flush
                subtitle="Their share of the volume, last 7 days"
              >
                <DataTable
                  label="Members"
                  rows={scope.members}
                  rowKey={(row) => row.channel}
                  limit={15}
                  columns={[
                    {
                      id: "channel",
                      header: "Channel",
                      cell: (row) => <ScopeLink scope={row.channel} />,
                    },
                    {
                      id: "documents",
                      header: "Collected",
                      numeric: true,
                      sort: (row) => row.documents,
                      cell: (row) => count(row.documents),
                    },
                    {
                      id: "authors",
                      header: "People",
                      numeric: true,
                      sort: (row) => row.authors,
                      cell: (row) => count(row.authors),
                    },
                    {
                      id: "share",
                      header: "Share",
                      numeric: true,
                      sort: (row) => row.share,
                      cell: (row) => percent(row.share),
                    },
                  ]}
                />
              </Panel>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Where it leads" flush>
                <DataTable
                  label="Edges it leads"
                  rows={scope.leads}
                  rowKey={(row) => `${row.leader}|${row.follower}|${row.without_leader}`}
                  limit={10}
                  empty={<EmptyState title="No edges where it leads yet" />}
                  columns={edgeColumns("leader")}
                />
              </Panel>
              <Panel title="Where it follows" flush>
                <DataTable
                  label="Edges it follows"
                  rows={scope.follows}
                  rowKey={(row) => `${row.leader}|${row.follower}|${row.without_leader}`}
                  limit={10}
                  empty={<EmptyState title="No edges where it follows yet" />}
                  columns={edgeColumns("follower")}
                />
              </Panel>
            </div>
            <Panel title="Why people mention things here" subtitle="Intents of the last 30 days">
              <Loaded query={intents}>
                {(loaded) => (
                  <KpiRow>
                    {Object.entries(INTENTS).map(([kind, label]) => (
                      <StatTile key={kind} label={label} value={count(loaded.counts[kind] ?? 0)} />
                    ))}
                  </KpiRow>
                )}
              </Loaded>
            </Panel>
          </div>
        )}
      </Loaded>
    </>
  );
}
