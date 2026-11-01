import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import {
  useIntentExamples,
  useIntentFlows,
  useIntentNeeds,
  useIntentRising,
  useIntents,
} from "@/api/generated/endpoints";
import type { Need } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { Sparkline, SplitBar } from "@/charts/micro";
import { timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { Comments } from "@/components/Comments";
import { DataTable } from "@/components/DataTable";
import { TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Field, MultiPicker, ScopePicker, Segmented } from "@/components/Pickers";
import { KpiRow, StatTile } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { seriesColor } from "@/lib/colors";
import { count, decimal, formatDate, perThousand, times } from "@/lib/format";
import { useSetSearch } from "@/lib/navigation";
import { intentsDefaults, intentsSearch } from "@/lib/search";

export const Route = createFileRoute("/intents")({
  validateSearch: intentsSearch,
  search: { middlewares: [stripSearchParams(intentsDefaults)] },
  component: IntentsPage,
});

const KINDS = [
  [
    "switch",
    "Switches",
    "Someone switched from one product to another: “switched from Notion to Obsidian”, “dropped ChatGPT for Claude”.",
  ],
  [
    "considering",
    "Considering a switch",
    "Someone thinks of switching or leaving, in the first person: “I'm thinking of switching from Notion to Obsidian”.",
  ],
  [
    "alternative",
    "Alternatives sought",
    "“Any alternatives to LastPass?”, “a good Plex alternative”, “I use Firefox instead of Chrome”.",
  ],
  [
    "complaint",
    "Complaints",
    "“Is Reddit down?”, “Teams is unusable”, “cancelled my Netflix subscription”, “Spotify raised prices”.",
  ],
  [
    "need",
    "Unmet needs",
    "“Is there an app to track my sleep?”, “I wish there was a way to …”, “I'd pay for an app that …”.",
  ],
] as const;
const RISING = [
  ["alternative", "Alternatives sought", "Alternative to"],
  ["complaint", "Complaints", "About"],
  ["considering", "Switches considered", "Switch considered"],
] as const;

function IntentsPage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const params = {
    ...asOf,
    scope: search.scope,
    channels: search.channels,
    doc_types: search.doc_types,
    range: search.range,
    min_authors: search.min_authors,
    min_mentions: search.min_mentions,
  };
  const summary = useIntents(params);
  const flows = useIntentFlows(params);
  const rising = useIntentRising({ ...params, kind: search.rising });
  const needs = useIntentNeeds(params);
  const examples = useIntentExamples({
    ...asOf,
    scope: search.scope,
    channels: search.channels,
    doc_types: search.doc_types,
    term: search.term,
    ...(search.comment_kinds.length ? { intent_kinds: search.comment_kinds } : {}),
  });
  const groupChannels = meta.data?.groups[search.scope] ?? [];
  const showComments = (term: string) => {
    set({ term });
    document.getElementById("comments")?.scrollIntoView({ behavior: "smooth" });
  };
  const daily = useMemo(
    () =>
      summary.data &&
      timeSeries(
        {
          form: "stacked",
          daily: true,
          reducedMotion,
          series: KINDS.map(([kind, label], index) => ({
            name: label,
            color: seriesColor(index),
            points: summary.data.daily
              .filter((row) => row.kind === kind)
              .map((row) => [Date.parse(row.time), row.mentions] as [number, number]),
          })).filter((series) => series.points.length),
        },
        tokens,
      ),
    [summary.data, tokens, reducedMotion],
  );
  const risingLabel = RISING.find(([kind]) => kind === search.rising)?.[2] ?? "About";

  return (
    <>
      <PageHeader title="Why people switch">
        Why things are mentioned: who switches from what to what, who thinks about it, what they
        look for instead, what they complain about, and what they wish existed.
      </PageHeader>
      <div className="flex flex-col gap-4">
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
              onChange={(range) => set({ range })}
              options={[
                ["7d", "7 days"],
                ["30d", "30 days"],
                ["90d", "90 days"],
              ]}
            />
          </Field>
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
          <Field label="At least">
            <Segmented
              label="Minimum people"
              value={String(search.min_authors)}
              onChange={(value) => set({ min_authors: Number(value) })}
              options={(["1", "2", "3", "5"] as const).map(
                (n) => [n, n === "1" ? "1 person" : `${n} people`] as const,
              )}
            />
          </Field>
        </Filters>

        <KpiRow>
          {KINDS.map(([kind, label, help]) => (
            <StatTile
              key={kind}
              label={label}
              help={help}
              value={summary.data ? count(summary.data.counts[kind] ?? 0) : "…"}
              hint={
                search.comment_kinds.includes(kind) ? "showing its comments" : "its comments below"
              }
              pressed={search.comment_kinds.includes(kind)}
              onClick={() => {
                const only = search.comment_kinds.length === 1 && search.comment_kinds[0] === kind;
                set({ comment_kinds: only ? [] : [kind], term: "" });
              }}
            />
          ))}
          <StatTile
            label="Counting since"
            value={summary.data?.since ? formatDate(summary.data.since) : "–"}
            help="Intents are found when comments are collected, so there's no history before that."
          />
        </KpiRow>

        <Panel
          title="Who switches from what to what"
          flush
          subtitle="Switches that happened, in this range. Open one for its trend and the comments behind it."
          help="Mentions: comments and posts (each counts once). The other way: mentions of the reverse switch, so you see who's winning. Per 10,000: of all comments and posts here."
        >
          <Loaded query={flows}>
            {(data) => (
              <DataTable
                label="Switching flows"
                rows={data.flows}
                rowKey={(row) => row.term}
                limit={15}
                empty={
                  <EmptyState title="No switches in this range">
                    Switches are rare: about 1 comment in 6,000 has any intent. Try a longer range
                    or a bigger group.
                  </EmptyState>
                }
                columns={[
                  {
                    id: "flow",
                    header: "Switch",
                    cell: (row) => (
                      <TermLink term={row.term} kind="switch" label={`${row.from} → ${row.to}`} />
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
                    id: "other",
                    header: "The other way",
                    numeric: true,
                    sort: (row) => row.other_way,
                    cell: (row) => count(row.other_way),
                  },
                  {
                    id: "balance",
                    header: "Balance",
                    wide: true,
                    help: "This way (teal) against the other way (rust).",
                    cell: (row) => (
                      <SplitBar
                        left={row.mentions}
                        right={row.other_way}
                        label={`${row.mentions} this way, ${row.other_way} the other way`}
                      />
                    ),
                  },
                  {
                    id: "per_10k",
                    header: "Per 10,000",
                    numeric: true,
                    wide: true,
                    sort: (row) => row.per_10k,
                    cell: (row) => perThousand(row.per_10k),
                  },
                  {
                    id: "daily",
                    header: "Per day",
                    wide: true,
                    cell: (row) => (
                      <Sparkline
                        values={data.sparklines[row.term]}
                        width={110}
                        label={`${row.term} per day`}
                      />
                    ),
                  },
                  {
                    id: "comments",
                    header: "",
                    cell: (row) => (
                      <Button variant="link" size="xs" onClick={() => showComments(row.term)}>
                        Comments
                      </Button>
                    ),
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <Panel flush>
          <Tabs value={search.rising} onValueChange={(value) => set({ rising: value })}>
            <div className="overflow-x-auto px-4 pt-1">
              <TabsList variant="line">
                {RISING.map(([kind, label]) => (
                  <TabsTrigger key={kind} value={kind}>
                    {label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
            <TabsContent value={search.rising}>
              <p className="px-4 pt-2 pb-2 text-xs text-ink-muted">
                Rising: the last 7 days (today included) against the 28 days before, the most extra
                mentions first. Ignores the range above.
              </p>
              <Loaded query={rising}>
                {(data) => (
                  <DataTable
                    key={search.rising}
                    label="Rising intents"
                    rows={data.entries}
                    rowKey={(row) => row.term}
                    limit={15}
                    empty={
                      <EmptyState title="Nothing rising here this week">
                        Try fewer minimum people, or a bigger group.
                      </EmptyState>
                    }
                    columns={[
                      {
                        id: "entity",
                        header: risingLabel,
                        cell: (row) => (
                          <TermLink term={row.term} kind={search.rising} label={row.entity} />
                        ),
                      },
                      {
                        id: "mentions",
                        header: "This week",
                        numeric: true,
                        sort: (row) => row.mentions,
                        cell: (row) => (
                          <div>
                            {count(row.mentions)}
                            <div className="text-xs text-ink-muted">
                              {count(row.authors)} people
                            </div>
                          </div>
                        ),
                      },
                      {
                        id: "daily",
                        header: "Last 35 days",
                        wide: true,
                        cell: (row) => (
                          <Sparkline
                            values={data.sparklines[row.term]}
                            width={110}
                            label={`${row.entity} per day`}
                          />
                        ),
                      },
                      {
                        id: "excess",
                        header: "Extra",
                        numeric: true,
                        sort: (row) => row.excess,
                        help: "Mentions above what its share before would give.",
                        cell: (row) => `+${decimal(row.excess, (row.excess ?? 0) >= 10 ? 0 : 1)}`,
                      },
                      {
                        id: "ratio",
                        header: "× usual",
                        numeric: true,
                        sort: (row) => row.times_usual,
                        cell: (row) => times(row.times_usual),
                      },
                      {
                        id: "comments",
                        header: "",
                        cell: (row) => (
                          <Button variant="link" size="xs" onClick={() => showComments(row.term)}>
                            Comments
                          </Button>
                        ),
                      },
                    ]}
                  />
                )}
              </Loaded>
            </TabsContent>
          </Tabs>
        </Panel>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Unmet needs"
            subtitle="The 10 needs mentioned most in each group and in the r/all sample, in this range."
            help="A need is the 2–3 words after “is there an app to …”, “I wish there was a way to …”, “I'd pay for an app that …”."
          >
            <Loaded query={needs}>
              {(rows) =>
                rows.length ? (
                  <NeedGroups rows={rows} />
                ) : (
                  <EmptyState title="No needs in this range" />
                )
              }
            </Loaded>
          </Panel>
          <Panel title="Intents per day" subtitle="Comments and posts with an intent, by kind">
            <Loaded query={summary} height={240}>
              {(data) =>
                data.daily.length && daily ? (
                  <Chart option={daily} height={240} label="Intents per day, by kind" />
                ) : (
                  <EmptyState title="No intents in this range" />
                )
              }
            </Loaded>
          </Panel>
        </div>

        <Panel
          id="comments"
          title="Comments behind the intents"
          flush
          subtitle={
            search.term ? (
              <>
                Showing <span className="term font-medium">{search.term}</span> ·{" "}
                <button
                  type="button"
                  className="text-primary underline"
                  onClick={() => set({ term: "" })}
                >
                  show all
                </button>
              </>
            ) : (
              "The newest first, from the last 48 hours. Pick a kind or a row's comments to narrow it down."
            )
          }
          actions={
            <ToggleGroup
              type="multiple"
              variant="outline"
              size="sm"
              aria-label="Kinds of intents"
              value={search.comment_kinds}
              onValueChange={(comment_kinds) => set({ comment_kinds, term: "" })}
              className="flex-wrap"
            >
              {KINDS.map(([kind, label]) => (
                <ToggleGroupItem key={kind} value={kind} className="px-2 text-xs">
                  {label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          }
        >
          <Loaded query={examples}>
            {(rows) => (
              <Comments
                mentions={rows.slice(0, 50)}
                terms={rows.flatMap((row) =>
                  row.found.map((found) => found.replace(/^[a-z]+: /, "")),
                )}
                found={(index) => rows[index]?.found}
              />
            )}
          </Loaded>
        </Panel>
      </div>
    </>
  );
}

function NeedGroups({ rows }: { rows: Need[] }) {
  const groups = new Map<string, Need[]>();
  for (const row of rows) groups.set(row.group_name, [...(groups.get(row.group_name) ?? []), row]);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {[...groups].map(([group, items]) => (
        <div key={group}>
          <h3 className="mb-1 text-xs font-medium text-ink-muted">{group}</h3>
          <ol className="flex flex-col gap-1.5 text-sm">
            {items.map((item) => (
              <li key={item.term} className="flex items-baseline justify-between gap-2">
                <TermLink term={item.term} kind="need" label={item.need} />
                <span className="text-xs text-ink-muted tabular-nums">{count(item.mentions)}</span>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}
