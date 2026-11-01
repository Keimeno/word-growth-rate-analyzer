import { createFileRoute } from "@tanstack/react-router";
import { usePins, useTermSummary } from "@/api/generated/endpoints";
import type { Pin } from "@/api/generated/model";
import { useAsOf } from "@/api/hooks";
import { Sparkline } from "@/charts/micro";
import { PageHeader } from "@/components/AppShell";
import { KindBadge, ScopeLink, StrengthWord, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { PinButton } from "@/components/Personal";
import { count, formatDate, strength, times } from "@/lib/format";
import { pathPart } from "@/lib/links";

export const Route = createFileRoute("/pinned")({ component: PinnedPage });

/** The terms followed on purpose, each with its last 7 days and whether it trends. */
function PinnedPage() {
  const asOf = useAsOf();
  const pins = usePins(asOf);
  return (
    <>
      <PageHeader title="Pinned">
        Terms you follow on purpose, on every device. Pin a term from its page.
      </PageHeader>
      <Panel flush>
        <Loaded query={pins}>
          {(rows) =>
            rows.length ? (
              <ul className="divide-y divide-border">
                {rows.map((pin) => (
                  <PinnedRow key={`${pin.kind}|${pin.term}`} pin={pin} />
                ))}
              </ul>
            ) : (
              <EmptyState title="Nothing pinned yet">Open a term's page and pick Pin.</EmptyState>
            )
          }
        </Loaded>
      </Panel>
    </>
  );
}

function PinnedRow({ pin }: { pin: Pin }) {
  const asOf = useAsOf();
  const summary = useTermSummary(pin.kind, pathPart(pin.term), {
    ...asOf,
    scope: pin.scope || "reddit",
  });
  const top = summary.data?.trending[0];
  return (
    <li className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_auto_auto] sm:items-center">
      <div className="min-w-0">
        <TermLink term={pin.term} kind={pin.kind} scope={pin.scope || "reddit"} />
        <KindBadge kind={pin.kind} />
        <div className="text-xs text-ink-muted">
          in <ScopeLink scope={pin.scope || "reddit"} /> · pinned {formatDate(pin.pinned_at)}
          {summary.data && ` · ${count(summary.data.mentions_7d)} mentions in 7 days`}
        </div>
      </div>
      <div className="flex items-center gap-3 text-sm">
        {top ? (
          <>
            <span>
              trending in {top.scope}, {times(top.ratio, top.is_new)}
            </span>
            <StrengthWord value={strength(top.score)} />
          </>
        ) : (
          <span className="text-ink-muted">not trending</span>
        )}
        <Sparkline
          values={summary.data?.sparkline}
          width={120}
          label={`${pin.term}, mentions per hour, 7 days`}
        />
      </div>
      <PinButton kind={pin.kind} term={pin.term} scope={pin.scope || "reddit"} />
    </li>
  );
}
