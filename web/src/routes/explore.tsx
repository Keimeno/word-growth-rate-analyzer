import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useExplore, useExploreMentions } from "@/api/generated/endpoints";
import type { Explore } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { Comments } from "@/components/Comments";
import { DataTable } from "@/components/DataTable";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Field, MultiPicker, ScopePicker, Segmented } from "@/components/Pickers";
import { Button } from "@/components/ui/button";
import { seriesColor } from "@/lib/colors";
import { count, formatDateTime, perThousand } from "@/lib/format";
import { useSetSearch } from "@/lib/navigation";
import { exploreDefaults, exploreSearch } from "@/lib/search";

export const Route = createFileRoute("/explore")({
  validateSearch: exploreSearch,
  search: { middlewares: [stripSearchParams(exploreDefaults)] },
  component: ExplorePage,
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
const MAX_TERMS = 8;

function TermsInput({ terms, onChange }: { terms: string[]; onChange: (terms: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = (text: string) => {
    const added = text
      .split(",")
      .map((term) => term.trim().toLowerCase().replace(/\s+/g, " "))
      .filter(Boolean);
    const next = [...new Set([...terms, ...added])].slice(0, MAX_TERMS);
    if (next.length !== terms.length) onChange(next);
    setDraft("");
  };
  return (
    <div className="flex min-h-9 flex-1 flex-wrap items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2 py-1 focus-within:outline-2 focus-within:outline-focus-ring">
      {terms.map((term, index) => (
        <button
          key={term}
          type="button"
          title={`Remove ${term}`}
          className="inline-flex items-center gap-1.5 rounded-sm bg-surface-sunken px-2 py-0.5 text-sm hover:bg-surface-hover"
          onClick={() => onChange(terms.filter((other) => other !== term))}
        >
          <span
            aria-hidden
            className="h-0.5 w-2.5 rounded-full"
            style={{ background: seriesColor(index) }}
          />
          <span className="term">{term}</span>
          <X className="size-3 text-ink-muted" />
        </button>
      ))}
      {terms.length < MAX_TERMS && (
        <input
          className="min-w-36 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-ink-muted"
          value={draft}
          aria-label="Add a term"
          placeholder={terms.length ? "Add a term…" : "Type a term, then Enter"}
          onChange={(event) => {
            const value = event.target.value;
            if (value.includes(",")) add(value);
            else setDraft(value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && draft.trim()) add(draft);
            if (event.key === "Backspace" && !draft && terms.length) onChange(terms.slice(0, -1));
          }}
          onBlur={() => draft.trim() && add(draft)}
        />
      )}
    </div>
  );
}

function ExplorePage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const terms = search.terms;
  const isGroup = Boolean(meta.data?.groups[search.scope]);
  const window =
    search.from !== undefined && search.to !== undefined
      ? { from: search.from, to: search.to }
      : { range: search.range };
  const common = {
    ...asOf,
    terms,
    scope: search.scope,
    bucket: search.bucket,
    channels: search.channels,
    doc_types: search.doc_types,
  };
  const explore = useExplore({ ...common, ...window }, { query: { enabled: terms.length > 0 } });
  // the text is only kept for 48 hours
  const mentions = useExploreMentions(
    { ...common, range: "2d" },
    { query: { enabled: terms.length > 0 } },
  );
  const shareKey = search.rate === "macro" && isGroup ? "macro" : "pooled";
  const daily = explore.data !== undefined && explore.data.bucket !== "hour";
  const groupChannels = meta.data?.groups[search.scope] ?? [];
  const brush = useCallback(
    (from: number, to: number) => set({ from: Math.floor(from / 1000), to: Math.ceil(to / 1000) }),
    [set],
  );

  const build = useCallback(
    (data: Explore, value: "pooled" | "macro" | "mentions" | "authors", form: "line" | "bars") =>
      timeSeries(
        {
          form,
          daily,
          reducedMotion,
          brush: form === "line",
          ...(value === "pooled" || value === "macro" ? { format: perThousand } : {}),
          series: terms
            .map((term, index) => ({
              name: term,
              color: seriesColor(index),
              points: data.points
                .filter((point) => point.term === term)
                .map(
                  (point) =>
                    [Date.parse(point.time), point[value] ?? null] as [number, number | null],
                ),
            }))
            .filter((series) => series.points.length),
        },
        tokens,
      ),
    [terms, daily, tokens, reducedMotion],
  );
  const share = useMemo(
    () => explore.data && build(explore.data, shareKey, "line"),
    [explore.data, build, shareKey],
  );
  const counts = useMemo(
    () => explore.data && build(explore.data, "mentions", "bars"),
    [explore.data, build],
  );
  const people = useMemo(
    () => explore.data && build(explore.data, "authors", "bars"),
    [explore.data, build],
  );
  const bucketLabel = explore.data
    ? explore.data.bucket === "hour" && (explore.data.step ?? 3600) > 3600
      ? `${(explore.data.step ?? 3600) / 3600} hours`
      : explore.data.bucket
    : "";

  return (
    <>
      <PageHeader title="Explore">
        How often terms are mentioned over time, where, and by whom. Shares are per 1,000 comments
        and posts, so the daily and weekly swings in activity cancel out.
      </PageHeader>
      <div className="flex flex-col gap-4">
        <TermsInput terms={terms} onChange={(next) => set({ terms: next })} />
        <Filters>
          <ScopePicker
            meta={meta.data}
            value={search.scope}
            onChange={(scope) => set({ scope, channels: [] })}
          />
          <Field label="Over">
            <Segmented
              label="Range"
              value={search.range}
              onChange={(range) => set({ range, from: undefined, to: undefined })}
              options={RANGES}
            />
          </Field>
          <Field label="Per">
            <Segmented
              label="Bucket"
              value={search.bucket}
              onChange={(bucket) => set({ bucket })}
              options={[
                ["auto", "Auto"],
                ["hour", "Hour"],
                ["day", "Day"],
                ["week", "Week"],
              ]}
            />
          </Field>
          {isGroup && (
            <Field label="Group share">
              <Segmented
                label="Group share"
                value={search.rate}
                onChange={(rate) => set({ rate })}
                options={[
                  ["pooled", "All together"],
                  ["macro", "Average of channels"],
                ]}
              />
            </Field>
          )}
          {groupChannels.length > 0 && (
            <MultiPicker
              label="Channels"
              allLabel="All channels"
              options={groupChannels.map((channel) => [channel, channel] as const)}
              value={search.channels}
              onChange={(channels) => set({ channels })}
            />
          )}
        </Filters>
        {search.from !== undefined && search.to !== undefined && (
          <p className="text-xs text-ink-muted">
            Showing {formatDateTime(new Date(search.from * 1000))} to{" "}
            {formatDateTime(new Date(search.to * 1000))}.{" "}
            <Button
              variant="link"
              size="xs"
              onClick={() => set({ from: undefined, to: undefined })}
            >
              Back to the last {RANGES.find(([key]) => key === search.range)?.[1]}
            </Button>
          </p>
        )}

        {!terms.length ? (
          <Panel>
            <EmptyState title="Name a term to explore">
              Words, phrases (“claude code”), domains, subreddits or intents (“notion → obsidian”,
              “complaint: reddit”).
            </EmptyState>
          </Panel>
        ) : (
          <>
            <Panel
              title="Share of the conversation"
              subtitle={`Per 1,000 comments and posts in ${search.scope}${shareKey === "macro" ? ", averaged over its channels" : ""}${bucketLabel ? ` · per ${bucketLabel}` : ""} · drag across the chart to zoom in`}
              help="Hours reach back 180 days, days and weeks forever. Weeks are whole ISO weeks, Monday to Sunday UTC. “All together” divides all mentions by all comments and posts; “average of channels” averages each channel's share."
            >
              <Loaded query={explore} height={300}>
                {(data) =>
                  data.points.length && share ? (
                    <Chart
                      option={share}
                      height={300}
                      label={`Share of ${terms.join(", ")} over time`}
                      group="explore"
                      onBrush={brush}
                    />
                  ) : (
                    <EmptyState title="No mentions in this range">
                      Check the spelling, or try a longer range or a bigger group.
                    </EmptyState>
                  )
                }
              </Loaded>
            </Panel>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel
                title="Mentions"
                subtitle="Comments and posts containing the term, each counted once"
              >
                <Loaded query={explore} height={220}>
                  {(data) =>
                    data.points.length && counts ? (
                      <Chart
                        option={counts}
                        height={220}
                        label="Mentions over time"
                        group="explore"
                      />
                    ) : (
                      <EmptyState title="No mentions" />
                    )
                  }
                </Loaded>
              </Panel>
              <Panel
                title="People"
                subtitle="Different authors. Few people and many mentions usually means spam or one heated thread."
              >
                <Loaded query={explore} height={220}>
                  {(data) =>
                    data.points.length && people ? (
                      <Chart
                        option={people}
                        height={220}
                        label="People over time"
                        group="explore"
                      />
                    ) : (
                      <EmptyState title="No mentions" />
                    )
                  }
                </Loaded>
              </Panel>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Where it's discussed" flush subtitle="In this range">
                <Loaded query={explore}>
                  {(data) => (
                    <DataTable
                      label="Where it's discussed"
                      rows={data.where}
                      rowKey={(row) => `${row.term}|${row.channel}`}
                      limit={12}
                      columns={[
                        {
                          id: "term",
                          header: "Term",
                          sort: (row) => row.term,
                          cell: (row) => (
                            <span className="inline-flex items-center gap-1.5">
                              <span
                                aria-hidden
                                className="h-0.5 w-2.5 rounded-full"
                                style={{ background: seriesColor(terms.indexOf(row.term)) }}
                              />
                              <span className="term">{row.term}</span>
                            </span>
                          ),
                        },
                        {
                          id: "channel",
                          header: "Channel",
                          sort: (row) => row.channel,
                          cell: (row) => row.channel,
                        },
                        {
                          id: "mentions",
                          header: "Mentions",
                          numeric: true,
                          sort: (row) => row.mentions,
                          cell: (row) => count(row.mentions),
                        },
                        {
                          id: "authors",
                          header: "People",
                          numeric: true,
                          sort: (row) => row.authors,
                          cell: (row) => count(row.authors),
                        },
                        {
                          id: "per_1000",
                          header: "Per 1,000",
                          numeric: true,
                          sort: (row) => row.per_1000,
                          cell: (row) => perThousand(row.per_1000),
                        },
                      ]}
                    />
                  )}
                </Loaded>
              </Panel>
              <Panel
                title="Recent mentions"
                subtitle="The last 48 hours: raw text isn't kept longer"
                flush
              >
                <Loaded query={mentions}>
                  {(rows) => <Comments mentions={rows.slice(0, 30)} terms={terms} />}
                </Loaded>
              </Panel>
            </div>
          </>
        )}
      </div>
    </>
  );
}
