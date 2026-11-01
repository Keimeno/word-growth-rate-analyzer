import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { ArrowUpRight, Compass, Link2 } from "lucide-react";
import { useCallback, useMemo } from "react";
import {
  useExplore,
  useExploreMentions,
  useTermSummary,
  useTermAnnotations,
  useTermEvents,
} from "@/api/generated/endpoints";
import type { Annotations, TermSummary } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { BarList } from "@/charts/micro";
import { timeSeries } from "@/charts/options";
import { Comments } from "@/components/Comments";
import { DataTable } from "@/components/DataTable";
import { EventLink, ScopeLink, StrengthWord } from "@/components/Entity";
import { Explainer } from "@/components/Explainer";
import { ChannelsPanel, RelatedPanel, RhythmPanel } from "@/components/TermSections";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Field, ScopePicker, Segmented } from "@/components/Pickers";
import { Button } from "@/components/ui/button";
import {
  count,
  confidence,
  formatDate,
  formatShortDate,
  formatTime,
  perThousand,
  signedPercent,
  strength,
  times,
} from "@/lib/format";
import { grafanaLink } from "@/lib/grafana";
import { KIND_LABELS } from "@/lib/kinds";
import { pathPart, platformSearch } from "@/lib/links";
import { useSetSearch } from "@/lib/navigation";
import { termDefaults, termSearch } from "@/lib/search";

export const Route = createFileRoute("/t/$kind/$")({
  validateSearch: termSearch,
  search: { middlewares: [stripSearchParams(termDefaults)] },
  component: TermPage,
});

const RANGES = [
  ["24h", "24h"],
  ["2d", "2 days"],
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["90d", "90 days"],
  ["26w", "6 months"],
  ["52w", "1 year"],
] as const;

/** The term page (WEB-DASHBOARD.md §6.2): the page an alert opens, phone first. */
function TermPage() {
  const { kind, _splat: term = "" } = Route.useParams();
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const scope = search.scope;
  const summary = useTermSummary(kind, pathPart(term), { ...asOf, scope });
  const top = summary.data?.trending[0];
  const kindLabel = (KIND_LABELS[kind] ?? kind).replace(/s$/, "").toLowerCase();

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <nav aria-label="Breadcrumb" className="text-xs text-ink-muted">
          Terms · {kindLabel} · <ScopeLink scope={scope} />
        </nav>
        <h1 className="term type-title-xl break-words">{term}</h1>
        <p className="max-w-3xl text-sm text-ink-secondary">
          <StatusLine data={summary.data} />
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <ScopePicker meta={meta.data} value={scope} onChange={(next) => set({ scope: next })} />
          <Button size="sm" variant="outline" asChild>
            <a
              href={`/explore?terms=${encodeURIComponent(term)}&scope=${encodeURIComponent(scope)}`}
            >
              <Compass className="size-3.5" /> Explore
            </a>
          </Button>
          <Button size="sm" variant="ghost" asChild>
            <a href={platformSearch(term, scope)} target="_blank" rel="noreferrer">
              On Reddit <ArrowUpRight className="size-3.5" />
            </a>
          </Button>
          {meta.data && (
            <Button size="sm" variant="ghost" asChild>
              <a
                href={grafanaLink(meta.data.grafana_url, "explore", {
                  terms: term,
                  scope,
                  range: search.range,
                })}
                target="_blank"
                rel="noreferrer"
              >
                Pro mode <ArrowUpRight className="size-3.5" />
              </a>
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void navigator.clipboard.writeText(location.href)}
          >
            <Link2 className="size-3.5" /> Copy link
          </Button>
        </div>
      </header>

      <ShareOverTime kind={kind} term={term} />

      {top && (
        <Panel
          title="Why it's trending"
          subtitle={`In ${top.scope}, the ${top.horizon === "24h" ? "24-hour" : "6-hour"} window of the latest run`}
        >
          <Explainer kind={kind} term={term} scope={top.scope} horizon={top.horizon} />
        </Panel>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Where kind={kind} term={term} />
        <Spread kind={kind} term={term} summary={summary.data} />
      </div>

      <ChannelsPanel
        kind={kind}
        term={term}
        scope={scope}
        range={search.range === "24h" || search.range === "2d" ? "7d" : search.range}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <RelatedPanel kind={kind} term={term} scope={scope} />
        <RhythmPanel kind={kind} term={term} scope={scope} />
      </div>

      <LongTerm summary={summary.data} />

      <Panel title="Comments and posts" subtitle="The last 48 hours, the newest first" flush>
        <Mentions term={term} />
      </Panel>
    </div>
  );
}

function StatusLine({ data }: { data: TermSummary | undefined }) {
  if (!data) return <>Loading…</>;
  const top = data.trending[0];
  const growing = data.long_term.find(
    (row) => row.category !== "fading" && row.category !== "one-off",
  );
  const parts: string[] = [];
  if (top) {
    const breadth =
      top.scope_type === "group" && top.members
        ? `, in ${top.breadth} of ${top.members} channels`
        : "";
    parts.push(
      `Trending in ${top.scope}: ${times(top.ratio, top.is_new)} its usual share, ${strength(top.score).label}${breadth}.`,
    );
  }
  if (growing) {
    parts.push(
      `${growing.category === "emerging" ? "Emerging" : "Mainstreaming"} in ${growing.scope} over ${growing.horizon.replace("w", " weeks")} (${signedPercent(100 * ((growing.growth ?? 1) - 1))} a month).`,
    );
  }
  parts.push(
    `${count(data.mentions_7d)} comments and posts by ${count(data.authors_7d)} people in the last 7 days.`,
  );
  if (data.first_seen) parts.push(`First seen ${formatDate(data.first_seen)}.`);
  return <>{parts.join(" ")}</>;
}

/** Runs where it trended, merged into bands: consecutive runs at most 30 minutes apart. */
function bands(annotations: Annotations | undefined, scope: string) {
  const runs = (annotations?.runs ?? []).filter(
    (run) => run.scope === scope && run.horizon === "24h",
  );
  const result: Array<{ from: number; to: number; label: string }> = [];
  for (const run of runs) {
    const time = Date.parse(run.time);
    const last = result.at(-1);
    if (last && time - last.to <= 30 * 60_000) last.to = time;
    else result.push({ from: time, to: time + 15 * 60_000, label: "trending" });
  }
  return result;
}

function ShareOverTime({ kind, term }: { kind: string; term: string }) {
  const search = Route.useSearch();
  const set = useSetSearch();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const window =
    search.from !== undefined && search.to !== undefined
      ? { from: search.from, to: search.to }
      : { range: search.range };
  const explore = useExplore({ ...asOf, ...window, terms: [term], scope: search.scope });
  const annotations = useTermAnnotations(kind, pathPart(term), {
    ...asOf,
    ...window,
    scope: search.scope,
  });
  const option = useMemo(() => {
    if (!explore.data) return undefined;
    const alerts = (annotations.data?.runs ?? []).filter((run) => run.alert === "sent");
    const onsets = annotations.data?.onsets ?? [];
    const forecasts = (annotations.data?.forecasts ?? []).filter(
      (forecast) => forecast.outcome === "pending",
    );
    return timeSeries(
      {
        series: [
          {
            name: term,
            points: explore.data.points.map((point) => [
              Date.parse(point.time),
              point.pooled ?? null,
            ]),
          },
        ],
        format: perThousand,
        daily: explore.data.bucket !== "hour",
        reducedMotion,
        brush: true,
        bands: [
          ...bands(annotations.data, search.scope),
          ...forecasts.map((forecast) => ({
            from: Date.parse(forecast.leader_onset),
            to: Date.parse(forecast.due_by),
            label: `expected in ${forecast.follower}`,
          })),
        ],
        marks: [
          ...alerts.map((run) => ({ at: Date.parse(run.time), label: "alert" })),
          ...onsets.map((onset) => ({ at: Date.parse(onset.at), label: onset.scope })),
        ],
      },
      tokens,
    );
  }, [explore.data, annotations.data, term, search.scope, tokens, reducedMotion]);
  const brush = useCallback(
    (from: number, to: number) => set({ from: Math.floor(from / 1000), to: Math.ceil(to / 1000) }),
    [set],
  );
  return (
    <Panel
      title="Share of the conversation"
      subtitle={`Per 1,000 comments and posts in ${search.scope}, with the runs where it trended, alerts and onsets · drag across to zoom in`}
      actions={
        <Field label="Over">
          <Segmented
            label="Range"
            value={search.range}
            onChange={(range) => set({ range, from: undefined, to: undefined })}
            options={RANGES}
          />
        </Field>
      }
    >
      <Loaded query={explore} height={280}>
        {(data) =>
          data.points.length && option ? (
            <Chart
              option={option}
              height={280}
              label={`${term}: share over time`}
              onBrush={brush}
              group="term"
            />
          ) : (
            <EmptyState title={`No mentions in ${search.scope} in this range`}>
              Try a longer range or a bigger scope.
            </EmptyState>
          )
        }
      </Loaded>
    </Panel>
  );
}

function Where({ kind, term }: { kind: string; term: string }) {
  const search = Route.useSearch();
  const set = useSetSearch();
  const asOf = useAsOf();
  const explore = useExplore({ ...asOf, terms: [term], scope: search.scope, range: search.range });
  void kind;
  return (
    <Panel
      title="Where"
      subtitle="Per 1,000 comments and posts in each channel. Pick one to narrow the page to it."
    >
      <Loaded query={explore}>
        {(data) =>
          data.where.length ? (
            <BarList
              rows={[...data.where]
                .sort((a, b) => (b.per_1000 ?? 0) - (a.per_1000 ?? 0))
                .slice(0, 12)
                .map((row) => ({
                  key: row.channel,
                  label: row.channel,
                  value: row.per_1000 ?? 0,
                  note: `${count(row.mentions)} by ${count(row.authors)}`,
                }))}
              format={perThousand}
              selected={search.scope}
              onSelect={(channel) => set({ scope: channel })}
            />
          ) : (
            <EmptyState title="Not mentioned here in this range" />
          )
        }
      </Loaded>
    </Panel>
  );
}

function Spread({
  kind,
  term,
  summary,
}: {
  kind: string;
  term: string;
  summary: TermSummary | undefined;
}) {
  const asOf = useAsOf();
  const events = useTermEvents(kind, pathPart(term), asOf);
  return (
    <Panel
      title="Spread"
      subtitle={
        summary
          ? `${count(summary.events)} stories, ${count(summary.pending_forecasts)} forecasts waiting`
          : undefined
      }
      flush
    >
      <Loaded query={events}>
        {(rows) => (
          <DataTable
            label="Stories it was part of"
            rows={rows}
            rowKey={(row) => row.start}
            limit={6}
            empty={
              <EmptyState title="Not part of a story yet">
                A story starts when a term trends somewhere; its spread is tracked for 17 days.
              </EmptyState>
            }
            columns={[
              {
                id: "start",
                header: "Started",
                sort: (row) => row.start,
                cell: (row) => (
                  <EventLink kind={row.kind} term={row.term} start={row.start}>
                    {formatShortDate(row.start)} {formatTime(row.start)}
                  </EventLink>
                ),
              },
              {
                id: "path",
                header: "Path",
                cell: (row) => (
                  <span className="text-xs">
                    {row.cascade
                      .slice(0, 5)
                      .map((onset) => onset.scope)
                      .join(" → ") || "one place"}
                    {row.cascade.length > 5 ? ` +${row.cascade.length - 5}` : ""}
                  </span>
                ),
              },
              {
                id: "closed",
                header: "",
                wide: true,
                cell: (row) => (
                  <span className="text-xs text-ink-muted">{row.closed ? "closed" : "open"}</span>
                ),
              },
            ]}
          />
        )}
      </Loaded>
    </Panel>
  );
}

function LongTerm({ summary }: { summary: TermSummary | undefined }) {
  if (!summary?.long_term.length) return null;
  return (
    <Panel
      title="Long-term"
      subtitle="Its category in the latest analyzed week, per window and scope"
      flush
    >
      <DataTable
        label="Long-term trends of the term"
        rows={summary.long_term}
        rowKey={(row) => `${row.horizon}|${row.scope}`}
        columns={[
          { id: "scope", header: "Where", cell: (row) => <ScopeLink scope={row.scope} /> },
          { id: "horizon", header: "Window", cell: (row) => row.horizon.replace("w", " weeks") },
          { id: "category", header: "Category", cell: (row) => row.category },
          {
            id: "growth",
            header: "Per month",
            numeric: true,
            cell: (row) => signedPercent(100 * ((row.growth ?? 1) - 1)),
          },
          {
            id: "confidence",
            header: "Confidence",
            cell: (row) => <StrengthWord value={confidence(row.q)} />,
          },
          {
            id: "since",
            header: "Window from",
            wide: true,
            cell: (row) => formatDate(row.window_start),
          },
        ]}
      />
    </Panel>
  );
}

function Mentions({ term }: { term: string }) {
  const search = Route.useSearch();
  const asOf = useAsOf();
  const mentions = useExploreMentions({ ...asOf, terms: [term], scope: search.scope, range: "2d" });
  return (
    <Loaded query={mentions}>
      {(rows) => <Comments mentions={rows.slice(0, 30)} terms={[term]} />}
    </Loaded>
  );
}
