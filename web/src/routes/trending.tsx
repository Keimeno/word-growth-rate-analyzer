import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import {
  useRising,
  useTrendAlerts,
  useTrendDigest,
  useTrendSeries,
  useTrends,
} from "@/api/generated/endpoints";
import type { Trend } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { Sparkline } from "@/charts/micro";
import { type Series, timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { BumpPanel, WhatIfPanel } from "@/components/Extras";
import { ALERT_HELP, AlertBadge, KindBadge, StrengthWord, TermLink } from "@/components/Entity";
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
import { Switch } from "@/components/ui/switch";
import { assignSlots, colorOf } from "@/lib/colors";
import { ago, count, decimal, formatDateTime, perThousand, strength, times } from "@/lib/format";
import { ALL_KINDS, WORD_KINDS } from "@/lib/kinds";
import { useSetSearch } from "@/lib/navigation";
import { trendingDefaults, trendingSearch } from "@/lib/search";

export const Route = createFileRoute("/trending")({
  validateSearch: trendingSearch,
  search: { middlewares: [stripSearchParams(trendingDefaults)] },
  component: TrendingPage,
});

function TrendingPage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const quick = search.view === "quick";
  return (
    <>
      <PageHeader
        title={quick ? "Quick look" : "Trending now"}
        actions={
          <Segmented
            label="View"
            value={search.view}
            onChange={(view) => set({ view })}
            options={[
              ["scored", "Scored trends"],
              ["quick", "Quick look"],
            ]}
          />
        }
      >
        {quick
          ? "A first, rough look: the last 24 hours against the 7 days before, without the detector's scoring."
          : "Terms mentioned far more than usual, found every 15 minutes. Open a term to see it over time and the comments behind it."}
      </PageHeader>
      {quick ? <QuickLook /> : <Scored />}
    </>
  );
}

type Row = Trend & { others: string[] };

function Scored() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const params = {
    ...asOf,
    scope: search.scope,
    horizon: search.horizon,
    kinds: search.kinds,
    scopes: search.scopes,
    subsumed: search.subsumed,
  };
  const trends = useTrends(params);
  const series = useTrendSeries({ ...params, range: search.chart });
  const digest = useTrendDigest(params);
  const alerts = useTrendAlerts({ ...asOf, scope: search.scope, scopes: search.scopes });
  const data = trends.data;

  // one row per term at its strongest (rows come strongest first), with where else
  const rows = useMemo(() => {
    const byTerm = new Map<string, Row>();
    for (const trend of data?.trends ?? []) {
      const key = `${trend.kind}|${trend.term}`;
      const seen = byTerm.get(key);
      if (seen) seen.others.push(trend.scope);
      else byTerm.set(key, { ...trend, others: [] });
    }
    return [...byTerm.values()];
  }, [data]);
  // the chart's 8 terms keep their colour in the table
  const slots = useMemo(
    () => assignSlots(rows.filter((row) => !row.subsumed_by).map((row) => row.term)),
    [rows],
  );
  const option = useMemo(() => {
    if (!series.data) return undefined;
    const byTerm = new Map<string, Series>();
    for (const point of series.data) {
      const line = byTerm.get(point.term) ?? {
        name: point.term,
        color: colorOf(slots, point.term),
        points: [],
      };
      line.points.push([Date.parse(point.time), point.per_1000 ?? null]);
      byTerm.set(point.term, line);
    }
    const ordered = [...byTerm.values()].sort(
      (a, b) => (slots.get(a.name) ?? 99) - (slots.get(b.name) ?? 99),
    );
    return timeSeries({ series: ordered, format: perThousand, reducedMotion }, tokens);
  }, [series.data, slots, tokens, reducedMotion]);

  const warmup = data && data.reference_days !== null && data.reference_days < 3;
  return (
    <div className="flex flex-col gap-4">
      <Filters>
        <ScopePicker
          meta={meta.data}
          value={search.scope}
          onChange={(scope) => set({ scope, scopes: [] })}
        />
        <Field label="Window">
          <Segmented
            label="Window"
            value={search.horizon}
            onChange={(horizon) => set({ horizon })}
            options={[
              ["24h", "Last 24 hours"],
              ["6h", "Last 6 hours"],
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
        <div className="flex items-center gap-2 text-xs text-ink-muted">
          <Switch
            id="subsumed"
            checked={search.subsumed}
            onCheckedChange={(subsumed) => set({ subsumed })}
          />
          <label htmlFor="subsumed">Explained bursts</label>
        </div>
      </Filters>

      {warmup && (
        <Notice>
          {data.reference_days === 0
            ? "No history to compare with yet."
            : `Only ${data.reference_days} day${data.reference_days === 1 ? "" : "s"} of history so far.`}{" "}
          Until there's more, each window is compared with the term's share on the whole platform,
          so this shows what's distinctive here more than what's rising. Alerts start at 3 days, the
          full 28-day comparison takes 4 weeks.
        </Notice>
      )}

      <KpiRow>
        <StatTile
          label="Last analysis"
          value={data ? ago(data.last_run) : "…"}
          hint={data?.last_run ? formatDateTime(data.last_run) : "runs every 15 minutes"}
          help="When the analyzer last scored this window. It runs every 15 minutes."
        />
        <StatTile
          label="History compared with"
          value={data?.reference_days ?? "–"}
          unit="of 28 days"
          help="Days of data each window is compared with, up to 28. Alerts need at least 3."
        />
        <StatTile
          label="Trending"
          value={data ? count(data.trending) : "…"}
          unit="terms"
          hint={`in the latest run${search.scopes.length ? ", picked scopes" : ""}`}
        />
        <StatTile
          label="Alerts sent"
          value={data ? count(data.alerts_sent) : "…"}
          unit="in 24 hours"
          hint="at most 5 a day, every group"
        />
      </KpiRow>

      <Panel
        title="Trending now"
        flush
        subtitle={
          data?.last_run
            ? `The ${search.horizon === "24h" ? "last 24 hours" : "last 6 hours"} against the 28 days before, as of ${formatDateTime(data.last_run)}`
            : undefined
        }
        help="Ranked by strength. A term trends with at least 10 mentions by 5 different people, twice its usual share, and a strength of 3. 'pro' isn't shown when 'vision pro' explains it, unless explained bursts are shown."
      >
        <Loaded query={trends} height={320}>
          {(loaded) => (
            <DataTable
              label="Trending terms"
              rows={rows}
              rowKey={(row) => `${row.kind}|${row.term}`}
              limit={30}
              empty={
                <EmptyState title="Nothing trending here right now">
                  Try another group, the 24-hour window or more kinds.
                </EmptyState>
              }
              columns={[
                {
                  id: "term",
                  header: "Term",
                  sort: (row) => row.term,
                  cell: (row) => (
                    <div className="min-w-0">
                      <TermLink term={row.term} kind={row.kind} color={colorOf(slots, row.term)} />
                      <KindBadge kind={row.kind} />
                      {row.subsumed_by && (
                        <div className="text-xs text-ink-muted">
                          explained by “{row.subsumed_by}”
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  id: "scope",
                  header: "Where",
                  sort: (row) => row.scope,
                  wide: true,
                  help: "Where it's strongest. For a group: in how many of its channels it trends, of those mentioning it.",
                  cell: (row) => (
                    <div>
                      {row.scope}
                      {row.scope_type === "group" && row.members > 0 && (
                        <span className="text-xs text-ink-muted">
                          {" "}
                          · {row.breadth} of {row.members} channels
                        </span>
                      )}
                      {row.others.length > 0 && (
                        <div className="text-xs text-ink-muted" title={row.others.join(", ")}>
                          also {row.others.slice(0, 3).join(", ")}
                          {row.others.length > 3 ? ` +${row.others.length - 3}` : ""}
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  id: "ratio",
                  header: "× usual",
                  numeric: true,
                  sort: (row) => (row.is_new ? Number.POSITIVE_INFINITY : row.ratio),
                  help: "The share of comments and posts mentioning it now, divided by its share before. new: barely mentioned before.",
                  cell: (row) => (
                    <span
                      title={`${count(row.mentions)} now, ${count(row.mentions_before)} in the 28 days before`}
                    >
                      {times(row.ratio, row.is_new)}
                    </span>
                  ),
                },
                {
                  id: "mentions",
                  header: "Mentions",
                  numeric: true,
                  sort: (row) => row.mentions,
                  cell: (row) => (
                    <div>
                      {count(row.mentions)}
                      <div className="text-xs text-ink-muted">{count(row.authors)} people</div>
                    </div>
                  ),
                },
                {
                  id: "strength",
                  header: "Strength",
                  sort: (row) => row.score,
                  help: "How strong the evidence is that it's mentioned more than usual (the z-score of the weighted log odds; hover for it). Trends are ranked by it: 3 is the minimum, instant alerts start at 10.",
                  cell: (row) => (
                    <StrengthWord value={strength(row.score)} title={`z ${decimal(row.score)}`} />
                  ),
                },
                {
                  id: "spark",
                  header: "Last 7 days",
                  wide: true,
                  cell: (row) => (
                    <Sparkline
                      values={loaded.sparklines[row.term]}
                      color={colorOf(slots, row.term)}
                      label={`${row.term}, hourly mentions over the last 7 days`}
                    />
                  ),
                },
                {
                  id: "alert",
                  header: "Alert",
                  wide: true,
                  help: ALERT_HELP,
                  sort: (row) => row.alert || null,
                  cell: (row) => <AlertBadge alert={row.alert} />,
                },
              ]}
            />
          )}
        </Loaded>
      </Panel>

      <Panel
        title="The strongest trends over time"
        subtitle={`The 8 strongest of the latest run, per 1,000 comments and posts in ${search.scope}`}
        actions={
          <Segmented
            label="Chart range"
            value={search.chart}
            onChange={(chart) => set({ chart })}
            options={[
              ["24h", "24h"],
              ["3d", "3 days"],
              ["7d", "7 days"],
              ["14d", "14 days"],
            ]}
          />
        }
      >
        <Loaded query={series} height={260}>
          {(points) =>
            points.length && option ? (
              <Chart option={option} height={260} label="The strongest trends, share over time" />
            ) : (
              <EmptyState title="No trends to chart" />
            )
          }
        </Loaded>
      </Panel>

      <BumpPanel scope={search.scope} horizon={search.horizon} />

      {data && data.trends.length > 0 && (
        <WhatIfPanel
          trends={data.trends}
          defaults={{ mentions: 10, authors: 5, ratio: 2, score: 3 }}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Strongest in the last 24 hours"
          flush
          subtitle="Each term at its strongest, in any scope here and either window. The daily digest sends a group's top 10."
        >
          <Loaded query={digest}>
            {(entries) => (
              <DataTable
                label="Strongest in the last 24 hours"
                rows={entries}
                rowKey={(row) => `${row.term_kind}|${row.term}`}
                limit={10}
                columns={[
                  {
                    id: "term",
                    header: "Term",
                    cell: (row) => <TermLink term={row.term} kind={row.term_kind} />,
                  },
                  {
                    id: "where",
                    header: "Strongest in",
                    wide: true,
                    cell: (row) => row.strongest_in,
                  },
                  {
                    id: "strength",
                    header: "Strength",
                    sort: (row) => row.score,
                    cell: (row) => (
                      <StrengthWord value={strength(row.score)} title={`z ${decimal(row.score)}`} />
                    ),
                  },
                  {
                    id: "ratio",
                    header: "× usual",
                    numeric: true,
                    sort: (row) => row.ratio,
                    cell: (row) => times(row.ratio, row.is_new),
                  },
                  {
                    id: "since",
                    header: "Since",
                    sort: (row) => row.first_seen,
                    cell: (row) => (
                      <span title={formatDateTime(row.first_seen)}>{ago(row.first_seen)}</span>
                    ),
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>
        <Panel title="Alerts, last 14 days" flush help={ALERT_HELP}>
          <Loaded query={alerts}>
            {(entries) => (
              <DataTable
                label="Alerts of the last 14 days"
                rows={entries}
                rowKey={(row) => `${row.time}|${row.horizon}|${row.scope}|${row.term}`}
                limit={10}
                empty={
                  <EmptyState title="No alert-worthy trends in 14 days">
                    Instant alerts need a strength of 10 and 20 people, or a term trending in many
                    channels of a group at once.
                  </EmptyState>
                }
                columns={[
                  {
                    id: "time",
                    header: "When",
                    sort: (row) => row.time,
                    cell: (row) => <span title={formatDateTime(row.time)}>{ago(row.time)}</span>,
                  },
                  {
                    id: "term",
                    header: "Term",
                    cell: (row) => (
                      <div>
                        <TermLink term={row.term} kind={row.kind} />
                        <div className="text-xs text-ink-muted">
                          {row.scope} · {row.horizon}
                        </div>
                      </div>
                    ),
                  },
                  {
                    id: "strength",
                    header: "Strength",
                    sort: (row) => row.score,
                    cell: (row) => (
                      <StrengthWord value={strength(row.score)} title={`z ${decimal(row.score)}`} />
                    ),
                  },
                  {
                    id: "status",
                    header: "Status",
                    cell: (row) => <AlertBadge alert={row.alert} />,
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>
      </div>
    </div>
  );
}

function QuickLook() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const rising = useRising({
    ...asOf,
    scope: search.scope,
    channels: search.channels,
    doc_types: search.doc_types,
    kinds: search.quick_kinds,
    min_mentions: search.min_mentions,
    min_authors: search.min_authors,
  });
  const groupChannels = meta.data?.groups[search.scope] ?? [];
  return (
    <div className="flex flex-col gap-4">
      <Filters>
        <ScopePicker
          meta={meta.data}
          value={search.scope}
          onChange={(scope) => set({ scope, channels: [] })}
        />
        {groupChannels.length > 0 && (
          <MultiPicker
            label="Channels"
            allLabel="All channels"
            options={groupChannels.map((channel) => [channel, channel] as const)}
            value={search.channels}
            onChange={(channels) => set({ channels })}
          />
        )}
        <MultiPicker
          label="Type"
          allLabel="Comments and posts"
          options={(meta.data?.doc_types ?? []).map((type) => [type, `${type}s`] as const)}
          value={search.doc_types}
          onChange={(doc_types) => set({ doc_types })}
        />
        <KindChips
          kinds={WORD_KINDS}
          value={search.quick_kinds}
          onChange={(quick_kinds) => set({ quick_kinds })}
        />
        <Field label="At least">
          <Segmented
            label="Minimum mentions"
            value={String(search.min_mentions)}
            onChange={(value) => set({ min_mentions: Number(value) })}
            options={(["5", "10", "25", "50"] as const).map((n) => [n, `${n} mentions`] as const)}
          />
        </Field>
      </Filters>
      <Panel
        title="Mentioned more than usual, last 24 hours"
        flush
        help="× usual: the share of comments and posts mentioning a term in the last 24 hours, divided by its usual share. Usual blends its share in the 7 days before with its share in the platform's background (the r/all sample), so without history this first shows what is distinctive for the group."
      >
        <Loaded query={rising} height={320}>
          {(rows) => (
            <DataTable
              label="Rising terms"
              rows={rows}
              rowKey={(row) => `${row.kind}|${row.term}`}
              limit={40}
              initialSort={{ id: "ratio", desc: true }}
              empty={
                <EmptyState title="Nothing rising here">
                  Try fewer minimum mentions or another group.
                </EmptyState>
              }
              columns={[
                {
                  id: "term",
                  header: "Term",
                  cell: (row) => (
                    <>
                      <TermLink term={row.term} kind={row.kind} />
                      <KindBadge kind={row.kind} />
                    </>
                  ),
                },
                {
                  id: "ratio",
                  header: "× usual",
                  numeric: true,
                  sort: (row) => row.times_usual,
                  cell: (row) => times(row.times_usual),
                },
                {
                  id: "mentions",
                  header: "Mentions",
                  numeric: true,
                  sort: (row) => row.mentions,
                  cell: (row) => (
                    <div>
                      {count(row.mentions)}
                      <div className="text-xs text-ink-muted">{count(row.authors)} people</div>
                    </div>
                  ),
                },
                {
                  id: "now",
                  header: "Per 1,000 now",
                  numeric: true,
                  wide: true,
                  sort: (row) => row.per_1000_now,
                  cell: (row) => perThousand(row.per_1000_now),
                },
                {
                  id: "usual",
                  header: "Usually",
                  numeric: true,
                  wide: true,
                  sort: (row) => row.per_1000_usual,
                  cell: (row) => perThousand(row.per_1000_usual),
                },
                {
                  id: "before",
                  header: "7 days before",
                  numeric: true,
                  wide: true,
                  sort: (row) => row.mentions_before,
                  cell: (row) => count(row.mentions_before),
                },
              ]}
            />
          )}
        </Loaded>
      </Panel>
    </div>
  );
}
