import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useLongTerm } from "@/api/generated/endpoints";
import type { LongTermTrend } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { Sparkline } from "@/charts/micro";
import { timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { type Column, DataTable } from "@/components/DataTable";
import { KindBadge, StrengthWord, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Notice, Panel } from "@/components/Panel";
import {
  Field,
  KindChips,
  MultiPicker,
  ScopePicker,
  Segmented,
  scopeOptions,
} from "@/components/Pickers";
import { KpiRow, StatTile } from "@/components/Stat";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { assignSlots, colorOf } from "@/lib/colors";
import {
  ago,
  confidence,
  count,
  decimal,
  formatDate,
  formatDateTime,
  percent,
  perThousand,
  signedPercent,
} from "@/lib/format";
import { ALL_KINDS } from "@/lib/kinds";
import { useSetSearch } from "@/lib/navigation";
import { longTermDefaults, longTermSearch } from "@/lib/search";

export const Route = createFileRoute("/long-term")({
  validateSearch: longTermSearch,
  search: { middlewares: [stripSearchParams(longTermDefaults)] },
  component: LongTermPage,
});

const CATEGORIES = [
  [
    "emerging",
    "Emerging",
    "Rare at the start of the window (at most 1 in 1,000 comments and posts), growing significantly and steadily.",
  ],
  [
    "mainstreaming",
    "Mainstreaming",
    "Common already at the start of the window, still growing significantly and steadily.",
  ],
  ["fading", "Fading", "Its share shrank significantly and steadily."],
  [
    "one-off",
    "One-offs",
    "The change comes mostly from one or two weeks far above the rest (at least half of it, the peak at least 3 times the median week): an event, not a trend.",
  ],
] as const;
type Category = (typeof CATEGORIES)[number][0];
const WEEK = 7 * 86_400_000;
const key = (trend: LongTermTrend) => `${trend.scope}|${trend.term}`;

function LongTermPage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const query = useLongTerm({
    ...asOf,
    scope: search.scope,
    horizon: search.horizon,
    kinds: search.kinds,
    scopes: search.scopes,
  });
  const data = query.data;
  const weeks = Number(search.horizon.replace("w", ""));
  const byCategory = useMemo(() => {
    const groups: Record<Category, LongTermTrend[]> = {
      emerging: [],
      mainstreaming: [],
      fading: [],
      "one-off": [],
    };
    for (const trend of data?.trends ?? []) groups[trend.category as Category]?.push(trend);
    return groups;
  }, [data]);
  // the 8 fastest growing or fading, for the chart, and their colours in the tables
  const strongest = useMemo(
    () =>
      (data?.trends ?? [])
        .filter((trend) => trend.category !== "one-off")
        .sort((a, b) => Math.abs(Math.log(b.growth ?? 1)) - Math.abs(Math.log(a.growth ?? 1)))
        .slice(0, 8),
    [data],
  );
  const slots = useMemo(() => assignSlots(strongest.map(key)), [strongest]);
  const option = useMemo(
    () =>
      timeSeries(
        {
          series: strongest.map((trend) => ({
            name: `${trend.term} · ${trend.scope}`,
            color: colorOf(slots, key(trend)),
            points: trend.weekly.map((value, index) => [
              Date.parse(`${trend.window_start}T00:00:00Z`) + index * WEEK,
              value,
            ]),
          })),
          daily: true,
          format: perThousand,
          reducedMotion,
        },
        tokens,
      ),
    [strongest, slots, tokens, reducedMotion],
  );
  const tab = search.tab;
  const description = CATEGORIES.find(([name]) => name === tab)?.[2];

  return (
    <>
      <PageHeader title="Long-term trends">
        Terms whose share of the conversation grows or fades steadily, week after week. Found once a
        day; the results change on Mondays, when a week completes.
      </PageHeader>
      <div className="flex flex-col gap-4">
        <Filters>
          <ScopePicker
            meta={meta.data}
            value={search.scope}
            onChange={(scope) => set({ scope, scopes: [] })}
          />
          <Field label="Over">
            <Segmented
              label="Window"
              value={search.horizon}
              onChange={(horizon) => set({ horizon })}
              options={[
                ["13w", "13 weeks"],
                ["26w", "26 weeks"],
                ["52w", "52 weeks"],
              ]}
            />
          </Field>
          <MultiPicker
            label="Show"
            allLabel="Group and its channels"
            options={scopeOptions(meta.data, search.scope)}
            value={search.scopes}
            onChange={(scopes) => set({ scopes })}
          />
          <KindChips kinds={ALL_KINDS} value={search.kinds} onChange={(kinds) => set({ kinds })} />
        </Filters>

        {data && data.weeks_of_history < weeks && (
          <Notice>
            The {weeks}-week window needs {weeks} complete weeks of data. {search.scope} has{" "}
            {data.weeks_of_history} so far, so its first results come in about{" "}
            {weeks - data.weeks_of_history} week{weeks - data.weeks_of_history === 1 ? "" : "s"}.
          </Notice>
        )}

        <KpiRow>
          <StatTile
            label="Last run"
            value={data ? ago(data.last_run) : "…"}
            hint={data?.last_run ? formatDateTime(data.last_run) : "once a day after 00:30 UTC"}
            help="When the stored results were found. The detector runs every day after 00:30 UTC; the results only change when a week has completed."
          />
          <StatTile
            label="Weeks analyzed up to"
            value={data?.analyzed_until ? formatDate(data.analyzed_until) : "–"}
            help="The last day of the last complete week analyzed (weeks run Monday to Sunday, UTC)."
          />
          <StatTile
            label="History"
            value={data?.weeks_of_history ?? "…"}
            unit="complete weeks"
            hint={`the window needs ${weeks}`}
          />
          <StatTile
            label="Trends found"
            value={data ? count(data.trends.length) : "…"}
            hint={
              data
                ? CATEGORIES.map(
                    ([name, label]) => `${byCategory[name].length} ${label.toLowerCase()}`,
                  ).join(" · ")
                : undefined
            }
          />
        </KpiRow>

        {strongest.length > 0 && (
          <Panel
            title="The fastest growing and fading"
            subtitle={`Weekly share per 1,000 comments and posts${meta.data?.groups[search.scope] ? ", a group's the average of its channels' shares" : ""}`}
          >
            <Chart
              option={option}
              height={260}
              label="The fastest growing and fading terms, weekly share"
            />
          </Panel>
        )}

        <Panel flush>
          <Tabs value={tab} onValueChange={(value) => set({ tab: value })}>
            <div className="overflow-x-auto px-4 pt-1">
              <TabsList variant="line">
                {CATEGORIES.map(([name, label]) => (
                  <TabsTrigger key={name} value={name}>
                    {label}
                    <span className="ml-1 text-xs text-ink-muted tabular-nums">
                      {byCategory[name].length}
                    </span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
            <TabsContent value={tab}>
              <p className="px-4 pt-2 pb-2 text-xs text-ink-muted">{description}</p>
              <Loaded query={query} height={240}>
                {() => (
                  <DataTable
                    key={tab}
                    label={`${tab} terms`}
                    rows={byCategory[tab]}
                    rowKey={key}
                    limit={25}
                    initialSort={
                      tab === "one-off" ? null : { id: "growth", desc: tab !== "fading" }
                    }
                    empty={
                      <EmptyState title={`No ${tab} terms`}>
                        {data && data.weeks_of_history < weeks
                          ? `The ${weeks}-week window hasn't run yet.`
                          : "Nothing passed the tests in this window and scope."}
                      </EmptyState>
                    }
                    columns={columns(tab, slots)}
                  />
                )}
              </Loaded>
            </TabsContent>
          </Tabs>
        </Panel>
      </div>
    </>
  );
}

function columns(tab: Category, slots: Map<string, number>): Array<Column<LongTermTrend>> {
  const oneOff = tab === "one-off";
  return [
    {
      id: "term",
      header: "Term",
      cell: (row) => (
        <>
          <TermLink term={row.term} kind={row.kind} color={colorOf(slots, key(row))} />
          <KindBadge kind={row.kind} />
        </>
      ),
    },
    {
      id: "scope",
      header: "Where",
      wide: true,
      sort: (row) => row.scope,
      cell: (row) => row.scope,
    },
    oneOff
      ? {
          id: "change",
          header: "Change",
          numeric: true,
          sort: (row) => row.change,
          help: "The second half of the window against the first, per month.",
          cell: (row) => signedPercent(100 * ((row.change ?? 1) - 1)),
        }
      : {
          id: "growth",
          header: "Per month",
          numeric: true,
          sort: (row) => row.growth,
          help: "Growth per month: the Theil–Sen slope of the weekly share, robust to single spikes.",
          cell: (row) => (
            <span className="font-medium">{signedPercent(100 * ((row.growth ?? 1) - 1))}</span>
          ),
        },
    {
      id: "weekly",
      header: "Weekly share",
      wide: true,
      cell: (row) => (
        <Sparkline
          values={row.weekly}
          width={120}
          color={colorOf(slots, key(row))}
          label={`${row.term}, weekly share`}
        />
      ),
    },
    {
      id: "share",
      header: "Per 1,000",
      numeric: true,
      sort: (row) => row.end_share,
      help: "The trend line at the first and the last week of the window, per 1,000 comments and posts.",
      cell: (row) => (
        <span className="whitespace-nowrap">
          {perThousand(row.start_share)} → {perThousand(row.end_share)}
        </span>
      ),
    },
    {
      id: "mentions",
      header: "Mentions",
      numeric: true,
      wide: true,
      sort: (row) => row.mentions,
      cell: (row) => count(row.mentions),
    },
    ...(oneOff
      ? [
          {
            id: "spike",
            header: "From 2 weeks",
            numeric: true,
            sort: (row: LongTermTrend) => row.spike_share,
            help: "How much of the change comes from the two highest weeks.",
            cell: (row: LongTermTrend) => percent(row.spike_share),
          },
          {
            id: "peak",
            header: "Peak",
            numeric: true,
            sort: (row: LongTermTrend) => row.peak,
            help: "The highest week, times the median week.",
            cell: (row: LongTermTrend) => `×${decimal(row.peak)}`,
          },
        ]
      : []),
    {
      id: "confidence",
      header: "Confidence",
      sort: (row) => -(row.q ?? 1),
      help: "How sure the trend is steady: the Mann–Kendall test corrected for testing many terms at once (Benjamini–Hochberg q, at most 0.05 to be shown; hover for it).",
      cell: (row) => (
        <StrengthWord value={confidence(row.q)} title={`q ${row.q?.toExponential(1) ?? "–"}`} />
      ),
    },
  ];
}
