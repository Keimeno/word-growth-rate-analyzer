import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useIngestion, useIngestionSeries } from "@/api/generated/endpoints";
import type { FeedRate } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { Meter } from "@/charts/micro";
import { type Series, timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/Entity";
import { Loaded, Notice, Panel } from "@/components/Panel";
import { Field, MultiPicker, Segmented } from "@/components/Pickers";
import { KpiRow, StatTile } from "@/components/Stat";
import { seriesColor } from "@/lib/colors";
import { ago, bytes, count, decimal, formatDateTime, percent } from "@/lib/format";
import { collectionHealth, feedState } from "@/lib/health";
import { useSetSearch } from "@/lib/navigation";
import { collectionDefaults, collectionSearch } from "@/lib/search";

export const Route = createFileRoute("/collection")({
  validateSearch: collectionSearch,
  search: { middlewares: [stripSearchParams(collectionDefaults)] },
  component: CollectionPage,
});

// Reddit allows 1,000 requests per 10 minutes and client id
const RATE_LIMIT = 1000;

/** Every feed's items per minute, the biggest 7 on their own and the rest as "other". */
function feedSeries(items: FeedRate[]): Series[] {
  const totals = new Map<string, number>();
  for (const row of items)
    totals.set(row.feed, (totals.get(row.feed) ?? 0) + (row.per_minute ?? 0));
  const top = [...totals]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 7)
    .map(([feed]) => feed);
  const byFeed = new Map(top.map((feed) => [feed, new Map<number, number>()]));
  const other = new Map<number, number>();
  for (const row of items) {
    const target = byFeed.get(row.feed) ?? other;
    const time = Date.parse(row.time);
    target.set(time, (target.get(time) ?? 0) + (row.per_minute ?? 0));
  }
  const series = [...byFeed].map(([name, points], index) => ({
    name,
    color: seriesColor(index),
    points: [...points],
  }));
  if (other.size) series.push({ name: "other feeds", color: seriesColor(7), points: [...other] });
  return series;
}

function CollectionPage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const params = { ...asOf, platforms: search.platforms, range: search.range };
  const ingestion = useIngestion(params, { query: { staleTime: 30_000, refetchInterval: 60_000 } });
  const series = useIngestionSeries(params, {
    query: { staleTime: 30_000, refetchInterval: 60_000 },
  });
  const data = ingestion.data;
  const items = useMemo(
    () =>
      series.data &&
      timeSeries(
        {
          series: feedSeries(series.data.items),
          reducedMotion,
          format: (v) => decimal(v, v < 10 ? 1 : 0),
        },
        tokens,
      ),
    [series.data, tokens, reducedMotion],
  );
  const requests = useMemo(
    () =>
      series.data &&
      timeSeries(
        {
          reducedMotion,
          format: (v) => decimal(v, v < 10 ? 1 : 0),
          series: (
            [
              ["requests", "Requests", "var(--series-1)"],
              ["errors", "Errors", "var(--series-8)"],
              ["gaps", "Gaps", "var(--series-4)"],
            ] as const
          ).map(([key, name, color]) => ({
            name,
            color,
            points: series.data.requests.map(
              (row) => [Date.parse(row.time), row[key] ?? null] as [number, number | null],
            ),
          })),
        },
        tokens,
      ),
    [series.data, tokens, reducedMotion],
  );

  const health = data ? collectionHealth(data) : null;
  const status: ["good" | "warning", string] | null = health
    ? [health.status === "good" ? "good" : "warning", health.long]
    : null;

  return (
    <>
      <PageHeader title="Collection">
        Is the ingester healthy and complete? Requests to each platform, what they found, and what's
        stored.
      </PageHeader>
      <div className="flex flex-col gap-4">
        <Filters>
          {(meta.data?.platforms ?? []).length > 1 && (
            <MultiPicker
              label="Platform"
              allLabel="Every platform"
              options={(meta.data?.platforms ?? []).map(
                (platform) => [platform, platform] as const,
              )}
              value={search.platforms}
              onChange={(platforms) => set({ platforms })}
            />
          )}
          <Field label="Charts over">
            <Segmented
              label="Range"
              value={search.range}
              onChange={(range) => set({ range })}
              options={[
                ["1h", "1 hour"],
                ["6h", "6 hours"],
                ["24h", "24 hours"],
                ["7d", "7 days"],
              ]}
            />
          </Field>
        </Filters>

        {status && <Notice tone={status[0]}>{status[1]}</Notice>}

        <KpiRow>
          <StatTile
            label="Collected, 24 hours"
            value={data ? count(data.documents_24h) : "…"}
            unit="comments and posts"
            help="From the tracked channels of the selected platforms, without their samples (r/all)."
          />
          <StatTile
            label="Requests, last 10 minutes"
            value={data ? count(data.requests_10m) : "…"}
            hint={
              <Meter value={data?.requests_10m ?? 0} max={RATE_LIMIT}>
                of {count(RATE_LIMIT)} allowed
              </Meter>
            }
            help="Reddit allows 1,000 requests per 10 minutes per client id."
          />
          <StatTile
            label="Gaps, 24 hours"
            value={data ? count(data.gaps_24h) : "…"}
            hint={
              data &&
              (data.gaps_24h ? (
                <StatusBadge status="warning">Some items probably missed</StatusBadge>
              ) : (
                <StatusBadge status="good">None</StatusBadge>
              ))
            }
            help="Polls that found a full listing of unseen items: some items were probably missed. The feed then polls more often."
          />
          <StatTile
            label="Share of reddit sampled"
            value={data?.sampled_share == null ? "–" : percent(data.sampled_share, 2)}
            help="The r/all sample: new comments we got against how far reddit's comment ids advanced, over the charts' range."
          />
          <StatTile
            label="Last request"
            value={data ? ago(data.last_poll) : "…"}
            hint={data?.last_poll ? formatDateTime(data.last_poll) : undefined}
          />
        </KpiRow>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="New items per minute" subtitle="By feed">
            <Loaded query={series} height={220}>
              {() =>
                items ? (
                  <Chart
                    option={items}
                    height={220}
                    label="New items per minute by feed"
                    group="collection"
                  />
                ) : null
              }
            </Loaded>
          </Panel>
          <Panel title="Requests per minute" subtitle="With errors and gaps">
            <Loaded query={series} height={220}>
              {() =>
                requests ? (
                  <Chart
                    option={requests}
                    height={220}
                    label="Requests, errors and gaps per minute"
                    group="collection"
                  />
                ) : null
              }
            </Loaded>
          </Panel>
        </div>

        <Panel title="Feeds, last hour" flush>
          <Loaded query={ingestion} shape="table">
            {(loaded) => (
              <DataTable
                label="Feeds"
                rows={loaded.feeds}
                rowKey={(row) => `${row.platform}|${row.feed}`}
                limit={30}
                columns={[
                  {
                    id: "state",
                    header: "State",
                    sort: (row) => feedState(row)[1],
                    cell: (row) => {
                      const [state, label] = feedState(row);
                      return <StatusBadge status={state}>{label}</StatusBadge>;
                    },
                  },
                  {
                    id: "feed",
                    header: "Feed",
                    sort: (row) => row.feed,
                    cell: (row) => (
                      <span>
                        <span className="font-medium">{row.feed}</span>{" "}
                        <span className="text-xs text-ink-muted">{row.platform}</span>
                      </span>
                    ),
                  },
                  {
                    id: "polls",
                    header: "Requests",
                    numeric: true,
                    sort: (row) => row.polls,
                    cell: (row) => count(row.polls),
                  },
                  {
                    id: "errors",
                    header: "Errors",
                    numeric: true,
                    sort: (row) => row.errors,
                    cell: (row) => count(row.errors),
                  },
                  {
                    id: "new",
                    header: "New items",
                    numeric: true,
                    sort: (row) => row.new_items,
                    cell: (row) => count(row.new_items),
                  },
                  {
                    id: "gaps",
                    header: "Gaps",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.gaps,
                    cell: (row) => count(row.gaps),
                  },
                  {
                    id: "every",
                    header: "Polled every",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.poll_every_s,
                    cell: (row) =>
                      `${decimal(row.poll_every_s, (row.poll_every_s ?? 0) < 10 ? 1 : 0)} s`,
                  },
                  {
                    id: "last",
                    header: "Last request",
                    wide: true,
                    sort: (row) => row.last_poll,
                    cell: (row) => (
                      <span title={formatDateTime(row.last_poll)}>{ago(row.last_poll)}</span>
                    ),
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Channels, last 24 hours"
            flush
            help="Every channel of config.yaml: the tracked ones, the samples (r/all) and the radar's search (r/_search). People add up per type: someone writing a comment and a post counts twice."
          >
            <Loaded query={ingestion} shape="table">
              {(loaded) => (
                <DataTable
                  label="Channels"
                  rows={loaded.channels}
                  rowKey={(row) => row.channel}
                  limit={15}
                  initialSort={{ id: "documents", desc: true }}
                  columns={[
                    {
                      id: "channel",
                      header: "Channel",
                      sort: (row) => row.channel,
                      cell: (row) => (
                        <span>
                          {row.channel}
                          {row.background ? (
                            <span className="ml-1.5 text-xs text-ink-muted">sample</span>
                          ) : !row.analyzed ? (
                            <span className="ml-1.5 text-xs text-ink-muted">search</span>
                          ) : null}
                        </span>
                      ),
                    },
                    {
                      id: "documents",
                      header: "Collected",
                      numeric: true,
                      sort: (row) => row.documents,
                      cell: (row) => count(row.documents),
                    },
                    {
                      id: "types",
                      header: "By type",
                      wide: true,
                      cell: (row) => (
                        <span className="text-xs text-ink-muted">
                          {row.by_type.map(([type, n]) => `${count(n)} ${type}s`).join(", ") ||
                            "nothing"}
                        </span>
                      ),
                    },
                    {
                      id: "authors",
                      header: "People",
                      numeric: true,
                      sort: (row) => row.authors,
                      cell: (row) => count(row.authors),
                    },
                  ]}
                />
              )}
            </Loaded>
          </Panel>
          <Panel title="Storage" flush>
            <Loaded query={ingestion} shape="table">
              {(loaded) => (
                <DataTable
                  label="Storage per table"
                  rows={loaded.storage}
                  rowKey={(row) => row.table}
                  limit={20}
                  columns={[
                    {
                      id: "table",
                      header: "Table",
                      sort: (row) => row.table,
                      cell: (row) => <code className="text-xs">{row.table}</code>,
                    },
                    {
                      id: "rows",
                      header: "Rows",
                      numeric: true,
                      sort: (row) => row.rows,
                      cell: (row) => count(row.rows),
                    },
                    {
                      id: "bytes",
                      header: "On disk",
                      numeric: true,
                      sort: (row) => row.bytes,
                      cell: (row) => bytes(row.bytes),
                    },
                  ]}
                />
              )}
            </Loaded>
          </Panel>
        </div>
      </div>
    </>
  );
}
