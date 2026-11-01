import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, Compass } from "lucide-react";
import { useMemo } from "react";
import { useExplore, useExploreMentions } from "@/api/generated/endpoints";
import { useAsOf, useMetaData } from "@/api/hooks";
import { Chart, useChartTokens, useReducedMotion } from "@/charts/Chart";
import { BarList } from "@/charts/micro";
import { timeSeries } from "@/charts/options";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { count, perThousand } from "@/lib/format";
import { grafanaLink } from "@/lib/grafana";
import { KIND_LABELS } from "@/lib/kinds";
import { searchOf, useAnySearch, withSearch } from "@/lib/navigation";
import { parsePeek } from "@/lib/search";
import { Comments } from "./Comments";
import { Loaded, Panel } from "./Panel";

/** A term in a side sheet over any page, kept in the url (`peek=kind:term`), so it can be
 * linked and survives a reload (WEB-DASHBOARD.md §6.1). */
export function Peek() {
  const search = useAnySearch();
  const navigate = useNavigate();
  const peek = parsePeek(typeof search.peek === "string" ? search.peek : undefined);
  const close = () =>
    void navigate({
      to: ".",
      search: withSearch({ peek: undefined }),
      resetScroll: false,
    });
  return (
    <Sheet open={peek !== null} onOpenChange={(open) => !open && close()}>
      <SheetContent
        className="w-full gap-0 overflow-y-auto sm:max-w-xl"
        aria-describedby={undefined}
      >
        {peek && (
          <PeekBody
            kind={peek.kind}
            term={peek.term}
            scope={typeof search.scope === "string" ? search.scope : "reddit"}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function PeekBody({ kind, term, scope }: { kind: string; term: string; scope: string }) {
  const asOf = useAsOf();
  const meta = useMetaData();
  const tokens = useChartTokens();
  const reducedMotion = useReducedMotion();
  const params = { ...asOf, terms: [term], scope, range: "7d" };
  const explore = useExplore(params);
  const mentions = useExploreMentions({ ...asOf, terms: [term], scope, range: "2d" });
  const option = useMemo(
    () =>
      explore.data &&
      timeSeries(
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
          reducedMotion,
        },
        tokens,
      ),
    [explore.data, term, tokens, reducedMotion],
  );
  const total = explore.data?.points.reduce((sum, point) => sum + point.mentions, 0) ?? 0;
  return (
    <>
      <SheetHeader className="border-b border-border pb-3">
        <p className="text-xs text-ink-muted">
          {(KIND_LABELS[kind] ?? kind).replace(/s$/, "")} in {scope}
        </p>
        <SheetTitle className="term type-title-lg break-words">{term}</SheetTitle>
        <SheetDescription>
          {explore.data ? `${count(total)} comments and posts in the last 7 days` : "Loading…"}
        </SheetDescription>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" asChild>
            <Link to="/explore" search={searchOf({ terms: [term], range: "7d" })}>
              <Compass className="size-3.5" /> Explore
            </Link>
          </Button>
          {meta.data && (
            <Button size="sm" variant="ghost" asChild>
              <a
                href={grafanaLink(meta.data.grafana_url, "explore", {
                  terms: term,
                  scope,
                  range: "7d",
                })}
                target="_blank"
                rel="noreferrer"
              >
                Pro mode <ArrowUpRight className="size-3.5" />
              </a>
            </Button>
          )}
        </div>
      </SheetHeader>
      <div className="flex flex-col gap-4 p-4">
        <Panel
          title="Share of the conversation"
          subtitle={`Per 1,000 comments and posts in ${scope}, per hour`}
        >
          <Loaded query={explore} height={200}>
            {(data) =>
              data.points.length && option ? (
                <Chart option={option} height={200} label={`${term}, share per hour over 7 days`} />
              ) : (
                <p className="text-sm text-ink-muted">No mentions in the last 7 days.</p>
              )
            }
          </Loaded>
        </Panel>
        <Panel title="Where it's discussed" subtitle="Per 1,000 comments and posts, last 7 days">
          <Loaded query={explore}>
            {(data) =>
              data.where.length ? (
                <BarList
                  rows={[...data.where]
                    .sort((a, b) => (b.per_1000 ?? 0) - (a.per_1000 ?? 0))
                    .slice(0, 8)
                    .map((row) => ({
                      key: row.channel,
                      label: row.channel,
                      value: row.per_1000 ?? 0,
                      note: `${count(row.mentions)} by ${count(row.authors)}`,
                    }))}
                  format={perThousand}
                />
              ) : (
                <p className="text-sm text-ink-muted">Nowhere in this scope.</p>
              )
            }
          </Loaded>
        </Panel>
        <Panel title="Recent comments and posts" subtitle="The last 48 hours" flush>
          <Loaded query={mentions}>
            {(data) => <Comments mentions={data.slice(0, 20)} terms={[term]} />}
          </Loaded>
        </Panel>
      </div>
    </>
  );
}
