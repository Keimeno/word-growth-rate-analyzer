import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useIntentExamples, useProductDetail } from "@/api/generated/endpoints";
import type { ProductDetail } from "@/api/generated/model";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { BarList } from "@/charts/micro";
import { timeSeries } from "@/charts/options";
import { Filters, PageHeader } from "@/components/AppShell";
import { Comments } from "@/components/Comments";
import { ProductLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Field, ScopePicker, Segmented } from "@/components/Pickers";
import { KpiRow, StatTile } from "@/components/Stat";
import { seriesColor } from "@/lib/colors";
import { count } from "@/lib/format";
import { pathPart } from "@/lib/links";
import { useSetSearch } from "@/lib/navigation";
import { productDefaults, productSearch } from "@/lib/search";

export const Route = createFileRoute("/p/$")({
  validateSearch: productSearch,
  search: { middlewares: [stripSearchParams(productDefaults)] },
  component: ProductPage,
});

const KINDS = [
  ["switch", "Switches"],
  ["considering", "Considering a switch"],
  ["alternative", "Alternatives sought"],
  ["complaint", "Complaints"],
] as const;

/** A product as people mention it (WEB-DASHBOARD.md §6.3): who switches to it and away, who
 * considers leaving, complains or looks for something else. The churn radar's report page in
 * waiting. Below 10, counts stay counts. */
function ProductPage() {
  const { _splat: name = "" } = Route.useParams();
  const search = Route.useSearch();
  const set = useSetSearch();
  const meta = useMetaData();
  const asOf = useAsOf();
  const product = useProductDetail(pathPart(name), {
    ...asOf,
    scope: search.scope,
    range: search.range,
  });
  return (
    <>
      <PageHeader title={name}>
        Who switches to it and away, who considers leaving, complains, or looks for something else.
      </PageHeader>
      <div className="flex flex-col gap-4">
        <Filters>
          <ScopePicker meta={meta.data} value={search.scope} onChange={(scope) => set({ scope })} />
          <Field label="Over">
            <Segmented
              label="Range"
              value={search.range}
              onChange={(range) => set({ range })}
              options={[
                ["30d", "30 days"],
                ["90d", "90 days"],
                ["26w", "6 months"],
                ["52w", "1 year"],
              ]}
            />
          </Field>
        </Filters>
        <Loaded query={product} height={300}>
          {(data) => <Product data={data} />}
        </Loaded>
      </div>
    </>
  );
}

function Product({ data }: { data: ProductDetail }) {
  const search = Route.useSearch();
  const set = useSetSearch();
  const asOf = useAsOf();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const term = search.term || data.terms[0] || "";
  const examples = useIntentExamples(
    { ...asOf, scope: search.scope, term },
    { query: { enabled: Boolean(term) } },
  );
  const daily = useMemo(
    () =>
      timeSeries(
        {
          form: "stacked",
          daily: true,
          reducedMotion,
          series: KINDS.map(([kind, label], index) => ({
            name: label,
            color: seriesColor(index),
            points: data.daily
              .filter((row) => row.kind === kind)
              .map((row) => [Date.parse(row.time), row.mentions] as [number, number]),
          })).filter((series) => series.points.length),
        },
        tokens,
      ),
    [data, tokens, reducedMotion],
  );
  const net =
    data.flows_in.reduce((sum, flow) => sum + flow.mentions, 0) -
    data.flows_out.reduce((sum, flow) => sum + flow.mentions, 0);
  return (
    <>
      <KpiRow>
        {KINDS.map(([kind, label]) => (
          <StatTile key={kind} label={label} value={count(data.counts[kind] ?? 0)} />
        ))}
        <StatTile
          label="Net switches"
          value={net > 0 ? `+${count(net)}` : count(net)}
          hint="to it, minus away from it"
        />
      </KpiRow>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Switching to it" subtitle="From where, in mentions">
          {data.flows_in.length ? (
            <BarList
              rows={data.flows_in.map((flow) => ({
                key: flow.product,
                label: <ProductLink product={flow.product} />,
                value: flow.mentions,
                note: `${count(flow.authors)} people`,
              }))}
              onSelect={(product) => set({ term: `${product} → ${data.name}` })}
            />
          ) : (
            <EmptyState title="Nobody switched to it in this range" />
          )}
        </Panel>
        <Panel title="Switching away" subtitle="To where, in mentions">
          {data.flows_out.length ? (
            <BarList
              rows={data.flows_out.map((flow) => ({
                key: flow.product,
                label: <ProductLink product={flow.product} />,
                value: flow.mentions,
                note: `${count(flow.authors)} people`,
              }))}
              onSelect={(product) => set({ term: `${data.name} → ${product}` })}
            />
          ) : (
            <EmptyState title="Nobody switched away in this range" />
          )}
        </Panel>
      </div>
      <Panel title="Per day" subtitle="Mentions per intent kind">
        {data.daily.length ? (
          <Chart option={daily} height={220} label={`${data.name}: intents per day`} />
        ) : (
          <EmptyState title="No intents about it in this range" />
        )}
      </Panel>
      <Panel
        title="Comments"
        flush
        subtitle={
          term ? (
            <>
              The last 48 hours with <span className="term">{term}</span>
            </>
          ) : (
            "The last 48 hours"
          )
        }
      >
        {term ? (
          <Loaded query={examples}>
            {(rows) => (
              <Comments
                mentions={rows.slice(0, 30)}
                terms={[data.name]}
                found={(index) => rows[index]?.found}
              />
            )}
          </Loaded>
        ) : (
          <EmptyState title="No intents to show comments for" />
        )}
      </Panel>
    </>
  );
}
