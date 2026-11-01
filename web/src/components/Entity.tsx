import { Link, useNavigate } from "@tanstack/react-router";
import { CircleAlert, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";
import { useTermSummary } from "@/api/generated/endpoints";
import { useAsOf } from "@/api/hooks";
import { Sparkline } from "@/charts/micro";
import { Badge } from "@/components/ui/badge";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { count, type Strength, strength, times } from "@/lib/format";
import { KIND_LABELS } from "@/lib/kinds";
import { pathPart } from "@/lib/links";
import { searchOf, useAnySearch, withSearch } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const plainClick = (event: MouseEvent) =>
  event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;

/** A term, as everywhere: in mono as the detector stores it. A real link to its page, so
 * middle-click and copy link work; a plain click opens it in the peek instead, and
 * hovering shows its last 7 days (WEB-DASHBOARD.md §6.1). */
export function TermLink({
  term,
  kind,
  label,
  color,
  scope,
}: {
  term: string;
  kind: string;
  label?: string;
  color?: string | undefined;
  scope?: string;
}) {
  const navigate = useNavigate();
  const search = useAnySearch();
  const inScope = scope ?? (typeof search.scope === "string" ? search.scope : undefined);
  return (
    <HoverCard openDelay={400} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Link
          to="/t/$kind/$"
          params={{ kind, _splat: term }}
          search={searchOf(inScope ? { scope: inScope } : {})}
          className="inline-flex max-w-full items-center gap-1.5 rounded-sm font-medium text-ink hover:text-primary hover:underline"
          onClick={(event) => {
            event.stopPropagation();
            if (!plainClick(event)) return;
            event.preventDefault();
            void navigate({
              to: ".",
              search: withSearch({ peek: `${kind}:${term}` }),
              resetScroll: false,
            });
          }}
        >
          {color && (
            <span
              aria-hidden
              className="h-0.5 w-2.5 shrink-0 rounded-full"
              style={{ background: color }}
            />
          )}
          <span className="term truncate">{label ?? term}</span>
        </Link>
      </HoverCardTrigger>
      <HoverCardContent className="w-72 text-sm" align="start">
        <TermCard kind={kind} term={term} scope={inScope ?? "reddit"} />
      </HoverCardContent>
    </HoverCard>
  );
}

function TermCard({ kind, term, scope }: { kind: string; term: string; scope: string }) {
  const asOf = useAsOf();
  const summary = useTermSummary(kind, pathPart(term), { ...asOf, scope });
  const data = summary.data;
  const top = data?.trending[0];
  return (
    <div className="flex flex-col gap-2">
      <div>
        <div className="text-xs text-ink-muted">
          {(KIND_LABELS[kind] ?? kind).replace(/s$/, "")} in {scope}
        </div>
        <div className="term font-medium break-words">{term}</div>
      </div>
      {data ? (
        <>
          <p className="text-ink-secondary">
            {top
              ? `Trending in ${top.scope}: ${times(top.ratio, top.is_new)} its usual share, ${strength(top.score).label}.`
              : "Not trending right now."}
          </p>
          <Sparkline
            values={data.sparkline}
            width={256}
            height={36}
            label={`${term}, mentions per hour, 7 days`}
          />
          <p className="text-xs text-ink-muted">
            {count(data.mentions_7d)} mentions by {count(data.authors_7d)} people in 7 days
          </p>
        </>
      ) : (
        <p className="text-xs text-ink-muted">Loading…</p>
      )}
    </div>
  );
}

/** A platform, group or channel, linking to its page. */
export function ScopeLink({ scope, children }: { scope: string; children?: ReactNode }) {
  return (
    <Link
      to="/s/$"
      params={{ _splat: scope }}
      className="rounded-sm text-ink hover:text-primary hover:underline"
      onClick={(event) => event.stopPropagation()}
    >
      {children ?? scope}
    </Link>
  );
}

/** A story, linking to its page. */
export function EventLink({
  kind,
  term,
  start,
  children,
}: {
  kind: string;
  term: string;
  start: string;
  children?: ReactNode;
}) {
  return (
    <Link
      to="/e/$kind/$start/$"
      params={{ kind, start, _splat: term }}
      className="rounded-sm hover:text-primary hover:underline"
      onClick={(event) => event.stopPropagation()}
    >
      {children ?? term}
    </Link>
  );
}

/** A product of the intents, linking to its page. */
export function ProductLink({ product }: { product: string }) {
  return (
    <Link
      to="/p/$"
      params={{ _splat: product }}
      className="rounded-sm font-medium hover:text-primary hover:underline"
      onClick={(event) => event.stopPropagation()}
    >
      {product}
    </Link>
  );
}

export function KindBadge({ kind }: { kind: string }) {
  if (kind === "word") return null;
  const label = (KIND_LABELS[kind] ?? kind).replace(/s$/, "").toLowerCase();
  return (
    <span className="ml-1.5 rounded-xs bg-surface-sunken px-1 py-px text-[11px] text-ink-muted">
      {label}
    </span>
  );
}

/** A strength as a word with three steps of seq-700 (BRAND.md §8, the trend row). */
export function StrengthWord({ value, title }: { value: Strength; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <span aria-hidden className="flex gap-0.5">
        {[1, 2, 3].map((step) => (
          <span
            key={step}
            className={cn(
              "h-2.5 w-1 rounded-xs",
              step <= value.level ? "bg-seq-700" : "bg-seq-100",
            )}
          />
        ))}
      </span>
      <span className="text-ink-secondary">{value.label}</span>
    </span>
  );
}

const STATUS = {
  good: { icon: CircleCheck, className: "bg-status-good-wash text-status-good-text" },
  warning: { icon: TriangleAlert, className: "bg-status-warning-wash text-status-warning-text" },
  serious: { icon: CircleAlert, className: "bg-status-serious-wash text-status-serious-text" },
  critical: { icon: CircleX, className: "bg-status-critical-wash text-status-critical-text" },
} as const;

/** The system's state, always with an icon and a word (BRAND.md §5.4). */
export function StatusBadge({
  status,
  children,
}: {
  status: keyof typeof STATUS | "neutral";
  children: ReactNode;
}) {
  if (status === "neutral") {
    return (
      <Badge variant="outline" className="font-normal text-ink-secondary">
        {children}
      </Badge>
    );
  }
  const { icon: Icon, className } = STATUS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-medium",
        className,
      )}
    >
      <Icon className="size-3" strokeWidth={2} aria-hidden />
      {children}
    </span>
  );
}

const ALERTS: Record<string, [keyof typeof STATUS | "neutral", string]> = {
  sent: ["good", "Sent"],
  failed: ["critical", "Failed"],
  capped: ["warning", "Daily limit"],
  cooldown: ["neutral", "Cooldown"],
  warmup: ["neutral", "Warming up"],
  skipped: ["neutral", "Skipped"],
  muted: ["neutral", "Muted"],
};

export const ALERT_HELP =
  "What happened to the trends strong enough for an instant alert: sent, failed, daily limit reached (at most 5 a day), cooldown (alerted in the last 72 hours), warming up (less than 3 days of history), skipped (the scope never alerts), muted (a run without notifications).";

export function AlertBadge({ alert }: { alert: string }) {
  if (!alert) return null;
  const [status, label] = ALERTS[alert] ?? ["neutral", alert];
  return <StatusBadge status={status}>{label}</StatusBadge>;
}
