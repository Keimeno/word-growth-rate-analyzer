import { createFileRoute, Link, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useEdges, useEvents, useForecastRecord, useForecasts } from "@/api/generated/endpoints";
import type { Edge } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { Meter } from "@/charts/micro";
import { network, timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { EventLink, StatusBadge, StrengthWord, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Field, MultiPicker, Segmented } from "@/components/Pickers";
import { KpiRow, StatTile } from "@/components/Stat";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { seriesColor } from "@/lib/colors";
import {
  ago,
  confidence,
  count,
  decimal,
  duration,
  formatDateTime,
  formatShortDate,
  formatTime,
  inFuture,
  percent,
} from "@/lib/format";
import { searchOf, useSetSearch } from "@/lib/navigation";
import { spreadDefaults, spreadSearch } from "@/lib/search";

export const Route = createFileRoute("/spread")({
  validateSearch: spreadSearch,
  search: { middlewares: [stripSearchParams(spreadDefaults)] },
  component: SpreadPage,
});

const follower = (row: { follower: string; without_leader: boolean }) =>
  row.without_leader ? `${row.follower} (rest)` : row.follower;

const NO_EDGES = (
  <EmptyState title="No leader → follower pairs yet">
    They're learned from terms that trended in several places: an event takes 17 days to be over,
    and a pair needs at least 5 of them. Expect the first ones after 4–6 weeks of collection.
  </EmptyState>
);

function SpreadPage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const edges = useEdges({ ...asOf, topic: search.topic, leaders: search.leaders });
  const forecasts = useForecasts(asOf);
  const events = useEvents(asOf);
  const record = useForecastRecord({ ...asOf, range: search.range });
  const data = edges.data;

  const graph = useMemo(() => {
    const list = data?.edges ?? [];
    if (!list.length) return undefined;
    const leaders = [...new Set(list.map((edge) => edge.leader))].sort();
    const followers = [...new Set(list.map(follower))].sort();
    const place = (names: string[], x: number) =>
      names.map((name, index) => ({
        id: `${x}:${name}`,
        label: name,
        x,
        y: names.length === 1 ? 0.5 : index / (names.length - 1),
      }));
    const maxLift = Math.max(...list.map((edge) => edge.lift ?? 1), 1);
    return network(
      {
        reducedMotion,
        nodes: [...place(leaders, 0), ...place(followers, 1)],
        edges: list.map((edge: Edge) => ({
          source: `0:${edge.leader}`,
          target: `1:${follower(edge)}`,
          weight: Math.min(1, (edge.lift ?? 1) / maxLift),
          tooltip: `${edge.leader} → ${follower(edge)}<br>chance ${percent(edge.probability)}, usually ${percent(edge.base_rate)}<br>lead ${duration(edge.lag_median)}, ${edge.hits} of ${edge.events} events`,
        })),
      },
      tokens,
    );
  }, [data, tokens, reducedMotion]);

  const daily = useMemo(
    () =>
      record.data &&
      timeSeries(
        {
          form: "stacked",
          daily: true,
          reducedMotion,
          series: (
            [
              ["came_true", "Came true"],
              ["missed", "Missed"],
              ["pending", "Waiting"],
            ] as const
          ).map(([key, name], index) => ({
            name,
            color: seriesColor(index),
            points: record.data.daily.map(
              (row) => [Date.parse(row.time), row[key]] as [number, number],
            ),
          })),
        },
        tokens,
      ),
    [record.data, tokens, reducedMotion],
  );

  return (
    <>
      <PageHeader title="Early warning">
        Some communities pick up terms days before others. Learned from what trended, these pairs
        turn today's bursts into forecasts of where they'll show up next.
      </PageHeader>
      <div className="flex flex-col gap-4">
        <Filters>
          <Field label="Topic">
            <Select value={search.topic} onValueChange={(topic) => set({ topic })}>
              <SelectTrigger size="sm" className="h-8 min-w-36" aria-label="Topic">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(data?.topics ?? ["all"]).map((topic) => (
                  <SelectItem key={topic} value={topic}>
                    {topic === "all" ? "All topics" : topic}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <MultiPicker
            label="Leaders"
            allLabel="Every leader"
            options={(data?.leaders ?? []).map((leader) => [leader, leader] as const)}
            value={search.leaders}
            onChange={(leaders) => set({ leaders })}
          />
        </Filters>

        <KpiRow>
          <StatTile
            label="Pairs learned"
            value={data ? ago(data.edges_learned) : "…"}
            hint={
              data?.edges_learned
                ? formatDateTime(data.edges_learned)
                : "once a day after 01:00 UTC"
            }
          />
          <StatTile
            label="Leader → follower pairs"
            value={data ? count(data.edge_count) : "…"}
            hint={search.topic === "all" ? "every topic" : search.topic}
            help="Pairs that pass the tests: at least 5 events and 3 hits, more hits than the follower's usual rate explains, and the leader first in at least 70% of the events where both picked the term up."
          />
          <StatTile
            label="Events"
            value={data ? count(data.events) : "…"}
            hint={data ? `${count(data.closed_events)} closed` : undefined}
            help="Terms that trended somewhere, what the pairs are learned from. An event is closed when its span (3 days before its first trend to 14 days after) is over."
          />
          <StatTile label="Forecasts waiting" value={data ? count(data.pending) : "…"} />
          <StatTile
            label="Came true, 30 days"
            value={
              data?.precision_30d == null
                ? "–"
                : data.resolved_30d < 10
                  ? `${Math.round(data.precision_30d * data.resolved_30d)} of ${data.resolved_30d}`
                  : percent(data.precision_30d)
            }
            hint={data ? `of ${count(data.resolved_30d)} resolved` : undefined}
            help="Of the forecasts resolved in the last 30 days, how many came true."
          />
          <StatTile
            label="Forecast alerts"
            value={data ? count(data.forecast_alerts) : "…"}
            unit="in 24 hours"
            help="Forecast alerts are off by default (forecast.alert in config.yaml). They share the daily cap with trend alerts."
          />
        </KpiRow>

        <Panel
          title="What's expected to spread"
          flush
          subtitle="A term rising in a leader that a follower hasn't picked up yet."
          help="Chance: that the follower picks it up within 7 days of the leader's onset, with its 80% interval. Usually: how often the follower picks up any trending term. Expected: the leader's onset plus the pair's median lead."
        >
          <Loaded query={forecasts}>
            {(rows) => (
              <DataTable
                label="Pending forecasts"
                rows={rows}
                rowKey={(row) => `${row.term}|${row.leader}|${row.follower}|${row.created_at}`}
                limit={15}
                empty={
                  <EmptyState title="No forecasts waiting">
                    Forecasts are made when a term trends in a leader of a learned pair.
                  </EmptyState>
                }
                columns={[
                  {
                    id: "term",
                    header: "Term",
                    cell: (row) => <TermLink term={row.term} kind={row.kind} />,
                  },
                  {
                    id: "path",
                    header: "From → to",
                    cell: (row) => (
                      <span className="whitespace-nowrap">
                        {row.leader} → <span className="font-medium">{follower(row)}</span>
                      </span>
                    ),
                  },
                  {
                    id: "chance",
                    header: "Chance",
                    numeric: true,
                    sort: (row) => row.probability,
                    cell: (row) => (
                      <div>
                        <Meter value={row.probability} max={1}>
                          {percent(row.probability)}
                        </Meter>
                        <div className="text-xs text-ink-muted">
                          {percent(row.probability_low)}–{percent(row.probability_high)}
                        </div>
                      </div>
                    ),
                  },
                  {
                    id: "base",
                    header: "Usually",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.base_rate,
                    cell: (row) => percent(row.base_rate),
                  },
                  {
                    id: "expected",
                    header: "Expected",
                    sort: (row) => row.expected_at,
                    cell: (row) => (
                      <div title={formatDateTime(row.expected_at)}>
                        {inFuture(row.expected_at)}
                        <div className="text-xs text-ink-muted">
                          by {formatShortDate(row.due_by)}
                        </div>
                      </div>
                    ),
                  },
                  {
                    id: "lift",
                    header: "Lift",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.lift,
                    help: "The chance divided by the usual rate.",
                    cell: (row) => `×${decimal(row.lift)}`,
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Who leads whom"
            subtitle="Leaders left, followers right. Thicker: the likelier the follower picks the leader's terms up."
          >
            <Loaded query={edges} height={300}>
              {() =>
                graph ? (
                  <Chart
                    option={graph}
                    height={Math.max(260, 28 * (data?.edges.length ?? 0))}
                    label="Leaders and their followers"
                  />
                ) : (
                  NO_EDGES
                )
              }
            </Loaded>
          </Panel>
          <Panel
            title="Recent cascades"
            flush
            subtitle="Terms of the last 14 days that reached more than one place, in the order they got there."
          >
            <Loaded query={events}>
              {(rows) => (
                <DataTable
                  label="Recent cascades"
                  rows={rows}
                  rowKey={(row) => `${row.kind}|${row.term}|${row.start}`}
                  limit={8}
                  empty={<EmptyState title="No cascades in 14 days" />}
                  columns={[
                    {
                      id: "term",
                      header: "Term",
                      cell: (row) => (
                        <div>
                          <EventLink kind={row.kind} term={row.term} start={row.start}>
                            <span className="term font-medium">{row.term}</span>
                          </EventLink>
                          <div className="text-xs text-ink-muted">
                            {row.topic || "no topic"}
                            {row.closed ? " · closed" : ""}
                          </div>
                        </div>
                      ),
                    },
                    {
                      id: "path",
                      header: "Path",
                      cell: (row) => (
                        <div className="flex flex-wrap items-center gap-1 text-xs">
                          {row.cascade.slice(0, 6).map((onset, index) => (
                            <span key={onset.scope} className="flex items-center gap-1">
                              {index > 0 && <span className="text-ink-muted">→</span>}
                              <span className="rounded-xs bg-surface-sunken px-1 py-0.5">
                                {onset.scope}
                                <span className="ml-1 text-ink-muted">
                                  {formatShortDate(onset.at)} {formatTime(onset.at)}
                                </span>
                              </span>
                            </span>
                          ))}
                          {row.cascade.length > 6 && (
                            <span className="text-ink-muted">+{row.cascade.length - 6}</span>
                          )}
                        </div>
                      ),
                    },
                  ]}
                />
              )}
            </Loaded>
          </Panel>
        </div>

        <Panel
          title="Leader → follower pairs"
          flush
          help="Learned daily from the events of the last 180 days. Lead: median time from the leader's onset to the follower's, with the middle half. Chance: hits shrunk towards the usual rate, with its 80% interval. Leader first: of the events where both picked it up within 7 days of each other, how often the leader was first. (rest): a group of the leader's, without the leader's own mentions."
        >
          <Loaded query={edges}>
            {(loaded) => (
              <DataTable
                label="Leader → follower pairs"
                rows={loaded.edges}
                rowKey={(row) => `${row.leader}|${follower(row)}`}
                limit={20}
                initialSort={{ id: "lift", desc: true }}
                empty={NO_EDGES}
                columns={[
                  {
                    id: "leader",
                    header: "Leader",
                    sort: (row) => row.leader,
                    cell: (row) => (
                      <Link
                        to="/edge"
                        search={searchOf({
                          leader: row.leader,
                          follower: row.follower,
                          topic: search.topic,
                          without_leader: row.without_leader,
                        })}
                        className="font-medium hover:text-primary hover:underline"
                      >
                        {row.leader}
                      </Link>
                    ),
                  },
                  {
                    id: "follower",
                    header: "Follower",
                    sort: (row) => follower(row),
                    cell: (row) => (
                      <span>
                        {follower(row)}{" "}
                        <span className="text-xs text-ink-muted">{row.follower_type}</span>
                      </span>
                    ),
                  },
                  {
                    id: "lead",
                    header: "Lead",
                    numeric: true,
                    sort: (row) => row.lag_median,
                    cell: (row) => (
                      <div>
                        {duration(row.lag_median)}
                        <div className="text-xs text-ink-muted">
                          {duration(row.lag_q25)}–{duration(row.lag_q75)}
                        </div>
                      </div>
                    ),
                  },
                  {
                    id: "chance",
                    header: "Chance",
                    numeric: true,
                    sort: (row) => row.probability,
                    cell: (row) => (
                      <div>
                        {percent(row.probability)}
                        <div className="text-xs text-ink-muted">
                          {percent(row.probability_low)}–{percent(row.probability_high)}
                        </div>
                      </div>
                    ),
                  },
                  {
                    id: "base",
                    header: "Usually",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.base_rate,
                    cell: (row) => percent(row.base_rate),
                  },
                  {
                    id: "lift",
                    header: "Lift",
                    numeric: true,
                    sort: (row) => row.lift,
                    cell: (row) => <span className="font-medium">×{decimal(row.lift)}</span>,
                  },
                  {
                    id: "hits",
                    header: "Hits",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.hits,
                    cell: (row) => `${row.hits} of ${row.events}`,
                  },
                  {
                    id: "first",
                    header: "Leader first",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.lead_share,
                    cell: (row) => percent(row.lead_share),
                  },
                  {
                    id: "confidence",
                    header: "Confidence",
                    sort: (row) => -(row.q ?? 1),
                    cell: (row) => (
                      <StrengthWord
                        value={confidence(row.q)}
                        title={`q ${row.q?.toExponential(1) ?? "–"}`}
                      />
                    ),
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Track record, last 30 days"
            flush
            subtitle="Came true when the follower picked the term up in time, missed otherwise."
          >
            <Loaded query={record}>
              {(loaded) => (
                <DataTable
                  label="Resolved forecasts"
                  rows={loaded.resolved}
                  rowKey={(row) => `${row.term}|${row.leader}|${row.follower}|${row.created_at}`}
                  limit={10}
                  empty={<EmptyState title="No resolved forecasts yet" />}
                  columns={[
                    {
                      id: "made",
                      header: "Made",
                      sort: (row) => row.created_at,
                      cell: (row) => (
                        <span title={formatDateTime(row.created_at)}>{ago(row.created_at)}</span>
                      ),
                    },
                    {
                      id: "term",
                      header: "Term",
                      cell: (row) => (
                        <div>
                          <TermLink term={row.term} kind={row.kind} />
                          <div className="text-xs text-ink-muted">
                            {row.leader} → {follower(row)}
                          </div>
                        </div>
                      ),
                    },
                    {
                      id: "chance",
                      header: "Chance",
                      numeric: true,
                      sort: (row) => row.probability,
                      cell: (row) => percent(row.probability),
                    },
                    {
                      id: "outcome",
                      header: "Outcome",
                      sort: (row) => row.outcome,
                      cell: (row) =>
                        row.outcome === "hit" ? (
                          <StatusBadge status="good">Came true</StatusBadge>
                        ) : (
                          <StatusBadge status="neutral">Missed</StatusBadge>
                        ),
                    },
                    {
                      id: "warning",
                      header: "Warning",
                      numeric: true,
                      wide: true,
                      sort: (row) => row.warning_hours,
                      help: "Time from the forecast to the follower picking it up.",
                      cell: (row) => (row.outcome === "hit" ? duration(row.warning_hours) : "–"),
                    },
                  ]}
                />
              )}
            </Loaded>
          </Panel>
          <Panel
            title="Calibration, last 90 days"
            flush
            help="Well calibrated forecasts come true about as often as they say. Usually: what always forecasting the follower's usual rate would say."
          >
            <Loaded query={record}>
              {(loaded) => (
                <DataTable
                  label="Calibration"
                  rows={loaded.calibration}
                  rowKey={(row) => String(row.bin)}
                  limit={5}
                  empty={<EmptyState title="Nothing resolved in 90 days" />}
                  columns={[
                    {
                      id: "bin",
                      header: "Forecast said",
                      cell: (row) => `${row.bin * 20}–${row.bin * 20 + 20}%`,
                    },
                    {
                      id: "n",
                      header: "Forecasts",
                      numeric: true,
                      cell: (row) => count(row.forecasts),
                    },
                    {
                      id: "predicted",
                      header: "On average",
                      numeric: true,
                      cell: (row) => percent(row.predicted),
                    },
                    {
                      id: "came",
                      header: "Came true",
                      numeric: true,
                      cell: (row) =>
                        row.forecasts < 10 ? (
                          `${Math.round((row.came_true ?? 0) * row.forecasts)} of ${row.forecasts}`
                        ) : (
                          <Meter value={row.came_true} max={1}>
                            {percent(row.came_true)}
                          </Meter>
                        ),
                    },
                    {
                      id: "base",
                      header: "Usually",
                      numeric: true,
                      cell: (row) => percent(row.base_rate),
                    },
                  ]}
                />
              )}
            </Loaded>
          </Panel>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Forecasts per day"
            actions={
              <Segmented
                label="Range"
                value={search.range}
                onChange={(range) => set({ range })}
                options={[
                  ["14d", "14 days"],
                  ["30d", "30 days"],
                  ["90d", "90 days"],
                ]}
              />
            }
          >
            <Loaded query={record} height={220}>
              {(loaded) =>
                loaded.daily.length && daily ? (
                  <Chart option={daily} height={220} label="Forecasts per day by outcome" />
                ) : (
                  <EmptyState title="No forecasts in this range" />
                )
              }
            </Loaded>
          </Panel>
          <Panel
            title="Onsets against Wikipedia"
            subtitle="Optional (wikipedia.enabled): for events whose term names a Wikipedia article, did its pageviews rise after the term's first onset? Last 90 days."
          >
            <Loaded query={record}>
              {(loaded) =>
                loaded.wikipedia.events ? (
                  <KpiRow className="lg:grid-cols-3">
                    <StatTile
                      label="Events with an article"
                      value={count(loaded.wikipedia.events)}
                      hint={`${count(loaded.wikipedia.with_interest)} with rising views`}
                    />
                    <StatTile
                      label="Onset first"
                      value={count(loaded.wikipedia.onset_first)}
                      hint={`${count(loaded.wikipedia.same_day)} same day, ${count(loaded.wikipedia.wikipedia_first)} Wikipedia first`}
                    />
                    <StatTile
                      label="Median lead"
                      value={decimal(loaded.wikipedia.median_lead_days)}
                      unit="days"
                    />
                  </KpiRow>
                ) : (
                  <EmptyState title="Not enabled, or nothing to compare yet">
                    Turn it on with wikipedia.enabled in config.yaml.
                  </EmptyState>
                )
              }
            </Loaded>
          </Panel>
        </div>
      </div>
    </>
  );
}
